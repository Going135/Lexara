# -*- coding: utf-8 -*-
"""新识别链路全场景回归（2026-10-17）。

覆盖真实使用会出现的全部形态，验收新 `recognize_lines`：
  1. 花式字体测试图（用户原始反馈的那两张）
  2. 宽扁单行（旧版必挂：内部放大后宽度爆表 → 检测端直接返回空）
  3. 宽扁段落 1920x150（同上）
  4. 整页小字 2200 宽
  5. 大画布 20/26px 正文
  6. 暗底（IDE / 暗色网页）
并断言：所有行框/词坐标都落在原图范围内（腿不能踩飞）。
"""

import os
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ocr_engine import OcrEngine                              # noqa: E402

FONT = r"C:\Windows\Fonts\segoeui.ttf"
SENTENCE = ("The quarterly release report shows revenue growth "
            "in every product segment this year")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if ok else "[FAIL]", name, detail))


def render(lines_text, font_px, dark=False, canvas_w=None):
    font = ImageFont.truetype(FONT, font_px)
    probe = Image.new("RGB", (10, 10))
    d0 = ImageDraw.Draw(probe)
    line_h = int(font_px * 1.9)
    widths = [d0.textbbox((0, 0), t, font=font)[2] for t in lines_text]
    w = canvas_w or (max(widths) + 80)
    h = line_h * len(lines_text) + 80
    bg, fg = ((30, 30, 30), (212, 212, 212)) if dark else ((255, 255, 255), (51, 51, 51))
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    y = 40
    for t in lines_text:
        d.text((40, y), t, font=font, fill=fg)
        y += line_h
    return np.asarray(img, dtype=np.uint8)


def run_case(tag, arr, word, min_hits, total=None):
    total = total or min_hits
    t0 = time.time()
    lines = OcrEngine.recognize_lines(arr)
    dt = time.time() - t0
    # 与应用同口径：数「词」不数「行」—— 整行被并成一行时词照样在
    hits = sum(1 for ln in lines for wd in ln.words if word in wd.text)
    h, w = arr.shape[:2]
    inside = all(0 <= ln.box[0] and ln.box[2] <= w + 1 and
                 0 <= ln.box[1] and ln.box[3] <= h + 1 for ln in lines)
    check(tag, hits >= min_hits and inside,
          "%.1fs hits=%d/%d 坐标%s" % (dt, hits, total,
                                       "ok" if inside else "越界!"))
    if not inside:
        for ln in lines:
            print("      越界行:", ln.text[:30], ln.box)


def main():
    OcrEngine.warmup()

    # 1) 用户原始的两张花式测试图
    for name, path, total in (
            ("release", r"C:\Users\35388\Desktop\2af1acd10c6efc98ab470d6b3510c816.png", 5),
            ("revenue", r"C:\Users\35388\Desktop\2ffaf0ed9e4a04531eda84a0711fe2fd.png", 5)):
        bgr = cv2.imread(path, cv2.IMREAD_COLOR)
        arr = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        lines = OcrEngine.recognize_lines(arr)
        hits = sum(1 for ln in lines for wd in ln.words if name in wd.text)
        check("花式图 %s" % name, hits >= total - 1,
              "hits=%d/%d %s" % (hits, total, [ln.text[:14] for ln in lines]))

    # 2) 宽扁单行（旧版必挂的死穴）
    for px in (14, 16, 20):
        one = render([SENTENCE], px)
        run_case("单行 %dpx (%dx%d)" % (px, one.shape[1], one.shape[0]),
                 one, "revenue", 1, 1)

    # 3) 宽扁段落 1920x150
    for px in (14, 16, 20):
        para = render([SENTENCE] * 3, px, canvas_w=1920)
        run_case("宽段落 %dpx 1920宽" % px, para, "revenue", 2, 3)

    # 4) 整页小字
    page = render([SENTENCE] * 20, 16, canvas_w=2200)
    run_case("整页 16px 20行", page, "revenue", 5, 20)

    # 5) 大画布正文
    for px in (20, 26):
        big = render([SENTENCE] * 6, px, canvas_w=2200)
        run_case("大画布 %dpx 6行" % px, big, "revenue", 5, 6)

    # 6) 暗底
    dark = render([SENTENCE] * 3, 18, dark=True)
    run_case("暗底 18px 3行", dark, "revenue", 2, 3)

    print("\n%s  通过 %d / 失败 %d" % ("=" * 46, len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
