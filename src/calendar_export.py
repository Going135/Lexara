# -*- coding: utf-8 -*-
"""把学习日历画成一张 PNG（任务书 §7.4）。

刻意**不是截图**：这里用 QPainter 重新画一遍日历卡片，所以导出物里
绝不会带出 AI 配置、API Key、桌面壁纸或其它窗口 —— 只有日历格子、
日期范围、标题、累计打卡天数和三色图例。

画法与 `HeatGrid`（QML 里的点阵）共用 `activity` 的数据口径，
两边不会出现「屏幕上深绿、导出的图里浅绿」这种对不上的情况。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

import activity

#: 导出图尺寸：1440×520。
#: 53 列 × 7 行的点阵天生是「宽而矮」的，以前给 900 高会剩一大片空白；
#: 现在高度按内容算：标题区 150 + 点阵 ~161 + 月份标签 + 图例 + 内边距 ≈ 520。
WIDTH = 1440
HEIGHT = 520

BG = QColor("#FAFAF7")
CARD = QColor("#FFFFFF")
LINE = QColor("#E7E6E0")
INK = QColor("#1F1F1F")
TEXT = QColor("#2B2B2B")
MUTED = QColor("#747474")
EMPTY = QColor("#EEF0EE")
DIM = QColor("#F4F5F3")
SCAN = QColor("#B9DCC1")
STUDY = QColor("#4F765F")
FONT = "Microsoft YaHei UI"


def _font(size: int, bold: bool = False) -> QFont:
    font = QFont(FONT)
    font.setPixelSize(size)
    font.setBold(bold)
    return font


def render(book, days: int = activity.WINDOW_DAYS,
           today: str | None = None) -> QImage:
    """画一张日历图（不落盘）。调用方负责 `save()` 与失败提示。"""
    image = QImage(WIDTH, HEIGHT, QImage.Format_ARGB32_Premultiplied)
    image.fill(BG)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)

        card = QRectF(60, 48, WIDTH - 120, HEIGHT - 96)
        painter.setPen(QPen(LINE, 1))
        painter.setBrush(CARD)
        painter.drawRoundedRect(card, 22, 22)

        summary = activity.summary(book, days, today)
        cells = activity.calendar_cells(book, days, today)

        left = card.left() + 40
        painter.setPen(INK)
        painter.setFont(_font(30, True))
        painter.drawText(QRectF(left, card.top() + 34, 760, 40),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         "学习日志 · 已打卡 %d 天" % summary["checked"])

        painter.setPen(MUTED)
        painter.setFont(_font(16))
        painter.drawText(
            QRectF(left, card.top() + 82, 900, 26),
            Qt.AlignLeft | Qt.AlignVCenter,
            "统计区间 %s — %s　·　累计打开 %d 天　·　绿色 %d 天"
            % (summary["rangeStart"], summary["rangeEnd"],
               summary["openDays"], summary["greenDays"]))

        # ---- 点阵（与 HeatGrid 同一套 7 行布局）----
        # 2026-10-19：日历改成自然年后列数按真实格子数反推（周对齐的
        # 一整年可能是 53 列或 54 列），不再写死 53 —— 写死的话，多出来
        # 的那一列会画到卡片外面。
        rows = 7
        weeks = max(1, (len(cells) + rows - 1) // rows)
        gap = 5.0
        grid_left = left
        grid_top = card.top() + 150
        avail = card.width() - 80
        cell = (avail - (weeks - 1) * gap) / weeks
        cell = max(8.0, min(18.0, cell))
        for index, cell_data in enumerate(cells):
            col = index // rows
            level = cell_data.get("level", "none")
            # 两端补位格（去年 12 月末 / 明年 1 月初）与未来日期一样画成暗色
            if cell_data.get("future") or cell_data.get("outOfYear"):
                color = DIM
            elif level == "study":
                color = STUDY
            elif level == "scan":
                color = SCAN
            else:
                color = EMPTY
            x = grid_left + col * (cell + gap)
            y = grid_top + (index % rows) * (cell + gap)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, y, cell, cell), 3, 3)

        # ---- 月份标签 ----
        painter.setPen(MUTED)
        painter.setFont(_font(14))
        for index, cell_data in enumerate(cells):
            day = cell_data.get("date", "")
            if not day.endswith("-01") or cell_data.get("outOfYear"):
                continue
            col = index // rows
            x = grid_left + col * (cell + gap)
            painter.drawText(QRectF(x, grid_top + rows * (cell + gap) + 6, 60, 20),
                             Qt.AlignLeft, "%d月" % int(day[5:7]))

        # ---- 图例 ----
        legend_y = card.bottom() - 64
        x = left
        for color, label in ((SCAN, "浅绿：当天至少完成一次蜘蛛扫描"),
                             (STUDY, "深绿：背单词复习 / 主动问 AI"),
                             (EMPTY, "灰色：没有学习活动")):
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, legend_y, 16, 16), 4, 4)
            painter.setPen(TEXT)
            painter.setFont(_font(15))
            painter.drawText(QRectF(x + 24, legend_y - 2, 340, 22),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
            x += 380

        painter.setPen(MUTED)
        painter.setFont(_font(13))
        painter.drawText(
            QRectF(card.right() - 420, legend_y - 2, 380, 22),
            Qt.AlignRight | Qt.AlignVCenter,
            "词蛛 LEXARA　·　导出于 %s" % (today or activity.today_key()))
    finally:
        painter.end()
    return image


def export(book, path: str, days: int = activity.WINDOW_DAYS,
           today: str | None = None) -> dict:
    """画好并保存到 ``path``。返回 ``{"ok": bool, "message": str}``。

    保存失败不抛异常（UI 要能把原因显示给用户并允许重试），
    也**绝不**在失败时返回 ok=True。
    """
    try:
        image = render(book, days, today)
    except Exception as error:                  # noqa: BLE001
        return {"ok": False, "message": "生成日历图片失败：%s" % (error,)}
    if not path:
        return {"ok": False, "message": "没有选择保存路径。"}
    if not path.lower().endswith(".png"):
        path += ".png"
    try:
        saved = image.save(path, "PNG")
    except Exception as error:                  # noqa: BLE001
        return {"ok": False, "message": "写入文件失败：%s" % (error,)}
    if not saved:
        return {"ok": False,
                "message": "写入文件失败（可能没有权限或磁盘已满）。"}
    return {"ok": True, "path": path,
            "message": "日历图片已保存到 %s" % path}
