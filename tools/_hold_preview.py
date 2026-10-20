# -*- coding: utf-8 -*-
"""验证「八词以内 = 原地定位」：宽跨度词群下八条腿是否真的伸出去。

场景照抄用户给的验证图（1080×608，五个词铺满四角 + 正中央）。
底图直接当背景，词框按图上文字的位置给，输出 dist/hold_preview.png
+ 控制台数字（leg_stretch / 派腿数 / 完成数 / 身体位移）。
"""
import math
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import crawler_spider as CS
import aim_overlay as AO
from aim_overlay import AimOverlay
from spider_painter import SpiderPainter

SRC = r"C:\Users\35388\Desktop\生成图片.png"
GEO = AO.union_geometry()
OX, OY = GEO.x(), GEO.y()

# 图上五个词的墨迹框（1080×608 原图坐标）
BOXES = [("DREAM", 84, 94, 79, 20), ("EXPLORE", 917, 95, 87, 18),
         ("CREATE", 481, 290, 119, 22), ("INSPIRE", 84, 500, 79, 20),
         ("ACHIEVE", 917, 500, 84, 19)]


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


base = QImage(SRC)
if base.isNull():
    W, H = 1080, 608
else:
    # 原图是 2 倍图（2048×1152）。屏幕上它是按 1080×608 **逻辑像素**显示的，
    # 覆盖层吃的也是逻辑坐标 —— 所以先缩回逻辑尺寸，框才能和字对齐。
    base = base.scaled(1080, 608)
    W, H = base.width(), base.height()
SX = SY = 1.0

words = []
for text, x, y, w, h in BOXES:
    x, y, w, h = x * SX, y * SY, w * SX, h * SY
    words.append({
        "lemma": text.lower(), "surface": text, "meaning": "释义", "level": "",
        "screen_pos": (OX + x + w / 2.0, OY + y + h / 2.0),
        "screen_box": (OX + float(x), OY + float(y), float(w), float(h)),
    })

pet = StubPet((OX + W / 2.0, OY + H / 2.0 + 150 * SY))
for _ in range(180):
    pet.spider.update(1.0 / 60.0, "crawl", None, motion=(0.0, 0.0))

ov = AimOverlay(pet, words, stagger=0.0)
ov._timer.stop()
print("compact=%s 词数=%d stretch=%.3f 派腿=%d"
      % (ov._compact_scan, len(ov.session.order), ov.leg_stretch, len(ov._pairs)))

STEP = 1.0 / 60.0
body0 = (float(pet.center.x()), float(pet.center.y()))
for _ in range(90):                      # ~1.5s
    t0 = time.monotonic()
    pet.spider.update(STEP, "crawl", None, motion=(0.0, 0.0))
    ov._tick()
    time.sleep(max(0.0, STEP - (time.monotonic() - t0)))
st = ov.session.stats()
print("1.5s 后 完成=%d 踩到=%d 只亮框=%d 失败=%d 批=%d"
      % (st["completed"], st["pegged"], st["box_only"], st["failed"], st["batches"]))
print("身体位移 %.2fpx" % math.hypot(pet.center.x() - body0[0],
                                    pet.center.y() - body0[1]))

img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
img.fill(QColor(252, 252, 252))
if not base.isNull():
    img = base.convertToFormat(QImage.Format_ARGB32_Premultiplied)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing, True)
p.translate(-OX, -OY)
ov.render(p, QPoint(0, 0))
ov.close()
p.end()
out = os.path.join(BASE, "dist", "hold_preview.png")
img.save(out)
print("saved", out)
