# -*- coding: utf-8 -*-
"""单词本导出（txt / csv / json 三个出口）的纯逻辑测试。

盯的是三件会**悄悄坏**的事：
1. txt/csv 丢了 BOM —— 中文 Windows 的 Excel/记事本打开就是乱码，
   「直接拿走」变成「拿走了但没法看」，磁盘上的字节才算数，不看返回值；
2. 释义里的逗号/引号没走 csv 转义 —— 表格列错位；
3. 落盘不是原子的 —— 导出坏一半比不导出更糟，所以断言 .tmp 不残留。

词库 schema 一个字节没改，json 出口只是把它原样读出来再包一层元信息。
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import word_export
from wordbook import Item


class FakeLexicon:
    """只用来验证「item 没 tags 时回退查词库」这条路径。"""

    def __init__(self, mapping):
        self._mapping = mapping

    def tags_of(self, word):
        return list(self._mapping.get(word, []))


def _items():
    return [
        Item(word="algorithm", phonetic="/ˈælɡərɪðəm/", meaning="n. 算法",
             tags=["cet4"]),
        Item(word="silicon", phonetic="/ˈsɪlɪkən/",
             meaning="n. 硅；硅谷", tags=["industry", "cet6"]),
        Item(word="serendipity", meaning="", tags=[]),
    ]


class TxtRenderTest(unittest.TestCase):
    def test_sections_follow_sidebar_order(self):
        text = word_export.render_txt(_items())
        pos = {label: text.find("── %s（" % label) for label in
               ("四级", "六级", "工业英语", "未分类")}
        self.assertEqual(list(pos.values()), sorted(pos.values()))
        self.assertIn("algorithm", text[text.index("── 四级"):text.index("── 六级")])

    def test_word_line_and_empty_meaning(self):
        text = word_export.render_txt(_items())
        self.assertIn("algorithm /ˈælɡərɪðəm/  n. 算法", text)
        self.assertIn("serendipity  （无释义）", text)

    def test_multi_tag_word_enters_every_section(self):
        text = word_export.render_txt(_items())
        self.assertIn("silicon", text[text.index("── 六级"):text.index("── 工业英语")])
        self.assertIn("silicon", text[text.index("── 工业英语"):])

    def test_study_mode_hides_meaning(self):
        text = word_export.render_txt(_items(), study=True)
        self.assertNotIn("n. 算法", text)
        self.assertNotIn("n. 硅", text)
        self.assertIn("algorithm /ˈælɡərɪðəm/  ________________________", text)

    def test_empty_book_gives_note_not_crash(self):
        text = word_export.render_txt([])
        self.assertIn("还没有收藏任何单词", text)
        self.assertIn("共 0 词", text)

    def test_lexicon_fallback_when_tags_missing(self):
        lex = FakeLexicon({"serendipity": ["cet4"]})
        text = word_export.render_txt(_items(), lexicon=lex)
        self.assertIn("serendipity", text[text.index("── 四级"):text.index("── 六级")])


class CsvRenderTest(unittest.TestCase):
    def _rows(self, items):
        text = word_export.render_csv(items)
        return list(csv.reader(io.StringIO(text)))

    def test_header_and_columns(self):
        rows = self._rows(_items())
        self.assertEqual(rows[0], ["word", "phonetic", "meaning", "categories",
                                   "level", "stage", "due_date", "correct",
                                   "wrong", "added_date"])
        self.assertEqual(len(rows), 4)

    def test_categories_join_labels(self):
        rows = self._rows(_items())
        row = {r[0]: r for r in rows[1:]}["silicon"]
        self.assertEqual(row[3], "六级|工业英语")
        self.assertEqual({r[0]: r for r in rows[1:]}["serendipity"][3], "未分类")

    def test_meaning_with_comma_quote_newline_survives(self):
        nasty = Item(word="chunder", meaning="v. 呕吐, 晕船\n俗称 \" seasickness \"",
                     tags=["cet4"])
        rows = self._rows([nasty])
        self.assertEqual(rows[1][2], 'v. 呕吐, 晕船 俗称 " seasickness "')
        self.assertEqual(len(rows[1]), 10)

    def test_crlf_line_endings(self):
        self.assertIn("\r\n", word_export.render_csv(_items()))


class JsonRenderTest(unittest.TestCase):
    def test_shape_matches_wordbook_plus_meta(self):
        payload = json.loads(word_export.render_json(_items()))
        self.assertEqual(payload["schemaVersion"], 3)
        self.assertEqual(len(payload["items"]), 3)
        meta = payload["_lexaraMeta"]
        self.assertEqual(meta["kind"], "lexara-word-export")
        self.assertEqual(meta["count"], 3)

    def test_items_roundtrip_into_wordbook(self):
        # wordbook.load 用 Item(**已知字段) 还原，这里走同一条路
        fields = set(Item.__dataclass_fields__)
        payload = json.loads(word_export.render_json(_items()))
        restored = [Item(**{k: v for k, v in d.items() if k in fields})
                    for d in payload["items"]]
        self.assertEqual(restored[0].word, "algorithm")
        self.assertEqual(restored[1].tags, ["industry", "cet6"])

    def test_chinese_not_escaped(self):
        text = word_export.render_json(_items())
        self.assertIn("算法", text)
        self.assertNotIn("\\u7b97", text)


class ExportFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="lexara-export-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _path(self, name):
        return os.path.join(self.dir, name)

    def test_txt_and_csv_carry_bom_on_disk(self):
        for fmt in ("txt", "csv"):
            result = word_export.export(_items(), fmt, self._path("book." + fmt))
            self.assertTrue(result["ok"], result["message"])
            with open(result["path"], "rb") as handle:
                self.assertEqual(handle.read(3), b"\xef\xbb\xbf", fmt)

    def test_json_has_no_bom(self):
        result = word_export.export(_items(), "json", self._path("book.json"))
        with open(result["path"], "rb") as handle:
            self.assertNotEqual(handle.read(3), b"\xef\xbb\xbf")

    def test_extension_filled_only_when_absent(self):
        self.assertEqual(word_export.export(_items(), "csv",
                                            self._path("noext"))["path"],
                         self._path("noext.csv"))
        self.assertEqual(word_export.export(_items(), "csv",
                                            self._path("mine.txt"))["path"],
                         self._path("mine.txt"))

    def test_no_tmp_residue_and_nested_dir_created(self):
        target = self._path("deep/nested/book.txt")
        result = word_export.export(_items(), "txt", target)
        self.assertTrue(result["ok"])
        self.assertTrue(os.path.isfile(result["path"]))
        leftovers = [n for n in os.listdir(os.path.dirname(result["path"]))
                     if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_empty_book_and_unknown_format_rejected(self):
        bad = word_export.export([], "txt", self._path("empty.txt"))
        self.assertFalse(bad["ok"])
        self.assertFalse(os.path.exists(self._path("empty.txt")))
        bad = word_export.export(_items(), "apkg", self._path("x.apkg"))
        self.assertFalse(bad["ok"])

    def test_default_name_carries_format_suffix(self):
        for fmt in word_export.FORMATS:
            self.assertTrue(word_export.default_name(fmt).endswith("." + fmt))


if __name__ == "__main__":
    unittest.main()
