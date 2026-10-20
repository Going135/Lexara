# -*- coding: utf-8 -*-
"""学习日历、两种天数与成就判定（任务书 §7）。

两个**不能混**的口径
--------------------
1. **打开应用天数**：每个自然日第一次真正进入主工作状态记一次，
   同一天多次启动只算 1 天；用于 7 / 30 / 100 天成就。
2. **学习打卡天数**：当天有过至少一次真实学习活动就记一次；
   用于「学习日志 · 已打卡 XX 天」和日历颜色。

日历三色的判定（§7.2）
----------------------
- 灰：当天没有任何学习活动；
- 浅绿：只有蜘蛛扫描（八腿识词 / 连续扫词）；
- 深绿：有背单词复习 **或** 用户主动发出的 AI 提问（当天也扫描过仍是深绿）。

「当天有活动」的写入点只有三个，全部是「真的成功」才算：
`Wordbook.record_learning()`（扫描出有效词）、`Wordbook.grade()`（提交复习自评）、
`Wordbook.record_ai_ask()`（对话请求成功返回）。仅打开面板、连接测试失败、
点击没发出去的请求都不计。

本模块刻意不 import Qt，方便纯逻辑单测（时钟可注入）。
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

#: ★ 2026-10-19：日历窗口改成**自然年**（`year_span`），不再是滚动 371 天。
#: 常量保留只为兼容旧调用方（`WINDOW_DAYS` 仍然是一个「整年周对齐」时的
#: 典型天数，53 周 × 7 = 371）。新代码请用 `year_days` / `year_span`。
WINDOW_DAYS = 371

LEVEL_NONE = "none"
LEVEL_SCAN = "scan"
LEVEL_STUDY = "study"

#: 等级强弱：深绿 > 浅绿 > 灰（同日取最强）
_RANK = {LEVEL_NONE: 0, LEVEL_SCAN: 1, LEVEL_STUDY: 2}

#: 成就目录。`need` 是打开天数门槛；`all_green` 不按天数算。
ACHIEVEMENTS = {
    "open_7": {
        "id": "open_7", "name": "七日成习", "kind": "open", "need": 7,
        "desc": "累计打开词蛛 7 天",
        "cheer": "一周的坚持已经变成习惯，蜘蛛记住你每天来过的样子。",
    },
    "open_30": {
        "id": "open_30", "name": "满月不辍", "kind": "open", "need": 30,
        "desc": "累计打开词蛛 30 天",
        "cheer": "三十天，词汇量不是唯一的变化——你已经开始按节奏学习。",
    },
    "open_100": {
        "id": "open_100", "name": "百日之约", "kind": "open", "need": 100,
        "desc": "累计打开词蛛 100 天",
        "cheer": "一百天。这不是冲刺，是你给自己留下的长期记录。",
    },
    "all_green": {
        "id": "all_green", "name": "日历全绿", "kind": "green",
        "desc": "日历窗口中每一个过去的日期都有学习记录",
        "cheer": "整张日历没有一格是灰的。这张图值得存下来。",
    },
}

#: 弹窗顺序（先天数里程碑，再全绿）
ACHIEVEMENT_ORDER = ("open_7", "open_30", "open_100", "all_green")

#: 全绿成就的最小时间跨度：至少 7 天，避免「只打卡 1 天就全绿」这种假成就
GREEN_MIN_SPAN = 7


# ---------------------------------------------------------------- 日期工具

def today_key() -> str:
    return time.strftime("%Y-%m-%d")


def _as_date(key: str) -> date | None:
    try:
        return datetime.strptime(str(key), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def window_days(days: int = WINDOW_DAYS, today: str | None = None) -> list:
    """日历窗口内每一天（旧 → 新），最后一个是今天。

    ★ 2026-10-19：日历改成**自然年**（见 `year_span`）之后，这个函数只剩
      兼容用途（老的「滚动 N 天」口径）。新代码请用 `year_span` / `year_days`。
    """
    end = _as_date(today or today_key())
    if end is None:
        return []
    start = end - timedelta(days=days - 1)
    return [start + timedelta(days=index) for index in range(days)]


def year_span(today: str | None = None, year: int | None = None) -> tuple:
    """今年日历的**周对齐**边界：`(1/1 所在周的周日, 12/31 所在周的周六)`。

    为什么按周对齐而不是直接 1/1~12/31：日历是 GitHub 贡献图那种
    「一列七天、周日在上」的点阵，每列必须是一整周，否则第一列会缺几天、
    最后一行也会缺几天。多出来的那几天（去年 12 月末 / 明年 1 月初）照样
    占格子，但 `calendar_cells` 会把它们标成 `outOfYear`，画成暗色 ——
    视觉上是一整块完整的网格，语义上只统计今年。

    返回 `(date, date)`；`today` 解析失败时退化成系统当天。
    """
    anchor = _as_date(today or today_key()) or date.today()
    y = anchor.year if year is None else int(year)
    first, last = date(y, 1, 1), date(y, 12, 31)
    # `weekday()` 周一 = 0、周日 = 6；点阵里周日排最上面
    start = first - timedelta(days=(first.weekday() + 1) % 7)
    end = last + timedelta(days=(6 - (last.weekday() + 1) % 7))
    return start, end


def year_days(today: str | None = None, year: int | None = None) -> list:
    """今年日历窗口内每一天（旧 → 新），含两端补足的去年/明年那几天。"""
    start, end = year_span(today, year)
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def _learning_map(book) -> dict:
    """{日期: 等级}，由三个事件表合成；同日取最强等级。"""
    result: dict = {}

    def bump(key: str, level: str) -> None:
        key = str(key or "")
        if _as_date(key) is None:
            return
        if _RANK[level] > _RANK.get(result.get(key, LEVEL_NONE), 0):
            result[key] = level

    for event in getattr(book, "study_events", []) or []:
        if isinstance(event, dict):
            bump(event.get("date"), LEVEL_SCAN)
    for event in getattr(book, "review_events", []) or []:
        if isinstance(event, dict):
            bump(event.get("date"), LEVEL_STUDY)
    for event in getattr(book, "ai_events", []) or []:
        if isinstance(event, dict):
            bump(event.get("date"), LEVEL_STUDY)
    return result


def learning_map(book) -> dict:
    """对外暴露的学习等级表（供 UI 与成就共用同一份口径）。"""
    return _learning_map(book)


def checked_days(book) -> int:
    """已打卡天数 = 有学习活动的**去重自然日**数（不限于日历窗口）。"""
    return len(_learning_map(book))


def open_days(book) -> int:
    """打开应用天数 = 去重自然日数（用于里程碑）。"""
    keys = set()
    for key in getattr(book, "open_dates", []) or []:
        if _as_date(key) is not None:
            keys.add(str(key))
    return len(keys)


def calendar_cells(book, days: int | None = None,
                   today: str | None = None) -> list:
    """今年日历的格子：`[{date, level, future, outOfYear}]`，旧 → 新。

    ★ 2026-10-19：窗口从「滚动 `days` 天」改成**自然年**（1 月 1 日起、
      12 月 31 日止，两端按周对齐，见 `year_span`）。用户口径是
      「1-12 月从左到右」，滚动窗口会排出「11月、12月、1月…」这种跨年
      月份顺序，看着不像一张年历。

    `days` 参数只为兼容旧调用保留，传什么都不再影响结果。
    `outOfYear` 标记的是两端那几天补位格（去年 12 月末 / 明年 1 月初）：
    它们照样占格子，界面画成暗色，但不计入任何统计。
    """
    levels = _learning_map(book)
    today_value = _as_date(today or today_key())
    anchor = today_value or date.today()
    cells = []
    for day in year_days(today):
        key = day.strftime("%Y-%m-%d")
        cells.append({
            "date": key,
            "level": levels.get(key, LEVEL_NONE),
            "future": bool(today_value is not None and day > today_value),
            "outOfYear": day.year != anchor.year,
        })
    return cells


def first_record(book) -> date | None:
    """最早一条记录（含打开记录），用于「全绿」的有效区间起点。"""
    keys = [k for k in (getattr(book, "open_dates", []) or [])]
    keys += list(_learning_map(book).keys())
    values = [d for d in (_as_date(k) for k in keys) if d is not None]
    return min(values) if values else None


def range_is_all_green(book, days: int | None = None,
                       today: str | None = None,
                       min_span: int = GREEN_MIN_SPAN) -> bool:
    """**今年**已过去的日期是否全绿。

    有效日期的定义（写进 UI 文案，避免用户误解）：
    - 区间 = [max(今年 1/1, 首次记录日期), 今天]；
    - 未来日期不算、去年不算；
    - 区间长度不足 `min_span` 天时不算达成（否则第一天打卡就「全绿」）。

    ★ 2026-10-19：窗口跟着日历改成**自然年**。原来按「滚动 `days` 天」算，
      日历一改成 1-12 月就会两边对不上 —— UI 上 1 月还是灰的、成就却按
      滚动窗口判了全绿（或者反过来）。`days` 参数只为兼容旧调用保留。
    """
    end = _as_date(today or today_key())
    if end is None:
        return False
    start = date(end.year, 1, 1)
    first = first_record(book)
    if first is not None and first > start:
        start = first
    span = (end - start).days + 1
    if span < min_span:
        return False
    levels = _learning_map(book)
    day = start
    while day <= end:
        if _RANK.get(levels.get(day.strftime("%Y-%m-%d"), LEVEL_NONE), 0) <= 0:
            return False
        day += timedelta(days=1)
    return True


def summary(book, days: int | None = None, today: str | None = None) -> dict:
    """标题与图例要用的全部数字（一次算清，UI 不各算各的）。"""
    levels = _learning_map(book)
    cells = calendar_cells(book, days, today)
    # 两端的补位格（去年 12 月末 / 明年 1 月初）不算，否则「今年绿了几天」
    # 会把去年的记录也数进来。
    in_year = [c for c in cells if not c.get("outOfYear")]
    green = sum(1 for cell in in_year
                if not cell["future"] and cell["level"] != LEVEL_NONE)
    scan_only = sum(1 for cell in in_year
                    if not cell["future"] and cell["level"] == LEVEL_SCAN)
    study = sum(1 for cell in in_year
                if not cell["future"] and cell["level"] == LEVEL_STUDY)
    end = _as_date(today or today_key()) or date.today()
    first = first_record(book)
    return {
        "checked": len(levels),
        "openDays": open_days(book),
        "windowDays": len(in_year),
        "greenDays": green,
        "scanDays": scan_only,
        "studyDays": study,
        "allGreen": range_is_all_green(book, days, today),
        "rangeStart": date(end.year, 1, 1).strftime("%Y-%m-%d"),
        "rangeEnd": end.strftime("%Y-%m-%d"),
        "firstRecord": first.strftime("%Y-%m-%d") if first else "",
    }


# ---------------------------------------------------------------- 成就

def _done(book) -> dict:
    data = getattr(book, "achievements", None)
    if not isinstance(data, dict):
        data = {}
        try:
            book.achievements = data
        except Exception:                       # noqa: BLE001
            pass
    return data


def earned_ids(book, today: str | None = None) -> list:
    """当前数据**满足条件**的成就 ID（按目录顺序，不写状态）。"""
    total = open_days(book)
    out = []
    for key in ACHIEVEMENT_ORDER:
        spec = ACHIEVEMENTS[key]
        if spec["kind"] == "open":
            if total >= spec["need"]:
                out.append(key)
        elif spec["kind"] == "green":
            if range_is_all_green(book, today=today):
                out.append(key)
    return out


def claim_new(book, today: str | None = None) -> list:
    """把新达成的成就记进 `book.achievements`（`seen=False`），返回新达成项。

    只标记「已达成但未展示」，**不**在这里标记已读 —— 用户可能还来不及看到
    就退出程序，下次启动要能补弹（§7.3）。
    """
    done = _done(book)
    fresh = []
    now = time.time()
    for key in earned_ids(book, today):
        if key in done:
            continue
        spec = ACHIEVEMENTS[key]
        done[key] = {"id": key, "name": spec["name"], "desc": spec["desc"],
                     "at": now, "date": today or today_key(), "seen": False}
        fresh.append(key)
    if fresh:
        try:
            book.save()
        except Exception:                       # noqa: BLE001
            pass
    return fresh


def pending(book) -> list:
    """待展示的成就（含上次异常退出没来得及展示的），按目录顺序。"""
    done = _done(book)
    rows = [done[key] for key in ACHIEVEMENT_ORDER if key in done]
    return [dict(row) for row in rows if not row.get("seen", False)]


def mark_seen(book, keys) -> None:
    done = _done(book)
    changed = False
    for key in keys:
        row = done.get(key)
        if isinstance(row, dict) and not row.get("seen", False):
            row["seen"] = True
            changed = True
    if changed:
        try:
            book.save()
        except Exception:                       # noqa: BLE001
            pass


def pending_payload(book) -> dict:
    """给 QML 的单个待展示成就（没有就是空 dict，QML 侧全部字段兜底）。"""
    rows = pending(book)
    if not rows:
        return {}
    row = rows[0]
    spec = ACHIEVEMENTS.get(row.get("id"), {})
    return {
        "id": row.get("id", ""),
        "name": row.get("name") or spec.get("name", "成就达成"),
        "desc": row.get("desc") or spec.get("desc", ""),
        "cheer": spec.get("cheer", ""),
        "date": row.get("date", ""),
        "total": len(rows),
    }
