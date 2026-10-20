# -*- coding: utf-8 -*-
"""音效：文件就位 + 失败不炸 + 「记住了」才响。

这里**故意不真的放声**：测试跑在无人值守的离屏环境里，一跑一串叮叮声没有意义，
也会把「播放成功」这种依赖声卡的事混进断言。真播放交给 `LEXARA_SFX_MUTE`
之外的场景，人工听一次就够。
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
sys.path.insert(0, BASE)

import sfx                                                    # noqa: E402


class SfxFileCase(unittest.TestCase):
    """素材本身：路径能解析、文件真的在、是 mp3。"""

    def test_default_path_exists(self):
        path = sfx.default_path()
        self.assertTrue(os.path.isfile(path), "音效文件不存在：%s" % path)
        self.assertTrue(path.lower().endswith(".mp3"), "期望 mp3，实际 %s" % path)

    def test_missing_file_is_silent(self):
        """文件不存在只能返回 False —— 音效放不出来不该让背单词点不动。"""
        with mock.patch.dict(os.environ, {"LEXARA_SFX": os.path.join(BASE, "无此文件.mp3")}):
            self.assertFalse(sfx.play())

    def test_mute(self):
        with mock.patch.dict(os.environ, {"LEXARA_SFX_MUTE": "1"}):
            self.assertFalse(sfx.play(), "静音开关打开时不该出声")

    def test_env_override(self):
        """`LEXARA_SFX` 能指到别的文件（调试/换音效）。"""
        with mock.patch.dict(os.environ, {"LEXARA_SFX": os.path.join(BASE, "assets", "sfx", "ding.mp3")}):
            self.assertTrue(sfx.default_path().endswith("ding.mp3"))


class NoStallCase(unittest.TestCase):
    """回归：点「记住了」不能卡界面。

    MCI 的 `play` 实测同步阻塞 310~560 ms。以前它写在 QML 槽里 = UI 线程冻结，
    表现就是「播音效时卡一下」。这里把设备假装成慢的（400 ms），断言 `play()`
    本身必须立刻返回——只要有人又把 MCI 调用搬回调用方线程，这两条就红。
    """

    SLOW = 0.4

    def setUp(self):
        # 这个类的 `_handle` 全被换成 sleep，本来就不会出声，所以临时解除静音；
        # 否则 `play()` 会直接返回 False，断言就测不到东西了。
        self._env = mock.patch.dict(os.environ, {"LEXARA_SFX_MUTE": ""})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_play_returns_at_once(self):
        with mock.patch.object(sfx._PLAYER, "_handle",
                               side_effect=lambda kind, path: time.sleep(self.SLOW)):
            start = time.perf_counter()
            ok = sfx.play()
            cost_ms = (time.perf_counter() - start) * 1000
        sfx._PLAYER.wait_idle(5)
        self.assertTrue(ok, "文件在就该受理")
        self.assertLess(cost_ms, 30,
                        "play() 阻塞了 %.0f ms —— 400ms 的 MCI 开销又回到 UI 线程了"
                        % cost_ms)

    def test_prewarm_returns_at_once(self):
        with mock.patch.object(sfx._PLAYER, "_handle",
                               side_effect=lambda kind, path: time.sleep(self.SLOW)):
            start = time.perf_counter()
            ok = sfx.prewarm()
            cost_ms = (time.perf_counter() - start) * 1000
        sfx._PLAYER.wait_idle(5)
        self.assertTrue(ok)
        self.assertLess(cost_ms, 30, "启动预热不能反过来拖慢启动")

    def test_rapid_clicks_do_not_queue_up(self):
        """连点不排长队：后台最多再补一声，不会把 5 声全播完。"""
        seen = []

        def slow(kind, path):
            seen.append(kind)
            time.sleep(self.SLOW)

        with mock.patch.object(sfx._PLAYER, "_handle", side_effect=slow):
            for _ in range(5):
                sfx.play()
            sfx._PLAYER.wait_idle(8)
        self.assertGreaterEqual(len(seen), 1, "至少得响一声")
        self.assertLessEqual(len(seen), 2,
                             "连点 5 次排了 %d 声，应该在播完当前这声后只补一声"
                             % len(seen))


class ReviewGradeSoundCase(unittest.TestCase):
    """接线：只有 correct=True 那一下才响，且只响一次。"""

    def _bridge(self):
        from launcher_qml import LauncherBridge

        class _Review:
            def __init__(self):
                self.grades = []

            def grade_and_advance(self, correct):
                self.grades.append(correct)

            def summary(self):
                return {"finished": False}

        class _Changed:
            def __init__(self):
                self.count = 0

            def emit(self):
                self.count += 1

        stub = mock.Mock(spec=LauncherBridge)
        stub._review = _Review()
        stub._review_stage = "card"
        stub.changed = _Changed()
        return LauncherBridge, stub

    def test_plays_on_correct(self):
        LauncherBridge, stub = self._bridge()
        with mock.patch.object(sfx, "play_ding") as ding:
            LauncherBridge.reviewGrade(stub, True)
        self.assertEqual(ding.call_count, 1, "记住了 → 应该响一次")
        self.assertEqual(stub._review.grades, [True], "评分还是要真的走下去")
        self.assertEqual(stub.changed.count, 1, "界面要刷新")

    def test_quiet_on_wrong(self):
        LauncherBridge, stub = self._bridge()
        with mock.patch.object(sfx, "play_ding") as ding:
            LauncherBridge.reviewGrade(stub, False)
        self.assertEqual(ding.call_count, 0, "没记住不该有庆祝音")
        self.assertEqual(stub._review.grades, [False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
