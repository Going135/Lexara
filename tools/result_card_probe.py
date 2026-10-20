# -*- coding: utf-8 -*-
"""结果卡按需 AI（任务书 §5）的**可视化 + 无网络**探针。

跑法：``python tools/result_card_probe.py``
输出：``dist/cards/*.png`` 三张状态图 + 终端 PASS/FAIL 计数。

这里刻意**不碰真实配置**：
* `ai.context_request.resolve_config` 被打桩成「未配置」，
  所以既不会去读 `%APPDATA%\\Lexara\\ai_secret.bin`，更不会拿真 key 发请求；
* `urllib.request.urlopen` 全程打桩成「调了就炸」，
  任何一条路径偷偷联网都会被抓出来。
"""
from __future__ import annotations

import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)
OUT = os.path.join(BASE, "dist", "cards")
os.makedirs(OUT, exist_ok=True)

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("[ok]" if ok else "[x] ", name,
                         ("　" + detail) if detail else ""))


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    # ---- 红线探针：任何联网尝试都当场炸掉 ------------------------------
    attempts = []

    def explode(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("默认链路里不允许发网络请求")

    original_urlopen = urllib.request.urlopen
    urllib.request.urlopen = explode

    class NoConfig:
        def api_key(self): return ""
        def base_url(self): return ""
        def model(self): return ""
        def endpoint(self): return ""

    import ai.context_request as context_request
    original_resolve = context_request.resolve_config

    def fake_resolve(config=None):
        return (config or NoConfig()), ["API Key", "Base URL", "模型名"]

    context_request.resolve_config = fake_resolve

    try:
        import dialogs
        from ai.context_request import ContextRequest

        items = [
            {"lemma": "accelerate", "surface": "accelerated", "word": "accelerate",
             "phonetic": "/əˈseləreɪt/", "meaning": "v. 加速；促进",
             "level": "CET6", "tags": ["CET6"],
             "screen_pos": (320.0, 210.0), "screen_box": (250.0, 198.0, 96.0, 24.0),
             "ai_source": "local", "ai_requested": False,
             "ai_candidate_count": 9, "ai_eligible_count": 9,
             "context_meaning": "v. 加速；促进", "ai_reason": "",
             "collocations": [], "sentence_meaning": "",
             "context_sentence": "The committee accelerated the spring plan."},
            {"lemma": "thunder", "surface": "thunder", "word": "thunder",
             "phonetic": "/ˈθʌndə/", "meaning": "n. 雷 v. 打雷",
             "level": "KET", "tags": ["KET"], "off_syllabus": False,
             "screen_pos": (500.0, 210.0), "ai_source": "local",
             "ai_requested": False, "ai_candidate_count": 9,
             "ai_eligible_count": 9, "context_meaning": "n. 雷",
             "ai_reason": "", "collocations": [],
             "context_sentence": "thunder rolled across the valley"},
        ]

        class Book:
            def __init__(self): self.saved = []
            def stats(self): return {"today": 2, "due": 0, "total": 0}
            def has(self, word): return word in [i["lemma"] for i in self.saved]
            def add(self, info):
                self.saved.append(info); return True
            def remove(self, word): return False

        book = Book()
        dialog = dialogs.WordResultDialog(None, items, book, "CET6")
        dialog.show()
        app.processEvents()

        ui = dialog._ai_ui["accelerate"]
        labels = ui["labels"]
        print("\n[1] 默认状态 = 本地词典，卡片里没有 AI 内容")
        check("卡片带上了「AI 语境分析与造句」按钮",
              ui["button"].text() == "AI 语境分析与造句",
              "按钮文案=%r" % ui["button"].text())
        check("默认没有展开 AI 结果区", ui["box"].isVisible() is False)
        check("默认状态没有发过任何网络请求", not attempts,
              "尝试次数 %d" % len(attempts))
        header = [label for label in dialog.findChildren(dialogs.QLabel)
                  if label.objectName() == "analysis"]
        check("头部如实写着「未调用云端」",
              bool(header) and "未调用云端" in header[0].text(),
              header[0].text() if header else "（没有 analysis 标签）")
        dialog.grab().save(os.path.join(OUT, "card_1_local.png"))

        print("\n[2] 未配置时点按钮 → 提示「先配置 API/模型」，且仍然不联网")
        ui["button"].click()
        app.processEvents()
        check("提示里写清了缺什么", "还没有配置" in ui["status"].text(),
              ui["status"].text())
        check("提示里有「先配置 API/模型」入口语",
              "先配置 API/模型" in ui["status"].text())
        check("按钮回到可再点状态", ui["button"].isEnabled()
              and ui["button"].text() == "AI 语境分析与造句")
        check("未配置这条路没有起网络请求", not attempts,
              "尝试次数 %d" % len(attempts))
        check("没有在途请求残留", dialog._ai_request is None)
        dialog.grab().save(os.path.join(OUT, "card_2_unconfigured.png"))

        print("\n[3] 注入一次成功结果 → 只追加内容，不动词典释义与词框")
        dialog._ai_finished("accelerate", {
            "status": "ok", "elapsed": 1.87, "word": "accelerated",
            "ai": {"context_meaning": "（委员会）加快、推进（春季计划）",
                   "ai_reason": "真题里高频出现的及物动词，常接抽象名词",
                   "collocations": ["accelerate the plan", "accelerate growth"],
                   "examples": [{"sentence": "The city accelerated its green programme.",
                                 "meaning": "这座城市加快了绿色计划。"}],
                   "ai_source": "cloud", "ai_requested": True}})
        app.processEvents()
        check("句中义显示出来了", "加快、推进" in labels["context"].text(),
              labels["context"].text())
        check("搭配显示出来了", "accelerate the plan" in labels["phrases"].text())
        check("例句显示出来了", "green programme" in labels["examples"].text())
        check("AI 区展开", ui["box"].isVisible())
        check("词典释义本身没有被改写",
              items[0]["meaning"] == "v. 加速；促进"
              and items[0]["context_sentence"].startswith("The committee"),
              items[0]["context_sentence"])
        check("词框与落点没有被改写",
              items[0]["screen_box"] == (250.0, 198.0, 96.0, 24.0)
              and items[0]["screen_pos"] == (320.0, 210.0))
        check("按钮变成「再分析一次」", ui["button"].text() == "再分析一次")
        star = dialog._stars.get("accelerate")
        star.click()
        app.processEvents()
        check("收藏时带走的是本地词典释义（AI 内容不覆盖它）",
              bool(book.saved) and book.saved[0] is items[0]
              and book.saved[0]["meaning"] == "v. 加速；促进",
              "saved=%d" % len(book.saved))
        dialog.grab().save(os.path.join(OUT, "card_3_ai_ok.png"))

        print("\n[4] 失败与取消：本地释义必须原样留着")
        dialog._ai_finished("thunder", {
            "status": "failed", "code": "timeout", "word": "thunder",
            "message": "连接超时。检查网络，或换一个响应更快的服务。"})
        app.processEvents()
        thunder = dialog._ai_ui["thunder"]
        check("失败只在状态行里说原因", "连接超时" in thunder["status"].text())
        check("失败时按钮可重试", thunder["button"].text() == "重试 AI 分析")
        check("失败时不显示 AI 结果区", thunder["box"].isVisible() is False)
        dialog._ai_finished("thunder", {"status": "cancelled", "word": "thunder"})
        app.processEvents()
        check("取消后写「本地释义不受影响」",
              "已取消" in thunder["status"].text())

        print("\n[5] 限流：一张卡同一时刻只有一个在途请求")
        request = ContextRequest(config=NoConfig(), parent=dialog)
        request.active = True            # 模拟「请求正在跑」
        dialog._ai_request = request
        dialog._ai_word = "accelerate"
        thunder["button"].click()
        app.processEvents()
        check("第二张卡的按钮被挡住并给出说明",
              "已经有一个分析在跑" in thunder["status"].text(),
              thunder["status"].text())
        check("被挡住时没有新建请求", dialog._ai_request is request)
        dialog._ai_request = None
        dialog._ai_word = ""

        print("\n[6] 关闭卡片：线程回收 + 不再有请求")
        dialog.close()
        app.processEvents()
        check("关闭后没有在途请求", dialog._ai_request is None)
        check("全程没有触碰网络", not attempts, "尝试次数 %d" % len(attempts))

        cards = sorted(f for f in os.listdir(OUT) if f.endswith(".png"))
        check("状态图已存盘", len(cards) >= 3, " ".join(cards))
    finally:
        urllib.request.urlopen = original_urlopen
        context_request.resolve_config = original_resolve

    print("\n" + "=" * 60)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for name in FAIL:
        print("  FAILED:", name)
    print("图：%s" % OUT)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
