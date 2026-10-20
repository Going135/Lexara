# -*- coding: utf-8 -*-
"""截一张启动台窗口（只截窗口本身，不含桌面）。

    python tools/shot_qml.py dist/shot.png [等待毫秒]

为什么不用 `QScreen.grabWindow(0)`：那会把整个桌面（含用户其他窗口）截进去，
既慢又没必要。`QQuickWindow.grabWindow()` 直接渲染这一棵树，结果干净。
"""

from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "dist/shot.png"
    delay = int(sys.argv[2]) if len(sys.argv) > 2 else 4000

    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    from launcher_qml import LauncherBridge
    from lexicon import Lexicon
    from settings_store import Settings
    from wordbook import app_data_dir, resource_path, Wordbook

    lexicon = Lexicon(resource_path("assets", "ecdict.sqlite"),
                      resource_path("assets", "exam-tags.sqlite"),
                      resource_path("assets", "industry.sqlite"))
    book = Wordbook()
    settings = Settings(log=lambda _m: None)
    settings.load()
    bridge = LauncherBridge(lexicon, book, settings, log=lambda _m: None)

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
        except Exception:                    # noqa: BLE001
            traceback.print_exc()
        app.quit()

    QTimer.singleShot(delay, shoot)
    return bridge.run()


if __name__ == "__main__":
    raise SystemExit(main())
