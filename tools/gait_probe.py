# -*- coding: utf-8 -*-
"""步态体检：在**真机默认 unit**下走一段，量步态是否跟得上身体。

为什么要单独量：各种阈值（STEP_FRAC 等）都是**局部单位**，而 165 px/s
换算成局部单位/秒要除以 unit，unit 又随桌宠大小变
（unit = unit_for_width(sprite_w)，默认 sprite_w=360 → unit≈1.23）。
所以拿小尺寸探针的 unit 调出来的常量，到真机上可能完全不是一回事 ——
必须按真机 unit 量。

指标：
  · 每条**步足**每秒开步次数（0 = 腿被拖着走，远大于 1/步时 = 抽搐）
  · over 帧占比（tip 贴到 OVER_FRAC×腿长）—— 越接近 0 越好，
    贴住就意味着这条腿正在被硬夹，画面上是「拉长的腿」
  · 步态周期时长

A/B 用法：`--src <另一份源目录>` 可以拿旧版本对比同一指标，
判断「新步态到底是变好还是变差」。
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_argv = sys.argv[1:]
SRC = os.path.join(ROOT, "src")
if "--src" in _argv:
    SRC = _argv[_argv.index("--src") + 1]
sys.path.insert(0, SRC)

from PySide6.QtWidgets import QApplication

import crawler_spider as CS
from spider_painter import SpiderPainter

app = QApplication(sys.argv)

APP_SPRITE_W = 360.0                  # pet_window.base_sprite_w 默认值 × scale=1
UNIT = SpiderPainter.unit_for_width(APP_SPRITE_W)
LOCAL_PER_SEC_165 = 165.0 / UNIT      # WALK_SPEED(px/s) 换算成局部单位/秒


def is_over(leg) -> bool:
    hx, hy = leg.hip_pos
    return math.hypot(leg.tip[0] - hx, leg.tip[1] - hy) >= leg.full * CS.OVER_FRAC - 1e-9


def run(px_speed: float, seconds: float = 6.0) -> None:
    spider = CS.Spider(size=1.0)
    spider.heading = math.pi / 2
    step_local = px_speed / UNIT / 60.0
    steppers = [L for L in spider.legs if not L.palp]
    steps = {L.index: 0 for L in steppers}
    was = {L.index: L.stepping for L in steppers}
    over_frames = 0
    clamped_frames = 0
    frames = 0
    limit = getattr(CS, "REACH_LIMIT_FRAC", None)

    for _ in range(int(seconds * 60)):
        spider.update(1 / 60, "crawl", None, motion=(step_local, 0.0))
        for L in steppers:
            if L.stepping and not was[L.index]:
                steps[L.index] += 1
            was[L.index] = L.stepping
        if any(is_over(L) for L in steppers):
            over_frames += 1
        if limit is not None and any(
                math.hypot(L.tip[0] - L.hip_pos[0], L.tip[1] - L.hip_pos[1])
                > L.full * limit - 1e-6 for L in steppers):
            clamped_frames += 1
        frames += 1

    total = sum(steps.values())
    rate = getattr(CS, "GAIT_PHASE_PER_UNIT", 0.0)
    local_per_sec = px_speed / UNIT
    period = (1.0 / (local_per_sec * rate)) if rate else float("inf")

    print("\n=== %3.0f px/s（= %.1f 局部单位/秒）===" % (px_speed, local_per_sec))
    print("  开步 %3d 次 / 8 条步足 / %.0f 秒 → 每腿 %.2f 次/秒" %
          (total, seconds, total / 8.0 / seconds))
    print("  各步足开步次数 %s" % [steps[L.index] for L in steppers])
    print("  over 帧占比 %5.1f%%" % (100.0 * over_frames / frames))
    if limit is None:
        print("  [无夹子] 旧版没有 REACH_LIMIT_FRAC，tip 可以飞出腿长之外")
    else:
        print("  被硬夹帧占比 %5.1f%%（夹住 = 画面上腿被拉长）" %
              (100.0 * clamped_frames / frames))
    if period != float("inf"):
        print("  步态周期 ≈ %.2f 秒" % period)


print("源码目录:", SRC)
print("unit = %.3f（sprite_w=%.0f）" % (UNIT, APP_SPRITE_W))
for speed in (60.0, 165.0, 320.0):
    run(speed)

ref = CS.Spider(size=1.0)
steppers = [L for L in ref.legs if not L.palp]
avg_reach = sum(L.reach for L in steppers) / len(steppers)
avg_full = sum(L.full for L in steppers) / len(steppers)
print("\n参考：平均 reach=%.0f、腿长 full=%.0f（局部单位）；"
      "STEP_FRAC=%.2f → 偏离静止位约 %.0f 就该迈步"
      % (avg_reach, avg_full, CS.STEP_FRAC, avg_reach * CS.STEP_FRAC))
if hasattr(CS, "GAIT_WINDOW"):
    print("      GAIT_WINDOW=%.2f（每条腿相位窗口占周期的比例）" % CS.GAIT_WINDOW)
