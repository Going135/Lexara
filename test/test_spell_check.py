# -*- coding: utf-8 -*-
"""默写判分 `src/spell_check.py` 的单元测试。

纯函数，不起 Qt、不连网、不读词库。

**这里守的是判定口径，不是实现细节**：拼写正确但大小写 / 首尾标点 / 全角
字母 / 连字符不同时，必须判 `correct`。把「用户写对了」判成错，比漏判更伤人
—— 用户会以为自己一直拼错。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

import spell_check as sc          # noqa: E402


class NormalizeCase(unittest.TestCase):

    def test_unify(self):
        self.assertEqual(sc.normalize("  Academy. "), "academy")
        self.assertEqual(sc.normalize("ＡＣＡＤＥＭＹ"), "academy",
                         "全角字母要当同一个词")
        self.assertEqual(sc.normalize("caf\u00e9"), "café",
                         "带音标的词不能被拆掉字母")

    def test_only_edge_punctuation_is_stripped(self):
        # 中间的连字符是拼写的一部分，剥掉会让 wellknown 冒充 well-known
        self.assertEqual(sc.normalize("well-known"), "well-known")
        self.assertEqual(sc.normalize("(well-known)"), "well-known")


class CheckCase(unittest.TestCase):

    def test_exact(self):
        r = sc.check("academy", "academy")
        self.assertEqual(r["verdict"], "correct")
        self.assertEqual(r["hint"], "")
        self.assertEqual(r["answer"], "academy")

    def test_case_and_whitespace_are_not_errors(self):
        for typed in ("Academy", "  academy  ", "academy.", "ACADEMY"):
            with self.subTest(typed=typed):
                self.assertEqual(sc.check(typed, "academy")["verdict"],
                                 "correct")

    def test_hyphen_dropped_is_correct_but_warns(self):
        r = sc.check("wellknown", "well-known")
        self.assertEqual(r["verdict"], "correct",
                         "少打个连字符不算拼错")
        self.assertIn("well-known", r["hint"],
                      "要告诉用户规范写法，否则他永远不知道有这个连字符")

    def test_empty(self):
        for typed in ("", "   ", "...", "\u2014\u2014"):
            with self.subTest(typed=typed):
                self.assertEqual(sc.check(typed, "academy")["verdict"],
                                 "empty")

    def test_one_letter_off(self):
        r = sc.check("acadmy", "academy")
        self.assertEqual(r["verdict"], "wrong")
        self.assertEqual(r["distance"], 1)
        self.assertIn("一个字母", r["hint"])

    def test_far_off(self):
        r = sc.check("xyz", "academy")
        self.assertEqual(r["verdict"], "wrong")
        self.assertGreater(r["distance"], 3)

    def test_answer_is_echoed_verbatim(self):
        # 界面要直接显示「正确拼写：xxx」，大小写不能被判分逻辑抹掉
        r = sc.check("nope", "Wi-Fi")
        self.assertEqual(r["answer"], "Wi-Fi")


class EmptyStateCase(unittest.TestCase):

    def test_has_every_key_qml_reads(self):
        keys = {"open", "verdict", "answer", "typed", "distance", "hint",
                "attempts"}
        self.assertTrue(keys <= set(sc.empty_state()),
                        "少一个键，QML 就会读到 undefined 并报警告")

    def test_flags(self):
        self.assertFalse(sc.empty_state()["open"])
        s = sc.empty_state(open=True, answer="academy")
        self.assertTrue(s["open"])
        self.assertEqual(s["answer"], "academy")
        self.assertEqual(s["verdict"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
