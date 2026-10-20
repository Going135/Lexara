# -*- coding: utf-8 -*-
"""几何探针：身体平移时头部是否领路（八方向）。

用法：``python tools/heading_probe.py``
口径：`crawler_spider.Spider.to_world()` 是渲染层同一个旋转，
所以这里算出的「头的世界方向」就是画面上头真正指着的方向。
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import crawler_spider as CS          # noqa: E402

DIRS = (("右", (3, 0)), ("左", (-3, 0)), ("下", (0, 3)), ("上", (0, -3)),
        ("右下", (3, 3)), ("左下", (-3, 3)), ("右上", (3, -3)), ("左上", (-3, -3)))

print("方向   世界运动角   头指向角    偏差     heading    结论")
bad = 0
for name, (mx, my) in DIRS:
    s = CS.Spider()
    s.heading = 0.0
    for _ in range(150):
        s.update(1 / 60.0, "crawl", None, motion=(mx, my))
    want = math.atan2(my, mx)
    head_world = s.to_world(s.body["head"])          # 头的世界方向
    got = math.atan2(head_world[1], head_world[0])
    diff = math.degrees((got - want + math.pi) % (2 * math.pi) - math.pi)
    ok = abs(diff) < 15.0
    bad += 0 if ok else 1
    print("%-4s %10.1f° %10.1f° %8.1f° %9.1f°  %s"
          % (name, math.degrees(want), math.degrees(got), diff,
             math.degrees(s.heading), "OK" if ok else "反向/偏"))

# 头是否真的领先体心（沿运动方向的前后关系）
print("\n头部领先量（沿运动方向的投影，>0 才算头在前）：")
for name, (mx, my) in DIRS:
    s = CS.Spider()
    s.heading = 0.0
    for _ in range(150):
        s.update(1 / 60.0, "crawl", None, motion=(mx, my))
    n = math.hypot(mx, my)
    u = (mx / n, my / n)
    hw = s.to_world(s.body["head"])
    aw = s.to_world(s.body["abd"])
    print("  %-4s 头 %+.1f  腹 %+.1f  %s"
          % (name, hw[0] * u[0] + hw[1] * u[1], aw[0] * u[0] + aw[1] * u[1],
             "OK" if (hw[0] * u[0] + hw[1] * u[1]) > (aw[0] * u[0] + aw[1] * u[1])
             else "腹在前"))
print("\n失败 %d 项" % bad)
sys.exit(1 if bad else 0)
