# -*- coding: utf-8 -*-
"""OCR 引擎：离线 RapidOCR（ONNX Runtime，中英文），延迟加载。

和参考实现相比，这里多做了一件事：**保留每一行文字的位置**，
并把行内文字按字符宽度估算出每个单词的落点。
「词蛛LEXARA」要让蜘蛛的八条腿去踩住屏幕上的八个单词，
没有这套坐标就只能把词排在卡片里，腿无处可落。

为什么用 RapidOCR 而不是 PaddleOCR：
    RapidOCR 是纯 ONNX 推理，模型随包分发、无外部运行时依赖，
    也不存在 Paddle C++ 层对非 ASCII 路径的硬性限制
    （项目目录在中文路径下，用 Paddle 会在 create_predictor 里直接失败）。

------------------------------------------------------------------------------
2026-10-17 识别链路重写（用户实测「还是没识别出来」之后的根因复查）：

旧版注释认为「检测端会把大图缩到 ~736px」，**这是错的**。
读 rapidocr_onnxruntime/ch_ppocr_v3_det/utils.py 的 DetResizeForTest：
默认 ``limit_side_len=736, limit_type='min'`` ——
    min(h, w) < 736 时把**小边放大**到 736；min 边 >= 736 时 ratio=1 不缩放。
由此实测出两个真正的坑：

    1. 宽扁选区必失败：框一句话（如 1920x150）会被内部放大 736/150 ≈ 4.9 倍，
       有效宽度冲到 ~9400px；而检测端输入的**有效宽度超过 ~6000px 时
       直接返回空结果**（实测 0.1~0.3s 返回、一行都没有）。
       这就是「框一段话/一行字识别不出来」的真凶，与字号无关。
    2. 内部放大的插值质量差：小字（14~16px）靠检测端自己 linear 放大糊得
       厉害；先用**立方插值**把图放大再送进去，同样的有效尺寸识别率明显更高。

所以新的识别计划（`_plans_for`）由粗到细：
    第 0 档  裁掉四周纯背景后直送 —— ≥18px 的正文一次就中，最快；
    第 1 档  立方放大（上限 4 倍）专治小字；宽扁图先用背景色补白压低
             内部放大倍数，超宽则横向切条（条间留 64px 重叠防切词）；
    兜底    全部档位跑完仍没有高分行时，用对比度拉伸变体再救一次。
所有坐标一律除回 factor、加回裁边/切条偏移，**还原到用户框选的原图像素**。
"""

from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import cv2
import numpy as np
from PySide6.QtGui import QImage

#: 与 lexicon 保持一致的分词口径
WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")

#: —— RapidOCR 检测端行为参数（上面文档字符串里的两个坑的数值） ——
DET_LIMIT = 736       #: 检测端把 min 边内部放大到这个值
EFF_CAP = 5600        #: 有效最长边安全线（实测 ~6000 起检测端返回空，留余量）
MAX_FACTOR = 6        #: 立方放大上限倍率（再大耗时不成比例）
TILE_OVERLAP = 640    #: 横向切条的重叠像素，必须 > 最长单词宽度，保证词不被切在缝里
GOOD_SCORE = 0.82     #: 加档后的早停线：出现达到该置信度的行就不再加档
FIRST_PASS_SCORE = 0.9  #: 直送档的早停线更严：一行含糊就不该偷懒，值得加档再试
#: 两个框 IoU 超过它才算「同一行」，不同档位的结果按它去重合并。
MERGE_IOU = 0.55

#: 「策略 0.5」的补白与放大：把行带上下补到 2 倍行高、再立方放大 3 倍。
#:
#: ★ 2026-10-19 深夜**关闭**（设 0 即不生成这一档）。它在合成图上是有效的
#:   便宜档，但真实整屏截图上多这一档会让「读不出」的带多跑一次完整推理，
#:   而框的坐标还原又多一条路径要验证。为了先回到确定可用的状态，先关。
#:   想试：设 LEXARA_OCR_CHEAP_PAD=3。
CHEAP_PAD_SCALE = 2.0
CHEAP_PAD_FACTOR = max(0, int(os.environ.get("LEXARA_OCR_CHEAP_PAD") or 0))

#: 逐行切带的上限（老规则）：超过 8 行、或图高 ≥600 就整块送。
#: 2026-10-19 深夜恢复 —— 见 `recognize_lines` 里那段说明。
LEGACY_MAX_SPLIT_BANDS = 8
#: 旧名字，保留给 `tools/ocr_speed.py`（它靠改这个值做「整块 vs 逐带」对照）。
MAX_SPLIT_BANDS = LEGACY_MAX_SPLIT_BANDS
#: 一轮里同时跑几条带。**默认 1（串行）**。
#:
#: ★ 2026-10-19 深夜回退：一度设成 4，理由是合成图的批量基准上能到 1.6x。
#:   但真实交互场景（框一次选区、等第一次出结果）反而更慢，原因有三：
#:   ① ONNX Runtime 的同一个 session 内部有锁，4 个线程抢一把锁，只是把
#:      锁竞争和 cache 抖动加进来，单次推理本身变慢；
#:   ② 并发是「整批一起返回」，用户等的是**最慢那条带**，快的那几条省下的
#:      时间在界面上完全体现不出来；
#:   ③ 我原来的 A/B 用的是合成图 + 预热后取两次最小值，正好把这三条都掩盖了。
#:   要重新打开：设 LEXARA_OCR_THREADS=4（只用环境变量，不改代码）。
BAND_WORKERS = max(1, int(os.environ.get("LEXARA_OCR_THREADS") or 1))

#: 一条行带的**硬预算**：最多几次推理调用 / 最多多少毫秒。
#:
#: ★ 2026-10-19 深夜新增，这是「框一句要等 20 秒」的真正病根。
#:   一条读不出的带会依次跑：直送 → 6 条横向切条 → 补白巨图，
#:   每档最多 3 个变体（原图/对比度/二值化）≈ 20 次推理。真实截图
#:   （浅灰 11px 小字界面）实测**单带 7 秒、整页 20 条带 77 秒**，而且那些带
#:   最后一行都没读出来 —— 读不出就是 0 行，多等一秒都是白等。
#:   预算用完就带着已读到的行收工。正常图不受影响：直送一次就中的带
#:   `calls=1` 就走了，根本碰不到预算。
#:   数值取得比较宽松（12 次 / 3 秒），只兜「彻底卡死」这种极端情况，
#:   不参与正常取舍 —— 宁可慢一点，也不要因为预算把本来能读出的行截掉。
BAND_CALL_BUDGET = max(1, int(os.environ.get("LEXARA_OCR_CALL_BUDGET") or 12))
BAND_TIME_BUDGET_MS = max(100, int(os.environ.get("LEXARA_OCR_TIME_BUDGET") or 3000))
#: 一整轮的兜底预算。行带再多（框了整页），也不许让用户对着"识别中"干等：
#: 超过这个时间就带着**已经读到的那些带**先出结果。
OCR_TOTAL_BUDGET_MS = max(1000, int(os.environ.get("LEXARA_OCR_TOTAL_BUDGET") or 20000))

#: 全局并发闸门。用**信号量**而不是「只让线程池管自己」：
#: 感应模式与手动框选可能同时各起一轮，两轮共用同一个引擎，
#: 闸门保证全进程同一时刻最多 `BAND_WORKERS` 条带在推理，
#: 不会把引擎并发数翻倍、把内存峰值顶上去。
_band_gate = threading.BoundedSemaphore(max(1, BAND_WORKERS))


def _debug() -> bool:
    """排障开关：设 LEXARA_OCR_DEBUG=1 打印每档的识别情况。"""
    return bool(os.environ.get("LEXARA_OCR_DEBUG"))


def _cubic(arr: np.ndarray, factor: int) -> np.ndarray:
    """立方插值放大。

    不能用 ``np.repeat`` 最近邻：抗锯齿笔画会被打成锯齿块，
    实测把原本 6/6 全对的图直接打成 0 行。
    """
    if factor <= 1:
        return arr
    h, w = arr.shape[:2]
    return cv2.resize(arr, (int(w) * factor, int(h) * factor),
                      interpolation=cv2.INTER_CUBIC)


def _border_bg(arr: np.ndarray) -> tuple:
    """四边像素的中位色当背景色（裁边判定与补白共用）。"""
    h, w = arr.shape[:2]
    strips = [arr[0, :, :], arr[-1, :, :], arr[:, 0, :], arr[:, -1, :]]
    pixels = np.concatenate([s.reshape(-1, 3) for s in strips], axis=0)
    return tuple(int(v) for v in np.median(pixels, axis=0))


def _pad_min_side(arr: np.ndarray, target: int, bg: tuple):
    """用背景色把 min 边补到 target —— 压低检测端的内部放大倍数。

    宽扁选区必须补白：min 边 150px 会被内部放大 4.9 倍、宽度直接爆表；
    补到 ~317px 后内部只剩 ~2.3 倍，检测才活得下来。补白本身不影响识别。
    返回 ``(补后图, x方向补白量, y方向补白量)`` —— 补白发生在**缩放后**，
    坐标还原时必须把这段偏移减掉，否则行框整体错位。
    """
    h, w = arr.shape[:2]
    pad_h, pad_w = max(0, target - h), max(0, target - w)
    if pad_h <= 0 and pad_w <= 0:
        return arr, 0, 0
    top, left = pad_h // 2, pad_w // 2
    out = cv2.copyMakeBorder(arr, top, pad_h - top, left, pad_w - left,
                             cv2.BORDER_CONSTANT, value=bg)
    return out, int(left), int(top)


def _autocrop(arr: np.ndarray):
    """裁掉四周纯背景（留 12px 呼吸边），返回 ``(裁后图, x偏移, y偏移)``。

    大片空白会白占宽度预算、还会让小字在整图里更不起眼。
    按「与背景色的亮度差」找内容，亮底/暗底通用；满屏都是内容或
    根本没有内容时不裁（裁了也白裁）。
    """
    h, w = arr.shape[:2]
    lum = arr.astype(np.float32).mean(axis=2)
    border = np.concatenate([lum[0, :], lum[-1, :], lum[:, 0], lum[:, -1]])
    bg = float(np.median(border))
    mask = np.abs(lum - bg) > 26.0
    if not mask.any() or mask.mean() > 0.6:
        return arr, 0, 0
    ys, xs = np.where(mask)
    pad = 12
    y0, y1 = max(0, int(ys.min()) - pad), min(h, int(ys.max()) + pad + 1)
    x0, x1 = max(0, int(xs.min()) - pad), min(w, int(xs.max()) + pad + 1)
    if (y1 - y0) * (x1 - x0) >= int(h * w * 0.98):
        return arr, 0, 0
    return np.ascontiguousarray(arr[y0:y1, x0:x1]), int(x0), int(y0)


def _internal_ratio(h: int, w: int) -> float:
    """检测端对 (h, w) 输入的内部缩放比（``limit_type='min'``）。"""
    m = min(h, w)
    return (float(DET_LIMIT) / m) if m < DET_LIMIT else 1.0


def _contrast_variant(arr: np.ndarray):
    """min-max 对比度拉伸：最暗像素压到纯黑、最亮压到纯白。

    2026-10-17 实测：14px 的灰色（#333）小字无论放大多少倍都读不出，
    纯黑同字号一次全对 —— 卡住识别的不是尺寸而是**笔画不够黑**
    （抗锯齿+灰字让笔画核心到不了 0）。旧版用 2%~98% 分位拉伸，
    但小字占整图像素常不足 2%，分位点落在浅色像素上等于白拉；
    改用最暗值兜底，灰字/斜体/彩色混排都能受益。
    """
    lum = arr.astype(np.float32).mean(axis=2)
    lo = float(np.min(lum))
    hi = max(float(np.percentile(lum, 99.8)), lo + 16.0)
    if hi - lo < 16:                          # 全图本来就几乎单色，拉了白拉
        return None
    st = np.clip((lum - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(np.stack([st] * 3, axis=-1))


def _otsu_variant(arr: np.ndarray):
    """Otsu 全局二值化（灰度 → 0/255 三通道）。

    2026-10-17 实测：14px 的灰色小字，对比度拉伸都救不动（拉伸后抗锯齿
    边缘还是灰的），但**硬二值化**一次全对 —— 识别模型对纯黑白最友好。
    只作为最后兜底：花哨背景（照片/深色 UI）上 Otsu 会放大噪声。
    """
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return np.ascontiguousarray(np.stack([bw] * 3, axis=-1))


def _iou(a: tuple, b: tuple) -> float:
    """两个 (x0,y0,x1,y1) 框的交并比。"""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0.0:
        return 0.0
    area_a = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / (area_a + area_b - inter)


#: 一行「够长的纯字母、却一个空格都没有」= 识别模型把词粘连了。
#: 字是对的、词边界是错的（`Thequarterlyreleasereport…`）。这种文本进
#: `scan_text` 只会被当成一个超长 token，**一个词都切不出来**，对「出词」而言
#: 等于没读到 —— 但它置信度往往有 0.9+，以前会被当成「读得足够好」而提前收工。
#: 实测窄行带（19px 左右）直送档稳定复现，同一张图补白后那一档就能正确断词。
GLUED_MIN_LEN = 8
#: 读到粘连版时，最多再往下试几档去换一个「断得出词」的读次。
#:
#: ★ 2026-10-19 深夜回退：从 1 改回 **0**。多试一档在「补白那一档正好能救」
#:   的图上有效，但真实场景里更多时候救不回来，白等一次完整推理（窄带还要
#:   再跑切条）。现在退到 0 = 老行为：分数够就收工，不额外补一刀。
#:   想恢复补救：设 LEXARA_OCR_GLUE_RETRY=1。
GLUE_RETRY = max(0, int(os.environ.get("LEXARA_OCR_GLUE_RETRY") or 0))
#: 行带上下各留多少（占这一行墨迹高度的比例）。
#:
#: ★ 2026-10-19 深夜**回退到 0.15**。一度改成 0.35，理由是合成图上
#:   「22px 三行命中率 14%→100%」。但真实整屏截图（终端 + IDE + 任务列表）
#:   上这 35% 会把**相邻两行并进同一条带**：一条带里读出好几行，
#:   还原后的框就撑成横跨整行的大块（`python`、`run` 那种巨型框），
#:   同时同一行被两条带各读一次、坐标错位。用户看到的就是「标注全乱」。
#:   合成图之所以没暴露：PIL 渲染的行距大、字号统一，0.35 刚好卡在中缝里。
#:   **真实界面截图的行距紧得多，0.35 必然越过中缝。**
#:   留白放宽只能在「不许越过与邻行的中缝」的前提下做，而现在的
#:   `_line_bands` 没有那个约束，所以先退回 0.15。
BAND_PAD_RATIO = 0.15


def _glued(text: str) -> bool:
    """这行文字是不是「纯字母、无空格、还够长」的粘连读次。"""
    core = (text or "").strip()
    return (len(core) >= GLUED_MIN_LEN and " " not in core
            and bool(re.fullmatch(r"[A-Za-z'\-]+", core)))


def _merge_lines(old: list, new: list) -> list:
    """按 IoU 合并两批行：同一行（IoU 达标）择优替换，新行直接并入。"""
    out = list(old)
    for line in new:
        twin = next((o for o in out if _iou(o.box, line.box) >= MERGE_IOU), None)
        if twin is None:
            out.append(line)
        elif line.score > twin.score:
            out[out.index(twin)] = line
    return out


def _contains(big: tuple, small: tuple, margin: float = 6.0) -> bool:
    """small 的框是否整体落在 big 内（含少量边距）。用于去重时丢弃被覆盖的局部碎片。"""
    return (small[0] >= big[0] - margin and small[2] <= big[2] + margin and
            small[1] >= big[1] - margin and small[3] <= big[3] + margin)


def _dedup_lines(lines: list) -> list:
    """去掉被更长/更高分行覆盖的局部碎片与近乎重复的读次，保留每物理行最好的那行。

    横向切条（重叠很大）时，一条词可能同时出现在相邻两条里 → 近乎重复；
    某条只读出半行、另一条读出整行 → 半行被整行包含。两种情况都只留完整那行，
    否则蜘蛛会把同一个词踩两遍、或漏掉被覆盖段。优先保留**置信度更高**的行，
    因为小字直接档常读出整宽乱码（高分但内容错），不能靠长度判胜负。
    """
    out = []
    for ln in sorted(lines, key=lambda l: (-l.score, -len(l.text))):
        if any(_contains(b.box, ln.box) and b.score >= ln.score
               for b in out):
            continue
        if any(_iou(b.box, ln.box) > 0.85 for b in out):
            continue
        out.append(ln)
    return out


def _covers_full(lines: list, band_w: int) -> bool:
    """是否已有某行覆盖了整条带的大部分宽度（视为这条带已读全）。

    置信度门槛取 GOOD_SCORE：小字直接档（factor 1）常读出整宽乱码，
    分数不高但框占满整宽，若门槛太低会误以为「读全了」而提前收工。
    """
    if band_w <= 0:
        return False
    return any((ln.box[2] - ln.box[0]) >= 0.82 * band_w and ln.score >= GOOD_SCORE
              for ln in lines)



def _max_filter(rows: np.ndarray, win: int) -> np.ndarray:
    """1D 居中最大滤波：把窗口内任一墨迹行的最高占比铺到整窗。

    用来桥接**行内**笔画间的低墨缝隙（单个字母的镂空、字母上沿到字身之间
    的那一两行空白）。不碰**行间**的大间隙，所以后面仍能把多行正确分开。
    """
    if win <= 1:
        return rows
    half = win // 2
    ext = np.pad(rows, half, mode="edge")
    sw = np.lib.stride_tricks.sliding_window_view(ext, win)
    return sw.max(axis=1)


def _line_bands(crop: np.ndarray, bg: tuple) -> list:
    """用水平投影把多行文字切成「单行带」，返回 ``[(带图, x偏, y偏), ...]``。

    为什么要切：把整条短带（如 553x89 的三行段落）一次性立方放大后，
    图变成极端宽扁（宽高比 ~6:1），RapidOCR 的检测端会把挨得近的几行
    **并成一行**（实测 factor 4/5/6 分别只认出 1/2/1 行，毫无规律）。
    而单行宽扁图在同样的 factor 下稳定识别 —— 所以按行切开、逐行送，
    既保住「框一句话」的旧用例，又能让多行段落每行都读到。

    切法：先对每行墨迹占比做居中最大滤波，把行内笔画缝隙（1~5 行空白）
    填上，避免单个字母的细缝把一行切成几段（19px Arial 实测踩过）；
    再以「中值行高」为尺度合并残留的小间隙 —— 间隙小于中值行高一半的
    视为同一行。只有聚出 **2 段及以上** 才真正切，否则原样返回整条。
    """
    h, w = crop.shape[:2]
    lum = crop.astype(np.float32).mean(axis=2)
    ink = np.abs(lum - float(np.mean(bg))) > 24.0
    row_ink = ink.mean(axis=1)
    if row_ink.max() <= 0.02:
        return [(crop, 0, 0)]

    # 窗口随画布高度自适应，但远小于行间距（13~31px），只对行内缝隙生效。
    win = min(max(4, h // 25), 9)
    smooth = _max_filter(row_ink, win)
    thr = smooth.max() * 0.15
    text_row = smooth > thr
    if not text_row.any():
        return [(crop, 0, 0)]

    groups = []
    start = None
    for y in range(h):
        if text_row[y] and start is None:
            start = y
        elif not text_row[y] and start is not None:
            groups.append([start, y])
            start = None
    if start is not None:
        groups.append([start, h])
    if len(groups) <= 1:
        return [(crop, 0, 0)]

    # 以中值行高为尺度合并：相邻段间隙小于中值行高一半的视为同一行。
    heights = [e - s for s, e in groups]
    median_h = max(1, int(np.median(heights)))
    merged = [list(groups[0])]
    for s, e in groups[1:]:
        gap = s - merged[-1][1]
        if gap <= median_h * 0.5:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    if len(merged) <= 1:
        return [(crop, 0, 0)]

    out = []
    for s, e in merged:
        pad = max(2, int((e - s) * BAND_PAD_RATIO))
        s2 = max(0, s - pad)
        e2 = min(h, e + pad)
        out.append((np.ascontiguousarray(crop[s2:e2, :]), 0, s2))
    return out


def _plans_for(crop: np.ndarray, ox: int, oy: int, bg: tuple) -> list:
    """由粗到细生成识别计划。

    每个计划是 ``(图像, factor, sub_x, sub_y, add_x, add_y, 可早停, 要严判)``，
    坐标还原公式：``原图坐标 = (缩放图坐标 - sub) / factor + add``。
    「要严判」= 这一档想收工，置信度得达到 `FIRST_PASS_SCORE`(0.9) 而不是
    `GOOD_SCORE`(0.82) —— 直送与「策略 0.5」两档用它：它们是一次性的低成本尝试，
    分数只要 0.84 这种「八成对」就收工的话，会**挡住后面读得更准的档位**
    （实测 14px 那条带：策略 0.5 给 0.84 的残缺文本，而继续跑完能读全）。

    第 0 档直送；策略 0.5 小补白；第 1 档立方放大（倍率按 min 边抬到 736，上限
    `MAX_FACTOR`）专治小字，min 边不足 736 时补白压低内部放大，
    有效宽度超预算则把**缩放后的图**横向切条（带重叠）。
    切条时除最后一条外都**不可早停** —— 否则第一条读干净了就直接收工，
    后面几条的词全丢（花式测试图实测踩过）。
    """
    h, w = crop.shape[:2]
    plans = [(crop, 1, 0, 0, ox, oy, True, False)]  # 第 0 档：直送（大字号一次中）

    # —— 策略 0.5：小补白 + 小倍率（★ 2026-10-19 新增，见模块常量 CHEAP_*）——
    # 直送读不出的窄带，绝大多数不是「字太小」，而是**这条带太矮**：22px 的带
    # 被检测端内部放大 33 倍（736/22），有效宽度冲到 2.6 万 → 直接返回空。
    # 上下补到 2 倍行高、再立方放大 3 倍，min 边就够用了。
    # 实测 7 条「直送 0 行」的带（13/14/20/22/26px、暗底、灰字）全部一次读出整行，
    # 单次 60~150ms；而策略 B 那条补到 736 的巨图（4842×738）要 1.5~3s，
    # 且这些带它照样读不出。
    if CHEAP_PAD_FACTOR > 0 and h < w and w * CHEAP_PAD_FACTOR <= EFF_CAP:
        pad_h = int(round(h * CHEAP_PAD_SCALE))
        if pad_h > h:
            pad = pad_h - h
            top = pad // 2
            cheap = cv2.copyMakeBorder(crop, top, pad - top, 0, 0,
                                       cv2.BORDER_CONSTANT, value=bg)
            plans.append((_cubic(cheap, CHEAP_PAD_FACTOR), CHEAP_PAD_FACTOR,
                          0, top * CHEAP_PAD_FACTOR, ox, oy, True, True))

    factor = int(min(MAX_FACTOR,
                     max(2, -(-DET_LIMIT // max(1, min(h, w))))))
    min_side = min(h, w)

    # —— 策略 A：不补白、纯立方放大；超宽则横向切条（带重叠） ——
    # 极扁单行带（如 14px 一行）靠这条能逐条读干净；切条保证有效宽度不爆表。
    big = _cubic(crop, factor)
    bh, bw = big.shape[:2]
    eff = max(bh, bw) * _internal_ratio(bh, bw)
    if eff > EFF_CAP:
        k = int(-(-eff // (EFF_CAP * 0.85)))
        tile_w = int(-(-bw // k))
        tiled = []
        for i in range(k):
            x0 = max(0, i * tile_w - TILE_OVERLAP)
            x1 = min(bw, (i + 1) * tile_w + TILE_OVERLAP)
            part = np.ascontiguousarray(big[:, x0:x1])
            tiled.append((part, factor, 0, 0,
                          ox + x0 / float(factor), oy, i == k - 1, False))
    else:
        tiled = [(big, factor, 0, 0, ox, oy, True, False)]

    # —— 策略 B：把 min 边补到「factor 倍后刚好到 DET_LIMIT」再放大 ——
    # 检测端内部 ratio=1、有效宽度 = 缩放后宽度，整条单行一次识别，
    # 不被 tiny min 边放大成几十倍再切碎。14px 补白反而读不出（实测），
    # 但 16/20px 靠它最稳；两条策略都跑、按 IoU 合并择优，谁好用谁。
    padded = None
    if min_side * factor < DET_LIMIT:
        target = int(-(-DET_LIMIT // factor))   # ceil(DET_LIMIT / factor)
        if h <= w:                              # 高度是 min 边 → 上下补白
            pad = target - h
            top = pad // 2
            big0 = cv2.copyMakeBorder(crop, top, pad - top, 0, 0,
                                      cv2.BORDER_CONSTANT, value=bg)
            sy0 = top * factor
            padded = (_cubic(big0, factor), factor, 0, sy0, ox, oy,
                      True, False)
        else:                                   # 宽度是 min 边 → 左右补白
            pad = target - w
            left = pad // 2
            big0 = cv2.copyMakeBorder(crop, 0, 0, left, pad - left,
                                      cv2.BORDER_CONSTANT, value=bg)
            sx0 = left * factor
            padded = (_cubic(big0, factor), factor, sx0, 0, ox, oy,
                      True, False)

    # 顺序（2026-10-19 深夜恢复老顺序）：直送 → 补白整图（可早停，省掉切条）→ 切条兜底。
    # 曾把补白整图挪到切条之后，理由是「补白整图是巨图，更贵」。但在真实截图
    # 上补白整图常常是唯一能读出的那一档，挪后反而让切条先跑一堆没用的。
    if padded is not None:
        plans.append(padded)
    plans.extend(tiled)
    return plans



def qimage_to_ndarray(img: QImage):
    """QImage → RGB ndarray（正确跳过 bytesPerLine 的行尾填充）。

    这里额外做一次 ``.copy()``：QImage 是隐式共享的，跨线程访问同一份像素
    缓冲区会有数据竞争（症状很隐蔽 —— 主线程识别正常，worker 线程里一个词都
    识别不出来）。复制成独立缓冲区后，后续的指针取值才是安全的。
    """
    if img is None or img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_RGB888).copy()
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return None
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8)
    stride = img.bytesPerLine()
    # 行尾可能有填充字节，先按行重组再切掉右侧填充
    arr = arr[: stride * h].reshape(h, stride)
    arr = arr[:, : w * 3].reshape(h, w, 3)
    # 必须拷贝：np.frombuffer 得到的是**只读**视图，而 ascontiguousarray 在已经
    # 连续时会原样返回它，于是 RapidOCR 拿到一个不可写的数组 → 识别结果为空。
    return np.ascontiguousarray(arr).copy()


@dataclass
class OcrWord:
    """行内一个单词（位置为**相对于被识别图像的像素坐标**）。

    2026-10-17 词框贴合改造：只有 `cx/cy` 的话，覆盖层就只能「在词上方另画一只
    按字体度量定尺寸的浮动标签」—— 那正是用户反馈的「单词上面多了一个框」。
    现在词自带 `bbox`（贴合字形本体的外接框）与 `poly`（跟随行倾斜的四点），
    框的宽高**由这个词实际占了多少像素决定**，短词短框、长词长框。
    """

    text: str
    cx: float
    cy: float
    left: float
    right: float
    top: float = 0.0
    bottom: float = 0.0
    poly: tuple = ()            # tl, tr, br, bl（图像像素）
    confidence: float = 0.0
    line_id: str = ""
    engine_id: str = "rapid"
    refined: bool = False       # 框边是否被墨迹投影细化过（评测要看这个比例）

    @property
    def bbox(self) -> tuple:
        """(x, y, w, h) —— 与 `communite/contracts/ocr-result-contract.md` §1 一致。"""
        return (self.left, self.top, self.right - self.left,
                max(0.0, self.bottom - self.top))


@dataclass
class OcrLine:
    """一行文字（含整行外接框与行内单词落点）。"""

    text: str
    box: tuple          # (x0, y0, x1, y1)
    score: float
    words: list = field(default_factory=list)
    poly: tuple = ()    # 引擎给的原始四点（斜体/倾斜文本靠它把词框跟着歪）
    line_id: str = ""

    @property
    def center(self):
        x0, y0, x1, y1 = self.box
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


#: 词框「墨迹细化」开关。`Trainer/scripts/evaluate_ocr.py` 的对照组用
#: `LEXARA_OCR_REFINE=0` 关掉它，量化这一步赚了多少 IoU；生产默认开。
WORD_REFINE = os.environ.get("LEXARA_OCR_REFINE", "1").strip() != "0"

#: 细化路径最近吞掉的异常（只留 20 条，内容是本机异常字符串，不含屏幕文字/截图）。
REFINE_ERRORS: list = []

#: 比例字体的相对字宽表（以 0..9 的 em 比例为参照，实测够用即可）。
#: 用「加权字符宽度」代替「按字符数均分」，是为了让 `i`/`l`/标点不再和 `m`/`w`
#: 抢一样多的水平空间 —— 均分法在 `millions` 这类词上会把框画到隔壁词上。
_CHAR_W = {
    "i": 0.30, "l": 0.30, "j": 0.31, "t": 0.36, "f": 0.36, "r": 0.43,
    "I": 0.30, "!" : 0.30, ".": 0.30, ",": 0.30, ":": 0.30, ";": 0.30,
    "'": 0.24, "\u2019": 0.24, "-": 0.40, "\u2013": 0.70, "(": 0.34, ")": 0.34,
    "[": 0.34, "]": 0.34, "|": 0.30, " ": 0.35,
    "m": 1.15, "w": 1.05, "M": 1.10, "W": 1.20,
    "z": 0.45, "x": 0.50, "e": 0.53, "c": 0.51, "s": 0.49, "a": 0.54,
    "b": 0.56, "d": 0.56, "g": 0.56, "h": 0.56, "k": 0.52, "n": 0.58,
    "o": 0.57, "p": 0.56, "q": 0.56, "u": 0.58, "v": 0.50, "y": 0.50,
}


def _char_w(ch: str) -> float:
    if ch in _CHAR_W:
        return _CHAR_W[ch]
    if ch.isupper():
        return 0.72
    if ch.isdigit():
        return 0.56
    return 0.55


def _token_weights(text: str, start: int, end: int) -> float:
    return sum(_char_w(c) for c in text[start:end])


def _estimate_word_spans(text: str, box) -> list:
    """按加权字符宽度把行框切成每个词的水平区间。

    返回 ``[(match, left, right), ...]``，坐标是**图像像素**。
    这是「引擎只给行框」时的兜底；真正的贴合靠后面的墨迹投影细化。
    """
    x0, y0, x1, y1 = box
    width = max(1.0, x1 - x0)
    matches = list(WORD_RE.finditer(text))
    if not matches:
        return []
    total_w = sum(_token_weights(text, m.start(), m.end()) for m in matches)
    # 非词字符（空格、标点）也占宽度，按整串权重分摊，避免词框被撑满整行
    all_w = sum(_char_w(c) for c in text) or total_w
    scale = width / all_w
    out = []
    for m in matches:
        left_off = sum(_char_w(c) for c in text[:m.start()]) * scale
        right_off = left_off + _token_weights(text, m.start(), m.end()) * scale
        out.append((m, x0 + left_off, x0 + right_off))
    return out


def _interpolate_poly(poly: tuple, frac_a: float, frac_b: float) -> tuple:
    """把行四点沿水平方向按 [frac_a, frac_b] 切出一个平行四边形。

    斜体/倾斜文本的整行四点已经是歪的，词框跟着歪，
    才不会「框比词宽」或者「框压在上一行的字上」。
    """
    if not poly or len(poly) != 4:
        return ()
    tl, tr, br, bl = poly

    def lerp(p, q, f):
        return (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)

    a_top, a_bot = lerp(tl, tr, frac_a), lerp(bl, br, frac_a)
    b_top, b_bot = lerp(tl, tr, frac_b), lerp(bl, br, frac_b)
    return (a_top, b_top, b_bot, a_bot)


def _ink_profile(arr, x0: int, x1: int, y0: int, y1: int):
    """行带内的「逐列有没有墨」与「逐行有没有墨」。

    背景色取该条带的四边中位色，前景按亮度差判定 —— 亮底暗字、暗底亮字通用
    （和 `_autocrop` / `_line_bands` 同一套判据，别再引入第三种口径）。
    """
    h, w = arr.shape[:2]
    x0, x1 = max(0, int(x0)), min(w, int(x1))
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None, None
    strip = arr[y0:y1, x0:x1].astype(np.float32)
    lum = strip.mean(axis=2)
    border = np.concatenate([lum[0, :], lum[-1, :], lum[:, 0], lum[:, -1]])
    bg = float(np.median(border))
    diff = np.abs(lum - bg)
    thr = max(18.0, float(np.percentile(diff, 92.0)) * 0.35)
    ink = diff > thr
    if ink.mean() < 0.002:
        return None, None
    return ink.any(axis=0), ink.any(axis=1)


def _ink_runs(col_ink):
    """把「逐列有没有墨」压成一段段连续的墨迹区间 `[(start, end), ...]`。

    一个真实的词 = 一段连续墨迹（词内字母是连着的，词间是空白）。
    这是「框贴合词」最硬的一条证据，比空白列中点更直接。
    """
    runs = []
    start = None
    for i, on in enumerate(col_ink):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(col_ink) - 1))
    return [r for r in runs if r[1] - r[0] >= 1]


def _grow_run(runs, idx, hard_cap: float, allow: float, max_width: float):
    """从 `runs[idx]` 出发，把「缝太小、不像词间空格」的相邻段并回来。

    ★ 为什么不能在全局按一个固定阈值先合并：阈值用行高做尺度时，
      行距大的排版（词间空白和字母缝一样宽）会把整行并成一段墨迹，
      只有一个词认领得上，其余全退回估算框 —— 实测 `I a committee…` 里
      'w' 的 IoU 直接 0。
    ★ 也不能「按当前段宽度的比例」长：从一个只有 3px 宽的字母碎片起步时，
      0.55×3=1.6px 的允许量谁也吸收不了，框就永远只是那个碎片
      （实测 'millions' 只框住 'll'，IoU 0.54）。
      所以允许量取 **本行墨迹段宽的中位数** 做尺度（字母缝 ≈ 段宽的 0.2~0.3，
      词间空格 ≈ 0.6~1.2 倍），再被三个上限夹住：
        · `hard_cap` —— 不许超过行高的一成多，避免整行并一起；
        · `0.35 × 估算词宽` —— 窄词不许把隔壁词吃掉；
        · 合并后总宽 ≤ `max_width` —— 同上，长度兜底。
    """
    seg = [float(runs[idx][0]), float(runs[idx][1])]
    i = idx
    while i - 1 >= 0:
        prev = runs[i - 1]
        gap = seg[0] - prev[1] - 1
        if gap > allow or (seg[1] - prev[1]) > max_width:
            break
        seg[0] = float(prev[0])
        i -= 1
    i = idx
    while i + 1 < len(runs):
        nxt = runs[i + 1]
        gap = nxt[0] - seg[1] - 1
        if gap > allow or (nxt[1] - seg[0]) > max_width:
            break
        seg[1] = float(nxt[1])
        i += 1
    return seg


def _snap_edges(arr, box, spans) -> None:
    """用墨迹投影把每个词的框**落到真实笔画上**，并收紧上下边。

    为什么必须做这一步：字符宽度估算只能保证「大致对」，
    而任务书 §4 要的是「框线直接贴合单词本身、偏差可量化」。
    三步（都在整行带内做一次列方向投影，不额外调 OCR）：
      ① 落位：估算区间一对一认领最近的**连续墨迹段**；
      ② 吸附：认领不上时，边界只允许在**半个字符宽**内挪到最近的空白列中点；
      ③ 收高：按每个词自己的列区间再量一次行方向投影，top/bottom 贴到笔画上下沿。
    找不到墨迹段也找不到 gap（词挨得太紧）就保留估算值 —— 宁可略宽，不能切进词里。

    `LEXARA_OCR_REFINE=0` 可以整段关掉这一步，`Trainer/scripts/evaluate_ocr.py`
    用它跑「只用估算」的对照组，量化细化到底赚了多少 IoU。
    """
    if not WORD_REFINE:
        return
    x0, y0, x1, y1 = box
    col_ink, _ = _ink_profile(arr, x0, x1, y0, y1)
    if col_ink is None:
        return
    base = float(x0)
    n = len(col_ink)
    # 空白列（含首尾）
    empty = np.logical_not(col_ink)
    if not empty.any():
        return
    empty_idx = np.flatnonzero(empty)
    #: 吸附前先存一份估算区间，退化了要拿它当中点/下限参照
    originals = [(w.left, w.right) for w in spans]

    def nearest_gap_center(px: float, limit: float):
        """在 px 附近 limit 像素内找一个空白列区段的中点（比单列更稳）。"""
        best, best_d = None, limit + 1.0
        for i in empty_idx:
            d = abs(i - px)
            if d > limit:
                continue
            # 该空白列所属的整段 gap
            s = i
            while s > 0 and empty[s - 1]:
                s -= 1
            e = i
            while e < n - 1 and empty[e + 1]:
                e += 1
            center = (s + e) / 2.0
            d = abs(center - px)
            if d < best_d:
                best, best_d = center, d
        return best

    # ① **落位**：把估算区间搬到它对应的那段连续墨迹上。
    #   为什么光靠「边界吸附」不够：`_estimate_word_spans` 是按字符权重把整行
    #   宽度摊开的，而真实排版里词间空白比一个 0.35em 的空格宽得多，
    #   于是从第二个词开始估算位置会**整体偏左** —— 偏得超过半个字符时，
    #   「只允许移动半个字符」的吸附根本救不回来（实测 `I a committee…` 里
    #   'a' 估算在 46~52、墨迹其实在 56~76，IoU 直接 0）。
    #   改成「一对一认领最近的墨迹段」：认领得上就把整框搬到那段墨迹上，
    #   认不上（太远、或被隔壁词先抢走）就保留估算值，绝不硬抢。
    relocated = set()
    runs = _ink_runs(col_ink)
    if runs:
        hard_cap = 0.2 * max(6.0, y1 - y0)
        #: 本行「一段墨迹有多宽」的中位数 —— 字母缝/词间空格的尺度参照
        med_run_w = float(np.median([e - s + 1 for s, e in runs]))
        candidates = []
        for wi, word in enumerate(spans):
            est_w = max(1.0, word.right - word.left)
            center = (word.left + word.right) / 2.0 - base
            best, best_d = None, None
            for ri, (s, e) in enumerate(runs):
                distance = abs((s + e) / 2.0 - center)
                if distance > max(est_w, e - s) * 1.2:
                    continue          # 太远就不是这个词，别硬抢隔壁的墨迹
                if best_d is None or distance < best_d:
                    best, best_d = ri, distance
            if best is None:
                continue
            allow = max(2.0, min(hard_cap, 0.42 * med_run_w, 0.35 * est_w))
            candidates.append((best_d, wi,
                               tuple(_grow_run(runs, best, hard_cap, allow,
                                               1.75 * est_w))))
        candidates.sort()
        taken_words, taken_segs = set(), set()
        for _distance, wi, seg in candidates:
            # 一对一：同一段墨迹只许一个词认领，抢不过就退回估算框
            if wi in taken_words or seg in taken_segs:
                continue
            taken_words.add(wi)
            taken_segs.add(seg)
            spans[wi].left = base + seg[0] - 1.0
            spans[wi].right = base + seg[1] + 1.0
            relocated.add(wi)

    # ② 没认领到墨迹段的词，再退而求其次：边界吸附到最近的空白列中点
    for wi, word in enumerate(spans):
        if wi in relocated:
            continue
        char_w = max(3.0, (word.right - word.left) / max(1, len(word.text)) * 1.2)
        for attr in ("left", "right"):
            cur = getattr(word, attr) - base
            hit = nearest_gap_center(cur, char_w)
            if hit is not None:
                setattr(word, attr, base + float(hit))

    # ★ 吸附之后必须**兜住退化**：窄词（`i`/`a`/`w`）估算出来就七八像素宽，
    #   左右两边各自吸到最近的空白列中点时很容易落到**同一个** gap 上，
    #   框塌成一条 0 宽的线。塌了的框后面连行投影都量不出来
    #   （`_ink_profile` 对宽度 <2px 直接返回 None），于是上下边也退化成整条行带，
    #   高度比真实笔画高出一倍多 —— 实测 `I a committee...` 里 'a' 的框高 53px vs 词 21px。
    # 规则：不许越过原区间的中点，宽度不小于原估宽的一半（且 ≥3px）。
    for wi, (word, (orig_left, orig_right)) in enumerate(zip(spans, originals)):
        if wi in relocated:
            continue        # 宽度是墨迹说的，不是估的 —— 别拿估算下限去推翻它
        mid = (orig_left + orig_right) / 2.0
        min_w = max(3.0, 0.5 * (orig_right - orig_left))
        if word.right - word.left < min_w or word.left >= word.right:
            word.left = max(min(word.left, mid), mid - min_w / 2.0)
            word.right = min(max(word.right, mid), mid + min_w / 2.0)
            if word.right - word.left < min_w:
                pad = (min_w - (word.right - word.left)) / 2.0
                word.left -= pad
                word.right += pad

    # 上下边：按每个词自己的列区间再量一次行方向投影
    for word in spans:
        _, row_ink = _ink_profile(arr, word.left, word.right, y0, y1)
        if row_ink is None or not row_ink.any():
            continue
        ys = np.flatnonzero(row_ink)
        top = y0 + float(ys[0]) - 1.0
        bottom = y0 + float(ys[-1]) + 2.0
        if bottom - top >= 3.0:
            word.top = max(y0 - 2.0, top)
            word.bottom = min(y1 + 2.0, bottom)
            word.refined = True


def _split_line_words(text: str, box, arr=None, poly=(), line_id: str = "",
                      score: float = 0.0) -> list:
    """行内文字 → 词级框（贴合字形本体）。

    三步：① 加权字符宽度估算水平区间；② 墨迹投影吸附左右边、收紧上下边；
    ③ 用行四点插值出跟随倾斜的平行四边形。
    第 ② 步只在拿到原图（``arr``）时才做 —— 单测里允许只喂文本 + 框，
    那条路径退化成 ①② 的估算版，仍然比旧的「按字符数均分」准。
    """
    x0, y0, x1, y1 = box
    width = max(1.0, x1 - x0)
    cy = (y0 + y1) / 2.0
    out = []
    for m, left, right in _estimate_word_spans(text, box):
        frac_a = max(0.0, min(1.0, (left - x0) / width))
        frac_b = max(0.0, min(1.0, (right - x0) / width))
        out.append(OcrWord(text=m.group(0).lower(), cx=(left + right) / 2.0,
                           cy=cy, left=left, right=right, top=y0, bottom=y1,
                           poly=_interpolate_poly(poly, frac_a, frac_b),
                           confidence=score, line_id=line_id,
                           engine_id="rapid"))
    if arr is not None and out:
        try:
            _snap_edges(arr, box, out)
            for word in out:
                word.cx = (word.left + word.right) / 2.0
                word.cy = (word.top + word.bottom) / 2.0
                w_a = max(0.0, min(1.0, (word.left - x0) / width))
                w_b = max(0.0, min(1.0, (word.right - x0) / width))
                word.poly = _interpolate_poly(poly, w_a, w_b) or word.poly
        except Exception as error:                    # noqa: BLE001
            # 细化是「锦上添花」：任何异常都退回估算框，绝不能把整条识别链路带崩。
            # 但**不能连声响都没有** —— 2026-10-17 这里就静默吞掉过一个
            # `ValueError: not enough values to unpack`，表现成「所有词框都不收紧」，
            # 只能靠回归测试才发现。留下最近几条供评测/日志追查。
            REFINE_ERRORS.append("%r" % (error,))
            del REFINE_ERRORS[:-20]
    return out


#: OCR 推理的**默认** CPU 线程上限。
#: 为什么不是「不限」：`rapidocr_onnxruntime` 的 `OrtInferSession` 把
#: `SessionOptions` 写死了（只设日志级别 / 图优化等级），
#: `intra_op_num_threads` 留在默认值 0 = 「onnxruntime 你按机器核数自己开线程池」。
#: 本机 32 逻辑核，于是**一次识别把 27 个核点着**（`tools/sense_threads_probe.py`：
#: 满载核数中位 26.99、最大 32.95）—— 这就是「一开蜘蛛感应风扇就狂转」的原因：
#: 抓屏 114ms + 变化检测 6.5ms 都是单线程小活，尖峰全部来自这一发多核爆发，
#: 而感应每个 tick 都可能再来一发（bench 的「平均 1.2 个核」是含 93% 空闲的大平均）。
#: 夹到 2 是用户 2026-10-18 的决定（最凉），实测同一批合成行：
#: 满载核数 26.99 → 3.14，单次中位 160.7ms → 71.7ms，读出总行数 16 → 16（没掉行）。
#: 口径要说清楚：那是**便宜形状**（清晰、单行）；「贵的形状」（低对比小字、
#: 回退阶梯全跑）夹核后单轮更慢、更容易撞 §7.4 的降频/暂停判据 —— 那一组数
#: 要重跑 `tools/sense_bench.py` 才有，未运行。
DEFAULT_THREAD_LIMIT = 2

#: 当前夹到几个核（`None` = 不夹，让 onnxruntime 按核数开）。
_THREAD_LIMIT = DEFAULT_THREAD_LIMIT


def thread_limit():
    """当前夹到几个核（`None` = 没夹）。给日志 / 状态用，别把默认值说成用户设置值。"""
    return _THREAD_LIMIT


def set_thread_limit(threads) -> None:
    """把 OCR 推理的 CPU 线程池夹到 N 个核。**必须在模型第一次加载之前调用**
    （会话建好之后再改就不生效了）。

    为什么要夹：`rapidocr_onnxruntime` 的 `OrtInferSession` 把 `SessionOptions`
    写死了 —— 只设日志级别和图优化等级，`intra_op_num_threads` 留在默认值 0，
    而 0 的意思是「onnxruntime 你按机器核数自己开线程池」。本机 32 逻辑核，
    于是一次识别把 **27 个核**点着（满载核数 = 同一次识别的
    `process_time / wall`，`tools/sense_threads_probe.py`），风扇听见的正是
    这个**瞬时**爆发（`bench_report.md` 里「平均 1.2 个核」是含 93% 空闲的
    整段大平均，两回事）。

    代价必须一起看：夹小 = 同样的算力摊到更少的核上 = **单次识别更慢**，
    而 §7.4 的降频 / 自动暂停判据量的是「近 5 轮中位延迟」，
    所以线程预算和延迟预算要一起调；只夹不重测，表现成「感应开一会儿自己暂停」
    是预料中的事。
    """
    global _THREAD_LIMIT
    try:
        n = int(threads)
    except (TypeError, ValueError):
        n = 0
    _THREAD_LIMIT = n if n > 0 else None


def _build_engine():
    """建 RapidOCR 实例；`_THREAD_LIMIT` 有值就在**建会话那一刻**把线程数按进去。

    要套两层是因为：`SessionOptions` 一旦传进 `InferenceSession` 就改不动了，
    而 rapidocr 是在它自己模块里 `from onnxruntime import InferenceSession`
    —— 所以补的是**它模块里的那个名字**（改 `onnxruntime.InferenceSession`
    对它没有任何影响，它手里拿的是导入时绑好的那个）。建完立刻还原，
    不把补丁留给别人的代码。
    """
    from rapidocr_onnxruntime import RapidOCR
    if _THREAD_LIMIT is None:
        return RapidOCR()
    import rapidocr_onnxruntime.utils as utils
    original = getattr(utils, "InferenceSession", None)
    if original is None:                        # 版本换了 / 结构不同：不夹，也别崩
        return RapidOCR()
    limit = _THREAD_LIMIT

    def _session(model_path, sess_options=None, **kwargs):
        if sess_options is not None:
            sess_options.intra_op_num_threads = limit
            sess_options.inter_op_num_threads = 1
        return original(model_path, sess_options=sess_options, **kwargs)

    utils.InferenceSession = _session
    try:
        return RapidOCR()
    finally:
        utils.InferenceSession = original


class OcrEngine:
    """延迟加载的 RapidOCR 单例。"""

    _engine = None
    _error = None
    _init_seconds = None
    #: 最近一次用到引擎的 monotonic 时间。空闲释放靠它判断。
    _last_used = 0.0
    #: 模型构造的互斥锁。2026-10-17：预热改在后台线程做（见 main.py），
    #: 「预热线程」和「第一次识词」可能同时进 `get()` —— RapidOCR 构造不便宜，
    #: 双实例既浪费内存又可能撞 onnxruntime 的全局状态，这里用锁保证只建一次。
    _lock = threading.Lock()

    @classmethod
    def loaded(cls) -> bool:
        return cls._engine is not None

    @classmethod
    def touch(cls) -> None:
        cls._last_used = time.monotonic()

    @classmethod
    def idle_seconds(cls) -> float:
        return time.monotonic() - cls._last_used if cls._last_used else 0.0

    @classmethod
    def release(cls) -> bool:
        """卸载模型，把常驻内存还给系统。

        onnxruntime 的 session 一旦建好就钉住 ~90MB（三份模型 + 各自的工作区），
        背单词的人可能一小时才框选一次屏幕，让它整天占着不划算。
        下次 `get()` 会自动重建（约 1~2 秒，期间界面照常响应）。

        返回是否真的释放过 —— 重复调用是安全的。
        """
        with cls._lock:
            if cls._engine is None:
                return False
            cls._engine = None
            cls._init_seconds = None
        import gc
        gc.collect()
        return True

    @classmethod
    def available(cls) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except Exception as error:            # noqa: BLE001
            cls._error = str(error)
            return False

    @classmethod
    def warmup(cls) -> None:
        """后台预热：把模型加载的一次性开销挪到启动阶段。"""
        try:
            cls.get()
        except Exception:                     # noqa: BLE001
            pass

    @classmethod
    def get(cls):
        if cls._engine is not None:
            cls.touch()
            return cls._engine
        with cls._lock:
            if cls._engine is None:            # 双检：等锁期间别人可能已建好
                t0 = time.time()
                cls._engine = _build_engine()
                cls._init_seconds = time.time() - t0
            cls.touch()
        return cls._engine

    @classmethod
    def recognize_lines(cls, img, upscale_below: int = None) -> list:
        """识别图像，返回行列表（含位置）。失败时返回空列表。

        ``img`` 可以是 QImage，也可以是已经转好的 ndarray。
        **在子线程里请务必传 ndarray**：QImage 的格式转换/拷贝属于 GUI 线程
        的操作，放到 worker 里做会让进程以退出码 127 直接崩掉（症状是
        ``done`` 信号永远收不到，而不是抛出一个可捕获的异常）。

        坐标一律还原到**原图像素**：内部会裁边/放大/补白/切条，
        但对外暴露的必须是用户框选的原图坐标，否则八条腿会踩到错位的地方。
        ``upscale_below`` 是旧版参数，已废弃（新链路自适应档位），仅为兼容保留。
        """
        arr = img if isinstance(img, np.ndarray) else qimage_to_ndarray(img)
        if arr is None or arr.size == 0:
            return []
        arr = np.ascontiguousarray(arr)
        if not arr.flags.writeable:
            arr = arr.copy()

        try:
            engine = cls.get()
        except Exception as error:            # noqa: BLE001
            cls._error = str(error)
            return []

        crop, ox, oy = _autocrop(arr)
        bg = _border_bg(crop)
        # 多行短带先按行切开（单行/整页自动跳过，见 _line_bands 与下方回退）
        bands = _line_bands(crop, bg)
        # ★ 2026-10-19 深夜**回退**：恢复「带数 > 8 或图高 ≥600 就整块送」。
        #   我曾把这条删掉、改成一律逐带，理由是合成图基准上逐带更快。但在
        #   真实整屏截图上逐带反而更糟：一是同一行被上下两条带各读一次，
        #   二是行距紧的界面（终端 / IDE）里行带之间会互相抢到邻行的笔画，
        #   框的位置和宽度都跟着漂。老规则对「整页/大块选区」直接整块送，
        #   恰好避开这两种情况。小选区（≤8 行且高度 <600）仍然逐带，
        #   和用户日常框一句话的场景一致。
        if len(bands) > LEGACY_MAX_SPLIT_BANDS or (
                len(bands) > 1 and crop.shape[0] >= 600):
            bands = [(crop, 0, 0)]

        jobs = [(index, band, bx, by)
                for index, (band, bx, by) in enumerate(bands)]
        total_deadline = time.perf_counter() + OCR_TOTAL_BUDGET_MS / 1000.0
        if len(jobs) > 1 and BAND_WORKERS > 1:
            # 带与带互不依赖，几条一起跑；`map` 保序，拼回去的顺序与串行一致。
            # 每条带内部**一次调用都没少**（档位阶梯原样保留），只改了「谁来跑」。
            with ThreadPoolExecutor(max_workers=min(BAND_WORKERS,
                                                    len(jobs))) as pool:
                groups = list(pool.map(
                    lambda job: cls._band_lines(engine, job, arr, ox, oy, bg),
                    jobs))
        else:
            groups = []
            for job in jobs:
                # 整轮兜底：超时就不再加新带（已读到的照常返回）。
                # 至少跑完第一条：否则一行都读不出时用户会以为功能坏了。
                if groups and time.perf_counter() >= total_deadline:
                    if _debug():
                        print("[ocr] 整轮预算用尽 · 已跑 %d/%d 条带"
                              % (len(groups), len(jobs)))
                    break
                groups.append(cls._band_lines(engine, job, arr, ox, oy, bg))

        best = []
        for group in groups:
            # 去重：保留该带最完整的一行，去掉被覆盖的局部/重复读次
            best.extend(_dedup_lines(group))

        # 按阅读顺序（上→下、左→右）排序，避免卡片里词序错乱
        best.sort(key=lambda ln: (round(ln.box[1] / 12.0), ln.box[0]))
        return best

    @classmethod
    def _band_lines(cls, engine, job, arr, ox: int, oy: int, bg: tuple) -> list:
        """一条行带的完整档位阶梯（从 `recognize_lines` 里搬出来的同一套逻辑）。

        抽出来是为了能被线程池并发调用 —— 里面的临时变量（`band_lines` /
        `first` / `glue_retry`）全是这一条带私有的，没有共享状态。

        ★ 一条带自己崩掉**不许连累整页**：以前异常会一路冒到 `recognize_lines`，
          调用方拿到空列表、整页的词全没了。现在这里兜住，已经读到的行照常返回。
        """
        band_index, band, bx, by = job
        band_w = band.shape[1]
        band_lines = []
        first = True
        glue_retry = 0
        #: 这条带已经花掉几次推理、什么时候必须收手（见 `BAND_CALL_BUDGET`）。
        calls = 0
        deadline = time.perf_counter() + BAND_TIME_BUDGET_MS / 1000.0
        try:
            with _band_gate:                  # 全局最多 BAND_WORKERS 条带在跑
                for plan_index, (scaled, factor, sx, sy, ax, ay,
                                 stoppable, strict) in enumerate(
                        _plans_for(band, ox + bx, oy + by, bg)):
                    # 预算闸门：读不出的带不许把整轮拖成十几秒。
                    # 放在档位开头而不是内层，是为了「已经拿到的行」照常返回。
                    if (calls >= BAND_CALL_BUDGET
                            or time.perf_counter() >= deadline):
                        if _debug():
                            print("[ocr] band=%d 预算用尽（%d 次调用 / %d ms）"
                                  " → 收工，带回 %d 行"
                                  % (band_index, calls, BAND_TIME_BUDGET_MS,
                                     len(band_lines)))
                        break
                    threshold = (FIRST_PASS_SCORE if (first or strict)
                                 else GOOD_SCORE)
                    stop = False
                    # 同一档最多试三种变体：原图 → 对比度拉伸 → Otsu 二值化。
                    # 直出已可用（top >= 0.5）就别在同档上花时间，直接看下一档。
                    for step in (0, 1, 2):
                        if step == 0:
                            image = scaled
                        elif step == 1:
                            image = _contrast_variant(scaled)
                        else:
                            image = _otsu_variant(scaled)
                        if image is None:
                            continue
                        calls += 1
                        try:
                            result, _ = engine(np.ascontiguousarray(image))
                        except Exception as error:    # noqa: BLE001
                            cls._error = str(error)
                            continue
                        lines = cls._to_lines(result or [], factor, sx, sy, ax, ay,
                                              arr=arr,
                                              line_id="L%d_%d" % (band_index,
                                                                   plan_index))
                        top = max((ln.score for ln in lines), default=0.0)
                        # 「能不能收工」只看**断得出词**的读次：粘连版分数再高也没用，
                        # 继续往下走（补白那一档往往就能正确断词）。
                        clean = max((ln.score for ln in lines
                                     if not _glued(ln.text)), default=0.0)
                        if _debug():
                            print("[ocr] band=%d step=%d f=%d in=%dx%d -> %d 行"
                                  " top=%.2f clean=%.2f"
                                  % (band_index, step, factor,
                                     image.shape[1], image.shape[0],
                                     len(lines), top, clean))
                        if lines:
                            band_lines = _merge_lines(band_lines, lines)
                        # ★ 回退：收工判据看**置信度**（原版行为），不看「有没有断出词」。
                        #   看断词会让粘连读次拒绝收工、继续加档，真实截图上每条带
                        #   都多跑一两轮推理，整体更慢。
                        if stoppable and top >= threshold:
                            stop = True   # 这一档已经读得足够干净，别再花时间加档
                            break
                        if step == 0 and top < 0.5:
                            continue      # 直出没读出东西 → 同图试对比度/二值化
                        break             # 直出可用，或变体已试完 → 下一档
                    # 某条切条已经读出覆盖整带宽度的整行 → 这条带读全了，不必再切
                    if _covers_full(band_lines, band_w):
                        break
                    if stop:
                        break             # 该档已读干净（直送/补白整图够好）
                    # 粘连读次：分数够、但断不出词。给**下一档 `GLUE_RETRY` 次**
                    # 机会（补白那一档常能救回来），救不回来就认 —— 再往下就是切条和
                    # 4842×738 的巨图，为一行字不值。
                    if glue_retry:
                        glue_retry -= 1
                        if max((ln.score for ln in band_lines
                                if not _glued(ln.text)), default=0.0) < threshold:
                            break
                    elif top >= threshold:
                        if GLUE_RETRY > 0:
                            glue_retry = GLUE_RETRY
                        else:
                            # 老行为（GLUE_RETRY=0）：分数够就收工，不额外补一刀
                            break
                    first = False
        except Exception as error:            # noqa: BLE001
            cls._error = str(error)
            if _debug():
                print("[ocr] band=%d 识别中断: %r" % (band_index, error))
        return band_lines

    @classmethod
    def _to_lines(cls, result, factor: int,
                  sub_x: float = 0.0, sub_y: float = 0.0,
                  add_x: float = 0.0, add_y: float = 0.0,
                  arr=None, line_id: str = "") -> list:
        """RapidOCR 原始结果 → OcrLine 列表。

        坐标还原：``原图 = (缩放图坐标 - 补白偏移) / factor + 裁边偏移``。
        ★ 四点（`poly`）和 AABB 走**同一套**还原公式，词框才能既对齐又跟着倾斜走。
        """
        lines = []
        for item in result:
            try:
                box, text, score = item[0], str(item[1]), float(item[2])
            except Exception:                 # noqa: BLE001
                continue
            xs = [(float(p[0]) - sub_x) / factor + add_x for p in box]
            ys = [(float(p[1]) - sub_y) / factor + add_y for p in box]
            rect = (min(xs), min(ys), max(xs), max(ys))
            poly = cls._ordered_poly(xs, ys)
            lines.append(OcrLine(text=text, box=rect, score=score,
                                 poly=poly, line_id=line_id,
                                 words=_split_line_words(text, rect, arr=arr,
                                                         poly=poly,
                                                         line_id=line_id,
                                                         score=score)))
        return lines

    @staticmethod
    def _ordered_poly(xs, ys) -> tuple:
        """把检测端给的任意顺序四点整成 tl,tr,br,bl。

        整不出来就退回 AABB 四角 —— 下游 `_interpolate_poly` 只依赖「前两点是上沿、
        后两点是下沿、顺序对应」这个约定。
        """
        if len(xs) != len(ys) or len(xs) < 4:
            return ((min(xs), min(ys)), (max(xs), min(ys)),
                    (max(xs), max(ys)), (min(xs), max(ys)))
        pts = sorted(zip(xs, ys), key=lambda p: (p[1], p[0]))
        top = sorted(pts[:2], key=lambda p: p[0])
        bottom = sorted(pts[2:] if len(pts) >= 4 else pts[-2:], key=lambda p: p[0])
        return (top[0], top[1], bottom[1], bottom[0])

    @classmethod
    def recognize_text(cls, img: QImage) -> str:
        """只要纯文本时的便捷入口。"""
        return "\n".join(ln.text for ln in cls.recognize_lines(img))

    @classmethod
    def stats(cls) -> dict:
        return {"available": cls.available(), "error": cls._error,
                "initSeconds": cls._init_seconds, "threads": _THREAD_LIMIT}


# ---------------------------------------------------------------- 引擎状态出口
#
# WorkBuddy 的 UI 发现层约定用 `getattr(ocr_engine, "describe_engines")` 取真实状态
# （见 `communite/messages/20261017-232700_*`）。这些函数的**实现**在
# `ocr_adapter.py`（引擎层），这里只做**惰性转发**：
#   · 不能在模块顶部 import ocr_adapter —— adapter 反过来要 import 本模块，循环导入；
#   · PEP 562 的模块级 `__getattr__` 让「取不到时才转发」，两边都零副作用。

_ADAPTER_EXPORTS = ("describe_engines", "current_engine", "set_engine",
                    "configure", "probe", "probe_state", "recognize",
                    "engine_status", "engine_lines",
                    "OCRWord", "OCRLine", "OCRResult",
                    "ENGINE_RAPID", "ENGINE_PADDLE")


def __getattr__(name):                                  # noqa: N802
    if name in _ADAPTER_EXPORTS:
        import ocr_adapter
        return getattr(ocr_adapter, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
