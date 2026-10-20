# -*- coding: utf-8 -*-
"""腿长倍率对比图：同一个词环，在 ×1.0 / ×1.3 / ×1.6 下踩词的样子。

用途：`AIM_LEG_STRETCH` 是个观感参数，测试只能证明「够得着」，
证明不了「好不好看」。这个脚本把三种倍率并排画出来，一眼定该给多少。

    python tools/leg_reach_sheet.py

面板从左到右 = `FACTORS` 的顺序，具体数字打印在 stdout。
**图里不写任何文字**：离屏平台（`QT_QPA_PLATFORM=offscreen`）在本机枚举不到
可用字体库，连 ASCII 都画成豆腐块（`aim_overlay.font_()` 上面那段注释说的就是
这件事）。所以别在这里加 `drawText`，加了只会得到一排方框。

产出 → dist/aim/leg_reach_sheet.png
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import math                                                       # noqa: E402

from PySide6.QtCore import QRectF                                # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPen          # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

import aim_overlay as AO                                          # noqa: E402
import crawler_spider as CS                                       # noqa: E402
from spider_painter import SpiderPainter, SpiderState             # noqa: E402

STEP = 1.0 / 60.0

#: 词环半径（**屏幕像素**）。取一个「原来的腿够不着、拉长后够得着」的值：
#: 老腿长下后足可达 335px、前足 314px，400px 正好落在这段差距里。
RING_PX = 400.0

#: 对比的倍率（面板从左到右）
FACTORS = (1.0, 1.3, 1.6)

#: 面板边长：要装得下 400px 的词环（半径 400 → 对角 566）再留余量
PANEL = 900


def build(factor: float):
    """造一只蜘蛛：八条步足各朝自己髋部的方向，去踩一个 400px 外的词。

    方向按「髋部朝外」取，是最坏情况 —— 每条腿都得往外伸。
    """
    spider = CS.Spider(size=1.0)
    for _ in range(150):                       # 先散到静止位
        spider.update(STEP, motion=(0.0, 0.0))
    spider.lean = 0.0
    spider.body_sway = 0.0

    painter = SpiderPainter()
    unit = SpiderPainter.unit_for_width(360.0 * AO.AIM_SCALE_BOOST)
    painter.setup((0.0, 0.0), unit, spider.heading)

    spider.set_leg_stretch(factor)

    ring_local = RING_PX / unit
    targets, marks = {}, []
    for leg in spider.legs:
        if leg.palp:
            continue
        hx, hy = leg.hip_pos
        span = math.hypot(hx, hy) or 1.0
        point = (hx + hx / span * ring_local, hy + hy / span * ring_local)
        targets[leg.index] = point
        marks.append(point)
    spider.targets = targets

    for _ in range(90):                        # 让脚尖伸过去
        spider.update(STEP, motion=(0.0, 0.0))

    errors = []
    for leg in spider.legs:
        if leg.palp:
            continue
        goal = targets[leg.index]
        errors.append(math.hypot(leg.tip[0] - goal[0],
                                 leg.tip[1] - goal[1]) * unit)
    return spider, painter, unit, marks, errors


def render_panel(painter: QPainter, spider, spider_painter, unit, marks,
                 ox: int) -> None:
    """把一个面板画进大图的 `ox` 列（原点在图左上）。"""
    painter.save()
    painter.setClipRect(QRectF(ox, 0, PANEL, PANEL))
    painter.translate(ox + PANEL / 2.0, PANEL / 2.0)

    # 词框（代表屏幕上被框出来的词）
    painter.setPen(QPen(QColor("#4a5560"), 1.5))
    painter.setBrush(QColor("#20262c"))
    for point in marks:
        sx, sy = spider_painter.to_screen(point)
        painter.drawRoundedRect(QRectF(sx - 26, sy - 11, 52, 22), 5, 5)

    # 蜘蛛本体
    spider.origin_px = (0.0, 0.0)
    spider_painter.paint(painter, spider,
                         SpiderState(dim=1.0, focus=True, joint_glow=1.0,
                                     heading=spider.heading, moving=False),
                         unit=unit, origin_px=(0.0, 0.0))
    painter.restore()


def main() -> None:
    QApplication(sys.argv)

    image = QImage(len(FACTORS) * PANEL, PANEL, QImage.Format_ARGB32)
    image.fill(QColor("#101418"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    for column, factor in enumerate(FACTORS):
        ox = column * PANEL
        spider, spider_painter, unit, marks, _ = build(factor)
        render_panel(painter, spider, spider_painter, unit, marks, ox)

        if column:                             # 面板分隔线
            painter.setPen(QPen(QColor("#2a3238"), 2))
            painter.drawLine(ox, 0, ox, PANEL)

    painter.end()

    out_dir = os.path.join(BASE, "dist", "aim")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "leg_reach_sheet.png")
    image.save(path)

    print("词环半径 %.0fpx（老腿长够不着的距离）" % RING_PX)
    for factor in FACTORS:
        spider, _, unit, _, errors = build(factor)
        reach = max(L.full for L in spider.legs if not L.palp) * unit * 0.92
        print("  ×%.1f  可达 %4.0fpx  离词还差 %5.1fpx"
              % (factor, reach, max(errors)))
    print("存图 → %s" % path)


if __name__ == "__main__":
    main()
