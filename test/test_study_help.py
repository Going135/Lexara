# -*- coding: utf-8 -*-
"""背单词 AI 辅助（造句 / 同义词）的测试。

三条守则：
1. **一次网络都不发**：worker 用假实现注入，`StudyHelpService` 里的线程逻辑
   不参与测试 —— 测的是「状态机、缓存、作废」这三件真正容易写错的事；
2. **提示词单独测**：`build_messages()` 是纯函数，直接断言它带了单词、释义和
   「只给结果、不要寒暄」，因为这三条决定了输出能不能直接铺在卡片上；
3. **未配置不能假装能用**：没填 Key 时必须落到 `error/not_configured`，
   而且**不许启动线程**（否则用户会在后台一直等一个注定失败的请求）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QObject, Signal

from ai.study_help import (MAX_CACHE, MODE_SENTENCE, MODE_SYNONYM,
                           StudyHelpService, build_messages)


class FakeConfig:
    """只实现服务真正用到的那三个方法。"""

    settings = None

    def __init__(self, key="k", base="http://localhost:11434/v1", model="m"):
        self._key, self._base, self._model = key, base, model

    def api_key(self):
        return self._key

    def base_url(self):
        return self._base

    def model(self):
        return self._model


class FakeWorker(QObject):
    """记录被请求体，手动触发结果。`start()` 不跑线程。"""

    finished_with = Signal(object, object)

    def __init__(self, endpoint, key, model, messages):
        super().__init__()
        self.endpoint = endpoint
        self.api_key = key
        self.model = model
        self.messages = messages
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def isRunning(self):
        return self.started and not self.cancelled

    def cancel(self):
        self.cancelled = True

    def finish(self, ok, payload):
        self.finished_with.emit(ok, payload)


class Harness:
    """把 service + 造出来的 worker 收在一起，省得每个用例都写一遍。"""

    def __init__(self, config=None):
        self.created = []
        self.service = StudyHelpService(
            config or FakeConfig(),
            worker_factory=self._factory)
        self.events = []
        self.service.changed.connect(lambda: self.events.append(
            dict(self.service.state)))

    def _factory(self, endpoint, key, model, messages):
        worker = FakeWorker(endpoint, key, model, messages)
        self.created.append(worker)
        return worker

    @property
    def state(self):
        return self.service.state


class PromptTests(unittest.TestCase):
    def test_sentence_prompt_carries_word_and_meaning(self):
        messages = build_messages("accelerate", "加快，加速", MODE_SENTENCE, "cet4")
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        body = messages[1]["content"]
        self.assertIn("accelerate", body)
        self.assertIn("加快，加速", body)
        self.assertIn("译：", body)                  # 要求带中文翻译
        self.assertIn("大学英语四级", body)           # 档位进了提示词
        # 「只给结果」的口径必须写死在提示词里，不能指望模型自觉
        # （人设走 persona，所以这句话在 system，不在 user）
        self.assertIn("不要寒暄", messages[0]["content"])

    def test_synonym_prompt_asks_for_differences(self):
        body = build_messages("big", "大的", MODE_SYNONYM, "cet6")[1]["content"]
        self.assertIn("同义词", body)
        self.assertIn("细微差别", body)
        self.assertIn("大学英语六级", body)
        self.assertIn("不要反义词", body)

    def test_missing_meaning_is_stated_not_blank(self):
        body = build_messages("zyzzyva", "", MODE_SENTENCE)[1]["content"]
        self.assertIn("没有这个词的中文释义", body)

    def test_prompt_never_includes_screenshots(self):
        # 同 chat.py 的红线：请求体里只有文字，没有图片字段。
        messages = build_messages("abandon", "放弃", MODE_SENTENCE)
        joined = " ".join(m["content"] for m in messages)
        for forbidden in ("image_url", "base64", "screenshot", "data:image"):
            self.assertNotIn(forbidden, joined)

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            build_messages("abandon", "放弃", "translate")
        with self.assertRaises(ValueError):
            build_messages("", "放弃", MODE_SENTENCE)


class StateMachineTests(unittest.TestCase):
    def test_unconfigured_never_starts_a_worker(self):
        h = Harness(FakeConfig(key=""))
        started = h.service.request("abandon", "放弃", MODE_SENTENCE)
        self.assertFalse(started)
        self.assertEqual(h.state["state"], "error")
        self.assertEqual(h.state["code"], "not_configured")
        self.assertIn("API Key", h.state["error"])
        self.assertEqual(h.created, [])              # 关键：一个线程都没起

    def test_missing_model_name_is_named(self):
        h = Harness(FakeConfig(model=""))
        h.service.request("abandon", "放弃", MODE_SYNONYM)
        self.assertEqual(h.state["code"], "not_configured")
        self.assertIn("模型名", h.state["error"])

    def test_success_fills_state_and_caches(self):
        h = Harness()
        self.assertTrue(h.service.request("abandon", "放弃", MODE_SENTENCE))
        self.assertEqual(h.state["state"], "loading")
        self.assertEqual(h.state["modeLabel"], "造句")
        self.assertEqual(len(h.created), 1)

        worker = h.created[0]
        self.assertTrue(worker.started)
        self.assertIn("abandon", worker.messages[1]["content"])
        worker.finish(True, {"text": "1. He abandoned the plan.\n译：他放弃了这个计划。",
                             "elapsed": 1.2})

        self.assertEqual(h.state["state"], "done")
        self.assertIn("abandoned", h.state["text"])
        self.assertEqual(h.state["error"], "")

        # 同一个词同一种问法：命中缓存，**不再发请求**
        before = len(h.created)
        h.service.reset()
        self.assertEqual(h.state["state"], "idle")
        self.assertTrue(h.service.request("abandon", "放弃", MODE_SENTENCE))
        self.assertEqual(len(h.created), before)
        self.assertEqual(h.state["state"], "done")
        self.assertIn("abandoned", h.state["text"])

    def test_cache_is_per_mode(self):
        h = Harness()
        h.service.request("abandon", "放弃", MODE_SENTENCE)
        h.created[0].finish(True, {"text": "sentence-only", "elapsed": 0.4})
        h.service.request("abandon", "放弃", MODE_SYNONYM)
        self.assertEqual(h.state["state"], "loading")
        self.assertEqual(len(h.created), 2)
        h.created[1].finish(True, {"text": "give up（v.）— 更口语", "elapsed": 0.5})
        self.assertIn("give up", h.state["text"])

    def test_case_insensitive_cache_key(self):
        h = Harness()
        h.service.request("Abandon", "放弃", MODE_SENTENCE)
        h.created[0].finish(True, {"text": "cached", "elapsed": 0.1})
        h.service.reset()
        h.service.request("abandon", "放弃", MODE_SENTENCE)
        self.assertEqual(len(h.created), 1)          # 只发过一次
        self.assertEqual(h.state["text"], "cached")

    def test_stale_result_cannot_overwrite_new_card(self):
        h = Harness()
        h.service.request("first", "第一个", MODE_SENTENCE)
        first = h.created[0]
        # 卡片换词：新的请求作废旧的结果
        h.service.request("second", "第二个", MODE_SENTENCE)
        second = h.created[-1]
        first.finish(True, {"text": "STALE", "elapsed": 0.1})
        self.assertEqual(h.state["state"], "loading")
        self.assertEqual(h.state["word"], "second")
        second.finish(True, {"text": "FRESH", "elapsed": 0.2})
        self.assertEqual(h.state["text"], "FRESH")

    def test_reset_discards_in_flight_and_cancels(self):
        h = Harness()
        h.service.request("abandon", "放弃", MODE_SENTENCE)
        worker = h.created[0]
        h.service.reset()
        self.assertTrue(worker.cancelled)
        self.assertEqual(h.state["state"], "idle")
        worker.finish(True, {"text": "迟到的结果", "elapsed": 0.1})
        self.assertEqual(h.state["state"], "idle")   # 不会被迟到结果点亮

    def test_error_payload_is_shown_verbatim(self):
        h = Harness()
        h.service.request("abandon", "放弃", MODE_SENTENCE)
        h.created[0].finish(False, {"code": "auth",
                                    "message": "API Key 无效或未通过验证（401）。",
                                    "elapsed": 0.3})
        self.assertEqual(h.state["state"], "error")
        self.assertEqual(h.state["code"], "auth")
        self.assertIn("401", h.state["error"])

    def test_empty_reply_is_an_error_not_a_blank_box(self):
        h = Harness()
        h.service.request("abandon", "放弃", MODE_SENTENCE)
        h.created[0].finish(True, {"text": "   ", "elapsed": 0.2})
        self.assertEqual(h.state["state"], "error")
        self.assertEqual(h.state["code"], "empty_reply")

    def test_long_reply_is_truncated(self):
        h = Harness()
        h.service.request("abandon", "放弃", MODE_SENTENCE)
        h.created[0].finish(True, {"text": "x" * 4000, "elapsed": 0.2})
        self.assertEqual(h.state["state"], "done")
        self.assertTrue(h.state["text"].endswith("…"))
        self.assertLess(len(h.state["text"]), 1300)

    def test_duplicate_click_while_loading_is_ignored(self):
        h = Harness()
        h.service.request("abandon", "放弃", MODE_SENTENCE)
        self.assertFalse(h.service.request("abandon", "放弃", MODE_SENTENCE))
        self.assertEqual(len(h.created), 1)

    def test_unknown_mode_request_is_ignored(self):
        h = Harness()
        self.assertFalse(h.service.request("abandon", "放弃", "translate"))
        self.assertEqual(h.state["state"], "idle")
        self.assertEqual(h.created, [])

    def test_cache_is_bounded(self):
        h = Harness()
        for i in range(MAX_CACHE + 5):
            h.service.request("word%d" % i, "词", MODE_SENTENCE)
            h.created[-1].finish(True, {"text": "t%d" % i, "elapsed": 0.1})
        self.assertLessEqual(len(h.service._cache), MAX_CACHE)
        self.assertEqual(len(h.service._cache_order), len(h.service._cache))


if __name__ == "__main__":
    unittest.main(verbosity=2)
