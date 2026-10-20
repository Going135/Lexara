# -*- coding: utf-8 -*-
"""截启动台的**设置面板**（验证「最大识词」四档按钮的实际排版）。

    python tools/_shot_settings.py dist/shape/settings_panel.png

跟 `shot_qml.py` 的区别只有一处：加载完把 `root.overlay` 设成 "settings"，
等面板布局好再截。用户库/设置都指向临时目录，不会动真实数据。
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "dist/shape/settings_panel.png"

    tmp = tempfile.mkdtemp(prefix="lexara-shot-")
    os.environ["LEXARA_HOME"] = tmp
    for key in ("LEXARA_AI_API_KEY", "LEXARA_AI_URL", "LEXARA_AI_MODEL"):
        os.environ.pop(key, None)

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    from launcher_qml import LauncherBridge
    from lexicon import Lexicon
    from settings_store import Settings
    from wordbook import resource_path, Wordbook

    lexicon = Lexicon(resource_path("assets", "ecdict.sqlite"),
                      resource_path("assets", "exam-tags.sqlite"),
                      resource_path("assets", "industry.sqlite"))
    book = Wordbook()
    settings = Settings(log=lambda _m: None)
    settings.load()
    bridge = LauncherBridge(lexicon, book, settings, log=lambda _m: None)

    def open_panel() -> None:
        try:
            engine = getattr(bridge, "_engine", None)
            roots = engine.rootObjects() if engine is not None else []
            if not roots:
                print("no root")
                return
            root = roots[0]
            root.setProperty("overlay", "settings")
            print("overlay =", root.property("overlay"))
        except Exception:                      # noqa: BLE001
            traceback.print_exc()

    def shoot() -> None:
        try:
            win = getattr(bridge, "_window", None)
            if win is None:
                print("no window")
            else:
                image = win.grabWindow()
                os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
                image.save(out)
                print("saved %s  %dx%d" % (out, image.width(), image.height()))
        except Exception:                      # noqa: BLE001
            traceback.print_exc()
        app.quit()

    QTimer.singleShot(1800, open_panel)
    QTimer.singleShot(3600, shoot)
    return bridge.run()


if __name__ == "__main__":
    raise SystemExit(main())
