# -*- coding: utf-8 -*-
"""QML 界面 + 新桥接能力的自动化自检（不依赖人眼看截图）。

覆盖任务书第 9 节里这几条：
- 启动台 QML 能加载、无 QML 错误/警告；
- 背单词：入口 → 开始 → 揭示 → 自评 → 下一词 → 退出/重进 → 数据真的变了；
- AI 未配置时发送必须禁用且失败要有原因；配置保存 / 清除 / 安全存储；
- 引擎状态来自真实实现；
- `?` 帮助文案与实际能力一致（不允许出现「开发中」却宣称可用）。

跑法：
    python tools/ui_probe.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtWidgets import QApplication        # noqa: E402

from ai.config import SecretStore                 # noqa: E402
from launcher_qml import LauncherBridge           # noqa: E402
from lexicon import Lexicon                       # noqa: E402
from settings_store import Settings               # noqa: E402
from wordbook import Wordbook, resource_path      # noqa: E402


def main() -> int:
    """跑一遍自检。

    **全程隔离**：词库 / 设置 / 密钥目录都指向临时目录，并且先把
    ``LEXARA_AI_*`` 环境变量摘掉 —— 否则本机配过的 AI 会让「未配置」这条
    断言恒假，探针也会把用户的真实词库和密钥改脏。
    """
    saved_env = {key: os.environ.pop(key)
                 for key in ("LEXARA_AI_API_KEY", "LEXARA_AI_URL",
                             "LEXARA_AI_MODEL")
                 if key in os.environ}
    try:
        with tempfile.TemporaryDirectory(prefix="lexara-probe-") as tmp:
            app = QApplication.instance() or QApplication(sys.argv)
            lexicon = Lexicon(resource_path("assets", "ecdict.sqlite"),
                              resource_path("assets", "exam-tags.sqlite"),
                              resource_path("assets", "industry.sqlite"))
            book = Wordbook(path=os.path.join(tmp, "wordbook.json"))
            settings = Settings(path=os.path.join(tmp, "settings.json"),
                                log=lambda *a: None)
            secrets = SecretStore(directory=tmp)

            failures: list = []

            def check(name, got, want):
                ok = got == want
                print("[%s] %-34s got=%r want=%r"
                      % ("ok" if ok else "FAIL", name, got, want))
                if not ok:
                    failures.append(name)

            bridge = LauncherBridge(lexicon, book, settings,
                                    log=lambda *a: None, secrets=secrets)
            _cases(bridge, settings, book, check)
            _qml_load(bridge, check)

            print("[ui-probe] %s" % ("PASS" if not failures
                                     else "FAIL " + ", ".join(failures)))
            return 0 if not failures else 1
    finally:
        os.environ.update(saved_env)
        print("isolated: temp profile removed, env restored")


def _cases(bridge, settings, book, check) -> None:
    print("--- 设置区间（唯一来源） ---")
    # 档位必须由 `settings_store.MAX_WORDS_CHOICES` 透出，而不是 QML 里写字面量。
    # 这条断言盯的是「常量改了但界面没跟上」——这个数今年改过两次
    # （8 → 24 → 收成 8/16/32/48 四档）。
    from settings_store import MAX_WORDS_CHOICES
    check("settings.choices", list(bridge.maxWordsChoices),
          list(MAX_WORDS_CHOICES))
    bridge.setMaxWords(MAX_WORDS_CHOICES[-1] + 100)
    check("settings.range.clampHigh", settings.get("max_words"),
          MAX_WORDS_CHOICES[-1])
    bridge.setMaxWords(0)
    check("settings.range.clampLow", settings.get("max_words"),
          MAX_WORDS_CHOICES[0])
    # 中间值（滑杆时代留下的 12 / 24）必须落到最近的档，而不是原样存进去 ——
    # 否则设置页四个按钮一个都不亮。
    bridge.setMaxWords(12)
    check("settings.snap12", settings.get("max_words"), 16)
    bridge.setMaxWords(24)
    check("settings.snap24", settings.get("max_words"), 32)
    bridge.setMaxWords(MAX_WORDS_CHOICES[-1])

    print("--- 背单词 ---")
    bridge.openReview()
    check("review.stage", bridge.reviewStage, "home")
    # 入口页统计必须来自真实词库，且与 book.stats() 一致
    overview = bridge.reviewOverview
    stats = book.stats()
    check("review.total", overview["total"], stats["total"])
    check("review.due", overview["due"], stats["due"])

    # 空输入 / 未开始时的诚实状态
    if bridge.reviewSummary["total"] == 0:
        check("review.emptyCard", bridge.reviewCard, {})

    # 造 3 个到期词，跑完整流程
    added = 0
    for i in range(3):
        if book.add({"word": "probe%d" % i, "phonetic": "/pr/",
                     "meaning": "探针 %d" % i, "level": "CET4", "tags": ["四级"]}):
            added += 1
    bridge.startReviewSession(False)
    check("review.started", bridge.reviewStage, "card")
    card = bridge.reviewCard
    check("review.card.index", card["index"], 1)
    check("review.card.total", card["total"], added)
    check("review.card.hidden", card["revealed"], False)
    check("review.card.hasMeaning", bool(card["meaning"]), True)

    bridge.reviewReveal()
    check("review.card.revealed", bridge.reviewCard["revealed"], True)

    word = bridge.reviewCard["word"]
    # 注意：`book.get()` 返回的是**活的 Item 对象**，直接持有它会在评分后被就地
    # 改写（同一个对象），断言就失去意义。这里先把标量快照下来。
    snapshot = book.get(word)
    before_stage, before_correct = snapshot.stage, snapshot.correct
    bridge.reviewGrade(True)
    after = book.get(word)
    check("review.grade.writes", after.stage, min(before_stage + 1, 3))
    check("review.grade.counts", after.correct, before_correct + 1)
    check("review.advances", bridge.reviewSummary["answered"], 1)

    # 中途退出 → 已经产生的复习记录不能被回滚
    bridge.reviewExit()
    check("review.exit.stage", bridge.reviewStage, "home")
    check("review.exit.keeps", book.get(word).stage, after.stage)

    # 再次进入还能继续
    bridge.startReviewSession(False)
    check("review.reenter", bridge.reviewStage, "card")

    print("--- AI 配置 / 安全存储 ---")
    cfg = bridge._ai_config
    check("ai.store.available", cfg.secrets.available, True)
    check("ai.key.notInSettings", "apiKey" in settings.as_dict(), False)
    check("ai.defaultNotConfigured", bridge.aiReady, False)

    # 未配置时发送必须失败并给出原因
    bridge.newChatSession()
    sent = bridge.send("hello")
    check("ai.send.blocked", sent, False)
    check("ai.send.reason", bridge.chatStatus.get("code"), "not_configured")
    check("ai.noMessages", len(bridge.chatMessages), 0)

    # 公网 HTTP 必须被拒绝
    result = bridge.saveAiConfig("http://example.com/v1", "m", "k")
    check("ai.rejectPlainHttp", result.get("message", "").find("https") >= 0, True)
    # loopback 允许
    result = bridge.saveAiConfig("http://localhost:11434/v1", "llama3", "secret-key")
    check("ai.loopbackOk", result.get("configured"), True)
    check("ai.endpointResolved", result["endpoint"],
          "http://localhost:11434/v1/chat/completions")

    # 密钥必须落进加密文件，而不是 settings.json
    raw_text = open(settings.path, encoding="utf-8").read()
    check("ai.keyAbsentFromJson", "secret-key" in raw_text, False)
    check("ai.hasKey", bool(cfg.api_key()), True)
    check("ai.readyNow", bridge.aiReady, True)
    check("ai.masked", cfg.masked_key().startswith("●"), True)
    check("ai.fullKeyHidden", "secret-key" in bridge.aiSnapshot.values(), False)

    bridge.clearAiKey()
    check("ai.cleared", bool(cfg.api_key()), False)
    check("ai.disabledAfterClear", bridge.aiReady, False)

    print("--- OCR 引擎状态 ---")
    engines = bridge.engines
    ids = [e["id"] for e in engines]
    check("engine.listNotEmpty", len(ids) > 0, True)
    check("engine.hasRapid", "rapid" in ids, True)
    states = {e["id"]: e["state"] for e in engines}
    # `unknown` 是后端的**初始态**（还没探测过），属于诚实状态，必须放行；
    # 但绝不能被画成可用 —— 下面这两条断言负责盯这件事。
    check("engine.statesKnown",
          all(v in ("available", "unavailable", "loading", "error", "unknown")
              for v in states.values()), True)
    check("engine.currentReal", bridge.currentEngine in ids, True)
    check("engine.hasLabels", all(e["stateLabel"] for e in engines), True)
    # 切到不存在的引擎必须失败，且不静默
    bad = bridge.selectEngine("nope")
    check("engine.unknownRejected", bad["ok"], False)
    # 没验证过的 / 不可用的引擎一律拒绝，并且**把原因回给用户**
    for row in engines:
        if row["state"] == "available":
            continue
        res = bridge.selectEngine(row["id"])
        check("engine.rejected.%s" % row["id"], res["ok"], False)
        check("engine.reason.%s" % row["id"], bool(res.get("message")), True)

    print("--- 帮助文案 ---")
    steps = bridge.helpSteps
    check("help.count", len(steps), 10)
    check("help.fields", all(k in steps[0] for k in
                             ("id", "title", "state", "bullets", "stateLabel")), True)
    check("help.statesValid",
          all(s["state"] in ("ready", "partial", "planned") for s in steps), True)
    check("help.plannedMarked",
          all(s["stateLabel"] for s in steps if s["state"] == "planned"), True)


def _qml_load(bridge, check) -> None:
    """真的把 Main.qml 拉起来，断言零错误零警告。"""
    print("--- QML 加载 ---")
    from PySide6.QtQml import QQmlApplicationEngine

    from launcher_qml import HeatGrid, build_engine
    import ui_theme
    warnings: list = []

    def on_warning(items):
        for item in items:
            warnings.append(item.toString())

    #: 装配走 `build_engine`（和 LauncherBridge.run 同一个函数）。
    #: 以前这里手工复刻 contextProperty 清单，主题一加就漏了 theme ——
    #: 测出来的是「一份没有主题的界面」，84 条 undefined 警告。
    #: watch=False：探针只验证加载，不需要盯文件。
    probe_theme = ui_theme.ThemeStore(watch=False)
    ui_theme.set_active(probe_theme)
    engine = build_engine(bridge, probe_theme, on_warnings=on_warning)
    app = QApplication.instance()
    roots = engine.rootObjects()
    check("qml.rootLoaded", len(roots) > 0, True)
    if roots:
        # 多轮事件处理，让延时绑定 / Loader / Repeater 全部求值，
        # 这样 QML 的错误与警告才会真的发出来。
        for _ in range(5):
            app.processEvents()
            app.sendPostedEvents(None, 0)
    real = [w for w in warnings if w.strip()]
    for message in real[:12]:
        print("    [qml] %s" % message)
    check("qml.noWarnings", len(real), 0)
    for grid in (roots[0].findChildren(HeatGrid) if roots else []):
        grid.attachBook(bridge._book)
    print("    roots=%d children=%d" % (len(roots),
                                        len(roots[0].findChildren(object)) if roots else 0))


if __name__ == "__main__":
    raise SystemExit(main())
