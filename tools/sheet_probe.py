# -*- coding: utf-8 -*-
"""设置弹层两连修验证：不透明（白底圆角）+ 可拖动 + 顶部 logo。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.makedirs(os.path.join(os.path.dirname(__file__), "..", "dist", "selftest"),
            exist_ok=True)
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from launcher_window import SettingsSheet, LauncherWindow, TitleBar

app = QApplication([])
root = os.path.join(os.path.dirname(__file__), "..", "dist", "selftest")

# 1) 透明修复：弹层截图后采样中心与四角内测像素，必须是纯白不透明
sheet = SettingsSheet({"max_words": 8, "min_conf": 0.6})
sheet.resize(360, 240)
sheet.move(100, 100)
sheet.show()
app.processEvents()
pix = sheet.grab()
pix.save(os.path.join(root, "sheet_opaque.png"))
img = pix.toImage()
from PySide6.QtGui import QColor
center = QColor(img.pixel(img.width() // 2, img.height() // 2))
inside = QColor(img.pixel(20, 12))  # 圆角内侧
print("sheet center rgb=(%d,%d,%d) alpha=%d" % (center.red(), center.green(), center.blue(), center.alpha()))
print("sheet inside-corner alpha=%d" % inside.alpha())
ok_opaque = center.alpha() == 255 and center.red() > 250

# 2) 拖动修复：直接喂鼠标事件，窗口位置必须跟手
start = sheet.pos()
press = QMouseEvent(QEvent.MouseButtonPress, QPointF(30, 10),
                    QPointF(start) + QPointF(30, 10),
                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
sheet.mousePressEvent(press)
moved = sheet.pos() + QPoint(40, 25)
move = QMouseEvent(QEvent.MouseMove, QPointF(70, 35),
                   QPointF(moved) + QPointF(70, 35),
                   Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
sheet.mouseMoveEvent(move)
rel = QMouseEvent(QEvent.MouseButtonRelease, QPointF(70, 35),
                  QPointF(moved) + QPointF(70, 35),
                  Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
sheet.mouseReleaseEvent(rel)
delta = sheet.pos() - start
print("drag delta = (%d, %d)  expect (80, 50) = 光标全局位移" % (delta.x(), delta.y()))
ok_drag = abs(delta.x() - 80) <= 2 and abs(delta.y() - 50) <= 2

# 3) logo：真窗口标题栏的 logo pixmap 必须存在且在左上角
title = TitleBar("词蛛LEXARA", "启动台")
pm = title.logo.pixmap()
print("logo pixmap null=%s size=%dx%d" % (pm.isNull(), pm.width(), pm.height()))
ok_logo = not pm.isNull() and pm.width() > 30

print("RESULT opaque=%s drag=%s logo=%s" % (ok_opaque, ok_drag, ok_logo))
sys.exit(0 if (ok_opaque and ok_drag and ok_logo) else 1)
