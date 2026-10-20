"""真实截图 · 串行版绝对耗时（回退后自检）。

只回答一个问题：现在这条链路在真实截图上，一次框选要多久、能不能切出词。
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


def main():
    arr = load(SHOT)
    print("截图 %dx%d" % (arr.shape[1], arr.shape[0]))
    OE.OcrEngine.get()
    crop, ox, oy = OE._autocrop(arr)
    bands = OE._line_bands(crop, OE._border_bg(crop))
    print("行带 %d 条 · 串行 %d 路\n" % (len(bands), OE.BAND_WORKERS))
    if not bands:
        return

    def region(lo, hi):
        top = max(0, min(int(b[2]) for b in bands[lo:hi]) - 6)
        bot = min(arr.shape[0],
                  max(int(b[2] + b[0].shape[0]) for b in bands[lo:hi]) + 6)
        return np.ascontiguousarray(arr[top:bot])

    for tag, sel in (("3 行", region(0, min(3, len(bands)))),
                     ("8 行", region(0, min(8, len(bands)))),
                     ("全部", region(0, len(bands)))):
        OE.OcrEngine.recognize_lines(sel)          # 预热这一尺寸
        times, lines = [], []
        for _ in range(3):
            t0 = time.perf_counter()
            lines = OE.OcrEngine.recognize_lines(sel)
            times.append((time.perf_counter() - t0) * 1000.0)
        text = "\n".join(ln.text for ln in lines)
        words = [w for w in text.replace("\n", " ").split() if len(w) > 1]
        glued = sum(1 for ln in lines if " " not in ln.text and len(ln.text) > 7)
        print("%-5s 中位 %5.0fms（首次 %5.0fms） %2d 行 %3d 词  粘连行 %d"
              % (tag, statistics.median(times), times[0], len(lines),
                 len(words), glued))


if __name__ == "__main__":
    main()
