# -*- coding: utf-8 -*-
"""排障探针：`tools/sense_e2e.py` [3] 红了 —— 字幕窗口里的词为什么没被提示。

只加日志、不改产品代码：把「哪几格被判定变了 → 裁了哪一块 → 引擎读到几行 →
提示落在哪个坐标」四步全部打出来，对照字幕窗口的逻辑矩形。

跑法：``python tools/sense_coord_probe.py``（要真桌面，和 e2e 一样）
★ 隐私：只打坐标、尺寸与计数，**不打屏内容、不打识别到的句子文本**。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

SANDBOX = os.path.join(tempfile.gettempdir(), "lexara_coord_probe")
os.makedirs(SANDBOX, exist_ok=True)
os.environ["APPDATA"] = SANDBOX
os.environ["LOCALAPPDATA"] = SANDBOX

from PySide6.QtCore import QPoint, Qt                       # noqa: E402
from PySide6.QtGui import QGuiApplication                   # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)
APP.setQuitOnLastWindowClosed(False)
SENTENCE = "an aggressive approach to eliminate the duplicate consequence"
NOTICES = []


def pump(seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        APP.processEvents()
        time.sleep(0.01)


class FakeBook:
    def has(self, w): return False
    def add(self, item): return True
    def remove(self, w): pass
    def __len__(self): return 0
    def stats(self): return {}
    def items(self): return []
    def record_learning(self, words): return 0


def main() -> int:
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("不许联网"))
    from lexicon import Lexicon
    import sense_worker
    from pet_window import PetWindow
    from ocr_engine import OcrEngine
    if not OcrEngine.available():
        print("OCR 不可用")
        return 1

    # ---- 把生产代码的三个决策点打出来（不改行为，只加记录）-------------
    log = []
    #: 字幕窗口的逻辑矩形 + 这句字幕自己的词表。★ 只用来判「读回来的词**是不是
    #: 这句里的**」，非这句的词只计数、不打文本 —— 屏幕上别处是用户的内容。
    where = {"rect": None, "words": set()}

    def in_card(item):
        rect = where["rect"]
        pos = item.get("screen_pos")
        if rect is None or pos is None:
            return False
        rx, ry, rw, rh = rect
        return (rx - 14 <= pos[0] <= rx + rw + 14
                and ry - 14 <= pos[1] <= ry + rh + 14)

    real_roi = sense_worker.SenseWorker._roi_boxes

    def spy_roi(self, roi_keys, thumb_size, scale, full_size):
        boxes = real_roi(self, roi_keys, thumb_size, scale, full_size)
        log.append(("roi", list(roi_keys), [b[1:] for b in boxes]))
        return boxes
    sense_worker.SenseWorker._roi_boxes = spy_roi

    real_rec = sense_worker.SenseWorker._recognize

    def spy_rec(self, crop, offset, origin, dpr):
        items, ms = real_rec(self, crop, offset, origin, dpr)
        card = [it for it in items if in_card(it)]
        log.append(("rec", crop.shape[:2], offset, len(items), round(ms),
                    "框内 %d/%d" % (len(card), len(items)),
                    [it.get("surface") for it in card
                     if (it.get("surface") or "").lower() in where["words"]]))
        return items, ms
    sense_worker.SenseWorker._recognize = spy_rec

    real_note = sense_worker.SenseSession.note_words

    def spy_note(self, roi_key, words, elapsed_ms, now=None):
        fresh = real_note(self, roi_key, words, elapsed_ms, now=now)
        log.append(("note", roi_key, len(words), len(fresh),
                    "队列 %d" % len(self._queue), round(self.hz, 2),
                    self.state, round(float(elapsed_ms)),
                    "近5轮中位%.0fms" % self.recent_cycle_ms,
                    [it.get("surface") for it in fresh
                     if (it.get("surface") or "").lower() in where["words"]]))
        return fresh
    sense_worker.SenseSession.note_words = spy_note

    real_next = sense_worker.SenseSession.next_notice

    def spy_next(self, now=None):
        item = real_next(self, now=now)
        if item is not None:
            log.append(("flash", item.get("surface"),
                        tuple(round(v) for v in (item.get("screen_pos")
                                                 or ())), in_card(item)))
        return item
    sense_worker.SenseSession.next_notice = spy_next

    real_ingest = sense_worker.SenseWorker.process

    def spy_process(self, thumb, scale, array, origin, dpr, now=None):
        before = len(log)
        state0 = self.session.state
        real_ingest(self, thumb, scale, array, origin, dpr, now=now)
        if len(log) == before:
            log.append(("skip", state0, self.session.state,
                        tuple(self.session.stats[k] for k in
                              ("cycles", "ocr_runs", "skipped_no_change")),
                        self.session.note[:60]))
    sense_worker.SenseWorker.process = spy_process

    lexicon = Lexicon(os.path.join(BASE, "assets", "ecdict.sqlite"),
                      os.path.join(BASE, "assets", "exam-tags.sqlite"),
                      os.path.join(BASE, "assets", "industry.sqlite"))
    pet = PetWindow(lexicon, FakeBook(), sprite_w=360.0)
    pet.bubble.hide_now()
    screen = pet._screen_rect()
    pet.move(screen.x() + 40, screen.y() + 40)
    pet.show()
    pump(0.4)
    print("桌宠模式 mode=%s · limit=%s · 跳过停用词=%s"
          % (pet.capture_mode, pet.capture_limit, pet.capture_skip_stopwords))
    pet._start_sense(hz=2.0)
    pet.sense_worker.notice.connect(lambda item: NOTICES.append(item))
    session = pet.sense_session
    pump(6.0)
    print("基准轮之后：整帧 %d · OCR %d · 提示 %d · 待提示 %d"
          % (session.stats["full_frame"], session.stats["ocr_runs"],
             session.stats["notices"], session.pending_notices()))

    # ---- 字幕窗口：和 e2e 一样放在屏幕底部中央 -------------------------
    from sense_e2e import SubtitleWindow                  # noqa: WPS433
    card = SubtitleWindow(SENTENCE)
    card.show_at_bottom()
    APP.processEvents()
    pos = card.mapToGlobal(QPoint(0, 0))
    dpr = QGuiApplication.primaryScreen().devicePixelRatio()
    geo = QGuiApplication.primaryScreen().geometry()
    print("\n字幕窗口：逻辑矩形 (%d,%d,%d,%d) · dpr=%.2f · 桌面原点=(%d,%d)"
          % (pos.x(), pos.y(), card.width(), card.height(), dpr, geo.x(), geo.y()))
    print("           图像像素矩形 (%d,%d,%d,%d)"
          % ((pos.x() - geo.x()) * dpr, (pos.y() - geo.y()) * dpr,
             card.width() * dpr, card.height() * dpr))
    print("排除区：%s" % (pet._sense_exclude_rects(),))
    where["rect"] = (float(pos.x()), float(pos.y()),
                     float(card.width()), float(card.height()))
    where["words"] = {w.strip(".,") for w in SENTENCE.lower().split()}
    log.clear()
    mark = len(NOTICES)
    pump(75.0)

    print("\n这 75 秒里 %d 条事件：" % len(log))
    for entry in log:
        print("  ", entry)
    print("会话：轮次 %d · OCR %d · 整帧 %d · 无变化跳过 %d · 纯色跳过 %d "
          "· 提示 %d · 抑制 %d · 频率 %.2f"
          % (session.stats["cycles"], session.stats["ocr_runs"],
             session.stats["full_frame"], session.stats["skipped_no_change"],
             session.stats["skipped_blank"], session.stats["notices"],
             session.stats["suppressed"], session.hz))
    print("会话状态：%s · note：%s" % (session.state, session.note or "（无）"))
    print("收到提示 %d 个（本轮新增 %d）" % (len(NOTICES), len(NOTICES) - mark))
    rx, ry, rw, rh = (pos.x(), pos.y(), card.width(), card.height())
    inside = [n for n in NOTICES[mark:]
              if n.get("screen_pos")
              and rx - 14 <= n["screen_pos"][0] <= rx + rw + 14
              and ry - 14 <= n["screen_pos"][1] <= ry + rh + 14]
    print("落在字幕窗口内的：%d 个" % len(inside))
    ours = [n for n in NOTICES[mark:]
            if (n.get("surface") or "").lower() in where["words"]]
    print("提示里属于这句字幕的：%d 个 → %s"
          % (len(ours), [n.get("surface") for n in ours]))
    for n in NOTICES[mark:][:12]:
        p = n.get("screen_pos")
        print("   pos=%s box=%s %s" % (
            None if p is None else (round(p[0]), round(p[1])),
            None if n.get("screen_box") is None
            else tuple(round(v) for v in n["screen_box"]),
            "← 在字幕窗口内" if n in inside else ""))
    pet._stop_sense()
    card.close()
    APP.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
