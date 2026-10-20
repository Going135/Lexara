# -*- coding: utf-8 -*-
"""折叠（无腿模式）对照图：右键菜单文案 + 收腿/伸腿过程 + 折叠后的站位。

三件事一次看清：

  1. **菜单**：展开态那一项写「🧷 折叠」、折叠态那项写「🦵 展开」
     —— 直接调 `PetWindow._make_menu()` 渲染，不是另画一张示意图。
  2. **动画**：从 `eff_hide_legs` / `eff_show_legs` 的真实进度上掐帧，
     看腿往髋部缩 + 淡出、以及伸出去时身体的蓄力回弹。
  3. **折叠后的样子**：只剩本体；红虚线标出腿原来的落点（现在已穿透）。

蜘蛛走的是**生产 paintEvent**（`PetWindow.render`），所以朝向、侧摆、
一次性形变矩阵全都跟真机一致 —— 不是另搭一套几何去描，免得「图里好看、
真机上不是那样」。

运行：  python tools/fold_sheet.py
输出：  dist/shape/fold_sheet.png
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

# 故意不设 offscreen：那个平台的字体库枚举不到中文字族，中文会画成豆腐块。
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt               # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen     # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

import pet_window as PW                                             # noqa: E402
from pet_window import PetWindow                                    # noqa: E402

OUT = os.path.join(BASE, "dist", "shape")
os.makedirs(OUT, exist_ok=True)


class Clock:
    """假时钟：主循环和形变进度都读挂钟，要能把动画冻在任意进度。"""

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

BG_DARK = QColor(11, 16, 23)
BG_LIGHT = QColor(245, 247, 250)
INK_DARK = QColor(150, 175, 190)
INK_LIGHT = QColor(70, 88, 108)
TITLE = QColor(46, 230, 214)
MARK = QColor(232, 92, 92)


def font(px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSize(px)
    f.setBold(bold)
    return f


pet = PetWindow(None, None, sprite_w=360.0)
pet.effect = None
pet.resize(*pet._window_size())


def settle_frames(count: int = 150) -> None:
    """跑若干帧主循环，让八条腿从「刚出生」散到静止站姿。

    ★ 这一步不能省：`Spider` 新建时每条腿的 `tip` 都是 (0, 0)（还缩在体心），
    要 `update()` 跑够帧数才会张开。不跑就会画出一团挤在中心的东西 ——
    而且它看起来「也不是很像坏掉」，很容易被骗过去。
    `shape_sheet.py` 的 `idle()` 也是这么做的（同样 150 帧）。
    """
    pet.effect = None
    for _ in range(count):
        clock.t += 1.0 / 60.0
        pet._tick()
    pet.spider.lean = 0.0
    pet.spider.body_sway = 0.0
    pet.spider.clear_targets()


settle_frames()


def at_progress(effect: str, progress: float) -> None:
    """把折叠/展开冻在动画的第 `progress` 帧。

    `folded` 取的是**目标态**（这和 `set_folded()` 的做法一致），
    所以 `_leg_retract()` 从 `_leg_from` 插到目标 —— 和生产逻辑同一条式子。
    """
    duration = PW.anim.EFFECT_DURATION[effect]
    pet.folded = (effect == "hide_legs")
    pet._leg_from = 0.0 if effect == "hide_legs" else 1.0
    pet.effect = (effect, clock.t - progress * duration, duration)


def leg_footprints():
    """八条步足脚尖的窗口像素坐标（照 painter 复刻：只随 heading 转 + 侧摆）。"""
    import math
    heading = pet.spider.heading
    sway = getattr(pet.spider, "body_sway", 0.0)
    ox, oy = pet._canvas_origin()
    unit = pet.unit
    ch, sh = math.cos(heading), math.sin(heading)
    transform = pet._scene_transform()
    points = []
    for leg in pet.spider.legs:
        if leg.palp:
            continue
        x, y = leg.tip[0] * unit, (leg.tip[1] + sway) * unit
        point = QPointF(ox + x * ch - y * sh, oy + x * sh + y * ch)
        if transform is not None:
            point = transform.map(point)
        points.append(point)
    return points


def draw_spider(painter: QPainter, rect: QRectF, bg: QColor, ink: QColor,
                label: str, annotate: bool = False,
                forced_scale: float = None) -> None:
    """把桌宠按真实 paintEvent 渲染到 rect 这一格里。

    `forced_scale` 用来强制各格同比例 —— 不然每格各自「缩放到装得下」，
    格子大小不同就没法比较本体大小了。
    """
    # 窗口是「体心居中」的，所以把窗口整体摆到让体心落在格心即可
    scale = forced_scale or min(rect.width() / pet.width(),
                                rect.height() / pet.height())
    painter.save()
    painter.setClipRect(rect)
    painter.fillRect(rect, bg)

    if bg == BG_LIGHT:                       # 假桌面：看得出哪里是透明的
        painter.setPen(QPen(QColor(206, 215, 226), 1, Qt.DashLine))
        for k in range(1, 5):
            y = rect.top() + rect.height() * k / 5.0
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    image = QImage(pet.width(), pet.height(),
                   QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    pet.render(image)

    left = rect.center().x() - pet.width() * scale / 2.0
    top = rect.center().y() - pet.height() * scale / 2.0
    painter.drawImage(QRectF(left, top, pet.width() * scale, pet.height() * scale),
                      image, QRectF(0, 0, pet.width(), pet.height()))

    if annotate:
        painter.setPen(QPen(MARK, 1.1, Qt.DashLine))
        for point in leg_footprints():
            x = left + point.x() * scale
            y = top + point.y() * scale
            painter.drawEllipse(QPointF(x, y), 5.0, 5.0)
            painter.drawLine(QPointF(x - 8, y), QPointF(x + 8, y))
            painter.drawLine(QPointF(x, y - 8), QPointF(x, y + 8))
        painter.setPen(QPen(MARK))
        painter.setFont(font(8))
        painter.drawText(QRectF(rect.left() + 8, rect.top() + 8,
                                rect.width() - 16, 16),
                         Qt.AlignLeft, "红虚线 = 腿的原位，现在已穿透")

    painter.setPen(QPen(ink))
    painter.setFont(font(9))
    painter.drawText(QRectF(rect.left() + 6, rect.bottom() - 20,
                            rect.width() - 12, 16),
                     Qt.AlignRight, label)
    painter.restore()


def menu_image(folded: bool) -> QImage:
    """把真正的 `_make_menu()` 渲染出来（不是另画的示意图）。"""
    pet.folded = folded
    menu = pet._make_menu()
    menu.setStyleSheet(PW.MENU_QSS)
    menu.ensurePolished()
    menu.adjustSize()
    image = QImage(menu.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    # `render(QPainter)` 不接受单参重载，得给 targetOffset
    menu.render(image, QPoint(0, 0))
    return image


# ---------------------------------------------------------------- 排版

PAD = 16
FILM_COLS = 5
FILM_W, FILM_H = 250, 210
ROW1_W, ROW1_H = 414, 300
HEADER = 76
ROW_GAP = 24

#: 各格统一用这个比例（= 胶片格的「装得下」比例），格子大小不同也能比大小
CELL_SCALE = min((FILM_W - 8) / pet.width(), FILM_H / pet.height())

WIDTH = PAD * 2 + FILM_W * FILM_COLS
HEIGHT = HEADER + (ROW1_H + ROW_GAP) + (FILM_H + ROW_GAP) * 2 + PAD

sheet = QImage(WIDTH, HEIGHT, QImage.Format_ARGB32)
sheet.fill(BG_DARK)
outer = QPainter(sheet)
outer.setRenderHint(QPainter.Antialiasing, True)

outer.setPen(QPen(TITLE))
outer.setFont(font(14, bold=True))
outer.drawText(PAD, 32, "折叠（无腿模式）：右键菜单 + 收腿/伸腿过程 + 折叠后的站位")
outer.setPen(QPen(INK_DARK))
outer.setFont(font(9))
outer.drawText(PAD, 52,
               "菜单是直接渲染 PetWindow._make_menu()；蜘蛛走生产 paintEvent。"
               "折叠后腿不画、也不吃点击，本体照旧可拖。")

# ---- ① 右键菜单（两种状态）+ 折叠后站位
row_y = HEADER
outer.setPen(QPen(INK_DARK))
outer.setFont(font(9))
outer.drawText(PAD, row_y - 4, "① 右键菜单：那一项的文案跟着状态走")

for column, folded in enumerate((False, True)):
    cell = QRectF(PAD + column * (ROW1_W + 12), row_y + 12, ROW1_W, ROW1_H - 12)
    outer.fillRect(cell, QColor(9, 13, 19))
    image = menu_image(folded)
    outer.drawImage(QPointF(cell.left() + 6, cell.top() + 6), image)
    outer.setPen(QPen(INK_DARK))
    outer.setFont(font(9))
    outer.drawText(QRectF(cell.left() + 6, cell.bottom() - 18, cell.width(), 16),
                   Qt.AlignLeft,
                   "%s　→ 菜单里是「%s」"
                   % ("展开态" if not folded else "折叠态",
                      "折叠（收起八条腿）" if not folded else "展开（伸出八条腿）"))

cell = QRectF(PAD + 2 * (ROW1_W + 12), row_y + 12, ROW1_W, ROW1_H - 12)
pet.effect = None
pet.folded = True
pet._leg_from = 1.0
draw_spider(outer, cell, BG_LIGHT, INK_LIGHT, "", annotate=True,
            forced_scale=CELL_SCALE)
outer.setPen(QPen(INK_LIGHT))
outer.setFont(font(9))
outer.drawText(QRectF(cell.left() + 6, cell.bottom() - 18, cell.width() - 12, 16),
               Qt.AlignRight, "② 折叠后只剩本体（与上排同比例）")

# ---- ③ 收腿 / ④ 伸腿
label_y = row_y + ROW1_H + ROW_GAP
outer.setPen(QPen(INK_DARK))
outer.drawText(PAD, label_y - 4, "③ 收腿动画（右键「折叠」）：腿向髋部缩 + 淡出，"
                                "本体轻微膨胀")
for index, progress in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
    cell = QRectF(PAD + index * FILM_W, label_y + 10, FILM_W - 8, FILM_H)
    at_progress("hide_legs", progress)
    draw_spider(outer, cell, BG_DARK, INK_DARK,
                "%.0f%%  retract=%.2f" % (progress * 100, pet._leg_retract()),
                forced_scale=CELL_SCALE)

label_y += FILM_H + ROW_GAP
outer.setPen(QPen(INK_DARK))
outer.drawText(PAD, label_y - 4, "④ 伸腿动画（右键「展开」）：本体先蓄力收缩，"
                                "再把腿弹出去")
for index, progress in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
    cell = QRectF(PAD + index * FILM_W, label_y + 10, FILM_W - 8, FILM_H)
    at_progress("show_legs", progress)
    draw_spider(outer, cell, BG_LIGHT, INK_LIGHT,
                "%.0f%%  retract=%.2f" % (progress * 100, pet._leg_retract()),
                forced_scale=CELL_SCALE)

outer.end()

path = os.path.join(OUT, "fold_sheet.png")
sheet.save(path)
print("存图 → %s  %dx%d" % (path, sheet.width(), sheet.height()))
