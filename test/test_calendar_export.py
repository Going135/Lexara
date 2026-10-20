# -*- coding: utf-8 -*-
"""导出学习日历 PNG（任务书 §7.4）。

两个必须钉死的行为：

1. **失败绝不返回 ok=True** —— 用户点了「保存图片」，磁盘满 / 没权限时必须
   如实报错，不能弹「已保存」然后什么都没有；
2. **导出物只含日历** —— 这张图是 QPainter 重画的，不是截图，所以不可能带出
   AI 配置、API Key、桌面壁纸或任何其它窗口。

运行：  python test/test_calendar_export.py
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

import activity
import calendar_export


class FakeBook:
    def __init__(self, open_dates=(), scans=(), reviews=()):
        self.open_dates = list(open_dates)
        self.study_events = [{"date": d} for d in scans]
        self.review_events = [{"date": d} for d in reviews]
        self.ai_events = []
        self.achievements = {}

    def save(self):
        pass


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # QPainter 需要 QApplication；只画到 QImage，不建窗口。
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lexara_cal_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_render_has_expected_size(self):
        image = calendar_export.render(FakeBook(scans=["2026-10-18"]),
                                       today="2026-10-18")
        self.assertIsInstance(image, QImage)
        self.assertEqual((image.width(), image.height()),
                         (calendar_export.WIDTH, calendar_export.HEIGHT))

    def test_export_writes_png(self):
        path = os.path.join(self.tmp, "cal.png")
        result = calendar_export.export(FakeBook(scans=["2026-10-18"]), path,
                                        today="2026-10-18")
        self.assertTrue(result["ok"], result.get("message"))
        self.assertTrue(os.path.isfile(path))
        self.assertGreater(os.path.getsize(path), 4096)      # 不是空文件
        # 真的能被读回来
        again = QImage(path)
        self.assertEqual((again.width(), again.height()),
                         (calendar_export.WIDTH, calendar_export.HEIGHT))

    def test_export_appends_missing_extension(self):
        target = os.path.join(self.tmp, "no_ext")
        result = calendar_export.export(FakeBook(), target, today="2026-10-18")
        self.assertTrue(result["ok"], result.get("message"))
        self.assertTrue(os.path.isfile(target + ".png"))

    def test_export_failure_is_honest(self):
        missing = os.path.join(self.tmp, "nope", "deep", "cal.png")
        result = calendar_export.export(FakeBook(), missing, today="2026-10-18")
        self.assertFalse(result["ok"])                       # 关键：不谎报成功
        self.assertTrue(result["message"])

    def test_empty_path_is_rejected(self):
        result = calendar_export.export(FakeBook(), "", today="2026-10-18")
        self.assertFalse(result["ok"])
        self.assertTrue(result["message"])

    def test_export_does_not_contain_settings(self):
        """导出的是重画的日历，文件里不该出现 settings.json 的任何字符串。"""
        path = os.path.join(self.tmp, "cal.png")
        calendar_export.export(FakeBook(scans=["2026-10-18"]), path,
                               today="2026-10-18")
        with open(path, "rb") as handle:
            raw = handle.read()
        for token in (b"api_key", b"deepseek", b"sk-", b"settings"):
            self.assertNotIn(token, raw)


class AggregateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_calendar_numbers_match_activity_module(self):
        """导出图与界面必须同一口径（否则屏幕深绿、图里浅绿）。"""
        book = FakeBook(open_dates=["2026-10-18"],
                        scans=["2026-10-18"],
                        reviews=["2026-10-17"])
        info = activity.summary(book, today="2026-10-18")
        self.assertEqual(info["checked"], 2)
        self.assertEqual(info["greenDays"], 2)
        image = calendar_export.render(book, today="2026-10-18")
        self.assertFalse(image.isNull())


if __name__ == "__main__":
    unittest.main(verbosity=2)
