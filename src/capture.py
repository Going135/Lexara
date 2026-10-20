# -*- coding: utf-8 -*-
"""全屏框选截图。

流程：先把整个虚拟桌面**冻结**成一张图，再在冻结图上框选。
这样截图里不会拍进蜘蛛自己，遮罩也不会被后续动画干扰。

多屏与缩放：截图是**物理像素**，鼠标坐标是**逻辑像素（DIP）**，
两者在 125%/150% 缩放下差着一个 devicePixelRatio，必须换算，
否则框选区域会整体偏移（这个坑在 4K 屏上非常明显）。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

#: LEXARA：框选层采用克制的深色遮罩 + 品牌蓝选区，保证识别清晰。
ACCENT = QColor(47, 107, 255)
ACCENT_DIM = QColor(47, 107, 255, 62)
SHADE = QColor(21, 21, 21, 132)
TIP_BG = QColor(255, 255, 255, 255)
TIP_BORDER = QColor(228, 228, 223, 255)
TIP_FG = QColor(21, 21, 21)
TIP_SUB = QColor(116, 116, 116)

#: 小于这个尺寸的框选视为误触
MIN_SELECT = 12


def grab_virtual_desktop():
    """抓取整个虚拟桌面（多屏拼接）。

    返回 ``(pixmap, 逻辑坐标区域, 设备像素比)``。
    """
    screens = QGuiApplication.screens()
    if not screens:
        raise RuntimeError("没有可用的屏幕")

    geo = QRect()
    for s in screens:
        geo = geo.united(s.geometry())
    dpr = max([s.devicePixelRatio() for s in screens] or [1.0])

    pm = QPixmap(int(geo.width() * dpr), int(geo.height() * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor(237, 241, 246))

    painter = QPainter(pm)
    for s in screens:
        shot = s.grabWindow(0)
        g = s.geometry()
        painter.drawPixmap(
            QRectF(g.x() - geo.x(), g.y() - geo.y(), g.width(), g.height()),
            shot, QRectF(shot.rect()))
    painter.end()
    return pm, geo, dpr


class CaptureOverlay(QWidget):
    """框选遮罩窗口。"""

    selected = Signal(QRect)     # 逻辑坐标（相对虚拟桌面左上角）
    cancelled = Signal()

    def __init__(self, frozen: QPixmap, geo: QRect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self._pm = frozen
        self._geo = geo
        self.setGeometry(geo)
        self._origin = None
        self._cur = None
        self._drag = False
        self._finished = False
        self._hover = None

    # ------------------------------------------------ 状态
    def _dpr(self) -> float:
        return self._pm.devicePixelRatio() or 1.0

    def _rect(self):
        if self._origin is None or self._cur is None:
            return None
        return QRect(self._origin, self._cur).normalized()

    def _finish(self, ok: bool, rect: QRect = None) -> None:
        """保证 selected / cancelled 只发一次，且窗口一定关闭。"""
        if self._finished:
            return
        self._finished = True
        if ok and rect is not None:
            self.selected.emit(rect)
        else:
            self.cancelled.emit()
        try:
            self.close()
        except Exception:                      # noqa: BLE001
            pass

    def closeEvent(self, event):
        if not self._finished:
            self._finished = True
            self.cancelled.emit()
        super().closeEvent(event)

    # ------------------------------------------------ 绘制
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.drawPixmap(0, 0, self._pm)
        painter.fillRect(self.rect(), SHADE)

        rect = self._rect()
        dpr = self._dpr()

        if rect and rect.width() > 2 and rect.height() > 2:
            # 选区内还原亮度
            painter.drawPixmap(
                QRectF(rect), self._pm,
                QRectF(rect.x() * dpr, rect.y() * dpr,
                       rect.width() * dpr, rect.height() * dpr))

            # 发光外框
            for width, alpha in ((6.0, 40), (3.0, 90)):
                pen = QPen(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), alpha))
                pen.setWidthF(width)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect)
            painter.setPen(QPen(ACCENT, 1.6))
            painter.drawRect(rect)

            # 四角标记
            painter.setPen(QPen(ACCENT, 3.0))
            arm = min(18, rect.width() // 3, rect.height() // 3)
            for cx, cy, dx, dy in (
                (rect.left(), rect.top(), 1, 1),
                (rect.right(), rect.top(), -1, 1),
                (rect.left(), rect.bottom(), 1, -1),
                (rect.right(), rect.bottom(), -1, -1),
            ):
                painter.drawLine(cx, cy, cx + arm * dx, cy)
                painter.drawLine(cx, cy, cx, cy + arm * dy)

            # 尺寸标签
            info = f"{int(rect.width())} × {int(rect.height())}"
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(info) + 20
            bx = min(max(4, rect.left()), self.width() - tw - 4)
            by = rect.bottom() + 8
            if by > self.height() - 30:
                by = rect.top() - 30
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 255))
            painter.drawRoundedRect(QRectF(bx, by, tw, 24), 8, 8)
            painter.setPen(TIP_FG)
            painter.drawText(QRect(bx, by, tw, 24), Qt.AlignCenter, info)
        elif self._hover and not self._drag:
            # 未开始拖动时给一个十字准线，方便对齐
            painter.setPen(QPen(ACCENT_DIM, 1.0))
            painter.drawLine(0, self._hover.y(), self.width(), self._hover.y())
            painter.drawLine(self._hover.x(), 0, self._hover.x(), self.height())

        self._paint_tip(painter)
        painter.end()

    def _paint_tip(self, painter: QPainter):
        tip = "拖动鼠标框选要识别的英文　·　Esc / 右键取消"
        painter.setFont(QFont("Microsoft YaHei UI", 11))
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(tip) + 44
        th = 44
        tx = (self.width() - tw) // 2
        ty = 30
        path = QPainterPath()
        path.addRoundedRect(QRectF(tx, ty, tw, th), 12, 12)
        painter.setPen(QPen(TIP_BORDER, 1))
        painter.setBrush(TIP_BG)
        painter.drawPath(path)
        painter.setPen(TIP_FG)
        painter.drawText(QRect(tx, ty, tw, th), Qt.AlignCenter, tip)

        sub = "蛛蛛会用八条腿踩住挑出来的单词"
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        fm2 = painter.fontMetrics()
        sw = fm2.horizontalAdvance(sub) + 32
        sx = (self.width() - sw) // 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(248, 248, 245, 255))
        painter.drawRoundedRect(QRectF(sx, ty + th + 8, sw, 26), 8, 8)
        painter.setPen(TIP_SUB)
        painter.drawText(QRect(sx, ty + th + 8, sw, 26), Qt.AlignCenter, sub)

    # ------------------------------------------------ 交互
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._finish(False)
            return
        if event.button() != Qt.LeftButton:
            return
        self._origin = event.position().toPoint()
        self._cur = self._origin
        self._drag = True
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._drag:
            self._cur = pos
        self._hover = pos
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._drag = False
        rect = self._rect()
        if rect and rect.width() >= MIN_SELECT and rect.height() >= MIN_SELECT:
            self._finish(True, rect)
        else:
            self._finish(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish(False)
