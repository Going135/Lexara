# -*- coding: utf-8 -*-
"""量一件事：一次 OCR 到底同时吃几个核（决定风扇转不转）。

`bench` 报的「平均 1.2 个核」是整段 58 秒的大平均（含没活干的时间），
风扇响应的是**瞬时**，所以这里用 `process_time / wall` 直接算
「这一次识别期间平均有几个核在满载」。

顺带验 `OCR_THREADS` 这个限核开关：`rapidocr_onnxruntime` 的
`OrtInferSession` 把 `SessionOptions` 写死了（只设 log 级别和优化等级，
不设 `intra_op_num_threads`），默认值 0 = onnxruntime 自己按机器核数开线程池。
这里在 `InferenceSession` 外面套一层，在建会话前把线程数按进去。

    .venv/Scripts/python.exe tools/sense_threads_probe.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

import numpy as np                                                # noqa: E402


def draw(text: str, width: int = 900, height: int = 64):
    """白底黑字画一行，当作被识别的那一段（不落盘、不抓屏）。"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("arial.ttf", 40)
    d.text((10, 8), text, font=font, fill=20)
    g = np.asarray(img)
    return np.dstack([g, g, g]).astype(np.uint8)


def measure(threads, rounds: int = 4) -> None:
    """按给定线程上限**重建**引擎再量（`OcrEngine` 是单例，不重建等于白设）。"""
    import ocr_engine
    ocr_engine.set_thread_limit(threads)
    ocr_engine.OcrEngine._engine = None          # 探针专用：丢掉已建的会话
    crops = [draw("the aggressive approach eliminates duplicates"),
             draw("an approach to eliminate the duplicate entries"),
             draw("spider sense watches the desktop quietly"),
             draw("short line")]
    cores, total_ms, calls = [], [], 0
    for _ in range(rounds):
        for crop in crops:
            w0, c0 = time.perf_counter(), time.process_time()
            lines = ocr_engine.OcrEngine.recognize_lines(crop)
            dw = time.perf_counter() - w0
            dc = time.process_time() - c0
            total_ms.append(dw * 1000.0)
            cores.append(dc / dw if dw > 0 else 0.0)
            calls += len(lines or [])
    total_ms.sort()
    cores.sort()
    mid = len(total_ms) // 2
    print("threads=%-6s 单次中位 %7.1fms · 满载核数中位 %5.2f · 最大 %5.2f"
          % ("不夹" if threads is None else threads,
             total_ms[mid], cores[mid], cores[-1]))
    print("%-12s 读出的总行数 %d（限核后如果掉行 = 质量退化，必须看见）"
          % ("", calls))



def main() -> int:
    import multiprocessing
    import onnxruntime as ort
    import ocr_engine
    print("逻辑核数：%d · os.cpu_count=%d"
          % (multiprocessing.cpu_count(), os.cpu_count()))
    print("onnxruntime %s · SessionOptions 默认 intra=%s（0 = 引擎自己按核数开线程池）"
          % (ort.__version__, ort.SessionOptions().intra_op_num_threads))
    print("本项目：DEFAULT_THREAD_LIMIT=%s · 当前 thread_limit()=%s"
          % (ocr_engine.DEFAULT_THREAD_LIMIT, ocr_engine.thread_limit()))
    print("★ 满载核数 = 一次识别期间的 process_time / wall。"
          "这个数字是几，风扇就听到几声。\n")
    for n in (None, 2, 4):
        measure(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
