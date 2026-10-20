"""用旧 pyc（10-18 20:24）和当前源码分别算几何，输出 JSON 供对比。

几何层（_autocrop / _line_bands / _plans_for）不依赖 OCR 引擎，
所以能脱离 rapidocr 单独跑 —— 这是唯一能拿到「原版行为」的办法。
"""
import json
import marshal
import sys
import types

import numpy as np
from PIL import Image

SHOT = r"C:\Users\35388\Desktop\屏幕截图 2026-10-18 152551.png"
OUT = sys.argv[1]


def load_old():
    sys.path.insert(0, "src")
    data = open("src/__pycache__/ocr_engine.cpython-314.pyc", "rb").read()
    code = marshal.loads(data[16:])
    mod = types.ModuleType("old_ocr")
    mod.__file__ = "src/__pycache__/ocr_engine.cpython-314.pyc"
    sys.modules["old_ocr"] = mod
    exec(code, mod.__dict__)
    return mod


def load_new():
    sys.path.insert(0, "src")
    import ocr_engine
    return ocr_engine


def dump(mod, tag):
    img = Image.open(SHOT).convert("RGB")
    arr = np.ascontiguousarray(np.array(img)[:, :, ::-1])
    crop, ox, oy = mod._autocrop(arr)
    bg = mod._border_bg(crop)
    bands = mod._line_bands(crop, bg)
    rows = {
        "tag": tag,
        "crop": list(crop.shape),
        "offset": [int(ox), int(oy)],
        "bg": [int(v) for v in bg],
        "bands": [],
    }
    for band, bx, by in bands:
        plans = mod._plans_for(band, ox + bx, oy + by, bg)
        rows["bands"].append({
            "shape": list(band.shape),
            "xy": [int(bx), int(by)],
            "plans": [[list(p[0].shape), int(p[1]), float(p[2]), float(p[3]),
                       float(p[4]), float(p[5])] for p in plans],
        })
    open(OUT, "w", encoding="utf-8").write(json.dumps(rows, ensure_ascii=False))
    print("%s: %d 条带 → %s" % (tag, len(bands), OUT))


if __name__ == "__main__":
    mode = sys.argv[2] if len(sys.argv) > 2 else "new"
    mod = load_old() if mode == "old" else load_new()
    dump(mod, "old-pyc" if mode == "old" else "current-" + ".".join(
        str(v) for v in sys.version_info[:2]))
