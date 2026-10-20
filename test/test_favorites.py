# -*- coding: utf-8 -*-
"""收藏夹分类统计（任务书 §2.2）。

要钉住的四条：

1. **一词可属多分类，但底层只存一份** —— 同一个收藏词命中四级、六级、雅思，
   三个分类各 +1，但「未分类」不加；
2. **分母是真实词库总量**，不是收藏数、更不是硬编码常量；
3. **词库不可用就显示「—」**，绝不拿 0 冒充总数；
4. **兜底不丢词** —— 只带高考/中考/考研标签的词进「未分类」，
   老的收藏记录（没存 tags）要回查词典补齐，而不是一律「未分类」。

运行：  python test/test_favorites.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import launcher_qml
from lexicon import FAVORITE_CATEGORIES, OTHER_CATEGORY


class FakeTags:
    def __init__(self, counts=None, available=True):
        self.counts = dict(counts or {})
        self.available = available


class FakeIndustry:
    def __init__(self, entry_count=0, available=True):
        self.entry_count = entry_count
        self.available = available


class FakeLexicon:
    def __init__(self, counts=None, industry=None, dictionary=None, tags=True):
        self.tags = FakeTags(counts, available=tags)
        self.industry = industry
        self.dictionary = dict(dictionary or {})

    def tags_of(self, word):
        return list(self.dictionary.get(word, []))


class Item:
    def __init__(self, word, tags=None):
        self.word = word
        self.tags = list(tags) if tags is not None else []


COUNTS = {"cet4": 3849, "cet6": 5407, "ielts": 5040, "toefl": 6974}


def _rows(items, lexicon, cache=None):
    return {row["id"]: row for row in
            launcher_qml.favorite_rows(items, lexicon, cache)}


class FavoriteRowsTests(unittest.TestCase):
    def test_six_rows_in_order(self):
        rows = launcher_qml.favorite_rows([], FakeLexicon(COUNTS))
        self.assertEqual([row["id"] for row in rows],
                         [key for key, _label in FAVORITE_CATEGORIES]
                         + [OTHER_CATEGORY[0]])

    def test_multi_category_word_counted_once_per_category(self):
        lexicon = FakeLexicon(COUNTS,
                              FakeIndustry(307),
                              {"apple": ["cet4", "cet6", "ielts"]})
        rows = _rows([Item("apple", ["cet4", "cet6", "ielts"])], lexicon)
        self.assertEqual(rows["cet4"]["count"], 1)
        self.assertEqual(rows["cet6"]["count"], 1)
        self.assertEqual(rows["ielts"]["count"], 1)
        self.assertEqual(rows["toefl"]["count"], 0)
        self.assertEqual(rows["industry"]["count"], 0)
        self.assertEqual(rows[OTHER_CATEGORY[0]]["count"], 0)

    def test_denominator_comes_from_lexicon(self):
        lexicon = FakeLexicon(COUNTS, FakeIndustry(307))
        rows = _rows([Item("apple", ["cet4"])], lexicon)
        self.assertEqual(rows["cet4"]["total"], 3849)
        self.assertEqual(rows["cet4"]["display"], "1/3849")
        self.assertEqual(rows["industry"]["total"], 307)
        self.assertEqual(rows["industry"]["display"], "0/307")

    def test_missing_lexicon_shows_dash_not_zero(self):
        lexicon = FakeLexicon(None, FakeIndustry(0, available=False), tags=False)
        rows = _rows([Item("apple", ["cet4"])], lexicon)
        self.assertFalse(rows["cet4"]["known"])
        self.assertEqual(rows["cet4"]["display"], "1/—")
        self.assertFalse(rows["industry"]["known"])

    def test_zero_total_is_treated_as_unknown(self):
        """总数为 0 时按「不可用」处理 —— 「3/0」是坏数据，不是 300% 收藏。"""
        lexicon = FakeLexicon({"cet4": 0})
        rows = _rows([Item("apple", ["cet4"])], lexicon)
        self.assertFalse(rows["cet4"]["known"])
        self.assertEqual(rows["cet4"]["display"], "1/—")

    def test_unclassified_bucket_only_counts(self):
        items = [Item("a", ["gk"]), Item("b", ["zk"]), Item("c", ["cet4"])]
        rows = _rows(items, FakeLexicon(COUNTS))
        other = rows[OTHER_CATEGORY[0]]
        self.assertEqual(other["count"], 2)
        # 「未分类」没有外部词库，不显示分母（4/4 会被读成「都收藏了」）
        self.assertEqual(other["display"], "2")
        self.assertFalse(other["known"])

    def test_legacy_item_without_tags_falls_back_to_dictionary(self):
        lexicon = FakeLexicon(COUNTS, dictionary={"legacy": ["toefl"]})
        rows = _rows([Item("legacy", [])], lexicon)
        self.assertEqual(rows["toefl"]["count"], 1)
        self.assertEqual(rows[OTHER_CATEGORY[0]]["count"], 0)

    def test_dictionary_lookup_failure_still_degrades(self):
        class Broken(FakeLexicon):
            def tags_of(self, word):
                raise RuntimeError("db closed")

        rows = _rows([Item("x", [])], Broken(COUNTS))
        self.assertEqual(rows[OTHER_CATEGORY[0]]["count"], 1)   # 不炸，进兜底

    def test_cache_is_used_and_populated(self):
        cache = {}
        lexicon = FakeLexicon(COUNTS)
        launcher_qml.favorite_rows([], lexicon, cache)
        self.assertEqual(cache.get("cet4"), 3849)
        lexicon.tags.counts["cet4"] = 1          # 改了也不该影响已缓存的分母
        rows = _rows([], lexicon, cache)
        self.assertEqual(rows["cet4"]["total"], 3849)

    def test_empty_book(self):
        rows = _rows([], FakeLexicon(COUNTS, FakeIndustry(307)))
        self.assertTrue(all(row["count"] == 0 for row in rows.values()))
        self.assertEqual(rows["cet4"]["display"], "0/3849")


if __name__ == "__main__":
    unittest.main(verbosity=2)
