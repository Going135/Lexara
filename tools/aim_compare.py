# -*- coding: utf-8 -*-
"""把「平时站姿」和「识词瞄准姿态」并排放，用来肉眼核对瞄准效果是否正常。

运行：  python tools/aim_compare.py
输出：  dist/aim/pose_vs_aim.png
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QRect, Qt                              # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter          # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

OUT = os.path.join(BASE, "dist", "aim")
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv)

idle_path = os.path.join(BASE, "dist", "pose", "01_idle.png")
aim_path = os.path.join(OUT, "e2e_aim.png")
for path in (idle_path, aim_path):
    if not os.path.exists(path):
        raise SystemExit("缺少素材：%s\n请先跑 tools/pose_probe.py 和 tools/aim_e2e.py" % path)

idle = QImage(idle_path)
aim = QImage(aim_path)
print("idle %dx%d   aim %dx%d" % (idle.width(), idle.height(),
                                  aim.width(), aim.height()))

TH = 380
PAD = 18
TITLE = 92
W = PAD * 3 + TH * 2
H = TITLE + TH + PAD * 2
out = QImage(W, H, QImage.Format_ARGB32)
out.fill(QColor(11, 16, 23))
p = QPainter(out)
p.setRenderHint(QPainter.SmoothPixmapTransform, True)
p.setRenderHint(QPainter.TextAntialiasing, True)

p.setPen(QColor(46, 230, 214))
p.setFont(QFont("Microsoft YaHei UI", 15, QFont.Bold))
p.drawText(PAD, 40, "八足微光 · 平时站姿 vs 识词瞄准")
p.setPen(QColor(150, 175, 190))
p.setFont(QFont("Microsoft YaHei UI", 9))
p.drawText(PAD, 62, "右图是瞄准层实拍：八个词各有一个与「踩它的那条腿」同色的光框，"
                    "八条腿依次伸出去按住各自的词。")
p.drawText(PAD, 80, "够得着的词才派腿；够不着的只亮框，腿保持自然站姿 —— 不再拉成一束射线。")

left = idle.scaled(TH, TH, Qt.KeepAspectRatio, Qt.SmoothTransformation)
# 瞄准层取体心附近（体心在 800x800 画布上的位置由 aim_e2e 决定，这里按已知值裁）
cx, cy = 379, 192
box = QRect(cx - 190, cy - 190, 380, 380).intersected(QRect(0, 0, aim.width(), aim.height()))
right = aim.copy(box).scaled(TH, TH, Qt.KeepAspectRatio, Qt.SmoothTransformation)

for index, (img, label) in enumerate([(left, "平时站姿（idle）"),
                                      (right, "识词瞄准（八腿踩词 + 词框）")]):
    x = PAD + index * (TH + PAD)
    p.fillRect(x, TITLE, TH, TH, QColor(17, 23, 32))
    p.drawImage(x + (TH - img.width()) // 2, TITLE + (TH - img.height()) // 2, img)
    p.setPen(QColor(150, 175, 190))
    p.setFont(QFont("Microsoft YaHei UI", 11))
    p.drawText(x, TITLE + TH + 24, label)
p.end()

path = os.path.join(OUT, "pose_vs_aim.png")
out.save(path)
print("saved", path, out.width(), out.height())
