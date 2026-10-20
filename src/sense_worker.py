# -*- coding: utf-8 -*-
"""蜘蛛感应的后台线程（任务书 §7.1 的「屏幕捕获 → 变化检测/ROI → OCR worker」）。

线程边界（§7.3 硬性要求，写在这里免得以后被「顺手」改回去）
----------------------------------------------------------
* **捕获必须在 GUI 线程**：`QScreen.grabWindow()` / `QPixmap` 不是线程安全的，
  子线程碰它实测就是 exit 127 级别的硬崩（`OcrWorker` 那条注释是同一个坑）；
* 所以主线程只做两件事：抓一帧、`QImage → ndarray`（也属于 GUI 线程操作），
  然后把 **ndarray** 交给这里；
* 这里（子线程）做：缩略图、变化检测、裁 ROI、OCR、词典挑词、坐标换算、调度；
* 回主线程只通过 Qt Signal（`queued connection` 自动跨线程），
  不在子线程里建窗口、不碰 widget。

丢帧而不是排队（这是「节流」的另一半）
--------------------------------------
主线程 `submit()` 只留**最新一帧**：这一帧还没处理完就来了一帧新的，
旧的直接丢。理由是感应的语义是「现在屏幕上有什么」，
处理一帧 2 秒前的画面没有任何价值，排队只会把延迟越堆越高，
最后表现成「蜘蛛在提示我三秒前的字幕」。丢掉的帧数记在 `dropped`，如实上报。
"""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QThread, Signal

from sense_session import SenseSession

#: 一轮最多处理几个 ROI 格子。**配合 `_roi_boxes` 的并集策略**看：
#: 挨在一起的格子并成一次 OCR，所以这个数放大到 6 也不会多出几次调用；
#: 真正决定成本的是「并起来铺得开不开」（`MERGE_SLACK`），铺不开就退回整帧。
#: 从 3 提到 6 是因为实测：一屏字幕换行会同时点亮底部 4 格，
#: 卡在 3 就把右边那格**永远漏掉**（内容认不出来，比慢更糟）。
MAX_ROIS_PER_CYCLE = 6
#: 变化检测用的缩略图最大宽度（像素）。再大的屏先等比缩到这里，
#: 网格均值和哈希的开销就与屏幕分辨率解耦了。
THUMB_WIDTH = 1280
#: 空转时的轮询间隔（毫秒）：没有帧就当 20ms 睡一次，比 1ms 省 CPU，
#: 又比 100ms 响应快（真正的扫描节奏由 `SenseSession.hz` 决定）。
POLL_MS = 20


class SenseWorker(QThread):
    """感应流水线的工作线程。生命周期跟着「感应开关」走，不做常驻服务。"""

    #: 一个要被提示的词（含 `screen_pos` / `screen_box`，逻辑像素屏幕坐标）
    notice = Signal(dict)
    #: 出错 / 降频 / 自动暂停的说明（只含异常类型与计数，不含屏幕内容）
    fault = Signal(str)
    #: 每轮的性能数据（`perf()` 的快照），给「查看性能/错误信息」入口用
    perf = Signal(dict)

    def __init__(self, session: SenseSession, lexicon, parent=None,
                 min_conf: float = 0.0, mode: str = "cet6", limit: int = 8,
                 skip_stopwords: bool = True):
        super().__init__(parent)
        self.session = session
        self.lexicon = lexicon
        self.min_conf = float(min_conf)
        self.mode = mode
        self.limit = int(limit)
        self.skip_stopwords = bool(skip_stopwords)

        self._frame = None            # (ndarray RGB, origin(x,y), dpr, stamp)
        self._stop = False
        self.dropped = 0              # 处理不过来时被丢掉的帧数
        self.capture_ms = 0.0         # 最近一帧「主线程捕获+转换」的耗时（由 submit 带进来）
        #: 引擎预热的一次性耗时（**不**进延迟预算，见 `_warm_engine`）
        self.warmup_ms = 0.0
        #: 上一次 `perf` 信号里的会话状态，用来判断「状态变了必须让界面知道」
        self._last_perf_state = None
        #: 最近一轮**实际**跑的引擎（不是界面期望值）。回退时这里和
        #: `engine_note` 一起进状态条，「感应中 · 本地识别」后面能看到真话。
        self.engine_id = "rapid"
        self.engine_note = ""
        #: ROI 收紧（`_tighten_bands`）发生了几次、一共剪掉了多少行/列，供 bench/报表量
        self.trim_count = 0
        self.trimmed_px = 0.0
        self.trimmed_cols = 0.0
        #: 一共喂进 OCR 的**行段**数、其中「本轮没读完、顺延到下一轮」的段与块各几次
        self.band_count = 0
        self.band_deferred = 0
        self.round_deferred = 0
        #: 一轮 OCR 的时间预算（默认跟会话的延迟预算一致，用户调小预算这里也跟着小）
        self.round_budget_ms = float(min(self.ROUND_OCR_BUDGET_MS,
                                         float(session.budget_ms)))

    # ---------------------------------------------------------------- 主线程侧
    def submit(self, array, origin, dpr: float, capture_ms: float = 0.0) -> None:
        """主线程把一帧塞进来。**只留最新的一帧**，处理不完的就丢（见模块注释）。"""
        if array is None:
            return
        if self._frame is not None:
            self.dropped += 1
        self.capture_ms = float(capture_ms or 0.0)
        self._frame = (array, (float(origin[0]), float(origin[1])),
                       float(dpr or 1.0), time.monotonic())

    def stop_sense(self) -> None:
        """关闭感应：置停标志 + 等线程真退出（调用方随后 `wait()`）。"""
        self._stop = True
        self._frame = None

    # ---------------------------------------------------------------- 子线程侧
    def run(self) -> None:
        import cv2                                       # noqa: WPS433
        self._warm_engine()
        while not self._stop:
            frame = self._frame
            if frame is None:
                self.msleep(POLL_MS)
                continue
            # 取走即清空：这一帧处理期间新到的帧会覆盖 `_frame`，不会被漏掉
            self._frame = None
            array, origin, dpr, _stamp = frame
            try:
                gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
                thumb, scale = _thumbnail(gray, cv2)
                self.process(thumb, scale, array, origin, dpr)
            except Exception as error:                   # noqa: BLE001
                self.handle_error(error)
        self._frame = None

    def _warm_engine(self) -> None:
        """线程一起来先把 OCR 引擎落到内存里，耗时**不进**延迟预算。

        为什么必须在这里、而不是指望 `main.py` 的启动预热：
        预热线程和感应的第一个 ROI 之间没有先后保证，用户「开桌面 → 立刻开感应」
        时第一个真帧就会去撞 `RapidOCR()` 构造（实测模型加载那一口 1~10s）。
        那笔一次性开销记进 `cycle_ms`，`SenseSession` 看到的是
        「这台机器单轮 10 秒」→ 降频、暂停 —— **把加载成本误判成机器跟不上**，
        是 §7.3「自动暂停」最不该出现的一种触发。所以先在这里把它花掉，
        并且只记一个 `warmup_ms` 供 bench / 状态显示用。
        """
        started = time.time()
        try:
            from ocr_engine import OcrEngine             # noqa: WPS433
            OcrEngine.warmup()
        except Exception as error:                       # noqa: BLE001
            # 预热失败**不算错**：真正的识别会自己报错并计入 `note_error`，
            # 这里提前判定会让「引擎装了但这次构造失败」变成静默暂停。
            self.engine_note = "OCR 预热失败：%s" % type(error).__name__
        self.warmup_ms = round((time.time() - started) * 1000.0, 1)

    def handle_error(self, error: BaseException) -> None:
        """异常 → 会话计数 + 把原因广播出去；到上限就停线程（**不重启**，§7.3）。

        单独抽成方法有两个理由：
          1. `run()` 的 except 里那串逻辑（截断文案、判断是否自杀）是有分支的，
             测试要能直接踩到它，而不是靠起线程、喂十二帧坏帧去间接覆盖；
          2. 只报异常类型与截断后的文案，**不报屏幕内容** —— 这条隐私边界
             写在一个方法里比写在循环里更容易被看清。
        """
        self.session.note_error("%s: %s" % (type(error).__name__,
                                            str(error)[:160]))
        self.fault.emit(self.session.note)
        if self.session.state == "error":
            # 连续 N 次崩 → 会话已经把自己置成 error 了；
            # 这里**不重启、不重试**，等用户手动「继续」。
            self._stop = True

    def process(self, thumb, scale: float, array, origin, dpr: float,
                now: float = None) -> None:
        """一帧的处理：变化检测 → ROI → 按行段切 → OCR → 词典 → 调度 → 发提示。

        拆成方法是为了让测试能喂假帧（`test_sense_worker` 直接调这里，
        不起线程、不抓屏幕）。`now` 也允许注入，测试里才能控制 TTL。

        ★ 一轮的 OCR 用量被两道闸门夹住：
            1. 每块 ROI 最多 `MAX_BANDS_PER_ROI` 段（切出来的段读不完就顺延）；
            2. 本轮累计 OCR 时间超过 `round_budget_ms` 就不再开新块，整块顺延。
          第二道是关键：真桌面上「一块」可以是 37 行小字、4~19 秒
          （`tools/sense_shape_probe.py` / `dist/sense/coord_probe3.log`），
          以前的代码把 `MAX_ROIS_PER_CYCLE` 块全跑完才收工，于是
          **「机器慢」被记成「单轮 9 秒」→ 降频到下限 → 两轮后自动暂停**，
          用户看到的是感应开十几秒就自己停了。现在一轮只花预算内的钱，
          读不完的下一轮接着读（`SenseSession.defer_roi`），不静默丢。
        """
        now = time.monotonic() if now is None else float(now)
        # ---- 1. 节流判定：没变化就不 OCR（这是「1~2 次/秒」真正的省点）----
        # `now` 用 `time.monotonic()`，和 `SenseSession` 默认时钟同一个基准，
        # 所以冷却窗口、提示时刻、延迟预算都算在同一根时间轴上。
        roi_keys, full_frame = self.session.ingest(thumb, now=now,
                                                   pixel_scale=scale)
        if self.session.state != "running":
            self._emit_perf_if_changed()
            return

        h, w = thumb.shape[:2]
        full_h, full_w = array.shape[:2]
        # ---- 2. 要跑的块：整屏变化就整帧，否则把变化的格子**并成一块**裁。
        #      再挂上「上一轮没读完、这轮接着读」的那些块（顺延表）。----
        #      ★ 整帧那一轮现在**也**走行段切（`_tighten_bands`）：以前整帧不收紧，
        #      理由是「整屏都在换时没有哪一行有字可赌」，但实测整帧一次 13846~18966ms
        #      （`dist/sense/card_probe.log`），这台机器上等于一轮就把预算花光、
        #      还把上一轮的降频判据顶坏。切段之后整帧也只是一轮读 ≤4 段、几百毫秒，
        #      剩下的段顺延 —— 读得完，只是分几轮。
        boxes = []
        if full_frame:
            boxes.append(("full", 0.0, 0.0, float(full_w), float(full_h), 0))
        elif roi_keys:
            boxes = [(k, float(x), float(y), float(bw), float(bh), 0)
                     for (k, x, y, bw, bh)
                     in self._roi_boxes(roi_keys, (w, h), scale,
                                        (full_w, full_h))]
        if not full_frame:
            have = set(b[0] for b in boxes)
            for key, cursor in self.session.take_deferred():
                if key in have:
                    continue          # 这块自己又变了：本轮从头读，不用旧 cursor
                box = self._box_for_key(key, (w, h), scale, (full_w, full_h))
                if box is not None:
                    boxes.append((box[0], box[1], box[2], box[3], box[4],
                                  int(cursor)))
        if boxes:
            spent = 0.0
            for index, (key, x, y, bw, bh, cursor) in enumerate(boxes):
                if self._stop or self.session.state != "running":
                    # ★ 本轮被预算/出错**中途**停了：也必须把状态发回主线程，
                    #   否则界面还挂着「感应中」，而会话已经 `paused` 了 ——
                    #   这个不一致是 `tools/sense_bench.py` 量出来的：
                    #   一个 ~10s 的尖峰让模式在一轮中途自动暂停，队列里 5 个
                    #   新词一个都没闪出来，状态条却什么都没变。
                    self._emit_perf_if_changed()
                    return
                if index and spent >= self.round_budget_ms:
                    # 本轮预算花完：这一块**连同后面的**整块顺延，下一轮接着读
                    for rest_key, _rx, _ry, _rw, _rh, rest_cursor in boxes[index:]:
                        self.session.defer_roi(rest_key, rest_cursor)
                    self.round_deferred += 1
                    break
                crop = array[int(y):min(full_h, int(y) + int(bh)),
                             int(x):min(full_w, int(x) + int(bw))]
                if crop.shape[0] < 12 or crop.shape[1] < 24:
                    continue
                bands = self._tighten_bands(crop)
                if bands:
                    self.trim_count += 1
                    covered_rows = (max(b[0] + b[1] for b in bands)
                                    - min(b[0] for b in bands))
                    covered_cols = (max(b[2] + b[3] for b in bands)
                                    - min(b[2] for b in bands))
                    self.trimmed_px += float(max(0, crop.shape[0] - covered_rows))
                    self.trimmed_cols += float(max(0, crop.shape[1] - covered_cols))
                    self.band_count += len(bands)
                else:
                    bands = [(0, crop.shape[0], 0, crop.shape[1])]
                    self.band_count += 1
                # ---- 2b. 逐段送 OCR：每段「贴着字的那一条」（本机实测：
                #      贵在**一段里有几行字**，不在面积，见 `TIGHT_MAX_ROWS`）----
                cursor = max(0, min(int(cursor), len(bands) - 1))
                stop_at = None
                for bi in range(cursor, len(bands)):
                    if self._stop or self.session.state != "running":
                        self._emit_perf_if_changed()
                        return
                    if bi > cursor and (spent >= self.round_budget_ms
                                        or bi - cursor >= self.MAX_BANDS_PER_ROI):
                        stop_at = bi               # 剩下的段留给下一轮
                        break
                    start, height, col, width = bands[bi]
                    sub = crop[start:start + height, col:col + width]
                    if sub.shape[0] < 12 or sub.shape[1] < 24:
                        continue
                    if self._is_blank(sub):
                        # 纯一片色的块没有可读内容。让它进 OCR 是最贵的选择：
                        # `OcrEngine` 读不出东西时会把「多档缩放 × 对比度/二值化」
                        # 的回退阶梯**全部跑完**，实测一张 1920×1080 的空白整帧
                        # 单轮 10029ms，而同一帧有字幕时是 1280ms ——
                        # 「屏幕上暂时没有英文」恰好是最贵的一种帧，先在这里挡掉。
                        self.session.note_blank_crop()
                        continue
                    items, elapsed_ms = self._recognize(
                        sub, (int(x) + col, int(y) + start), origin, dpr)
                    spent += float(elapsed_ms or 0.0)
                    # 段级键（`r2c0,r2c1#2`）：同一块里换个段落就是不同条目，
                    # 「这块内容没变」的判断才不会把上一段的结果顶掉。
                    fresh = self.session.note_words("%s#%d" % (key, bi),
                                                    items, elapsed_ms, now=now)
                    # 「跑通了一次 OCR」才是清连续错误计数的凭据 —— **没变化被跳过的那些帧
                    # 不算**。以前把这个清零放在 `run()` 的 try/else 里，结果引擎真的坏了
                    # 的时候：坏帧报错 → 中间夹几帧静态（没跑 OCR 也没异常）→ 计数归零 →
                    # 永远到不了 3 次 → 「自动暂停」形同虚设（测试实测出来的）。
                    self.session.note_success()
                    if fresh:
                        self.perf.emit(self.session.perf())
                if stop_at is not None:
                    self.session.defer_roi(key, stop_at)
                    self.band_deferred += 1

        # ---- 3. 发一个提示（一次只闪一个词，§7.2「再切换到下一个目标」）----
        item = self.session.next_notice(now=now)
        if item is not None:
            self.notice.emit(item)
        self._emit_perf_if_changed(force=True)

    def _box_for_key(self, key, thumb_size, scale: float, full_size):
        """把顺延表里的 ROI 键还原成**全分辨率**框；认不出来就返回 `None`。

        键可能是并集块拼出来的 `r2c0,r2c1,r2c2`，也可能是单格 `r0c1`，
        整帧那轮则是 `full`。这里按同一套 `_roi_boxes` 几何还原 ——
        给回原来的那些格子，合并结果与当初必然一致（`_roi_boxes` 是纯函数）。
        """
        if key == "full":
            return ("full", 0.0, 0.0, float(full_size[0]), float(full_size[1]))
        parts = [p for p in str(key).split(",") if p[:1] == "r"]
        if not parts:
            return None
        boxes = self._roi_boxes(parts, thumb_size, scale, full_size)
        return boxes[0] if boxes else None

    def _emit_perf_if_changed(self, force: bool = False) -> None:
        """把会话状态发回主线程；**状态没变时不刷屏**，变了则一定送到。"""
        state = self.session.state
        if not force and state == self._last_perf_state:
            return
        self._last_perf_state = state
        self.perf.emit(self.session.perf())

    #: 一块 ROI 的灰度标准差低于它就认定「纯一片色」—— 没有可读内容。
    #: 取 2.0 而不是更大的理由（本机实测，`tools/sense_bench.py` 造的帧）：
    #: 空白整帧 **0.0**、字幕条 **62.5**、只有静态表头的那条 **16.1**、
    #: 滚动正文整帧 **24.0** —— 有内容的最低也有 16，所以 2.0 只会切掉
    #: 真正一片空的地方，不会把低对比正文一起当空白跳过。
    BLANK_STD_THRESHOLD = 2.0

    @classmethod
    def _is_blank(cls, crop) -> bool:
        """ROI 是否一片纯色（跳进 OCR 之前最便宜的一道闸）。

        只算**降采样后**的标准差：整块 1920×1080 也就 2M 像素 → 取 1/16 采样，
        几毫秒的事，比一次 OCR 便宜三个数量级；判定用的是「有没有对比」，
        采样不会改变结论。
        """
        try:
            g = (crop.astype(np.int32).mean(axis=2) if crop.ndim == 3
                 else crop.astype(np.int32))
            g = g[::4, ::4]
            if g.size == 0:
                return True
            mean = float(g.mean())
            return float(((g - mean) ** 2).mean()) ** 0.5 < cls.BLANK_STD_THRESHOLD
        except Exception:                                # noqa: BLE001
            return False        # 判不动就当「有内容」，宁多跑一次也别静默漏词

    #: 一行里像素标准差超过它就认定「这行有字形像素」。
    #: 取 4.0 的理由（`tools/sense_roi_probe.py` 实测）：字幕条里**没有字**的行是
    #: 纯色（0.0），有字的行是 20 以上；4.0 只切得掉真正的空行。
    TIGHT_ROW_STD = 4.0
    #: 一列里像素标准差超过它就认定「这一列有字形」。列向用比行向低的阈值：
    #: 一行字在列方向只占几个像素宽，对比度被同一列的空白摊薄。
    #: 3.0 的依据是 `tools/sense_card_probe.py`：卡片那块里**没有字**的列是
    #: 0.0，有字的列中位 5.4、最高 108.6，3.0 卡在两者之间。
    TIGHT_COL_STD = 3.0
    #: 收紧后四周各留的余量（像素）。不留会切掉字的升降部与下一行的边缘，
    #: 词框坐标会跟着偏；12px 是 1080p 字幕行高的几分之一，够便宜又不会切字。
    TIGHT_MARGIN = 12
    #: 两段之间隔不到这么多行/列就并成**一段**：同一句字幕换行、
    #: 词与词之间的空列，都不该被当成两段各收一次。
    TIGHT_GAP = 24
    #: 一段至少要占 `峰值段的 min_share` 的对比度、且厚过 `min_rows` 行/列，
    #: 才算「值得为它留进裁片」的内容。挡掉的是鼠标指针、进度条那一两行的亮点
    #: —— 它们会把首尾跨度撑满，等于把收紧整个废掉（本机实测就是这么坏的）。
    TIGHT_MIN_SHARE = 0.2
    TIGHT_MIN_SPAN = 3
    #: 一段最多喂这么多行给 OCR。**成本的关键就在这里**：一次引擎调用的耗时
    #: 几乎正比于「这一段里有几行字」，而不是像素面积
    #: （`tools/sense_shape_probe.py`，本机真桌面 · 同一张字幕帧）：
    #:
    #:     505x1970 一整条并集带（37 行小字）→ 1254ms（热）/ 4657ms（冷）
    #:     498x460  一格的一部分（10 行）    → 1541ms
    #:     1600x933 整帧横切三条之一（96 行）→ 4415ms
    #:     整帧     2560x1600                → 13846ms（`card_probe` 量的）
    #:
    #: 所以「切几刀」不是按面积算的，是按**行数**算的：一段 160 行足够装下
    #: 一行大字幕 + 上下余量，又能把一次调用压在 300~600ms 这个量级。
    #: 超出的部分不是丢掉，是 `SenseSession.defer_roi` 顺延到下一轮接着读。
    TIGHT_MAX_ROWS = 160
    #: 一块 ROI 一轮最多跑几段（`MAX_ROIS_PER_CYCLE` 块 × 这么多段是一轮的上限，
    #: 真正的闸门是 `ROUND_OCR_BUDGET_MS`：超预算就整块顺延，段数只是第二道）。
    MAX_BANDS_PER_ROI = 4
    #: 切段时相邻段之间的重叠（像素）。不留重叠会把正好跨在切线上的那行字
    #: **切成两半**，两半都读不出词 —— 宁可多读 24 行里的几个词（词级去重会压掉）。
    TIGHT_BAND_OVERLAP = 24
    #: 一段里行数超过这个数就不再切（一整页正文能切几十段，顺延表挤爆；
    #: 真正的读法交给 `MAX_ROIS_PER_CYCLE` 与轮预算）。
    MAX_BANDS_PER_ROI_HARD = 24
    #: 一轮里 OCR 的**总**时间预算（毫秒）。超过就把剩下的块整块顺延到下一轮。
    #: 这是「本机 OCR 比我们的节奏慢」时的真正止血点：以前一轮能跑到 4~19 秒
    #: （整帧那轮实测 18966ms），降频和暂停的判据被这种轮次顶到下限，
    #: 于是「蜘蛛感应在这台机器上开十几秒就自己停了」—— 而那本来只是**一轮喂太多**。
    ROUND_OCR_BUDGET_MS = 1200.0

    @classmethod
    def _kept_runs(cls, score):
        """把「有内容的行/列」并成段、丢掉亮点段，返回**保留的段** `[(起, 止), ...]`。

        `score` 是每行（或每列）的对比度，**已经按阈值置过零**（低于阈值的为 0）。
        规则：隔不到 `TIGHT_GAP` 的相邻段先并成一段 → 厚度不到 `TIGHT_MIN_SPAN`
        或总量不到最强段 `TIGHT_MIN_SHARE` 的段丢掉。剩下的可能是一段，也可能是
        好几段（屏幕上两处不挨着的文字）—— 几段就是几次便宜的 OCR，而不是一整块。
        """
        hit = np.flatnonzero(score > 0)
        if hit.size == 0:
            return []
        runs, start, prev = [], int(hit[0]), int(hit[0])
        for value in hit[1:]:
            value = int(value)
            if value - prev > cls.TIGHT_GAP:
                runs.append((start, prev + 1))
                start = value
            prev = value
        runs.append((start, prev + 1))
        totals = [(a, b, float(score[a:b].sum())) for a, b in runs]
        peak = max(item[2] for item in totals)
        return [(a, b) for a, b, total in totals
                if b - a >= cls.TIGHT_MIN_SPAN
                and total >= cls.TIGHT_MIN_SHARE * peak]

    @classmethod
    def _content_span(cls, score):
        """兼容旧接口：所有保留段合起来的 `(起, 止)`；一段都没有就 `None`。"""
        kept = cls._kept_runs(score)
        if not kept:
            return None
        return kept[0][0], kept[-1][1]

    @classmethod
    def _row_ink(cls, gray, cols):
        """每行的对比度（按列降采样到 ~640 点，几毫秒的开销）。"""
        step = max(1, cols // 640)
        return gray[:, ::step].std(axis=1)

    @classmethod
    def _chop(cls, top, bottom, limit, overlap):
        """把 `[top, bottom)` 切成若干不超过 `limit` 行的小段（相邻重叠 `overlap`）。

        只切**一段之内**的：`_kept_runs` 已经保证了段与段之间隔得够远，
        段内再切是因为一段正文可以有两三百行。

        ★ 两处防御不是装饰：`overlap >= limit` 时「下一段的起点 = 终点 - 重叠」
          会**不往前走**（本机测试里直接把进程挂在一个死循环上），
          所以重叠先被夹到 `limit // 2`，步进再取 `max(1, ...)` 保证单调推进。
        """
        height = bottom - top
        if height <= limit:
            return [(top, bottom)]
        overlap = max(0, min(int(overlap), int(limit) // 2))
        step = max(1, int(limit) - overlap)
        pieces = []
        start = top
        while start < bottom:
            stop = min(bottom, start + limit)
            pieces.append((start, stop))
            if stop >= bottom:
                break
            start += step
        return pieces[:cls.MAX_BANDS_PER_ROI_HARD]

    @classmethod
    def _tighten_bands(cls, crop):
        """ROI → 要 OCR 的**行段列表** `[(起始行, 高, 起始列, 宽), ...]`（按阅读顺序）。

        返回空列表 = 这块收不出东西（一片平 / 一行内容都没有 / 本来就只有一小段），
        调用方按原框整块送。每段自己按列收窄过，所以是「贴着字的那一条」。

        ★ 为什么切段而不是收成一整块（`tools/sense_shape_probe.py` 本机实测）：
          成本看的是**一段里有几行字**（见 `TIGHT_MAX_ROWS` 上的表），而真桌面上的
          并集带里除了字幕，还混着桌面图标、任务栏、别的小字 —— 一整块读回 37 行
          就是 1~5 秒。切成 ≤`TIGHT_MAX_ROWS` 行的几段，每段几行字、一次调用
          压到几百毫秒；一轮跑不完的段交给顺延表，下一轮接着读，**不静默丢**。
          旧的「收成一整块」还有一个更坏的副作用：一块 505 行高的图里，
          字幕那句只占 4 行，其余 33 行的小字把识别时间全花掉了。

        ★ 代价（说清楚，别当成无损优化）：一段里挑不亮的行（低于 `TIGHT_ROW_STD`）
          不进这一轮；它们在 `_prev_gray` 里算「看过」，要等自己变化才再有机会。
        """
        try:
            gray = (crop.astype(np.int32).mean(axis=2) if crop.ndim == 3
                    else crop.astype(np.int32))
            rows, cols = gray.shape[:2]
            if rows < 24 or cols < 24:
                return []
            ink = cls._row_ink(gray, cols)
            runs = cls._kept_runs(np.where(ink > cls.TIGHT_ROW_STD, ink, 0.0))
            if not runs:
                return []                      # 一段像内容的行都没有：交给 `_is_blank`
            margin = cls.TIGHT_MARGIN
            out = []
            for top, bottom in runs:
                cink = gray[top:bottom].std(axis=0)
                cruns = cls._kept_runs(np.where(cink > cls.TIGHT_COL_STD,
                                                cink, 0.0))
                left, right = (cruns[0][0], cruns[-1][1]) if cruns else (0, cols)
                left = max(0, left - margin)
                right = min(cols, right + margin)
                for a, b in cls._chop(max(0, top - margin),
                                      min(rows, bottom + margin),
                                      cls.TIGHT_MAX_ROWS,
                                      cls.TIGHT_BAND_OVERLAP):
                    out.append((a, b - a, left, right - left))
            if len(out) == 1:
                a, b, left, right = out[0][0], out[0][0] + out[0][1], \
                    out[0][2], out[0][2] + out[0][3]
                if b - a >= rows * 0.9 and right - left >= cols * 0.9:
                    return []                  # 行列都收不掉多少，按原框走
            return out
        except Exception:                        # noqa: BLE001
            return []            # 判不动就不收，绝不能因为收紧把词弄丢

    @classmethod
    def _tighten_crop(cls, crop):
        """`_tighten_bands` 的**包围盒**视角：`(起始行, 高, 起始列, 宽)` 或 `None`。

        线上跑的是 `_tighten_bands`（逐段送 OCR）；这里留给探针、报表和测试回答
        「线上这一轮究竟会碰 ROI 里的哪一块」，所以它给出的是各段的并集框。

        历史（保留原来的说明，因为形状与成本的关系就是在这里量出来的）：
        `tools/sense_card_probe.py` 在真桌面上量到「三个格子并成一整条
        1970x642 的带」这块**根本不包含字幕那句能读出来的形状** ——
        从这条带里读回 38 行小字，句子一个词都没读到（3454ms），而
            只收行 1970x393 → 读到整句 · 3401ms
            只收列 1428x642 → 读到整句 · 2106ms
            行列都收 1428x393 → 读到整句 · 922ms
        机制是 `OcrEngine` 检测前把长边缩到 `DET_LIMIT=736`：1970 宽 → 系数 0.37，
        42px 的字变成 16px，掉到检测器不认的量级。列向收窄不是为了省面积，
        是**保住字的尺寸**。
        """
        bands = cls._tighten_bands(crop)
        if not bands:
            return None
        top = min(b[0] for b in bands)
        bottom = max(b[0] + b[1] for b in bands)
        left = min(b[2] for b in bands)
        right = max(b[2] + b[3] for b in bands)
        return top, bottom - top, left, right - left

    # ---------------------------------------------------------------- ROI 取舍
    #: 并集包围盒最多允许是「各块面积之和」的几倍。超过就说明变化点散在屏幕两头，
    #: 硬并成一块会把无关区域也喂进 OCR。
    MERGE_SLACK = 2.2

    def _roi_boxes(self, roi_keys, thumb_size, scale: float, full_size):
        """变化格子键 → 要 OCR 的框（**全分辨率**坐标：`(key, x, y, w, h)`）。

        ★ 2026-10-18 实测改的设计：原来「每个变化格子各裁一块、各跑一次 OCR」，
        `tools/sense_bench.py` 在 1080p 帧上量出来是
        `r2c0 2397ms / r2c1 111ms / r2c2 65ms / r2c3 1863ms` —— 一轮四次调用，
        每次都要把检测模型完整跑一遍，**分开裁反而比整帧一次（1280ms）更贵**，
        「优先局部」这笔账当场不成立。
        所以改成：格子相邻/挨着 → **并成一个包围盒，只跑一次 OCR**；
        只有并起来确实铺得太开（超过各块面积之和的 `MERGE_SLACK` 倍）才分开跑。
        单格变化时行为与原来完全一致（包围盒就是那一格）。
        """
        boxes = []
        for key in list(roi_keys)[:MAX_ROIS_PER_CYCLE]:
            x, y, bw, bh = self.session.roi_box(key, thumb_size)
            # 缩略图坐标 → 全分辨率坐标
            boxes.append((key, x / scale, y / scale, bw / scale, bh / scale))
        if not boxes:
            return []
        single = [(k, int(x), int(y), max(1, int(bw)), max(1, int(bh)))
                  for k, x, y, bw, bh in boxes]
        if len(single) == 1:
            return single
        x0 = min(b[1] for b in boxes)
        y0 = min(b[2] for b in boxes)
        x1 = max(b[1] + b[3] for b in boxes)
        y1 = max(b[2] + b[4] for b in boxes)
        union = max(1.0, (x1 - x0) * (y1 - y0))
        parts = sum(max(1.0, b[3] * b[4]) for b in boxes)
        if union <= parts * self.MERGE_SLACK:
            key = ",".join(b[0] for b in single)       # 键按行优先顺序拼，去重稳定
            return [(key, int(x0), int(y0),
                     max(1, int(x1 - x0)), max(1, int(y1 - y0)))]
        return single

    # ---------------------------------------------------------------- OCR + 词典
    def _recognize(self, crop, offset, origin, dpr: float):
        """一块 ROI → 词卡列表（带屏幕坐标）+ 该块 OCR 耗时（毫秒）。

        坐标换算和 `OcrWorker.locate` 严格同一条公式：
            屏幕逻辑坐标 = 选区原点 + 图像像素坐标 / DPR
        这里「选区原点」是整个虚拟桌面左上角，「图像像素坐标」是
        词中心在**整帧**里的位置 = ROI 偏移 + 词在 ROI 里的位置。
        """
        from ocr_adapter import engine_lines                # noqa: WPS433
        started = time.time()
        # 和 `OcrWorker.run` 同一个出口：**引擎只换推理实现**，词典/词框/坐标
        # 换算这条链保持不变；`note` 非空时挂到会话上，状态条里看得见。
        lines, self.engine_id, note = engine_lines(crop)
        elapsed_ms = (time.time() - started) * 1000.0
        self.engine_note = note
        self.session.note_engine(self.engine_id, note)
        if self.min_conf > 0:
            lines = [ln for ln in lines
                     if getattr(ln, "score", None) is None
                     or ln.score <= 0 or ln.score >= self.min_conf]
        text = "\n".join(line.text for line in lines)
        if not text.strip():
            return [], elapsed_ms
        # 候选池开大一点：`scan_text` 会按考纲/难度排序，截断交给 limit；
        # 池子比 limit 小会让「最多 N 个」变成假筛选（和 OcrWorker 同一个理由）。
        words = self.lexicon.scan_text(text, mode=self.mode,
                                       limit=max(24, int(self.limit)),
                                       skip_stopwords=self.skip_stopwords)
        positions, boxes = {}, {}
        for line in lines:
            for word in line.words:
                positions.setdefault(word.text, (word.cx, word.cy))
                boxes.setdefault(word.text, (word.left, word.top,
                                             max(1.0, word.right - word.left),
                                             max(1.0, word.bottom - word.top)))
        items = []
        for item in words[:max(1, int(self.limit))]:
            surface = item.get("surface")
            point = positions.get(surface)
            box = boxes.get(surface)
            if point is None and surface and " " in surface:
                # 多词术语：和 `OcrWorker.phrase_point/phrase_box` 同一套算法。
                # 惰性 import 是为了避开循环依赖（pet_window 要 import 本模块）。
                from pet_window import OcrWorker          # noqa: WPS433
                point = OcrWorker.phrase_point(surface, lines)
                box = OcrWorker.phrase_box(surface, lines)
            if point is None:
                continue
            ox, oy = offset
            screen = (origin[0] + (ox + point[0]) / dpr,
                      origin[1] + (oy + point[1]) / dpr)
            entry = dict(item)
            entry["screen_pos"] = screen
            if box:
                entry["screen_box"] = (origin[0] + (ox + box[0]) / dpr,
                                       origin[1] + (oy + box[1]) / dpr,
                                       max(1.0, box[2]) / dpr,
                                       max(1.0, box[3]) / dpr)
            items.append(entry)
        return items, elapsed_ms


def _thumbnail(gray, cv2):
    """灰度帧 → 缩略图（宽不超过 `THUMB_WIDTH`），返回 ``(thumb, scale)``。

    为什么先缩：变化检测只需要「这块区域整体亮暗有没有变」，
    4K 屏 800 万像素做一次均值金字塔毫无必要；
    `scale` 带回去给上层把格子坐标乘回全分辨率去裁 OCR 图。
    """
    h, w = gray.shape[:2]
    if w <= THUMB_WIDTH:
        return gray, 1.0
    scale = THUMB_WIDTH / float(w)
    thumb = cv2.resize(gray, (THUMB_WIDTH, max(1, int(h * scale))),
                       interpolation=cv2.INTER_AREA)
    return thumb, scale
