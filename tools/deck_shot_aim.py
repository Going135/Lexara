# -*- coding: utf-8 -*-
"""为 deck 拍一张「真实运行」的踩词截图。

和 `tools/aim_e2e.py` 的区别：那个跑 offscreen 做断言，这个**开真窗口**拍图。
场景 = 一个阅读窗格（真 QWidget，真排版）+ 真 PetWindow + 真 AimOverlay，
最后抓整屏再裁到窗格里 —— 所以图上的每一个像素都是这台机器实际渲染出来的，
腿的位置也是 `Spider` 真解算出来的，不是画上去的示意。

运行：  python tools/deck_shot_aim.py
输出：  .workbuddy/shots/deck/aim_live.png
"""
from __future__ import annotations

import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QPoint, QRect, QRectF, Qt                  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication,  # noqa: E402
                           QImage, QPainter, QPen)
from PySide6.QtWidgets import QApplication, QWidget                   # noqa: E402

import pet_window as PW                                              # noqa: E402
from pet_window import OcrWorker, PetWindow                          # noqa: E402

OUT = os.path.join(BASE, ".workbuddy", "shots", "deck")
os.makedirs(OUT, exist_ok=True)

# ------------------------------------------------------------------ 假时钟
class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def strftime(self, fmt):
        import time as real
        return real.strftime(fmt)


clock = Clock()
PW.time = clock


class StubOcrWorker(OcrWorker):
    """只把「OCR 认出了什么」换掉，坐标换算仍走生产代码 `OcrWorker.locate`。"""

    payload = None

    def run(self) -> None:
        words, meta = self.payload or ([], {"positions": {}, "lines": []})
        self.locate(words, meta.get("positions", {}))
        self.done.emit(words, meta, "")


class _FakeBook:
    def __init__(self):
        self._s = set()

    def has(self, w):
        return w in self._s

    def add(self, item):
        self._s.add(item["lemma"])
        return True

    def remove(self, w):
        self._s.discard(w)

    def __len__(self):
        return len(self._s)

    def stats(self):
        return {"total": 0, "due": 0, "mastered": 0}

    def items(self):
        return []

    def review_queue(self):
        return []

    def record_learning(self, words) -> int:
        return 0


# ------------------------------------------------------------------ 阅读窗格
PARAS = [
    ("What finally worked was a fixed hour and a short list: read one "
     "section, stop at the first word you cannot define, and let the rest "
     "wait. The lesson was never about speed. It was about the cost of "
     "switching context every time a question appeared, and about how "
     "quickly a page stops being yours once you leave it."),
    ("A reader meets the same pattern on every screen. The meaning is "
     "usually within reach, but the act of leaving the page to look it up "
     "breaks the thread you were holding: the word is learned, the passage "
     "is lost, and the next paragraph has to be read twice."),
    ("So the habit matters more than the tool. You abandon the lookup tab, "
     "accept the absence of a perfect definition, and keep the committee of "
     "small routines that allocate an hour, hold a persistent schedule and "
     "measure the threshold of what you can absorb. Nothing else can supervise "
     "the work, and without it the gain stays insufficient."),
]

TARGETS = ["insufficient", "abandon", "supervise", "absence",
           "committee", "persistent", "allocate", "threshold"]

CREAM = QColor(253, 252, 249)
INK = QColor(24, 28, 34)
MUTED = QColor(120, 128, 138)
TEAL = QColor(16, 199, 197)


class ReadingPane(QWidget):
    """真排版的阅读器：逐词测量，顺手把目标词的矩形记下来。"""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.boxes = {}          # word -> QRect (窗口逻辑坐标)
        self._layout()

    def _layout(self):
        fm = QFontMetricsF(QFont("Georgia", 16))
        self.line_h = int(fm.height() * 1.74)
        self.pad_x = 72
        width = 1060

        # 先排版，拿到每行每个词的位置
        self.lines = []          # [(text, x, y)]
        y = 150
        for para in PARAS:
            x = self.pad_x
            for word in para.split():
                w = fm.horizontalAdvance(word + " ")
                if x + w > width - self.pad_x:
                    x = self.pad_x
                    y += self.line_h
                self.lines.append((word, x, y))
                key = word.strip(".,;:").lower()
                if key in TARGETS:
                    tw = fm.horizontalAdvance(word.strip(".,;:"))
                    self.boxes[key] = QRect(int(x), int(y + fm.ascent() * 0.16),
                                            int(tw), int(fm.height() * 0.92))
                x += w
            y += self.line_h

        self.resize(width, y + 250)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), CREAM)

        # 顶部：一条极简的阅读器标题栏
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(241, 239, 233))
        p.drawRoundedRect(QRectF(26, 30, self.width() - 52, 62), 14, 14)
        p.setPen(QColor(90, 98, 108))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(QRectF(48, 30, 520, 62), Qt.AlignVCenter | Qt.AlignLeft,
                   "Field Notes  —  chapter 04 / on attention and recall")
        for i, c in enumerate([QColor(255, 106, 118), QColor(255, 196, 92),
                               QColor(74, 205, 138)]):
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPoint(self.width() - 82 + i * 20, 61), 5, 5)

        # 正文
        p.setFont(QFont("Georgia", 16))
        p.setPen(INK)
        for text, x, y in self.lines:
            p.drawText(QPoint(int(x), int(y + QFontMetricsF(p.font()).ascent())), text)

        # 页脚
        p.setPen(QColor(150, 142, 128))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(self.pad_x, self.height() - 92, 700, 30),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   "Field Notes · issue 04 · the cost of leaving the page")
        p.end()


# ------------------------------------------------------------------ 主流程
app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

pane = ReadingPane()
screen = QGuiApplication.primaryScreen()
avail = screen.availableGeometry()
pane.move(avail.x() + int(avail.width() * 0.5) - pane.width() // 2,
          avail.y() + int(avail.height() * 0.10))
pane.show()
pane.lower()

RECT = QRect(pane.geometry())

pet = PetWindow(None, _FakeBook(), sprite_w=300.0)
pet._timer.stop()
pet.set_skin("original", persist=False)   # 深色原皮在浅底正文上才看得清
pet.start_capture = lambda *a, **k: None
pet.bubble.hide_now()
# 停在「目标词簇的正下方」—— 生产里也是走到词与词之间的最优点再伸腿
_cluster = QRect()
for _b in pane.boxes.values():
    _cluster = _b if _cluster.isNull() else _cluster.united(_b)
pet.move(RECT.x() + int(_cluster.center().x()) - pet.width() // 2,
         RECT.y() + RECT.height() - pet.height() - 34)
pet.show()


def pump(frames: int, dt: float = 1 / 60.0) -> None:
    for _ in range(frames):
        pet._last = clock.t
        clock.t += dt
        pet._tick()
        app.processEvents()


def wait_until(pred, timeout=8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.004)
    return pred()


words, positions = [], {}
for i, name in enumerate(TARGETS):
    words.append({"lemma": name, "surface": name, "pos": "n.", "cn": "释义",
                  "tags": ["cet6"], "difficulty": 3, "off_syllabus": False})
    box = pane.boxes[name]
    positions[name] = (box.center().x(), box.center().y())

pet._capture_rect = QRect(RECT)
pet._capture_dpr = 1.0
worker = StubOcrWorker(None, None, "cet6", 8, True, parent=pet)
worker.capture_rect = QRect(RECT)
worker.dpr = 1.0
worker.payload = (words, {"positions": dict(positions), "lines": []})
pet._workers.append(worker)
worker.done.connect(pet._on_ocr_done)
worker.finished.connect(lambda item=worker: pet._reap(item))
worker.start()

wait_until(lambda: worker not in pet._workers, 8.0)

guard = 0
while pet._travel is not None and guard < 900:
    pump(1)
    guard += 1
app.processEvents()

overlay = pet._dialogs.get("aim")
if overlay is None:
    raise SystemExit("瞄准层没起来")

from shiboken6 import isValid
overlay._timer.stop()
# 让词框先亮起来，再让腿按错峰顺序伸出去
for frame in range(34):
    pump(1)
    if not isValid(overlay):
        raise SystemExit("瞄准层被销毁")
    overlay._tick()

# 识词结果卡会自动弹出来，会挡住半页；拍图前先收掉它和气泡
for key in ("words", "book", "sense"):
    dlg = pet._dialogs.pop(key, None)
    if dlg is not None:
        try:
            dlg.close()
        except Exception:
            pass
pet.bubble.hide_now()
# 结果卡的淡出走**真挂钟**（QPropertyAnimation），假时钟推不动，只能真等
_deadline = time.monotonic() + 0.9
while time.monotonic() < _deadline:
    app.processEvents()
    time.sleep(0.01)
pane.repaint()                # 结果卡关掉后那块区域要重画，否则抓到的是残影
pet.repaint()
app.processEvents()

print("legs 踩词 %d 组 / %d 词" % (len(overlay._pairs), len(overlay.words)))

# grabWindow 的 w/h 是逻辑像素，返回的却是设备像素：整屏抓再按 dpr 裁，
# 免得 150% 缩放下只拍到窗格左上角那一块。
full = screen.grabWindow(0)
dpr = full.width() / screen.geometry().width()
crop = QRect(int(RECT.x() * dpr), int(RECT.y() * dpr),
             int(RECT.width() * dpr), int(RECT.height() * dpr))
img = full.copy(crop)
img.setDevicePixelRatio(1.0)
path = os.path.join(OUT, "aim_live.png")
img.save(path)
print("→ %s  %dx%d (dpr %.2f)" % (path, img.width(), img.height(), dpr))
sys.stdout.flush()
os._exit(0)
