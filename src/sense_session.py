# -*- coding: utf-8 -*-
"""蜘蛛感应（任务书 §7）的**纯逻辑核心**：变化检测 / ROI 选择 / 去重缓存 / 提示调度。

为什么单独一个模块、而且不 import Qt
------------------------------------
§7 要求的是一整条流水线：

    屏幕捕获 → 变化检测/ROI → OCR worker → 词级解析 → 去重缓存 → 短暂高亮/射线 → 词典释义

其中「捕获」和「OCR」都必须待在各自的 Qt 线程里（`pet_window.SenseWorker` 负责），
而**最难验、最容易骗人**的是中间这三件事：

* 静态画面不能无限重复提示同一个词（否则用户看到的是「蜘蛛一直在抽风」）；
* 内容变了要优先检测新内容（视频字幕场景的核心）；
* 缓存必须有上限（否则开一小时内存一直在长）。

这三条全都可以用「假帧 + 注入时钟」测出来，不需要真屏幕、不需要 OCR、不需要网络。
所以它们放在这里，`import numpy` 是唯一依赖。

不承诺的事（§7.3，写进代码注释里免得以后又被「优化」掉）
--------------------------------------------------------
* **不是**「无限扫描 / 零成本」：这是用户开启期间、受频率与延迟预算限制的观察模式；
* 默认**本地处理**：本模块不碰网络，也不接收任何 AI 相关的入参；
* 日志只记**计数与耗时**，绝不记屏幕内容。
"""
from __future__ import annotations

import math
import statistics
import time
from collections import OrderedDict

import numpy as np

# ---------------------------------------------------------------- 状态与默认值

OFF = "off"                 #: 开关关着：不捕获、不 OCR、不起线程
RUNNING = "running"         #: 感应中
PAUSED = "paused"           #: 用户暂停（或超预算自动降频后仍在跑，见 `note`）
ERROR = "error"             #: 连续出错自动暂停，**不会**自己重启

#: 节流初值：**待测的起点，不是性能承诺**（任务书 §7.3 明说 1~2 次/秒是初始值）。
#: 真实开销由 `tools/sense_bench.py` 在本机量出来后回填。
DEFAULT_HZ = 1.0
#: 变化检测网格：4×3 = 12 格。为什么不是更细：格子越细，光标闪烁/视频压缩噪声
#: 越容易被当成「内容变了」，OCR 就被白唤醒；12 格 + 「逐像素绝对差」判据
#: （见 `CELL_DIFF_THRESHOLD`）足够把「一条字幕换了」和「鼠标动了一下」区分开，
#: 实测见 bench。
DEFAULT_COLS, DEFAULT_ROWS = 4, 3
#: 单格「平均绝对差」阈值（0~1 归一化）。低于它视为没变 → 跳过 OCR。
#:
#: ★ 2026-10-18 实测改过这里，别再改回去：原来判据是**每格灰度均值差**，
#: 而 `tools/sense_bench.py` 拿真字幕帧量出来 —— 一行英文字幕整句换掉，
#: 每格均值差只有 **0.0009~0.0026**，低于旧阈值 0.006 → 12 格里 0 格算「变了」
#: → 感应模式对用户真正关心的场景（字幕/正文换行）**根本不触发 OCR**。
#: 均值是「增减抵消」的量：白字换了内容、白字占比几乎没变，均值就不动。
#: 换成逐像素绝对差之后，同一组帧的实测值是 **0.022~0.036**（动的那一行），
#: 没动的行是 **0.0**，±1 灰级噪声是 **0.0039**，鼠标指针划过一格约 **0.0017**
#: —— 0.010 卡在中间：噪声与指针都唤不醒，换行一定会唤醒。
CELL_DIFF_THRESHOLD = 0.010
#: 「变化格数」占整屏格数的比例超过它，就认为整屏都在换 → 走全屏 ROI。
FULL_FRAME_FRACTION = 0.75
#: 同一个词在冷却窗口内最多被提示几次；再多就压掉，直到它**所在 ROI 又发生变化**。
NOTICE_TTL = 60.0
NOTICE_MAX_PER_WORD = 2
#: 缓存上限（条），防止内存无限增长。
ROI_CACHE_MAX = 64
WORD_CACHE_MAX = 512
#: 「待提示」队列的上限：一轮最多读回十几个词，积压到这个数就丢**最旧**的那几个。
#: 理由见 `note_words()` 里的 ★（新内容插到队首，旧的自然排在队尾先被丢掉）。
QUEUE_MAX = 16
#: 「本轮没读完的 ROI」顺延表的上限。超了就丢**最久没人碰**的那块 ——
#: 顺延表存在的意义是「一块内容分几轮读完」，不是「把整屏排队读一遍」：
#: 真桌面上（`tools/sense_shape_probe.py`）一次调用读 30~40 行小字要 1~5 秒，
#: 屏幕上到处有小字时队列会一直长，读不完的代价是「那些行本来也没变」。
DEFER_MAX = 8
#: 连续错误到这个数就自动暂停并提示，**不允许**后台线程无限重启（§7.3）。
MAX_CONSECUTIVE_ERRORS = 3
#: 单轮 OCR 延迟预算：超过就自动降频（先降后提示），见 `_apply_budget`。
BUDGET_MS = 1200.0
MIN_HZ = 0.4
#: 「连最慢的节奏都追不上」的判据：一轮 OCR 比下限频率的**轮间隔**还长
#: （1/0.4 = 2500ms）。到这一步才暂停 —— 不是「一超预算就停」，
#: 那样一次偶发的长图 OCR 就会把模式关掉。
DUTY_LIMIT_MS = 1000.0 / MIN_HZ
#: 降频 / 暂停的判据只看**最近这么几轮**的延迟（不是 40 轮大平均）。
#:
#: ★ 2026-10-18 `tools/sense_bench.py` 实测出来的缺陷：真线程流水线里出现过
#:   一个 ~10s 的冷启动样本，40 轮窗口的平均值被它一直拖着（均 4704ms），
#:   于是阶梯一步踩到下限、再两轮就**自动暂停** —— 用户看到的是
#:   「开启感应十几秒后自己停了，而这台机器其实一整帧只要 1.3s」。
#:   大平均对**孤立尖峰**和**持续追不上**给出同一个答案，这是错的：
#:   前者该继续跑，后者才该停。所以判据换成「近 5 轮的**中位数**」，
#:   `avg_cycle_ms` / `p95_cycle_ms` 保留给显示（§7.4 要报的是全窗口的数）。
RECENT_WINDOW = 5
#: 机器**追得上**时，降下去的频率要能回来（见 `_apply_budget` 第 6 条）。
#: 连续这么多个「在预算内」的轮次才回一步 —— 回速刻意比降速慢，避免抖。
RECOVER_AFTER_ROUNDS = 3
#: 一次回多少倍。0.6 的降速阶梯配 1.6 的回升阶梯，来回不对称：
#: 占着机器要立刻让，回到快节奏要连着几轮证明跟得上。
RECOVER_FACTOR = 1.6
#: 自动暂停最少要有这么多轮样本（§7.3「出错/超预算时自动暂停」的证据门槛）。
#: 两轮就停 = 被「一次慢 + 一次巧」关掉；本机实测那种 10s 尖峰正是这样。
PAUSE_MIN_SAMPLES = 3


class SenseSession:
    """一次「感应开启」期间的调度器。所有时间都走注入的 `clock`，方便测试。"""

    def __init__(self, hz: float = DEFAULT_HZ, cols: int = DEFAULT_COLS,
                 rows: int = DEFAULT_ROWS, mode: str = "cet6", limit: int = 8,
                 exclude_rects=None, clock=None,
                 notice_ttl: float = NOTICE_TTL, budget_ms: float = BUDGET_MS):
        self.hz = max(MIN_HZ, float(hz))
        #: 用户设定的初值（降频只往下走，界面要能区分「我设的就是 0.4」
        #: 和「设的 2.0、被这台机器压到 0.4」）。
        self.hz_start = self.hz
        self.cols, self.rows = int(cols), int(rows)
        self.mode, self.limit = mode, int(limit)
        #: 本程序自己的窗口（桌宠 / 瞄准层 / 结果卡 / 帮助）在**图像像素**里的矩形，
        #: 用来避免「蜘蛛认出自己」→ 无限自我提示（§7.3）。
        self.exclude_rects = list(exclude_rects or [])
        self._clock = clock or (lambda: time.monotonic())
        self.notice_ttl = float(notice_ttl)
        self.budget_ms = float(budget_ms)

        self.state = OFF
        self.note = ""
        #: 最近一轮**实际**跑的引擎与回退说明（由 `SenseWorker` 写）。
        #: 单独两个字段而不是塞进 `note`：`note` 是「降频/出错」的一格显示位，
        #: 引擎回退和降频可能同轮发生，挤在一起就谁都看不清了（§3.2 不许静默）。
        self.engine_id = "rapid"
        self.engine_note = ""
        #: 上一帧的**灰度缩略图**（宽 1280，约 0.9MB，定长一份，不增长）。
        #: 变化检测要逐格算绝对差，必须有它 —— 只存均值会认不出「字幕换了句子」。
        self._prev_gray = None
        self._roi_cache: "OrderedDict[str, dict]" = OrderedDict()
        self._seen_words: "OrderedDict[str, float]" = OrderedDict()
        self._word_counts: dict = {}
        self._queue: list = []           # 待提示的词（稳定顺序）
        self._consecutive_errors = 0
        #: 已在最低频率上、却仍超预算的**连续**轮数（见 `_apply_budget`）。
        self._floor_over_budget = 0
        #: 已经在预算内了、却还低于设定频率的**连续**轮数（回升用的计数器）。
        self._budget_ok = 0

        # ---- 只有计数，没有内容 ----
        self.stats = {"cycles": 0, "skipped_no_change": 0, "ocr_runs": 0,
                      "skipped_blank": 0, "words_in": 0, "notices": 0,
                      "suppressed": 0, "errors": 0, "downshifts": 0,
                      "upshifts": 0,
                      "queue_dropped": 0, "full_frame": 0,
                      #: 被**顺延**到下一轮的行段数（`defer_roi`）与顺延表挤爆后
                      #: 丢掉的最旧块数（`roi_dropped`）。`ocr_runs` 现在是
                      #: 「OCR 调用次数」而不是「轮次数」，这两个数解释了差额。
                      "roi_deferred": 0, "roi_dropped": 0}
        #: 本轮没读完的 ROI → `下一轮该从第几行段接着读`（`defer_roi`/`take_deferred`）。
        #: 只存**键与序号**，不存图像、不存文本。
        self._deferred: "OrderedDict[str, int]" = OrderedDict()
        self.cycle_ms: list = []         # 最近若干轮的 OCR 延迟（滚动窗口）
        self.last_scan_at = None         # 最近一次真正跑了 OCR 的时刻
        self.last_capture_at = None      # 最近一次捕获的时刻
        self.avg_cycle_ms = 0.0
        self.p95_cycle_ms = 0.0
        #: 近 `RECENT_WINDOW` 轮的平均耗时 —— **降频/暂停的判据**（见 `_apply_budget`）
        self.recent_cycle_ms = 0.0

    # ---------------------------------------------------------------- 开关
    def start(self) -> None:
        self.state = RUNNING
        self.note = ""
        self._consecutive_errors = 0
        self._floor_over_budget = 0
        self._budget_ok = 0
        self._deferred.clear()
        # 上一帧基准清空：暂停很久之后内容早变了，不该被当成「没变」。
        self._prev_gray = None

    def pause(self, reason: str = "") -> None:
        if self.state == RUNNING:
            self.state = PAUSED
            self.note = reason

    def resume(self) -> None:
        if self.state in (PAUSED, ERROR):
            self.state = RUNNING
            self.note = ""
            self._consecutive_errors = 0
            self._prev_gray = None
            self._floor_over_budget = 0
            # 暂停期间屏幕内容早就换了，顺延表里那个「读到第几段」没有意义了
            self._deferred.clear()

    def stop(self) -> None:
        """关闭：丢弃所有帧状态与队列，调用方负责停线程与释放捕获。"""
        self.state = OFF
        self._queue.clear()
        self._roi_cache.clear()
        self._seen_words.clear()
        self._word_counts.clear()
        self._deferred.clear()
        self._prev_gray = None
        self._floor_over_budget = 0
        self.note = ""

    @property
    def interval(self) -> float:
        return 1.0 / self.hz

    # ---------------------------------------------------------------- 变化检测
    def cell_diffs(self, prev, cur) -> np.ndarray:
        """两帧灰度缩略图 → 每格**逐像素平均绝对差**（归一化 0~1）。

        为什么不用「每格均值差」：一行英文字幕整句换掉时白字占比几乎不变，
        均值差实测只有 0.0009~0.0026（低于旧阈值 → 感应直接认不出新内容）；
        而平均绝对差同一组帧是 0.022~0.036，没动的格是 0.0。
        开销：一次 `int16` 减法 + 12 次 `.mean()`，实测在几毫秒，
        且只作用在**缩略图**（宽 1280）上，不是全分辨率帧。
        """
        h, w = cur.shape[:2]
        out = np.zeros((self.rows, self.cols), np.float64)
        if prev.shape[:2] != (h, w) or h <= 0 or w <= 0:
            out[:, :] = 1.0                       # 尺寸对不上：视为整屏都变了
            return out
        absolute = np.abs(cur.astype(np.int16) - prev.astype(np.int16))
        for r, c, box in self._cells((h, w)):
            y0, y1, x0, x1 = box
            out[r, c] = float(absolute[y0:y1, x0:x1].mean()) / 255.0
        return out

    def _cells(self, gray_shape):
        """网格几何**唯一**的出处：`[(r, c, (y0, y1, x0, x1)), ...]`。

        检测用缩略图尺寸、裁图也用同一套，所以变化格子和 ROI 框不可能错位；
        最后一行/列吃掉除不尽的余数，保证 12 格拼起来正好是整帧。
        """
        h, w = gray_shape[:2]
        bh, bw = max(1, h // self.rows), max(1, w // self.cols)
        out = []
        for r in range(self.rows):
            y0 = r * bh
            y1 = (r + 1) * bh if r < self.rows - 1 else h
            for c in range(self.cols):
                x0 = c * bw
                x1 = (c + 1) * bw if c < self.cols - 1 else w
                out.append((r, c, (y0, y1, x0, x1)))
        return out

    def _excluded_cells(self, gray_shape, pixel_scale: float = 1.0) -> set:
        """完全落在本程序窗口里的格子 —— 不参与变化判定，也不 OCR。

        ★ `exclude_rects` 是**全分辨率图像像素**（`pet_window._sense_exclude_rects`
          按 DPR 换算），而这里比的是**缩略图**格子（`_thumbnail` 把宽压到 1280）。
          不乘 `pixel_scale` 的话，1.5 倍屏上排除区会被挪到别的地格去：
          「排除自己」等于没做 —— 状态条/词卡里的英文还是会被认成新词，
          §7.3 明令避免的自识别循环照样成立（2026-10-18 接线时发现）。
        """
        h, w = gray_shape[:2]
        scale = float(pixel_scale or 1.0)
        out = set()
        for rect in self.exclude_rects:
            x, y, rw, rh = (float(v) * scale for v in rect)
            if rw <= 0 or rh <= 0:
                continue
            for r, c, (y0, y1, x0, x1) in self._cells((h, w)):
                # 只有「整格都在自己窗口里」才屏蔽：部分重叠的格子还得继续感应，
                # 否则桌宠往屏幕中间一站就瞎了一片。
                if (x <= x0 and x + rw >= x1 and y <= y0 and y + rh >= y1):
                    out.add((r, c))
        return out

    def set_exclude_rects(self, rects) -> None:
        self.exclude_rects = list(rects or [])

    def ingest(self, gray, now=None, pixel_scale: float = 1.0):
        """吃一帧灰度**缩略图**，决定这一轮要不要跑 OCR。

        返回 ``(roi_keys, need_full_frame)``：
          * `([], False)` = 没变化 → 上层**不要**调 OCR（这就是节流的落点）；
          * `(_, True)`  = 变化铺满整屏（滚动/切页/整屏动画）→ 上层送整帧；
          * `(keys, False)` = 只有几块格子动了 → 上层按这些格子裁 ROI 送 OCR。

        ★ 判据是**每格逐像素平均绝对差**，不是「每格均值差」。
        前者能认出「字幕换了一句话」（白字占比几乎没变、均值不动，但像素全换了），
        后者认不出 —— 这个缺陷是 `tools/sense_bench.py` 用真帧量出来的，
        见 `CELL_DIFF_THRESHOLD` 上的注释。代价是多留一份上一轮的缩略图
        （宽 1280 的灰度帧 ≈ 0.9MB，**定长一份**，不随时间增长）。
        """
        now = self._clock() if now is None else now
        self.last_capture_at = now
        if self.state != RUNNING:
            return [], False
        self.stats["cycles"] += 1

        if gray is None or getattr(gray, "size", 0) == 0:
            return [], False

        prev_frame = self._prev_gray
        self._prev_gray = gray
        if prev_frame is None:
            # 第一帧没有参照，只能整帧看一次；这是「开感应」的一次性成本。
            self.stats["full_frame"] += 1
            return [], True
        if prev_frame.shape[:2] != gray.shape[:2]:
            # 换屏 / 改 DPI / 窗口拖到另一块屏 → 尺寸都变了，逐格没法比，整帧重来
            self.stats["full_frame"] += 1
            return [], True
        if np.array_equal(prev_frame, gray):
            # 逐像素一模一样 → 连绝对差都不用算（省下三次 int16 大数组）。
            # ★ 这里**曾经**用「每格均值量化后的 md5」当快判，那是错的：
            #   12 个格子均值、量化到 32 级，「换了一句话」的 0.1/255 亮度差
            #   会被量化吞掉 → 哈希相同 → 又被判成「没变」，等于把刚修的
            #   灵敏度缺陷从后门放回来。快判只能是**精确**的像素比较。
            self.stats["skipped_no_change"] += 1
            return [], False

        blocked = self._excluded_cells(gray.shape, pixel_scale)
        diffs = self.cell_diffs(prev_frame, gray)
        changed = [(r, c) for r, c, _box in self._cells(gray.shape)
                   if (r, c) not in blocked and diffs[r, c] >= CELL_DIFF_THRESHOLD]
        if not changed:
            self.stats["skipped_no_change"] += 1
            return [], False
        if len(changed) / float(self.rows * self.cols) >= FULL_FRAME_FRACTION:
            self.stats["full_frame"] += 1
            return [], True
        return ["r%dc%d" % (r, c) for (r, c) in changed], False

    def roi_box(self, roi_key: str, image_size) -> tuple:
        """把 `r2c3` 这种格子键还原成图像像素框（上层裁图用）。

        ★ 格子几何从 `_cells()` 来 —— 和「判定哪格变了」是同一套坐标。
        以前两处各算各的（一边整除、一边带余数），最后一行/列的 ROI 会差几像素；
        横向多留 8%、纵向多留 20%（字通常比格子高），是把边界上的词也捞进来。
        """
        w, h = image_size
        try:
            r_str, c_str = roi_key[1:].split("c")
            r, c = int(r_str), int(c_str)
        except Exception:                   # noqa: BLE001
            return (0, 0, w, h)
        for rr, cc, (y0, y1, x0, x1) in self._cells((h, w)):
            if (rr, cc) != (r, c):
                continue
            pad_x, pad_y = int((x1 - x0) * 0.08), int((y1 - y0) * 0.20)
            left, top = max(0, x0 - pad_x), max(0, y0 - pad_y)
            right, bottom = min(w, x1 + pad_x), min(h, y1 + pad_y)
            return (left, top, right - left, bottom - top)
        return (0, 0, w, h)                 # 越界的格子键：退化成整帧，而不是崩

    # ---------------------------------------------------------------- 去重 + 排期
    def note_words(self, roi_key: str, words, elapsed_ms: float,
                   now=None) -> list:
        """一轮 OCR 回来后登记结果，返回**这一轮新出现的**候选词。

        `words` 是词卡 dict 列表（`surface/lemma/screen_pos/screen_box`）。
        同一个 ROI 的同一份内容在 TTL 窗口里只提示有限次（`NOTICE_MAX_PER_WORD`），
        再多就压掉 —— §7.4「静态画面不会重复无限提示同一词」就是这条。

        ★ 这里登记的耗时是**该 ROI 的 OCR 延迟**，超预算会自动降频（§7.3）。
        """
        now = self._clock() if now is None else now
        self.last_scan_at = now
        self.stats["ocr_runs"] += 1
        self.stats["words_in"] += len(words or [])
        self._record_latency(float(elapsed_ms or 0.0))

        payload = tuple(sorted((w.get("surface") or "").lower() for w in (words or [])))
        entry = self._roi_cache.get(roi_key)
        fresh = []
        if entry is not None and entry["payload"] == payload:
            # 内容没变（同一块字幕又扫到一遍）→ 只续期，不出新候选。
            entry["at"] = now
            self._roi_cache.move_to_end(roi_key)
        else:
            self._roi_cache[roi_key] = {"payload": payload, "at": now}
            while len(self._roi_cache) > ROI_CACHE_MAX:
                self._roi_cache.popitem(last=False)
            fresh = list(words or [])

        queued = []
        for item in fresh:
            key = self._word_key(item)
            if not key:
                continue
            last = self._seen_words.get(key, None)
            count = self._word_counts.get(key, 0)
            if last is not None and now - last < self.notice_ttl \
                    and count >= NOTICE_MAX_PER_WORD:
                self.stats["suppressed"] += 1
                continue
            self._seen_words[key] = now
            self._word_counts[key] = count + 1
            while len(self._seen_words) > WORD_CACHE_MAX:
                # `_roi_pop` 返回**单个键**（OrderedDict 的第一个 = 最旧）。
                # 这里以前写成 `old_key, _ = ...` 解包 → ValueError，
                # 而它只在缓存挤满（512 个词）时才走到，测试没覆盖到就是漏网。
                old_key = self._roi_pop(self._seen_words)
                self._word_counts.pop(old_key, None)
            queued.append(item)
        # 稳定顺序：按阅读顺序（y 再 x）。§7.2 要「目标循环顺序稳定」。
        queued.sort(key=lambda it: ((it.get("screen_pos") or (0, 0))[1] // 24,
                                    (it.get("screen_pos") or (0, 0))[0]))
        # ★ 新内容**插到队首**，不是排队尾。§7.3 明写「优先新出现的内容」，
        #   而真桌面 e2e（`dist/sense/coord_probe.log`）量到过反面：
        #   开感应的第一帧没有参照 → 走整帧，在本机读了 **24 个词、19073ms**，
        #   这期间测试才把字幕窗口放出来；字幕那轮 ROI 只读回 14 个词，
        #   排在 24 个后面 → 一轮只闪一个、降频后 2.5s 一轮，
        #   等了 30 秒闪出来的 8 个**全是开机前就在屏幕上的旧内容**，
        #   新出现的那句字幕一个都没轮到。FIFO 在「旧内容一大堆 + 新内容一小撮」
        #   这种真实桌面上等于把「新」挤没了。
        #   队尾那些陈旧项本来就快过期（`drop_expired` 按 TTL 清），
        #   所以丢掉它们的代价最低、留住新词的代价为零。
        fresh_queue = [it for it in queued if it not in self._queue]
        if fresh_queue:
            self._queue[0:0] = fresh_queue
            if len(self._queue) > QUEUE_MAX:
                # 只从**队尾**收（队尾 = 最旧），新内容的顺序不受影响。
                self.stats["queue_dropped"] = (
                    self.stats.get("queue_dropped", 0)
                    + len(self._queue) - QUEUE_MAX)
                del self._queue[QUEUE_MAX:]
        return queued

    @staticmethod
    def _roi_pop(cache: "OrderedDict"):
        key = next(iter(cache))
        cache.pop(key, None)
        return key

    @staticmethod
    def _word_key(item) -> str:
        surface = (item.get("surface") or item.get("lemma") or "").strip().lower()
        if not surface:
            return ""
        pos = item.get("screen_pos") or (0, 0)
        # 位置粗分桶（±32px）：同一句话里同一个词出现两次算两个目标，
        # 但同一块字幕刷新后位置没动就不算「新目标」。
        return "%s@%d,%d" % (surface, round(pos[0] / 32.0), round(pos[1] / 32.0))

    # ---------------------------------------------------------------- 提示调度
    def next_notice(self, now=None):
        """取下一个要提示的词；没有就返回 None（腿**不参与**，§7.2）。"""
        now = self._clock() if now is None else now
        # 先清陈旧目标：队列里躺着一分钟前的词，闪出来就是「提示了一个已经
        # 不在屏幕上的位置」，比不提示更误导人。
        self.drop_expired(now=now)
        while self._queue:
            item = self._queue.pop(0)
            key = self._word_key(item)
            last = self._seen_words.get(key)
            if last is None:               # 缓存被挤掉了，视为过期
                continue
            self.stats["notices"] += 1
            return item
        return None

    def pending_notices(self) -> int:
        """还有几个词排在「待提示」里（给日志/状态看，不暴露内容）。"""
        return len(self._queue)

    def drop_expired(self, now=None) -> int:
        """清掉冷却期已过的提示项，防止队列里堆着一堆陈旧目标。"""
        now = self._clock() if now is None else now
        before = len(self._queue)
        self._queue = [it for it in self._queue
                       if now - (self._seen_words.get(self._word_key(it)) or -1e9)
                       <= self.notice_ttl]
        return before - len(self._queue)

    # ---------------------------------------------------------------- 错误与预算
    def note_error(self, reason: str) -> None:
        """后台线程报错就调这里。连续 N 次 → 自动暂停，**不会自己重启**（§7.3）。

        `reason` 只放异常类型/文案，不放屏幕内容。
        """
        self.stats["errors"] += 1
        self._consecutive_errors += 1
        self.note = reason
        if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            self.state = ERROR

    def note_success(self) -> None:
        self._consecutive_errors = 0

    def defer_roi(self, roi_key: str, band_index: int) -> None:
        """本轮没读完的那块 ROI，记下「下一轮从第 `band_index` 行段接着读」。

        ★ 为什么需要它（2026-10-18 真桌面实测，`tools/sense_shape_probe.py`）：
          一次 OCR 调用的耗时几乎正比于**这一段里有几行字**，不是面积 ——
              505x1970（37 行小字）→ 1254ms（热的）/ 4657ms（冷的）
              498x460 （10 行）    → 1541ms
              1600x933（整帧切三条之一，96 行）→ 4415ms
          所以 `SenseWorker` 把一块 ROI 按行切成几段、一轮只跑其中几段。
          切段本身没问题，问题是**剩下的段去哪了**：没有顺延表，
          它们就永远读不到 —— 那一块屏幕的格子在 `_prev_gray` 里已经是
          「看过」的状态，画面不再变就再也不会唤醒 OCR，等于静默漏词。
          有了顺延表，一块内容分几轮读完，每轮的花费都留在预算里。
        """
        if self.state != RUNNING:
            return
        prev = self._deferred.get(roi_key)
        self._deferred[roi_key] = band_index if prev is None else max(prev,
                                                                      band_index)
        self._deferred.move_to_end(roi_key)
        self.stats["roi_deferred"] += 1
        while len(self._deferred) > DEFER_MAX:
            old = next(iter(self._deferred))
            self._deferred.pop(old, None)
            self.stats["roi_dropped"] += 1

    def take_deferred(self) -> list:
        """取出并清空顺延表，返回 `[(roi_key, band_index)]`（按记下的先后顺序）。"""
        out = list(self._deferred.items())
        self._deferred.clear()
        return out

    def pending_deferred(self) -> int:
        """还有几块 ROI 排着「下一轮接着读」（给日志/状态用，不含内容）。"""
        return len(self._deferred)

    def note_blank_crop(self) -> None:
        """登记「这块 ROI 是一片纯色，没进 OCR」（`SenseWorker._is_blank`）。

        单独一个计数有两个用处：① §7.4 要「跑了多少轮 vs 为什么没跑」的分解，
        ② 万一阈值调错了（把低对比正文当空白），这里会立刻看出
        「skipped_blank 很多而 ocr_runs 几乎不动」—— 没有这个数就是静默漏词。
        """
        self.stats["skipped_blank"] += 1

    def note_engine(self, engine_id: str, note: str = "") -> None:
        """登记「这一轮到底用哪个引擎跑的」（`SenseWorker` 每轮调）。

        发生回退时状态条必须写出来 —— 「感应中 · 本地识别」下面挂着
        「本轮已回退 RapidOCR：…」才是诚实的显示（§3.2）。
        """
        self.engine_id = engine_id or "rapid"
        self.engine_note = note or ""

    def _record_latency(self, ms: float) -> None:
        self.cycle_ms.append(ms)
        if len(self.cycle_ms) > 40:
            self.cycle_ms.pop(0)
        if self.cycle_ms:
            self.avg_cycle_ms = round(sum(self.cycle_ms) / len(self.cycle_ms), 1)
            ordered = sorted(self.cycle_ms)
            index = max(0, min(len(ordered) - 1,
                               int(math.ceil(0.95 * len(ordered))) - 1))
            self.p95_cycle_ms = round(ordered[index], 1)
        # ★ 判据用的窗口（近 `RECENT_WINDOW` 轮的**中位数**）。
        #   中位数而不是平均值：平均值会被一次孤立尖峰长期顶高（见 `RECENT_WINDOW`
        #   那条注释里实测到的「一次 10s → 模式被自动暂停」）。这里刻意不
        #   四舍五入，因为要和 `DUTY_LIMIT_MS` 比大小，先舍后比会在边界上
        #   差出半个百分点（实测踩过：窗口里全是 3200ms 时，显示值让判定
        #   跳过了暂停分支）。
        recent = self.cycle_ms[-RECENT_WINDOW:]
        self.recent_cycle_ms = statistics.median(recent) if recent else 0.0
        self._apply_budget()

    def _apply_budget(self) -> None:
        """单轮延迟超预算 → 先降频，降到下限还追不上才暂停（§7.3 / §7.4）。

        四个坑都踩过，所以这段写得啰嗦：

        1. **不能**一超预算就停：一次偶发的长图 OCR 就会关掉模式；
        2. **不能**死守频率：那正是「把用户机器占满」的做法；
        3. 原来用 `target = 1000/平均延迟 × 0.75` 一步到位，结果**卡死在半路**：
           实测本机整帧 OCR 平均 1503ms、预算 1200ms → 目标频率正好算出 0.5，
           于是既不会再降（`target < hz` 不成立）、也够不到下限 0.4（暂停分支
           进不去）—— 状态条挂着「已降到 0.5 次/秒」，机器却一直在超预算跑。
           现在改成「每轮最多降 40%」的阶梯，一定会走到下限或预算之内。
        4. 判据的**统计口径**：用 40 轮大平均时，一个孤立尖峰（本机实测那次
           ~10s 的空白整帧）会把平均值长期顶在预算外，两轮就触发自动暂停；
           反过来真的「连最慢节奏都追不上」时，前面的快轮又把它稀释掉、迟迟不暂停。
           两头都错。现在只看 `recent_cycle_ms`（近 5 轮的**中位数**）：
           尖峰进不了中位数，持续追不上会让中位数立刻抬起来。
        5. 暂停还要再多一个证据门槛：至少 3 轮样本。两轮就停等于被
           「一次慢 + 一次巧」关掉，而 §7.3 要的是「这台机器真的跑不动」才停。
        6. ★ 阶梯**要能往上回**（2026-10-18 实测加的行为）：本机开感应的第一帧
           没有参照 → 走整帧，`tools/sense_coord_probe.py` 量到 **18966ms**，
           那一个样本就把阶梯一路踩到下限 0.4 次/秒，而之后每轮（收紧后的 ROI）
           其实只用 0.3~0.9 秒 —— 跟得上，却永远停在 0.4。只降不升的模式
           等于「一次尖峰判你机器不行，判期无限长」，用户看到的是字幕闪得越来越慢。
           所以现在改成：连续 `RECOVER_AFTER_ROUNDS` 轮都在预算内，就往上回一步
           （每轮最多 ×1.6，回到 `hz_start` 为止）。**回速比降速慢**是故意的：
           降速要果断（占着机器），回速要犹豫（来回抖比停在低频更难看）。
        """
        recent = self.recent_cycle_ms
        if recent <= self.budget_ms:
            self._floor_over_budget = 0
            if self.hz < self.hz_start - 1e-9:
                # 追得上 → 攒够连续轮数就回一步（见上面第 6 条）
                self._budget_ok += 1
                if self._budget_ok >= RECOVER_AFTER_ROUNDS:
                    self._budget_ok = 0
                    self.hz = min(self.hz_start, self.hz * RECOVER_FACTOR)
                    self.stats["upshifts"] += 1
                    self.note = "近 %d 轮中位 %.0fms 在预算内，已回到 %.1f 次/秒" % (
                        min(len(self.cycle_ms), RECENT_WINDOW), recent, self.hz)
            return
        self._budget_ok = 0
        target = max(MIN_HZ, min(self.hz * 0.6, 1000.0 / recent * 0.75))
        if target < self.hz - 1e-9:
            self.hz = target
            self.stats["downshifts"] += 1
            self._floor_over_budget = 0
            self.note = "近 %d 轮中位 %.0fms 超预算，已降到 %.1f 次/秒" % (
                min(len(self.cycle_ms), RECENT_WINDOW), recent, self.hz)
            return
        # 已经踩在下限频率上了。★「追不上」的计数只算**真的追不上**的轮
        # （中位数 ≥ 下限频率的轮间隔）：否则「1500ms、比 2500ms 的间隔快」这种
        # 完全跟得上的超预算轮会一直累加，等真出现一次 3200ms 时当场就暂停，
        # 把「连着两轮追不上才停」这条保护变成「攒够 30 轮后被一次尖峰关掉」。
        cannot_keep_up = (recent >= DUTY_LIMIT_MS
                          and len(self.cycle_ms) >= PAUSE_MIN_SAMPLES)
        if cannot_keep_up:
            self._floor_over_budget += 1
        else:
            self._floor_over_budget = 0
        if self._floor_over_budget >= 2:
            self.state = PAUSED
            self.note = ("已到最低频率 %.1f 次/秒，近 %d 轮中位仍 %.0fms（比一轮的间隔"
                         "还长），这台机器跟不上，已自动暂停" % (
                             self.hz, min(len(self.cycle_ms), RECENT_WINDOW), recent))
        elif recent >= DUTY_LIMIT_MS:
            self.note = ("已到最低频率 %.1f 次/秒，近 %d 轮中位 %.0fms 比轮间隔还长"
                         "（连着两轮这样就停掉感应）" % (
                             self.hz, min(len(self.cycle_ms), RECENT_WINDOW), recent))
        else:
            self.note = ("已到最低频率 %.1f 次/秒，近 %d 轮中位 %.0fms 仍超预算 %.0fms" % (
                self.hz, min(len(self.cycle_ms), RECENT_WINDOW), recent,
                self.budget_ms))

    # ---------------------------------------------------------------- 状态展示
    def status_text(self, now=None) -> str:
        """§7.3：要能看见「感应中 · 本地识别 · 最近扫描时间」。

        这里只输出**模式与计数**，不含任何被识别到的文本。
        """
        now = self._clock() if now is None else now
        label = {OFF: "未开启", RUNNING: "感应中", PAUSED: "已暂停",
                 ERROR: "出错已暂停"}[self.state]
        tail = ""
        if self.last_scan_at is None:
            tail = "尚未扫描"
        else:
            tail = "最近扫描 %.0fs 前" % max(0.0, now - self.last_scan_at)
        base = "%s · 本地识别 · %s · %.1f 次/秒" % (label, tail, self.hz)
        # 引擎只在「不是默认那个」或「发生了回退」时才写进状态条 ——
        # 一直挂着「RapidOCR」是噪声，出事时不写才是隐瞒。
        if self.engine_note or self.engine_id not in ("rapid", "", None):
            base += " · %s" % (self.engine_note or self.engine_id)
        if self.note:
            base += " · %s" % self.note
        return base

    def perf(self) -> dict:
        """给「查看性能/错误信息」入口用（§7.3）。全是计数与耗时，无内容。"""
        return {"state": self.state, "hz": round(self.hz, 2),
                "hz_start": round(self.hz_start, 2),
                "grid": "%dx%d" % (self.cols, self.rows),
                "engine": self.engine_id, "engine_note": self.engine_note,
                "last_scan_at": self.last_scan_at,
                "avg_cycle_ms": self.avg_cycle_ms,
                "recent_cycle_ms": round(self.recent_cycle_ms, 1),
                "p95_cycle_ms": self.p95_cycle_ms,
                #: 顺延表与待提示队列的**长度**（不含内容）：状态条/报表要能看出
                #: 「这块内容还没读完，排在下一轮」和「读完了但排队等闪」是两件事
                "deferred": self.pending_deferred(),
                "pending_notices": len(self._queue),
                "note": self.note, **self.stats}
