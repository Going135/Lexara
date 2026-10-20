# -*- coding: utf-8 -*-
"""换装缩略图调试：不同 heading / unit / 背景 对比成一张 sheet。"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

import crawler_spider as CS
from spider_painter import SKIN_ORDER, SpiderPainter, SpiderState

CELL = 170
VARIANTS = [
    ("h=0 u=128", 0.0, 128),
    ("h=pi/2 u=128", math.pi / 2, 128),
    ("h=pi/2 u=150", math.pi / 2, 150),
    ("h=pi/2 u=110", math.pi / 2, 110),
]


def render(heading: float, width_px: float, skin: str, bg: QColor) -> QImage:
    image = QImage(CELL, CELL, QImage.Format_ARGB32_Premultiplied)
    image.fill(bg)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    spider = CS.Spider(size=1.0)
    spider.heading = heading
    # 先跑几帧让腿落到静止站姿（新 Spider 的 targets/legs 还没经过一次 update）
    for _ in range(20):
        spider.update(0.016, "idle", None, motion=(0.0, 0.0))
    renderer = SpiderPainter()
    renderer.set_skin(skin)
    unit = SpiderPainter.unit_for_width(width_px)
    renderer.paint(painter, spider,
                   SpiderState(heading=heading, moving=False, dim=1.0),
                   unit=unit, origin_px=(CELL / 2.0, CELL / 2.0 + 6))
    painter.end()
    return image


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    skins = ["white_jump_spider", "original", "milk_spider", "pixel_spider"]
    sheet = QImage(CELL * len(VARIANTS), CELL * len(skins),
                   QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#F2F3F5"))
    painter = QPainter(sheet)
    for row, skin in enumerate(skins):
        for col, (label, heading, width_px) in enumerate(VARIANTS):
            tile = render(heading, width_px, skin, QColor("#FFFFFF"))
            painter.drawImage(col * CELL, row * CELL, tile)
            painter.setPen(QColor("#BBBBBB"))
            painter.drawRect(col * CELL, row * CELL, CELL - 1, CELL - 1)
            painter.setPen(QColor("#333333"))
            painter.drawText(col * CELL + 6, row * CELL + 14, label)
    painter.setPen(QColor("#111111"))
    for row, skin in enumerate(skins):
        painter.drawText(CELL * len(VARIANTS) - 4 - 130, row * CELL + 14, skin)
    painter.end()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "backup", "skin_thumb_probe.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(os.path.normpath(out))
    print("saved", os.path.normpath(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
