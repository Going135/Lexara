# -*- coding: utf-8 -*-
"""身体特写：把「画出来的形状」和「点击热区」并排放大，一眼核对两件事 ——

  1. 尾巴（腹部 + 纺器）确实没了，那块现在是空的、并且**穿透**；
  2. 三角头放大了多少（和上一版 11×6.5 的轮廓对比），
     并且热区就是画出来的三角本身：**点三角 = 识词，点矩形 = 拖动**。

左格：渲染出来的身体（深底 + 浅底各一张，浅底上才看得出描边）
右格：热区叠加 —— 绿=三角（head/识词）、青=矩形（body/拖动）、红=已删的尾巴、
      虚线=上一版三角的大小。

运行：  python tools/body_zoom.py
输出：  dist/shape/body_zoom.png
"""
from __future__ import annotations

import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

# 故意**不**设 QT_QPA_PLATFORM=offscreen：offscreen 平台的字体库枚举不到中文字族，
# 画出来的标签会整片变成豆腐块（口口口）。本机有真实桌面会话，只渲染到 QImage、
# 不 show() 窗口，用默认的 windows 插件既安全、中文又正常。
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPointF, QRectF, Qt                        # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QPainter,          # noqa: E402
                           QPen, QPolygonF)
from PySide6.QtWidgets import QApplication                            # noqa: E402

import crawler_spider as CS                                           # noqa: E402
from spider_painter import SpiderPainter, SpiderState                 # noqa: E402

OUT = os.path.join(BASE, "dist", "shape")
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)

CELL_W, CELL_H = 460, 380
PAD, TITLE = 16, 62
UNIT = 4.2                       # 放大倍数（正常桌宠 unit≈1.23）
BG_DARK = QColor(11, 16, 23)
BG_LIGHT = QColor(245, 247, 250)

OLD_TRI = (11.0, 6.5)            # 上一版的三角（长度, 底半宽）


def font(px: int, bold: bool = False) -> QFont:
    """用默认字族。

    别写死 `QFont("Microsoft YaHei UI")` —— 在这个 venv 里解析不到该族，
    中文会整片画成豆腐块（`sheet.png` 用默认族就是好的）。
    """
    f = QFont()
    f.setPointSize(px)
    f.setBold(bold)
    return f


def make_spider() -> CS.Spider:
    s = CS.Spider(size=1.0)
    s.heading = -math.pi / 2     # 面朝上：截图里就是这个朝向
    return s


def body_cell(painter: QPainter, spider: CS.Spider, bg: QColor, label: str) -> None:
    painter.fillRect(0, 0, CELL_W, CELL_H, bg)
    origin = (CELL_W / 2.0, CELL_H / 2.0 + 10)
    sp = SpiderPainter()
    sp.paint(painter, spider, SpiderState(heading=spider.heading),
             unit=UNIT, origin_px=origin)
    painter.setPen(QColor(150, 175, 190) if bg == BG_DARK else QColor(90, 105, 120))
    painter.setFont(font(10))
    painter.drawText(QRectF(0, CELL_H - 30, CELL_W, 24), Qt.AlignCenter, label)


def region_cell(painter: QPainter, spider: CS.Spider, bg: QColor, label: str) -> None:
    """热区图：直接问 `hit_test` —— 一格一格扫，按返回的语义上色。

    这样画出来的就是**判定本身**，不是另写一套几何去描边，
    免得「描出来的框」和「真正吃的点击」是两回事。
    """
    painter.fillRect(0, 0, CELL_W, CELL_H, bg)
    origin_x, origin_y = CELL_W / 2.0, CELL_H / 2.0 + 10
    heading = spider.heading
    cos_h, sin_h = math.cos(heading), math.sin(heading)

    colors = {
        "head": QColor(60, 220, 130, 150),      # 绿：识词
        "body": QColor(80, 200, 255, 130),      # 青：拖动
    }
    painter.setPen(Qt.NoPen)
    for gx in range(0, CELL_W, 2):
        for gy in range(0, CELL_H, 2):
            dx, dy = gx - origin_x, gy - origin_y
            local = ((dx * cos_h + dy * sin_h) / UNIT,
                     (-dx * sin_h + dy * cos_h) / UNIT)
            got = spider.hit_test(local)
            if got:
                painter.setBrush(colors[got])
                painter.drawRect(gx, gy, 2, 2)

    # 上一版三角的大小（虚线，灰）
    old_len, old_half = OLD_TRI
    pen = QPen(QColor(200, 205, 215, 200), 1.2, Qt.DashLine)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    tri = [QPointF(*(_to_screen(p, origin_x, origin_y, cos_h, sin_h)))
           for p in ((CS.HEAD_OFF, -old_half), (CS.HEAD_OFF + old_len, 0.0),
                     (CS.HEAD_OFF, old_half))]
    painter.drawPolygon(QPolygonF(tri))

    # 已删的尾巴（红虚线）：从前胸后沿一直拉到纺器原来的位置
    painter.setPen(QPen(QColor(255, 90, 110, 220), 1.4, Qt.DashLine))
    rear = CS.THORAX[0] * CS.THORAX_SCALE
    tail_end = (CS.ABD_OFF + CS.SPIN_OFF) * CS.BASE_SCALE
    corners = (
        _to_screen((rear, -14.0), origin_x, origin_y, cos_h, sin_h),
        _to_screen((rear, 14.0), origin_x, origin_y, cos_h, sin_h),
        _to_screen((tail_end, -14.0), origin_x, origin_y, cos_h, sin_h),
        _to_screen((tail_end, 14.0), origin_x, origin_y, cos_h, sin_h),
    )
    a, b, c, d = corners
    painter.drawLine(QPointF(*a), QPointF(*c))
    painter.drawLine(QPointF(*b), QPointF(*d))
    painter.drawLine(QPointF(*a), QPointF(*b))
    painter.drawLine(QPointF(*c), QPointF(*d))
    mid = ((a[0] + c[0]) / 2, (b[1] + d[1]) / 2)
    painter.setPen(QColor(255, 120, 140))
    painter.setFont(font(9))
    painter.drawText(QRectF(mid[0] - 80, mid[1] - 9, 160, 18),
                     Qt.AlignCenter, "尾巴已删 · 现在穿透")

    painter.setPen(QColor(150, 175, 190))
    painter.setFont(font(10))
    painter.drawText(QRectF(0, CELL_H - 30, CELL_W, 24), Qt.AlignCenter, label)


def _to_screen(local, ox, oy, cos_h, sin_h):
    x, y = local[0] * UNIT, local[1] * UNIT
    return (ox + x * cos_h - y * sin_h, oy + x * sin_h + y * cos_h)


sheet = QImage(2 * (CELL_W + PAD) + PAD, 2 * (CELL_H + PAD) + PAD + TITLE,
               QImage.Format_ARGB32)
sheet.fill(QColor(6, 10, 14))
outer = QPainter(sheet)
outer.setRenderHint(QPainter.Antialiasing, True)
outer.setRenderHint(QPainter.SmoothPixmapTransform, True)
outer.setRenderHint(QPainter.TextAntialiasing, True)
outer.setPen(QColor(46, 230, 214))
outer.setFont(font(14, bold=True))
outer.drawText(PAD, 30, "身体特写：删掉尾巴、放大三角头，热区就是画出来的形状")
outer.setPen(QColor(150, 175, 190))
outer.setFont(font(9))
outer.drawText(PAD, 50, "绿 = 三角头（点它识词）　青 = 矩形身（点它拖动）　"
                        "红虚线 = 已删的尾巴位置（现在完全穿透）　灰虚线 = 上一版三角的大小")

cells = (
    ("渲染 · 深色桌面", BG_DARK, body_cell),
    ("渲染 · 浅色文档", BG_LIGHT, body_cell),
    ("热区 · 深色", BG_DARK, region_cell),
    ("热区 · 浅色", BG_LIGHT, region_cell),
)
for index, (label, bg, draw) in enumerate(cells):
    col, row = index % 2, index // 2
    cell = QImage(CELL_W, CELL_H, QImage.Format_ARGB32)
    cell.fill(bg)
    inner = QPainter(cell)
    inner.setRenderHint(QPainter.Antialiasing, True)
    inner.setRenderHint(QPainter.TextAntialiasing, True)
    draw(inner, make_spider(), bg, label)
    inner.end()
    outer.drawImage(PAD + col * (CELL_W + PAD), TITLE + PAD + row * (CELL_H + PAD), cell)
outer.end()

path = os.path.join(OUT, "body_zoom.png")
sheet.save(path)
print("存图 → dist/shape/body_zoom.png  %dx%d（单格 %dx%d，unit=%.1f，"
      "三角 %g×%g ← 上一版 %g×%g）"
      % (sheet.width(), sheet.height(), CELL_W, CELL_H, UNIT,
         CS.HEAD_TRI_LEN, CS.HEAD_TRI_HALF, OLD_TRI[0], OLD_TRI[1]))
