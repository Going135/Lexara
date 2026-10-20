# -*- coding: utf-8 -*-
"""``ocr_registry`` 的行为护栏：**UI 不许编造引擎可用性**。

任务书 6.3：识别引擎的真相归 Qoder（`ocr_adapter` / `ocr_engine`），
启动台只负责问和显示。这个文件用一个**假的后端模块**证明：

- 后端说什么状态，UI 就显示什么状态，`unknown` 不会被美化成 `available`；
- 后端返回形状换了（dict / bool / tuple）也不会被误判成「切换成功」；
- 后端没给钩子时，UI 只用自己能验证的事实兜底，不假装“都可用”。
"""
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import ocr_registry  # noqa: E402
from settings_store import Settings  # noqa: E402


class _Fake:
    """假 `ocr_engine`：只暴露 UI 允许使用的那几个钩子。"""

    def __init__(self, rows=None, set_result=(True, "已切换")):
        self._rows = rows or []
        self._set_result = set_result
        self.probe_calls = 0

    def describe_engines(self):
        return [dict(r) for r in self._rows]

    def current_engine(self):
        for row in self._rows:
            if row.get("state") == "available":
                return row["id"]
        return ""

    def set_engine(self, engine_id):
        for row in self._rows:
            if row["id"] == engine_id and row.get("state") == "available":
                return self._set_result
        return False, "不可用"

    def probe(self, engine_id=None, force=False):
        self.probe_calls += 1


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(path=os.path.join(self._tmp.name, "s.json"))
        self._real_module = ocr_registry._module
        ocr_registry._probe_requested = False

    def tearDown(self):
        ocr_registry._module = self._real_module
        ocr_registry._probe_requested = False
        self._tmp.cleanup()

    def _patch(self, fake):
        ocr_registry._module = lambda: fake

    def test_unknown_state_is_reported_as_unknown(self):
        fake = _Fake([{"id": "rapid", "name": "RapidOCR", "state": "unknown"}])
        self._patch(fake)
        rows = ocr_registry.list_engines()
        self.assertEqual(rows[0]["state"], "unknown")
        self.assertEqual(rows[0]["stateLabel"], "未探测")

    def test_switch_to_unverified_engine_refuses(self):
        # 后端「还没探测过」时，UI 不能把用户点的那一档当成功
        fake = _Fake([{"id": "rapid", "name": "RapidOCR", "state": "unknown"}])
        self._patch(fake)
        result = ocr_registry.switch_engine(self.settings, "rapid")
        self.assertFalse(result["ok"])
        self.assertTrue(result["message"])

    def test_switch_reports_backend_reason(self):
        fake = _Fake([{"id": "paddle", "name": "PaddleOCR", "state": "unavailable",
                       "reason": "未安装 paddleocr"}])
        self._patch(fake)
        result = ocr_registry.switch_engine(self.settings, "paddle")
        self.assertFalse(result["ok"])
        self.assertIn("未安装 paddleocr", result["message"])

    def test_switch_accepts_tuple_and_dict_and_bool(self):
        for result_value, expected in (((True, "ok"), True),
                                       ({"ok": True, "message": "ok"}, True),
                                       (True, True),
                                       ((False, "no"), False),
                                       ({"ok": False}, False),
                                       (False, False),
                                       ("junk", False)):
            fake = _Fake([{"id": "rapid", "name": "RapidOCR",
                           "state": "available"}], set_result=result_value)
            self._patch(fake)
            got = ocr_registry.switch_engine(self.settings, "rapid")["ok"]
            self.assertEqual(got, expected, "后端返回 %r 被误判" % (result_value,))

    def test_switch_persists_only_on_success(self):
        fake = _Fake([{"id": "rapid", "name": "RapidOCR", "state": "available"}])
        self._patch(fake)
        self.assertTrue(ocr_registry.switch_engine(self.settings, "rapid")["ok"])
        self.assertEqual(self.settings.get("ocr_engine"), "rapid")

        failing = _Fake([{"id": "paddle", "name": "PaddleOCR",
                          "state": "unavailable", "reason": "缺依赖"}])
        self._patch(failing)
        self.assertFalse(ocr_registry.switch_engine(self.settings, "paddle")["ok"])
        self.assertEqual(self.settings.get("ocr_engine"), "rapid")

    def test_backend_exception_does_not_fake_availability(self):
        class Boom(_Fake):
            def describe_engines(self):
                raise RuntimeError("boom")

        self._patch(Boom())
        # 后端炸了时 UI 会记一笔日志（这是好事），测试里静音，
        # 免得 traceback 混进 stdout 干扰别的判读。
        logging.disable(logging.ERROR)
        try:
            rows = ocr_registry.list_engines()
        finally:
            logging.disable(logging.NOTSET)
        self.assertTrue(rows)
        self.assertNotIn("available", [r["state"] for r in rows])

    def test_no_backend_hooks_falls_back_to_facts(self):
        # 连识词模块都没加载（打包缺失 / 环境问题）时：只允许报不可用 + 原因，
        # 绝不许为了让界面好看就宣布「可用」。
        ocr_registry._module = lambda: None
        rows = ocr_registry.list_engines()
        ids = [r["id"] for r in rows]
        self.assertIn("rapid", ids)
        self.assertTrue(all(r["state"] == "unavailable" for r in rows))
        self.assertTrue(all(r["reason"] for r in rows))

    def test_probe_requested_once(self):
        fake = _Fake([{"id": "rapid", "name": "RapidOCR", "state": "unknown"}])
        self._patch(fake)
        ocr_registry.list_engines()
        ocr_registry.list_engines()
        self.assertLessEqual(fake.probe_calls, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
