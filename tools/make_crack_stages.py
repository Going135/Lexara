# -*- coding: utf-8 -*-
"""把 `assets/ui/spider_cracked.png` 切成三档递进损毁贴图。

为什么需要它：旧的 `assets/jar_crack_0{1,2,3}.png` 是「一整张 970x400 白底上
几根极细灰线」，叠进玻璃罐里几乎看不见（实测基本等于没有裂纹），部署动画的
三个阶段等于空放。新素材是一整张八向裂纹，按**撞击点向外扩散**做径向遮罩
就能得到自然的三段式：中心细纹 → 半数裂开 → 全裂。

输出严格对齐 `launcher_window.IMPACT = (0.500, 0.440)`：撞击点落在画布
(0.5, 0.44) 处，JarView 直接把整张图按瓶身尺寸拉伸即可，不用额外偏移。
"""
from __future__ import annotations

import os
import shutil

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "ui", "spider_cracked.png")
OUT_DIR = os.path.join(ROOT, "assets")
BACKUP = os.path.join(ROOT, "backup")

CANVAS_PAD = 26              # 裁到裂纹本体后再留一点边
IMPACT = (0.500, 0.440)       # 必须与 launcher_window.IMPACT 一致
#: 半径按「裂纹自身尺度」而不是画布对角算：0.34/0.62 是实测好看的两档，
#: 用画布对角算会把第一档直接铺满（踩过）。
STAGE_RADIUS = (0.34, 0.62, 1.00)
FEATHER = 46.0               # 遮罩羽化像素，避免出现硬边圆环


def main() -> int:
    os.makedirs(BACKUP, exist_ok=True)
    for index in range(1, 4):
        path = os.path.join(OUT_DIR, "jar_crack_0%d.png" % index)
        if os.path.isfile(path):
            keep = os.path.join(BACKUP, "jar_crack_0%d_old.png" % index)
            if not os.path.isfile(keep):
                shutil.copy2(path, keep)

    source = Image.open(SRC).convert("RGBA")

    # ★ 去彩色晕边：源图**透明区域里 RGB 是黑/青色**（去背残留），直接缩放会
    #   被插值带进可见边缘，出来一圈青紫描边（第一版实测就是这样）。做法是
    #   把 a<8 的像素 RGB 统一刷白 + 整体去饱和 → 只剩中性灰玻璃，任意插值都安全。
    raw = np.asarray(source).astype(np.float32)
    alpha0 = raw[..., 3]
    gray = raw[..., :3].mean(axis=2)
    gray = np.where(alpha0 < 8.0, 255.0, gray)
    # ★ 只留墨线：源图里大片「玻璃面」是半透明白（alpha>0 但很亮），直接搬过来
    #   会变成一片白斑/噪点。按暗度重建 alpha —— 越暗越是裂纹，亮面直接透明。
    ink = np.clip((255.0 - gray) / 255.0, 0.0, 1.0)
    alpha1 = np.clip(alpha0 * np.power(ink, 0.85) * 2.6, 0.0, 255.0)
    alpha1 = np.where(ink < 0.06, 0.0, alpha1)
    cleaned = Image.fromarray(
        np.dstack([gray, gray, gray, alpha1]).astype(np.uint8), "RGBA")
    arr = np.asarray(cleaned).astype(np.float32)
    alpha = arr[..., 3]
    weight = alpha / max(1.0, alpha.sum())
    ys, xs = np.mgrid[0:source.height, 0:source.width]
    cx = float((xs * weight).sum())
    cy = float((ys * weight).sum())

    # 裁到真实内容，避免原图四周大片留白把裂纹压小
    solid = np.asarray(alpha > 8)
    rows = np.where(solid.any(axis=1))[0]
    cols = np.where(solid.any(axis=0))[0]
    box = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
    crop = cleaned.crop(box)
    ccx, ccy = cx - box[0], cy - box[1]

    # 让裂纹本体铺满画布：缩放到固定宽度，画布 = 缩放后尺寸 + 一点边
    target_w = 1100
    scale = target_w / float(crop.width)
    size = (max(1, int(round(crop.width * scale))),
            max(1, int(round(crop.height * scale))))
    scaled = crop.resize(size, Image.LANCZOS)
    canvas_w = size[0] + CANVAS_PAD * 2
    canvas_h = size[1] + CANVAS_PAD * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    px = int(round(canvas_w * IMPACT[0] - ccx * scale))
    py = int(round(canvas_h * IMPACT[1] - ccy * scale))
    canvas.alpha_composite(scaled, (px, py))

    base = np.asarray(canvas).astype(np.float32)
    h, w = base.shape[:2]
    iy, ix = np.mgrid[0:h, 0:w]
    dx = ix - canvas_w * IMPACT[0]
    dy = iy - canvas_h * IMPACT[1]
    dist = np.sqrt(dx * dx + dy * dy)
    visible = base[..., 3] > 8
    # 裂纹自身尺度：取可见像素到撞击点的 98 分位距离
    extent = float(np.percentile(dist[visible], 98)) if visible.any() else 1.0

    for index, ratio in enumerate(STAGE_RADIUS):
        radius = extent * ratio
        if ratio >= 1.0:
            mask = np.ones_like(dist)
        else:
            mask = np.clip((radius - dist) / FEATHER + 0.5, 0.0, 1.0)
        out = base.copy()
        out[..., 3] = base[..., 3] * mask
        path = os.path.join(OUT_DIR, "jar_crack_0%d.png" % (index + 1))
        Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA").save(path)
        covered = float((out[..., 3] > 8).mean())
        print("stage %d -> %s  r=%.0fpx (extent %.0f)  可见占比 %.1f%%"
              % (index + 1, os.path.basename(path), radius, extent, covered * 100))
    print("crack centroid in source: (%.0f, %.0f)  crop=%s  canvas=%dx%d"
          % (cx, cy, box, canvas_w, canvas_h))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
