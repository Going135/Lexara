# -*- coding: utf-8 -*-
"""折叠时身体「朝头部缩小」的特写对照：走**真实右键折叠**的动画进度。

三格分别截在折叠动画的 0% / 约 50% / 100%（`PetWindow.set_folded(True)`
驱动，不是手塞 `body_fold`），都用生产 paintEvent 渲染（朝向临时摆正到 +x），
只把身体那块裁出来放大，每格叠两圈线：
  · 红虚线 = 未折叠时的身体框
  · 蓝实线 = 当前实际绘制框
锚点在前缘（靠头那侧）—— 红蓝两条**右边那条边完全重合**，左边和上下往里收。

运行：  python tools/_fold_zoom.py
输出：  dist/shape/fold_body_zoom.png
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt                # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QPainter, QPen)      # noqa: E402
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

# 摆正朝向：这次只看身体几何，不看向朝哪边
pet.spider.heading = 0.0
pet.spider.lean = 0.0
pet.spider.body_sway = 0.0
pet.spider._idle_pose_t = 1.0

u = pet.unit
ts = u * CS.THORAX_SCALE
raw = QRectF(CS.THORAX[0] * ts, CS.THORAX[1] * ts,
             CS.THORAX[2] * ts, CS.THORAX[3] * ts)

ZOOM = 2.4
BOX = 130.0
PANEL_W = int(BOX * 2 * ZOOM)
PANEL_H = int(BOX * 2 * ZOOM)

# 未折叠时的**画出来的**身体框（含皮肤的 body_scale 放大）
skin_scale = float(getattr(pet.painter.skin_spec(), "body_scale", 1.0) or 1.0)
open_rect = pet.painter._body_draw_rect(raw)
# 裁剪中心 = 这个框的中心（局部像素坐标；heading=0 时窗口坐标就是 origin + 局部）
crop_cx = open_rect.center().x()
crop_cy = open_rect.center().y()

panels = []


def grab():
    pet.spider.heading = 0.0
    pet.spider.lean = 0.0
    pet.spider.body_sway = 0.0
    pet.spider._idle_pose_t = 1.0
    image = QImage(pet.width(), pet.height(), QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    pet.render(image)
    pet.render(image)
    ox, oy = pet._canvas_origin()
    crop = image.copy(int(ox + crop_cx - BOX), int(oy + crop_cy - BOX),
                      int(BOX * 2), int(BOX * 2))
    return float(pet.spider.fold_depth), crop


panels.append(grab())                 # 折叠前
pet.set_folded(True)
for _ in range(15):                   # ≈0.25s：动画半途
    clock.t += 1.0 / 60.0
    pet._tick()
panels.append(grab())
for _ in range(60):                   # 收完
    clock.t += 1.0 / 60.0
    pet._tick()
panels.append(grab())

out = QImage(PANEL_W * 3, PANEL_H + 46, QImage.Format_ARGB32_Premultiplied)
out.fill(QColor(246, 247, 249))
p = QPainter(out)
p.setRenderHint(QPainter.SmoothPixmapTransform, True)
p.setRenderHint(QPainter.Antialiasing, True)


def panel_rect(x0: float, rect: QRectF) -> QRectF:
    """局部像素框 → 面板里的屏幕框（裁剪中心是 crop_cx/crop_cy）。"""
    return QRectF(x0 + (rect.left() - crop_cx + BOX) * ZOOM,
                  46 + (rect.top() - crop_cy + BOX) * ZOOM,
                  rect.width() * ZOOM, rect.height() * ZOOM)


for i, (fold, crop) in enumerate(panels):
    x0 = i * PANEL_W
    p.drawImage(QRectF(x0, 46, PANEL_W, PANEL_H), crop,
                QRectF(0, 0, crop.width(), crop.height()))
    p.setPen(QColor(30, 34, 40))
    p.setFont(QFont("Segoe UI", 13, QFont.Bold))
    p.drawText(QPointF(x0 + 14, 30),
               "fold_depth = %.2f   可见体长 %.0f%%"
               % (fold, (1.0 - CS.BODY_FOLD_SHRINK * fold) * 100))

    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(220, 60, 90), 1.6, Qt.DashLine))
    p.drawRect(panel_rect(x0, open_rect))

    cur = pet.painter._folded_body_rect(raw, pet.spider)
    # 折叠完再按皮肤倍率放大（和渲染同一链）
    cur = QRectF(cur.right() - cur.width() * skin_scale,
                 cur.center().y() - cur.height() * skin_scale / 2.0,
                 cur.width() * skin_scale, cur.height() * skin_scale)
    p.setPen(QPen(QColor(40, 130, 220), 1.6))
    p.drawRect(panel_rect(x0, cur))

p.setPen(QColor(90, 96, 104))
p.setFont(QFont("Segoe UI", 10))
p.drawText(QPointF(14, PANEL_H + 40),
           "红虚线 = 未折叠时的身体框　·　蓝实线 = 当前绘制框　·　"
           "锚点在前缘（靠头那侧，右边那条边不动），后缘与上下一起往里收")
p.end()

path = os.path.join(OUT, "fold_body_zoom.png")
out.save(path)
print("saved", path, "%dx%d" % (out.width(), out.height()))
