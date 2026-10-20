# -*- coding: utf-8 -*-
"""排障探针 2：真桌面上把字幕窗口**直接喂给引擎**，看它到底读到了什么。

`tools/sense_coord_probe.py` 量到的事实是：字幕窗口整张都在 ROI 裁片里
（框 (0,958,1970,642) ⊇ 卡片图像矩形 (589,1138,1380,345)），
`engine_lines` 从这一块读回 14 个词，**框内 0 个**、也没有一个是这句字幕里的词。
而词典侧是干净的：同一句 `scan_text` 稳定回 5 个候选
（consequence / aggressive / eliminate / approach / duplicate）。
所以问题只能在「抓到的这张图 → 引擎」这一段。这里把那段单独拎出来：

    1. 真抓屏，取卡片自己的图像矩形 → 送引擎（贴脸裁片）
    2. 同一帧取线上那块并集 ROI → 送引擎（线上路径）
    3. 同一帧取整帧 → 送引擎
    4. 离线把卡片 `render()` 成图 → 送引擎（排除「抓屏没抓到这张窗」这种可能）

★ 隐私：这张探针打的文本**全是测试自己写上去的那句**，不打屏幕上别的内容；
  别的区域只打计数与坐标。

跑法：``python tools/sense_card_probe.py``（要真桌面）
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

SANDBOX = os.path.join(tempfile.gettempdir(), "lexara_card_probe")
os.makedirs(SANDBOX, exist_ok=True)
os.environ["APPDATA"] = SANDBOX
os.environ["LOCALAPPDATA"] = SANDBOX
os.environ["LEXARA_OCR_DEBUG"] = "1"

from PySide6.QtCore import QPoint                     # noqa: E402
from PySide6.QtGui import QGuiApplication             # noqa: E402
from PySide6.QtWidgets import QApplication           # noqa: E402

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
    from sense_e2e import SubtitleWindow
    from pet_window import qimage_to_ndarray
    if not OcrEngine.available():
        print("OCR 不可用")
        return 1

    card = SubtitleWindow(SENTENCE)
    card.show_at_bottom()
    APP.processEvents()
    pump(1.2)                                  # 真渲染一帧，别拿还没画出来的图
    pos = card.mapToGlobal(QPoint(0, 0))
    rect = (float(pos.x()), float(pos.y()), float(card.width()),
            float(card.height()))
    pixmap, geo, dpr = cap.grab_virtual_desktop()
    array = qimage_to_ndarray(pixmap.toImage())
    print("桌面图像 %s · dpr=%.2f · 原点=%s" % (array.shape[:2], dpr,
                                                (geo.x(), geo.y())))
    print("卡片逻辑矩形 %s → 图像矩形 %s" % (
        rect, tuple(int(round(v)) for v in (
            (rect[0] - geo.x()) * dpr, (rect[1] - geo.y()) * dpr,
            rect[2] * dpr, rect[3] * dpr))))

    ix, iy = int((rect[0] - geo.x()) * dpr), int((rect[1] - geo.y()) * dpr)
    iw, ih = int(rect[2] * dpr), int(rect[3] * dpr)

    pad = 24

    def run(tag, crop, ox, oy):
        """一块裁片送引擎，按**生产同款**坐标系算落点。

        生产里是 `screen = 桌面逻辑原点 + (裁片在图像里的偏移 + 词在该裁片里的像素)
        / dpr`（`SenseWorker._recognize`）。★ 之前这版探针把「图像像素偏移」当成
        「逻辑偏移」直接相加，算出来的落点整块偏了 1.5 倍 —— 那是**探针自己的错**，
        这里按生产的公式重写，别再拿错坐标去指控产品。
        """
        started = time.time()
        lines = ocr_adapter.engine_lines(crop)[0]
        ms = (time.time() - started) * 1000.0
        ox2, oy2 = ox / dpr + geo.x(), oy / dpr + geo.y()
        inside = 0
        for ln in lines:
            for wd in getattr(ln, "words", []) or []:
                px, py = ox2 + wd.cx / dpr, oy2 + wd.cy / dpr
                if rect[0] - 14 <= px <= rect[0] + rect[2] + 14 \
                        and rect[1] - 14 <= py <= rect[1] + rect[3] + 14:
                    inside += 1
        own = sorted({w for ln in lines
                      for w in (ln.text or "").lower().split() if w in WORDS})
        print("  %-10s %6.0fms · 行 %2d · 落进卡片 %2d · 这句的词 %s"
              % (tag, ms, len(lines), inside, own or "（一个都没读到）"))

    print("\n[1] 卡片自己那一块（贴脸裁片，±24px 余量）")
    run("card", array[max(0, iy - pad):iy + ih + pad,
                      max(0, ix - pad):ix + iw + pad],
        max(0, ix - pad), max(0, iy - pad))

    print("\n[2] 线上那块并集 ROI（图像 y 958~1600 全宽）")
    run("union", array[958:1600, 0:1970], 0, 958)

    print("\n[2b] 同一块，只把**行**收到卡片那几行（列还是全带宽）")
    run("rows-only", array[max(0, iy - pad):iy + ih + pad, 0:1970],
        0, max(0, iy - pad))

    print("\n[2c] 只把**列**收到卡片那段（行还是整条并集带）")
    run("cols-only", array[958:1600, max(0, ix - pad):ix + iw + pad],
        max(0, ix - pad), 958)

    print("\n[2e] **线上路径**：并集带交给 `SenseWorker._tighten_crop` 收到哪块")
    from sense_worker import SenseWorker
    band = array[958:1600, 0:1970]
    tight = SenseWorker._tighten_crop(band)
    if tight is None:
        print("  _tighten_crop 返回 None（不收）　← 那这条带还是读不到句子")
    else:
        t0, th, l0, tw = tight
        print("  收到 (行 %d+%d, 列 %d+%d) / 原 642x1970" % (t0, th, l0, tw))
        run("tight", band[t0:t0 + th, l0:l0 + tw], l0, 958 + t0)

    print("\n[3] 整帧")
    run("full", array, 0, 0)

    print("\n[4] 离线渲染同一张卡片（绕开抓屏，看引擎认不认这种样式）")
    pix = card.grab()
    off = qimage_to_ndarray(pix.toImage())
    print("  离线的形状 %s" % (off.shape[:2],))
    lines = ocr_adapter.engine_lines(off)[0]
    print("  离线读到 %d 行，文本：%r"
          % (len(lines), [ln.text for ln in lines][:3]))

    print("\n[5] 卡片那块区域的像素统计（背景/前景有没有对比）")
    seg = array[iy:iy + ih, ix:ix + iw]
    import numpy as np
    gray = seg.astype(np.int32).mean(axis=2) if seg.ndim == 3 else seg
    print("  形状 %s · 均值 %.1f · 标准差 %.1f · 最亮 1%% 分位 %.0f · 行标准差"
          " min/中位/max %.1f/%.1f/%.1f"
          % (gray.shape, gray.mean(), gray.std(),
             np.percentile(gray, 99),
             gray.std(axis=1).min(), float(np.median(gray.std(axis=1))),
             gray.std(axis=1).max()))
    card.close()
    APP.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
