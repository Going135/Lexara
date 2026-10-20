# -*- coding: utf-8 -*-
"""触须（pedipalp）髋部位置对照：旧「身子前缘正中」vs 新「头前方两侧」。

上下两行，每行左旧右新：
  · 上行 = 整只蜘蛛（看远观像不像「长在头上」）
  · 下行 = 头部特写（红圈是髋部，蓝虚线是头部三角）

两档都用生产 paintEvent 渲染，朝向摆正到 +x、lean/sway 归零。「旧」那一档是
**把两根触须的髋部整体平移回旧坐标**得到的（foot 一起平移同样距离），所以
腿型、步态、身体完全一样，差别只有髋长在哪。

运行：  python tools/_palp_preview.py
输出：  dist/shape/palp_hip.png
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt                # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QPainter, QPen,      # noqa: E402
                           QPolygonF)
from PySide6.QtWidgets import QApplication                            # noqa: E402

import crawler_spider as CS                                           # noqa: E402
import pet_window as PW                                               # noqa: E402

OUT = os.path.join(BASE, "dist", "shape")
os.makedirs(OUT, exist_ok=True)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def strftime(self, fmt):
        import time as real
        return real.strftime(fmt)


clock = Clock()
PW.time = clock
app = QApplication(sys.argv)

pet = PW.PetWindow(None, None, sprite_w=360.0)
pet.effect = None
pet.resize(*pet._window_size())
pet._timer.stop()
pet.bubble.hide_now()
screen = pet._screen_rect()
pet.center = QPoint(int(screen.center().x()), int(screen.center().y()))

for _ in range(150):
    clock.t += 1.0 / 60.0
    pet._tick()
pet.spider.clear_targets()


def settle(frames=30):
    """推到稳定状态并摆成**待机徽章姿势**（用户平时看到的就是这个）。"""
    for _ in range(frames):
        clock.t += 1.0 / 60.0
        pet._tick()
    pet.spider.heading = 0.0
    pet.spider.lean = 0.0
    pet.spider.body_sway = 0.0
    pet.spider._idle_pose_t = 1.0
    for _ in range(130):
        pet.spider.heading = 0.0
        pet.spider.lean = 0.0
        pet.spider.body_sway = 0.0
        pet.spider._idle_pose_t = 1.0
        clock.t += 1.0 / 60.0
        pet._tick()


settle(60)

sp = pet.spider
sc = sp.scale
pals = [L for L in sp.legs if L.palp]
assert len(pals) == 2, pals

NEW = [(L.hip, L.hip_y) for L in pals]
OLD = [(10.0 * sc, L.side * 3.0 * sc) for L in pals]

u = pet.unit
BOX = 78.0
ZOOM = 3.0
PANEL = int(BOX * 2 * ZOOM)          # 特写面板边长
CROP_CX, CROP_CY = 46.0, 0.0
FULL = 520                            # 全身面板边长（586 窗口缩到这个）

panels = []


def grab(label: str, hips):
    for leg, (hx, hy) in zip(pals, hips):
        dx, dy = hx - leg.hip, hy - leg.hip_y
        leg.hip, leg.hip_y = hx, hy
        leg.foot = (leg.foot[0] + dx, leg.foot[1] + dy)
    settle(24)
    image = QImage(pet.width(), pet.height(), QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    pet.render(image)
    pet.render(image)
    ox, oy = pet._canvas_origin()
    crop = image.copy(int(ox + CROP_CX - BOX), int(oy + CROP_CY - BOX),
                      int(BOX * 2), int(BOX * 2))
    return {"label": label, "full": image, "crop": crop,
            "hips": [(L.hip, L.hip_y) for L in pals]}


panels.append(grab("旧：HIP_SIDE（身子前缘正中）", OLD))
panels.append(grab("新：头部三角底边两侧", NEW))

HEAD_H = 34
ROW1_Y = HEAD_H
ROW2_Y = ROW1_Y + FULL + 14 + HEAD_H
W = PANEL * 2
H = ROW2_Y + PANEL + 46

out = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
out.fill(QColor(246, 247, 249))
p = QPainter(out)
p.setRenderHint(QPainter.SmoothPixmapTransform, True)
p.setRenderHint(QPainter.Antialiasing, True)


def to_panel(x0: float, y0: float, lx: float, ly: float) -> QPointF:
    """局部坐标 → 面板坐标（heading=0，局部 y 向下为正）。"""
    return QPointF(x0 + (lx - CROP_CX + BOX) * ZOOM,
                   y0 + (ly - CROP_CY + BOX) * ZOOM)


for i, item in enumerate(panels):
    x0 = i * PANEL

    # ---- 上行：全身 ----
    p.drawImage(QRectF(x0, ROW1_Y, FULL, FULL), item["full"],
                QRectF(0, 0, item["full"].width(), item["full"].height()))
    p.setPen(QColor(30, 34, 40))
    p.setFont(QFont("Segoe UI", 12, QFont.Bold))
    p.drawText(QPointF(x0 + 12, ROW1_Y - 10), item["label"])

    # ---- 下行：头部特写 ----
    crop = item["crop"]
    y0 = ROW2_Y
    p.drawImage(QRectF(x0, y0, PANEL, PANEL), crop,
                QRectF(0, 0, crop.width(), crop.height()))

    pts = [to_panel(x0, y0, CS.HEAD_OFF, -CS.HEAD_TRI_HALF),
           to_panel(x0, y0, CS.HEAD_OFF + CS.HEAD_TRI_LEN, 0.0),
           to_panel(x0, y0, CS.HEAD_OFF, CS.HEAD_TRI_HALF)]
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(120, 190, 240, 210), 1.3, Qt.DashLine))
    p.drawPolygon(QPolygonF(pts))

    for hx, hy in item["hips"]:
        pt = to_panel(x0, y0, hx, hy)
        p.setPen(QPen(QColor(235, 80, 70), 1.8))
        p.setBrush(QColor(235, 80, 70, 60))
        p.drawEllipse(pt, 6.0, 6.0)

    h0 = item["hips"][0]
    p.setPen(QColor(200, 60, 55))
    p.setFont(QFont("Consolas", 10))
    p.drawText(QPointF(x0 + 12, y0 + PANEL + 26),
               "髋 (%.1f, ±%.1f) 局部单位　·　头三角底边 x=%.0f 半宽 ±%.0f"
               % (h0[0], abs(h0[1]), CS.HEAD_OFF, CS.HEAD_TRI_HALF))

p.setPen(QColor(90, 96, 104))
p.setFont(QFont("Segoe UI", 10))
p.drawText(QPointF(12, ROW2_Y + PANEL + 44),
           "蓝虚线 = 头部三角（HEAD_OFF / HEAD_TRI_LEN / HEAD_TRI_HALF）　·　"
           "红圈 = 触须髋部　·　触须不参与踩词（palp=True）")
p.end()

path = os.path.join(OUT, "palp_hip.png")
out.save(path)
print("saved", path, "%dx%d" % (out.width(), out.height()))
