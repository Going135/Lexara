# -*- coding: utf-8 -*-
"""PaddleOCR 3.x 在 Windows CPU 上跑不通的那条 oneDNN/PIR 报错，能不能绕过？

`.venv_paddle` 实测（2026-10-18）：

    PaddleOCR(lang="en") 构造成功（首次要下 76.5MB 模型，共 87.4s），
    但 `predict()` / `ocr()` 都抛
        NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute
        not support [pir::ArrayAttribute<pir::DoubleAttribute>]
        (at ...\\onednn\\onednn_instruction.cc:118)

这属于 Paddle 3.x 的新执行器（PIR）+ oneDNN 在 Windows 上的实现缺口，
**不是**我们调用方式错了。这个脚本按可能性从高到低试四种绕法，
每一种都记录「构造耗时 / 推理耗时 / 报错原文」，试不通就如实留档，
不改产品代码去掩盖。

只给 `.venv_paddle` 用；输入图是现场合成的 `LEXARA` 字样，不含任何用户内容。
"""
from __future__ import annotations

import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import ocr_adapter as OA                                             # noqa: E402

IMAGE = OA.probe_image()


def attempt(name, setup, ctor):
    print("\n" + "=" * 66)
    print("[尝试] %s" % name)
    try:
        setup()
    except Exception as error:        # noqa: BLE001
        print("    环境设置失败: %r" % (error,))
        return False
    t0 = time.time()
    try:
        engine = ctor()
    except Exception as error:        # noqa: BLE001
        print("    构造失败 %.1fs: %s: %s"
              % (time.time() - t0, type(error).__name__, str(error)[:220]))
        return False
    print("    构造 %.1fs ok" % (time.time() - t0))
    started = time.time()
    try:
        res = engine.predict(IMAGE)
    except Exception as error:        # noqa: BLE001
        print("    推理失败 %.2fs: %s: %s"
              % (time.time() - started, type(error).__name__, str(error)[:300]))
        return False
    print("    推理 %.2fs ok，%d 行" % (time.time() - started, len(res or [])))
    for row in (res or [])[:2]:
        keys = sorted(list(row.keys())) if hasattr(row, "keys") else []
        print("    keys=%s" % keys[:12])
        for key in ("rec_texts", "rec_scores", "rec_polys"):
            if key in keys:
                print("      %s=%s" % (key, str(row[key])[:160]))
    return True


def main() -> int:
    from paddleocr import PaddleOCR

    results = {}
    results["mkldnn_off"] = attempt(
        "enable_mkldnn=False（关掉 oneDNN，绕开 onednn_instruction 那条路径）",
        lambda: None,
        lambda: PaddleOCR(lang="en", enable_mkldnn=False))
    results["pir_off"] = attempt(
        "FLAGS_enable_pir_api=0（退回旧执行器）",
        lambda: os.environ.update({"FLAGS_enable_pir_api": "0"}),
        lambda: PaddleOCR(lang="en", enable_mkldnn=False))
    results["device_cpu"] = attempt(
        "device='cpu' + precision='fp32'",
        lambda: None,
        lambda: PaddleOCR(lang="en", device="cpu", precision="fp32",
                          enable_mkldnn=False))

    print("\n" + "=" * 66)
    for key, ok in results.items():
        print("%-12s %s" % (key, "PASS" if ok else "FAIL"))
    return 0 if any(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
