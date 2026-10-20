# -*- coding: utf-8 -*-
"""头部关节对照图：**旧顺序（点画在最上层）vs 新顺序（点压在身体/头部之下）**。

为什么单独做一张：这颗点（`_paint_body` 里的 head joint）本身只有
`2.2 × dr` 那么大，在整只蜘蛛的对照图（`skin_sheet.py`）里是一个几像素的
小点，缩略图上根本看不出差别 —— 但图皮的头部素材画的是一张**脸**，
它正好落在脸部横向 32%、垂直居中的位置，落在脸上就非常显眼。

四套皮肤 × 两种状态（静止 / 思考·瞄准）各出一组对照，并且把
「新旧两张图的像素差」打出来：差多少像素，就是那颗点实际遮掉了多少。

用法：
    python tools/head_joint_sheet.py      # → dist/skin/head_joint_sheet.png
"""

from __future__ import annotations

import os
import sys

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SRC, "src"))
sys.path.insert(0, SRC)

from PySide6.QtCore import QPointF, QRectF, Qt                     # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QImage,          # noqa: E402
                           QPainter, QRadialGradient)
from PySide6.QtWidgets import QApplication                         # noqa: E402

import crawler_spider as CS                                        # noqa: E402
import spider_painter as SP                                        # noqa: E402

OUT_DIR = os.path.join(SRC, "dist", "skin")

CELL_W, CELL_H = 220, 126
ZOOM = 2.2
UNIT = 2.0
LABEL_H = 22

#: 体心在格子里的位置（**逻辑**像素，不是输出像素）。
#: 取这个值是为了让「整只蜘蛛的躯干 + 头」正好落进格子：
#: 躯干后沿在体心左侧 `-THORAX[0]*THORAX_SCALE*UNIT ≈ 27px`，
#: 头尖在右侧 `(HEAD_OFF+HEAD_TRI_LEN)*UNIT = 58px`。
#: 格子逻辑宽 100px → 左边留 32、右边到 90，两头都不切。
#: ★ 定这个值之前踩过坑：想当然按「格子中心 = 体心」放，
#:   结果头部整块被切在框外，图上只剩一个躯干屁股。
BODY_ORIGIN = (32.0, CELL_H / ZOOM / 2.0)

#: 成对出现：先复现旧顺序，再画现在的新顺序
VARIANTS = (("旧：点画在最上层", True), ("新：点压在头图层之下", False))
#: 两种会画到这颗点的状态 —— `focus` 由 pet_window 的 think 态、
#: aim_overlay 的瞄准态、以及托盘图标三处置 True
STATES = (("静止", False, 1.0), ("思考 · 瞄准", True, 1.0))


def settled_spider() -> CS.Spider:
    """一只站好的蜘蛛（腿必须先解算出来，否则八条腿全塌在体心）。"""
    spider = CS.Spider(size=1.0)
    spider.origin_px = (0.0, 0.0)
    for leg in spider.legs:
        foot = spider.rest_pos(leg)
        leg.tip = foot
        leg.knee = spider.solve_ik(leg.hip_pos, foot, leg.l1, leg.l2, leg.bend)
    return spider


class LegacyOrderPainter(SP.SpiderPainter):
    """复现**旧**顺序：身体画完之后，再把那颗点补在最上层。

    只用于对照图，不进产品代码 —— 产品里 `_paint_body` 已经把点挪到图层下方。
    取值口径和改动前逐字一致（半径 `2.2 × dr`、颜色 `spec.joint`）。
    """

    def _paint_body(self, painter, spider, state, lw, dr, dim):
        super()._paint_body(painter, spider, state, lw, dr, dim)

        sox, soy = self._sway_offset
        screen = self.to_screen(spider.body["head"])
        head = (screen[0] + sox, screen[1] + soy)
        spec = self.skin_spec()
        glow = max(0.0, min(1.0, state.joint_glow))
        radius = 2.2 * dr

        if state.focus:                     # 旧顺序里辉光也在最上层
            halo = QRadialGradient(QPointF(*head), radius * 4.0)
            halo.setColorAt(0.0, SP.qcolor(spec.joint, 0.75 * dim * glow))
            halo.setColorAt(1.0, SP.qcolor(spec.joint, 0.0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(QPointF(*head), radius * 4.0, radius * 4.0)

        painter.setPen(Qt.NoPen)
        painter.setBrush(SP.qcolor(spec.joint, dim))
        painter.drawEllipse(QPointF(*head), radius, radius)


def render(skin_id: str, focus: bool, legacy: bool) -> QImage:
    """把**头部特写**渲染成一个 CELL 尺寸的离屏图。"""
    cell = QImage(CELL_W, CELL_H, QImage.Format_ARGB32_Premultiplied)
    cell.fill(QColor(255, 255, 255))

    painter = QPainter(cell)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(ZOOM, ZOOM)

    layer = LegacyOrderPainter() if legacy else SP.SpiderPainter()
    layer.set_skin(skin_id)
    layer.paint(
        painter, settled_spider(),
        SP.SpiderState(heading=0.0, dim=1.0, focus=focus),
        unit=UNIT,
        origin_px=BODY_ORIGIN,
    )
    painter.end()
    return cell


def diff_pixels(a: QImage, b: QImage) -> int:
    n = 0
    for y in range(a.height()):
        for x in range(a.width()):
            ca, cb = a.pixelColor(x, y), b.pixelColor(x, y)
            if (abs(ca.red() - cb.red()) + abs(ca.green() - cb.green())
                    + abs(ca.blue() - cb.blue())) > 12:
                n += 1
    return n


def main() -> int:
    app = QApplication(sys.argv)                                   # noqa: F841
    os.makedirs(OUT_DIR, exist_ok=True)

    skins = [sid for sid, _ in SP.skin_options()]
    cols = len(skins)
    rows = len(VARIANTS) * len(STATES)

    gap, title_h, col_head_h, row_head_h = 10, 34, 24, 22
    width = gap + cols * (CELL_W + gap)
    top = title_h + col_head_h
    height = top + gap + rows * (row_head_h + CELL_H + gap)

    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(248, 249, 251))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    painter.setPen(QColor(26, 26, 26))
    painter.setFont(QFont("Microsoft YaHei", 13, QFont.DemiBold))
    painter.drawText(QRectF(gap, 4, width - gap * 2, title_h - 6),
                     int(Qt.AlignLeft | Qt.AlignVCenter),
                     "八足微光 · 头部关节点的绘制顺序对照（特写 %.1f×）" % ZOOM)

    # 列首：四套皮肤各占一列（对齐上面那句标题，别让读者去数格子）
    painter.setFont(QFont("Microsoft YaHei", 10, QFont.DemiBold))
    painter.setPen(QColor(60, 66, 74))
    for col, skin_id in enumerate(skins):
        x = gap + col * (CELL_W + gap)
        painter.drawText(QRectF(x + 4, title_h, CELL_W - 8, col_head_h),
                         int(Qt.AlignLeft | Qt.AlignVCenter),
                         SP.SKIN_SPECS[skin_id].name)

    differ = {}
    row = 0
    for state_name, focus, _ in STATES:
        for variant_name, legacy in VARIANTS:
            y = top + gap + row * (row_head_h + CELL_H + gap)
            is_legacy = legacy
            painter.setPen(QColor(0, 102, 255) if is_legacy else QColor(90, 96, 104))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(QRectF(gap, y, width - gap * 2, row_head_h - 6),
                             int(Qt.AlignLeft | Qt.AlignVCenter),
                             "%s · %s" % (state_name, variant_name))
            for col, skin_id in enumerate(skins):
                x = gap + col * (CELL_W + gap)
                cell = render(skin_id, focus, legacy)
                painter.drawImage(QRectF(x, y + row_head_h, CELL_W, CELL_H), cell)
                if legacy:
                    differ[(state_name, skin_id)] = diff_pixels(
                        cell, render(skin_id, focus, False))
            row += 1

    painter.end()
    path = os.path.join(OUT_DIR, "head_joint_sheet.png")
    image.save(path)
    print("存图 → %s  %dx%d" % (path, width, height))
    print()
    print("  新旧两张特写的像素差（= 那颗点实际占掉/遮住的面积）")
    for (state_name, skin_id), n in differ.items():
        print("    %-10s %-18s %4d px" % (state_name,
                                          SP.SKIN_SPECS[skin_id].name, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
