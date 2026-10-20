# -*- coding: utf-8 -*-
"""「近处走、远处跳」的决策回归（任务书 §4）。

三条硬要求，逐条对上：

    ① 阈值**集中**且随体型缩放：不能是散在文件里的写死像素数；
    ② 距离与阈值**同一坐标系**：都用屏幕逻辑像素（DPR 不参与比较）；
    ③ 阈值附近**不闪烁切换**：滞回 + 单段决策锁定。

①②③ 的纯函数部分不需要 GUI；最后一组把真 `PetWindow.travel_to()` 拉起来，
确认「生产入口」确实按这套策略走 —— 以前那里写的是 `distance > 260.0`。

运行：  python test/test_walk_jump.py
"""

from __future__ import annotations

import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QPoint                          # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

import crawler_spider as CS                                # noqa: E402
import locomotion                                          # noqa: E402
from spider_painter import SpiderPainter                   # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-56s %s" % ("ok" if ok else "FAIL", name, detail))


print("\n[①] 阈值来自腿展，跟着体型缩放")

spider = CS.Spider(size=1.0)
thresholds, spans = {}, {}
for width in (120.0, 180.0, 360.0, 540.0):
    unit = SpiderPainter.unit_for_width(width)
    spans[width] = locomotion.leg_span_px(spider, unit)
    thresholds[width] = locomotion.walk_jump_threshold(spider, unit)

ordered = [thresholds[w] for w in (120.0, 180.0, 360.0, 540.0)]
check("尺寸越大阈值越大（单调不减）",
      all(b >= a for a, b in zip(ordered, ordered[1:])),
      "→ %s" % [round(v, 1) for v in ordered])
check("全部夹在 [MIN, MAX] 里（小尺寸不乱跳、大尺寸不慢爬）",
      all(locomotion.MIN_THRESHOLD_PX <= v <= locomotion.MAX_THRESHOLD_PX
          for v in ordered),
      "→ 区间 [%.0f, %.0f]" % (locomotion.MIN_THRESHOLD_PX,
                               locomotion.MAX_THRESHOLD_PX))
t360 = thresholds[360.0]
check("真机档位（sprite_w=360）保持原有手感：≈260px",
      abs(t360 - 260.0) < 30.0, "→ %.1fpx（腿展 %.0fpx）" % (t360, spans[360.0]))

print("\n[②] 同一坐标系 + 滞回：阈值附近不许反复翻")


def flips(distances, threshold):
    """按 `distances` 依次决策，返回「走↔跳」翻脸次数。"""
    previous, count = None, 0
    for d in distances:
        nxt = locomotion.decide_movement(d, threshold, previous)
        if previous is not None and nxt != previous:
            count += 1
        previous = nxt
    return count


wobble = [t360 * (1.0 + 0.02 * math.sin(i * 0.7)) for i in range(240)]
check("距离在阈值 ±2% 抖 240 次：翻转 ≤1 次",
      flips(wobble, t360) <= 1, "→ %d 次" % flips(wobble, t360))
check("近处（0.4×阈值）判走",
      locomotion.decide_movement(t360 * 0.4, t360) == locomotion.WALK)
check("远处（3×阈值）判跳",
      locomotion.decide_movement(t360 * 3.0, t360) == locomotion.JUMP)
mid = t360 * (1.0 - locomotion.HYSTERESIS * 0.5)
check("落在滞回带里：上一次是走就一直走",
      locomotion.decide_movement(mid, t360, locomotion.WALK) == locomotion.WALK,
      "→ d=%.1f t=%.1f" % (mid, t360))
check("落在滞回带里：上一次是跳就一直跳",
      locomotion.decide_movement(mid, t360, locomotion.JUMP) == locomotion.JUMP)
check("越过阈值就立刻换跳（不能被滞回拖住）",
      locomotion.decide_movement(t360 * 1.02, t360, locomotion.WALK)
      == locomotion.JUMP)
check("退回带外才换走",
      locomotion.decide_movement(t360 * (1.0 - locomotion.HYSTERESIS * 2),
                                 t360, locomotion.JUMP) == locomotion.WALK)

j0 = locomotion.jump_duration(t360 * 1.2, t360, 0.78)
j1 = locomotion.jump_duration(t360 * 6.0, t360, 0.78)
check("跳得越久才落地（远跳不比近跳一样快，倍数夹住）",
      j1 > j0 and j1 <= 0.78 * 1.6 + 1e-6, "→ %.2fs / %.2fs" % (j0, j1))

print("\n[③] 生产入口：PetWindow.travel_to 真的按这套策略走/跳")

import pet_window as PW                                    # noqa: E402


class _FakeBook:
    """只为撑住结果卡片的构造，不参与本测试的断言。"""

    def __init__(self):
        self._s = set()

    def has(self, w):
        return w in self._s

    def add(self, item):
        self._s.add(item["lemma"])
        return True

    def remove(self, w):
        self._s.discard(w)

    def __len__(self):
        return len(self._s)

    def stats(self):
        return {}

    def items(self):
        return []

    def review_queue(self):
        return []

    def record_learning(self, words) -> int:
        return 0


pet = PW.PetWindow(None, _FakeBook(), sprite_w=360.0)
pet._timer.stop()
pet.bubble.hide_now()

screen = pet._screen_rect()
# 先把本体放到屏幕正中：`travel_to` 会 `_clamp_point`（四周留 sprite_w×0.45 的边距），
# 贴着边时「目标=自己」也会被夹走，那就测不到「已经在目标上」这条分支了。
pet.center = QPoint(int(screen.center().x()), int(screen.center().y()))
near = QPoint(int(pet.center.x() + t360 * 0.35), int(pet.center.y()))
far = QPoint(int(pet.center.x() + t360 * 2.5), int(pet.center.y()))

pet.travel_to(near)
check("近距离 → 走（_travel[4] 为假）",
      pet._travel is not None and pet._travel[4] is False,
      "→ %s" % (pet._travel and ("跳" if pet._travel[4] else "走")))
check("走路时长按距离算（不是固定值）",
      pet._travel is not None and 0.25 <= pet._travel[3] <= 4.0,
      "→ %.2fs" % (pet._travel[3] if pet._travel else -1))

pet.travel_to(far)
check("远距离 → 跳", pet._travel is not None and pet._travel[4] is True,
      "→ %s" % (pet._travel and ("跳" if pet._travel[4] else "走")))
check("跳跃时长比基准 0.78s 长（远跳慢半拍才有抛物线）",
      pet._travel is not None and pet._travel[3] > PW.JUMP_DURATION,
      "→ %.2fs" % (pet._travel[3] if pet._travel else -1))

# 单段决策锁定：正在跳的这一段不会因为中途换目标（距离落到带内）而翻成走
pet.travel_to(QPoint(near.x(), near.y()))
locked = pet._movement_choice
pet.travel_to(QPoint(int(pet.center.x() + t360 * (1.0 - 0.5 * locomotion.HYSTERESIS)),
                     int(pet.center.y())))
check("带内目标沿用上一次决定（没有翻脸）",
      pet._movement_choice == locked,
      "→ %s（历史 %s）" % (pet._movement_choice, locked))

# `force_jump` 入口还在（main.py / 部署链路会显式指定）
pet.travel_to(near, force_jump=True)
check("显式 force_jump=True 仍然优先于策略",
      pet._travel is not None and pet._travel[4] is True)
pet.travel_to(far, force_jump=False)
check("显式 force_jump=False 仍然优先于策略",
      pet._travel is not None and pet._travel[4] is False)

# 坐标系一致性：`travel_to` 实际选的方式，必须等于「拿 center 到**夹好后**目标
# 的逻辑像素距离」交给纯策略算出来的结果 —— 距离、阈值、决策三者同一坐标系。
mismatch = 0
for delta in (0.3, 0.7, 0.95, 1.05, 1.6, 3.2):
    pet._movement_choice = None
    target = QPoint(int(pet.center.x() + t360 * delta), int(pet.center.y()))
    pet.travel_to(target)
    if pet._travel is None:
        continue
    real = pet._travel[1]
    distance = math.hypot(real.x() - pet.center.x(), real.y() - pet.center.y())
    want = locomotion.decide_movement(
        distance, locomotion.walk_jump_threshold(pet.spider, pet.unit))
    if (locomotion.JUMP if pet._travel[4] else locomotion.WALK) != want:
        mismatch += 1
check("走/跳与「center→目标的逻辑像素距离」的判定完全一致",
      mismatch == 0, "→ 6 档里 %d 档不一致" % mismatch)

pet.center = QPoint(int(screen.center().x()), int(screen.center().y()))
pet.travel_to(QPoint(pet.center))
check("已经在目标上：历史清空，回到「没有决定」",
      pet._movement_choice is None and pet._travel is None,
      "→ %s" % (pet._movement_choice,))

pet.close()

print("\n" + "=" * 78)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
for name in FAIL:
    print("  FAILED:", name)
raise SystemExit(1 if FAIL else 0)
