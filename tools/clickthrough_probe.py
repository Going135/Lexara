# -*- coding: utf-8 -*-
"""「点击穿透」方案对照实验。

在同一个位置放两层窗口：下层是**另一个进程**里的普通窗口，上层是我们的
透明无边框窗口。然后用 `WindowFromPoint`（Windows 路由鼠标消息时用的正是它）
查询那个点到底命中了谁，从而判定上层窗口有没有把点击吃掉。

三种方案对比：
    A. 什么都不做（逐像素 alpha 透明，但不设遮罩）
    B. Qt.WA_TransparentForMouseEvents
    C. nativeEvent 里对 WM_NCHITTEST 返回 HTTRANSPARENT

运行：  python tools/clickthrough_probe.py
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

# ---------------------------------------------------------------- 形状
AT = QRect(360, 320, 460, 360)          # 逻辑坐标
DISC_CX, DISC_CY, DISC_R = 250, 190, 96  # 窗口内画一个圆


def phys(pt, dpr):
    return wintypes.POINT(int(pt.x() * dpr), int(pt.y() * dpr))


user32 = ctypes.windll.user32
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND


class MSG(ctypes.Structure):
    _fields_ = [("hWnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG)]


HTTRANSPARENT = -1
WM_NCHITTEST = 0x0084


# ---------------------------------------------------------------- 下层窗口（另一个进程）
CHILD = r'''
import sys
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QColor, QPalette
app = QApplication(sys.argv)
w = QWidget()
w.setWindowTitle("UNDER")
w.setGeometry(QRect(%d, %d, %d, %d))
w.setAutoFillBackground(True)
p = w.palette(); p.setColor(QPalette.Window, QColor(255, 210, 60))
w.setPalette(p)
w.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
w.show()
print("under-ready", int(w.winId()), flush=True)
app.exec()
''' % (AT.x(), AT.y(), AT.width(), AT.height())

child = subprocess.Popen([sys.executable, "-c", CHILD],
                         stdout=subprocess.PIPE, text=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
line = child.stdout.readline().split()
UNDER_HWND = int(line[1])
print("下层窗口：", line, "→ hwnd", UNDER_HWND, flush=True)
time.sleep(1.2)

app = QApplication(sys.argv)
screen = QGuiApplication.primaryScreen()
dpr = screen.devicePixelRatio()


class Overlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(AT)
        self.hit_mode = "none"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 220, 200, 230))
        painter.drawEllipse(QPoint(DISC_CX, DISC_CY), DISC_R, DISC_R)
        # 一块 alpha=1 的极淡色块：验证「是不是 alpha 只要非零就吃点击」
        painter.setBrush(QColor(255, 255, 255, 1))
        painter.drawRect(20, 300, 120, 40)
        # 一块 alpha=8 的淡光晕
        painter.setBrush(QColor(120, 200, 255, 8))
        painter.drawRect(160, 300, 120, 40)
        painter.end()

    def is_on_disc(self, x, y):
        return (x - DISC_CX) ** 2 + (y - DISC_CY) ** 2 <= DISC_R ** 2

    def nativeEvent(self, event_type, message):
        if self.hit_mode == "nchittest" and event_type == b"windows_generic_MSG":
            msg = MSG.from_address(int(message))
            if msg.message == WM_NCHITTEST:
                sx = ctypes.c_short(msg.lParam & 0xFFFF).value
                sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                local = self.mapFromGlobal(QPoint(int(sx / dpr), int(sy / dpr)))
                if not self.is_on_disc(local.x(), local.y()):
                    return True, HTTRANSPARENT
        return False, 0


overlay = Overlay()
overlay.show()
app.processEvents()
time.sleep(0.6)
app.processEvents()

hwnd = int(overlay.winId())
print("上层窗口 hwnd =", hwnd, flush=True)

ON_DISC = QPoint(AT.x() + DISC_CX, AT.y() + DISC_CY)
OFF_DISC = QPoint(AT.x() + 40, AT.y() + 40)          # 窗口内、圆外的空白处
ALPHA1 = QPoint(AT.x() + 80, AT.y() + 320)           # alpha=1 的极淡色块
ALPHA8 = QPoint(AT.x() + 220, AT.y() + 320)          # alpha=8 的淡光晕
OUTSIDE = QPoint(AT.x() - 60, AT.y() - 60)


def who(pt):
    got = user32.WindowFromPoint(phys(pt, dpr))
    if got == hwnd:
        return "上层·吃点击"
    if got == UNDER_HWND:
        return "下层·穿透成功"
    return "别的窗口(%s)" % (got or "桌面")


def run(tag, setup):
    setup()
    app.processEvents()
    time.sleep(0.45)
    app.processEvents()
    print("  %-22s 圆(α230)=%-14s 空白(α0)=%-14s α1=%-14s α8=%-14s 窗外=%s" % (
        tag, who(ON_DISC), who(OFF_DISC), who(ALPHA1), who(ALPHA8),
        who(OUTSIDE)), flush=True)


print("\n=== 结果 ===")
run("A 什么都不做", lambda: setattr(overlay, "hit_mode", "none"))
run("B TransparentForMouse", lambda: (
    setattr(overlay, "hit_mode", "none"),
    overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)))
overlay.setAttribute(Qt.WA_TransparentForMouseEvents, False)
run("C HTTRANSPARENT", lambda: setattr(overlay, "hit_mode", "nchittest"))

child.terminate()
print("\n说明：「下层·穿透成功」= 鼠标能落到下层窗口；「上层·吃点击」= 被上层吃掉。")
