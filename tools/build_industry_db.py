# -*- coding: utf-8 -*-
"""把「工业英语权威词汇表」的 markdown 表编译成 `assets/industry.sqlite`。

为什么不直接读 md：
    打包后 md 不在 exe 里（--add-data 只收了两个 sqlite + 图标），而且每次
    启动时去解析一遍 374 行文本纯属浪费。编译成 sqlite 后跟另外两个词典一样
    用 `file:...?mode=ro` 只读打开，330 行全表扫描也比解析文本快。

为什么单独一张库而不是并进 ECDICT：
    ECDICT 是第三方数据（75.8 万条），**不该**往里写东西 —— 一改就再也分不清
    哪些是上游的、哪些是我们加的，也没法跟着上游升级。行业词库是我们自己的
    一层，独立成库、独立版本号。

用法：
    python tools/build_industry_db.py [输入的 md 路径]
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

DEFAULT_SRC = r"C:\Users\35388\Desktop\工业英语权威词汇表.md"
OUT_PATH = os.path.join(BASE, "assets", "industry.sqlite")

SOURCE_ID = "industrial-en-vocab-2026-10-15"

#: 表格分隔行 / 表头行
_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")


def parse_markdown(path: str):
    """解析 md，返回 `(meta, entries)`。

    只认「## 分类」开头的段落 + 五列表格行，其余（标题、说明、引用）一律跳过。
    这样即便以后往 md 里加别的段落，脚本也不会把说明文字当成词条。
    """
    entries = []
    category = ""
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("## "):
                category = line[3:].strip()
                # 「通用工业与生产（42 条）」→ 只留分类名，条数交给计数器
                category = re.sub(r"[（(]\s*\d+\s*条?\s*[)）]\s*$", "", category)
                continue
            if not line.startswith("|") or _SEP_RE.match(line):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 6:
                continue
            index, term, phonetic, cn, en, source = cells[:6]
            if not index.isdigit():          # 表头行
                continue
            term = term.strip()
            if not term:
                continue
            entries.append({
                "word": term.lower(),
                "display": term,
                "phonetic": (phonetic or "").strip().strip("/"),
                "cn": (cn or "").strip(),
                "en": (en or "").strip(),
                "category": category,
                "source": (source or "").strip(),
            })
    return entries


def merge_duplicates(entries):
    """同一术语跨分类重复时合并（原表 330 行里 23 个重复，唯一 307 条）。

    重复的性质是「同一个词既属机械工程、又属自动化/缩写表」，两边的中文释义
    几乎一致、英文说明详略不同。所以合并规则取**更完整的那一版**：

    - 音标：取第一个非空的（缩写表里普遍为空，正文那版才有 IPA）；
    - 中文 / 英文：取更长的一条（更完整，而不是先出现的）；
    - 分类、来源：去重后用「 / 」连起来。
    """
    merged = {}
    order = []
    for item in entries:
        base = merged.get(item["word"])
        if base is None:
            merged[item["word"]] = dict(item)
            order.append(item["word"])
            continue
        if not base["phonetic"] and item["phonetic"]:
            base["phonetic"] = item["phonetic"]
        for key in ("cn", "en"):
            if len(item[key]) > len(base[key]):
                base[key] = item[key]
        for key in ("category", "source"):
            parts = [p for p in base[key].split(" / ") if p]
            if item[key] and item[key] not in parts:
                parts.append(item[key])
            base[key] = " / ".join(parts)
    return [merged[w] for w in order]


def build(entries, out_path: str) -> dict:
    if os.path.exists(out_path):
        os.remove(out_path)
    con = sqlite3.connect(out_path)
    con.execute("""
        CREATE TABLE entries (
            word     TEXT PRIMARY KEY,   -- 小写术语，词组保留空格
            display  TEXT NOT NULL,      -- 原始大小写，卡片上显示这个
            phonetic TEXT,
            cn       TEXT,               -- 中文释义
            en       TEXT,               -- 英文释义 / 说明
            category TEXT,               -- 所属分类
            source   TEXT                -- 权威来源
        )""")
    con.execute("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)""")
    con.executemany(
        "INSERT INTO entries(word, display, phonetic, cn, en, category, source) "
        "VALUES(:word, :display, :phonetic, :cn, :en, :category, :source)",
        entries)

    counts = Counter(e["category"] or "未分类" for e in entries)
    with_ph = sum(1 for e in entries if e["phonetic"])
    phrases = sum(1 for e in entries if " " in e["word"])
    meta = {
        "sourceId": SOURCE_ID,
        "entryCount": str(len(entries)),
        "counts": ",".join("%s=%d" % kv for kv in
                           sorted(counts.items(), key=lambda kv: -kv[1])),
        "withPhonetic": str(with_ph),
        "phraseCount": str(phrases),
        "builtAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    con.executemany("INSERT INTO meta(key, value) VALUES(?, ?)", meta.items())
    con.commit()
    con.close()
    return {"entries": len(entries), "counts": counts, "phrases": phrases,
            "withPhonetic": with_ph, "path": out_path}


def main(argv) -> int:
    src = argv[1] if len(argv) > 1 else DEFAULT_SRC
    if not os.path.isfile(src):
        print("找不到词表: %s" % src)
        return 1
    entries = parse_markdown(src)
    raw_count = len(entries)
    entries = merge_duplicates(entries)
    if raw_count != len(entries):
        print("合并跨分类重复 %d 条：%d → %d 条"
              % (raw_count - len(entries), raw_count, len(entries)))

    stats = build(entries, OUT_PATH)
    print("解析 %d 条 → %s" % (stats["entries"], stats["path"]))
    print("  短语（含空格）%d 条，带音标 %d 条"
          % (stats["phrases"], stats["withPhonetic"]))
    for name, count in stats["counts"].items():
        print("  %-14s %3d" % (name, count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
