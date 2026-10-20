# -*- coding: utf-8 -*-
"""临时预览：把词框画在一段假网页文字上，看「盖住原文 + 框内生成词」的实际观感。

词框不是手填的：先用 QFontMetricsF 量出每个词的**墨迹框**，再交给覆盖层，
这样「露不露原文」看到的就是真实效果。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import crawler_spider as CS
from spider_painter import SpiderPainter
from aim_overlay import AimOverlay


class StubPet:
    def __init__(self):
        self.sprite_w = 360.0
        self.spider = CS.Spider(size=1.0)
        self.painter = SpiderPainter()
        self.center = QPoint(500, 900)

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

    def char_rect(self):
        return QRect(480, 480, 40, 40)

    def show(self):
        pass

    def raise_(self):
        pass


def lay_out(text, family, px, x0, baseline):
    """把一行拆成词，返回 [(word, 墨迹框)] —— 墨迹框就是覆盖层要盖住的范围。"""
    font = QFont(family, px)
    metrics = QFontMetricsF(font)
    out = []
    x = x0
    for token in text.split(" "):
        ink = metrics.tightBoundingRect(token)
        out.append((token, (x + ink.left(), baseline + ink.top(),
                            ink.width(), ink.height()), x))
        x += metrics.horizontalAdvance(token + " ")
    return out


LINES = [
    ("The committee abandoned the obligatory tests.", "Georgia", 21, 40, 90, 2),
    ("I am a witness to this catastrophe, truly.", "Georgia", 21, 40, 150, 2),
    ("small print: the committee abandoned the obligatory tests in 1987.",
     "Georgia", 13, 40, 210, 2),
]

words, spans = [], []
for text, family, px, x0, baseline, _pick in LINES:
    for token, box, tx in lay_out(text, family, px, x0, baseline):
        spans.append((token, box, family, px, tx, baseline))
        # 只挑几个词做框，别把整行铺满
        if token.strip(".,:").lower() in ("committee", "abandoned", "obligatory",
                                          "i", "catastrophe"):
            words.append({
                "lemma": token.strip(".,:").lower(),
                "surface": token.strip(".,:"),
                "screen_pos": (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0),
                "screen_box": box,
            })

ov = AimOverlay(StubPet(), words, stagger=0.0)
ov._timer.stop()

img = QImage(int(ov.width()), int(ov.height()), QImage.Format_ARGB32_Premultiplied)
# 深色网页底：词框是暗色玻璃 + 同色辉光，在深底上才看得出真实观感
img.fill(QColor(18, 22, 28))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing, True)
p.setRenderHint(QPainter.TextAntialiasing, True)
p.translate(-ov._offset.x(), -ov._offset.y())
for token, box, family, px, tx, baseline in spans:
    p.setFont(QFont(family, px))
    p.setPen(QColor(226, 232, 240))
    # QPoint 版本的原点就是**基线起点**，和量墨迹框时用的是同一套坐标
    p.drawText(QPoint(tx, baseline), token)

ov.render(p, QPoint(0, 0))
ov.close()
p.end()

crop = img.copy(0, 40, min(760, img.width()), min(220, img.height() - 40))
out = os.path.join(BASE, "dist", "box_preview.png")
crop.save(out)
print("saved", out, crop.width(), crop.height(), "| 框数", len(words))
