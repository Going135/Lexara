#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成三张「整面玻璃碎裂」贴图：jar_crack_01 / 02 / 03.png

用法：`python make_cracks.py`（Pillow 12.3.0 实测可跑，输出写在脚本同目录）。

约定（2026-10-15 第四轮，和启动台.html 里的 .glass-face / .crack 是一对死的）
---------------------------------------------------------------------------
· 图片尺寸 = 瓶身（.jar-box）在 1060×720 设计尺寸下的 CSS 像素尺寸 **980×433**，
  1:1 映射。`.crack` 是 `inset:0;object-fit:fill` 贴在 .jar-box 上，所以
  **图里的一个像素 = 屏幕上的一 CSS 像素**，划痕不会被拉歪。窗口比例（.stage 的
  flex-basis）一改，这里的 W/H 就得跟着改并重出图。
· 撞击点在正面正中偏上：IMPACT = (0.500, 0.440)。启动台里 `spawnDebris()` 用同
  一组比例（`b.width*.5, b.height*.44`），改这里要一起改，否则碎片从别处崩出来。
· 三档是「同一块玻璃越裂越狠」：只加内容、不挪旧内容，所以叠着看不冲突。
  01 = 撞击点附近的细纹；02 = 放射纹伸到半路 + 同心弧；03 = 放射纹打通到边缘 +
  密集蛛网 + 碎玻璃亮点。
· 颜色沿用旧约定：一条深色描边 + 一条近白内芯。浅色底下 HTML 用 `filter:invert(1)`
  + `mix-blend-mode:multiply`，于是内芯变成深色裂纹线、描边变成一圈很淡的光晕。
  **线宽是每档一个显式 `stroke`**，最轻的一档必须最细 —— 早先写成 `4-branch_depth`
  时最轻的一档反而最粗，在窄壁上糊成一坨。
· 放射纹的长度用「沿该方向到玻璃边缘的距离」的分数控制，不用绝对像素：窗口比例变了、
  重出图之后「裂到哪」还是同一个观感。
· 随机游走必须带 guard 上限和 step 下限：`step *= rng.uniform(...)` 是几何衰减，
  只靠 `walked < length` 判断会在原地打转，第一次跑就卡死过。
"""
import math
import os
import random

from PIL import Image, ImageDraw

# ---------------------------------------------------------------- 几何常数（对死启动台）
JAR_CSS_W = 980.0          # .jar-box 设计宽度：min(980px, 94%) @ 1060px 窗口
JAR_CSS_H = 433.0          # .jar-box 设计高度：64% × (720-44) = 432.64 → 433
W, H = 980, 433            # 图 = 设计尺寸，1:1，不做各向异性拉伸
IMPACT = (0.500, 0.440)    # 撞击点（比例），和 spawnDebris() 的 .5 / .44 一致
SEED = 20261015            # 固定种子：同样的参数要能重出同样的图

# 每一档画多少、裂多远。length 是「到边缘距离」的分数区间。
PLAN = {
    1: dict(radial=7,  length=(0.10, 0.26), branch=0, rings=3, ring_r=(0.045, 0.13),
            alpha=150, stroke=1, shards=0,   star=False, tick=0, wob=0.14),
    2: dict(radial=13, length=(0.26, 0.62), branch=1, rings=6, ring_r=(0.07, 0.26),
            alpha=185, stroke=1, shards=24,  star=True,  tick=7,  wob=0.16),
    3: dict(radial=24, length=(0.55, 1.00), branch=2, rings=11, ring_r=(0.05, 0.48),
            alpha=228, stroke=2, shards=170, star=True,  tick=18, wob=0.18),
}


def edge_distance(cx, cy, ang):
    """从 (cx,cy) 沿 ang 方向走到玻璃边缘的距离（图内），不会为负。"""
    dx, dy = math.cos(ang), math.sin(ang)
    ts = []
    if abs(dx) > 1e-6:
        ts.append((W - 1 - cx) / dx if dx > 0 else -cx / dx)
    if abs(dy) > 1e-6:
        ts.append((H - 1 - cy) / dy if dy > 0 else -cy / dy)
    ts = [t for t in ts if t > 0]
    return min(ts) if ts else 0.0


def walk(draw, rng, x, y, ang, length, stroke, alpha, wob=0.16, step=7.0):
    """一段随机游走裂纹：深色描边 + 近白内芯。返回走过的点，供分叉和横枝用。"""
    pts, walked, guard = [], 0.0, 0
    while walked < length and guard < 400:          # guard：防原地打转（踩过坑）
        guard += 1
        pts.append((x, y))
        # 玻璃裂纹 = 长直段 + 突然的折角，不是正弦波：抖动很小，每 4 步给一次 kink
        ang += rng.uniform(-wob, wob)
        if guard % 4 == 0:
            ang += rng.choice([-1, 1]) * rng.uniform(0.22, 0.46)
        step = max(2.6, step * rng.uniform(0.90, 1.05))
        x += math.cos(ang) * step
        y += math.sin(ang) * step
        walked += step
        if x < 0 or x >= W or y < 0 or y >= H:      # 到边就停，裂纹不越界
            pts.append((max(0.0, min(W - 1.0, x)), max(0.0, min(H - 1.0, y))))
            break
    if len(pts) > 1:
        draw.line(pts, fill=(12, 20, 28, int(alpha * 0.45)), width=stroke + 1)
        draw.line(pts, fill=(252, 254, 255, alpha), width=stroke)
    return pts


def radial_web(draw, rng, cx, cy, count, length_span, branch, stroke, alpha, wob):
    """从撞击点均匀发散的放射纹；branch>0 时在中段再岔出短纹。"""
    base = rng.uniform(0.0, math.tau)
    paths = []
    for i in range(count):
        ang = base + (i + rng.uniform(-0.34, 0.34)) * math.tau / count
        dist = edge_distance(cx, cy, ang) * rng.uniform(*length_span)
        pts = walk(draw, rng, cx, cy, ang, dist, stroke, alpha, wob=wob)
        paths.append(pts)
        if branch and len(pts) > 6:
            for _ in range(branch):
                k = rng.randrange(max(2, len(pts) // 3), len(pts) - 1)
                bx, by = pts[k]
                bang = ang + rng.choice([-1, 1]) * rng.uniform(0.5, 1.1)
                walk(draw, rng, bx, by, bang,
                     dist * rng.uniform(0.18, 0.42), max(1, stroke - 1),
                     int(alpha * 0.85), wob=min(0.30, wob * 1.8))
    return paths


def concentric_rings(draw, rng, cx, cy, n_rings, r_span, stroke, alpha, paths):
    """撞击点周围的同心弧（蛛网的圈）：每段只跨一段角度，断开才像裂的。"""
    mean_edge = sum(edge_distance(cx, cy, a) for a in range(0, 628, 32)) / 20
    for _ in range(n_rings):
        r = mean_edge * rng.uniform(*r_span)
        if r < 6:
            continue
        a0 = rng.uniform(0.0, math.tau)
        span = rng.uniform(0.4, 1.6)          # 跨度大就会画成闭合圈，不像裂的
        steps = max(8, int(r * span / 5))
        pts = []
        for i in range(steps + 1):
            a = a0 + span * i / steps
            rr = r + rng.uniform(-0.9, 0.9)
            x, y = cx + math.cos(a) * rr, cy + math.sin(a) * rr
            if 0 <= x < W and 0 <= y < H:
                pts.append((x, y))
            elif pts:
                break
        if len(pts) > 2:
            draw.line(pts, fill=(12, 20, 28, int(alpha * 0.40)), width=stroke + 1)
            draw.line(pts, fill=(252, 254, 255, alpha), width=stroke)


def cross_ticks(draw, rng, paths, count, stroke, alpha, cx, cy):
    """横枝（shell marks）：裂纹上的短横线，垂直于裂纹走向，像玻璃的贝氏线。"""
    usable = [p for p in paths if len(p) > 8]
    if not usable:
        return
    for _ in range(count):
        pts = rng.choice(usable)
        k = rng.randrange(3, len(pts) - 2)
        x, y = pts[k]
        ang = math.atan2(pts[k][1] - pts[k - 1][1], pts[k][0] - pts[k - 1][0]) + math.pi / 2
        ln = rng.uniform(7, 20)
        for s in (-1, 1):
            x2 = min(W - 1, max(0, x + math.cos(ang) * ln * s))
            y2 = min(H - 1, max(0, y + math.sin(ang) * ln * s))
            draw.line([(x, y), (x2, y2)], fill=(252, 254, 255, int(alpha * 0.85)),
                      width=max(1, stroke - 1))


def shards(draw, rng, cx, cy, n, alpha):
    """碎玻璃亮点：撞击点附近的小三角/菱形，越远越稀。"""
    for _ in range(n):
        a = rng.uniform(0, math.tau)
        d = abs(rng.gauss(0, 1)) * H * 0.20
        x, y = cx + math.cos(a) * d * 2.0, cy + math.sin(a) * d
        if not (0 <= x < W and 0 <= y < H):
            continue
        s = rng.uniform(1.6, 5.2)
        pts = [(x + rng.uniform(-s, s), y + rng.uniform(-s, s)) for _ in range(3)]
        draw.polygon(pts, fill=(252, 254, 255, int(alpha * rng.uniform(0.5, 0.95))))


def impact_star(draw, rng, cx, cy, alpha):
    """撞击点中心的「小洞」：一小撮密线 + 一个亮点，读出破口。"""
    for i in range(18):
        a = i / 18 * math.tau + rng.uniform(-0.1, 0.1)
        ln = rng.uniform(4, 15)
        draw.line([(cx, cy), (cx + math.cos(a) * ln, cy + math.sin(a) * ln)],
                  fill=(252, 254, 255, alpha), width=1)
    r = rng.uniform(2.4, 3.4)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(252, 254, 255, 255))


def make(severity):
    cfg = PLAN[severity]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rng = random.Random(SEED + severity)
    cx, cy = IMPACT[0] * W, IMPACT[1] * H

    paths = radial_web(draw, rng, cx, cy, cfg["radial"], cfg["length"],
                       cfg["branch"], cfg["stroke"], cfg["alpha"], cfg["wob"])
    if cfg["rings"]:
        concentric_rings(draw, rng, cx, cy, cfg["rings"], cfg["ring_r"],
                         cfg["stroke"], cfg["alpha"], paths)
    if cfg["tick"]:
        cross_ticks(draw, rng, paths, cfg["tick"], cfg["stroke"], cfg["alpha"], cx, cy)
    if cfg["shards"]:
        shards(draw, rng, cx, cy, cfg["shards"], cfg["alpha"])
    if cfg["star"]:
        impact_star(draw, rng, cx, cy, cfg["alpha"])

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "jar_crack_%02d.png" % severity)
    img.save(out)
    return out, len(img.getbbox() or ())


if __name__ == "__main__":
    print("瓶身设计尺寸 %.0f×%.0f → 图 %d×%d（1:1），撞击点 %s"
          % (JAR_CSS_W, JAR_CSS_H, W, H, IMPACT))
    for sev in sorted(PLAN):
        path, _ = make(sev)
        print("%s  %d bytes" % (os.path.basename(path), os.path.getsize(path)))
