# -*- coding: utf-8 -*-
"""覆盖面板「可拖动 / 可最小化」实测探针。

为什么非要用真鼠标事件：把 `anchors.centerIn` 换成自由的 x/y 之后，最典型的
两种回归是 **点着拖不动**（锚定和 `drag.target` 打架）与 **松手跑到窗口外面
抓不回来**（没有夹取）。这两种都只有真发一遍 press/move/release 才看得出来，
看截图是看不出的。

用法：  python tools/panel_float_probe.py
退出码：0 全过，1 有失败。
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import (QEventLoop, QObject, QPoint, QPointF,  # noqa: E402
                            QTimer, Qt)
from PySide6.QtTest import QTest                                 # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

PASS, FAIL = [], []
#: 引擎必须活着，否则它被 GC 掉时会把 QQuickWindow 一起带走
#: （症状：`Internal C++ object (QQuickWindow) already deleted`）。
_KEEP = []


def wait(ms):
    """切一拍事件循环。

    ★ 这里**不能用 `QTest.qWait`**：它在这个工程里会卡死（实测 8s 不返回，
      主线程停在 C++ 里，连 faulthandler 都只有 `<no Python frame>`）。
      而 `QTest.qWaitForWindowExposed` 更糟 —— 无边框透明窗永远等不到 exposed。
      自己起一个 QEventLoop + QTimer 就完全正常。
    """
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("%s %-34s %s" % ("[ok]  " if condition else "[FAIL]", name, detail))


def headless_limit(app):
    """允许在无显示环境里退化成 offscreen（CI 里跑得起来就行）。"""
    if app.platformName() not in ("windows", "cocoa", "xcb"):
        print("platform=%s（非桌面平台，拖动断言照常执行）" % app.platformName())


def build():
    import ui_theme
    from launcher_qml import LauncherBridge, build_engine
    from lexicon import Lexicon
    from settings_store import Settings
    from wordbook import Wordbook, resource_path

    lexicon = Lexicon(resource_path("assets", "ecdict.sqlite"),
                      resource_path("assets", "exam-tags.sqlite"),
                      resource_path("assets", "industry.sqlite"))
    book = Wordbook()
    settings = Settings(log=print)
    settings.load()
    bridge = LauncherBridge(lexicon, book, settings, log=print)
    theme = ui_theme.ThemeStore(watch=False)
    ui_theme.set_active(theme)
    warnings: list = []
    engine = build_engine(bridge, theme,
                          on_warnings=lambda items: [warnings.append(w.toString())
                                                     for w in items])
    _KEEP.extend([engine, bridge, theme, lexicon, book, settings])
    window = engine.rootObjects()[0]
    window.resize(1236, 816)
    window.show()
    # ★ 不要用 `QTest.qWaitForWindowExposed`：这块无边框透明窗口在 Windows 上
    #   等不到 exposed 事件，会一直卡在它自己的循环里（实测 30s+ 不返回，
    #   连超时参数都不生效）。只要切一拍事件循环，让 QML 把初始绑定都求完就够。
    wait(900)
    return window, warnings


def buttons_of(item):
    """面板里所有 AbstractButton，按屏幕横坐标排好（最右：关闭；次右：收起）。"""
    from PySide6.QtQuick import QQuickItem

    found = []
    for child in item.findChildren(QQuickItem):
        try:
            if not child.inherits("QQuickAbstractButton"):
                continue
        except RuntimeError:                       # 已析构的壳，跳过
            continue
        if child.isVisible():
            center = child.mapToScene(QPointF(child.width() / 2, child.height() / 2))
            found.append((center.x(), center.y(), child))
    return sorted(found, key=lambda row: row[0])


def drag(window, start, offset, steps=6):
    """在 start 按下，分 steps 段移动到 start+offset，松手。"""
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    for i in range(1, steps + 1):
        point = QPoint(start.x() + int(offset[0] * i / steps),
                       start.y() + int(offset[1] * i / steps))
        QTest.mouseMove(window, point)
        wait(16)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier,
                       QPoint(start.x() + offset[0], start.y() + offset[1]))
    wait(80)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    headless_limit(app)
    window, warnings = build()
    if not window:
        print("[FAIL] 窗口没起来")
        return 1

    def settle(ms=260):
        for _ in range(6):
            app.processEvents()
            wait(max(1, ms // 6))

    window.setProperty("overlay", "skins")
    settle()
    panel = window.findChild(QObject, "skinsPanel")
    check("panel.exists", panel is not None)
    if panel is None:
        return 1

    # ---- 1. 打开时居中，且处于模态（有遮罩）
    layer_w = panel.parent().property("width")
    layer_h = panel.parent().property("height")
    x0, y0 = panel.property("x"), panel.property("y")
    check("open.centered",
          abs(x0 - (layer_w - panel.property("width")) / 2) <= 2
          and abs(y0 - (layer_h - panel.property("height")) / 2) <= 2,
          "x=%s y=%s" % (x0, y0))
    check("open.notPinned", window.property("overlayPinned") is False)
    check("open.notCollapsed", panel.property("collapsed") is False)

    # ---- 2. 拖标题栏：位置跟着走 + 转成浮动（遮罩撤掉）
    header = panel.mapToScene(QPointF(panel.property("width") / 2, 24)).toPoint()
    drag(window, header, (140, 90))
    dx, dy = panel.property("x") - x0, panel.property("y") - y0
    # 起步 10px 是系统的拖动阈值（drag.startDragDistance），**不参与位移**，
    # 所以实际位移会比鼠标少一小截 —— 这是正常的，不是跑偏。
    check("drag.moved", 140 - 34 <= dx <= 146 and 90 - 34 <= dy <= 96,
          "Δ=(%d, %d) 期望约 (140, 90)（扣掉 10px 拖动阈值）" % (dx, dy))
    check("drag.pinned", window.property("overlayPinned") is True)

    # ---- 3. 拖到窗口外：松手必须被夹回来，还能抓到
    header = panel.mapToScene(QPointF(panel.property("width") / 2, 24)).toPoint()
    drag(window, header, (-1400, -900))
    x2, y2 = panel.property("x"), panel.property("y")
    floor_x = 96 - panel.property("width")
    check("drag.clampedLeft", floor_x - 0.5 <= x2 <= floor_x + 0.5,
          "x=%s 期望贴到下限 %s" % (x2, floor_x))
    check("drag.clampedTop", y2 >= 0, "y=%s" % y2)

    # ---- 4. 点标题栏上的「—」：收成一条，且仍然是浮动态
    found = buttons_of(panel)
    check("header.twoWinButtons", len(found) >= 2, "找到 %d 个按钮" % len(found))
    if len(found) >= 2:
        collapse_btn = QPoint(int(found[-2][0]), int(found[-2][1]))
        full_h = panel.property("height")
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, collapse_btn)
        settle(200)
        check("collapse.height", panel.property("height") == 56,
              "h=%s（原 %s）" % (panel.property("height"), full_h))
        check("collapse.flag", panel.property("collapsed") is True)
        check("collapse.pinned", window.property("overlayPinned") is True)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, collapse_btn)
        settle(200)
        check("collapse.restore", panel.property("height") == full_h
              and panel.property("collapsed") is False,
              "h=%s 期望 %s" % (panel.property("height"), full_h))

    # ---- 6. 换到另一个面板：位置与收起状态都重置（不留到下一次）
    window.setProperty("overlay", "review")
    settle(200)
    review = window.findChild(QObject, "reviewPanel")
    check("switch.panelVisible", review is not None and review.property("visible") is True)
    check("switch.unpinned", window.property("overlayPinned") is False)
    check("switch.resetCollapsed",
          panel.property("collapsed") is False and review.property("collapsed") is False)

    # ---- 7. 六个面板都接上了拖动条（漏一个就会出现「这个面板拖不动」）
    for name in ("skinsPanel", "settingsPanel", "apiPanel", "chatPanel",
                 "reviewPanel", "helpPanel"):
        item = window.findChild(QObject, name)
        ok = item is not None and item.property("isPanel") is True
        check("panel.%s.draggable" % name, ok)

    hard = [w for w in warnings if "Unable to assign" in w or "Cannot assign" in w]
    check("qml.noAnchorConflict", not hard, "%d 条相关警告" % len(hard))

    window.close()
    print("\n%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    for name in FAIL:
        print("  FAIL:", name)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
