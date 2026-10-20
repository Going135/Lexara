# -*- coding: utf-8 -*-
"""把自检截图里的蜘蛛区裁出来放大，便于肉眼核对形象。"""
import os
import sys

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "dist", "selftest")
OUT = os.path.join(ROOT, "dist", "shape")
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)

# 蜘蛛按屏幕中心附近绘制；这个矩形在 2560×1600 下覆盖它
REGION = QRect(560, 200, 820, 820)

for name in sorted(os.listdir(SRC)):
    if not name.endswith(".png") or not name[0].isdigit():
        continue
    img = QImage(os.path.join(SRC, name))
    if img.isNull():
        continue
    rect = REGION.intersected(QRect(0, 0, img.width(), img.height()))
    if rect.isEmpty():
        continue
    out = img.copy(rect)
    path = os.path.join(OUT, "zoom_" + name)
    out.save(path)
    print("saved", path, out.width(), out.height())
