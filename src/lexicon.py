# -*- coding: utf-8 -*-
"""词典层：ECDICT 全量释义 + 独立考纲标签 + 挑词。

和参考实现的区别：
    参考版内置的是 401 KB 的 `vocab.json`（约几千条 CET4/CET6 高频词），
    屏幕上一旦出现表外词就直接漏掉。
    这里接 ECDICT Revised 全量 **75.8 万词条 + 5.8 万条词形映射**，
    再叠加独立考纲标签表（zk/gk/cet4/cet6/ky/toefl/ielts/gre，14942 词），
    所以覆盖面大得多，而且「考纲」与「词典」两层是解耦的：
    换词典不影响标签，换标签也不用动词典。

数据来源与许可：
    assets/ecdict.sqlite      ECDICT Revised v0.1.1（MIT / CC BY-SA 4.0）
    assets/exam-tags.sqlite   由上游 ECDICT 的 tag 字段生成的独立标签表（MIT）

线程模型：OCR 跑在 QThread 里，而 sqlite3 连接是线程绑定的，
因此连接一律放在 threading.local，不在线程间共享。
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

import industry

# ---------------------------------------------------------------- 文本处理

#: 英文单词（允许内部连字符与撇号）
WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")

#: 功能词：识别出来也不值得进卡片（背了没用）
STOPWORDS = frozenset("""
a an the and or but if of to in on at by for with from as is are was were be been
being am do does did have has had will would shall should can could may might must
this that these those it its he she they them his her their we us our you your i me
my mine not no so than then there here when where which who whom whose what how
all any both each few more most other some such only own same too very just also
about into over after before between during without again further once up down out
off above below under while because through against along among around upon
""".split())

#: 释义里的换行是字面量 "\n"
_ESCAPED_NL = "\\n"

_POS_PREFIXES = (
    "n.", "v.", "vt.", "vi.", "adj.", "adv.", "prep.", "conj.", "pron.",
    "num.", "art.", "int.", "aux.", "modal.", "pl.", "abbr.", "ad.",
)

# ---------------------------------------------------------------- 考纲层

#: 标签取值白名单，与生成脚本保持一致
#: （`industry` 不在这里：它不属于考纲体系，由 `industry.py` 单独提供）
EXAM_LABELS = ("zk", "gk", "cet4", "cet6", "ky", "toefl", "ielts", "gre")

#: 模式 → 命中的标签集合；空集合表示「不筛选」。
#:
#: cet6 收录 cet4 是有意为之：六级考纲本身覆盖四级词汇，
#: 若只认 cet6，绝大多数日常词在六级模式下都会被判成表外，筛选就失去意义了。
MODE_LABELS = {
    "cet4": frozenset({"cet4"}),
    "cet6": frozenset({"cet4", "cet6"}),
    "ky": frozenset({"ky"}),
    "ielts": frozenset({"ielts"}),
    "toefl": frozenset({"toefl"}),
    "gre": frozenset({"gre"}),
    "industry": frozenset({"industry"}),
    "all": frozenset(),
}

MODE_DISPLAY = {
    "cet4": "四级", "cet6": "六级", "ky": "考研", "ielts": "雅思",
    "toefl": "托福", "gre": "GRE", "industry": "工业英语", "all": "全部词汇",
}

MODE_ORDER = ("cet4", "cet6", "ky", "ielts", "toefl", "gre", "industry", "all")

#: 收藏夹的五个分类（任务书 §2.2）。**唯一来源**：启动台侧栏、单词本过滤、
#: 计数分母都从这里取，避免「侧栏说有五个、弹窗里只认四个」这种分叉。
#: 第一个元素是标签键（与 `exam-tags.sqlite` 的 tag 一一对应），第二个是显示名。
FAVORITE_CATEGORIES = (
    ("cet4", "四级"),
    ("cet6", "六级"),
    ("ielts", "雅思"),
    ("toefl", "托福"),
    ("industry", "工业英语"),
)
#: 「未分类」兜底：一个标签都没命中的收藏词（老版本收藏可能没存 tags）
OTHER_CATEGORY = ("other", "未分类")

#: 难度权重：越靠后的考纲越难，用于排序（同屏多词时先推难的）
_LABEL_WEIGHT = {"zk": 0.5, "gk": 1.0, "cet4": 2.0, "cet6": 3.0,
                 "ky": 3.6, "ielts": 4.0, "toefl": 4.2, "gre": 4.6}
#: 行业术语不属于考纲序列，权重由 industry 层自己定，避免两处各写一个数
_LABEL_WEIGHT[industry.LABEL] = industry.LABEL_WEIGHT

#: 词长增益：同样标签下，长词通常更值得记
def _difficulty(word: str, tags) -> float:
    score = max((_LABEL_WEIGHT.get(t, 0.0) for t in tags), default=0.0)
    score += min(len(word), 12) * 0.12
    return score


# ---------------------------------------------------------------- 词形还原

def lemma_candidates(surface: str) -> list:
    """规则兜底：surface 的可能原形，按可信度排序。

    ECDICT 自带 aliases 表覆盖了绝大多数不规则变化；这里的规则只用于
    兜住 aliases 没有收录的边缘情况（例如自造词、专有名词复数）。
    """
    w = surface.lower()
    out = []
    n = len(w)
    if n > 4 and w.endswith("ies"):
        out.append(w[:-3] + "y")
    if n > 4 and w.endswith("ied"):
        out.append(w[:-3] + "y")
    if n > 4 and w.endswith("ves"):
        out.append(w[:-3] + "f")
        out.append(w[:-3] + "fe")
    if n > 3 and w.endswith("es"):
        out.append(w[:-2])
    if n > 3 and w.endswith("s") and not w.endswith("ss"):
        out.append(w[:-1])
    if n > 5 and w.endswith("ing"):
        stem = w[:-3]
        out.append(stem)
        out.append(stem + "e")
        if len(stem) > 2 and stem[-1] == stem[-2]:
            out.append(stem[:-1])
    if n > 4 and w.endswith("ed"):
        stem = w[:-2]
        out.append(stem)
        out.append(w[:-1])
        if len(stem) > 2 and stem[-1] == stem[-2]:
            out.append(stem[:-1])
    if n > 4 and w.endswith("ly"):
        out.append(w[:-2])
    if n > 5 and w.endswith("est"):
        out.append(w[:-3])
    if n > 4 and w.endswith("er"):
        out.append(w[:-2])
    seen, result = set(), []
    for v in out:
        if len(v) > 2 and v not in seen:
            seen.add(v)
            result.append(v)
    return result


# ---------------------------------------------------------------- 考纲标签表

class ExamTags:
    """独立考纲标签表。

    缺表时**安静降级**：`available=False`，`tags_of()` 一律返回空列表，
    界面显示为「全部词汇」。绝不让标签缺失把整条识词链路带崩。
    """

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.available = False
        self.source_id = ""
        self.entry_count = 0
        self.counts = {}
        self._local = threading.local()
        self._lock = threading.Lock()
        self._cache = {}
        if not self.db_path.is_file():
            return
        try:
            rows = self.con.execute("SELECT key, value FROM meta").fetchall()
            meta = {r["key"]: r["value"] for r in rows}
            self.source_id = meta.get("sourceId", "")
            self.entry_count = int(meta.get("entryCount", "0") or 0)
            for pair in (meta.get("counts") or "").split(","):
                if "=" in pair:
                    name, _, value = pair.partition("=")
                    try:
                        self.counts[name.strip()] = int(value)
                    except ValueError:
                        pass
            self.available = True
        except Exception as error:            # noqa: BLE001
            print("[exam] 标签表不可用: %r" % (error,))

    @property
    def con(self) -> sqlite3.Connection:
        c = getattr(self._local, "con", None)
        if c is None:
            c = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True,
                                check_same_thread=False)
            c.row_factory = sqlite3.Row
            self._local.con = c
        return c

    def tags_of(self, word: str) -> list:
        if not self.available or not word:
            return []
        key = word.lower()
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        row = self.con.execute(
            "SELECT tags FROM tags WHERE word = ? LIMIT 1", (key,)).fetchone()
        tags = row["tags"].split() if row else []
        with self._lock:
            if len(self._cache) < 40000:
                self._cache[key] = tags
        return tags

    def matches(self, word: str, mode: str) -> bool:
        wanted = MODE_LABELS.get(mode)
        if not wanted or not self.available:
            return True
        return bool(wanted.intersection(self.tags_of(word)))

    def status(self) -> dict:
        return {"available": self.available, "sourceId": self.source_id,
                "entryCount": self.entry_count, "counts": dict(self.counts)}


# ---------------------------------------------------------------- 词典

def parse_translation(translation: str):
    """把 ECDICT 的 translation 拆成 ``(pos, [释义…])``。

    原始格式形如 ``vt. 放弃, 抛弃\\nn. 放任``，其中 ``\\n`` 是**字面量**的反斜杠+n。
    只在同一词性内部去重：同一词在不同词性下重复的释义属于不同义项。
    """
    if not translation:
        return "", []
    text = translation.replace(_ESCAPED_NL, "\n").replace("\\/", "/")

    pos_parts, meanings, seen = [], [], set()
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        matched = ""
        for prefix in _POS_PREFIXES:
            if line.startswith(prefix):
                matched = prefix
                line = line[len(prefix):].strip()
                break
        if matched:
            pos_parts.append(matched.rstrip("."))
        for item in re.split(r"[,，、;；]", line):
            item = item.strip().strip("()（）")
            item = re.sub(r"^\[[^\]]*\]\s*", "", item)   # 去掉 [网络] 这类来源标记
            if len(item) >= 2 and item not in seen:
                seen.add(item)
                meanings.append(item)
    return "/".join(dict.fromkeys(pos_parts)), meanings


class Lexicon:
    """ECDICT 查询 + 挑词。"""

    #: 卡片释义最多显示几条
    MEANING_LIMIT = 4

    def __init__(self, dict_path, tags_path=None, industry_path=None):
        self.dict_path = Path(dict_path)
        self.available = self.dict_path.is_file()
        self._local = threading.local()
        self._legacy_vocab = None
        if self.available:
            self._ensure_indexes()
        self.tags = ExamTags(tags_path) if tags_path else ExamTags("__missing__")
        self.industry = industry.IndustryDict(industry_path or "__missing__")

    # ---- 标签（考纲 + 行业）----
    def tags_of(self, word: str) -> list:
        """**完整**标签：考纲标签 + 行业标签。

        这里必须自己合成、不能直接用 `self.tags.tags_of()`：
        行业标签不在考纲表里（`PLC`/`SMED` 这些缩写本来也不会带 cet 标签），
        若只看考纲表，切到「工业英语」模式时它们全会被判成表外词。
        """
        tags = list(self.tags.tags_of(word))
        if self.industry.has(word):
            tags.append(industry.LABEL)
        return tags

    def matches(self, word: str, mode: str) -> bool:
        wanted = MODE_LABELS.get(mode)
        if not wanted:
            return True
        return bool(wanted.intersection(self.tags_of(word)))

    # ---- 连接 ----
    @property
    def con(self) -> sqlite3.Connection:
        c = getattr(self._local, "con", None)
        if c is None:
            c = sqlite3.connect(f"file:{self.dict_path}?mode=ro", uri=True,
                                check_same_thread=False)
            c.row_factory = sqlite3.Row
            self._local.con = c
        return c

    def _ensure_indexes(self) -> None:
        """原库无索引（75 万行），查询从全表扫描降到 O(log n)。

        ★ 2026-10-19：以前这里建 `ix_entries_word` / `ix_aliases_alias`，是**纯死重**
        —— `entries.word` 和 `aliases.alias` 本身就是 `TEXT PRIMARY KEY`，
        SQLite 会自动建唯一索引，`EXPLAIN QUERY PLAN` 显示查询一直走
        `SEARCH ... USING PRIMARY KEY`，那两份索引从没被用过。代价是库文件胖
        21.3MB（64.3 → 43.0），`COUNT(*)` 还要多扫一遍。
        现在改成只**清理**老库里遗留的重复索引，不再新建。
        """
        try:
            c = sqlite3.connect(str(self.dict_path))
            # 先看 schema 里到底有没有 —— 没有就走，一次写事务都不开。
            # 打包后的资源目录可能只读，无谓的 DDL 会抛异常刷日志。
            present = {row[0] for row in c.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            stale = [n for n in ("ix_entries_word", "ix_aliases_alias") if n in present]
            if stale:
                for name in stale:
                    c.execute("DROP INDEX %s" % name)   # 名字来自上面的白名单
                c.commit()
                print("[dict] 删掉重复索引 %s" % ", ".join(stale))
            c.close()
        except sqlite3.OperationalError as error:
            # 只读介质（打包后资源目录）会拒绝 DDL —— 不影响查询，直接跳过。
            print("[dict] 跳过索引清理（%s）" % error)

    # ---- 查询 ----
    def _industry_entry(self, surface: str):
        """只按行业词库造一条词条（ECDICT 查不到时的兜底）。

        缩写（`SMED`/`OEE`）和多词术语（`preventive maintenance`）走的都是这条路。
        """
        row = self.industry.get(surface)
        if row is None:
            return None
        meanings = [m for m in re.split(r"[,，、;；]", row["cn"] or "")
                    if m.strip()]
        return {
            "word": row["word"],
            "surface": surface,
            "lemma": row["word"],
            "phonetic": row["phonetic"] or "",
            "pos": "",
            "meanings": meanings[:self.MEANING_LIMIT],
            "meaning": "；".join(meanings[:self.MEANING_LIMIT]),
            "tags": [industry.LABEL],
            "level": industry.LEVEL_TEXT,
            "sourceId": self.industry.source_id,
            "industry": row,
        }

    def _merge_industry(self, info: dict) -> dict:
        """给 ECDICT 词条叠上行业义项。

        顺序是**行业义项在前**：屏幕上出现在工艺文件里的 `tolerance`，
        用户想记的是「公差」而不是「容忍」。通用义项保留在后面，
        去重后再按 `MEANING_LIMIT` 截断。
        """
        entry = self.industry.get(info["lemma"])
        if entry is None:
            return info
        cn = [m.strip() for m in re.split(r"[,，、;；]", entry["cn"] or "")
              if m.strip()]
        merged = []
        for item in cn + list(info["meanings"]):
            if item and item not in merged:
                merged.append(item)
        info["meanings"] = merged[:self.MEANING_LIMIT]
        info["meaning"] = "；".join(info["meanings"])
        if entry["phonetic"] and not info["phonetic"]:
            info["phonetic"] = entry["phonetic"]
        if industry.LABEL not in info["tags"]:
            info["tags"] = list(info["tags"]) + [industry.LABEL]
        info["level"] = self.level_label(info["tags"])
        info["industry"] = entry
        return info

    def lemma_of(self, surface: str) -> str:
        """词形还原：surface → 词头；查不到就原样返回。"""
        s = surface.lower()
        row = self.con.execute(
            "SELECT target FROM aliases WHERE alias = ? LIMIT 1", (s,)).fetchone()
        if row and row["target"]:
            return row["target"].lower()
        return s

    def _entry(self, word: str):
        return self.con.execute(
            "SELECT word, phonetic, translation FROM entries WHERE word = ? LIMIT 1",
            (word,)).fetchone()

    def lookup(self, surface: str):
        """查一个词，返回词卡所需的全部字段；查不到返回 None。"""
        if not self.available or not surface:
            return None

        lemma = self.lemma_of(surface)
        row = self._entry(lemma)

        if row is None:
            # aliases 没收录，用规则兜底逐个试
            for cand in lemma_candidates(surface):
                row = self._entry(cand)
                if row is not None:
                    lemma = cand
                    break
        if row is None:
            # ECDICT 没有，最后问行业词库（缩写、多词术语基本都落在这里）
            return self._industry_entry(surface)

        pos, meanings = parse_translation(row["translation"])
        tags = self.tags_of(lemma)
        return self._merge_industry({
            "word": row["word"].lower(),
            "surface": surface,
            "lemma": lemma,
            "phonetic": row["phonetic"] or "",
            "pos": pos,
            "meanings": meanings[:self.MEANING_LIMIT],
            "meaning": "；".join(meanings[:self.MEANING_LIMIT]),
            "tags": tags,
            "level": self.level_label(tags),
            "sourceId": "ECDICT-Revised-0.1.1",
        })

    @staticmethod
    def level_label(tags) -> str:
        """把标签集合压成卡片上的一行级别文字，如 ``CET6 · 考研 · 工业``。"""
        names = {"zk": "中考", "gk": "高考", "cet4": "CET4", "cet6": "CET6",
                 "ky": "考研", "ielts": "雅思", "toefl": "托福", "gre": "GRE",
                 industry.LABEL: industry.LEVEL_TEXT}
        ordered = [names[t] for t in EXAM_LABELS if t in names and t in tags]
        if industry.LABEL in tags:
            ordered.append(industry.LEVEL_TEXT)
        return " · ".join(ordered)

    def tokenize(self, text: str) -> list:
        return [m.group(0) for m in WORD_RE.finditer(text or "")]

    def _tokenize_spans(self, text: str) -> list:
        """带位置的切词。短语匹配要靠它判断「这个单词是不是已被短语吃掉」。"""
        return [(m.group(0), m.start(), m.end())
                for m in WORD_RE.finditer(text or "")]

    # ---- 挑词 ----
    def scan_text(self, text: str, mode: str = "cet6", limit: int = 8,
                  skip_stopwords: bool = True) -> list:
        """从 OCR 文本里挑出最值得背的单词，最多 ``limit`` 个。

        两轮挑选：
          第一轮只收**命中当前模式**的词（考纲标签或行业标签）；
          若不足 limit，第二轮补上表外的实义词（标 ``off_syllabus=True``），
          这样屏幕上出现的词不会被白白丢掉，但卡片里能看出哪些是考纲内的。

        ★ 切词前**先扫多词术语**：行业词库里 138 / 307 条是带空格的短语
        （`heavy industry`、`preventive maintenance`），而 `tokenize` 只切单词，
        永远切不出它们。短语命中后，落在其字符区间内的单词不再单独入选，
        否则「heavy industry」和「industry」会各占一张卡片。
        """
        if not self.available:
            return []

        on_syllabus, off_syllabus = [], []
        seen = set()
        taken_spans = []

        def _take(surface, key, info):
            info["off_syllabus"] = not self.matches(key, mode)
            info["difficulty"] = _difficulty(key, info["tags"])
            if info["off_syllabus"] and mode != "all":
                off_syllabus.append(info)
            else:
                on_syllabus.append(info)

        for phrase, start, end in self.industry.find_phrases(text):
            info = self.lookup(phrase)
            if info is None:
                continue
            key = info["lemma"]
            if key in seen:
                continue
            seen.add(key)
            taken_spans.append((start, end))
            _take(phrase, key, info)

        for token, start, end in self._tokenize_spans(text):
            surface = token.strip("-'").lower()
            if len(surface) < 2 or surface in seen:
                continue
            if skip_stopwords and surface in STOPWORDS:
                continue
            if any(start < e and s < end for s, e in taken_spans):
                continue                      # 已被更长的术语吃掉

            info = self.lookup(surface)
            if info is None:
                continue
            key = info["lemma"]
            if key in seen:
                continue
            seen.add(key)

            _take(surface, key, info)

        on_syllabus.sort(key=lambda x: (-x["difficulty"], x["lemma"]))
        off_syllabus.sort(key=lambda x: (-x["difficulty"], x["lemma"]))

        picked = on_syllabus[:limit]
        if len(picked) < limit:
            picked.extend(off_syllabus[:limit - len(picked)])
        return picked

    # ---- 状态 ----
    def status(self) -> dict:
        return {
            "available": self.available,
            "path": str(self.dict_path),
            "entries": self._count() if self.available else 0,
            "exam": self.tags.status(),
            "industry": self.industry.status(),
        }

    def _count(self) -> int:
        """词条数。

        ★ 优先读 `sqlite_stat1`：`entries` 是 WITHOUT ROWID 表，`count(*)` 要扫
        75 万行索引页（实测 95ms，还会把索引页拉进工作集）。ANALYZE 之后
        stat1 的第一列就是精确行数（本库已校准：758497），读一行就够。
        表结构变了或没跑过 ANALYZE 时回落到真实 count。
        """
        try:
            row = self.con.execute(
                "SELECT stat FROM sqlite_stat1 WHERE tbl = 'entries' LIMIT 1").fetchone()
            if row and row[0]:
                head = str(row[0]).split()
                if head and head[0].isdigit():
                    return int(head[0])
        except Exception:                     # noqa: BLE001
            pass
        try:
            return self.con.execute("SELECT count(*) FROM entries").fetchone()[0]
        except Exception:                     # noqa: BLE001
            return 0
