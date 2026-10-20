# -*- coding: utf-8 -*-
"""转身动画的单元测试（不依赖 GUI）。

要验的是「转身」这件事的**物理**，不是画面：

    · 转动身体时，脚必须**钉在世界坐标**上（体坐标系里反向旋转）
    · 于是脚相对静止位产生偏离 → 阈值步态被触发 → 腿一蹬一蹬地倒换
    · 站着不动时脚**一步都不能迈**（新加的 turn() 不能在 hdelta=0 时乱动）
    · 转身不再走 `Tf.rot`（那会把身子和腿当一张图一起转，腿完全不动）

运行：  python test/test_spin.py
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import anim          # noqa: E402
import crawler_spider as CS   # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if condition else "[FAIL]", name, detail))


STEP = 1.0 / 60.0
random.seed(11)


def settle(spider, seconds=1.5):
    """空跑到稳定（初值刚建好时腿还在往静止位散）。"""
    for _ in range(int(seconds / STEP)):
        spider.update(STEP)


def count_steps(spider, frames, turn_per_frame=0.0):
    """跑 ``frames`` 帧，返回新发起的迈步次数。``turn_per_frame`` 是每帧转的弧度。"""
    started = 0
    for _ in range(frames):
        was = {L.index: L.stepping for L in spider.legs}
        spider.heading += turn_per_frame
        spider.update(STEP)
        for leg in spider.legs:
            if leg.stepping and not was.get(leg.index):
                started += 1
    return started


def world_foot(spider, leg):
    """脚的**世界**坐标：体坐标 × 朝向旋转（本文里身体从不平移，原点恒为 0）。"""
    c, s = math.cos(spider.heading), math.sin(spider.heading)
    return (leg.foot[0] * c - leg.foot[1] * s,
            leg.foot[0] * s + leg.foot[1] * c)


print("-- A 脚钉在世界坐标上 --")

spider = CS.Spider(size=1.0)
settle(spider)
leg = next(L for L in spider.legs if not L.palp and L.slot == 0)

# 转一丁点（远低于迈步阈值），期间不会有腿迈步，脚应当被原地钉住
before_world = world_foot(spider, leg)
before_local = leg.foot
TINY = 0.02
spider.heading += TINY
spider.update(STEP)
after_world = world_foot(spider, leg)

check("A1 转动后脚的**世界**坐标不动（没被刚体带着转）",
      math.hypot(after_world[0] - before_world[0],
                 after_world[1] - before_world[1]) < 1e-9,
      "位移 %.2e" % math.hypot(after_world[0] - before_world[0],
                               after_world[1] - before_world[1]))

# 体坐标系里应当**反向**转了 TINY
c, s = math.cos(-TINY), math.sin(-TINY)
expect = (before_local[0] * c - before_local[1] * s,
          before_local[0] * s + before_local[1] * c)
check("A2 体坐标系里脚反向转了 -Δ（符号没写反）",
      math.hypot(leg.foot[0] - expect[0], leg.foot[1] - expect[1]) < 1e-9,
      "偏差 %.2e" % math.hypot(leg.foot[0] - expect[0], leg.foot[1] - expect[1]))

# 反证：如果写成 +Δ（顺着转），脚会被甩出去两倍
wrong_c, wrong_s = math.cos(TINY), math.sin(TINY)
wrong = (before_local[0] * wrong_c - before_local[1] * wrong_s,
         before_local[0] * wrong_s + before_local[1] * wrong_c)
check("A3 不是顺着转（+Δ 会让偏差翻倍）",
      math.hypot(leg.foot[0] - wrong[0], leg.foot[1] - wrong[1]) > 1e-6,
      "与错误写法的差距 %.4f" % math.hypot(leg.foot[0] - wrong[0],
                                          leg.foot[1] - wrong[1]))

print()
print("-- B 转身真的驱动了步态 --")

still = CS.Spider(size=1.0)
settle(still)
for _ in range(int(3.0 / STEP)):        # 让待机徽章姿势先收敛，分离「落位 vs 抽搐」
    still.update(STEP)
idle_steps = count_steps(still, int(1.0 / STEP))
check("B1 站着不动且已摆好徽章姿势后一步都不迈（turn 没在 hdelta=0 时乱动）",
      idle_steps == 0, "→ %d 次" % idle_steps)

# 慢转：约 0.6 rad/s（比真机转身 6.98 rad/s 慢得多，是更苛刻的用例）
turning = CS.Spider(size=1.0)
settle(turning)
slow_steps = count_steps(turning, int(1.0 / STEP), turn_per_frame=0.01)
check("B2 慢速自转（0.6 rad/s）也开始迈步", slow_steps > 0,
      "→ %d 次/秒" % slow_steps)

# 真机转身的角速度：SPIN_ANGLE / duration
spin_rate = anim.SPIN_ANGLE / anim.EFFECT_DURATION["spin"]
fast = CS.Spider(size=1.0)
settle(fast)
fast_steps = count_steps(fast, int(1.0 / STEP), turn_per_frame=spin_rate * STEP)
check("B3 真机转身角速度（%.2f rad/s）下八条腿都在倒换" % spin_rate,
      fast_steps >= 8, "→ %d 次/秒" % fast_steps)

# 迈步的腿应该是**轮换**的，不是两条腿反复抽
which = set()
once = CS.Spider(size=1.0)
settle(once)
for _ in range(int(0.9 / STEP)):
    once.heading += spin_rate * STEP
    once.update(STEP)
    for leg in once.legs:
        if leg.stepping:
            which.add(leg.index)
check("B4 一圈里至少 6 条不同的腿参与了迈步（是行波不是抽搐）",
      len(which) >= 6, "→ %d 条：%s" % (len(which), sorted(which)))

print()
print("-- C 转身期间脚没有被拖出腿长 --")

# 转动会不断把脚推离静止位，若不及时迈步就会被拉长。
# 这里测「over（贴到硬上限）」的帧占比，超过 20% 说明腿跟不上身体。
over_frames = 0
total = 0
probe = CS.Spider(size=1.0)
settle(probe)
for _ in range(int(0.9 / STEP)):
    probe.heading += spin_rate * STEP
    probe.update(STEP)
    for leg in probe.legs:
        total += 1
        hx, hy = leg.hip_pos
        tip = leg.tip
        if math.hypot(tip[0] - hx, tip[1] - hy) > leg.full * CS.OVER_FRAC:
            over_frames += 1
ratio = over_frames / max(total, 1)
check("C1 转身时脚贴到腿长硬上限的帧占比 < 20%%", ratio < 0.20,
      "→ %.1f%%" % (ratio * 100.0))

print()
print("-- D 转身不走「整张图一起转」--")

check("D1 eff_spin 不再带 rot（否则腿纹丝不动）",
      all(anim.eff_spin(t).rot == 0.0
          for t in (0.0, 0.25, 0.5, 0.75, 1.0)),
      "rot = %s" % [anim.eff_spin(t).rot for t in (0.0, 0.5, 1.0)])
check("D2 SPIN_ANGLE 是整圈（2π）",
      abs(anim.SPIN_ANGLE - 2.0 * math.pi) < 1e-9,
      "→ %.6f rad" % anim.SPIN_ANGLE)
check("D3 eff_spin 仍保留身体的压扁回弹",
      abs(anim.eff_spin(0.5).sy - 0.95) < 1e-9,
      "sy(0.5) = %.4f" % anim.eff_spin(0.5).sy)

# 匀角速度：整圈在 duration 内转完（复算 _tick 里的推进）
frames = int(anim.EFFECT_DURATION["spin"] / STEP)
total_turn = sum(anim.SPIN_ANGLE * STEP / anim.EFFECT_DURATION["spin"]
                 for _ in range(frames))
check("D4 匀角速度推进，整圈刚好转完",
      abs(total_turn - anim.SPIN_ANGLE) < 0.05,
      "累计 %.4f rad / 目标 %.4f rad" % (total_turn, anim.SPIN_ANGLE))

print()
print("-- E 步态相位跟着转 --")

phases = []
wave = CS.Spider(size=1.0)
settle(wave)
for _ in range(int(0.9 / STEP)):
    wave.heading += spin_rate * STEP
    wave.update(STEP)
    phases.append(wave.gait_phase)
# 相位必须真的在推进：只算平移的话这里会恒为 0（原地转身没有位移）
advanced = sum(1 for a, b in zip(phases, phases[1:]) if b != a)
check("E1 原地转身时步态相位仍在推进（不只按平移算）",
      advanced >= len(phases) - 2,
      "→ %d/%d 帧有推进" % (advanced, len(phases) - 1))

print()
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), "；".join(FAIL)))
    sys.exit(1)
print("全部通过：%d 项" % len(PASS))
