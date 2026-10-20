# -*- coding: utf-8 -*-
"""把自检截图裁成便于查看的小图（蜘蛛区 / 屏幕中央区）。"""
import os
import sys

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter, QGuiApplication
from PySide6.QtWidgets import QApplication

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "dist", "selftest")
OUT = os.path.join(BASE, "crop")
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)

# 蜘蛛在屏幕右下角：物理像素 ≈ (2320, 1375)，dpr=1.5
PET_REGION = QRect(1990, 1080, 570, 520)
CENTER_REGION = QRect(560, 240, 1440, 1120)

for name in sorted(os.listdir(BASE)):
    if not name.endswith(".png"):
        continue
    image = QImage(os.path.join(BASE, name))
    if image.isNull():
        continue
    stem = name[:-4]
    for label, region in (("pet", PET_REGION), ("mid", CENTER_REGION)):
        rect = region.intersected(QRect(0, 0, image.width(), image.height()))
        if rect.isEmpty():
            continue
        crop = image.copy(rect)
        target = QImage(crop.width(), crop.height(), QImage.Format_RGB32)
        target.fill(Qt.black)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(QRect(0, 0, target.width(), target.height()), crop)
        painter.end()
        path = os.path.join(OUT, "%s_%s.png" % (stem, label))
        target.save(path)
        print("saved", path, target.width(), target.height())
print("done")
