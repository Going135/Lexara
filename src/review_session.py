# -*- coding: utf-8 -*-
"""复习会话：把「背单词」的流程状态从 UI 里抽出来，做成可复用的业务层。

为什么单独建这个文件
--------------------
任务书明确要求：**不要新增调度算法**，1/3/7/14 天规则只能由既有的
``wordbook.Wordbook.grade()`` 决定；同时要求 QML 不能把业务逻辑抄进 JavaScript。
所以这里只做三件事：

1. **编排**：维护「队列 / 当前第几个 / 答案是否已揭示 / 本次 session 的统计」这层流程状态；
2. **读**：把 ``Wordbook.review_queue()`` 的结果整理成画卡片需要的字典；
3. **写**：自评结果**只**通过 ``Wordbook.grade(word, correct)`` 落盘，一行调度逻辑都没复制。

旧的 ``dialogs.WordbookDialog`` 复习页和新的 QML 复习页共用这一个类，
两边不可能出现「同一个自评按钮两种 behaviour」的分叉。

答案揭示（主动回忆）的语义
--------------------------
``reveal()`` 只改变 session 内部的 `_revealed` 标志，**不写任何持久化数据**。
只有 ``grade()`` 会写盘。这样「看一眼答案」永远不会偷偷改变到期时间。
"""

from __future__ import annotations

import time

from wordbook import STAGES

#: 一次 session 的默认上限。任务书 2.1：一次复习用短而明确的 session，
#: 不让用户面对一整页词表。旧的 Widgets 复习页传 ``limit=None`` 保持原行为（全量）。
DEFAULT_SESSION_LIMIT = 20

_NO_MEANING = "（本地词典暂无中文释义）"


def today_key() -> str:
    return time.strftime("%Y-%m-%d")


class ReviewSession:
    """一次复习会话的流程状态机。不持有 Qt，可脱离 GUI 单测。"""

    def __init__(self, book, limit: int | None = None):
        self.book = book
        self.limit = limit
        self._queue: list = []
        self._index = 0
        self._revealed = False
        self._answered = 0
        self._correct = 0
        self._wrong_words: list = []
        self._started_at = 0.0
        self._finished = False
        #: 本轮的分类过滤器（`item -> bool`，None = 全部）。调度算法不认它，
        #: 它只决定「哪些词有资格进队列」，1/3/7/14 仍由 `Wordbook.grade()` 定。
        self._keep = None

    # ------------------------------------------------ 生命周期
    @property
    def running(self) -> bool:
        return bool(self._queue) and not self._finished

    @property
    def revealed(self) -> bool:
        return self._revealed

    def start(self, limit: int | None = None,
              include_upcoming: bool = True,
              keep=None) -> dict:
        """开一轮复习。返回本轮概况（供复习入口页与卡片页使用）。

        ``include_upcoming=False`` 时只练**今天到期**的词（"只复习到期"语义）。
        ``keep`` 是可选的分类过滤器（``item -> bool``），会被记住并在
        ``rebuild()`` 后继续生效 —— 入口页选「四级」，中途自评不该把
        别的分类混进来。
        队列顺序完全来自 ``Wordbook.review_queue()``（到期优先、其次新词），
        这里不重排。
        """
        self._keep = keep
        items = list(self.book.review_queue())
        now = time.time()
        if self._keep is not None:
            items = [i for i in items if self._keep(i)]
        if not include_upcoming:
            items = [i for i in items if i.due_at <= now]
        cap = self.limit if limit is None else limit
        if cap:
            items = items[:cap]
        self._queue = items
        self._index = 0
        self._revealed = False
        self._answered = 0
        self._correct = 0
        self._wrong_words = []
        self._started_at = time.time()
        self._finished = False
        return self.summary()

    def start_wrong_only(self, limit: int | None = None) -> dict:
        """把本轮答错的词再练一遍（完成页的「再练错词」）。

        队列直接从**词库**里取现存的条目（期间可能被删除）；
        一个都找不到时就退化成空 session，UI 那边相应显示空状态。
        """
        words = list(dict.fromkeys(self._wrong_words))
        items = [self.book.get(w) for w in words]
        items = [i for i in items if i is not None]
        if not items:
            self._queue = []
            self._index = 0
            self._finished = True
            return self.summary()
        # 保序：`review_queue()` 的顺序不代表用户答错的顺序，这里按错词顺序排。
        order = {w: n for n, w in enumerate(words)}
        items.sort(key=lambda i: order.get(i.word, 1 << 30))
        self._queue = items
        self._index = 0
        self._revealed = False
        self._answered = 0
        self._correct = 0
        self._wrong_words = []
        self._started_at = time.time()
        self._finished = False
        return self.summary()

    def rebuild(self) -> None:
        """自评后按新的到期顺序重建队列（旧 Widgets 复习页的既有行为）。

        ``Wordbook.grade()`` 会把刚才那个词的 ``due_at`` 推到未来，
        队列顺序随之变化，所以 UI 必须重排才能自动落到下一个词上。
        这里刻意保留当前位置而**不是**清零 —— 与 2026-10-17 之前的行为一致。
        """
        if self._finished or not self._queue:
            return
        current = self.current_word()
        items = list(self.book.review_queue())
        if self._keep is not None:
            items = [i for i in items if self._keep(i)]
        if self.limit:
            items = items[:self.limit]
        index = 0
        for n, item in enumerate(items):
            if item.word == current:
                index = n
                break
        self._queue = items
        self._index = index
        self._revealed = False

    def exit_session(self) -> dict:
        """中途退出：丢弃未完成的 session，但**不动已存在的复习记录**。"""
        stats = self.summary()
        self._queue = []
        self._index = 0
        self._revealed = False
        self._finished = True
        return stats

    # ------------------------------------------------ 卡片
    def current_word(self) -> str | None:
        if not self._queue:
            return None
        return self._queue[self._index % len(self._queue)].word

    def card(self) -> dict:
        """当前卡片的数据（UI 只读这个字典，不做任何业务判断）。"""
        if not self._queue:
            return {}
        item = self._queue[self._index % len(self._queue)]
        now = time.time()
        total = len(self._queue)
        stage = max(0, int(item.stage))
        return {
            "word": item.word,
            "phonetic": item.phonetic or "",
            "meaning": item.meaning or _NO_MEANING,
            "hasMeaning": bool(item.meaning),
            "level": item.level or "",
            "tags": list(item.tags or []),
            "index": self._index + 1,
            "total": total,
            "progress": (self._index) / total if total else 0.0,
            "revealed": self._revealed,
            "stage": stage,
            "stageLabel": _stage_label(stage, item.wrong),
            "due": item.due_at <= now,
            "revisit": bool(self._wrong_words and item.word in self._wrong_words),
        }

    def reveal(self) -> dict:
        """揭示答案。纯 UI 状态，不写盘。"""
        self._revealed = True
        return self.card()

    # ------------------------------------------------ 自评 → 真实调度
    def grade(self, correct: bool) -> dict:
        """自评。调用既有 ``Wordbook.grade()``，**不新增任何调度算法**。"""
        if not self._queue:
            return self.card()
        item = self._queue[self._index % len(self._queue)]
        self.book.grade(item.word, bool(correct))
        self._answered += 1
        if correct:
            self._correct += 1
            if item.word in self._wrong_words:
                self._wrong_words.remove(item.word)
        else:
            if item.word not in self._wrong_words:
                self._wrong_words.append(item.word)
        return self.card()

    def step(self, delta: int = 1) -> dict:
        """翻到上一张 / 下一张。不影响任何持久化数据。"""
        if not self._queue:
            return self.card()
        n = len(self._queue)
        self._index = (self._index + delta) % n
        self._revealed = False
        return self.card()

    #: ``grade`` 之后自动前进一格的快捷入口（UI 的自评按钮走这条）
    def grade_and_advance(self, correct: bool) -> dict:
        card = self.grade(correct)
        if not self._queue:
            return card
        if self._index + 1 >= len(self._queue):
            # 最后一张答完 → session 结束，停留在完成页
            self._finished = True
            self._revealed = False
            return {}
        return self.step(1)

    # ------------------------------------------------ 统计
    def summary(self) -> dict:
        """session 概况。所有数字来自本 session 的真实行为 + 真实词库。"""
        elapsed = time.time() - self._started_at if self._started_at else 0.0
        remaining = max(0, len(self._queue) - self._index - (0 if not self._finished else 0))
        return {
            "started": bool(self._queue) or self._finished,
            "total": len(self._queue),
            "index": self._index,
            "answered": self._answered,
            "correct": self._correct,
            "wrong": self._answered - self._correct,
            "wrongWords": list(self._wrong_words),
            "wrongCount": len(self._wrong_words),
            "remaining": remaining if not self._finished else 0,
            "elapsed": round(elapsed, 1),
            "finished": self._finished,
            "empty": not self._queue,
            "limit": self.limit,
        }


def due_overview(book) -> dict:
    """复习入口页的真实统计（不给 UI 任何硬编码数字）。

    - ``total`` / ``due`` 来自 ``Wordbook.stats()``；
    - ``reviewedToday`` 数今天的复习事件（每条词只记一次）；
    - ``nextDueLabel`` 是下一个到期词还有多久（全都背完时为 ``""``）。
    """
    stats = book.stats()
    today = today_key()
    reviewed_today = len({e.get("word") for e in getattr(book, "review_events", [])
                          if e.get("date") == today})
    upcoming = [i.due_at for i in book.items if i.due_at > time.time()]
    next_label = ""
    if upcoming:
        wait_days = (min(upcoming) - time.time()) / 86400.0
        if wait_days < 1 / 24.0:
            next_label = "不到 1 小时后"
        elif wait_days < 1:
            next_label = "约 %d 小时后" % max(1, int(round(wait_days * 24)))
        else:
            next_label = "约 %d 天后" % max(1, int(round(wait_days)))
    return {
        "total": int(stats.get("total", 0)),
        "due": int(stats.get("due", 0)),
        "learnedToday": int(stats.get("today", 0)),
        "reviewedToday": int(reviewed_today),
        "nextDueLabel": next_label,
        "empty": int(stats.get("total", 0)) == 0,
    }


def _stage_label(stage: int, wrong: int) -> str:
    """当前所在档位的中文标签（只做展示，不参与调度）。"""
    if wrong and stage == 0:
        return "上次答错 · 今天重来"
    interval = STAGES[min(max(0, stage), len(STAGES) - 1)]
    return "第 %d 档 · 下次间隔 %d 天" % (stage + 1, interval)
