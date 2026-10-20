# -*- coding: utf-8 -*-
"""学习日历：两种天数、三色等级、成就只发一次（任务书 §7）。

这些断言直接对应 §7.5 的验收项：

- **打开天数 ≠ 学习天数**：只启动不学习，`openDays` 涨、`checked` 不涨；
- **同日取最强**：同一天既有扫描又有复习，格子是深绿（study）；
- **未来不算**：`future` 标记存在且不计入 `greenDays`；
- **里程碑只发一次**：重复 `claim_new()` 不重复入账；
- **崩溃可恢复**：`claim_new()` 后没来得及 `mark_seen()`，下次仍能补弹；
- **全绿有最小跨度**：只打卡 1 天不许「全绿」。

运行：  python test/test_activity.py
"""

import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import activity


class FakeBook:
    """只实现 activity 会读的那几个字段（真实实现见 wordbook.Wordbook）。"""

    def __init__(self, open_dates=(), scans=(), reviews=(), asks=()):
        self.open_dates = list(open_dates)
        self.study_events = [{"date": d} for d in scans]
        self.review_events = [{"date": d} for d in reviews]
        self.ai_events = [{"date": d} for d in asks]
        self.achievements = {}
        self.save_count = 0

    def save(self):
        self.save_count += 1


def _days_back(count, end="2026-10-18"):
    end_date = date.fromisoformat(end)
    return [(end_date - timedelta(days=index)).isoformat()
            for index in range(count)]


TODAY = "2026-10-18"


class LevelTests(unittest.TestCase):
    def test_scan_only_is_light_green(self):
        book = FakeBook(scans=["2026-10-17"])
        levels = activity.learning_map(book)
        self.assertEqual(levels["2026-10-17"], activity.LEVEL_SCAN)

    def test_review_and_ask_are_dark_green(self):
        book = FakeBook(reviews=["2026-10-16"], asks=["2026-10-15"])
        levels = activity.learning_map(book)
        self.assertEqual(levels["2026-10-16"], activity.LEVEL_STUDY)
        self.assertEqual(levels["2026-10-15"], activity.LEVEL_STUDY)

    def test_same_day_strongest_wins(self):
        book = FakeBook(scans=["2026-10-14"], reviews=["2026-10-14"])
        self.assertEqual(activity.learning_map(book)["2026-10-14"],
                         activity.LEVEL_STUDY)

    def test_garbage_dates_are_ignored(self):
        book = FakeBook(scans=["", "不是日期"], reviews=[None])
        self.assertEqual(activity.learning_map(book), {})


class TwoCountersTests(unittest.TestCase):
    def test_open_days_and_checked_days_are_separate(self):
        book = FakeBook(open_dates=["2026-10-18", "2026-10-17", "2026-10-18"])
        self.assertEqual(activity.open_days(book), 2)      # 去重
        self.assertEqual(activity.checked_days(book), 0)   # 没学习就不算打卡

    def test_checked_days_dedupe(self):
        book = FakeBook(scans=["2026-10-18", "2026-10-18"],
                        reviews=["2026-10-18"])
        self.assertEqual(activity.checked_days(book), 1)
        self.assertEqual(activity.open_days(book), 0)

    def test_summary_counts_match_cells(self):
        book = FakeBook(scans=["2026-10-18"], reviews=["2026-10-17"])
        info = activity.summary(book, today=TODAY)
        self.assertEqual(info["checked"], 2)
        self.assertEqual(info["scanDays"], 1)
        self.assertEqual(info["studyDays"], 1)
        self.assertEqual(info["greenDays"], 2)
        self.assertEqual(info["rangeEnd"], TODAY)
        self.assertEqual(info["firstRecord"], "2026-10-17")


class CalendarTests(unittest.TestCase):
    def test_window_is_whole_year_left_to_right(self):
        """日历是**自然年**、周对齐的一整块（2026-10-19 起）。

        用户口径：「1-12 月从左到右」。所以窗口不是滚动 371 天，而是
        「1/1 所在周的周日起 → 12/31 所在周的周六止」，两端补位格标
        `outOfYear`，月份标签必须是 1..12 递增（这就是「从左到右」）。
        """
        today = date.fromisoformat(TODAY)
        start, end = activity.year_span(TODAY)
        self.assertEqual(start, date(today.year, 1, 1)
                         - timedelta(days=(date(today.year, 1, 1).weekday() + 1) % 7))
        self.assertEqual(end, date(today.year, 12, 31)
                         + timedelta(days=(6 - (date(today.year, 12, 31).weekday() + 1) % 7)))
        # 周对齐 ⇒ 一定是整列（天数是 7 的倍数）
        self.assertEqual((end - start).days % 7, 6)

        cells = activity.calendar_cells(FakeBook(), today=TODAY)
        self.assertEqual(len(cells), (end - start).days + 1)
        self.assertEqual(cells[0]["date"], start.isoformat())
        self.assertEqual(cells[-1]["date"], end.isoformat())
        # 今年 1/1 与 12/31 都在窗口里，且都不算「年外」
        by_date = {cell["date"]: cell for cell in cells}
        self.assertFalse(by_date["%d-01-01" % today.year]["outOfYear"])
        self.assertFalse(by_date["%d-12-31" % today.year]["outOfYear"])
        # 两端补位格（去年 12 月末 / 明年 1 月初）必须被标出来
        self.assertTrue(by_date[start.isoformat()]["outOfYear"])
        # 月份标签从左到右 1..12 递增
        months = ["%d月" % int(cell["date"][5:7]) for cell in cells
                  if cell["date"].endswith("-01") and not cell["outOfYear"]]
        self.assertEqual(months, ["%d月" % n for n in range(1, 13)])

    def test_future_days_are_flagged_and_not_counted(self):
        # 自然年窗口到 12/31 才结束，所以「今天」之前的年份尾巴全在窗口里，
        # 它们必须是 future=True（画成暗色）且不计入绿天数。
        cells = activity.calendar_cells(FakeBook(scans=["2026-10-18"]),
                                        today="2026-10-17")
        self.assertTrue(any(cell["future"] for cell in cells))
        self.assertFalse(any(cell["future"]
                             for cell in cells if cell["date"] <= "2026-10-17"))
        self.assertTrue(any(cell["date"] == "2026-12-31" and cell["future"]
                            for cell in cells))
        # 数据里出现「未来日期」（改过系统时钟 / 手动改文件）时不能计入绿天数
        info = activity.summary(FakeBook(scans=["2026-10-18"]), today="2026-10-17")
        self.assertEqual(info["greenDays"], 0)
        self.assertEqual(info["checked"], 1)   # checked 是去重日数，与窗口无关


class AchievementTests(unittest.TestCase):
    def test_milestones_fire_once(self):
        book = FakeBook(open_dates=_days_back(7, TODAY))
        self.assertEqual(activity.earned_ids(book, TODAY), ["open_7"])
        self.assertEqual(activity.claim_new(book, TODAY), ["open_7"])
        self.assertEqual(activity.claim_new(book, TODAY), [])   # 不重复入账
        self.assertEqual([row["id"] for row in activity.pending(book)], ["open_7"])
        activity.mark_seen(book, ["open_7"])
        self.assertEqual(activity.pending(book), [])
        self.assertEqual(activity.claim_new(book, TODAY), [])

    def test_30_and_100_days_are_separate(self):
        book = FakeBook(open_dates=_days_back(30, TODAY))
        self.assertEqual(activity.earned_ids(book, TODAY), ["open_7", "open_30"])
        book2 = FakeBook(open_dates=_days_back(100, TODAY))
        self.assertEqual(activity.earned_ids(book2, TODAY),
                         ["open_7", "open_30", "open_100"])

    def test_unseen_survives_restart(self):
        """claim 之后进程被杀（没 mark_seen）→ 新实例读同一份 dict 仍待展示。"""
        book = FakeBook(open_dates=_days_back(7, TODAY))
        activity.claim_new(book, TODAY)
        reloaded = FakeBook()
        reloaded.achievements = book.achievements          # 等价于从磁盘重读
        rows = activity.pending(reloaded)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["seen"])
        payload = activity.pending_payload(reloaded)
        self.assertEqual(payload["name"], activity.ACHIEVEMENTS["open_7"]["name"])
        self.assertEqual(payload["total"], 1)

    def test_payload_empty_when_nothing_pending(self):
        self.assertEqual(activity.pending_payload(FakeBook()), {})

    def test_all_green_needs_consecutive_days(self):
        days = _days_back(8, TODAY)
        book = FakeBook(scans=[days[0]], reviews=days[1:])
        self.assertTrue(activity.range_is_all_green(book, today=TODAY))
        self.assertIn("all_green", activity.earned_ids(book, TODAY))

    def test_all_green_breaks_on_gap(self):
        days = _days_back(8, TODAY)
        book = FakeBook(scans=days[:3] + days[4:])          # 少一天
        self.assertFalse(activity.range_is_all_green(book, today=TODAY))
        self.assertNotIn("all_green", activity.earned_ids(book, TODAY))

    def test_all_green_needs_min_span(self):
        """只打卡 1 天就「全绿」是假成就（GREEN_MIN_SPAN 兜底）。"""
        book = FakeBook(scans=[TODAY])
        self.assertFalse(activity.range_is_all_green(book, today=TODAY))

    def test_all_green_ignores_days_before_first_record(self):
        """首次使用之前的日子本来就没活动，不能算作「不绿」。"""
        book = FakeBook(scans=_days_back(7, TODAY))
        self.assertTrue(activity.range_is_all_green(book, today=TODAY))


if __name__ == "__main__":
    unittest.main(verbosity=2)
