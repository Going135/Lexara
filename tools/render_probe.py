# -*- coding: utf-8 -*-
"""蜘蛛渲染诊断：大图渲染 + 打印每条腿的髋/膝/脚（像素），用来定位几何问题。"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

import crawler_spider as CS
from spider_painter import SpiderPainter, SpiderState

app = QApplication(sys.argv)

WIDTH = 760
SIZE = 1000
img = QImage(SIZE, SIZE, QImage.Format_ARGB32)
img.fill(QColor(14, 18, 26))
painter = QPainter(img)
painter.setRenderHint(QPainter.Antialiasing, True)

spider = CS.Spider(size=1.0)
mode = sys.argv[1] if len(sys.argv) > 1 else "idle"
frames = int(sys.argv[2]) if len(sys.argv) > 2 else 180
for _ in range(frames):
    spider.update(1 / 60, mode, 0.0)

painter_s = SpiderPainter()
unit = SpiderPainter.unit_for_width(WIDTH)
origin = (SIZE / 2.0, SIZE / 2.0)
painter_s.paint(painter, spider, SpiderState(heading=0.0), unit=unit, origin_px=origin)

# 参考圈：静止位半径
pen = QPen(QColor(255, 255, 255, 40))
pen.setWidthF(1)
painter.setPen(pen)
painter.setBrush(Qt.NoBrush)
for leg in spider.legs:
    rp = painter_s.to_screen(spider.rest_pos(leg))
    painter.drawEllipse(int(rp[0]) - 3, int(rp[1]) - 3, 6, 6)

# 体心
painter.setPen(QPen(QColor(255, 255, 255), 2))
painter.drawLine(int(origin[0]) - 8, int(origin[1]),
                 int(origin[0]) + 8, int(origin[1]))

painter.end()
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "dist", "spider_probe_%s.png" % mode)
img.save(out)
print("saved", out, "unit=%.3f" % unit)

print("\n%-6s %-4s %-22s %-22s %-22s %8s %8s" %
      ("leg", "palp", "hip(px)", "knee(px)", "tip(px)", "knee-h", "tip-h"))
painter_s.setup(origin, unit, 0.0)
for leg in spider.legs:
    h = painter_s.to_screen(leg.hip_pos)
    k = painter_s.to_screen(leg.knee)
    t = painter_s.to_screen(leg.tip)
    r = painter_s.to_screen(spider.rest_pos(leg))
    print("%-6s %-4s (%7.1f,%7.1f) (%7.1f,%7.1f) (%7.1f,%7.1f) %8.1f %8.1f  rest偏移=%5.1f" % (
        leg.name if hasattr(leg, "name") else "leg%d" % leg.index,
        "是" if leg.palp else "否", h[0], h[1], k[0], k[1], t[0], t[1],
        math.hypot(k[0] - h[0], k[1] - h[1]) / unit,
        math.hypot(t[0] - h[0], t[1] - h[1]) / unit,
        math.hypot(t[0] - r[0], t[1] - r[1]) / unit))