"""把识别框画回原图，用于目视确认「框还乱不乱」。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np                                              # noqa: E402
from PIL import Image, ImageDraw                                # noqa: E402

import ocr_engine as OE                                         # noqa: E402

SHOT = r"C:\Users\35388\Desktop\屏幕截图 2026-10-18 152551.png"
OUT = os.path.join(os.path.dirname(__file__), "..", "dist", "shape",
                   "ocr_boxes_after_fix.png")


def main():
    rgb = np.array(Image.open(SHOT).convert("RGB"))
    arr = np.ascontiguousarray(rgb[:, :, ::-1])
    OE.OcrEngine.recognize_lines(arr)                    # 预热
    lines = OE.OcrEngine.recognize_lines(arr)
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    for ln in lines:
        x0, y0, x1, y1 = ln.box
        draw.rectangle([x0, y0, x1, y1], outline=(220, 60, 60), width=2)
    img.save(OUT)
    print("框 %d 个 → %s" % (len(lines), OUT))


if __name__ == "__main__":
    main()
