# -*- coding: utf-8 -*-
"""§7 蜘蛛感应的**纯逻辑核心**：变化检测 / ROI 选择 / 去重缓存 / 提示调度 / 预算。

这里**不起线程、不抓屏幕、不跑 OCR**，全部用假帧 + 注入时钟，
所以毫秒级就能把 §7.4 那串验收条款逐条踩实：

    · 静态画面不会重复无限提示同一词；
    · 内容变了优先检测新内容（字幕场景）；
    · 缓存有上限（开一小时内存不涨）；
    · 出错自动暂停、**不会**自己重启；
    · 超预算先降频、降到下限才暂停；
    · 目标顺序稳定（阅读顺序）；
    · 排除自己的窗口，避免自我识别循环；
    · 状态文案只有模式与计数，**没有任何屏幕文本**。

`sense_session` 只 import numpy，所以本文件也不需要 Qt（和 §6 的
`test_scan_queue.py` 同一个理由）。
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sense_session import (ERROR, OFF, PAUSED, RUNNING, WORD_CACHE_MAX,
                           ROI_CACHE_MAX, NOTICE_MAX_PER_WORD, MIN_HZ,
                           QUEUE_MAX, DEFER_MAX, SenseSession)

H, W = 120, 160          # 4 列 × 3 行 → 每格 40×40
CELL_H, CELL_W = H // 3, W // 4


class Clock:
    """注入时钟：TTL / 冷却 / 延迟预算全都算得可控。"""

    def __init__(self, start: float = 1000.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def blank(value: float = 0.5) -> np.ndarray:
    return np.full((H, W), int(value * 255), np.uint8)


def with_cell(base, row: int, col: int, value: float) -> np.ndarray:
    """把某一格换成另一个亮度 —— 模拟「这一块内容变了」。"""
    frame = base.copy()
    y0, y1 = row * CELL_H, (row + 1) * CELL_H
    x0, x1 = col * CELL_W, (col + 1) * CELL_W
    frame[y0:y1, x0:x1] = int(value * 255)
    return frame


def word(surface, x=200.0, y=100.0, meaning="释义"):
    return {"surface": surface, "lemma": surface.lower(), "meaning": meaning,
            "screen_pos": (float(x), float(y)),
            "screen_box": (float(x), float(y), 40.0, 16.0)}


def session(clock=None, **kwargs):
    clock = clock or Clock()
    return SenseSession(clock=clock, **kwargs), clock


def first_frame(sense, frame=None):
    """开感应后的第一帧（没有参照 → 整帧扫一次）。"""
    roi, full = sense.ingest(frame if frame is not None else blank())
    assert full and roi == []
    return roi, full


# ---------------------------------------------------------------- 变化检测
class TestChangeDetection(unittest.TestCase):
    def test_state_machine_starts_off(self):
        sense, _ = session()
        self.assertEqual(sense.state, OFF)
        # 没开就吃帧：什么都不该发生（§7.2「关闭后停止捕获和工作线程」的逻辑面）
        roi, full = sense.ingest(blank())
        self.assertEqual((roi, full), ([], False))
        self.assertEqual(sense.stats["cycles"], 0)

    def test_start_then_first_frame_is_full(self):
        sense, _ = session()
        sense.start()
        self.assertEqual(sense.state, RUNNING)
        roi, full = first_frame(sense)
        self.assertEqual(sense.stats["full_frame"], 1)
        self.assertEqual(roi, [])

    def test_static_frame_is_skipped(self):
        """§7.4：静态画面不会重复触发 OCR —— 这是节流真正的省点。"""
        sense, _ = session()
        sense.start()
        frame = blank()
        first_frame(sense, frame)
        for _ in range(20):
            roi, full = sense.ingest(frame)
            self.assertEqual((roi, full), ([], False))
        self.assertEqual(sense.stats["skipped_no_change"], 20)
        self.assertEqual(sense.stats["ocr_runs"], 0)

    def test_one_cell_change_returns_that_roi_only(self):
        """只有字幕那条动了 → 只送那一块 ROI，不是整屏。"""
        sense, _ = session()
        sense.start()
        base = blank()
        first_frame(sense, base)
        changed = with_cell(base, 1, 2, 0.9)
        roi, full = sense.ingest(changed)
        self.assertFalse(full)
        self.assertEqual(roi, ["r1c2"])

    def test_mostly_changed_screen_goes_full_frame(self):
        """整屏在换（切页 / 全屏动画）→ 分块反而漏，直接整帧。"""
        sense, _ = session()
        sense.start()
        base = blank()
        first_frame(sense, base)
        frame = base.copy()
        for r in range(3):
            for c in range(4):
                if (r, c) != (0, 0):          # 11/12 格都变 ≥ 0.75
                    frame[r * CELL_H:(r + 1) * CELL_H,
                          c * CELL_W:(c + 1) * CELL_W] = int(0.95 * 255)
        roi, full = sense.ingest(frame)
        self.assertTrue(full)
        self.assertEqual(roi, [])
        # 2 = 开感应那一帧的整帧 + 这次「整屏在换」的整帧
        self.assertEqual(sense.stats["full_frame"], 2)

    def test_tiny_noise_does_not_wake_ocr(self):
        """±1 灰级的抖动（子像素渲染 / 视频压缩噪声）不该被当成内容变了。"""
        sense, _ = session()
        sense.start()
        base = blank()
        first_frame(sense, base)
        noisy = base.copy()
        noisy[:, :] = np.clip(noisy.astype(np.int16) + 1, 0, 255).astype(np.uint8)
        roi, full = sense.ingest(noisy)
        self.assertEqual((roi, full), ([], False))

    def test_pause_stops_detection_and_resume_resets_baseline(self):
        sense, _ = session()
        sense.start()
        base = blank()
        first_frame(sense, base)
        sense.pause("用户暂停")
        self.assertEqual(sense.state, PAUSED)
        roi, full = sense.ingest(with_cell(base, 0, 0, 0.95))
        self.assertEqual((roi, full), ([], False))   # 暂停中一律不响应
        sense.resume()
        roi, full = sense.ingest(with_cell(base, 0, 0, 0.95))
        self.assertTrue(full)                        # 恢复后重新建立参照

    def test_excluded_cell_blocks_detection(self):
        """§7.3：本程序自己的窗口不能被认成「屏幕上新出现的词」。"""
        sense, _ = session()
        sense.start()
        base = blank()
        first_frame(sense, base)
        # 盖住 r1c1 整格（图像像素）
        sense.set_exclude_rects([(1 * CELL_W, 1 * CELL_H, CELL_W, CELL_H)])
        roi, full = sense.ingest(with_cell(base, 1, 1, 0.98))
        self.assertEqual((roi, full), ([], False))
        # 隔壁格子照常能感应到
        roi, _full = sense.ingest(with_cell(base, 1, 2, 0.1))
        self.assertEqual(roi, ["r1c2"])

    def test_partial_overlap_is_not_blocked(self):
        """只压到半格 → 不能把整格屏蔽掉，否则桌宠往中间一站就瞎了一片。"""
        sense, _ = session()
        sense.start()
        base = blank()
        first_frame(sense, base)
        sense.set_exclude_rects([(CELL_W, CELL_H, CELL_W // 2, CELL_H)])
        roi, _full = sense.ingest(with_cell(base, 1, 1, 0.95))
        self.assertEqual(roi, ["r1c1"])

    def test_empty_frame_is_harmless(self):
        sense, _ = session()
        sense.start()
        roi, full = sense.ingest(np.zeros((0, 0), np.uint8))
        self.assertEqual((roi, full), ([], False))

    def test_exclude_rects_are_scaled_from_full_resolution_pixels(self):
        """★ 回归：排除区是**全分辨率像素**，格子是**缩略图像素**，必须换算。

        `pet_window._sense_exclude_rects()` 给出的是 2560×1600 那一帧里的矩形
        （逻辑坐标 × DPR），而 `ingest` 吃的是宽 1280 的缩略图（`scale=0.5`）。
        不换算的话排除区会被挪到别的地格去 —— 「排除自己」等于没写，
        §7.3 明令避免的自识别循环照样成立（2026-10-18 接线时发现）。
        """
        # 缩略图 800×600 → 每格 200×200；要屏蔽的是 r1c1（x 200..400, y 200..400）
        base = np.full((600, 800), 128, np.uint8)
        own_window = np.full((600, 800), 128, np.uint8)
        own_window[200:400, 200:400] = 250       # 「蜘蛛自己的状态条」那块亮了
        # 全分辨率坐标 = 缩略图坐标 / 0.5
        rect = [(400.0, 400.0, 400.0, 400.0)]

        sense, _ = session(cols=4, rows=3)
        sense.start()
        sense.set_exclude_rects(rect)
        first_frame(sense, base)
        self.assertEqual(sense.ingest(own_window, pixel_scale=0.5),
                         ([], False))            # 换算对了 → 这一格被屏蔽

        neighbour = np.full((600, 800), 128, np.uint8)
        neighbour[200:400, 400:600] = 250        # 隔壁 r1c2 才是桌面内容
        sense2, _ = session(cols=4, rows=3)
        sense2.start()
        sense2.set_exclude_rects(rect)
        first_frame(sense2, base)
        self.assertEqual(sense2.ingest(neighbour, pixel_scale=0.5),
                         (["r1c2"], False))      # 屏蔽不能顺手把隔壁也弄瞎

        sense3, _ = session(cols=4, rows=3)
        sense3.start()
        sense3.set_exclude_rects(rect)
        first_frame(sense3, base)
        roi, _full = sense3.ingest(own_window, pixel_scale=1.0)
        self.assertIn("r1c1", roi)               # 不换算 = 老缺陷，认得见自己

    def test_roi_box_covers_the_cell_and_stays_in_bounds(self):
        sense, _ = session()
        sense.start()
        sense.start()
        x, y, bw, bh = sense.roi_box("r2c3", (W, H))
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + bw, W)
        self.assertLessEqual(y + bh, H)
        # 框要真包住那一格
        self.assertLessEqual(x, 3 * CELL_W)
        self.assertGreaterEqual(x + bw, 4 * CELL_W)
        # 认不出的键退化成整帧，而不是崩
        self.assertEqual(sense.roi_box("garbage", (W, H)), (0, 0, W, H))


# ---------------------------------------------------------------- 去重 / 排期
class TestDedupeAndScheduling(unittest.TestCase):
    def test_same_payload_same_roi_is_not_fresh(self):
        """同一块字幕被扫第二遍 → 不出新候选（静态画面不重复提示）。"""
        sense, clock = session()
        sense.start()
        items = [word("subtitle")]
        self.assertEqual(len(sense.note_words("r1c2", items, 100.0)), 1)
        again = sense.note_words("r1c2", [word("subtitle")], 100.0)
        self.assertEqual(again, [])
        self.assertEqual(sense.stats["suppressed"], 0)   # 连「抑制」都不算

    def test_changed_content_is_fresh(self):
        """字幕换了一句 → 必须算新内容（§7.2「动态字幕优先检测新内容」）。"""
        sense, _ = session()
        sense.start()
        sense.note_words("r1c2", [word("old")], 100.0)
        fresh = sense.note_words("r1c2", [word("new")], 100.0)
        self.assertEqual([w["surface"] for w in fresh], ["new"])

    def test_repeat_notice_suppressed_after_ttl_count(self):
        """同一个词在冷却窗口里最多提示 N 次，再多就压掉。"""
        sense, clock = session()
        sense.start()
        total_fresh = 0
        for i in range(NOTICE_MAX_PER_WORD + 4):
            # 每轮换一下别的内容，保证 ROI 判定为「有新词」
            fresh = sense.note_words("r1c2", [word("repeat", 100, 100),
                                              word("filler%d" % i, 900, 100)],
                                     50.0)
            total_fresh += len(fresh)
        self.assertGreaterEqual(sense.stats["suppressed"], 4)
        queued = [w["surface"] for w in sense._queue]
        self.assertLessEqual(queued.count("repeat"), NOTICE_MAX_PER_WORD)

    def test_same_word_different_place_are_two_targets(self):
        sense, _ = session()
        sense.start()
        fresh = sense.note_words("r0c0", [word("lexara", 100, 100),
                                          word("lexara", 800, 300)], 40.0)
        self.assertEqual(len(fresh), 2)

    def test_notice_order_is_reading_order(self):
        """§7.2「目标循环顺序稳定」：按阅读顺序（先 y 后 x）。"""
        sense, _ = session()
        sense.start()
        sense.note_words("r0c0", [word("bottom", 100, 300),
                                  word("right", 500, 100),
                                  word("left", 100, 100)], 40.0)
        order = [w["surface"] for w in sense._queue]
        self.assertEqual(order, ["left", "right", "bottom"])

    def test_new_content_jumps_a_backlog_of_old_content(self):
        """§7.3「优先新出现的内容」：旧内容积压一大堆时，新内容得**先闪**。

        ★ 这条是复现真桌面 e2e 量到的失败（`dist/sense/coord_probe.log`）：
          开感应第一帧没有参照 → 整帧读到 24 个「开机前就在屏幕上」的词，
          这一轮在本机跑了 19073ms；这期间测试才把字幕窗口放出来，
          字幕那轮只读回 14 个词，FIFO 让它们排在 24 个后面 →
          一轮只闪一个 + 已被降频到 2.5s/轮，30 秒闪出来的 8 个全是旧内容，
          **新出现的那句一个都没轮到**。队列改成「新的插队首」后这条才成立。
        """
        sense, _ = session()
        sense.start()
        old = [word("old%d" % i, 100 + 30 * i, 60) for i in range(24)]
        sense.note_words("full", old, 19073.0)
        self.assertEqual(sense.pending_notices(), QUEUE_MAX)   # 积压有上限
        fresh = sense.note_words("r2c1", [word("subtitle", 300, 820)], 260.0)
        self.assertEqual([w["surface"] for w in fresh], ["subtitle"])
        # 下一个要闪的词**必须**是刚出现的那个，不是 24 个里的任何一个
        self.assertEqual(sense.next_notice()["surface"], "subtitle")

    def test_notice_backlog_is_bounded_and_drops_the_oldest(self):
        """待提示队列也有上限：积压时丢**队尾（最旧）**，新词永远留得住。"""
        sense, _ = session()
        sense.start()
        sense.note_words("full", [word("first", 100, 60)], 100.0)
        for i in range(4):
            sense.note_words("r%dc0" % i,
                             [word("w%d-%d" % (i, j), 100 + 30 * j, 60)
                              for j in range(QUEUE_MAX)], 80.0)
        self.assertEqual(sense.pending_notices(), QUEUE_MAX)
        self.assertGreaterEqual(sense.stats["queue_dropped"], 1)
        self.assertEqual(sense.next_notice()["surface"], "w3-0")
        self.assertNotIn("first", [w["surface"] for w in sense._queue])

    def test_next_notice_pops_one_at_a_time_no_duplicates(self):
        sense, _ = session()
        sense.start()
        sense.note_words("r0c0", [word("a", 100, 100), word("b", 200, 100)], 40.0)
        first = sense.next_notice()
        second = sense.next_notice()
        self.assertEqual(
            sorted([first["surface"], second["surface"]]), ["a", "b"])
        self.assertIsNone(sense.next_notice())
        self.assertEqual(sense.stats["notices"], 2)
        self.assertEqual(sense.pending_notices(), 0)

    def test_stale_queue_items_are_dropped(self):
        """躺过冷却窗口的陈旧目标不该再闪 —— 那个位置早就没这个词了。"""
        sense, clock = session()
        sense.start()
        sense.note_words("r0c0", [word("old", 100, 100)], 40.0)
        clock.advance(sense.notice_ttl + 1.0)
        self.assertIsNone(sense.next_notice())
        self.assertEqual(sense.pending_notices(), 0)

    def test_caches_are_bounded(self):
        """§7.3「维护有上限的缓存，防止内存无限增长」。"""
        sense, _ = session()
        sense.start()
        for i in range(WORD_CACHE_MAX + 120):
            sense.note_words("r%dc%d" % (i % 3, i % 4),
                             [word("w%d" % i, 100 + (i % 7), 100)], 20.0)
        self.assertLessEqual(len(sense._seen_words), WORD_CACHE_MAX)
        self.assertLessEqual(len(sense._word_counts), WORD_CACHE_MAX)
        for j in range(ROI_CACHE_MAX + 30):
            sense.note_words("k%d" % j, [word("roi%dx" % j, 10, 10)], 20.0)
        self.assertLessEqual(len(sense._roi_cache), ROI_CACHE_MAX)

    def test_word_key_bucketing(self):
        sense, _ = session()
        key = sense._word_key(word("Lexara", 100, 100))
        self.assertEqual(key, "lexara@3,3")
        self.assertEqual(sense._word_key({"surface": "  "}), "")

    def test_words_in_counter_matches_input(self):
        sense, _ = session()
        sense.start()
        sense.note_words("r0c0", [word("a"), word("b")], 30.0)
        self.assertEqual(sense.stats["words_in"], 2)
        self.assertEqual(sense.stats["ocr_runs"], 1)


# ---------------------------------------------------------------- 检测灵敏度
# 这一整类是 2026-10-18 由 `tools/sense_bench.py` **量出来的缺陷**补的回归：
# 老判据是「每格灰度均值差」，而一行英文字幕整句换掉时白字占比几乎不变，
# 均值差实测只有 0.0009~0.0026 < 阈值 0.006 → 12 格里 0 格算「变了」
# → 感应模式对「桌面上新出现的一句话」这个核心场景**根本不触发 OCR**。
# 现在判据换成每格「逐像素平均绝对差」（`cell_diffs`），下面几条把它钉住。

#: 真实缩略图尺寸（`sense_worker._thumbnail` 把宽缩到 1280）——
#: 灵敏度必须按**真实格子大小**测，按 40×40 的小格子测出来的结论是假的。
BIG_H, BIG_W = 720, 1280
BIG_CELL_H, BIG_CELL_W = BIG_H // 3, BIG_W // 4      # 240 × 320


def big(value: float = 0.5) -> np.ndarray:
    return np.full((BIG_H, BIG_W), int(value * 255), np.uint8)


def with_patch(frame, row: int, col: int, y0: int, x0: int, ph: int, pw: int,
               value: float) -> np.ndarray:
    """在某一格里换一小块 —— 模拟「鼠标指针划过」。"""
    out = frame.copy()
    top, left = row * BIG_CELL_H + y0, col * BIG_CELL_W + x0
    out[top:top + ph, left:left + pw] = int(value * 255)
    return out


def with_stripes(frame, row: int, col: int, phase: int = 0,
                 height: int = 60) -> np.ndarray:
    """把某一格里的一条横带换成**黑白竖条纹**（相位可选）。

    条纹的均值和底色一样（0.5），但逐像素全不一样 —— 这就是「换了字」的形状：
    亮度统计不动，像素全动。
    """
    out = frame.copy()
    top = row * BIG_CELL_H + (BIG_CELL_H - height) // 2
    band = np.tile((np.arange(BIG_CELL_W) + phase) % 2, (height, 1))
    out[top:top + height, col * BIG_CELL_W:(col + 1) * BIG_CELL_W] = \
        (band * 255).astype(np.uint8)
    return out


class TestChangeDetectionSensitivity(unittest.TestCase):
    def test_text_swap_with_unchanged_brightness_is_detected(self):
        """★ 回归：换了一句话（均值没变）必须被认成「内容变了」。"""
        sense, _ = session()
        sense.start()
        base = big()
        first_frame(sense, base)
        roi, full = sense.ingest(with_stripes(base, 2, 1, phase=0))
        self.assertFalse(full)
        self.assertIn("r2c1", roi)
        # 同一相位再来一次 = 内容没变 → 不该再唤醒 OCR
        roi, full = sense.ingest(with_stripes(base, 2, 1, phase=0))
        self.assertEqual((roi, full), ([], False))
        # 换相位（= 字幕换了一句）→ 必须再唤醒一次
        roi, _full = sense.ingest(with_stripes(base, 2, 1, phase=1))
        self.assertIn("r2c1", roi)

    def test_cursor_motion_does_not_wake_ocr(self):
        """指针那么几十个点划过一格，不该把 OCR 叫醒（否则每帧都在扫）。"""
        sense, _ = session()
        sense.start()
        base = big()
        first_frame(sense, base)
        # 16×16 指针：占 320×240 一格的 0.33%
        roi, full = sense.ingest(with_patch(base, 1, 2, 100, 100, 16, 16, 0.95))
        self.assertEqual((roi, full), ([], False))

    def test_subtitle_row_change_stays_local(self):
        """底部一整行字幕换了 → 是**几格**局部变化，不是整屏（省 OCR 的那笔账）。"""
        sense, _ = session()
        sense.start()
        base = big()
        first_frame(sense, base)
        frame = with_stripes(with_stripes(with_stripes(base, 2, 0, 0), 2, 1, 1),
                             2, 2, 0)
        roi, full = sense.ingest(frame)
        self.assertFalse(full)
        self.assertEqual(sorted(roi), ["r2c0", "r2c1", "r2c2"])

    def test_resolution_change_rebuilds_baseline(self):
        """换屏 / 改 DPI → 帧尺寸变了，逐格没法比，退回整帧重来一次。"""
        sense, _ = session()
        sense.start()
        first_frame(sense, big())
        roi, full = sense.ingest(np.full((360, 640), 128, np.uint8))
        self.assertEqual((roi, full), ([], True))
        # 下一帧起就有新参照了（同尺寸同内容 → 没变）
        roi, full = sense.ingest(np.full((360, 640), 128, np.uint8))
        self.assertEqual((roi, full), ([], False))

    def test_cell_diffs_are_normalised_and_zero_when_identical(self):
        sense, _ = session()
        frame = with_stripes(big(), 2, 3, 0)
        diffs = sense.cell_diffs(frame, frame)
        self.assertEqual(diffs.shape, (3, 4))
        self.assertAlmostEqual(float(diffs.max()), 0.0)
        swapped = with_stripes(big(), 2, 3, 1)
        diffs = sense.cell_diffs(frame, swapped)
        # 条纹只占那格里 60/240 的高度：反相 → 那 25% 的像素差满级 → 0.25，
        # 而**均值差是 0.0**（黑白各半）。这两个数的比值就是换判据的理由。
        self.assertGreaterEqual(float(diffs[2, 3]), 0.2)
        self.assertAlmostEqual(float(diffs[0, 0]), 0.0)      # 没动的格子还是 0
        self.assertAlmostEqual(float(diffs[2, 3]), 0.25, places=2)
        # 旧判据（每格灰度均值差）在同一组帧上量出来是 0：这里把它算出来对比，
        # 免得以后有人觉得「均值差就够了」又改回去。
        cell = slice(2 * BIG_CELL_H, BIG_H), slice(3 * BIG_CELL_W, BIG_W)
        before = float(frame[cell].mean()) / 255.0
        after = float(swapped[cell].mean()) / 255.0
        self.assertLess(abs(after - before), 0.006)          # 低于旧阈值 → 旧判据漏
        self.assertGreaterEqual(float(diffs[2, 3]), 0.010)   # 高于新阈值 → 新判据抓到


# ---------------------------------------------------------------- 预算 / 出错
class TestBudgetAndErrors(unittest.TestCase):
    def test_slow_rounds_downshift_frequency(self):
        """§7.4「超过预算时自动降频或提示」：先降频，不是一超就关。"""
        sense, _ = session(budget_ms=100.0)
        sense.start()
        self.assertGreater(sense.hz, MIN_HZ)
        for _ in range(6):
            sense.note_words("r0c0", [word("slow")], 900.0)
        self.assertLess(sense.hz, 1.0)
        self.assertEqual(sense.state, RUNNING)          # 只是降频，没关掉
        self.assertGreaterEqual(sense.stats["downshifts"], 1)
        self.assertIn("超预算", sense.note)

    def test_still_slow_at_min_hz_pauses(self):
        sense, _ = session(budget_ms=100.0)
        sense.start()
        for _ in range(60):
            sense.note_words("r0c0", [word("very slow")], 5000.0)
        self.assertAlmostEqual(sense.hz, MIN_HZ)
        self.assertEqual(sense.state, PAUSED)
        self.assertIn("已自动暂停", sense.note)

    def test_frequency_recovers_when_the_machine_catches_up(self):
        """★ 一次尖峰不能把频率**永久**钉在下限（本机真桌面实测到的缺陷）。

        `tools/sense_coord_probe.py` 量到：开感应第一帧没有参照 → 走整帧，
        本机 **18966ms** 一轮；那一个样本就把阶梯一路踩到 0.4 次/秒，
        而之后每轮（收紧后的 ROI）只用 0.3~0.9 秒 —— 明明跟得上，
        用户看到的却是「字幕越闪越慢」，而且再也回不去他设定的 2 次/秒。
        旧的「只降不升」在这里不成立，所以现在要求：连着几轮在预算内就往上回。
        """
        sense, _ = session(budget_ms=1200.0, hz=2.0)
        sense.start()
        sense.note_words("full", [word("cold")], 18966.0)      # 那一次尖峰
        self.assertLess(sense.hz, sense.hz_start)              # 立刻降下来（该降）
        for i in range(15):                                    # 之后一直追得上
            sense.note_words("r0c0", [word("w%d" % i)], 300.0)
        self.assertAlmostEqual(sense.hz, sense.hz_start)       # 回到设定的 2.0
        self.assertGreaterEqual(sense.stats["upshifts"], 4)
        self.assertIn("已回到", sense.note)
        self.assertEqual(sense.state, RUNNING)

    def test_recovery_needs_consecutive_comfortable_rounds(self):
        """回速要犹豫：一两轮快不足以说明问题（防抖，别在 0.4/2.0 之间跳）。"""
        sense, _ = session(budget_ms=1200.0, hz=1.0)
        sense.start()
        for i in range(8):                                     # 持续超预算但不占满
            sense.note_words("r0c0", [word("s%d" % i)], 1500.0)
        slowed = sense.hz
        self.assertLess(slowed, 1.0)
        for i in range(3):                                     # 快，但窗口里还是慢的多
            sense.note_words("r1c%d" % i, [word("fast%d" % i)], 300.0)
        self.assertAlmostEqual(sense.hz, slowed)               # 还没开始回
        self.assertEqual(sense.stats["upshifts"], 0)
        sense.note_words("r2c0", [word("fast4")], 300.0)
        sense.note_words("r2c1", [word("fast5")], 300.0)
        # 近 5 轮的中位数这时才真的站到「快」一边，再连着三轮在预算内才回一步
        self.assertGreater(sense.hz, slowed)                   # 回了
        self.assertEqual(sense.stats["upshifts"], 1)
        self.assertLessEqual(sense.hz, 1.0)                    # 不会冲过设定的初值

    def test_measured_latency_cannot_park_above_the_floor(self):
        """★ 回归（本机实测数字）：整帧 OCR 平均 1503ms、预算 1200ms。

        老算法一步到位 `hz = 1000/1503 × 0.75 ≈ 0.5`，然后**卡死在 0.5**：
        既不会再降（目标值就是 0.5）、也进不了暂停分支（要求已经在 0.4）
        —— 状态条挂着「已降到 0.5 次/秒」，机器却一直在超预算跑。
        现在是阶梯下降：一定会走到下限，到下限后如实说明「仍超预算」。
        """
        sense, _ = session(budget_ms=1200.0, hz=1.0)
        sense.start()
        for _ in range(30):
            sense.note_words("r0c0", [word("fullframe")], 1503.0)
        self.assertAlmostEqual(sense.hz, MIN_HZ)             # 走到了下限，没停在半路
        self.assertGreaterEqual(sense.stats["downshifts"], 2)
        self.assertEqual(sense.state, RUNNING)               # 还跑得动 → 不擅自关模式
        self.assertIn("仍超预算", sense.note)                 # 但如实说出来（§7.3）

    def test_at_floor_but_faster_than_the_interval_keeps_running(self):
        """下限频率还跑得过来（单轮 < 轮间隔）→ 继续跑，只是把话说明白。"""
        sense, _ = session(budget_ms=100.0)
        sense.start()
        for _ in range(20):
            sense.note_words("r0c0", [word("slowish")], 900.0)   # 900ms < 2500ms
        self.assertEqual(sense.state, RUNNING)
        self.assertAlmostEqual(sense.hz, MIN_HZ)

    def test_at_floor_and_cannot_keep_up_pauses_after_two_rounds(self):
        """单轮比下限频率的**轮间隔**还长（追不上）→ 连着两轮、且样本够多才暂停。

        §7.3 要「自动暂停」，但也明令不许「一超预算就关」；所以判据是
        近 5 轮中位数 ≥ 轮间隔 **连续两轮** + 至少 `PAUSE_MIN_SAMPLES` 轮样本。
        前面那一轮降频本身不算「追不上」，第 2 轮样本太少也不够证据。
        """
        sense, _ = session(budget_ms=100.0)
        sense.start()
        sense.note_words("r0c0", [word("huge")], 4000.0)     # 第 1 轮：降到下限
        sense.note_words("r0c0", [word("huge")], 4000.0)     # 第 2 轮：样本太少，不算证据
        self.assertEqual(sense.state, RUNNING)
        sense.note_words("r0c0", [word("huge")], 4000.0)     # 第 3 轮：第 1 次「追不上」
        self.assertEqual(sense.state, RUNNING)
        self.assertIn("比轮间隔还长", sense.note)             # 但先把话说明白
        sense.note_words("r0c0", [word("huge")], 4000.0)     # 第 4 轮：第 2 次 → 暂停
        self.assertEqual(sense.state, PAUSED)
        self.assertIn("已自动暂停", sense.note)

    def test_fast_rounds_keep_frequency(self):
        sense, _ = session(budget_ms=1200.0)
        sense.start()
        for _ in range(10):
            sense.note_words("r0c0", [word("quick")], 90.0)
        self.assertEqual(sense.stats["downshifts"], 0)
        self.assertAlmostEqual(sense.hz, 1.0)

    def test_latency_window_is_rolling(self):
        sense, _ = session()
        sense.start()
        for _ in range(60):
            sense.note_words("r0c0", [word("x")], 50.0)
        self.assertLessEqual(len(sense.cycle_ms), 40)

    def test_isolated_cold_start_spike_does_not_pause_the_mode(self):
        """★ 回归（`tools/sense_bench.py` 实测）：一次尖峰 ≠ 这台机器跟不上。

        真线程流水线里跑出一轮 ~10s 的 OCR（空白整帧把引擎的多档回退阶梯全跑完），
        后面每一轮都只有 120ms。老判据用 40 轮大平均，那个尖峰一直被算在里面
        （均 4704ms）→ 阶梯一步到底 → 两轮「追不上」→ **自动暂停**，
        而且暂停发生在一轮中途，`process()` 在发提示前就 return 了 ——
        用户看到的是「开感应十几秒后自己停了，而这台机器其实单轮 120ms」。
        现在判据只看近 5 轮：尖峰滑出窗口后模式继续在跑。
        """
        sense, _ = session(budget_ms=1200.0, hz=2.0)
        sense.start()
        sense.note_words("r0c0", [word("cold")], 10029.0)      # 那一次冷启动
        for _ in range(8):
            sense.note_words("r0c0", [word("warm%d" % _)], 120.0)
        self.assertEqual(sense.state, RUNNING)
        self.assertNotIn("已自动暂停", sense.note)
        self.assertLess(sense.recent_cycle_ms, 500.0)          # 判据已经回到真实节奏
        self.assertGreater(sense.avg_cycle_ms, sense.recent_cycle_ms)
        # 大平均仍然如实保留给显示（§7.4 要报的是全窗口口径）
        self.assertGreater(sense.perf()["avg_cycle_ms"], 1000.0)

    def test_sustained_slow_rounds_pause_even_after_many_fast_ones(self):
        """★ 回归（同一个缺陷的另一半）：真追不上时，前面的快轮不许把它稀释掉。

        老判据下 30 轮 1500ms 再连 6 轮 3200ms（比下限的轮间隔 2500ms 还长），
        大平均才 1695ms → 「还没到暂停的标准」→ 模式挂在一轮比一轮慢的状态里
        继续跑。近 5 轮的窗口里全是 3200ms，所以该停就停。
        """
        sense, _ = session(budget_ms=1200.0, hz=1.0)
        sense.start()
        for _ in range(30):
            sense.note_words("r0c0", [word("mid")], 1500.0)
        for _ in range(6):
            sense.note_words("r0c0", [word("huge")], 3200.0)
        self.assertAlmostEqual(sense.hz, MIN_HZ)
        self.assertEqual(sense.state, PAUSED)
        self.assertIn("已自动暂停", sense.note)

    def test_recent_window_is_five_rounds_median(self):
        """判据窗口 = 近 5 轮的**中位数**（不是均值）—— 这个数字要被钉住。"""
        sense, _ = session()
        sense.start()
        for value in (100.0, 200.0, 300.0, 400.0, 500.0, 9000.0):
            sense.note_words("r0c0", [word("w")], value)
        self.assertAlmostEqual(sense.recent_cycle_ms, 400.0)   # 中位数，尖峰不算

    def test_three_errors_auto_pause(self):
        """§7.3「出错时自动暂停并提示，不允许后台异常线程无限重启」。"""
        sense, _ = session()
        sense.start()
        sense.note_error("ValueError: boom")
        self.assertEqual(sense.state, RUNNING)          # 一次不算事
        sense.note_error("ValueError: boom")
        self.assertEqual(sense.state, RUNNING)
        sense.note_error("ValueError: boom")
        self.assertEqual(sense.state, ERROR)
        self.assertEqual(sense.stats["errors"], 3)

    def test_success_resets_error_streak(self):
        sense, _ = session()
        sense.start()
        sense.note_error("a")
        sense.note_error("b")
        sense.note_success()
        sense.note_error("c")
        self.assertEqual(sense.state, RUNNING)

    def test_resume_from_error_clears_streak(self):
        sense, _ = session()
        sense.start()
        for _ in range(3):
            sense.note_error("x")
        self.assertEqual(sense.state, ERROR)
        sense.resume()
        self.assertEqual(sense.state, RUNNING)
        self.assertEqual(sense.note, "")


# ---------------------------------------------------------------- 状态与隐私
class TestStatusAndPrivacy(unittest.TestCase):
    def test_status_text_has_the_required_three_parts(self):
        """§7.3：要显示「感应中 · 本地识别 · 最近扫描时间」。"""
        sense, clock = session()
        self.assertIn("未开启", sense.status_text())
        sense.start()
        sense.note_words("r0c0", [word("anything")], 120.0)
        clock.advance(3.0)
        text = sense.status_text()
        self.assertIn("感应中", text)
        self.assertIn("本地识别", text)
        self.assertIn("最近扫描 3s 前", text)
        self.assertIn("1.0 次/秒", text)

    def test_status_and_perf_never_leak_screen_text(self):
        """★ 隐私硬要求（§7.3）：状态、perf、note 里不许出现屏幕上的词。"""
        sense, _ = session()
        sense.start()
        secret = "confidentialEmailSubject"
        sense.note_words("r0c0", [word(secret, meaning="一整句话的私人内容")], 50.0)
        sense.note_error("RuntimeError: 某个异常")
        blob = " ".join([sense.status_text(), repr(sense.perf()),
                        repr(sense.stats), sense.note, repr(list(sense._queue))])
        # 队列里**是**有词卡的（那是给覆盖层画的，属于内存，不是日志），
        # 所以只检查「对外显示/记录的那三份」。
        for piece in (sense.status_text(), repr(sense.perf()), sense.note):
            self.assertNotIn(secret, piece)

    def test_perf_shape_is_counts_and_timings_only(self):
        sense, _ = session()
        sense.start()
        sense.note_words("r0c0", [word("a")], 55.0)
        data = sense.perf()
        for key in ("state", "hz", "grid", "avg_cycle_ms", "p95_cycle_ms",
                    "cycles", "skipped_no_change", "ocr_runs", "notices",
                    "suppressed", "errors", "downshifts", "engine"):
            self.assertIn(key, data)
        self.assertEqual(data["avg_cycle_ms"], 55.0)

    def test_engine_fallback_shows_up_in_status(self):
        """§3.2：感应模式下引擎回退也必须看得见，不静默。"""
        sense, _ = session()
        sense.start()
        self.assertNotIn("回退", sense.status_text())
        sense.note_engine("rapid", "PaddleOCR 失败，本轮已回退 RapidOCR：boom")
        self.assertIn("已回退 RapidOCR", sense.status_text())
        sense.note_engine("paddle", "")
        self.assertIn("paddle", sense.status_text())

    def test_stop_clears_everything(self):
        """关闭要丢干净：下次再开不该带着上一次的冷却记录和队列。"""
        sense, _ = session()
        sense.start()
        sense.note_words("r0c0", [word("a", 100, 100), word("b", 200, 100)], 50.0)
        sense.stop()
        self.assertEqual(sense.state, OFF)
        self.assertEqual(sense._queue, [])
        self.assertEqual(len(sense._seen_words), 0)
        self.assertEqual(len(sense._roi_cache), 0)
        self.assertEqual(sense.note, "")
        # 再开一次：第一个词还能提示（没有被旧冷却压掉）
        sense.start()
        fresh = sense.note_words("r0c0", [word("a", 100, 100)], 50.0)
        self.assertEqual([w["surface"] for w in fresh], ["a"])

    def test_default_hz_is_the_unverified_starting_point(self):
        """§7.3：1~2 次/秒是**待测初值**，代码里不许写成「性能承诺」。"""
        self.assertEqual(SenseSession().hz, 1.0)
        self.assertGreaterEqual(SenseSession().hz, MIN_HZ)


if __name__ == "__main__":
    unittest.main(verbosity=2)
