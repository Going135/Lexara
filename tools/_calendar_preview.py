# -*- coding: utf-8 -*-
"""日历改版预览：自然年（1-12 月从左到右）+ 去掉右下角文字说明。

上：主页卡片里那块（HeatGrid 真实 paint，900×208）
下：导出图片（calendar_export.render）

用的是同一份假数据（今年 2 月起隔三差五有记录），所以两张图的
月份位置和绿格子必须对得上。

运行：  python tools/_calendar_preview.py
输出：  dist/shape/calendar_year.png
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QRectF, Qt                                    # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter               # noqa: E402
from PySide6.QtWidgets import QApplication                              # noqa: E402

import activity                                                         # noqa: E402
import calendar_export                                                  # noqa: E402
from launcher_qml import HeatGrid                                       # noqa: E402

OUT = os.path.join(BASE, "dist", "shape")
os.makedirs(OUT, exist_ok=True)


class FakeBook:
    def __init__(self, scans=(), reviews=(), asks=(), opens=()):
        self.open_dates = list(opens)
        self.study_events = [{"date": d} for d in scans]
        self.review_events = [{"date": d} for d in reviews]
        self.ai_events = [{"date": d} for d in asks]
        self.achievements = {}

    def save(self):
        pass


TODAY = date.today()
YEAR = TODAY.year

# 今年 2 月起：每 3 天一次扫描（浅绿），每 7 天一次复习（深绿）——
# 这样 1 月是干净的灰、后面逐渐有颜色，月份边界一眼能看出来。
scans, reviews, opens = [], [], []
day = date(YEAR, 2, 1)
step = 0
while day <= TODAY:
    opens.append(day.strftime("%Y-%m-%d"))
    if step % 3 == 0:
        scans.append(day.strftime("%Y-%m-%d"))
    if step % 7 == 1:
        reviews.append(day.strftime("%Y-%m-%d"))
    day += timedelta(days=1)
    step += 1

book = FakeBook(scans=scans, reviews=reviews, opens=opens)

app = QApplication(sys.argv)

CW, CH = 980, 208
grid = HeatGrid()
grid.setWidth(CW)
grid.setHeight(CH)
grid._book = book                      # 绕开 Slot(QObject)：这里只读字段

card = QImage(CW, CH, QImage.Format_ARGB32_Premultiplied)
card.fill(0)
p = QPainter(card)
p.setRenderHint(QPainter.Antialiasing, True)
grid.paint(p)
p.end()

export = calendar_export.render(book)

W = max(CW, export.width()) + 40
H = 40 + CH + 24 + export.height() + 30
out = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
out.fill(QColor(245, 246, 247))
q = QPainter(out)
q.setRenderHint(QPainter.SmoothPixmapTransform, True)

q.setPen(QColor(30, 34, 40))
q.setFont(QFont("Segoe UI", 12, QFont.Bold))
q.drawText(QRectF(20, 10, W - 40, 24), Qt.AlignLeft,
           "主页卡片 · %d 年 1-12 月（自然年，周对齐，右下角文字说明已删除）" % YEAR)
q.drawImage(QRectF(20, 40, CW, CH), card, QRectF(0, 0, CW, CH))

q.drawText(QRectF(20, 40 + CH + 4, W - 40, 24), Qt.AlignLeft,
           "导出图片（数据跟随自然年）")
q.drawImage(QRectF(20, 40 + CH + 24, export.width(), export.height()), export,
            QRectF(0, 0, export.width(), export.height()))
q.end()

path = os.path.join(OUT, "calendar_year.png")
out.save(path)
info = activity.summary(book, today=TODAY.isoformat())
print("saved", path, "%dx%d" % (out.width(), out.height()))
print("区间 %s ~ %s · 绿 %d 天 · 打开 %d 天 · 全绿=%s"
      % (info["rangeStart"], info["rangeEnd"], info["greenDays"],
         info["openDays"], info["allGreen"]))
print("格子 %d · 列 %d" % (len(activity.calendar_cells(book)),
                          len(activity.calendar_cells(book)) // 7))
