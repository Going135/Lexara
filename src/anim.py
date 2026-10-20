# -*- coding: utf-8 -*-
"""交互形变动画。

**刻意保持克制**：web-crawlers 的蜘蛛本体没有呼吸、没有摆头，
它的「活」全部来�� `crawler_spider` 的步态（阈值迈步 + 抬腿 + 闲置抽动）。
所以这里只保留 crawlers 里没有、但桌宠交互又必须有的几件事：

    · 跳跃弧线（远距离移动时的蹲 → 起跳 → 空中 → 落地回弹）
    · 单击/摸头/进食/登场这几下的即时反馈
    · 思考时关节球的光晕强度

要调步态参数，去 `crawler_spider.py`（那里对齐的是 crawler.js 的 T 对象）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: CSS 里蜘蛛的参考显示宽度，用来把位移量换算到实际大小
REFERENCE_WIDTH = 260.0

#: 关节红点在思考态下的光晕强度（其余状态恒定，跟原版一样是静态红点）
THINK_GLOW = (0.45, 1.0)
THINK_PERIOD = 0.55


@dataclass
class Tf:
    """一次形变：缩放、旋转、位移（位移单位为参考像素）。

    ``retract`` 独立于几何变换：0.0 = 腿全部伸出，1.0 = 腿完全收回
    （只剩本体）。由 painter 按此值把腿向髋部收缩并淡出。
    """

    sx: float = 1.0
    sy: float = 1.0
    rot: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    flip: bool = False
    retract: float = 0.0


IDENT = Tf()


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _ease_in_out(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _tf_lerp(a: Tf, b: Tf, t: float) -> Tf:
    return Tf(
        sx=_lerp(a.sx, b.sx, t),
        sy=_lerp(a.sy, b.sy, t),
        rot=_lerp(a.rot, b.rot, t),
        dx=_lerp(a.dx, b.dx, t),
        dy=_lerp(a.dy, b.dy, t),
        flip=a.flip if t < 0.5 else b.flip,
        retract=_lerp(a.retract, b.retract, t),
    )


def keyframe_at(stops, t: float) -> Tf:
    """在一组关键帧上按 t∈[0,1] 取值，中间用 ease-in-out 插值。"""
    t = _clamp01(t)
    if t <= stops[0][0]:
        return stops[0][1]
    for index in range(len(stops) - 1):
        t0, tf0 = stops[index]
        t1, tf1 = stops[index + 1]
        if t0 <= t <= t1:
            span = max(1e-6, t1 - t0)
            return _tf_lerp(tf0, tf1, _ease_in_out((t - t0) / span))
    return stops[-1][1]


# ---------------------------------------------------------------- 跳跃

#: 蹲 → 起跳 → 空中 → 落地回弹
JUMP_STOPS = (
    (0.00, Tf(dy=7.0, sx=0.84, sy=1.12, rot=0.0)),
    (0.16, Tf(dy=3.0, sx=1.05, sy=0.90, rot=-5.0)),
    (0.45, Tf(dy=-35.0, sx=0.88, sy=0.88, rot=7.0)),
    (0.72, Tf(dy=-20.0, sx=0.92, sy=0.92, rot=-4.0)),
    (0.88, Tf(dy=4.0, sx=1.08, sy=0.88, rot=2.0)),
    (1.00, Tf()),
)


def eff_jump(t: float) -> Tf:
    return keyframe_at(JUMP_STOPS, t)


# ---------------------------------------------------------------- 交互动画

def eff_squash(t: float) -> Tf:
    a = math.sin(math.pi * t) ** 0.75
    b = 0.13 * math.sin(math.pi * 3.0 * t) * (1 - t)
    k = a + b
    return Tf(sx=1 + 0.16 * k, sy=1 - 0.16 * k, dy=0.10 * REFERENCE_WIDTH * k)


def eff_shake(t: float) -> Tf:
    w = math.sin(t * math.pi * 10)
    d = (1 - t) ** 0.8
    return Tf(dx=w * 14 * d, rot=w * 6.5 * d)


def eff_pat(t: float) -> Tf:
    a = math.sin(math.pi * t) ** 0.5
    b = 0.5 + 0.5 * math.cos(t * math.pi * 7)
    k = a * b
    return Tf(sy=1 - 0.12 * k, sx=1 + 0.08 * k, dy=0.05 * REFERENCE_WIDTH * k)


def eff_eat(t: float) -> Tf:
    k = math.cos(t * math.pi * 9) * (1 - t * 0.45)
    return Tf(sy=1 + 0.07 * k, sx=1 - 0.05 * k,
              dy=0.03 * REFERENCE_WIDTH * (0.5 + 0.5 * k))


def eff_spin(t: float) -> Tf:
    """整理丝线：转身一圈。

    旋转**不**走 `Tf.rot`。`rot` 是把画好的整幅图（身子 + 十条腿）当一张贴纸
    一起转，腿的姿态纹丝不动 —— 转起来看着就是「一张图在打转」，没有生命感。

    真正的转身由 `PetWindow._tick` 在效果期间直接推进 `spider.heading`，
    身体转了、脚仍然钉在世界坐标上（`Spider.turn()` 把脚在体坐标系里反向旋转），
    于是偏离静止位 → 阈值步态被触发 → 腿一蹬一蹬地跟着迈。
    这里只留身体的轻微压扁回弹，给转身加一点重量。
    """
    return Tf(sy=1 - 0.05 * math.sin(math.pi * t))


#: 一次 spin 转过的角度（弧度）。走匀角速度，整圈在 `duration` 内转完。
SPIN_ANGLE = math.tau


def eff_pop(t: float) -> Tf:
    k = 1.0 - (1.0 - t) ** 3
    s = 0.78 + 0.22 * k + 0.05 * math.sin(math.pi * 2 * t) * (1 - t)
    return Tf(sx=s, sy=s)


def eff_alert(t: float) -> Tf:
    """识词完成：轻轻上抬一下。"""
    k = math.sin(math.pi * min(1.0, t * 1.6)) ** 0.7
    return Tf(sy=1 + 0.06 * k, sx=1 + 0.04 * k, dy=-0.05 * REFERENCE_WIDTH * k)


def eff_hide_legs(t: float) -> Tf:
    """收腿：腿向身体收缩并淡出，本体轻微膨胀（像把腿吸进去）。

    ``retract``: 0 → 1。painter 按此值把腿向髋部缩进并淡出。
    身体 sx/sy 略微放大，呼应「收拢」的体积感。
    """
    e = _ease_in_out(t)
    return Tf(retract=e, sx=1.0 + 0.12 * e, sy=1.0 + 0.12 * e)


def eff_show_legs(t: float) -> Tf:
    """伸腿：腿从身体伸出并淡入，本体先缩一下再回弹。

    ``retract``: 1 → 0（线性，保证连续）。
    身体：前 35% 蓄力收缩，之后弹出并轻微过冲再回正，像把腿「弹」出去。
    """
    retract = 1.0 - t
    if t < 0.35:
        k = t / 0.35
        body = 1.0 - 0.10 * k                     # 1.0 → 0.90
    else:
        k = (t - 0.35) / 0.65
        e = _ease_in_out(k)
        body = 0.90 + 0.10 * e + 0.06 * math.sin(math.pi * e)
    return Tf(retract=retract, sx=body, sy=body)


EFFECTS = {
    "jump": eff_jump,
    "squash": eff_squash,
    "shake": eff_shake,
    "pat": eff_pat,
    "eat": eff_eat,
    "spin": eff_spin,
    "pop": eff_pop,
    "alert": eff_alert,
    "hide_legs": eff_hide_legs,
    "show_legs": eff_show_legs,
}

#: **状态切换类**形变（而不是反馈类）。
#:
#: 只有这两个动 `retract`，而 `retract` 是一个**常驻状态**（折叠/展开），
#: 不像 `squash` 那样播完就回到原点。所以这两件事：
#:   · 不能被「按下 / 开始框选 / 开始走位」顺手清掉 —— 清了腿当场瞬移；
#:   · 播完之后要由 `PetWindow.folded` 接着维持，不能让它落回 0。
#: 其它形变（jump/squash/shake/…）的 `retract` 恒为 0，与折叠无关，
#: 所以判断「当前该收多深」时**不能**直接读 `Tf.retract`，得先看名字在不在这个集合里。
LEG_EFFECTS = ("hide_legs", "show_legs")

EFFECT_DURATION = {
    "jump": 0.72, "squash": 0.70, "shake": 0.75, "pat": 0.85, "eat": 1.2,
    "spin": 0.9, "pop": 0.55, "alert": 0.6,
    "hide_legs": 0.55, "show_legs": 0.60,
}


def apply_effect(name: str, t: float) -> Tf:
    fn = EFFECTS.get(name)
    return IDENT if fn is None else fn(_clamp01(t))


def joint_glow(state: str, elapsed: float) -> float:
    """关节红点的亮度。

    原版除了「踩中」之外关节一直是静态红点，所以 idle/crawl/rest 恒为 1.0；
    只有 think（识词中）才脉动一下，提醒「它在干活」。
    """
    if state != "think":
        return 1.0
    u = (elapsed % THINK_PERIOD) / THINK_PERIOD
    u = u * 2.0 if u <= 0.5 else (1.0 - u) * 2.0          # alternate
    return _lerp(THINK_GLOW[0], THINK_GLOW[1], _ease_in_out(u))