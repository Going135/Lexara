# -*- coding: utf-8 -*-
"""PaddleOCR 3.x 的**真实接口形状**探针（只给 `.venv_paddle` 用）。

为什么要单独一个脚本：`ocr_adapter._probe_paddle` 里那套构造参数和结果解析是按
PaddleOCR 2.x 写的，3.7.0 实测直接报 `Unknown argument: show_log`。
**不猜 3.x 的签名和返回结构**，先跑这个把真实形状打出来，再改产品代码。

只做只读观察：构造引擎 + 对一张现场合成的图推理，打印类型/键名/耗时。
图里只有 `LEXARA SPIDER WORD` 这几个我们自己画的英文词，没有任何用户内容。
"""
from __future__ import annotations

import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import numpy as np                                                   # noqa: E402
import ocr_adapter as OA                                             # noqa: E402


def main() -> int:
    from paddleocr import PaddleOCR
    print("paddleocr module file:", getattr(PaddleOCR, "__module__", "?"))

    t0 = time.time()
    engine = PaddleOCR(lang="en")          # 3.x 的构造：只给 lang
    print("构造耗时 %.2fs" % (time.time() - t0))

    image = OA.probe_image()               # RGB ndarray，写着 LEXARA
    print("输入 shape=%s dtype=%s" % (image.shape, image.dtype))

    for name in ("predict", "ocr"):
        fn = getattr(engine, name, None)
        if fn is None:
            print("\n[%s] 不存在" % name)
            continue
        started = time.time()
        try:
            res = fn(image)
        except Exception as error:          # noqa: BLE001
            print("\n[%s] 调用失败 %.2fs: %r" % (name, time.time() - started, error))
            continue
        cost = time.time() - started
        print("\n[%s] %.2fs → 顶层类型=%s 长度=%s"
              % (name, cost, type(res).__name__, len(res) if hasattr(res, "__len__") else "-"))
        first = None
        try:
            first = res[0] if len(res) else None
        except Exception:                   # noqa: BLE001
            pass
        if first is None:
            print("    空结果")
            continue
        print("    item 类型=%s" % type(first).__name__)
        keys = getattr(first, "keys", None)
        if callable(keys):
            print("    keys=%s" % sorted(list(first.keys())))
            for key in sorted(list(first.keys())):
                value = first[key]
                text = repr(value)
                if key in ("rec_texts", "rec_scores", "rec_polys", "dt_polys"):
                    print("      %s = %s" % (key, text[:200]))
        else:
            print("    repr=%s" % repr(first)[:260])
    return 0


if __name__ == "__main__":
    sys.exit(main())
