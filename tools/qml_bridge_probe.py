# -*- coding: utf-8 -*-
"""QML 桥接的功能自检：换装 / 设置写回是否真的落到 settings 与渲染器上。

会临时改 settings.json，结束前恢复原值（不污染用户配置）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from PySide6.QtWidgets import QApplication

from launcher_qml import LauncherBridge
from lexicon import Lexicon
from settings_store import DEFAULTS, Settings
from wordbook import Wordbook, resource_path


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    lexicon = Lexicon(resource_path("assets", "ecdict.sqlite"),
                      resource_path("assets", "exam-tags.sqlite"),
                      resource_path("assets", "industry.sqlite"))
    book = Wordbook()
    settings = Settings(log=print)
    settings.load()
    original = settings.as_dict()

    bridge = LauncherBridge(lexicon, book, settings, log=print)
    failures = []

    def check(name, got, want):
        ok = got == want
        print("[%s] %-22s got=%r want=%r" % ("ok" if ok else "FAIL", name, got, want))
        if not ok:
            failures.append(name)

    try:
        return _cases(bridge, settings, failures, check)
    finally:
        # ★ 必须 try/finally：2026-10-17 一次中途 TypeError 崩在 payload 检查上，
        #   恢复语句没跑到，把用户真实 settings.json 改成了 pixel_spider/1.2/5/0.72。
        settings.update(original)
        print("restored:", {k: settings.get(k) for k in
                            ("skin", "pet_scale", "max_words", "min_conf")})


def _cases(bridge, settings, failures, check) -> int:
    # 换装：设置 + 罐内渲染器都要跟着
    bridge.setSkin("pixel_spider")
    check("skin.apply", settings.get("skin"), "pixel_spider")
    check("skin.jar", bridge.launcher.jar.painter._skin_id, "pixel_spider")
    # ★ 2026-10-18：`payload` 以前读隐藏面板（QML 换皮根本不点它），部署时发出去的
    #   还是旧皮肤 —— 用户看到「切换皮肤后部署仍是原皮肤」。必须逐层对齐。
    check("skin.payload", bridge.launcher.payload["skin"], "pixel_spider")
    check("skin.panel", bridge.launcher.panel.current_skin(), "pixel_spider")

    bridge.setMaxWords(5)
    check("max_words", settings.get("max_words"), 5)

    bridge.setMinConfPct(72)
    check("min_conf", round(float(settings.get("min_conf")), 2), 0.72)

    # 大小：除了写盘，还必须发信号让**已部署**的桌宠实时改（以前只写盘）
    scales = []
    bridge.launcher.scale_changed.connect(lambda v: scales.append(round(float(v), 2)))
    bridge.setPetScalePct(120)
    check("pet_scale", round(float(settings.get("pet_scale")), 2), 1.2)
    check("pet_scale.signal", scales, [1.2])
    # payload 是 @property（launcher_window.py:2017），部署时真正发给桌宠的就是它，
    # 必须和 settings 同步，否则会「调了大小但桌宠没变」。
    check("payload.pet_scale",
          round(float(bridge.launcher.payload["pet_scale"]), 2), 1.2)

    bridge.setAlwaysOnTop(False)
    check("always_on_top", bool(settings.get("always_on_top")), False)

    bridge.setShowMeaningCard(False)
    check("show_meaning_card", bool(settings.get("show_meaning_card")), False)

    bridge.resetSettings()
    # 别再把默认值写死成 8：max_words 的区间与默认值归 `settings_store.DEFAULTS`
    # 管（2026-10-18 起是 1~48 / 默认 24），写死会让这条断言在下一次调默认值时
    # 报一个**假的**失败。这里断言的语义是「重置回出厂值」，那就问出厂值是多少。
    check("reset.max_words", settings.get("max_words"), DEFAULTS["max_words"])
    check("reset.pet_scale", round(float(settings.get("pet_scale")), 2), 1.0)

    # 缩略图：四套皮肤都要有可用文件（QML 侧拿到的是 file:// URL 字符串）
    from PySide6.QtCore import QUrl

    skins = bridge.skins
    check("skins.count", len(skins), 4)
    missing = []
    for item in skins:
        local = QUrl(item["thumb"]).toLocalFile()
        if not os.path.isfile(local):
            missing.append("thumb:%s" % item["id"])
    check("skins.thumb", missing, [])
    failures.extend(missing)

    print("[probe] %s" % ("PASS" if not failures else "FAIL " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
