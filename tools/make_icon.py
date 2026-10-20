# -*- coding: utf-8 -*-
"""把程序化蜘蛛渲染成程序图标（多尺寸 .ico）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

import crawler_spider as CS
from spider_painter import SpiderPainter, SpiderState

app = QApplication(sys.argv)

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
png_path = os.path.join(base_dir, "assets", "icon.png")
ico_path = os.path.join(base_dir, "assets", "icon.ico")
os.makedirs(os.path.dirname(png_path), exist_ok=True)

# 先让腿落到静止站姿，再渲染
spider = CS.Spider(size=1.0)
for _ in range(90):
    spider.update(1 / 60, "idle", 0.0)

SIZE = 256
image = QImage(SIZE, SIZE, QImage.Format_ARGB32)
image.fill(Qt.transparent)
painter = QPainter(image)
painter.setRenderHint(QPainter.Antialiasing, True)
render = SpiderPainter()
unit = SpiderPainter.unit_for_width(SIZE * 0.96)
render.paint(painter, spider, SpiderState(focus=True, heading=0.0),
             unit=unit, origin_px=(SIZE / 2.0, SIZE / 2.0))
painter.end()
image.save(png_path)
print("png ->", png_path)

try:
    from PIL import Image
    source = Image.open(png_path)
    source.save(ico_path, format="ICO",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                       (64, 64), (128, 128), (256, 256)])
    print("ico ->", ico_path)
except ImportError:
    print("PIL 不可用，跳过 ico")