# -*- coding: utf-8 -*-
"""默写判分：把用户敲进去的一串字母和词条的规范拼写对上。

为什么判分在 Python 而不在 QML
------------------------------
规则本身很简单，但**会一直长**：全角字母、首尾标点、大小写、多余空格、
连字符、英美拼写、一键输入法带出来的弯引号……这些每一条都在真实使用里
冒出来过。写在 QML 里就没法单元测试，改一次要开窗口手敲一遍。

所以这里是一个纯函数模块：不依赖 Qt、不读配置、不改词库。`launcher_qml`
只负责把状态搬给界面，判断本身只有这一个真相。

判定口径
--------
- `correct`：归一化后完全一致；或者仅大小写 / 空格 / 连字符 / 首尾标点
  不同（拼写本身没错，不该判错，但要把规范写法告诉用户）
- `empty`：没输入（空串或纯标点）
- `wrong`：其余

`hint` 是给界面第二行小字用的**人话**，不返回「编辑距离 = 2」这种机器字段。
"""
from __future__ import annotations

import re
import unicodedata

#: 首尾要剥掉的字符。**只剥首尾**：`well-known` 中间的连字符是拼写的一部分，
#: 一起删掉会让 `wellknown` 被判成正确。
_EDGE_JUNK = re.compile(
    r"^[\s\"'“”‘’()\[\]{}<>.,;:!?·…—–]+|[\s\"'“”‘’()\[\]{}<>.,;:!?·…—–]+$")

_WS = re.compile(r"\s+")

#: 宽松比较时忽略的字符（大小写之外）。注意**不含字母本身**。
_LOOSE_DROP = re.compile(r"[\s\-'’]")


def normalize(text: str) -> str:
    """把用户输入和词条都过一遍同一个漏斗：全角转半角、弯引号摆正、去首尾杂字。"""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = _WS.sub(" ", s).strip()
    s = _EDGE_JUNK.sub("", s)
    return s.casefold()


def _loose(s: str) -> str:
    return _LOOSE_DROP.sub("", s)


def edit_distance(a: str, b: str, limit: int = 3) -> int:
    """Levenshtein 距离，超过 `limit` 就早退成 `limit+1`（只用来挑文案）。"""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    best = prev[-1]
    return best if best <= limit else limit + 1


def empty_state(open: bool = False, answer: str = "") -> dict:
    """弹窗的初始状态。`launcher_qml` 每次打开 / 关闭 / 换卡片都拿这个铺一遍，
    **不要手写字面量** —— 少一个键，QML 那边就会读到 undefined 并在控制台报警告。
    """
    return {
        "open": bool(open),
        "verdict": "",
        "answer": str(answer or ""),
        "typed": "",
        "distance": 0,
        "hint": "",
        "attempts": 0,
    }


def check(typed: str, answer: str) -> dict:
    """判一次默写。

    返回 `{"verdict", "answer", "typed", "distance", "hint"}`，
    `answer` 原样回传，界面直接显示「正确拼写：xxx」。
    """
    word = str(answer or "").strip()
    raw = str(typed or "")
    result = {
        "verdict": "wrong",
        "answer": word,
        "typed": raw.strip(),
        "distance": 0,
        "hint": "",
    }

    want = normalize(word)
    got = normalize(raw)
    if not got:
        result["verdict"] = "empty"
        result["hint"] = "还没输入。"
        return result
    if got == want:
        result["verdict"] = "correct"
        return result

    result["distance"] = edit_distance(got, want)

    # 大小写 / 空格 / 连字符 / 首尾标点不同：拼写是对的，不该判错。
    if _loose(got) == _loose(want):
        result["verdict"] = "correct"
        result["hint"] = "拼写正确。规范写法是 %s" % word
        return result

    if result["distance"] == 1:
        result["hint"] = "只差一个字母。"
    elif result["distance"] == 2:
        result["hint"] = "差了两个字母。"
    elif result["distance"] == 3:
        result["hint"] = "差了三个字母。"
    else:
        result["hint"] = "和正确拼写差得比较远。"
    return result
