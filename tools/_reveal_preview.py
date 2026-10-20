# -*- coding: utf-8 -*-
""">8 词模式的出框取证：框必须跟着腿一个一个亮，不是一批齐刷刷弹出。

12 个词排成 4×3，全部落在腿能踩到的范围里（身体不走位，只看框）。
按 t = 0.2 / 0.45 / 0.7 / 1.0 秒各截一帧，拼成 2×2 对比图。
输出 dist/reveal_preview.png。
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import crawler_spider as CS
import aim_overlay as AO
from aim_overlay import AimOverlay
from spider_painter import SpiderPainter

W, H = 1707, 1067                      # 逻辑屏尺寸（和真机一致）
# 12 个词挤在腿展之内（身体不走位，只看「框一个一个亮」这件事）
COL_X = [703, 873, 1043, 1213]
ROW_Y = [453, 533, 613]
TEXTS = ["abandon", "witness", "trivial", "commute",
         "diligent", "sustain", "fragile", "genuine",
         "precise", "vivid", "oblige", "wander"]
FONT_PX = 22


class StubPet:
    def __init__(self, center):
        self.sprite_w = 360.0
        self.spider = CS.Spider(size=1.0)
        self.painter = SpiderPainter()
        self.center = QPoint(int(center[0]), int(center[1]))

        class _B:
            def hide_now(self):
                pass
        self.bubble = _B()

    def _build_state(self):
        class _S:
            dim = 1.0
        return _S()

    def _mode_label(self):
        return "cet4"

    def _place_dialog(self, *a, **k):
        pass

    def show(self):
        pass

    def raise_(self):
        pass


font = QFont("Georgia", FONT_PX)
metrics = QFontMetricsF(font)
words, spans = [], []
for i, text in enumerate(TEXTS):
    x = COL_X[i % 4]
    y = ROW_Y[i // 4]
    ink = metrics.tightBoundingRect(text)
    box = (x + ink.left(), y + ink.top(), ink.width(), ink.height())
    spans.append((text, x, y))
    words.append({
        "lemma": text, "surface": text, "meaning": "释义", "level": "",
        "screen_pos": (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0),
        "screen_box": box,
    })

pet = StubPet((W / 2.0, H / 2.0))
for _ in range(180):
    pet.spider.update(1.0 / 60.0, "crawl", None, motion=(0.0, 0.0))

ov = AimOverlay(pet, words, stagger=0.06)
ov._timer.stop()
print("compact=%s 词数=%d 首批腿=%d stretch=%.2f"
      % (ov._compact_scan, len(ov.session.order), len(ov._pairs), ov.leg_stretch))

SHOTS = [0.25, 0.50, 0.75, 1.20]
COUNT_AT = [(t, 0) for t in SHOTS]
STEP = 1.0 / 60.0
step = 0

# 背景：白底 + 原文
bg = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
bg.fill(QColor(250, 250, 250))
pb = QPainter(bg)
pb.setRenderHint(QPainter.TextAntialiasing, True)
pb.setFont(font)
pb.setPen(QColor(24, 24, 24))
for text, x, y in spans:
    pb.drawText(QPoint(x, y), text)
pb.end()

shots, frames = [], []
for shot in SHOTS:
    while step * STEP < shot:
        t0 = time.monotonic()
        pet.spider.update(STEP, "crawl", None, motion=(0.0, 0.0))
        ov._tick()
        step += 1
        time.sleep(max(0.0, STEP - (time.monotonic() - t0)))
    canvas = QImage(bg)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)
    ov.render(p, QPoint(0, 0))
    p.end()
    shots.append(canvas)
    stats = ov.session.stats()
    frames.append((shot, len(ov._guides)))
    print("t=%.2fs 框=%d 已完成=%d 在途=%d" % (shot, len(ov._guides),
                                              stats["completed"], stats["active"]))
ov.close()

CW, CH = W // 2, H // 2
out = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
out.fill(QColor(255, 255, 255))
p = QPainter(out)
p.setRenderHint(QPainter.SmoothPixmapTransform, True)
for i, canvas in enumerate(shots):
    scaled = canvas.scaled(CW, CH, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p.drawImage(QPoint((i % 2) * CW, (i // 2) * CH), scaled)
    p.setPen(QColor(20, 20, 20))
    p.setFont(QFont("Segoe UI", 15, QFont.Bold))
    label = "t=%.2fs   %d 个框" % frames[i]
    p.drawText(QPointF((i % 2) * CW + 16, (i // 2) * CH + 28), label)
p.end()
path = os.path.join(BASE, "dist", "reveal_preview.png")
out.save(path)
print("saved", path)
