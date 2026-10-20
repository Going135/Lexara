# -*- coding: utf-8 -*-
"""诊断点击命中测试的失配。

做三件事：
  1. 把「画出来的点」逐条打上标签（腿、头顶红点、头胸矩形、头部三角），
     逐个朝向跑一遍 `_on_spider`，报出判不中的是**哪一类**点；
  2. 反向检查**已经删掉的尾巴**：那两块（腹部 / 纺器）现在必须判不中，
     否则会在空白处留一块「看不见却吃点击」的热区；
  3. 动态步态 240 帧（边走边转，`lean` 最大）—— 转弯是命中判定最容易错的时候。

失败点会被反查回局部坐标，并分别报出「离矩形多远 / 离三角多远 / 离最近那条腿多远」，
一眼就能看出是哪个形状的判定出了问题。
"""
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

import crawler_spider as CS
from pet_window import PetWindow

app = QApplication(sys.argv)
window = PetWindow(None, None, sprite_w=360.0)
window.effect = None                     # 开局那个 pop 形变会干扰判定
window.resize(*window._window_size())
UNIT = window.unit
print("unit=%.4f  window=%dx%d" % (UNIT, window.width(), window.height()))


def drawn_points():
    """本帧会画到窗口上的点 → [(标签, 窗口像素)]（照 painter 复刻）。"""
    heading = window.spider.heading
    lean = getattr(window.spider, "lean", 0.0)
    sway = getattr(window.spider, "body_sway", 0.0)
    ox, oy = window._canvas_origin()
    cos_h, sin_h = math.cos(heading), math.sin(heading)

    def to_screen(local):
        x, y = local[0] * UNIT, (local[1] + sway) * UNIT
        return QPointF(ox + x * cos_h - y * sin_h, oy + x * sin_h + y * cos_h)

    points = []
    for leg in window.spider.legs:
        tag = "palp" if leg.palp else "leg%d" % leg.index
        hip, knee, tip = (to_screen(leg.hip_pos), to_screen(leg.knee),
                          to_screen(leg.tip))
        points += [("%s.hip" % tag, hip), ("%s.knee" % tag, knee),
                   ("%s.tip" % tag, tip)]
        for a, b, seg in ((hip, knee, "hk"), (knee, tip, "kt")):
            for k in (0.3, 0.6, 0.9):
                points.append(("%s.%s@%.1f" % (tag, seg, k),
                               QPointF(a.x() + (b.x() - a.x()) * k,
                                       a.y() + (b.y() - a.y()) * k)))
    center = to_screen((0.0, 0.0))
    points.append(("head.dot", to_screen(window.spider.body["head"])))
    points.append(("center", center))

    # 矩形 / 三角都跟着 heading + lean
    cb, sb = math.cos(heading + lean), math.sin(heading + lean)
    ts = UNIT * CS.THORAX_SCALE
    x0, y0, rw, rh = CS.THORAX
    for lx, ly in ((x0, y0), (x0 + rw, y0), (x0, y0 + rh), (x0 + rw, y0 + rh)):
        px, py = lx * ts, ly * ts
        points.append(("thorax(%.1f,%.1f)" % (lx, ly),
                       QPointF(center.x() + px * cb - py * sb,
                               center.y() + px * sb + py * cb)))
    for lx, ly in ((CS.HEAD_OFF, -CS.HEAD_TRI_HALF), (CS.HEAD_OFF, 0.0),
                   (CS.HEAD_OFF, CS.HEAD_TRI_HALF),
                   (CS.HEAD_OFF + CS.HEAD_TRI_LEN, 0.0)):
        px, py = lx * UNIT, ly * UNIT
        points.append(("head.tri(%.1f,%.1f)" % (lx, ly),
                       QPointF(center.x() + px * cb - py * sb,
                               center.y() + px * sb + py * cb)))

    transform = window._scene_transform()
    if transform is not None:
        points = [(n, transform.map(p)) for n, p in points]
    return points


def ghost_points():
    """**已经删掉的尾巴**：腹部 / 纺器。它们必须判不中（否则是隐形热区）。"""
    heading = window.spider.heading
    sway = getattr(window.spider, "body_sway", 0.0)
    ox, oy = window._canvas_origin()
    cos_h, sin_h = math.cos(heading), math.sin(heading)

    def to_screen(local):
        x, y = local[0] * UNIT, (local[1] + sway) * UNIT
        return QPointF(ox + x * cos_h - y * sin_h, oy + x * sin_h + y * cos_h)

    out = []
    for key in ("abd", "spin"):
        out.append(("tail.%s" % key, to_screen(window.spider.body[key])))
    return out


def explain(name, point):
    """把一个判不中的点反查回局部坐标，报出它离每个形状有多远。"""
    back = window._to_local(point.x(), point.y())
    sp = window.spider
    body = sp._body_point(back)
    leg = sp._leg_point(back)
    ts = CS.THORAX_SCALE
    x0, y0 = CS.THORAX[0] * ts, CS.THORAX[1] * ts
    x1, y1 = (CS.THORAX[0] + CS.THORAX[2]) * ts, (CS.THORAX[1] + CS.THORAX[3]) * ts
    pad = window.HIT_BODY_PAD_PX / window._local_per_px()
    print("    窗口=(%.1f,%.1f) → 局部=(%.2f,%.2f)  body系=(%.2f,%.2f)" %
          (point.x(), point.y(), back[0], back[1], body[0], body[1]))
    print("    在矩形内=%s（x∈[%.1f,%.1f] y∈[%.1f,%.1f]，容差 %.2f）  在三角内=%s" %
          (sp._in_thorax(body, pad), x0, x1, y0, y1, pad,
           sp._in_head_tri(body, pad)))
    best = min(min(CS.point_segment_distance(leg, L.hip_pos, L.knee),
                   CS.point_segment_distance(leg, L.knee, L.tip))
               for L in sp.legs)
    print("    到最近腿线段 %.3f（容差 %.3f＝%.0fpx）" %
          (best, window.HIT_LEG_PAD_PX / window._local_per_px(), window.HIT_LEG_PAD_PX))


print("\n-- 静态朝向 --")
for degrees in (90, 0, 180, 45, 135):
    window.spider.heading = math.radians(degrees)
    hit, miss = [], []
    for name, point in drawn_points():
        x, y = int(round(point.x())), int(round(point.y()))
        (hit if window._on_spider(x, y) else miss).append(name)
    print("heading=%3d°  命中 %2d  判不中 %d  %s"
          % (degrees, len(hit), len(miss), sorted(set(miss)) or ""))


print("\n-- 删掉的尾巴必须穿透 --")
bad = []
for degrees in (90, 0, 180, 270):
    window.spider.heading = math.radians(degrees)
    for name, point in ghost_points():
        if window._on_spider(int(round(point.x())), int(round(point.y()))):
            bad.append((degrees, name))
print("  %s" % ("全部穿透 ✓" if not bad else "仍在吃点击：%s" % bad))


print("\n-- 动态步态 240 帧（边走边转，lean 最大）--")
window.spider.heading = math.pi / 2
kinds, worst = {}, None
for frame in range(240):
    window.spider.update(1 / 60, "crawl", 165.0,
                         motion=(3.0, 1.5) if frame < 150 else (0.0, -2.0))
    for name, point in drawn_points():
        if not window._on_spider(int(round(point.x())), int(round(point.y()))):
            kinds.setdefault(name.split(".")[0].split("(")[0], []).append(frame)
            if worst is None:
                worst = (frame, name, point)
for kind, frames in sorted(kinds.items()):
    print("  %-14s %d 帧（例：%s）" % (kind, len(set(frames)), sorted(set(frames))[:5]))
if not kinds:
    print("  全部点得中 ✓")
elif worst:
    frame, name, point = worst
    print("\n  细看第 %d 帧的 %s：" % (frame, name))
    explain(name, point)
