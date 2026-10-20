# -*- coding: utf-8 -*-
"""启动台（Qt 版）离线渲染探针。

为什么不用浏览器截图：本环境里 `take_screenshot` 拿不到真实视口
（`NATIVE_BROWSER_VIEWPORT_UNAVAILABLE` / visibilityState=hidden），
所以走 `widget.grab()` —— 它**同步**跑一遍 `paintEvent`，不依赖合成器，
正好能验「画得对不对」而不只是「跑没跑崩」。

用法：
    python tools/launcher_probe.py            # 跑完整时间线，图落在 dist/launcher_probe
    python tools/launcher_probe.py --shots    # 只要静态图，不跑部署/收回动画
"""

from __future__ import annotations

import os
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SRC, "src"))
sys.path.insert(0, SRC)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

OUT = os.path.join(SRC, "dist", "launcher_probe")
errors = []


def spin(seconds: float, fps: int = 30) -> None:
    """让事件循环真的跑帧（`grab()` 不算动画，必须空转）。"""
    deadline = time.monotonic() + seconds
    step = 1.0 / fps
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(step)


def shot(widget, name: str) -> str:
    path = os.path.join(OUT, name + ".png")
    try:
        ok = widget.grab().save(path)
    except Exception:                          # noqa: BLE001
        errors.append("[shot] %s\n%s" % (name, traceback.format_exc()))
        return ""
    if not ok:
        errors.append("[shot] %s 保存失败" % name)
    print("[shot] %-22s -> %s" % (name, path))
    return path


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)               # noqa: F841

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
    print("[probe] 词典 %s" % lexicon.status().get("available"))

    win = LauncherWindow(lexicon, book, settings, log=print)
    win.resize(1060, 720)
    win.show()
    spin(0.4)

    # ------------------------------------------------------------ 静态布局
    jar = win.jar
    rect = jar.jar_rect()
    ground, lo, hi, reach = jar.bounds()
    unit = jar.unit()
    speed = 0.30 * 60.0 * unit
    print("[geom] 窗口 %dx%d 瓶身 %.0fx%.0f 左偏移 %.1f 壁宽 %.1f"
          % (win.width(), win.height(), rect.width(), rect.height(),
             rect.left(), jar.wall_w()))
    print("[geom] unit %.3f reach %.1f ground %.1f 行走带 %.1f~%.1f"
          % (unit, reach, ground, lo, hi))
    print("[geom] 瓶内速度 %.1f px/s，单趟跨瓶 %.1fs"
          % (speed, (hi - lo) / speed))
    if reach > rect.height():
        errors.append("[geom] !! 蜘蛛够不着地（reach %.1f > 瓶高 %.1f）"
                      % (reach, rect.height()))
    if not (lo < hi):
        errors.append("[geom] !! 行走带反了")

    # 玻璃罐现在住在面板内部（六档按钮块的**右半边**）。
    # 旧版这里断言的是「瓶身占可用高度的 64%」—— 那是纵向三段布局的遗留，
    # 横向改版后就已经不成立（0.598 vs 0.64），罐子搬进面板后彻底作废。
    # 现在改断言它**真的在面板右半边、且不越出面板**，这才是新布局的契约。
    jar_in_panel = jar.mapTo(win.panel, QPoint(0, 0))
    panel_w = win.panel.width()
    print("[geom] 罐子在面板内 x %.0f~%.0f（面板宽 %d，右半边起点 %.0f）"
          % (jar_in_panel.x(), jar_in_panel.x() + jar.width(),
             panel_w, panel_w * 0.5))
    if jar_in_panel.x() < panel_w * 0.45:
        errors.append("[geom] !! 罐子没落在面板右半边：x=%.0f < %.0f"
                      % (jar_in_panel.x(), panel_w * 0.45))
    if jar_in_panel.x() + jar.width() > panel_w + 1:
        errors.append("[geom] !! 罐子越出面板右边界：%.0f > %d"
                      % (jar_in_panel.x() + jar.width(), panel_w))
    if jar.height() <= 0:
        errors.append("[geom] !! 罐子被压成 0 高（stretch 把它吃掉了）")

    shot(win, "01_idle")
    shot(jar, "02_jar_only")
    shot(win.panel, "03_panel")
    shot(win.title_bar, "04_titlebar")

    # 裂纹图加载情况（资源没打进来的话这里是 0x0）
    for index, pixmap in enumerate(jar._cracks):
        print("[crack] 图 %d：%dx%d null=%s"
              % (index + 1, pixmap.width(), pixmap.height(), pixmap.isNull()))
        if pixmap.isNull():
            errors.append("[crack] 第 %d 张贴图没加载到" % (index + 1))

    # ------------------------------------------------------------ 设置弹层
    win.open_sheet()
    spin(0.3)
    shot(win.sheet if win.sheet else win, "05_settings_sheet")
    try:
        sliders = win.sheet._sliders
        print("[sheet] 滑杆 %s" % sorted(sliders))
        win.sheet._reset()
        spin(0.1)
    except Exception:                          # noqa: BLE001
        errors.append("[sheet]\n" + traceback.format_exc())
    win.close_sheet()
    spin(0.1)

    # ------------------------------------------------------------ 部署时间线
    got = {"payload": None, "recall": 0}
    win.deploy_requested.connect(lambda p: got.__setitem__("payload", p))
    win.recall_requested.connect(lambda: got.__setitem__("recall", got["recall"] + 1))

    win.begin_deploy()
    spin(0.10)
    shot(win, "06_deploy_crack1")
    spin(0.18)
    shot(win, "07_deploy_crack2")
    spin(0.16)
    shot(win, "08_deploy_crack3_debris")
    spin(0.16)
    shot(win, "09_burst_flash")
    spin(0.50)
    print("[deploy] 阶段=%s 发出去的 payload=%s"
          % (win.phase, got["payload"]))
    if win.phase != "deployed":
        errors.append("[deploy] 740ms 后阶段仍是 %s" % win.phase)
    if got["payload"] is None:
        errors.append("[deploy] deploy_requested 没带 payload")

    # ------------------------------------------------------------ 收回时间线
    spin(1.2)                                   # 让瓶身淡出跑完
    shot(win, "10_after_deploy_empty")
    win.begin_recall()
    spin(0.20)
    shot(win, "11_recall_falling")
    spin(0.22)
    shot(win, "12_recall_landed")
    spin(0.60)
    shot(win, "13_recalled")
    print("[recall] 阶段=%s recall_requested 次数=%d 裂纹=%d opened=%s"
          % (win.phase, got["recall"], jar.crack_level, jar.opened))
    if got["recall"] != 1:
        errors.append("[recall] recall_requested 触发 %d 次（应为 1）" % got["recall"])
    if win.phase != "idle":
        errors.append("[recall] 收回后阶段=%s" % win.phase)
    if jar.crack_level != 0 or jar.opened:
        errors.append("[recall] 罐子没复原：crack=%d opened=%s"
                      % (jar.crack_level, jar.opened))

    # 再部署一次，确认状态机可重复
    win.begin_deploy()
    spin(1.0)
    if win.phase != "deployed":
        errors.append("[rerun] 第二次部署失败：%s" % win.phase)
    else:
        print("[rerun] 第二次部署 OK")

    print("\n[probe] %s" % ("全部通过，无异常" if not errors
                            else "发现问题 %d 条:\n%s" % (len(errors),
                                                          "\n".join(errors))))
    return 0 if not errors else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                          # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
