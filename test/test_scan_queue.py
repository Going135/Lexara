# -*- coding: utf-8 -*-
"""§6 连续扫词队列：八条腿是「同时踩词的能力」，不是词数上限。

覆盖任务书 §6 的验收清单：0 / 1 / 8 / 9 / 16 / 50 / 100 个词、
多行、双列、极窄选区、重叠框、同一个词重复出现、
中途暂停 / 继续 / 取消、引擎失败或没有框、
**整条队列不重复、不静默丢词**。

不调 Qt：`scan_session` 是纯逻辑，这里也不建窗口，跑起来是毫秒级。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from scan_session import (ACTIVE, COMPLETED, FAILED, LEG_COUNT, PENDING,
                          SKIPPED, ScanSession)


def word(surface, x, y, w=None, h=22, lemma=None):
    """造一个 `OcrWorker.locate` 之后的词卡（屏幕逻辑像素）。"""
    w = len(surface) * 9 if w is None else w
    return {"surface": surface, "lemma": (lemma or surface).lower(),
            "meaning": "义:" + surface, "word_id": "",
            "screen_pos": (float(x), float(y)),
            "screen_box": (float(x - w / 2.0), float(y - h / 2.0),
                           float(w), float(h))}


def line(texts, y=100.0, x0=100.0, step=90.0):
    return [word(t, x0 + i * step, y) for i, t in enumerate(texts)]


def run_to_end(session, clock, dwell_step=1.0):
    """把队列跑到结束：每批落定 → 推进停留 → 开下一批。"""
    opened = list(session.start())
    guard = 0
    while not session.finished and guard < 500:
        guard += 1
        for target in opened:
            session.mark_landed(target.word_id, pegged=True)
        clock.t += dwell_step
        opened = session.tick(clock.t)
        if not opened and not session.finished:
            # 没到停留时间：再推一帧
            clock.t += dwell_step
            opened = session.tick(clock.t)
    return guard


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()

    def session(self, words, batch=LEG_COUNT, dwell=0.45, stall=None):
        kwargs = {} if stall is None else {"stall": stall}
        return ScanSession(words, batch=batch, clock=self.clock, dwell=dwell,
                           **kwargs)

    # ------------------------------------------------ 数量档位
    def test_zero_words(self):
        session = self.session([])
        self.assertEqual(session.start(), [])
        self.assertTrue(session.finished)
        self.assertEqual(session.stats()["completed"], 0)

    def test_one_word(self):
        session = self.session(line(["alpha"]))
        batch = session.start()
        self.assertEqual(len(batch), 1)
        run_to_end(session, self.clock)
        self.assertEqual(session.stats()["completed"], 1)
        self.assertEqual(session.stats()["remaining"], 0)

    def test_sizes_up_to_100_all_complete(self):
        """0/1/8/9/16/50/100 个词：**一个都不能丢**。"""
        for count in (0, 1, 8, 9, 16, 50, 100):
            with self.subTest(count=count):
                words = line(["w%d" % i for i in range(count)])
                session = self.session(words)
                self.assertEqual(len(session.targets), count)
                run_to_end(session, self.clock)
                stats = session.stats()
                self.assertEqual(stats["completed"], count)
                self.assertEqual(stats["remaining"], 0)
                self.assertEqual(stats["failed"], 0)
                self.assertEqual(stats["skipped"], 0)
                # 批次数 = 向上取整(count / 8)，且每批不超过腿数
                self.assertEqual(stats["batches"],
                                 -(-count // LEG_COUNT) if count else 0)

    def test_no_batch_overshoots_legs(self):
        session = self.session(line(["w%d" % i for i in range(23)]))
        seen = []
        batch = session.start()
        while batch:
            self.assertLessEqual(len(batch), LEG_COUNT)
            seen.extend(b.word_id for b in batch)
            for target in batch:
                session.mark_landed(target.word_id)
            self.clock.t += 1.0
            batch = session.tick(self.clock.t)
        self.assertEqual(len(seen), 23)
        self.assertEqual(len(set(seen)), 23)          # 不重复

    # ------------------------------------------------ 稳定唯一 ID
    def test_same_word_repeated_gets_distinct_ids(self):
        words = line(["the", "cat", "the", "sat", "the"])
        session = self.session(words)
        ids = [t.word_id for t in session.targets]
        self.assertEqual(len(ids), len(set(ids)))
        the_ids = [i for i in ids if ":the#" in i]
        self.assertEqual(sorted(the_ids), ["scan:the#0", "scan:the#1",
                                           "scan:the#2"])

    def test_word_id_written_back_into_item(self):
        words = line(["alpha"])
        session = self.session(words)
        self.assertEqual(words[0]["word_id"], session.targets[0].word_id)

    # ------------------------------------------------ 路径顺序
    def test_reading_order_row_major(self):
        """行优先：给词的顺序打乱也必须按「从上到下、从左到右」排。"""
        row1 = line(["a", "b", "c", "d"], y=100)
        row2 = line(["e", "f", "g", "h"], y=140)
        session = self.session(list(reversed(row1 + row2)))
        self.assertEqual([t.word for t in session.order],
                         ["a", "b", "c", "d", "e", "f", "g", "h"])

    def test_batch_follows_reading_order_not_input_order(self):
        """领批次走 `order`：OCR 先给的词不一定是最靠前的词。"""
        row = line(["a", "b", "c", "d"], y=100)
        session = self.session(list(reversed(row)), batch=2)
        first = session.start()
        self.assertEqual([t.word for t in first], ["a", "b"])
        for target in first:
            session.mark_landed(target.word_id)
        self.clock.t += 1.0
        self.assertEqual([t.word for t in session.tick(self.clock.t)], ["c", "d"])

    def test_two_column_layout_is_row_major(self):
        """左右两栏并排：按行读，同一行内用「最近邻」决定先后。

        任务书 §6 定的路径就是「行优先 + 同行最近邻」；真要分栏得先做
        版面分析，那是下一阶段的事，这里先把行序钉住。
        第二行 `R1 → R2 → L2` 正是最近邻的体现：上一落点在右边，
        同一行的右侧词先踩，蜘蛛不会每行都横穿一次屏幕。
        """
        left = [word("L%d" % i, 100, 100 + i * 40) for i in range(3)]
        right = [word("R%d" % i, 600, 100 + i * 40) for i in range(3)]
        session = self.session(right + left)
        self.assertEqual([t.word for t in session.order],
                         ["L0", "R0", "L1", "R1", "R2", "L2"])

    def test_tilted_line_stays_one_row(self):
        """轻微倾斜（同一行 y 差 10px）不能被拆成两行。"""
        words = [word("w%d" % i, 100 + i * 90, 100 + i * 10) for i in range(5)]
        session = self.session(words)
        self.assertEqual([t.word for t in session.order],
                         ["w0", "w1", "w2", "w3", "w4"])

    def test_extremely_narrow_selection(self):
        """极窄选区：所有词 x 几乎相同，只靠 y 分行，队列照样跑完。"""
        words = [word("w%d" % i, 300 + (i % 2), 100 + i * 30) for i in range(12)]
        session = self.session(words)
        run_to_end(session, self.clock)
        self.assertEqual(session.stats()["completed"], 12)

    def test_overlapping_boxes_are_still_separate_targets(self):
        words = [word("alpha", 200, 100), word("beta", 202, 101),
                 word("gamma", 201, 100)]
        session = self.session(words)
        self.assertEqual(len(session.targets), 3)
        run_to_end(session, self.clock)
        self.assertEqual(session.stats()["completed"], 3)

    def test_words_without_position_are_dropped_before_queue(self):
        """没坐标的词**在入队前**就剔掉，并计入「识别到但没落点」的统计口径。"""
        words = line(["alpha"]) + [{"surface": "ghost", "lemma": "ghost"}]
        session = self.session(words)
        self.assertEqual([t.word for t in session.targets], ["alpha"])

    # ------------------------------------------------ 完成语义
    def test_complete_at_most_once(self):
        session = self.session(line(["alpha", "beta"]))
        batch = session.start()
        first = batch[0]
        self.assertTrue(session.mark_landed(first.word_id))
        self.assertFalse(session.mark_landed(first.word_id))   # 重复落位不重复计数
        self.assertEqual(session.stats()["completed"], 1)

    def test_unreachable_word_completes_without_leg(self):
        """够不着的词：只亮框，也算完成（`pegged=False`），不算丢词。"""
        session = self.session(line(["alpha", "beta"]))
        batch = session.start()
        session.mark_landed(batch[0].word_id, pegged=True)
        session.mark_landed(batch[1].word_id, pegged=False)
        stats = session.stats()
        self.assertEqual(stats["completed"], 2)
        self.assertEqual([t.pegged for t in session.targets], [True, False])

    def test_stuck_targets_fail_after_max_attempts(self):
        """反复领不到腿 → 判 failed，绝不静默悬着。"""
        session = self.session(line(["alpha"]), dwell=0.0)
        session.start()
        for _ in range(4):
            self.clock.t += 1.0
            session.tick(self.clock.t)          # 一直不 mark_landed
        self.assertEqual(session.stats()["failed"], 1)
        self.assertTrue(session.finished)
        self.assertIn("未落位", session.targets[0].reason)

    def test_stalled_batch_is_re_issued_before_failing(self):
        """卡住的一批先「重开让腿重新分配」，重试耗尽才判失败。

        这条测的是 §6.4「空出来的腿再领下一批」的反面：批里有一个词派不到腿时，
        队列不能永久钉在这批上。
        """
        batches = []
        session = self.session(line(["alpha"]), stall=0.5, dwell=0.0)
        session.on_batch = lambda picked: batches.append(
            [t.word for t in picked])
        session.start()
        for step in (0.6, 1.2, 1.8):
            self.clock.t = step
            session.tick(step)
        # 前三轮都是「重新分配」，第四轮才判失败
        self.assertEqual(len(batches), 3)
        self.assertEqual(session.targets[0].attempts, 3)
        self.assertEqual(session.stats()["failed"], 1)
        self.assertEqual(session.stats()["completed"], 0)

    def test_resume_does_not_instantly_trigger_stall(self):
        """暂停很久再回来，不能立刻被算成「这批落位太慢」。"""
        session = self.session(line(["w%d" % i for i in range(16)]), stall=0.9)
        batch = session.start()
        session.pause()
        self.clock.t += 30.0
        session.resume()
        self.clock.t += 0.5           # 恢复后只过了 0.5s < stall
        self.assertEqual(session.tick(self.clock.t), [])
        self.assertEqual(session.stats()["failed"], 0)
        self.assertEqual(len(session.active()), 8)

    def test_retry_is_the_only_way_back_to_pending(self):
        session = self.session(line(["alpha"]))
        batch = session.start()
        session.mark_landed(batch[0].word_id)
        self.assertEqual(session.stats()["completed"], 1)
        self.assertTrue(session.retry(batch[0].word_id))
        self.assertEqual(session.stats()["completed"], 0)
        self.assertEqual(session.targets[0].state, PENDING)

    def test_skip_and_fail_do_not_double_count(self):
        session = self.session(line(["a", "b", "c"]))
        batch = session.start()
        session.skip(batch[0].word_id)
        session.mark_failed(batch[1].word_id, "引擎异常")
        session.mark_landed(batch[2].word_id)
        stats = session.stats()
        self.assertEqual((stats["skipped"], stats["failed"], stats["completed"]),
                         (1, 1, 1))
        self.assertFalse(session.skip(batch[2].word_id))     # 已完成不能被改判
        self.assertFalse(session.mark_failed(batch[2].word_id))

    def test_every_state_transition_is_conserved(self):
        """总量守恒：pending+active+completed+skipped+failed == total，任何时刻都是。"""
        session = self.session(line(["w%d" % i for i in range(20)]))
        batch = session.start()
        for step in range(40):
            stats = session.stats()
            self.assertEqual(stats["total"],
                             stats["pending"] + stats["active"] +
                             stats["completed"] + stats["skipped"] +
                             stats["failed"])
            if batch:
                session.mark_landed(batch[0].word_id)
                batch = batch[1:] or session.tick(self.clock.t + 1.0)
                self.clock.t += 1.0

    # ------------------------------------------------ 暂停 / 取消
    def test_pause_blocks_new_batches_and_resume_continues(self):
        session = self.session(line(["w%d" % i for i in range(20)]), dwell=0.0)
        batch = session.start()
        self.assertEqual(len(batch), 8)
        session.pause()
        for target in batch:
            session.mark_landed(target.word_id)
        self.assertEqual(session.tick(self.clock.t + 5), [])
        self.assertEqual(len(session.active()), 0)
        self.assertEqual(session.pending().__len__(), 12)
        session.resume()
        nxt = session.tick(self.clock.t + 6)
        self.assertEqual(len(nxt), 8)

    def test_cancel_leaves_nothing_in_flight(self):
        session = self.session(line(["w%d" % i for i in range(30)]))
        session.start()
        session.cancel()
        stats = session.stats()
        self.assertTrue(session.finished)
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["active"], 0)
        self.assertEqual(stats["cancelled"], True)
        # 取消 = 剩下的都算 skipped，不是一删了之
        self.assertEqual(stats["skipped"], 30)
        self.assertTrue(all(t.reason for t in session.targets))

    def test_cancel_is_idempotent(self):
        session = self.session(line(["a", "b"]))
        session.start()
        session.cancel()
        first = session.stats()
        session.cancel()
        self.assertEqual(first, session.stats())

    def test_finish_callback_fires_once(self):
        fired = []
        session = self.session(line(["a", "b"]))
        session.on_finish = lambda stats: fired.append(stats)
        batch = session.start()
        for target in batch:
            session.mark_landed(target.word_id)
        self.clock.t += 1.0
        session.tick(self.clock.t)
        self.assertEqual(len(fired), 1)
        session.cancel()
        self.assertEqual(len(fired), 1)

    def test_batch_callback_sees_each_batch(self):
        seen = []
        session = self.session(line(["w%d" % i for i in range(10)]), dwell=0.0)
        session.on_batch = lambda picked: seen.append([t.word for t in picked])
        batch = session.start()
        while batch:
            for target in batch:
                session.mark_landed(target.word_id)
            self.clock.t += 1.0
            batch = session.tick(self.clock.t)
        self.assertEqual([len(b) for b in seen], [8, 2])
        self.assertEqual(seen[0][:3], ["w0", "w1", "w2"])

    # ------------------------------------------------ 呈现层需要的接口
    def test_visible_keeps_finished_boxes(self):
        """换批时旧框不消失 —— 否则用户看到的是「一闪一闪地丢词」。"""
        session = self.session(line(["w%d" % i for i in range(10)]), dwell=0.0)
        batch = session.start()
        for target in batch:
            session.mark_landed(target.word_id)
        self.clock.t += 1.0
        session.tick(self.clock.t)
        visible = session.visible()
        self.assertEqual(len(visible), 10)            # 8 已完成 + 2 当前批
        self.assertEqual([t.word for t in visible],
                         ["w%d" % i for i in range(10)])

    def test_engine_failure_path_reports_zero_boxes(self):
        """OCR 一个框都没给（引擎失败/空结果）：队列为空、立即结束、统计如实为 0。"""
        session = self.session([])
        self.assertEqual(session.start(), [])
        stats = session.stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["completed"], 0)
        self.assertTrue(session.finished)


class OverlayClampTests(unittest.TestCase):
    """`[:8]` 截断必须真的没了：覆盖层吃的是 session，不是「前八个词」。"""

    def test_overlay_source_has_no_eight_clamp(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "src", "aim_overlay.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn('][:8]', source.replace(" ", ""))
        self.assertIn("ScanSession", source)

    def test_settings_allow_more_than_eight(self):
        from settings_store import BOUNDS
        self.assertGreater(BOUNDS["max_words"](16), 8)


if __name__ == "__main__":
    unittest.main()
