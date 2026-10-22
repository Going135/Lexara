# -*- coding: utf-8 -*-
"""收藏夹单词本导出：文本 / 表格 / 备份三种出口（纯逻辑，无 Qt）。

三个出口对应三种拿走的理由，**不做第四种**（apkg/PDF 都评估过，收益配不上
长期兼容负担）：

- `txt`   —— 人读：按收藏夹五分类 + 未分类分节，`word /音标/ 释义`。
  `study=True` 是「复习遮答案版」：只留词和音标，释义位置换成下划线，
  打印出来直接默写。
- `csv`   —— 机器再用：Excel/WPS 可筛选。含分类、复习进度、对/错次数。
- `json`  —— 完整备份：形状照 `wordbook.json`（`schemaVersion`/`items`），
  将来导入/还原功能直接吃它；外加一段 `_lexaraMeta` 说明这是导出件。
  （词库 schema 本身一个字没改 —— 改它要双方协商，这里只是**读出来**。）

三条红线：
1. **编码**：txt/csv 一律 UTF-8 带 BOM。不带 BOM 的 UTF-8 在中文 Windows 的
   Excel/记事本里是乱码，「直接拿走」就白做了。
2. **原子写**：`.tmp` + `os.replace`，和 settings/wordbook 同一条路子；
   导出坏一半比不导出更糟。
3. **不碰词库**：本模块只收 `Item` 列表读字段，永不回写。
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from typing import Any, Dict, List

from lexicon import FAVORITE_CATEGORIES, OTHER_CATEGORY

FORMATS = ("txt", "csv", "json")
FORMAT_LABELS = {"txt": "文本", "csv": "表格", "json": "备份"}

#: 一词可属多个收藏夹分类（和侧栏计数同一口径：命中几个就进几节）。
#: 分类归属复用 `launcher_qml.tags_of` 的逻辑，这里独立实现一份最小版，
#: 避免纯逻辑模块反向拖起 Qt。
_CATEGORY_KEYS = {key for key, _label in FAVORITE_CATEGORIES}


def _tags_of(item, lexicon) -> set:
    tags = set(getattr(item, "tags", None) or [])
    if tags:
        return tags
    if lexicon is not None:
        try:
            return set(lexicon.tags_of(item.word))
        except Exception:                       # noqa: BLE001
            return set()
    return set()


def _sections(items, lexicon) -> List[tuple]:
    """(分类键, 显示名, [item]) 列表；顺序 = 侧栏顺序，未分类垫底。"""
    rows = []
    for key, label in FAVORITE_CATEGORIES:
        rows.append((key, label,
                     [i for i in items if key in _tags_of(i, lexicon)]))
    other = [i for i in items
             if not (_tags_of(i, lexicon) & _CATEGORY_KEYS)]
    rows.append((OTHER_CATEGORY[0], OTHER_CATEGORY[1], other))
    return rows


def _meaning_line(item) -> str:
    meaning = (getattr(item, "meaning", "") or "").replace("\n", " ").strip()
    return meaning or "（无释义）"


# ---------------------------------------------------------------- 三种渲染
def render_txt(items, lexicon=None, study: bool = False) -> str:
    """人读版 / 遮答案复习版。空分类不出节，全空给一句说明。"""
    lines = ["LEXARA 词蛛 · 我的单词本",
             "导出时间：%s" % time.strftime("%Y-%m-%d %H:%M"),
             "共 %d 词" % len(items), ""]
    wrote = False
    for _key, label, bucket in _sections(items, lexicon):
        if not bucket:
            continue
        wrote = True
        lines.append("── %s（%d）%s" % (label, len(bucket), "─" * 8))
        for item in bucket:
            phonetic = (getattr(item, "phonetic", "") or "").strip()
            head = "%s %s" % (item.word, phonetic) if phonetic else item.word
            if study:
                lines.append("%s  %s" % (head, "_" * 24))
            else:
                lines.append("%s  %s" % (head, _meaning_line(item)))
        lines.append("")
    if not wrote:
        lines.append("（还没有收藏任何单词）")
    return "\n".join(lines).rstrip() + "\n"


def render_csv(items, lexicon=None) -> str:
    """表格版。释义里的逗号/引号/换行交给 csv 模块转义，不手拼。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["word", "phonetic", "meaning", "categories", "level",
                     "stage", "due_date", "correct", "wrong", "added_date"])
    for item in items:
        tags = _tags_of(item, lexicon)
        cats = "|".join(label for key, label in FAVORITE_CATEGORIES
                        if key in tags) or OTHER_CATEGORY[1]
        due_at = getattr(item, "due_at", 0.0) or 0.0
        stage = int(getattr(item, "stage", -1))
        writer.writerow([
            item.word,
            (getattr(item, "phonetic", "") or "").strip(),
            (getattr(item, "meaning", "") or "").replace("\n", " ").strip(),
            cats,
            getattr(item, "level", "") or "",
            stage,
            time.strftime("%Y-%m-%d", time.localtime(due_at)) if due_at else "",
            int(getattr(item, "correct", 0) or 0),
            int(getattr(item, "wrong", 0) or 0),
            time.strftime("%Y-%m-%d", time.localtime(getattr(item, "added_at", 0)
                                                     or time.time())),
        ])
    return buffer.getvalue()


def render_json(items, lexicon=None) -> str:
    """备份版：形状 = wordbook.json + `_lexaraMeta`。还原端按 items 读即可。"""
    payload: Dict[str, Any] = {
        "schemaVersion": 3,
        "items": [i.to_dict() for i in items],
        "_lexaraMeta": {
            "kind": "lexara-word-export",
            "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "count": len(items),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=1) + "\n"


# ---------------------------------------------------------------- 落盘
def _ensure_extension(path: str, fmt: str) -> str:
    """用户在保存对话框里不打后缀时补上格式后缀；已有任何后缀则尊重选择。"""
    root, ext = os.path.splitext(path)
    if ext:
        return path
    return path + "." + fmt


def export(items, fmt: str, path: str, lexicon=None,
           study: bool = False) -> Dict[str, Any]:
    """渲染 + 原子写。返回 {ok, path, count, message}；失败不抛异常。"""
    if fmt not in FORMATS:
        return {"ok": False, "message": "未知导出格式 %s" % fmt}
    if not items:
        return {"ok": False, "message": "词库是空的，没有可导出的内容"}
    path = _ensure_extension(os.path.abspath(os.path.expanduser(path)), fmt)
    if fmt == "txt":
        text = render_txt(items, lexicon, study=study)
        encoding = "utf-8-sig"          # BOM：中文 Windows 记事本/Excel 认这个
    elif fmt == "csv":
        text = render_csv(items, lexicon)
        encoding = "utf-8-sig"
    else:
        text = render_json(items, lexicon)
        encoding = "utf-8"              # JSON 规范禁止 BOM
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temp = path + ".tmp"
        with open(temp, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        os.replace(temp, path)
    except OSError as error:
        try:
            os.unlink(temp)
        except OSError:
            pass
        return {"ok": False, "message": "写入失败：%s" % error}
    label = {"txt": "文本", "csv": "表格", "json": "备份"}[fmt]
    return {"ok": True, "path": path, "count": len(items),
            "message": "已导出 %d 个单词（%s）→ %s" % (len(items), label, path)}


def default_name(fmt: str) -> str:
    return "词蛛单词本_%s.%s" % (time.strftime("%Y%m%d"), fmt)
