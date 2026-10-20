# -*- coding: utf-8 -*-
"""新布局离屏渲染：整张卡片 + 面板内的玻璃罐（住在六档按钮的右半边）。

出图到 dist/launcher_probe/layout_*.png。

用法：python tools/render_layout.py
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SRC, "src"))
sys.path.insert(0, SRC)

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

OUT = os.path.join(SRC, "dist", "launcher_probe")


def spin(seconds, fps=30):
    deadline = time.monotonic() + seconds
    step = 1.0 / fps
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(step)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)  # noqa: F841

    from launcher_window import LauncherWindow
    from lexicon import Lexicon
    from settings_store import Settings
    from wordbook import Wordbook, resource_path

    settings = Settings()
    settings.load()
    lexicon = Lexicon(resource_path("assets", "ecdict.sqlite"),
                      resource_path("assets", "exam-tags.sqlite"),
                      resource_path("assets", "industry.sqlite"))
    book = Wordbook()

    win = LauncherWindow(lexicon, book, settings, log=print)
    win.resize(1200, 720)
    win.show()
    spin(0.5)

    jar = win.jar
    plate = jar.plate_rect()
    hold = jar.rect()
    card = win.right.rect()
    in_panel = jar.mapTo(win.panel, QPoint(0, 0))
    panel_w = win.panel.width()
    print("[layout] 窗口 %dx%d | 卡片 %dx%d"
          % (win.width(), win.height(), card.width(), card.height()))
    print("[layout] 卡片吃满可用区? %s"
          % (abs(card.width() - (win.width() - 32)) <= 2
             and abs(card.height() - (win.height() - 32)) <= 2))
    print("[layout] 罐位 %dx%d（瓶身 %.0fx%.0f，托盘 %.0fx%.0f）"
          % (hold.width(), hold.height(), jar.jar_rect().width(),
             jar.jar_rect().height(), plate.width(), plate.height()))
    print("[layout] 罐子在面板内 x %d~%d / 面板宽 %d（右半边起点 %d）"
          % (in_panel.x(), in_panel.x() + hold.width(), panel_w, panel_w // 2))
    print("[layout] 罐子落在右半边? %s | 不越出面板? %s"
          % (in_panel.x() >= panel_w * 0.45, in_panel.x() + hold.width() <= panel_w))

    win.grab().save(os.path.join(OUT, "layout_idle.png"))
    win.jar.grab().save(os.path.join(OUT, "layout_jar.png"))
    win.right.grab().save(os.path.join(OUT, "layout_right.png"))
    print("[layout] 图已写出 -> %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
