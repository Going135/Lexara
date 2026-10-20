# -*- coding: utf-8 -*-
"""量一件决定架构的事：一块**很小的变化格 ROI** 在真实引擎下值多少钱，
按行段切开到底是省钱还是更贵。

起因（`dist/sense/e2e_run3.log` 的 [3] 失败现场）：真桌面上一次「显示字幕窗口」
只点亮 2 个格子，并成的 ROI 是 **80×84 物理像素**，一次 `_recognize` 花
**8489ms**（会话记的整轮中位 9117ms）→ 越过 2500ms 暂停线 → 两轮后自动暂停，
字幕里的词一个都没闪出来。

而 `dist/sense/shape_probe.log` 那组「切段更便宜」的数是**大**形状量出来的
（505×1970：整块 4657ms → 一行段 1254ms）。小格子是不是同一个规律，
必须单独量：`_plans_for` 对短边不足 `DET_LIMIT` 的图会**放大再切条**，
切出来的段越短，每一段都要各自跑一遍回退阶梯 —— 有可能切段在小块上
是**反效果**（段数 × 每段一整套阶梯）。

用法：`.venv/Scripts/python.exe tools/sense_smallroi_probe.py`
（不抓屏、不发网络：图是本地画的，只喂引擎。）
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

import numpy as np                                                # noqa: E402

LINE_A = "the aggressive approach eliminates duplicates"
LINE_B = "an approach to eliminate the duplicate entries"
# 真桌面上那两块格子的形状：每格 40×40 物理像素、两格竖着并成 80×84
CELL = 40
FONT_PX = 13


def make_line(text: str, width: int, height: int) -> np.ndarray:
    """把一行字画进一块 `height×width` 的图里（浅灰底、深灰字，贴近真桌面）。"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("L", (width, height), 235)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", FONT_PX)
    except Exception:                                       # noqa: BLE001
        font = ImageFont.load_default()
    d.text((2, max(0, (height - FONT_PX) // 2)), text, font=font, fill=40)
    g = np.asarray(img)
    return np.dstack([g, g, g]).astype(np.uint8)


def call(crop: np.ndarray, label: str, out: list) -> None:
    from ocr_engine import OcrEngine
    started = time.time()
    lines = OcrEngine.recognize_lines(crop)
    ms = (time.time() - started) * 1000.0
    out.append((label, ms, crop.shape[1], crop.shape[0], len(lines or []),
                max((ln.score for ln in lines or []), default=0.0)))
    print("  %-22s %5dx%-5d %8.1fms · 行 %2d · top %.2f"
          % (label, crop.shape[1], crop.shape[0], ms, len(lines or []),
             max((ln.score for ln in lines or []), default=0.0)))


def main() -> int:
    import ocr_engine
    print("引擎常量：DET_LIMIT=%s MAX_FACTOR=%s EFF_CAP=%s"
          % (getattr(ocr_engine, "DET_LIMIT", "?"),
             getattr(ocr_engine, "MAX_FACTOR", "?"),
             getattr(ocr_engine, "EFF_CAP", "?")))
    from sense_worker import SenseWorker
    rows = []
    # 整帧那轮走的是「不收紧 → 一整块」，小块 ROI 走的是 `_tighten_bands`；
    # 这里两种形状都造出来，直接比总价。
    two_stacked = np.vstack([make_line(LINE_A, CELL * 2, CELL),
                             make_line(LINE_B, CELL * 2, CELL)])
    print("\n[A] 并起来的 2 格 ROI（真桌面实测 80×84 那个形状）：整块一次送")
    call(two_stacked, "A 整块", rows)

    print("\n[B] 同一块按 `_tighten_bands` 切段，每段单独送（生产链路的做法）")
    bands = SenseWorker._tighten_bands(two_stacked)
    print("  切出 %d 段：%s" % (len(bands), bands))
    total = 0.0
    for index, (top, height, col, width) in enumerate(bands or []):
        sub = two_stacked[top:top + height, col:col + width]
        before = len(rows)
        call(sub, "B 段%d" % index, rows)
        total += rows[-1][1]
    if not bands:
        print("  （返回空 = 不收紧，等于 A）")

    print("\n[C] 每格单独送（不并块的样子）")
    for index, text in enumerate((LINE_A, LINE_B)):
        call(make_line(text, CELL * 2, CELL), "C 格%d" % index, rows)

    print("\n[D] 稍大一点的样子：1 格宽 × 2 行高但字号 24px（对照用）")
    big = np.vstack([make_line(LINE_A, 240, 34), make_line(LINE_B, 240, 34)])
    call(big, "D 240x68 整块", rows)
    for index, (top, height, col, width) in enumerate(
            SenseWorker._tighten_bands(big) or []):
        call(big[top:top + height, col:col + width], "D 段%d" % index, rows)

    print("\n" + "=" * 66)
    print("%-24s %8s %8s %8s %6s %6s"
          % ("形状", "宽", "高", "ms", "行", "top"))
    for label, ms, w, h, n, top in rows:
        print("%-24s %8d %8d %8.1f %6d %6.2f" % (label, w, h, ms, n, top))
    print("\n判据：小 ROI 上「切段的总价」是否低于「整块一次」；"
          "两段都读不全就是反效果。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
