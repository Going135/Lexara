# -*- coding: utf-8 -*-
"""OCR 坐标回归测试：验证小图被放大后，词坐标仍落在**原图**范围内。

背景：
    `OcrEngine.recognize_lines` 对宽度 < 800px 的选区会先放大 2 倍再送模型。
    如果不把坐标除回去，八条腿就会踩到错一倍的位置上 ——
    这是八足微光实测发现过的 bug，这里钉死它。

运行：  python test/test_ocr_coords.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from ocr_engine import OcrEngine

app = QApplication(sys.argv)

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if condition else "[FAIL]", name, detail))


def render(width, height, lines, size=19):
    image = QImage(width, height, QImage.Format_RGB888)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    painter.setPen(QColor(18, 20, 30))
    painter.setFont(QFont("Arial", size))
    step = height // (len(lines) + 1)
    for index, text in enumerate(lines):
        painter.drawText(QRect(20, step * index + 4, width - 30, step),
                         int(Qt.AlignLeft | Qt.AlignVCenter), text)
    painter.end()
    return image


TEXT = ["The committee abandoned",
        "the government project"]

# 小图宽度 < 800 → 触发内部 2 倍放大（修复前坐标会翻倍）
small = render(560, 150, TEXT)
# 大图不放大；字号按画布同比放大，保证两边字符占的比例接近
big = render(1600, 240, TEXT, size=40)

print("小图 %dx%d，大图 %dx%d" % (small.width(), small.height(),
                                big.width(), big.height()))

small_lines = OcrEngine.recognize_lines(small)
big_lines = OcrEngine.recognize_lines(big)

check("小图识别出文字", bool(small_lines), "→ %d 行" % len(small_lines))
check("大图识别出文字", bool(big_lines), "→ %d 行" % len(big_lines))

small_words = [w for line in small_lines for w in line.words]
big_words = [w for line in big_lines for w in line.words]

print("小图词:", [(w.text, round(w.cx), round(w.cy)) for w in small_words])
print("大图词:", [(w.text, round(w.cx), round(w.cy)) for w in big_words])

check("小图至少切出 3 个词", len(small_words) >= 3, "→ %d" % len(small_words))

# 关键断言：小图的词坐标必须落在原图范围内（没除掉放大倍数就会是 2 倍）
inside = all(0 <= w.cx <= small.width() and 0 <= w.cy <= small.height()
             for w in small_words)
check("小图词坐标落在原图范围内（未翻倍）", inside,
      "→ 范围 %dx%d" % (small.width(), small.height()))

boxes_inside = all(0 <= ln.box[2] <= small.width() + 1 and
                   0 <= ln.box[3] <= small.height() + 1 for ln in small_lines)
check("小图行框落在原图范围内（未翻倍）", boxes_inside)

# 相对位置一致性：同一个词在小图/大图里的归一化横向位置应接近。
# 词内位置是按「字符数均分整行」估算的，两边只要行的起止比例接近即可，
# 因此这里给一个较宽的容差 —— 它验证的是坐标没有被整体平移或缩放。
if small_words and big_words:
    def norm(words, width):
        return {w.text: w.cx / width for w in words}

    a, b = norm(small_words, small.width()), norm(big_words, big.width())
    common = [k for k in a if k in b]
    if common:
        worst = max(abs(a[k] - b[k]) for k in common)
        check("小图与大图的词相对位置一致", worst < 0.22,
              "最大偏差 %.3f（词: %s）" % (worst, ",".join(common)))
    else:
        check("小图与大图的词相对位置一致", False, "没有共同词")

print("\n%s  通过 %d / 失败 %d" % ("=" * 40, len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)