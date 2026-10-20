# -*- coding: utf-8 -*-
"""一次性排障探针：bench [2] 里「并集 ROI 比整帧还贵 173%」到底是怎么来的。

同一帧（`subtitle_frame` 画的那张假字幕）分别按四种喂法量：
整帧 / 线上并集 ROI / 把 ROI 竖着垫高 / 单格，
除了耗时还记两件事：

  * **引擎内部调了几次**（靠 `LEXARA_OCR_DEBUG=1` 的 `[ocr] step=` 行计数）
    —— 用来证明贵的是「放大+切条的加档阶梯」，不是像素面积；
  * **读到几行、挑出几个词** —— 便宜不能靠漏词换来。

脚本自己画的帧，不落盘、不抓屏、不联网。用完可以删。
"""
from __future__ import annotations

import contextlib
import io
import os
import statistics
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
sys.path.insert(0, os.path.join(BASE, "tools"))
os.environ["LEXARA_OCR_DEBUG"] = "1"

import numpy as np                                          # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

import sense_bench as B                                     # noqa: E402
from lexicon import Lexicon                                 # noqa: E402
from ocr_engine import OcrEngine                            # noqa: E402
from sense_session import SenseSession                      # noqa: E402
from sense_worker import SenseWorker, _thumbnail            # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)
LEX = Lexicon(os.path.join(BASE, "assets", "ecdict.sqlite"),
              os.path.join(BASE, "assets", "exam-tags.sqlite"),
              os.path.join(BASE, "assets", "industry.sqlite"))


def measure(crop, runs=3):
    """返回 (耗时列表, 引擎调用次数, 行数, 挑出的词) —— 只喂 ndarray，不碰 GUI。"""
    times, calls, lines_n = [], [], []
    surfaces = []
    for _ in range(runs):
        buffer = io.StringIO()
        started = time.perf_counter()
        with contextlib.redirect_stdout(buffer):
            got = OcrEngine.recognize_lines(np.ascontiguousarray(crop))
        times.append((time.perf_counter() - started) * 1000.0)
        calls.append(sum(1 for ln in buffer.getvalue().splitlines()
                         if ln.startswith("[ocr] step=")))
        lines_n.append(len(got))
        surfaces.append(sorted(item.get("surface", "") for item in LEX.scan_text(
            " ".join(line.text for line in got), limit=50)))
    return times, calls, lines_n, surfaces


def report(tag, box, frame):
    # 线上的框是 `(键, x, y, w, h)`，键用来标是哪几格并成的
    if len(box) == 5:
        _, x, y, w, h = box
    else:
        x, y, w, h = box
    crop = frame[y:y + h, x:x + w]
    times, calls, lines_n, surfaces = measure(crop)
    print("  %-24s %4dx%-4d 均 %7.1fms 中位 %7.1fms · 调用 %s · 行 %s · 词 %d"
          % (tag, w, h, statistics.mean(times), statistics.median(times),
             calls, lines_n, len(surfaces[-1])))
    print("        %s" % " ".join(surfaces[-1]))
    return statistics.mean(times), surfaces[-1]



def grow(box, target, limit_h):
    """把 ROI 竖着垫高到 `target`（居中、贴边时往回收），用于对照实验。"""
    if len(box) == 5:
        _, x, y, w, h = box
    else:
        x, y, w, h = box
    if h >= target:
        return (x, y, w, h)
    y0 = max(0, y - (target - h) // 2)
    y1 = min(limit_h, y0 + target)
    y0 = max(0, y1 - target)
    return (x, y0, w, y1 - y0)


def main() -> int:
    OcrEngine.warmup()
    frame_a = B.to_array(B.subtitle_frame(B.SUBTITLES[0]))
    frame_b = B.to_array(B.subtitle_frame(B.SUBTITLES[1]))
    height, width = frame_a.shape[0], frame_a.shape[1]

    session = SenseSession(hz=1.0)
    session.start()
    thumb_a, scale = _thumbnail(B.gray_of(frame_a), B.cv2_import())
    session.ingest(thumb_a)
    thumb_b, _ = _thumbnail(B.gray_of(frame_b), B.cv2_import())
    keys, is_full = session.ingest(thumb_b)
    worker = SenseWorker(session, LEX)
    boxes = worker._roi_boxes(list(keys), (thumb_a.shape[1], thumb_a.shape[0]),
                              scale, (width, height))
    print("变化格子 %s（整屏=%s）→ 线上 ROI 框 %s" % (list(keys), is_full, boxes))

    print("\n同一帧（%dx%d）的喂法对照（词表用来核对「便宜是不是拿漏词换的」）："
          % (width, height))
    _ms, full_words = report("整帧", (0, 0, width, height), frame_a)
    merged_words = []
    for box in boxes:
        _ms, got = report("线上并集 ROI", box, frame_a)
        merged_words.extend(got)
        _, x, y, w, h = box
        crop = frame_a[y:y + h, x:x + w]
        tight = SenseWorker._tighten_crop(crop)
        if tight is None:
            print("  %-24s 收不动（`_tighten_crop` 返回 None）" % "收紧")
        else:
            start, height_, col, width_ = tight
            _ms, trimmed_words = report("收紧后（=线上路径）",
                                        (x + col, y + start, width_, height_),
                                        frame_a)
            lost = sorted(set(full_words) - set(trimmed_words))
            gained = sorted(set(trimmed_words) - set(full_words))
            print("      整帧有而收紧后没有的词：%s" % (" ".join(lost) or "（无）"))
            print("      收紧后多出来的词：%s" % (" ".join(gained) or "（无）"))
    for key in list(keys)[:2]:
        x, y, w, h = session.roi_box(key, (width, height))
        report("单格 %s" % key, (x, y, w, h), frame_a)

    # 「小面积 ROI 到底划不划算」—— 这决定 §7.3 的裁剪策略留不留
    print("\n手工形状对照（同一帧；字幕实际画在 y≈880~1010）：")
    report("贴着字幕的一条", (0, 880, 1920, 130), frame_a)
    report("字幕带上下各留白", (0, 800, 1920, 280), frame_a)
    report("两三个词", (120, 900, 300, 90), frame_a)
    report("左上 1/8 块（空白）", (0, 0, 480, 270), frame_a)

    print("\n滚动整屏帧（对照，走整帧路径）：")
    report("scroll 整帧", (0, 0, width, height), B.to_array(B.scroll_frame()))
    print("\n空白帧（对照，§7.3 那条 10s 尖峰）：")
    report("blank 整帧", (0, 0, width, height), B.to_array(B.blank_frame()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
