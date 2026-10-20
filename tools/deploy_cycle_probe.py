# -*- coding: utf-8 -*-
"""部署 / 收回生命周期探针（任务书 §4）。

复现「收回时出现重复 UI / 闪退」，把每一次循环的**顶层窗口**打出来：

    APPDATA=<临时沙箱> python tools/deploy_cycle_probe.py --cycles 20

判据（全部写进输出，不靠人眼）：
1. 每一轮结束后，可见的「启动台」类顶层窗口必须只有 1 个（QML 主窗）；
2. 已部署时桌宠窗口恰好 1 个；收回后 0 个；
3. 不允许出现 `RuntimeError` / `Internal C++ object already deleted`；
4. 进程退出码 0。

`--fake-pet` 用假桌宠（只统计创建/销毁次数），用来单独验证启动台侧的状态机；
默认用真 `PetWindow`，会真的在桌面右下角出现蜘蛛。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QTimer                              # noqa: E402
from PySide6.QtGui import QGuiApplication                      # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402


def _window_rows() -> list:
    """所有**可见**顶层窗口（含 QQuickWindow —— `topLevelWidgets` 看不到它）。"""
    rows = []
    for window in QGuiApplication.allWindows():
        if not window.isVisible():
            continue
        rows.append(window)
    return rows


def _launcher_windows() -> list:
    """可见的启动台类窗口。

    QML 启动台是 `QQuickWindow`；旧 Widgets 启动台是标题带「启动台」的 `QWidget`。
    两者都算「启动台 UI」—— 同屏出现两个就是任务书 §4 说的重复 UI。
    """
    out = []
    for window in _window_rows():
        name = type(window).__name__
        title = window.title() or ""
        if name == "QQuickWindow" or "启动台" in title:
            out.append("%s<%s>" % (title or "QML 启动台", name))
    return out


def _visible_top() -> list:
    rows = []
    for window in _window_rows():
        rows.append("%s<%s> %dx%d"
                    % (window.title() or "-", type(window).__name__,
                       window.width(), window.height()))
    return rows


class FakePet:
    """只统计生命周期的最小替身（不需要真窗口）。"""

    created = 0
    alive = 0

    def __init__(self, payload=None):
        FakePet.created += 1
        FakePet.alive += 1
        self.payload = payload

    def apply_settings(self, payload) -> None:
        self.payload = payload

    def shutdown(self) -> None:
        FakePet.alive -= 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--fake-pet", action="store_true")
    parser.add_argument("--deploy-ms", type=int, default=960)
    parser.add_argument("--recall-ms", type=int, default=880)
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)

    from launcher_qml import LauncherBridge
    from lexicon import Lexicon
    from settings_store import Settings
    from wordbook import Wordbook, resource_path

    tmp = tempfile.mkdtemp(prefix="lexara-cycle-")
    lexicon = Lexicon(resource_path("assets", "ecdict.sqlite"),
                      resource_path("assets", "exam-tags.sqlite"),
                      resource_path("assets", "industry.sqlite"))
    book = Wordbook(path=os.path.join(tmp, "wordbook.json"))
    settings = Settings(path=os.path.join(tmp, "settings.json"),
                        log=lambda *a: None)

    problems: list = []
    events: list = []
    bridge = LauncherBridge(lexicon, book, settings, log=lambda m: events.append(m))
    launcher = bridge.launcher

    # 手动复刻 `LauncherBridge.run()` 的前半段（不进入 exec，交给下面的循环驱动）
    qmlRegisterTypes = __import__("launcher_qml")
    import ui_theme
    warnings = []
    # 装配走 `build_engine`：和 LauncherBridge.run / ui_probe 同一个入口。
    # 以前这里复刻一份 contextProperty 清单，主题一加就漏（83 条 undefined 警告）。
    probe_theme = ui_theme.ThemeStore(watch=False)
    ui_theme.set_active(probe_theme)
    engine = qmlRegisterTypes.build_engine(
        bridge, probe_theme,
        on_warnings=lambda ws: warnings.extend(w.toString() for w in ws))
    roots = engine.rootObjects()
    if not roots:
        print("[cycle] Main.qml 加载失败")
        return 1
    bridge.set_window(roots[0])
    for grid in roots[0].findChildren(qmlRegisterTypes.HeatGrid):
        grid.attachBook(book)

    state = {"pet": None, "cycle": 0, "phase": "deploy", "t0": time.time()}

    def make_pet(payload):
        if args.fake_pet:
            return FakePet(payload)
        from pet_window import PetWindow
        pet = PetWindow(lexicon, book, settings=settings)
        pet.apply_settings(payload)
        return pet

    def on_deploy(payload):
        if state["pet"] is not None:
            problems.append("重复部署：已有桌宠实例仍存在")
            return
        state["pet"] = make_pet(payload)

    def on_recall():
        pet = state["pet"]
        if pet is None:
            return
        pet.shutdown()
        state["pet"] = None

    launcher.deploy_requested.connect(on_deploy)
    launcher.recall_requested.connect(on_recall)

    def inspect(tag: str) -> None:
        wins = _launcher_windows()
        extra = ""
        if len(wins) > 1:
            extra = "  ← 重复 UI：%d 个启动台窗口 %s" % (len(wins), wins)
            problems.append("%s 出现 %d 个启动台窗口" % (tag, len(wins)))
        print("[%02d] %-8s phase=%-9s 启动台=%d %s 桌宠=%s%s"
              % (state["cycle"], tag, launcher.phase, len(wins),
                 ",".join(wins), "有" if state["pet"] is not None else "无",
                 extra))

    def step():
        state["cycle"] += 1
        if state["cycle"] > args.cycles:
            inspect("结束")
            print("[cycle] 启动台窗口最终数量 = %d" % len(_launcher_windows()))
            print("[cycle] 可见顶层窗口：")
            for row in _visible_top():
                print("        %s" % row)
            print("[cycle] 假桌宠 created=%d alive=%d"
                  % (FakePet.created, FakePet.alive))
            if warnings:
                print("[cycle] QML 警告 %d 条（前 3）：" % len(warnings))
                for line in warnings[:3]:
                    print("        %s" % line)
            print("[cycle] 问题 %d 条" % len(problems))
            for line in problems[:12]:
                print("        %s" % line)
            print("[cycle] %s" % ("PASS" if not problems else "FAIL"))
            app.exit(0 if not problems else 1)
            return
        if state["phase"] == "deploy":
            state["phase"] = "recall"
            launcher.on_deploy_button()
            QTimer.singleShot(args.deploy_ms, after_deploy)
        else:
            state["phase"] = "deploy"
            launcher.on_deploy_button()
            QTimer.singleShot(args.recall_ms, after_recall)

    def after_deploy():
        inspect("部署后")
        if launcher.phase != "deployed":
            problems.append("第 %d 次部署未到 deployed（实际 %s）"
                            % (state["cycle"], launcher.phase))
        step()

    def after_recall():
        inspect("收回后")
        if launcher.phase != "idle":
            problems.append("第 %d 次收回未回到 idle（实际 %s）"
                            % (state["cycle"], launcher.phase))
        step()

    def install_hook() -> None:
        def hook(exc_type, exc, tb):
            text = "".join(traceback.format_exception(exc_type, exc, tb))
            problems.append("未捕获异常：%s" % text.splitlines()[-1])
            print("[cycle] 未捕获异常：\n%s" % text)
        sys.excepthook = hook

    install_hook()
    QTimer.singleShot(600, step)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
