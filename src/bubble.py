# -*- coding: utf-8 -*-
"""对话气泡：无边框透明小窗，浮在蜘蛛头顶，以实体白卡 + 几何焦点线呈现并自动淡出。

要点：
  · 用 WA_ShowWithoutActivating + Qt.Tool，保证弹出气泡**不会抢走焦点**
    （否则用户正在框选/输入时会被打断）；
  · 窗口整体透明，气泡本体自己画，因此圆角与阴影都不依赖系统主题。
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

BG = QColor(255, 255, 255, 255)
BORDER = QColor(210, 210, 205, 255)
TEXT = QColor(21, 21, 21)
ACCENT = QColor(47, 107, 255)
TAIL_H = 8.0
PAD_X, PAD_Y = 14.0, 10.0
RADIUS = 10.0
MAX_WIDTH = 300.0


class BubbleWindow(QWidget):
    """一个会自己消失的气泡。同一时刻只显示最新的一条。"""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool | Qt.WindowTransparentForInput
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._text = ""
        self._lines = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_now)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(240)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._finish_fade)
        #: 这次淡变是「淡出」还是「淡入」。以前 `_finish_fade` 靠
        #: `windowOpacity() <= 0.01` 判断要不要 hide —— 实测 20 次部署/收回里
        #: 会有 1~2 个气泡停在 0.011 这种值上，永远不 hide，于是桌面上留下
        #: 一个 212×46 的透明小窗（`tools/deploy_cycle_probe.py` 抓到的残留）。
        #: 用显式方向标记，动画一结束就隐藏，不跟浮点比较较劲。
        self._fade_out = False

    # ------------------------------------------------ 显示
    def show_message(self, text: str, anchor, screen, duration: int = 2600) -> None:
        """在 ``anchor``（蜘蛛身体矩形）上方弹出气泡。"""
        if not text:
            return
        self._text = text
        fm = QFontMetrics(QFont("Microsoft YaHei UI", 10))
        lines = self._wrap(text, fm)
        self._lines = lines

        text_w = max(fm.horizontalAdvance(ln) for ln in lines)
        text_h = fm.height() * len(lines)
        w = int(text_w + PAD_X * 2) + 2
        h = int(text_h + PAD_Y * 2 + TAIL_H) + 2
        self.resize(max(72, w), max(40, h))

        self._place(anchor, screen)
        self._fade.stop()
        self._fade_out = False
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(max(900, duration))

    def _wrap(self, text: str, fm: QFontMetrics) -> list:
        """按像素宽度折行（中英混排也按同样口径量）。"""
        lines = []
        for paragraph in text.split("\n"):
            current = ""
            for ch in paragraph:
                probe = current + ch
                if fm.horizontalAdvance(probe) > MAX_WIDTH - PAD_X * 2:
                    if current:
                        lines.append(current)
                    current = ch
                else:
                    current = probe
            lines.append(current)
        return lines or [""]

    def _place(self, anchor, screen) -> None:
        """头在 anchor 上方居中；顶到屏幕边就翻到下方。"""
        cx = int(anchor.center().x() - self.width() / 2)
        top = int(anchor.top() - self.height() + 6)
        if top < screen.top() + 4:
            top = int(anchor.bottom() - 6)
        cx = max(screen.left() + 4, min(cx, screen.right() - self.width() - 4))
        self.move(cx, top)

    def hide_now(self) -> None:
        self._timer.stop()
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade_out = True
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def dispose(self) -> None:
        """销毁前收尾：不淡出、直接隐藏（收回/退出时用，不留残留窗口）。"""
        self._timer.stop()
        self._fade.stop()
        self._fade_out = False
        self.hide()

    def _finish_fade(self) -> None:
        if self._fade_out:
            self._fade_out = False
            self.hide()

    # ------------------------------------------------ 绘制
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(1.0, 1.0, self.width() - 2, self.height() - TAIL_H - 2)

        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        # A small geometric tail keeps the companion relationship without making
        # the bubble look like a cartoon speech balloon.
        tail = QPainterPath()
        cx = rect.center().x()
        tail.moveTo(cx - 7, rect.bottom() - 1)
        tail.lineTo(cx, rect.bottom() + TAIL_H - 1)
        tail.lineTo(cx + 7, rect.bottom() - 1)
        tail.closeSubpath()
        path = path.united(tail)

        painter.setPen(QPen(BORDER, 1))
        painter.setBrush(BG)
        painter.drawPath(path)

        # One restrained accent rule, derived from the LEXARA wordmark.
        painter.setPen(QPen(ACCENT, 1.5))
        painter.drawLine(QPointF(rect.left() + 10, rect.top() + 1.5),
                         QPointF(min(rect.left() + 34, rect.right() - 10),
                                  rect.top() + 1.5))

        painter.setPen(TEXT)
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        fm = painter.fontMetrics()
        y = rect.top() + PAD_Y + fm.ascent()
        for line in self._lines:
            painter.drawText(QPointF(PAD_X + 1, y), line)
            y += fm.height()
        painter.end()
