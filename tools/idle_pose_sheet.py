# -*- coding: utf-8 -*-
"""待机姿势对照板 —— 用真状态机（阈值步态 + 姿势淡入）驱动，出「头朝上」剪影。

与参考图对拍 IDLE_POSE 用：每个候选姿势跑 5 秒（300 帧）让腿落位，
再用 SpiderPainter 原皮画一遍，拼成一张带标签的对照图。

运行：  python tools/idle_pose_sheet.py
输出：  dist/pose/idle_sheet.png
"""
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt                       # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPen     # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

import crawler_spider as CS                                  # noqa: E402
from spider_painter import SpiderPainter, SpiderState, SKIN_SPECS  # noqa: E402

OUT = os.path.join(BASE, "dist", "pose")
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv)

#: 候选姿势：每项 = (名字, IDLE_POSE 四步足 (角 rad, 伸展系数)，触须固定)
D = math.radians
CANDIDATES = [
    ("A_current",  ((0.96, 1.26), (1.48, 1.26), (2.09, 1.26), (2.72, 1.26))),
    ("B_sweep",    ((D(10), 1.26), (D(25), 1.26), (D(148), 1.26), (D(170), 1.26))),
    ("C_len",      ((D(10), 1.05), (D(25), 1.27), (D(148), 1.00), (D(170), 1.15))),
    ("D_swapRear", ((D(10), 1.05), (D(25), 1.27), (D(170), 1.00), (D(148), 1.15))),
    ("E_swapFront",((D(25), 1.05), (D(10), 1.27), (D(170), 1.00), (D(148), 1.15))),
    ("F_swapBoth", ((D(25), 1.05), (D(10), 1.27), (D(148), 1.00), (D(170), 1.15))),
    # G/H：按参考图钉比例 —— 前足外拱(±24°)最长、内拱(±8°)约 0.90；
    #      后足 ±148° 约 0.75、±170° 约 0.62（相对最长腿）
    ("G_tuned",    ((D(24), 1.26), (D(9), 1.13), (D(170), 1.00), (D(148), 1.26))),
    ("H_tunedSwap",((D(9), 1.13), (D(24), 1.26), (D(148), 1.26), (D(170), 1.00))),
    # P*：参考图的拱形 = 膝盖**朝外**凸（与走路时相反），脚尖钩回体轴附近。
    #     flip=True 在落位后把 bend 取反验证形状。
    ("P1_arch",    ((D(24), 1.26), (D(9), 1.26), (D(170), 0.87), (D(148), 0.88)), True),
    ("P2_arch",    ((D(24), 1.26), (D(9), 1.13), (D(170), 1.00), (D(148), 1.26)), True),
    ("P3_arch",    ((D(10), 1.26), (D(25), 1.26), (D(148), 1.00), (D(170), 0.85)), True),
]

CELL = 560
UNIT = 1.35


def render(name, pose4, frames=300, flip=False):
    CS.IDLE_POSE = tuple(pose4) + ((0.22, 1.00),)
    sp = CS.Spider(size=1.0, mode="idle")
    for _ in range(frames):
        sp.update(1 / 60.0, mode="idle")
    if flip:
        for leg in sp.legs:
            if not leg.palp:
                leg.bend = -leg.bend
                leg.knee = sp.solve_ik(leg.hip_pos, leg.tip, leg.l1, leg.l2, leg.bend)
    img = QImage(CELL, CELL, QImage.Format_ARGB32)
    img.fill(QColor(16, 22, 30))
    p = QPainter(img)
    painter = SpiderPainter()
    painter.set_skin("original")
    # heading = -PI/2：面朝屏幕上 = 与参考图同向（头朝上）
    painter.paint(p, sp, SpiderState(heading=-math.pi / 2),
                  unit=UNIT, origin_px=(CELL / 2.0, CELL / 2.0))
    p.setPen(QPen(QColor(255, 255, 255), 2))
    p.drawText(14, 28, name)
    # 量一下腿尖相对体轴的角，方便和参考图（±8/±24/±148/±170°）核对
    info = []
    for leg in sp.legs:
        if leg.palp:
            continue
        fx = leg.tip[0] * math.cos(-math.pi / 2) - leg.tip[1] * math.sin(-math.pi / 2)
        fy = leg.tip[0] * math.sin(-math.pi / 2) + leg.tip[1] * math.cos(-math.pi / 2)
        rel = math.degrees(math.atan2(fx, -fy))     # 相对体轴（屏幕上=上），右正
        info.append("s%d%s %5.0f° r=%3.0f" % (leg.slot, "R" if leg.side == 1 else "L",
                                              rel, math.hypot(fx, fy) ))
    p.setPen(QPen(QColor(160, 220, 255), 1))
    for i, line in enumerate(info):
        p.drawText(14, CELL - 118 + i * 14, line)
    p.end()
    path = os.path.join(OUT, "idle_%s.png" % name)
    img.save(path)
    print(name, "|", "  ".join(info))
    return img


rendered = [(c[0], render(c[0], c[1], flip=len(c) > 3)) for c in CANDIDATES]

# 拼图：直接读各自已保存的 PNG，避免碰 QImage 内部缓冲
from PIL import Image as PILImage
cols = 3
rows = (len(rendered) + cols - 1) // cols
sheet = PILImage.new("RGB", (CELL * cols, CELL * rows))
for i, (n, _) in enumerate(rendered):
    tile = PILImage.open(os.path.join(OUT, "idle_%s.png" % n)).convert("RGB")
    sheet.paste(tile, ((i % cols) * CELL, (i // cols) * CELL))
sheet.save(os.path.join(OUT, "idle_sheet.png"))
print("输出：", os.path.join(OUT, "idle_sheet.png"))
