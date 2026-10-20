# -*- coding: utf-8 -*-
"""§7 感应流水线的工作线程：假帧喂进 `SenseWorker.process`，验坐标与「不重启」。

这里**不抓屏幕、不跑真 OCR**（`ocr_adapter.engine_lines` 被换成假的行），
所以每条断言都稳定、毫秒级。测的是 §7.3 里最容易在真实环境里「看起来没问题」
的四件事：

    1. 没有变化就**一次 OCR 都不调**（节流是否真的生效）；
    2. ROI 裁的是那块格子（不是整屏），且坐标换算
       `屏幕逻辑坐标 = 虚拟桌面原点 + (ROI 偏移 + 词在 ROI 里的位置) / DPR`
       在 DPR≠1、原点≠0 时仍然对（多屏 / 缩放是唯一容易翻车的地方）；
    3. 处理不过来时**丢帧而不是排队**（否则提示的是三秒前的画面）；
    4. 连续出错 → 线程自己退出，**不重启**（§7.3 硬性要求）。

Qt 部分只用 `QCoreApplication`：`Signal.emit` 需要一个 app 实例，
但这里不建任何窗口，所以不涉及 `QT_QPA_PLATFORM=offscreen` 那个污染 OCR 字体的坑。
"""
import os
import sys
import time
import unittest

import numpy as np

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, SRC)

from PySide6.QtCore import QCoreApplication                      # noqa: E402

_APP = QCoreApplication.instance() or QCoreApplication(sys.argv)

from ocr_engine import OcrLine, OcrWord                          # noqa: E402
import ocr_adapter                                               # noqa: E402
from sense_session import ERROR, SenseSession                    # noqa: E402
from sense_worker import SenseWorker                             # noqa: E402

H, W = 120, 160                       # 4 列 × 3 行 → 每格 40×40
CELL_H, CELL_W = H // 3, W // 4
ORIGIN = (300.0, 200.0)               # 故意不用 (0,0)：多屏时桌面原点不为零
DPR = 1.5                             # 故意不用 1.0：缩放屏最容易把坐标算错


class Clock:
    def __init__(self, start=1000.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeLexicon:
    """词典桩：认识词表里的才返回，其余丢掉。

    真实 `lexicon.scan_text` 要 SQLite，而且按 lemma 去重 —— 那是 §5 的事。
    本文件只验「worker 怎么把词的坐标算出来、怎么调度」。
    """

    KNOWN = {"subtitle", "keyword", "lexara", "alpha", "beta"}

    def scan_text(self, text, mode=None, limit=8, skip_stopwords=True):
        out = []
        for token in text.replace("\n", " ").split():
            if token.lower() in self.KNOWN:
                out.append({"surface": token, "lemma": token.lower(),
                            "meaning": "假释义", "word_id": ""})
        return out[:limit]


def lines_of(text, words):
    """造 `OcrEngine.recognize_lines` 同形状的结果（坐标相对**被识别的那张 crop**）。

    `words` 里每项 = (text, cx, cy, left, right, top, bottom)。
    """
    return [OcrLine(text=text, box=(0, 0, 100, 20), score=0.99,
                    words=[OcrWord(text=t, cx=cx, cy=cy, left=l, right=r,
                                   top=tp, bottom=bt)
                           for (t, cx, cy, l, r, tp, bt) in words])]


class EngineStub:
    """替换 `ocr_adapter.engine_lines`：记录每次被喂进去的 crop 尺寸。"""

    def __init__(self):
        self.lines = []
        self.engine_id = "rapid"
        self.note = ""
        self.error = None
        self.calls = []               # (crop 高, crop 宽, crop 均值)

    def __call__(self, crop):
        self.calls.append((int(crop.shape[0]), int(crop.shape[1]),
                           float(crop.mean())))
        if self.error is not None:
            raise self.error
        return list(self.lines), self.engine_id, self.note


def textured(frame):
    """给假帧铺一层「像屏幕内容」的明暗纹理。

    ★ 为什么需要：`SenseWorker._is_blank` 会把**一片纯色**的 ROI 挡在 OCR 之前
      （实测一张 1920×1080 的空白整帧单轮 10029ms —— 读不出东西时引擎会把
      「多档缩放 × 对比度/二值化」的回退阶梯全跑完，而同一帧有字幕时 1280ms）。
      纯灰色的假帧正好会被那道闸挡住，那是被测对象的正确行为，
      但本文件绝大多数断言走的是「这块有内容」这条路，所以假帧必须有对比度。
      「一片纯色到底跳过不跳过」另有专门的测试（`test_uniform_roi_is_skipped`）。
    """
    out = frame.copy()
    dark = np.clip(out[:, ::8].astype(np.int32) - 70, 0, 255).astype(np.uint8)
    out[:, ::8] = dark
    light = np.clip(out[::6, :].astype(np.int32) + 55, 0, 255).astype(np.uint8)
    out[::6, :] = light
    return out


def blank(value=200):
    """RGB 帧（`qimage_to_ndarray` 交给 worker 的就是这个形状）。"""
    return textured(np.full((H, W, 3), value, np.uint8))


def gray_of(array):
    """和 worker 里 `cv2.cvtColor(RGB2GRAY)` 等价的灰度（测试不必真调 cv2）。"""
    return array[..., 0].copy()


def with_cell(array, row, col, value):
    frame = array.copy()
    frame[row * CELL_H:(row + 1) * CELL_H,
          col * CELL_W:(col + 1) * CELL_W] = value
    return frame


def make_worker():
    clock = Clock()
    session = SenseSession(clock=clock, mode="cet4", limit=8)
    session.start()
    worker = SenseWorker(session, FakeLexicon(), min_conf=0.0,
                         mode="cet4", limit=8, skip_stopwords=False)
    seen = []
    worker.notice.connect(lambda item: seen.append(item))
    return worker, session, clock, seen


class TestSenseWorkerPipeline(unittest.TestCase):
    """直接调 `process()`：不起线程、不抓屏，只验流水线本身。"""

    def setUp(self):
        self.stub = EngineStub()
        self._real = ocr_adapter.engine_lines
        ocr_adapter.engine_lines = self.stub

    def tearDown(self):
        ocr_adapter.engine_lines = self._real

    def cycle(self, worker, array, clock, origin=ORIGIN, dpr=DPR):
        """喂一帧（缩放 1.0：缩略图就是这一帧本身，坐标好核对）。"""
        worker.process(gray_of(array), 1.0, array, origin, dpr, now=clock())

    def test_first_frame_is_one_full_frame_ocr(self):
        """开感应的第一帧没有参照 → 整帧扫一次，这是「开启」的一次性成本。"""
        worker, session, clock, _seen = make_worker()
        frame = blank()
        self.cycle(worker, frame, clock)
        self.assertEqual(self.stub.calls, [(H, W, float(frame.mean()))])
        self.assertEqual(session.stats["full_frame"], 1)

    def test_static_screen_calls_no_ocr(self):
        """§7.4 的根因层：画面没变就一次引擎都不调。"""
        worker, session, clock, seen = make_worker()
        frame = blank()
        self.cycle(worker, frame, clock)
        self.stub.calls.clear()
        for _ in range(10):
            clock.advance(1.0)
            self.cycle(worker, frame, clock)
        self.assertEqual(self.stub.calls, [])
        self.assertEqual(session.stats["skipped_no_change"], 10)
        self.assertEqual(len(seen), 0)

    def test_uniform_roi_is_skipped_and_counted(self):
        """★ 一片纯色的 ROI 不进 OCR，但要**留下计数**（不是静默跳过）。

        这道闸的动机是实测数字：`tools/sense_bench.py` 里一张 1920×1080 的
        **空白整帧**单轮 10029ms，而同一尺寸带字幕的整帧是 1280ms ——
        读不出东西时引擎会把「多档缩放 × 对比度/二值化」的回退阶梯全跑完，
        所以「屏幕上暂时没有内容」恰好是**最贵**的一种帧，必须先挡掉。
        阈值 2.0 定在实测的两头之间（纯色 0.0 / 最矮有内容的那条 16.1），
        这里同时验「屏幕又出现内容」的下一轮照常跑，别让闸门变成漏词。
        """
        worker, session, clock, _seen = make_worker()
        self.cycle(worker, blank(), clock)             # 有内容的桌面（建基准）
        self.stub.calls.clear()
        runs = session.stats["ocr_runs"]               # 上面那一轮整帧扫过一次
        clock.advance(1.0)
        fade = np.full((H, W, 3), 250, np.uint8)       # 淡出成一片纯色
        self.cycle(worker, fade, clock)
        self.assertEqual(self.stub.calls, [])                      # 没喂进引擎
        self.assertEqual(session.stats["skipped_blank"], 1)        # 但计了数
        self.assertEqual(session.stats["ocr_runs"], runs)          # 一轮 OCR 都没多
        clock.advance(1.0)
        self.cycle(worker, blank(240), clock)          # 又出现内容了
        self.assertEqual(len(self.stub.calls), 1)                  # 该跑的还跑
        self.assertEqual(session.stats["skipped_blank"], 1)

    def test_mid_round_pause_still_reaches_the_ui(self):
        """★ 一轮**中途**被预算停掉时，也要把状态发回主线程。

        这是 `tools/sense_bench.py` 量出来的那条：一个 ~10s 的尖峰让会话在一轮
        跑到第二个 ROI 时自动暂停，`process()` 当场 `return`，`perf` 信号一个都没
        发 —— 界面还挂着「感应中」，队列里 5 个新词一个都不闪。
        现在停下来的那条路必须先把状态送到主线程。
        """
        import sense_worker as worker_module

        class SlowTime:
            """假时钟：每次 `time()` 走 3 秒 → `_recognize` 量到 3000ms 单轮耗时。"""

            def __init__(self):
                self.t = 1000.0

            def time(self):
                self.t += 3000.0
                return self.t

            def monotonic(self):
                return self.t / 1000.0

            def sleep(self, seconds):
                self.t += seconds * 1000.0

        session = SenseSession(clock=lambda: 5000.0, budget_ms=1200.0, hz=2.0)
        session.start()
        for _ in range(3):                       # 先把窗口填成「追不上」的样子
            session.note_words("seed", [{"surface": "seed"}], 3000.0)
        self.assertAlmostEqual(session.hz, 0.4)  # 已到下限，还在跑
        self.assertEqual(session.state, "running")
        worker = SenseWorker(session, FakeLexicon(), min_conf=0.0,
                             mode="cet4", limit=8, skip_stopwords=False)
        self.stub.lines = lines_of("alpha", [("alpha", 10.0, 8.0, 0.0, 20.0,
                                              0.0, 16.0)])
        self.stub.engine_id = "rapid"
        perf_states, notices = [], []
        worker.perf.connect(lambda p: perf_states.append(p["state"]))
        worker.notice.connect(lambda item: notices.append(item))

        array = textured(np.full((H, W, 3), 200, np.uint8))
        # 先替会话建好「上一帧」基准：这一步不花 OCR 时间，所以不会把假耗时算进去
        session.ingest(gray_of(array), now=5000.0, pixel_scale=1.0)
        # 两块**相距很远**的变化格子 → `_roi_boxes` 并不起来 → 一轮两次 OCR
        array[0:CELL_H, 0:CELL_W] = 30
        array[2 * CELL_H:3 * CELL_H, 3 * CELL_W:4 * CELL_W] = 60

        real_time = worker_module.time
        worker_module.time = SlowTime()          # 让这一轮的 OCR 显得很慢
        try:
            worker.process(gray_of(array), 1.0, array, (0.0, 0.0), 1.0,
                           now=5000.0)
        finally:
            worker_module.time = real_time
        self.assertEqual(len(self.stub.calls), 1)        # 第二块没跑（停下来才是要测的）
        self.assertEqual(session.state, "paused")
        self.assertIn("paused", perf_states)     # ★ 状态真的送到了主线程
        self.assertEqual(len(notices), 0)        # 停下来那一轮不再闪新词

    def test_warmup_cost_is_not_counted_as_a_round(self):
        """引擎预热的一次性开销**不许**进延迟预算（否则会被误判成机器跟不上）。"""
        from ocr_engine import OcrEngine
        worker, session, _clock, _seen = make_worker()
        real_warmup = OcrEngine.warmup
        calls = []
        try:
            def fake_warmup(cls):
                calls.append(cls)
                time.sleep(0.02)
            OcrEngine.warmup = classmethod(fake_warmup)
            worker._warm_engine()
        finally:
            OcrEngine.warmup = real_warmup
        self.assertEqual(calls, [OcrEngine])
        self.assertGreater(worker.warmup_ms, 0.0)
        self.assertEqual(session.cycle_ms, [])            # 一轮 OCR 都没算
        self.assertEqual(session.stats["ocr_runs"], 0)
        self.assertEqual(session.hz, session.hz_start)     # 频率也没被动过

    def test_roi_crop_is_the_changed_cell_not_the_whole_screen(self):
        """只有一格变了 → 引擎只吃那一块（含一点余量），不是整屏。"""
        worker, _session, clock, _seen = make_worker()
        base = blank()
        self.cycle(worker, base, clock)
        self.stub.calls.clear()
        clock.advance(1.0)
        changed = with_cell(base, 1, 2, 40)
        self.cycle(worker, changed, clock)
        self.assertEqual(len(self.stub.calls), 1)
        ch, cw, _mean = self.stub.calls[0]
        self.assertGreaterEqual(ch, CELL_H)          # `roi_box` 留了上下余量
        self.assertLess(ch, H)                       # 但绝不等于整屏
        self.assertGreaterEqual(cw, CELL_W)
        self.assertLess(cw, W)

    def test_screen_position_formula(self):
        """★ 核心坐标断言：原点≠0、DPR≠1、词在 ROI 内部，三件事叠在一起。

        词中心在 crop 里是 (20,10)，crop 左上角 = `session.roi_box("r1c2")`
        → 屏幕逻辑坐标必须是 `原点 + (ROI 偏移 + 词在 ROI 里的位置) / DPR`。
        少除一个 DPR、或者忘了加 ROI 偏移，射线就会画到词旁边的空白上 ——
        那正是「看着像踩空」的成因。
        """
        worker, session, clock, seen = make_worker()
        base = blank()
        self.cycle(worker, base, clock)              # 建立参照（整帧，无词）
        clock.advance(1.0)
        self.stub.lines = lines_of(
            "subtitle", [("subtitle", 20.0, 10.0, 0.0, 40.0, 2.0, 18.0)])
        changed = with_cell(base, 1, 2, 30)
        x, y, _bw, _bh = session.roi_box("r1c2", (W, H))
        self.cycle(worker, changed, clock)
        self.assertEqual(len(seen), 1)
        item = seen[0]
        self.assertEqual(item["surface"], "subtitle")
        self.assertAlmostEqual(item["screen_pos"][0],
                               ORIGIN[0] + (x + 20.0) / DPR)
        self.assertAlmostEqual(item["screen_pos"][1],
                               ORIGIN[1] + (y + 10.0) / DPR)
        box = item["screen_box"]
        self.assertIsNotNone(box)
        self.assertAlmostEqual(box[0], ORIGIN[0] + (x + 0.0) / DPR)
        self.assertAlmostEqual(box[1], ORIGIN[1] + (y + 2.0) / DPR)
        self.assertAlmostEqual(box[2], 40.0 / DPR)   # 宽
        self.assertAlmostEqual(box[3], 16.0 / DPR)   # 高

    def test_roi_is_tightened_to_the_line_that_changed(self):
        """★ ROI 要**收到真有字的那几行**再喂 OCR —— 本机实测差 15 倍。

        `tools/sense_roi_probe.py` 在同一张假字幕帧上量到：

            1920x432 的并集框（一整行格子 + 上下余量）→ 引擎调用 7 次 · 均 3575ms
            1920x65  贴着字幕行收出来              → 引擎调用 1 次 · 均  200ms

        而**挑出来的词一个都没少**（七个全在）。贵的不是面积，是形状：
        「中等高度、里面只有一行字」的裁片会被 `OcrEngine` 切成多个行带，
        每带再把「直送 → 放大 → 切条」的阶梯跑完；贴着字的那一条第 0 档就读干净了。
        这里验两件事：喂进引擎的 crop 真的变矮了，**且词的屏幕坐标跟着偏移修正**
        —— 收上去却忘了把 `y` 加回来，射线会画到词上方十几像素处。
        """
        worker, _session, clock, seen = make_worker()
        base = np.full((H, W, 3), 200, np.uint8)
        self.cycle(worker, base, clock)               # 第一帧：建立参照
        self.stub.calls.clear()
        clock.advance(1.0)
        band = base.copy()
        band[56:64, ::4] = 20                          # 只有这一条横带有内容
        self.stub.lines = lines_of(
            "subtitle", [("subtitle", 20.0, 4.0, 0.0, 40.0, 0.0, 8.0)])
        self.cycle(worker, band, clock)

        self.assertEqual(len(self.stub.calls), 1)
        ch, cw, _mean = self.stub.calls[0]
        self.assertEqual(cw, W)                        # 横向不动：宽条本来就是便宜的形状
        self.assertLess(ch, 40, "收紧后应当明显矮于一整行格子（含余量 56px）")
        self.assertGreaterEqual(ch, 8 + 2 * SenseWorker.TIGHT_MARGIN,
                                "上下各要留 `TIGHT_MARGIN`，不然会切掉升降部")
        self.assertEqual(worker.trim_count, 1)
        item = seen[0]
        # 词在**收紧后**的 crop 里是 (20, 4)，crop 左上角 = (0, 32+12=44)
        self.assertAlmostEqual(item["screen_pos"][0], ORIGIN[0] + (0 + 20.0) / DPR)
        self.assertAlmostEqual(item["screen_pos"][1], ORIGIN[1] + (44 + 4.0) / DPR)
        self.assertAlmostEqual(item["screen_box"][1], ORIGIN[1] + (44 + 0.0) / DPR)

    def test_full_frame_round_is_tightened_too(self):
        """★ 整帧那一轮**也**要按行段切：以前「整帧不收紧」是这台机器上最贵的一轮。

        旧断言写的是「整帧恰好是引擎最便宜的形状」，那是**合成帧**上的结论
        （`tools/sense_bench.py` 造的 1080p 假字幕帧：整帧 1300ms、
        并集带不收紧 3866ms）。真桌面反过来 —— `tools/sense_shape_probe.py`
        在同一张帧上量到：

            整帧      2560x1600                → 13846~18966ms（一次调用）
            整帧横切  1600x933 ×3              → 4415 · 4287 · 5599ms
            一格      498x460（10 行）         → 1541ms

        成本看的是**这一段里有几行字**（识别是逐行花的），不是像素面积。
        所以「整屏都在换」不能拿一整块 1600 行去赌：切段之后一轮只读
        `MAX_BANDS_PER_ROI` 段，剩下的段顺延（见下面那个测试）。
        """
        worker, session, clock, _seen = make_worker()
        frame = np.full((H, W, 3), 200, np.uint8)
        frame[56:64, ::4] = 20                     # 整帧里唯一的字幕横带
        self.cycle(worker, frame, clock)           # 第一帧 = 整帧建基准那一轮
        self.assertEqual(session.stats["full_frame"], 1)
        self.assertEqual(len(self.stub.calls), 1)  # 一轮只读一段（其余段没内容）
        ch, cw, _mean = self.stub.calls[0]
        self.assertLess(ch, H, "整帧那一轮喂进引擎的应当是贴着字的那一条，"
                              "不是 120 行高的整帧")
        self.assertGreaterEqual(ch, 8 + 2 * SenseWorker.TIGHT_MARGIN)
        self.assertEqual(worker.trim_count, 1)

    def test_a_tall_roi_is_finished_over_several_rounds(self):
        """★ 一轮读不完的行段**顺延**，下一轮即使画面没变也接着读。

        这条测的是「切段」最容易做错的一半：段读不完时，那些格子在
        `_prev_gray` 里已经是「看过」的状态，画面不再变就再也不会唤醒 OCR ——
        没有顺延表，切段就从「省时间」变成**静默漏词**（比慢更糟）。
        这里把段的长度调小（`TIGHT_MAX_ROWS=12`、一轮只跑 2 段），
        让一块 48 行高的 ROI 切成 4 段，然后用两轮把它读完。
        """
        worker, session, clock, _seen = make_worker()
        worker.MAX_BANDS_PER_ROI = 2               # 一轮只跑两段（实例属性）
        worker.round_budget_ms = 10 ** 6           # 本轮不看时间，只看段数
        base = np.full((H, W, 3), 200, np.uint8)
        self.cycle(worker, base, clock)            # 建立参照
        self.stub.calls.clear()
        clock.advance(1.0)
        frame = base.copy()
        # 顶部 48 行整条都有字（`::3` 的条纹：`_is_blank` 按 4 倍降采样，
        # 用 `::4` 会和条纹**对齐**成一片纯色，那是假帧的坑、不是被测行为）
        frame[0:CELL_H, 0:CELL_W] = 30
        frame[0:48, ::3] = 20
        saved = (SenseWorker.TIGHT_MARGIN, SenseWorker.TIGHT_MAX_ROWS,
                 SenseWorker.TIGHT_BAND_OVERLAP)
        SenseWorker.TIGHT_MARGIN, SenseWorker.TIGHT_MAX_ROWS = 0, 12
        SenseWorker.TIGHT_BAND_OVERLAP = 0
        try:
            self.cycle(worker, frame, clock)
            first = len(self.stub.calls)
            self.assertEqual(first, 2, "一段 48 行 ROI 切 4 段，一轮只跑两段")
            self.assertEqual(session.pending_deferred(), 1,
                             "没读完的那块必须进了顺延表")
            # 画面**完全不动**的第二轮：靠顺延表接着读，而不是「没变化就收工」
            self.stub.calls.clear()
            clock.advance(1.0)
            self.cycle(worker, frame, clock)
            self.assertEqual(len(self.stub.calls), 2,
                             "剩下两段要在第二轮读完")
            self.assertEqual(session.pending_deferred(), 0,
                             "读完了就必须从顺延表里出去，不然一轮比一轮长")
        finally:
            (SenseWorker.TIGHT_MARGIN, SenseWorker.TIGHT_MAX_ROWS,
             SenseWorker.TIGHT_BAND_OVERLAP) = saved

    def test_round_budget_defers_the_rest_of_the_boxes(self):
        """一轮的 OCR 时间超过轮预算就**整块顺延**，不把「一轮喂太多」记成机器慢。

        §7.4 要「超预算自动降频或提示」，但以前降频的输入是**整轮**的 OCR 耗时：
        真桌面上把 6 块格子 + 一整帧都塞进一轮，一轮 9~19 秒（实测），
        于是判据说「这台机器连 0.4 次/秒都追不上」→ 自动暂停。
        现在一轮最多花 `round_budget_ms`，多出来的块进顺延表。
        """
        worker, session, clock, _seen = make_worker()
        worker.round_budget_ms = 10.0              # 一眨眼就超：逼出顺延
        base = np.full((H, W, 3), 200, np.uint8)
        self.cycle(worker, base, clock)
        self.stub.calls.clear()
        clock.advance(1.0)
        frame = base.copy()
        # 两块**离得很远**的变化格子 → 并不起来 → 本来要各跑一次 OCR
        frame[0:CELL_H, 0:CELL_W] = 30
        frame[2 * CELL_H:3 * CELL_H, 3 * CELL_W:4 * CELL_W] = 60
        real = worker._recognize

        def slow(crop, offset, origin, dpr):
            # ★ 耗时必须从 `_recognize` 的**返回值**里来：`time.sleep()` 计不进
            #   `_recognize` 自己测的 `elapsed_ms`（它在返回值里带出来的那段才算），
            #   第一版在这里 sleep → `spent` 一直是 0 → 顺延根本没被踩到。
            items, _ms = real(crop, offset, origin, dpr)
            return items, 25.0                 # 假装这一段花了 25ms（轮预算 10ms）
        worker._recognize = slow
        try:
            self.cycle(worker, frame, clock)
        finally:
            worker._recognize = real
        self.assertEqual(worker.round_deferred, 1, "轮预算必须触发过一次整块顺延")
        self.assertGreaterEqual(session.stats["roi_deferred"], 1)
        # 顺延的块在下一轮（画面不动）也要被读掉
        self.stub.calls.clear()
        clock.advance(1.0)
        worker._recognize = real
        self.cycle(worker, frame, clock)
        self.assertGreaterEqual(len(self.stub.calls), 1,
                                "上一轮被预算挡在门外的块，这一轮必须补读")

    def test_tighten_only_when_it_really_shrinks_the_box(self):
        """`_tighten_crop` 的三种「不收」：太小的图 / 一段内容都没有 / 行列都收不掉。"""
        flat = np.full((60, 200, 3), 180, np.uint8)
        self.assertIsNone(SenseWorker._tighten_crop(flat))    # 全平 → 交给 `_is_blank`

        tiny = np.zeros((10, 200, 3), np.uint8)
        self.assertIsNone(SenseWorker._tighten_crop(tiny))     # 太小，别抖

        busy = np.full((120, 200, 3), 180, np.uint8)
        busy[:, ::4] = 40                     # 每行每列都有对比 → 收了等于没收
        self.assertIsNone(SenseWorker._tighten_crop(busy))

        one = np.full((120, 200, 3), 180, np.uint8)
        one[50:58, ::4] = 40
        got = SenseWorker._tighten_crop(one)
        self.assertIsNotNone(got)
        top, height, left, width = got
        self.assertEqual(top, 50 - SenseWorker.TIGHT_MARGIN)
        self.assertEqual(top + height, 58 + SenseWorker.TIGHT_MARGIN)
        # 这条横带是通栏的：列跨度覆盖 0~199，收不出东西，宽度保持原样
        self.assertEqual((left, width), (0, 200))

    def test_tighten_crops_the_columns_too(self):
        """★ 列也要收：真桌面上「只收行」能把字幕那句**整个读丢**。

        `tools/sense_card_probe.py` 在同一帧上量到的（2026-10-18，本机）：

            并集带 1970x642        → 读到 38 行小字，句子一个词都没有 · 3454ms
            只收行  1970x393        → 读到整句 · 3401ms
            只收列  1428x642        → 读到整句 · 2106ms
            行列都收 1428x393       → 读到整句 ·  922ms
            整帧    2560x1600       → 读到整句 · 13846ms

        机制在 `OcrEngine` 的检测前缩放：长边一律压到 `DET_LIMIT=736`，
        1970 宽的带 → 系数 0.37，42px 高的字变成 16px，掉到检测器认不出的量级；
        收到 1428 宽 → 系数 0.51，同一行字留在可检测尺寸上。
        所以列向收窄不是「省面积」，是**保住字的尺寸**，顺带把同行里的小字切掉。
        """
        crop = np.full((120, 400, 3), 180, np.uint8)
        crop[50:60, 100:200] = 40              # 内容只在这块 100x20 的窗口里
        crop[60:70, 100:200] = 96              # 上下两档 → 有字的那些列**沿 y 有起伏**
        got = SenseWorker._tighten_crop(crop)
        self.assertIsNotNone(got)
        top, height, left, width = got
        self.assertEqual(top, 50 - SenseWorker.TIGHT_MARGIN)
        self.assertEqual(top + height, 70 + SenseWorker.TIGHT_MARGIN)
        self.assertEqual(left, 100 - SenseWorker.TIGHT_MARGIN)
        self.assertEqual(left + width, 200 + SenseWorker.TIGHT_MARGIN)

    def test_tighten_ignores_a_one_row_cursor_line(self):
        """一两行的亮点（鼠标光标、进度条）不该把首尾跨度撑满。

        ★ 这正是旧版「首尾跨度 + 收不掉 90% 就不收」在真桌面上失效的原因：
          带里只要有一两个亮点行，跨度就顶到整条带 → `return None` →
          喂进 OCR 的还是那条最贵、又读不到字的 1970x642 大带。
          现在按**亮点段**挑内容：厚度不到 `TIGHT_MIN_SPAN` 的段不算内容。
        """
        crop = np.full((200, 300, 3), 240, np.uint8)
        crop[90:130, 40:260:3] = 30            # 正文：厚 40 行
        crop[5, :] = 0                          # 一根亮线（光标）：只占一行
        top, height, left, width = SenseWorker._tighten_crop(crop)
        self.assertEqual(top, 90 - SenseWorker.TIGHT_MARGIN)
        self.assertEqual(top + height, 130 + SenseWorker.TIGHT_MARGIN)
        self.assertLess(height, 200 * 0.5, "光标那行不该把跨度顶满")

    def test_thumbnail_scale_is_divided_out_before_cropping(self):
        """4K 屏先缩到 1280 宽再做变化检测；裁的必须是**全分辨率**那一帧。"""
        worker, session, clock, seen = make_worker()
        # ★ `big` 必须**有纹理**：`SenseWorker._is_blank` 会把一片纯色的 ROI 挡在
        #   OCR 前面（实测那种帧最贵），而这里验的是「裁的是全分辨率那一块、
        #   坐标按 scale 乘回去」，所以喂进去的得是「有内容」的帧。
        big = textured(np.full((H * 2, W * 2, 3), 128, np.uint8))
        small = np.full((H, W), 128, np.uint8)
        worker.process(small, 0.5, big, (0, 0), 1.0, now=clock())
        self.stub.calls.clear()
        clock.advance(1.0)
        # 缩略图（120×160）里只有 r1c2 变了，scale=0.5 → 全帧坐标要 ×2
        moved = small.copy()
        moved[CELL_H:2 * CELL_H, 2 * CELL_W:3 * CELL_W] = 20
        x, y, bw, bh = session.roi_box("r1c2", (W, H))
        self.stub.lines = lines_of("alpha",
                                   [("alpha", 10.0, 8.0, 0.0, 20.0, 0.0, 16.0)])
        worker.process(moved, 0.5, big, (0, 0), 1.0, now=clock())
        ch, cw, _ = self.stub.calls[0]
        self.assertEqual((ch, cw), (bh * 2, bw * 2))
        item = seen[0]
        self.assertAlmostEqual(item["screen_pos"][0], x * 2 + 10.0)
        self.assertAlmostEqual(item["screen_pos"][1], y * 2 + 8.0)

    def test_same_roi_same_content_does_not_notify_again(self):
        """同一块内容被扫第二遍 → 不重复提示（§7.4「静态画面不无限提示」）。"""
        worker, session, clock, seen = make_worker()
        base = blank()
        self.cycle(worker, base, clock)
        self.stub.lines = lines_of(
            "keyword", [("keyword", 12.0, 9.0, 0.0, 24.0, 1.0, 17.0)])
        clock.advance(1.0)
        self.cycle(worker, with_cell(base, 1, 2, 40), clock)
        self.assertEqual(len(seen), 1)
        clock.advance(1.0)
        # 同一格再动一下（触发检测），但 OCR 读到的还是那句 keyword
        self.cycle(worker, with_cell(base, 1, 2, 90), clock)
        self.assertEqual(len(seen), 1)
        self.assertEqual(session.stats["notices"], 1)

    def test_new_content_is_notified(self):
        """同一格换了新内容 → 必须算新目标（视频字幕场景的核心）。"""
        worker, _session, clock, seen = make_worker()
        base = blank()
        self.cycle(worker, base, clock)
        self.stub.lines = lines_of("alpha",
                                   [("alpha", 10.0, 8.0, 0.0, 20.0, 0.0, 16.0)])
        clock.advance(1.0)
        self.cycle(worker, with_cell(base, 0, 1, 40), clock)
        self.stub.lines = lines_of("beta",
                                   [("beta", 10.0, 8.0, 0.0, 20.0, 0.0, 16.0)])
        clock.advance(1.0)
        self.cycle(worker, with_cell(base, 0, 1, 90), clock)
        self.assertEqual([w["surface"] for w in seen], ["alpha", "beta"])

    def test_engine_fallback_is_recorded_not_silent(self):
        """§3.2：感应模式里引擎回退也要落到状态里，界面才说得出真话。"""
        worker, session, clock, _seen = make_worker()
        self.stub.engine_id = "rapid"
        self.stub.note = "PaddleOCR 失败，本轮已回退 RapidOCR：构造失败"
        self.cycle(worker, blank(), clock)
        self.assertEqual(session.engine_id, "rapid")
        self.assertIn("已回退 RapidOCR", session.engine_note)
        self.assertIn("已回退 RapidOCR", session.status_text())

    def test_min_conf_filters_low_score_words(self):
        """启动台的「最小置信度」在感应链路里同样生效。"""
        worker, _session, clock, seen = make_worker()
        base = blank()
        self.cycle(worker, base, clock)
        self.stub.calls.clear()
        self.stub.lines = lines_of("subtitle",
                                   [("subtitle", 20.0, 10.0, 0.0, 40.0,
                                     2.0, 18.0)])
        self.stub.lines[0].score = 0.40
        worker.min_conf = 0.6
        clock.advance(1.0)
        self.cycle(worker, with_cell(base, 2, 2, 20), clock)
        self.assertEqual(len(self.stub.calls), 1)    # 跑了一次 OCR
        self.assertEqual(len(seen), 0)               # 但低置信度没出词
        worker.min_conf = 0.0
        clock.advance(1.0)
        self.cycle(worker, with_cell(base, 2, 2, 60), clock)
        self.assertEqual(len(seen), 1)               # 放开阈值就出词

    def test_queued_words_drain_even_while_screen_is_static(self):
        """一批里挑出多个词 → 后面画面**完全不动**也要一个一个闪完。

        §7.2 要的是「逐个目标闪」。以前这一步挂在
        `if not roi_keys and not full_frame: return` 后面，于是「一句字幕里
        有 4 个考纲词」只会闪第 1 个，剩下 3 个要等下一条字幕才出来 ——
        静屏时队列直接冻住。这条就是那个回归的钉子：
        **不许有多余的 OCR，但提示必须排空。**
        """
        worker, session, clock, seen = make_worker()
        base = blank()
        self.cycle(worker, base, clock)
        self.stub.lines = lines_of("alpha beta keyword subtitle", [
            ("alpha", 10.0, 8.0, 0.0, 20.0, 0.0, 16.0),
            ("beta", 30.0, 8.0, 20.0, 40.0, 0.0, 16.0),
            ("keyword", 50.0, 8.0, 40.0, 60.0, 0.0, 16.0),
            ("subtitle", 70.0, 8.0, 60.0, 80.0, 0.0, 16.0)])
        clock.advance(1.0)
        frame = with_cell(base, 1, 2, 40)
        self.cycle(worker, frame, clock)
        self.assertEqual(len(seen), 1)               # 这一轮只闪一个（§7.2）
        self.assertEqual(session.pending_notices(), 3)
        self.stub.calls.clear()
        for _ in range(4):
            clock.advance(1.0)
            self.cycle(worker, frame, clock)         # 画面一模一样：不该再跑 OCR
        self.assertEqual(self.stub.calls, [])
        self.assertEqual([w["surface"] for w in seen],
                         ["alpha", "beta", "keyword", "subtitle"])
        self.assertEqual(session.pending_notices(), 0)

    def test_frames_are_dropped_not_queued(self):
        """§7.1「丢帧而不是排队」：处理不过来时旧帧丢掉，并如实计数。"""
        worker, _session, _clock, _seen = make_worker()
        for _ in range(5):
            worker.submit(blank(), (0, 0), 1.0, 0.012)
        self.assertEqual(worker.dropped, 4)
        self.assertIsNotNone(worker._frame)      # 留下的是**最新**那一帧
        worker.submit(None, (0, 0), 1.0)         # 空帧直接忽略
        self.assertEqual(worker.dropped, 4)
        self.assertEqual(worker.capture_ms, 0.012)


class TestSenseWorkerThread(unittest.TestCase):
    """真起线程：验「出错自动暂停 + 绝不重启」和「关了立刻退出」。"""

    def setUp(self):
        self._real = ocr_adapter.engine_lines

    def tearDown(self):
        ocr_adapter.engine_lines = self._real

    def test_repeated_errors_stop_thread_without_restart(self):
        """§7.3：出错自动暂停，**不允许**后台异常线程无限重启。

        ★ 这里每帧都要**真的动起来**：只有「跑了 OCR 且抛异常」才记一次错，
          没变化的帧不算错误、也不算成功（否则坏一次、静一帧、计数归零，
          永远凑不满 3 次 —— 这条实现细节就是这组帧喂出来的）。
        """
        def boom(_crop):
            raise ValueError("识别失败：这段异常文本不会被整条搬进日志")

        ocr_adapter.engine_lines = boom
        session = SenseSession(clock=Clock())
        session.start()
        worker = SenseWorker(session, FakeLexicon())
        faults, notices = [], []
        worker.fault.connect(lambda text: faults.append(text))
        worker.notice.connect(lambda item: notices.append(item))
        worker.start()
        base = blank()
        frames = [with_cell(base, i % 3, (i + 1) % 4, 40 + 9 * i)
                  for i in range(12)]
        try:
            deadline = time.time() + 20.0
            index = 0
            while time.time() < deadline and session.state != ERROR:
                worker.submit(frames[index % len(frames)], ORIGIN, DPR)
                index += 1
                ticks = 0
                while session.state != ERROR and ticks < 40:
                    ticks += 1
                    time.sleep(0.05)
                    QCoreApplication.processEvents()
            self.assertEqual(session.state, ERROR,
                             "连续 %d 帧识别失败仍未自动暂停（errors=%s）"
                             % (index, session.stats["errors"]))
            self.assertGreaterEqual(session.stats["errors"], 3)
            # 线程自己结束，不是「暂停后继续空转抓屏」
            self.assertTrue(worker.wait(8000), "出错后线程没有退出")
            self.assertFalse(worker.isRunning())
            count = len(notices)
            time.sleep(0.3)
            QCoreApplication.processEvents()
            self.assertEqual(len(notices), count)      # 不会偷偷重启再提示
            self.assertTrue(faults)
            # 只截断到 160 字符 + 异常类型，日志不会整条搬运屏幕内容
            for text in faults:
                self.assertLessEqual(len(text), 200)
        finally:
            worker.stop_sense()
            worker.wait(5000)

    def test_skipped_frames_do_not_reset_the_error_streak(self):
        """「没变化」的帧不能算成功：否则坏一次、静一帧 → 永远暂停不下来。"""
        def flaky(_crop):
            raise RuntimeError("引擎挂了")

        ocr_adapter.engine_lines = flaky
        session = SenseSession(clock=Clock())
        session.start()
        worker = SenseWorker(session, FakeLexicon())
        base = blank()
        for i in range(3):
            moved = with_cell(base, 1, 1, 40 + 30 * i)
            for frame in (moved, moved):        # 第二遍同一帧 → 判定为没变化
                try:
                    worker.process(gray_of(frame), 1.0, frame, ORIGIN, DPR)
                except RuntimeError as error:   # `run()` 里由 handle_error 收
                    worker.handle_error(error)
        self.assertEqual(session.stats["ocr_runs"], 0)
        self.assertGreaterEqual(session.stats["errors"], 3)
        self.assertEqual(session.state, ERROR)
        self.assertTrue(worker._stop)           # 到上限就把线程停下来
        # 三次「同一帧再来一遍」里前两次算跳过；第三次会话已经是 error 状态，
        # `ingest` 在计数之前就返回了（暂停中不该再记任何轮次）。
        self.assertEqual(session.stats["skipped_no_change"], 2)

    def test_stop_sense_ends_thread_promptly(self):
        """§7.2「关闭后停止捕获和工作线程」：`stop_sense()` + `wait()` 真退出。"""
        ocr_adapter.engine_lines = lambda _arr: ([], "rapid", "")
        session = SenseSession(clock=Clock())
        session.start()
        worker = SenseWorker(session, FakeLexicon())
        worker.start()
        self.assertTrue(worker.isRunning())
        worker.submit(blank(), (0, 0), 1.0)
        time.sleep(0.1)
        QCoreApplication.processEvents()
        worker.stop_sense()
        self.assertTrue(worker.wait(5000), "感应线程没有退出")
        self.assertFalse(worker.isRunning())
        self.assertIsNone(worker._frame)       # 待处理帧也一并释放

    def test_worker_thread_does_not_touch_gui_objects(self):
        """线程边界（§7.3）：`run()` 里不建窗口、不抓屏。用源码钉住这条约定。"""
        import inspect
        import sense_worker
        for name in ("run", "process", "_recognize"):
            source = inspect.getsource(getattr(SenseWorker, name))
            for banned in ("QWidget", "QMessageBox", "grabWindow",
                           "grab_virtual_desktop", "setStyleSheet"):
                self.assertNotIn(banned, source,
                                 "%s 里出现了 %s（属于 GUI 线程的活）"
                                 % (name, banned))
        self.assertTrue(hasattr(sense_worker.SenseWorker, "submit"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
