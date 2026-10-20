# -*- coding: utf-8 -*-
"""AI 配置面板的底座：``ai/config.py`` 的 URL 校验 + 密钥安全存储。

任务书 5.2 的三条红线在这里被逐条钉住：
- **公网 HTTP 一律拒绝**（不要把密钥发到明文端点），只有 loopback 放行；
- **密钥不得进 settings.json**，也不能出现在给 UI 的快照里；
- **加密失败必须如实报错**，不许假装已经加密保存。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ai.config import (AIConfig, AIConfigError, SecretStore,  # noqa: E402
                       mask, resolve_endpoint, validate_endpoint)
from settings_store import Settings  # noqa: E402


def _clear_env():
    for key in ("LEXARA_AI_API_KEY", "LEXARA_AI_URL", "LEXARA_AI_MODEL"):
        os.environ.pop(key, None)


class EndpointTests(unittest.TestCase):
    def test_public_http_rejected(self):
        with self.assertRaises(AIConfigError) as ctx:
            validate_endpoint("http://example.com/v1")
        self.assertEqual(ctx.exception.code, "insecure_url")

    def test_loopback_http_allowed(self):
        for host in ("http://localhost:11434/v1", "http://127.0.0.1:8000"):
            normalized, endpoint = validate_endpoint(host)
            self.assertTrue(normalized.startswith("http://"))
            self.assertTrue(endpoint.endswith("/chat/completions"))

    def test_https_always_ok(self):
        _, endpoint = validate_endpoint("https://api.openai.com/v1")
        self.assertEqual(endpoint, "https://api.openai.com/v1/chat/completions")

    def test_full_endpoint_not_double_suffixed(self):
        # 既有的环境变量默认值就带 /chat/completions，必须向后兼容
        self.assertEqual(resolve_endpoint("https://x.dev/v1/chat/completions"),
                         "https://x.dev/v1/chat/completions")

    def test_empty_and_bad_scheme(self):
        with self.assertRaises(AIConfigError):
            validate_endpoint("")
        with self.assertRaises(AIConfigError):
            validate_endpoint("ftp://host/v1")


class SecretStoreTests(unittest.TestCase):
    @unittest.skipUnless(SecretStore().available, "需要 Windows DPAPI")
    def test_roundtrip_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SecretStore(directory=tmp)
            self.assertFalse(store.has_secret())
            store.write("sk-secret-value")
            self.assertTrue(store.has_secret())
            self.assertEqual(store.read(), "sk-secret-value")

            # 落盘内容必须看不到明文
            with open(store.path, "rb") as handle:
                blob = handle.read()
            self.assertNotIn(b"sk-secret-value", blob)

            store.clear()
            self.assertFalse(store.has_secret())
            self.assertEqual(store.read(), "")

    @unittest.skipUnless(SecretStore().available, "需要 Windows DPAPI")
    def test_corrupt_file_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SecretStore(directory=tmp)
            with open(store.path, "wb") as handle:
                handle.write(b"NOT_THE_MAGIC\x00\x01")
            with self.assertRaises(AIConfigError) as ctx:
                store.read()
            self.assertEqual(ctx.exception.code, "format")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        _clear_env()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.settings = Settings(path=os.path.join(self.tmp, "s.json"))
        self.config = AIConfig(self.settings, SecretStore(directory=self.tmp))

    def tearDown(self):
        self._tmp.cleanup()
        _clear_env()

    def test_not_configured_by_default(self):
        self.assertFalse(self.config.configured())
        self.assertEqual(self.config.source_of_key(), "none")
        self.assertEqual(self.config.api_key(), "")
        self.assertEqual(self.config.key_source_label(), "未配置")

    def test_key_never_lands_in_settings_json(self):
        self.config.update("https://api.example.com/v1", "gpt", "sk-live-key")
        with open(self.settings.path, encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn("sk-live-key", raw)
        self.assertTrue(self.config.configured())

    @unittest.skipUnless(SecretStore().available, "需要 Windows DPAPI")
    def test_snapshot_hides_key(self):
        self.config.update("https://api.example.com/v1", "gpt", "sk-live-key")
        snap = self.config.snapshot()
        values = " ".join(str(v) for v in snap.values())
        self.assertNotIn("sk-live-key", values)
        self.assertTrue(snap["hasKey"])
        self.assertTrue(snap["keyHint"].startswith("●"))
        self.assertTrue(snap["configured"])
        self.assertEqual(snap["endpoint"],
                         "https://api.example.com/v1/chat/completions")

    @unittest.skipUnless(SecretStore().available, "需要 Windows DPAPI")
    def test_clear_disables(self):
        self.config.update("https://api.example.com/v1", "gpt", "sk-live-key")
        self.assertTrue(self.config.configured())
        self.config.clear_key()
        self.assertFalse(self.config.configured())
        self.assertEqual(self.config.source_of_key(), "none")

    def test_insecure_base_url_is_refused_before_anything_is_saved(self):
        with self.assertRaises(AIConfigError):
            self.config.update("http://api.example.com/v1", "gpt", "sk-x")
        self.assertEqual(self.settings.get("ai_base_url", ""), "")
        self.assertFalse(self.config.configured())

    def test_mask(self):
        self.assertEqual(mask(""), "***")
        self.assertEqual(mask("abcd"), "***")
        self.assertNotIn("cdef", mask("abcdefgh"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
