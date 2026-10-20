# -*- coding: utf-8 -*-
"""OCR 跨线程对照实验：主线程 / 原图直接传线程 / 拷贝后传线程。

用来定论「QImage 隐式共享跨线程」到底是不是识别不出来的根因。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QRect, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from ocr_engine import OcrEngine

app = QApplication(sys.argv)

TEXT = ["The government decided to abandon the project because of",
        "insufficient funds and an absence of public support."]


def make_image():
    image = QImage(1180, 300, QImage.Format_RGB888)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    painter.setPen(QColor(18, 20, 30))
    painter.setFont(QFont("Arial", 21))
    for index, line in enumerate(TEXT):
        painter.drawText(QRect(34, 28 + index * 66, 1120, 60),
                         int(Qt.AlignLeft | Qt.AlignVCenter), line)
    painter.end()
    return image


class Worker(QThread):
    done = Signal(list)

    def __init__(self, image):
        super().__init__()
        self.image = image

    def run(self):
        self.done.emit(OcrEngine.recognize_lines(self.image))


print("[1] 主线程直接识别 ...", flush=True)
lines = OcrEngine.recognize_lines(make_image())
print("    → %d 行 %s" % (len(lines), [ln.text[:26] for ln in lines]), flush=True)

source = make_image()
results = {}


def collect(tag):
    def _slot(lines):
        results[tag] = lines
        print("    → %d 行 %s" % (len(lines), [ln.text[:26] for ln in lines]), flush=True)
    return _slot


base = len(OcrEngine.recognize_lines(make_image()))

for tag, image in (("同一 QImage 直接传线程", source), ("QImage.copy() 后传线程", source.copy())):
    print("  %s ..." % tag, flush=True)
    worker = Worker(image)
    worker.done.connect(collect(tag))
    worker.start()
    while tag not in results:
        app.processEvents()
    worker.wait()

print("\n结论（主线程 %d 行）：" % base)
for tag, lines in results.items():
    print("  %-22s %d 行  %s" % (tag, len(lines),
                                  "✓ 与主线程一致" if len(lines) == base else "✗ 结果不一致"))