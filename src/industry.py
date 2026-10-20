# -*- coding: utf-8 -*-
"""行业词库层：工业英语权威词汇表（307 条）。

为什么要有这一层
----------------
挑词链路原本是「ECDICT 全量词典 + 考纲标签」两层。行业词表是**第三层**，
且语义与前两层都不同：

- ECDICT 收了 `industry`、`tolerance` 这些词，但给的是通用释义
  （「工业；行业」），而屏幕上出现在工艺文件里时，用户要记的是「公差」这类
  行业义项；
- 考纲标签只覆盖 zk/gk/cet4/cet6/ky/toefl/ielts/gre，**没有行业维度**，
  所以在四六级模式下 `PLC`、`SMED`、`OEE` 一律被判成表外词。

因此这一层既补**词条**（ECDICT 没收的缩写、多词术语），也补**标签**（`industry`），
并在合并释义时把行业义项排到最前面。

多词术语是个坑
--------------
138 / 307 条是带空格的短语（`heavy industry`、`preventive maintenance`）。
`scan_text` 原本只按 `WORD_RE` 切单词，**永远切不出短语**，直接导入的话这
138 条等于白加。所以这里提供 `find_phrases()`，在切词**之前**先按字面匹配
短语，并让被短语覆盖到的单词不再单独入选。

数据来源与许可
--------------
`assets/industry.sqlite` 由 `tools/build_industry_db.py` 从「工业英语权威词汇表」
编译而来，原始出处见库内 `meta.sourceId` 与每条的 `source` 字段。
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

#: 与 exam-tags 同一套标签命名空间，供 `MODE_LABELS` / `level_label` 使用
LABEL = "industry"

#: 卡片上显示的级别文字
LEVEL_TEXT = "工业"

#: 挑词权重：行业术语对非本专业人士偏难，权重给在 cet6 与考研之间
LABEL_WEIGHT = 3.3


class IndustryDict:
    """只读打开 `assets/industry.sqlite`。

    缺库时安静降级（`available=False`），和 `ExamTags` 一个路子 ——
    行业词表是**加分项**，绝不能因为它缺失把识词链路带崩。
    """

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.available = False
        self.entry_count = 0
        self.source_id = ""
        self._local = threading.local()
        self._cache = {}
        self._phrases = []          # [(正则, 词表里的写法)]
        self._lock = threading.Lock()
        if not self.db_path.is_file():
            return
        try:
            rows = self.con.execute("SELECT key, value FROM meta").fetchall()
            meta = {r["key"]: r["value"] for r in rows}
            self.source_id = meta.get("sourceId", "")
            self.entry_count = int(meta.get("entryCount", "0") or 0)
            self._phrases = self._compile()
            self.available = True
        except Exception as error:            # noqa: BLE001
            print("[industry] 行业词库不可用: %r" % (error,))

    # ---- 连接（sqlite 连接线程绑定，OCR 跑在 worker 线程里）----
    @property
    def con(self) -> sqlite3.Connection:
        c = getattr(self._local, "con", None)
        if c is None:
            c = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True,
                                check_same_thread=False)
            c.row_factory = sqlite3.Row
            self._local.con = c
        return c

    def _compile(self):
        """把「多词 / 含特殊字符」的术语编成正则，长的优先匹配。

        `preventive maintenance` 和 `maintenance` 同时命中时，先吃掉长的那条；
        剩下的 `maintenance` 由 `_scan_text` 按 span 覆盖关系跳过。
        """
        compiled = []
        for row in self.con.execute(
                "SELECT word, display FROM entries WHERE word LIKE '% %' "
                "OR word GLOB '*[^A-Za-z]*'"):
            word = row["word"]
            tokens = [t for t in re.split(r"\s+", word.strip()) if t]
            if not tokens:
                continue
            pattern = r"[\s\-–—]+".join(re.escape(t) for t in tokens)
            compiled.append((re.compile(r"(?<![\w])" + pattern + r"(?![\w])",
                                        re.IGNORECASE), word))
        compiled.sort(key=lambda kv: -len(kv[1]))
        return compiled

    # ---- 查询 ----
    def get(self, surface: str):
        """查一条术语；没有返回 None。"""
        if not self.available or not surface:
            return None
        key = surface.strip().lower()
        with self._lock:
            cached = self._cache.get(key, False)
        if cached is not False:
            return cached
        row = self.con.execute(
            "SELECT word, display, phonetic, cn, en, category, source "
            "FROM entries WHERE word = ? LIMIT 1", (key,)).fetchone()
        value = dict(row) if row else None
        with self._lock:
            if len(self._cache) < 8000:
                self._cache[key] = value
        return value

    def has(self, surface: str) -> bool:
        return self.get(surface) is not None

    def find_phrases(self, text: str):
        """在文本里找出所有**多词**术语，返回 `[(写法, 起点, 终点)]`。

        返回的起点终点用于让 `scan_text` 跳过这些单词，避免 `heavy industry`
        和 `industry` 被重复选进卡片。
        """
        if not self.available or not text:
            return []
        out = []
        used = []
        for pattern, word in self._phrases:
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(start < e and s < end for s, e in used):
                    continue        # 与已命中的更长术语重叠，让位
                used.append((start, end))
                out.append((word, start, end))
        return out

    def status(self) -> dict:
        return {"available": self.available, "sourceId": self.source_id,
                "entryCount": self.entry_count,
                "phraseCount": len(self._phrases)}
