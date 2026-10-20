# -*- coding: utf-8 -*-
"""单词本：收藏 + 间隔重复复习。

比参考实现多的部分：收藏时记录阶段与到期时间，按
「答对进下一档（1 → 3 → 7 → 14 天）、答错退回次日」调度复习队列，
单词本列表会按到期顺序优先展示今天该复习的词。

落盘位置：``%APPDATA%/Lexara/wordbook.json``
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field

#: 答对后进入的下一档间隔（天）
STAGES = (1, 3, 7, 14)

APP_DIR_NAME = "Lexara"
DAY = 86400.0


def resource_path(*parts) -> str:
    """兼容 PyInstaller 打包后的资源路径。"""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class Item:
    word: str
    phonetic: str = ""
    meaning: str = ""
    level: str = ""
    tags: list = field(default_factory=list)
    added_at: float = field(default_factory=time.time)
    #: 复习阶段：-1 表示还没开始复习，0..len(STAGES)-1 表示已连对几次
    stage: int = -1
    due_at: float = 0.0
    correct: int = 0
    wrong: int = 0

    @property
    def due(self) -> bool:
        return self.due_at <= time.time()

    def to_dict(self) -> dict:
        return asdict(self)


class Wordbook:
    """收藏单词本（含复习调度）。"""

    def __init__(self, path: str = None):
        self.path = path or os.path.join(app_data_dir(), "wordbook.json")
        self.items: list = []
        self.study_events: list = []
        self.review_events: list = []
        #: ---- 任务书 §7：两种天数 + 成就 -----------------------------------
        #: `open_dates`：每个自然日第一次进入主工作状态记一次（用于 7/30/100 天）；
        #: `ai_events`：用户主动发出且**成功返回**的 AI 提问（深绿的一种）；
        #: `achievements`：{id: {seen: bool, at, date}} —— 只存已达成，不存未达成。
        #: 三个键都是**后加的**：老 `wordbook.json` 里没有它们，读到就当空列表，
        #: 下一次 save 才会写出去（向后兼容，不迁移、不改老字段）。
        self.open_dates: list = []
        self.ai_events: list = []
        self.achievements: dict = {}
        self.load()

    # ------------------------------------------------ 持久化
    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            rows = data.get("items", []) if isinstance(data, dict) else data
            self.study_events = list(data.get("studyEvents", [])) if isinstance(data, dict) else []
            self.review_events = list(data.get("reviewEvents", [])) if isinstance(data, dict) else []
            # 旧版本没有这三个键：缺失 = 空，不报错、不打日志
            self.open_dates = [str(d) for d in (data.get("openDates", [])
                                                if isinstance(data, dict) else [])
                               if isinstance(d, str)]
            self.ai_events = list(data.get("aiEvents", [])) if isinstance(data, dict) else []
            raw_done = data.get("achievements", {}) if isinstance(data, dict) else {}
            self.achievements = dict(raw_done) if isinstance(raw_done, dict) else {}
            self.items = []
            for row in rows or []:
                if not isinstance(row, dict) or "word" not in row:
                    continue
                known = {k: row[k] for k in
                         ("word", "phonetic", "meaning", "level", "tags",
                          "added_at", "stage", "due_at", "correct", "wrong")
                         if k in row}
                self.items.append(Item(**known))
        except Exception:                      # noqa: BLE001
            self.items = []
            self.study_events = []
            self.review_events = []
            self.open_dates = []
            self.ai_events = []
            self.achievements = {}

    def save(self) -> None:
        try:
            payload = {"schemaVersion": 3, "items": [i.to_dict() for i in self.items],
                       "studyEvents": self.study_events[-400:],
                       "reviewEvents": self.review_events[-400:],
                       # 打开日期是「成就」的唯一依据，去重后长期保留（一年 365 条，
                       # 体积可以忽略）；超出时保留最近的 1200 条（≈3 年）。
                       "openDates": sorted(set(self.open_dates))[-1200:],
                       "aiEvents": self.ai_events[-400:],
                       "achievements": dict(self.achievements)}
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:                      # noqa: BLE001
            pass

    # ------------------------------------------------ 增删查
    def has(self, word: str) -> bool:
        w = (word or "").lower()
        return any(i.word == w for i in self.items)

    def get(self, word: str):
        w = (word or "").lower()
        for i in self.items:
            if i.word == w:
                return i
        return None

    def add(self, info: dict) -> bool:
        w = (info.get("word") or info.get("lemma") or "").lower()
        if not w or self.has(w):
            return False
        self.items.append(Item(
            word=w,
            phonetic=info.get("phonetic", ""),
            meaning=info.get("meaning", ""),
            level=info.get("level", ""),
            tags=list(info.get("tags") or []),
        ))
        self.save()
        return True

    def remove(self, word: str) -> bool:
        w = (word or "").lower()
        before = len(self.items)
        self.items = [i for i in self.items if i.word != w]
        if len(self.items) != before:
            self.save()
            return True
        return False

    def clear(self) -> None:
        self.items = []
        self.save()

    def __len__(self) -> int:
        return len(self.items)

    def record_learning(self, words) -> int:
        """Record a scan as a small, bounded learning history.

        Events are intentionally separate from收藏 and never affect review scheduling.
        The same word is counted once per calendar day so repeated demo scans do not inflate
        the number shown to the user.
        """
        today = time.strftime("%Y-%m-%d")
        existing = {e.get("word") for e in self.study_events if e.get("date") == today}
        added = 0
        for word in words or []:
            key = str(word.get("lemma") or word.get("word") or "").lower()
            if not key or key in existing:
                continue
            self.study_events.append({"date": today, "word": key,
                                      "at": time.time()})
            existing.add(key)
            added += 1
        if added:
            self.save()
        return added

    def record_ai_ask(self) -> bool:
        """记录一次**成功返回**的 AI 提问（同一天只记一次）。

        只在 `ChatService` 真的收到回复时调用；请求失败、被取消、没配置模型
        都不算 —— 任务书 §2.5「仅点击未成功的请求不计入」。
        """
        today = time.strftime("%Y-%m-%d")
        if any(e.get("date") == today for e in self.ai_events
               if isinstance(e, dict)):
            return False
        self.ai_events.append({"date": today, "at": time.time()})
        self.save()
        return True

    def record_app_open(self) -> bool:
        """记录「今天打开过应用」。同一天多次启动只算 1 天，返回是否新增。"""
        today = time.strftime("%Y-%m-%d")
        if today in self.open_dates:
            return False
        self.open_dates.append(today)
        self.open_dates = sorted(set(self.open_dates))[-1200:]
        self.save()
        return True

    def activity_snapshot(self) -> dict:
        """日历与成就需要的原始数据（供 `activity` 模块读取）。"""
        return {"open_dates": list(self.open_dates),
                "study_dates": [e.get("date") for e in self.study_events
                                if isinstance(e, dict)],
                "review_dates": [e.get("date") for e in self.review_events
                                 if isinstance(e, dict)],
                "ai_dates": [e.get("date") for e in self.ai_events
                             if isinstance(e, dict)],
                "achievements": dict(self.achievements)}

    # ------------------------------------------------ 复习调度
    def due_count(self) -> int:
        return sum(1 for i in self.items if i.due)

    def review_queue(self) -> list:
        """到期优先、其次新词，最后按加入时间倒序。"""
        now = time.time()
        due = [i for i in self.items if i.due_at <= now]
        rest = [i for i in self.items if i.due_at > now]
        due.sort(key=lambda i: (i.stage, -i.added_at))
        rest.sort(key=lambda i: i.due_at)
        return due + rest

    def grade(self, word: str, correct: bool) -> None:
        """一次复习结果：答对进下一档，答错退回次日重来。"""
        item = self.get(word)
        if item is None:
            return
        if correct:
            item.correct += 1
            item.stage = min(item.stage + 1, len(STAGES) - 1)
            interval = STAGES[max(0, item.stage)]
        else:
            item.wrong += 1
            item.stage = 0
            interval = 1
        item.due_at = time.time() + interval * DAY
        today = time.strftime("%Y-%m-%d")
        if not any(e.get("date") == today and e.get("word") == item.word
                   for e in self.review_events):
            self.review_events.append({"date": today, "word": item.word,
                                       "at": time.time()})
        self.save()

    def stats(self) -> dict:
        today = time.strftime("%Y-%m-%d")
        today_words = {e.get("word") for e in self.study_events if e.get("date") == today}
        return {"total": len(self.items), "due": self.due_count(),
                "today": len(today_words)}
