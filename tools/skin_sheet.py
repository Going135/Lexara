# -*- coding: utf-8 -*-
"""皮肤对照图：四套皮肤 ×（浅底 / 深底 / 玻璃罐底）。

为什么要三块底：桌宠是**透明置顶**窗口，落在什么壁纸上都有可能。
「白跳蛛在白底上还看不看得见」这种问题，只在单色底上渲染是看不出来的 ——
必须把浅底（文档/网页）、深底（深色主题）、以及启动台那种玻璃底都过一遍。

用法：
    python tools/skin_sheet.py            # → dist/skin/skin_sheet.png
"""

from __future__ import annotations

import os
import sys

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SRC, "src"))
sys.path.insert(0, SRC)

from PySide6.QtCore import QPointF, QRectF, Qt                    # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPen)
from PySide6.QtWidgets import QApplication                        # noqa: E402

import crawler_spider as CS                                       # noqa: E402
import spider_painter as SP                                       # noqa: E402

OUT_DIR = os.path.join(SRC, "dist", "skin")

CELL_W, CELL_H = 300, 214
LABEL_H = 26
#: ★ 用 `unit_for_width` 反推，不能拍一个常数。
#:   腿的静止跨度 = `2 × max_reach × BASE_SCALE × REST_K` 个局部单位，
#:   拍一个偏大的 unit 会让腿整条甩出格子外 —— 而**腿色恰恰是四套皮肤
#:   最主要的区别**，漏掉腿就等于什么也没比。
SPAN_W = CELL_W * 0.82
UNIT = SP.SpiderPainter.unit_for_width(SPAN_W)

#: 三种底：预览用的「桌面环境」
BACKGROUNDS = (
    ("白底", QColor(255, 255, 255)),
    ("浅灰底", QColor(237, 241, 246)),
    ("深色底", QColor(24, 28, 34)),
)


def settled_spider() -> CS.Spider:
    """一只**站好的**蜘蛛。

    ★ 不能直接 `CS.Spider()` 就画 —— 新构造出来的 `Leg.knee` / `Leg.tip`
      都是 `(0, 0)`，要等第一次 `update()` 才会解算出真实位置。
      直接画的话八条腿会全部塌在体心上（被身体盖住），看起来「腿没画出来」。
      这里照 `update()` 里静止分支的算法手动摆一次，确定性且不推进步态。
    """
    spider = CS.Spider(size=1.0)
    spider.origin_px = (0.0, 0.0)
    for leg in spider.legs:
        foot = spider.rest_pos(leg)
        leg.tip = foot
        leg.knee = spider.solve_ik(leg.hip_pos, foot, leg.l1, leg.l2, leg.bend)
    return spider


def paint_cell(painter: QPainter, x: float, y: float, skin_id: str,
               back: QColor, dark: bool) -> None:
    painter.fillRect(QRectF(x, y, CELL_W, CELL_H), back)

    painter_layer = SP.SpiderPainter()
    painter_layer.set_skin(skin_id)
    painter_layer.paint(
        painter, settled_spider(),
        SP.SpiderState(heading=0.0, dim=1.0),
        unit=UNIT,
        origin_px=(x + CELL_W / 2, y + CELL_H / 2 + 4),
    )

    name = SP.SKIN_SPECS[skin_id].name
    painter.setPen(QColor(255, 255, 255) if dark else QColor(26, 26, 26))
    painter.setFont(QFont("Microsoft YaHei", 10))

    # 每个底各自标注「这一格是什么底」，否则整张图上分不清哪列是哪列
    painter.drawText(QRectF(x + 8, y + 4, CELL_W - 16, LABEL_H - 6),
                     int(Qt.AlignLeft | Qt.AlignVCenter),
                     "%s · %s" % (name, back.name()))


def main() -> int:
    app = QApplication(sys.argv)                                  # noqa: F841
    os.makedirs(OUT_DIR, exist_ok=True)

    skins = [sid for sid, _ in SP.skin_options()]
    cols = len(BACKGROUNDS)
    rows = len(skins)

    gap = 10
    head_h = 34
    width = gap + cols * (CELL_W + gap)
    height = head_h + gap + rows * (CELL_H + gap)

    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(248, 249, 251))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    painter.setPen(QColor(26, 26, 26))
    painter.setFont(QFont("Microsoft YaHei", 13, QFont.DemiBold))
    painter.drawText(QRectF(gap, 4, width - gap * 2, head_h - 6),
                     int(Qt.AlignLeft | Qt.AlignVCenter),
                     "八足微光 · 蜘蛛皮肤对照（默认 %s）"
                     % SP.SKIN_SPECS[SP.DEFAULT_SKIN].name)

    for row, skin_id in enumerate(skins):
        y = head_h + gap + row * (CELL_H + gap)
        for col, (name, back) in enumerate(BACKGROUNDS):
            x = gap + col * (CELL_W + gap)
            paint_cell(painter, x, y, skin_id, back, name.endswith("底") and
                       back.lightness() < 110)

    painter.end()

    path = os.path.join(OUT_DIR, "skin_sheet.png")
    image.save(path)
    print("存图 → %s  %dx%d" % (path, width, height))

    # 顺带把每套皮肤在三种底上的「墨迹量」打出来 —— 白底上的白蜘蛛如果
    # 只靠淡描边，这个数会明显偏小，是「看不见」的量化信号。
    for skin_id in skins:
        counts = []
        for name, back in BACKGROUNDS:
            cell = QImage(CELL_W, CELL_H, QImage.Format_ARGB32_Premultiplied)
            cell.fill(back)
            cp = QPainter(cell)
            cp.setRenderHint(QPainter.Antialiasing, True)
            layer = SP.SpiderPainter()
            layer.set_skin(skin_id)
            layer.paint(cp, settled_spider(), SP.SpiderState(heading=0.0, dim=1.0),
                        unit=UNIT, origin_px=(CELL_W / 2, CELL_H / 2 + 4))
            cp.end()
            # 与底色差异明显的像素数 = 真能看见的部分
            diff = 0
            for yy in range(0, CELL_H, 2):
                for xx in range(0, CELL_W, 2):
                    color = cell.pixelColor(xx, yy)
                    if (abs(color.red() - back.red())
                            + abs(color.green() - back.green())
                            + abs(color.blue() - back.blue())) > 42:
                        diff += 1
            counts.append("%s %5d" % (name, diff))
        print("  %-18s %s" % (SP.SKIN_SPECS[skin_id].name, "  ".join(counts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
