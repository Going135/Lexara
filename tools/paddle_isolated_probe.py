# -*- coding: utf-8 -*-
"""PaddleOCR 独立环境验证（任务书 §3.1）。

**只给 `.venv_paddle` 用**，不是产品链路的一部分：

    .venv_paddle\\Scripts\\python.exe tools\\paddle_isolated_probe.py
    .venv_paddle\\Scripts\\python.exe tools\\paddle_isolated_probe.py --chdir "D:\\临时\\词蛛"

它做四件事，全部是**实测**，不做推断：

1. 版本与环境事实（Python / paddlepaddle / paddleocr / paddlex、当前工作目录是否纯 ASCII）；
2. 走**产品同一条探测代码**（`src/ocr_adapter._probe_paddle`），而不是在这里另写一套
   Paddle 调用 —— 否则「独立环境里跑通了」和「我们产品里能跑通」是两件事；
3. 跑通之后量两轮真实推理耗时（同一张合成图，不含任何用户内容）；
4. `--chdir` 用一个**含中文的路径**当工作目录再跑一遍，专门验
   `ocr_engine.py` 顶部注释里那条「Paddle 对非 ASCII 路径会直接失败」的历史结论
   在 3.x 上还成不成立。

输出里不含截图、不含用户文本：图是这里现场画的 `LEXARA` 合成字。
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))


def _version(name: str) -> str:
    try:
        return md.version(name)
    except Exception:                                    # noqa: BLE001
        return "MISSING"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chdir", default="", help="用这个目录当工作目录再跑（测非 ASCII 路径）")
    args = parser.parse_args(argv)

    if args.chdir:
        os.makedirs(args.chdir, exist_ok=True)
        os.chdir(args.chdir)

    print(json.dumps({
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "cwd_is_ascii": True,
    }, ensure_ascii=False)[:400])
    try:
        os.getcwd().encode("ascii")
    except UnicodeEncodeError:
        print("cwd_is_ascii = False（含非 ASCII 字符）")
    else:
        print("cwd_is_ascii = True")

    print("paddlepaddle = %s | paddleocr = %s | paddlex = %s"
          % (_version("paddlepaddle"), _version("paddleocr"), _version("paddlex")))

    import numpy as np
    import ocr_adapter as OA

    print("\n[1] 产品探测代码 ocr_adapter.probe('paddle', force=True)")
    t0 = time.time()
    try:
        snaps = OA.probe("paddle", force=True)
    except Exception as error:                            # noqa: BLE001
        print("    PROBE RAISED %r" % (error,))
        return 2
    snap = snaps[0]
    print("    state=%s version=%s probe_seconds=%s"
          % (snap["state"], snap["version"], snap.get("probe_seconds")))
    print("    reason=%s" % (snap["reason"] or "(空)",))
    print("    本地耗时 %.1fs" % (time.time() - t0))

    if snap["state"] != "available":
        print("\n[2] 未通过探测 → 跳过推理计时（不假装能量数据）")
        print("RESULT: unavailable")
        return 1

    print("\n[2] 统一入口 ocr_adapter.recognize(..., engine_id='paddle') 两轮计时")
    image = OA.probe_image()
    times, texts = [], []
    for i in range(2):
        started = time.time()
        result = OA.recognize(image, engine_id="paddle")
        times.append(round(time.time() - started, 3))
        texts.append([w.text for w in result.words])
        if result.error:
            print("    round %d error=%s degraded=%s note=%s"
                  % (i + 1, result.error, result.degraded, result.note))
    for i, (cost, words) in enumerate(zip(times, texts)):
        print("    round %d: %.3fs, %d 词, 内容=%r（合成图，非用户内容）"
              % (i + 1, cost, len(words), words))
    print("RESULT: available | probe=%ss infer=%s"
          % (snap.get("probe_seconds"), times))
    return 0


if __name__ == "__main__":
    sys.exit(main())
