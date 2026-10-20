# -*- coding: utf-8 -*-
"""识别 → 出词的耗时基准（可重复跑，用来盯回归）。

用法：
    .venv/Scripts/python.exe tools/ocr_speed.py
    .venv/Scripts/python.exe tools/ocr_speed.py --words   # 顺带打印认出来的词与释义

指标：
    * 耗时：一轮 `recognize_lines` 的墙钟（本机取 2 次最小值）；
    * 行数：识别出的行数，必须等于真值行数（丢行 = 质量事故）；
    * 命中率：真值里的单词有多少出现在识别文本里（顺序无关）；
    * 「整块」列把 `MAX_SPLIT_BANDS` 压成 0 来复现 2026-10-19 之前
      「带数 > 8 就整块送」的行为，供对照 —— 那一列只用于比较，不是可选开关。
      注意：≤8 行的场景旧代码本来也逐带，所以那一列对它们只是「整块长什么样」的参考。
"""

import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import ocr_engine as OE                                    # noqa: E402

FONT = r"C:\Windows\Fonts\segoeui.ttf"
LINES = [
    "The quarterly release report shows revenue growth in every product segment",
    "Our operators reduced the changeover time by applying SMED principles",
    "Preventive maintenance scheduling depends on accurate tolerance measurement",
    "Employees should submit the completed assessment before the deadline",
    "The committee will consider the proposal during the next session",
]
LONG = ("The quarterly release report shows revenue growth in every product segment "
        "this year while our operators reduced the changeover time by applying SMED "
        "principles and preventive maintenance scheduling on every line")


def render(texts, font_px, bg=(255, 255, 255), fg=(40, 40, 40), pad=40):
    font = ImageFont.truetype(FONT, font_px)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    widths = [probe.textbbox((0, 0), t, font=font)[2] for t in texts]
    lh = int(font_px * 1.9)
    img = Image.new("RGB", (max(widths) + pad * 2, lh * len(texts) + pad * 2), bg)
    draw = ImageDraw.Draw(img)
    y = pad
    for text in texts:
        draw.text((pad, y), text, font=font, fill=fg)
        y += lh
    return __import__("numpy").asarray(img, dtype="uint8")


def hit_rate(text, truth):
    want = " ".join(truth.lower().split()).split()
    got = set(" ".join(text.lower().split()).split())
    return sum(1 for w in want if w in got) / max(1, len(want))


def measure(arr, split_bands):
    saved = OE.MAX_SPLIT_BANDS
    OE.MAX_SPLIT_BANDS = split_bands
    best, lines = None, []
    try:
        for _ in range(2):
            t0 = time.perf_counter()
            lines = OE.OcrEngine.recognize_lines(arr)
            ms = (time.perf_counter() - t0) * 1000.0
            best = ms if best is None else min(best, ms)
    finally:
        OE.MAX_SPLIT_BANDS = saved
    return best, lines


CASES = [
    ("单行 22px", LINES[:1], 22),
    ("三行 22px", LINES[:3], 22),
    ("五行 22px", LINES, 22),
    ("十行 16px", (LINES * 3)[:10], 16),
    ("廿四行 16px", (LINES * 5)[:24], 16),
    ("卅六行 16px", (LINES * 8)[:36], 16),
    ("十二行宽行", [LONG] * 12, 16),
    ("三行 14px", LINES[:3], 14),
    ("暗底三行", LINES[:3], 18),
]


def main() -> None:
    OE.OcrEngine.get()
    split_default = OE.MAX_SPLIT_BANDS
    print("引擎加载完成 · 线程 %s · 逐带上限 %d · 并发 %d\n"
          % (OE.thread_limit(), split_default, OE.BAND_WORKERS))
    head = ("%-14s %10s %10s %7s   %9s %9s"
            % ("场景", "整块(旧)", "逐带(现)", "倍数", "整块行/命中", "现行数/命中"))
    print(head)
    print("-" * len(head.encode("gbk", "ignore")))
    total_old = total_new = 0.0
    for tag, texts, px in CASES:
        bg, fg = ((28, 28, 30), (212, 212, 212)) if tag.startswith("暗底") else \
                 ((255, 255, 255), (40, 40, 40))
        arr = render(texts, px, bg=bg, fg=fg)
        truth = "\n".join(texts)
        # 旧行为：带数 > 8 就整块 → 复现成「永不再切」
        old_ms, old_lines = measure(arr, 0)
        new_ms, new_lines = measure(arr, split_default)
        total_old += old_ms
        total_new += new_ms
        print("%-14s %8.0fms %8.0fms %6.1fx   %2d行/%3.0f%%     %2d行/%3.0f%%"
              % (tag, old_ms, new_ms, old_ms / max(1.0, new_ms),
                 len(old_lines), hit_rate("\n".join(l.text for l in old_lines), truth) * 100,
                 len(new_lines), hit_rate("\n".join(l.text for l in new_lines), truth) * 100))
    print("-" * 60)
    print("%-14s %8.0fms %8.0fms %6.1fx"
          % ("合计", total_old, total_new, total_old / max(1.0, total_new)))

    if "--words" in sys.argv:
        from lexicon import Lexicon
        lex = Lexicon(os.path.join(ROOT, "assets", "ecdict.sqlite"),
                      os.path.join(ROOT, "assets", "exam-tags.sqlite"),
                      os.path.join(ROOT, "assets", "industry.sqlite"))
        arr = render((LINES * 5)[:24], 16)
        lines = OE.OcrEngine.recognize_lines(arr)
        t0 = time.perf_counter()
        words = lex.scan_text("\n".join(l.text for l in lines), mode="cet6", limit=48)
        lex_ms = (time.perf_counter() - t0) * 1000.0
        print("\n廿四行 → 词典挑词 %d 个 · %.0f ms" % (len(words), lex_ms))
        for word in words[:10]:
            print("    %-16s %s" % (word["lemma"], word["meaning"][:40]))


if __name__ == "__main__":
    main()
