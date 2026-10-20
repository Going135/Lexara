# -*- coding: utf-8 -*-
"""瞄准层渲染诊断：把「蜘蛛 + 8 个词 + 引导线 + 词框」整幅渲染出来，
用来检查站姿是否拟真、引导线是否像射线、有没有异常色块。"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient,
                           QImage, QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QApplication

import crawler_spider as CS
from spider_painter import SpiderPainter, SpiderState, qcolor

app = QApplication(sys.argv)

W, H = 1600, 1000
img = QImage(W, H, QImage.Format_ARGB32)
img.fill(QColor(24, 28, 34))
painter = QPainter(img)
painter.setRenderHint(QPainter.Antialiasing, True)

BODY = (W * 0.5, H * 0.27 + 90)
SPIDER_W = 420.0
unit = SpiderPainter.unit_for_width(SPIDER_W * 1.35)

WORDS = ["abandon", "committee", "government", "insufficient",
         "supervise", "project", "support", "absence"]
spots = [(W * 0.16 + i * 0.095 * W, H * 0.18 + (i % 3) * 52) for i in range(8)]

spider = CS.Spider(size=1.0)
for _ in range(60):
    spider.update(1 / 60, "idle", 0.0)

render = SpiderPainter()
render.setup(BODY, unit, spider.heading)

# 屏幕点 → 局部点
targets = []
steppers = [L for L in spider.legs if not L.palp]
targets = [CS.Target(text=w, center=render.to_local(*p)) for w, p in zip(WORDS, spots)]

# 注意：**不要传 unit**。assign_reachable 全程走局部单位（hip_pos 与
# Target.center 都是调用方 to_local 换算好的），把 unit 乘进可达半径就等于
# 放宽 unit 倍（瞄准层约 1.66×），腿立刻被拉成射线 —— 之前踩过这个坑。
pairs = CS.assign_reachable(steppers, targets, max_frac=0.92)
spider.targets = {}
guides = []
for pair in pairs:
    leg = steppers[pair["leg"]]
    target = targets[pair["target"]]
    spider.targets[leg.index] = target.center
    guides.append((leg, target))

for _ in range(2):
    spider.update(1 / 60, "idle", 0.0)

# 1) 蜘蛛
render.paint(painter, spider, SpiderState(focus=True, heading=spider.heading),
             unit=unit, origin_px=BODY)

# 2) 引导线（弧线 + 渐隐）
for leg, target in guides:
    start = render.to_screen(leg.tip)
    end = render.to_screen(target.center)
    span = math.hypot(end[0] - start[0], end[1] - start[1])
    if span < 2:
        continue
    nx, ny = -(end[1] - start[1]) / span, (end[0] - start[0]) / span
    bulge = min(72.0, span * 0.2)
    control = ((start[0] + end[0]) / 2 + nx * bulge,
               (start[1] + end[1]) / 2 + ny * bulge)
    path = QPainterPath()
    path.moveTo(*start)
    path.quadTo(control[0], control[1], end[0], end[1])
    painter.setBrush(Qt.NoBrush)
    grad = QLinearGradient(start[0], start[1], end[0], end[1])
    grad.setColorAt(0.0, qcolor(leg.aura, 0.85))
    grad.setColorAt(0.55, qcolor(leg.aura, 0.32))
    grad.setColorAt(1.0, qcolor(leg.aura, 0.05))
    for width in (3.4, 1.5):
        # 注意：QPen 没有「只吃 QGradient」的构造签名，必须包一层 QBrush。
        # 之前写 QPen(grad) 会直接 TypeError 把整个探针打断。
        pen = QPen(QBrush(grad), width)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawPath(path)
    painter.setPen(QPen(qcolor(leg.aura, 0.55), 1.2))
    painter.drawLine(QPointF(end[0] - 5, end[1]), QPointF(end[0] + 5, end[1]))
    painter.drawLine(QPointF(end[0], end[1] - 5), QPointF(end[0], end[1] + 5))

# 3) 词框
font = QFont("Microsoft YaHei UI", 11)
font.setBold(True)
painter.setFont(font)
metrics = QFontMetricsF(font)
for index, (leg, target) in enumerate(guides):
    cx, cy = render.to_screen(target.center)
    text = target.text
    tw = metrics.horizontalAdvance(text)
    th = metrics.height()
    box = QRectF(cx - tw / 2 - 9, cy - th / 2 - 5, tw + 18, th + 10)
    glow = QRadialGradient(box.center(), box.width())
    glow.setColorAt(0.0, qcolor(leg.aura, 0.28))
    glow.setColorAt(1.0, qcolor(leg.aura, 0.0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(glow))
    painter.drawEllipse(box.center(), box.width(), box.width())
    painter.setPen(QPen(qcolor(leg.aura, 0.9), 1.6))
    painter.setBrush(QColor(10, 16, 22, 210))
    painter.drawRoundedRect(box, 8, 8)
    painter.setPen(qcolor("#f2fffd", 0.96))
    painter.drawText(box, Qt.AlignCenter, text)

painter.end()
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "dist", "aim_probe.png")
img.save(out)
print("saved", out, "heading=%.2f rad (%.0f deg)" % (spider.heading,
                                                     math.degrees(spider.heading)))
print("tip 距离:")
for leg, target in guides:
    d = math.hypot(target.center[0] - leg.hip_pos[0], target.center[1] - leg.hip_pos[1])
    print("  %s 腿长=%.0f(%.0fpx) 上限=%.0f 目标距离=%.0f(%.0fpx) 占腿长=%.2f×" %
          (leg.aura, leg.full, leg.full * unit, leg.full * 0.92,
           d, d * unit, d / leg.full))