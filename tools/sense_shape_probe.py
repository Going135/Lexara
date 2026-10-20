# -*- coding: utf-8 -*-
"""排障探针 3：OCR 的贵与不贵，究竟取决于**哪种切法**。

现场（`dist/sense/coord_probe3.log`，本机 2026-10-18，真桌面 + 真字幕窗口）：

    整帧            2560x1600 → 18966ms（读得到句子，但一轮就是 19 秒）
    并集带（线上）    642x1970  →  3471ms（读不到句子：框内 0/14）
    单格 ROI         638x740   →  2270ms（只读到 2 个词，句子不在里面）
    收到卡片（行+列） 393x1428  →   922ms（读到整句，见 card_probe）

`SenseWorker._tighten_crop` 修好之后（`card_probe3.log`）线上那块是
「行 0+505 · 列 0+1970」= **3383ms**：句子读到了，但一条真桌面带里
混着别的行的内容，收紧只收掉 137 行，仍然要跑 3.4 秒 ——
离 §7.4 的 1200ms 预算还差很远，会话于是连着降频到 0.4、再自动暂停。

所以这里只问一件事：**把同一块内容切成什么形状，引擎最便宜、又读得到句子**。
候选切法都在真抓到的帧上做，每种打完各自的耗时与落进卡片的词数：

    A 线上（`_tighten_crop` 一整块）
    B 按行段切（`_content_span` 挑出来的每一段单独送）
    C A 横切 2 条（重叠 60px）
    D A 横切 3 条（重叠 60px）
    E B 的每段再横切 2 条
    F 整帧横切 3 条（看「整帧那一轮」有没有便宜办法）
    G 单格 ROI 那种 740x638 横切 2 条

★ 隐私：打的文本**全是测试自己写上去的那句字幕**；屏幕上别的内容只打计数。
★ 这里不改产品代码，纯测量；跑法 ``python tools/sense_shape_probe.py``（要真桌面）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
sys.path.insert(0, os.path.join(BASE, "tools"))

SANDBOX = os.path.join(tempfile.gettempdir(), "lexara_shape_probe")
os.makedirs(SANDBOX, exist_ok=True)
os.environ["APPDATA"] = SANDBOX
os.environ["LOCALAPPDATA"] = SANDBOX

import numpy as np                                        # noqa: E402
from PySide6.QtCore import QPoint                        # noqa: E402
from PySide6.QtGui import QGuiApplication                # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)
APP.setQuitOnLastWindowClosed(False)
SENTENCE = "an aggressive approach to eliminate the duplicate consequence"
WORDS = {w.strip(".,") for w in SENTENCE.lower().split()}


def pump(seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        APP.processEvents()
        time.sleep(0.01)


def main() -> int:
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("不许联网"))
    from ocr_engine import OcrEngine
    import ocr_adapter
    import capture as cap
    from sense_worker import SenseWorker
    from sense_session import SenseSession
    from sense_e2e import SubtitleWindow
    from pet_window import qimage_to_ndarray
    if not OcrEngine.available():
        print("OCR 不可用")
        return 1

    card = SubtitleWindow(SENTENCE)
    card.show_at_bottom()
    APP.processEvents()
    pump(1.2)
    pos = card.mapToGlobal(QPoint(0, 0))
    rect = (float(pos.x()), float(pos.y()), float(card.width()),
            float(card.height()))
    pixmap, geo, dpr = cap.grab_virtual_desktop()
    array = qimage_to_ndarray(pixmap.toImage())
    full_h, full_w = array.shape[:2]
    print("桌面图像 %dx%d · dpr=%.2f" % (full_h, full_w, dpr))
    print("卡片图像矩形 %s" % (tuple(int(round(v)) for v in (
        (rect[0] - geo.x()) * dpr, (rect[1] - geo.y()) * dpr,
        rect[2] * dpr, rect[3] * dpr)),))

    # 卡片在**线上那块并集带**里的行范围：带 = 底部三格的并集（同 coord_probe3）
    BAND = (958, 1600, 0, 1970)          # (起始行, 结束行, 起始列, 结束列)
    band = array[BAND[0]:BAND[1], BAND[2]:BAND[3]]
    print("线上并集带 %dx%d" % band.shape[:2])

    tot = {"ms": 0.0, "calls": 0}

    def run(tag, crop, ox, oy):
        """一块裁片送引擎，按生产同款坐标系算「落进卡片几个词」。"""
        started = time.time()
        lines = ocr_adapter.engine_lines(crop)[0]
        ms = (time.time() - started) * 1000.0
        tot["ms"] += ms
        tot["calls"] += 1
        ox2, oy2 = ox / dpr + geo.x(), oy / dpr + geo.y()
        inside = 0
        for ln in lines:
            for wd in getattr(ln, "words", []) or []:
                px, oy_ = ox2 + wd.cx / dpr, oy2 + wd.cy / dpr
                if (rect[0] - 14 <= px <= rect[0] + rect[2] + 14
                        and rect[1] - 14 <= oy_ <= rect[1] + rect[3] + 14):
                    inside += 1
        own = sorted({w for ln in lines
                      for w in (ln.text or "").lower().split() if w in WORDS})
        print("    %-14s %5dx%-5d %6.0fms · 行 %2d · 框内 %2d · 这句的词 %s"
              % (tag, crop.shape[0], crop.shape[1], ms, len(lines), inside,
                 own or "（没读到）"))
        return ms, own

    def rows_of(crop):
        """按行内容段切：返回 `[(起行, 止行)]`（含 `TIGHT_MARGIN` 余量）。"""
        g = crop.astype(np.int32).mean(axis=2)
        step = max(1, crop.shape[1] // 640)
        ink = g[:, ::step].std(axis=1)
        score = np.where(ink > SenseWorker.TIGHT_ROW_STD, ink, 0.0)
        hit = np.flatnonzero(score > 0)
        if hit.size == 0:
            return []
        runs, start, prev = [], int(hit[0]), int(hit[0])
        for value in hit[1:]:
            value = int(value)
            if value - prev > SenseWorker.TIGHT_GAP:
                runs.append((start, prev + 1))
                start = value
            prev = value
        runs.append((start, prev + 1))
        totals = [(a, b, float(score[a:b].sum())) for a, b in runs]
        peak = max(item[2] for item in totals)
        out = []
        m = SenseWorker.TIGHT_MARGIN
        rows = crop.shape[0]
        for a, b, total in totals:
            if b - a < SenseWorker.TIGHT_MIN_SPAN:
                continue
            if total < SenseWorker.TIGHT_MIN_SHARE * peak:
                continue
            out.append((max(0, a - m), min(rows, b + m), total))
        return out

    def col_split(crop, parts, overlap=60):
        """横切成 `parts` 条（相邻重叠 `overlap` 列，免得把词从中间切开）。"""
        cols = crop.shape[1]
        if parts <= 1 or cols < 400:
            return [(0, cols, crop)]
        step = (cols + overlap) / float(parts)
        out = []
        for i in range(parts):
            a = int(round(max(0, i * step - (overlap if i else 0))))
            b = int(round(min(cols, a + step + overlap)))
            if b - a >= 200:
                out.append((a, b, crop[:, a:b]))
        return out or [(0, cols, crop)]

    print("\n[A] 线上形状：`_tighten_crop` 收出来那一整块")
    tight = SenseWorker._tighten_crop(band)
    box_a = None
    if tight is None:
        print("    _tighten_crop 返回 None（不收）→ 用原带")
        box_a = (0, band.shape[0], 0, band.shape[1])
    else:
        t0, th, l0, tw = tight
        box_a = (t0, t0 + th, l0, l0 + tw)
        print("    收到 (行 %d+%d, 列 %d+%d) / 原 %dx%d"
              % (t0, th, l0, tw, band.shape[0], band.shape[1]))
        run("A 一整块", band[t0:t0 + th, l0:l0 + tw],
            BAND[2] + l0, BAND[0] + t0)

    print("\n[B] 同一块带按**行段**切，每段单独送（列不动）")
    rsum = 0.0
    for i, (a, b, _total) in enumerate(rows_of(band)):
        rsum += run("B 行段%d" % i, band[a:b, :], BAND[2], BAND[0] + a)[0]
    print("    小计 %.0fms（%d 段）" % (rsum, len(rows_of(band))))

    print("\n[C] A 那块横切 2 条")
    if tight is not None:
        sub = band[box_a[0]:box_a[1], box_a[2]:box_a[3]]
        for i, (a, b, piece) in enumerate(col_split(sub, 2)):
            run("C 条%d" % i, piece, BAND[2] + box_a[2] + a, BAND[0] + box_a[0])

    print("\n[D] A 那块横切 3 条")
    if tight is not None:
        for i, (a, b, piece) in enumerate(col_split(sub, 3)):
            run("D 条%d" % i, piece, BAND[2] + box_a[2] + a, BAND[0] + box_a[0])

    print("\n[E] 行段 × 每段横切 2 条")
    esum = 0.0
    for i, (a, b, _t) in enumerate(rows_of(band)):
        for j, (ca, cb, piece) in enumerate(col_split(band[a:b, :], 2)):
            esum += run("E 段%d条%d" % (i, j), piece,
                        BAND[2] + ca, BAND[0] + a)[0]
    print("    小计 %.0fms" % esum)

    print("\n[F] 整帧横切 3 条（整帧那一轮有没有便宜办法）")
    for i, (a, b, piece) in enumerate(col_split(array, 3)):
        run("F 帧条%d" % i, piece, a, 0)

    print("\n[G] 单格那种 740x638 的框横切 2 条（coord_probe3 里 2270ms 那块）")
    cell = array[0:638, 590:1330]
    ct = SenseWorker._tighten_crop(cell)
    base = cell if ct is None else cell[ct[0]:ct[0] + ct[1], ct[2]:ct[2] + ct[3]]
    boff = (0, 0) if ct is None else (ct[2], ct[0])
    for i, (a, b, piece) in enumerate(col_split(base, 2)):
        run("G 条%d" % i, piece, 590 + boff[0] + a, 0 + boff[1])

    print("\n合计：%d 次引擎调用 · %.0fms" % (tot["calls"], tot["ms"]))
    from sense_session import RECENT_WINDOW, DUTY_LIMIT_MS
    print("会话侧的预算参数：budget_ms=%.0f · 判据=近 %d 轮中位 · "
          "暂停线=%.0fms" % (SenseSession().budget_ms, RECENT_WINDOW,
                             DUTY_LIMIT_MS))
    card.close()
    APP.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
