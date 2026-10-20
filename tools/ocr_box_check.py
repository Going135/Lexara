"""回退后自检：看框还乱不乱。

判据（不是"看着像"）：
- 有没有**跨行巨框**：框高 > 中位行高 × 1.8，或框宽 > 选区宽 85% 但只有 1 个词；
- 有没有**同一位置重复框**：两个框 IoU > 0.6。
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np                                              # noqa: E402
from PIL import Image                                           # noqa: E402

import ocr_engine as OE                                         # noqa: E402

SHOT = r"C:\Users\35388\Desktop\屏幕截图 2026-10-18 152551.png"


def load(path):
    img = Image.open(path).convert("RGB")
    return np.ascontiguousarray(np.array(img)[:, :, ::-1])


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / max(1e-6, area)


def report(tag, arr, sel_w):
    OE.OcrEngine.recognize_lines(arr)                    # 预热
    t0 = time.perf_counter()
    lines = OE.OcrEngine.recognize_lines(arr)
    ms = (time.perf_counter() - t0) * 1000.0
    if not lines:
        print("%-8s %6.0fms  0 行" % (tag, ms))
        return
    heights = [ln.box[3] - ln.box[1] for ln in lines]
    mid = statistics.median(heights)
    wide = [ln for ln in lines
            if (ln.box[3] - ln.box[1]) > mid * 1.8
            or (ln.box[2] - ln.box[0]) > sel_w * 0.85]
    dup = 0
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            if iou(a.box, b.box) > 0.6:
                dup += 1
    print("%-8s %6.0fms  %2d 行  行高中位 %4.0f  跨行/全宽框 %d  重复框 %d"
          % (tag, ms, len(lines), mid, len(wide), dup))
    for ln in wide[:3]:
        print("     ⚠ %5.0f×%-4.0f  %r"
              % (ln.box[2] - ln.box[0], ln.box[3] - ln.box[1], ln.text[:50]))


def main():
    arr = load(SHOT)
    crop, ox, oy = OE._autocrop(arr)
    bands = OE._line_bands(crop, OE._border_bg(crop))
    print("截图 %dx%d · 行带 %d 条 · 留白 %.2f · 逐带上限 %d（高%d≥600→整块）\n"
          % (arr.shape[1], arr.shape[0], len(bands), OE.BAND_PAD_RATIO,
             OE.LEGACY_MAX_SPLIT_BANDS, arr.shape[0]))

    def region(lo, hi):
        top = max(0, min(int(b[2]) for b in bands[lo:hi]) - 6)
        bot = min(arr.shape[0],
                  max(int(b[2] + b[0].shape[0]) for b in bands[lo:hi]) + 6)
        return np.ascontiguousarray(arr[top:bot])

    for tag, sel in (("3 行", region(0, min(3, len(bands)))),
                     ("8 行", region(0, min(8, len(bands)))),
                     ("整屏", arr)):
        report(tag, sel, sel.shape[1])


if __name__ == "__main__":
    main()
