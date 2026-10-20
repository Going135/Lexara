# -*- coding: utf-8 -*-
"""复习会话 + 1/3/7/14 调度回归。

这一组断言盯的是「新的 QML 复习流程有没有破坏老东西」：
- 自评必须真的调 ``Wordbook.grade()``，进而真的改 due_at / stage / correct / wrong；
- 间隔必须是 1 → 3 → 7 → 14 天，答错退回 1 天；
- 到期词必须排在队列前面；
- 揭示答案（reveal）不能产生任何副作用。
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from review_session import ReviewSession, due_overview
from wordbook import STAGES, Wordbook

DAY = 86400.0


def _seed(manager, count=4):
    path = os.path.join(manager, "book.json")
    book = Wordbook(path)
    for i in range(count):
        book.add({"word": "w%d" % i, "phonetic": "/p/", "meaning": "义 %d" % i,
                  "level": "CET4", "tags": ["四级"]})
    return book


def _requeue(manager):
    """从磁盘重读，验证写盘真的发生了。"""
    return Wordbook(os.path.join(manager, "book.json"))


class ReviewFlowTests(unittest.TestCase):
    def test_reveal_has_no_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 4)
            before = [(i.stage, i.due_at, i.correct, i.wrong) for i in book.items]
            s = ReviewSession(book)
            summary = s.start()
            self.assertEqual(summary["total"], 4)
            self.assertFalse(s.revealed)
            self.assertTrue(s.reveal()["revealed"])
            self.assertTrue(s.revealed)
            after = [(i.stage, i.due_at, i.correct, i.wrong) for i in book.items]
            self.assertEqual(before, after, "揭示答案不得改动任何复习数据")

    def test_card_hides_meaning_until_grade_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 3)
            s = ReviewSession(book)
            s.start()
            card = s.card()
            self.assertEqual(card["index"], 1)
            self.assertEqual(card["total"], 3)
            self.assertTrue(card["meaning"])          # 数据是有的
            self.assertFalse(s.revealed)              # 但 UI 侧要按 revealed 决定显不显示
            self.assertTrue(s.reveal()["revealed"])

    def test_correct_uses_existing_stage_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 1)
            s = ReviewSession(book)
            s.start()
            word = s.current_word()
            now = time.time()
            # 连答 4 次正确 → 1 / 3 / 7 / 14 天
            for expected_interval in (1, 3, 7, 14):
                s.grade(True)
                item = book.get(word)
                self.assertEqual(item.stage,
                                 STAGES.index(expected_interval),
                                 "stage 应对齐 1/3/7/14 档")
                self.assertAlmostEqual(item.due_at - now,
                                       expected_interval * DAY, delta=5)
                now = time.time()
                s.start()                             # 重开一轮继续练同一个词

    def test_wrong_falls_back_to_tomorrow(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 1)
            s = ReviewSession(book)
            s.start()
            word = s.current_word()
            book.get(word).stage = 3                  # 先推到最后一档
            s.grade(False)
            item = book.get(word)
            self.assertEqual(item.stage, 0, "答错必须退回第 0 档")
            self.assertAlmostEqual(item.due_at - time.time(), DAY, delta=5)
            self.assertEqual(item.wrong, 1)

    def test_grade_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 2)
            s = ReviewSession(book)
            s.start()
            word = s.current_word()
            s.grade(True)
            reread = _requeue(tmp)
            self.assertEqual(reread.get(word).stage, 0)
            self.assertEqual(reread.get(word).correct, 1)
            self.assertGreater(reread.get(word).due_at, time.time())

    def test_grade_and_advance_walks_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 3)
            s = ReviewSession(book)
            s.start()
            seen = []
            for _ in range(3):
                word = s.current_word()
                seen.append(word)
                s.grade_and_advance(True)
            self.assertEqual(len(set(seen)), 3, "每张卡只能被练一次")
            summary = s.summary()
            self.assertTrue(summary["finished"])
            self.assertEqual(summary["answered"], 3)
            self.assertEqual(summary["correct"], 3)

    def test_due_items_come_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 3)
            # w0/w1 到期，w2 排到很久以后
            book.items[0].due_at = time.time() - 10
            book.items[1].due_at = time.time() - 10
            book.items[2].due_at = time.time() + 30 * DAY
            s = ReviewSession(book)
            s.start()
            order = [s.card()["word"]]
            s.step(1)
            order.append(s.card()["word"])
            s.step(1)
            order.append(s.card()["word"])
            self.assertIn("w0", order[:2])
            self.assertIn("w1", order[:2])
            self.assertEqual(order[2], "w2")

    def test_due_only_session_skips_upcoming(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 3)
            book.items[0].due_at = time.time() - 10
            book.items[1].due_at = time.time() + 5 * DAY
            book.items[2].due_at = time.time() + 9 * DAY
            s = ReviewSession(book)
            summary = s.start(include_upcoming=False)
            self.assertEqual(summary["total"], 1)
            self.assertEqual(s.card()["word"], "w0")

    def test_session_limit_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 10)
            s = ReviewSession(book)
            self.assertEqual(s.start(limit=4)["total"], 4)
            self.assertEqual(s.start(limit=None)["total"], 10, "不传上限应保持全量")
            self.assertIsNone(s.limit)

    def test_summary_counts_are_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 4)
            s = ReviewSession(book)
            s.start()
            s.grade_and_advance(True)
            s.grade_and_advance(False)
            summary = s.summary()
            self.assertEqual(summary["answered"], 2)
            self.assertEqual(summary["correct"], 1)
            self.assertEqual(summary["wrong"], 1)
            self.assertEqual(summary["wrongWords"], [s._wrong_words[0]])
            self.assertGreaterEqual(summary["elapsed"], 0)

    def test_retry_wrong_words_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 4)
            s = ReviewSession(book)
            s.start()
            wrong_word = s.current_word()
            s.grade_and_advance(False)
            s.grade_and_advance(True)
            summary = s.start_wrong_only()
            self.assertEqual(summary["total"], 1)
            self.assertEqual(s.card()["word"], wrong_word)

    def test_exit_does_not_touch_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 3)
            s = ReviewSession(book)
            s.start()
            s.reveal()
            s.exit_session()
            self.assertFalse(s.running)
            self.assertEqual(s.card(), {})
            reread = _requeue(tmp)
            self.assertTrue(all(i.stage == -1 for i in reread.items))

    def test_empty_wordbook_is_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Wordbook(os.path.join(tmp, "book.json"))
            s = ReviewSession(book)
            summary = s.start()
            self.assertTrue(summary["empty"])
            self.assertEqual(s.card(), {})
            overview = due_overview(book)
            self.assertTrue(overview["empty"])
            self.assertEqual(overview["total"], 0)
            self.assertEqual(overview["due"], 0)

    def test_overview_reports_real_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = _seed(tmp, 3)
            book.items[0].due_at = time.time() - 1
            book.items[1].due_at = time.time() - 1
            book.items[2].due_at = time.time() + 3 * DAY
            overview = due_overview(book)
            self.assertEqual(overview["total"], 3)
            self.assertEqual(overview["due"], 2)
            self.assertEqual(overview["reviewedToday"], 0)
            self.assertTrue(overview["nextDueLabel"])
            # 练一个之后，今天已复习数应变成 1
            ReviewSession(book).start()
            s = ReviewSession(book)
            s.start()
            s.grade(True)
            self.assertEqual(due_overview(book)["reviewedToday"], 1)

    def test_missing_meaning_uses_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Wordbook(os.path.join(tmp, "book.json"))
            book.add({"word": "zzz"})
            s = ReviewSession(book)
            s.start()
            card = s.card()
            self.assertFalse(card["hasMeaning"])
            self.assertIn("暂无", card["meaning"])


if __name__ == '__main__':
    unittest.main()
