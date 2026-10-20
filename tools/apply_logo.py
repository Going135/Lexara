# -*- coding: utf-8 -*-
"""LEXARA / 词蛛 logo 换新：白底 → 透明，并按底色出两版（象牙白 / 墨黑）。

为什么要两版：侧栏顶部现在是墨绿渐变（`shell.top`），logo 直接放在底色上以后，
原图的黑字在墨绿上几乎看不见。QML 侧用象牙白那版；旧 Widgets 界面（浅色侧栏）
和任何浅底场景用墨黑那版。

抠像不用 flood fill：logo 是纯黑字 + 纯白底，按亮度取 alpha 最干净 ——
`alpha = 255 - min(R,G,B)`，黑字 a=255、白底 a=0、抗锯齿边自然落在中间。
然后整体重新填色，避免 JPEG 噪声把边缘染灰。

用法：
    python tools/apply_logo.py <新logo图>
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(BASE, "assets", "ui")
BACKUP = os.path.join(BASE, "backup", "logo_prev_20261018")

#: 显示宽度 200（侧栏 232 - 32 边距），出 2 倍图给高 DPI
OUT_WIDTH = 440
#: 与 QML `root.onDark` 一致的象牙白；墨黑用纯黑
IVORY = (0xF7, 0xF3, 0xE6)
INK = (0x1A, 0x1A, 0x1A)


def mask_from_image(im: Image.Image) -> Image.Image:
    """取字形遮罩。

    源图**自带 alpha**（这张是透明底黑字），那就直接用它的 alpha —— 转 RGB 会把
    透明区域压成黑，再按亮度算就等于整张画布全是字。只有不透明图（白底 JPG）
    才退回「亮度即遮罩」。
    """
    if im.mode in ("RGBA", "LA") or "transparency" in im.info:
        alpha = im.convert("RGBA").split()[3]
        if alpha.getextrema()[0] < 250:          # 确实有透明区才采信
            return alpha
    rgb = np.asarray(im.convert("RGB")).astype(np.float32)
    # min 通道：纯黑 0 → a=255；纯白 255 → a=0
    alpha = 255.0 - rgb.min(axis=2)
    alpha = np.clip((alpha - 6.0) * (255.0 / 240.0), 0.0, 255.0)
    return Image.fromarray(alpha.round().astype(np.uint8), "L")


def tint(mask: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    solid = Image.new("RGBA", mask.size, color + (255,))
    solid.putalpha(mask)
    return solid


def main(src: str) -> int:
    im = Image.open(src)
    mask = mask_from_image(im)
    # 紧裁到字身（阈值 8，抗锯齿残留不算）
    box = mask.point(lambda v: 255 if v >= 8 else 0).getbbox()
    if not box:
        raise SystemExit("抠不出字？检查源图是不是白底黑字")
    mask = mask.crop(box)
    print("字身 bbox %s  →  %dx%d  比例 %.3f"
          % (box, mask.size[0], mask.size[1], mask.size[0] / mask.size[1]))

    scale = OUT_WIDTH / mask.size[0]
    size = (OUT_WIDTH, max(1, round(mask.size[1] * scale)))
    mask = mask.resize(size, Image.LANCZOS)

    os.makedirs(BACKUP, exist_ok=True)
    for name, color in (("lexara_logo.png", IVORY), ("lexara_logo_ink.png", INK)):
        path = os.path.join(UI, name)
        if os.path.exists(path) and not os.path.exists(os.path.join(BACKUP, name)):
            shutil.copy2(path, os.path.join(BACKUP, name))
        tint(mask, color).save(path)
        print("  写入 %-24s %dx%d  rgb%s" % (name, size[0], size[1], color))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="logo 换新（白底→透明，两版配色）")
    parser.add_argument("source")
    sys.exit(main(parser.parse_args().source))
