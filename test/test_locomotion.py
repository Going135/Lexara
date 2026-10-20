# -*- coding: utf-8 -*-
"""运动学不变量测试（不依赖 GUI，纯几何 + 确定性时间步）。

任务书 §9.3 要求「截图用于肉眼检查，断言用于防回归」。本文是断言那一半里
最底层的三条物理事实，2026-10-18 那次「蜘蛛倒着走」的回归就藏在这里：

    A. **脚钉在世界上**：身体平移 + 转向的任意一帧里，处于支撑阶段
       （没在迈步）的脚尖世界坐标必须**一个数都不变**。
       这条同时锁住两套坐标系的换算：`update(motion=)` 吃世界位移、
       `advance()` 活体坐标系、`turn()` 反向旋转 —— 三者必须自洽。
    B. **头部领路**：八个方向移动后，头（局部 +x）的世界方向与运动方向
       夹角 < 15°，且头比腹更靠前。
    C. **身体一动腿就必须迈**：平移足够远要产生迈步（否则就是「整张图平移」
       的滑步），但同迈上限、骨长、可达半径都不能破。

运行：  python test/test_locomotion.py
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import crawler_spider as CS          # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if condition else "[FAIL]", name, detail))


STEP = 1.0 / 60.0
random.seed(7)

DIRECTIONS = (("右", (1, 0)), ("左", (-1, 0)), ("下", (0, 1)), ("上", (0, -1)),
              ("右下", (0.7071, 0.7071)), ("左下", (-0.7071, 0.7071)),
              ("右上", (0.7071, -0.7071)), ("左上", (-0.7071, -0.7071)))


def world_of(spider, root, point):
    """体坐标点 → 世界（局部单位口径，不乘 unit）。"""
    w = spider.to_world(point)
    return (root[0] + w[0], root[1] + w[1])


def walk(spider, root, direction, distance, step_len=2.0):
    """把身体沿 ``direction`` 真实平移 ``distance``（局部单位），返回新 root。

    每一步都按 `pet_window._tick` 的口径喂 `motion`（世界位移 / 单位）。
    """
    moved = 0.0
    per_frame = min(step_len, distance - moved)
    while moved < distance - 1e-9:
        per_frame = min(step_len, distance - moved)
        motion = (per_frame * direction[0], per_frame * direction[1])
        spider.update(STEP, "crawl", None, motion=motion)
        root = (root[0] + motion[0], root[1] + motion[1])
        moved += per_frame
    return root


def settle(spider, seconds=1.5):
    for _ in range(int(seconds / STEP)):
        spider.update(STEP, "idle", None, motion=(0.0, 0.0))


def stance_drift(spider, root, per_frame_motion, frames):
    """逐帧检查「支撑 → 支撑」的脚：世界坐标必须**分毫不动**。

    口径很关键：只在「这一帧开始时没在迈步、结束时也没在迈步」的腿上比。
    迈过一步的脚本来就该落到新位置（那是步态的全部意义），
    拿旧快照去比会把正常迈步算成漂移 —— 第一版就犯过这个错。
    """
    worst = 0.0
    for _ in range(frames):
        snap = {L.index: (world_of(spider, root, L.foot), L.stepping, L.foot is not None)
                for L in spider.legs}
        motion = (per_frame_motion[0], per_frame_motion[1])
        spider.update(STEP, "crawl", None, motion=motion)
        root = (root[0] + motion[0], root[1] + motion[1])
        for leg in spider.legs:
            before, was_stepping, had_foot = snap[leg.index]
            if was_stepping or leg.stepping or not had_foot or leg.foot is None:
                continue
            now = world_of(spider, root, leg.foot)
            worst = max(worst, math.hypot(now[0] - before[0], now[1] - before[1]))
    return worst, root


print("-- A 支撑脚的世界坐标必须钉住（平移 + 转向都算） --")

for name, d in DIRECTIONS:
    s = CS.Spider(size=1.0)
    s.heading = math.pi / 2               # 默认站姿朝向（屏幕下方）
    settle(s)
    root = (600.0, 400.0)
    # 先让朝向追上运动方向（这一段允许腿正常倒换）
    root = walk(s, root, d, 60.0)
    worst, root = stance_drift(s, root, (d[0] * 0.34, d[1] * 0.34), 60)
    check("A[%s] 支撑脚世界坐标不漂移" % name, worst < 1e-6,
          "最大漂移 %.3e" % worst)

print("\n-- A2 纯自转（不平移）时脚同样钉住 --")
s = CS.Spider(size=1.0)
settle(s)
root = (0.0, 0.0)
worst = 0.0
for _ in range(60):
    snap = {L.index: (world_of(s, root, L.foot), L.stepping, L.foot is not None)
            for L in s.legs}
    s.heading += 0.002                    # 极慢自转
    s.update(STEP, "idle", None, motion=(0.0, 0.0))
    for leg in s.legs:
        before, was_stepping, had_foot = snap[leg.index]
        if was_stepping or leg.stepping or not had_foot or leg.foot is None:
            continue
        now = world_of(s, root, leg.foot)
        worst = max(worst, math.hypot(now[0] - before[0], now[1] - before[1]))
check("A2 自转时脚钉住", worst < 1e-6, "最大漂移 %.3e" % worst)

print("\n-- B 八个方向都由头部领路 --")
for name, d in DIRECTIONS:
    s = CS.Spider(size=1.0)
    s.heading = 0.0
    for _ in range(150):
        s.update(STEP, "crawl", None, motion=(d[0] * 3.0, d[1] * 3.0))
    want = math.atan2(d[1], d[0])
    head = s.to_world(s.body["head"])
    got = math.atan2(head[1], head[0])
    diff = math.degrees((got - want + math.pi) % (2 * math.pi) - math.pi)
    proj_h = head[0] * d[0] + head[1] * d[1]
    abd = s.to_world(s.body["abd"])
    proj_a = abd[0] * d[0] + abd[1] * d[1]
    check("B[%s] 头部朝运动方向" % name, abs(diff) < 15.0,
          "偏差 %.1f°" % diff)
    check("B[%s] 头比腹更靠前" % name, proj_h > proj_a,
          "头 %+.1f / 腹 %+.1f" % (proj_h, proj_a))

print("\n-- C 身体真实位移会驱动迈步，且不破约束 --")
s = CS.Spider(size=1.0)
s.heading = 0.0
settle(s)
root = (0.0, 0.0)
started, max_simult, over_reach, bone_bad = 0, 0, 0, 0
l1l2 = {L.index: (L.l1, L.l2) for L in s.legs}
for _ in range(240):
    was = {L.index: L.stepping for L in s.legs}
    root = walk(s, root, (1, 0), 165.0 * STEP, step_len=165.0 * STEP)
    started += sum(1 for L in s.legs if L.stepping and not was[L.index])
    max_simult = max(max_simult, sum(1 for L in s.legs if L.stepping))
    for leg in s.legs:
        hip = leg.hip_pos
        if math.hypot(leg.tip[0] - hip[0], leg.tip[1] - hip[1]) > leg.full * 1.001:
            over_reach += 1
        if (leg.l1, leg.l2) != l1l2[leg.index]:
            bone_bad += 1
check("C1 走路期间确实产生了迈步", started >= 8, "新迈步 %d 次" % started)
check("C2 同时离地腿数不超上限", max_simult <= CS.MAX_STEPPING_FAST + 2,
      "峰值 %d 条" % max_simult)
check("C3 脚尖不超过腿长", over_reach == 0, "越界帧 %d" % over_reach)
check("C4 骨长恒定", bone_bad == 0, "改动帧 %d" % bone_bad)
check("C5 身体确实平移了", abs(root[0] - 165.0 * 4.0) < 1.0,
      "root.x=%.1f（期望 ≈%.1f）" % (root[0], 165.0 * 4.0))

print("\n-- C6 前进时落脚点在身体前方（不是后方） --")
s = CS.Spider(size=1.0)
s.heading = 0.0
settle(s)
root = (0.0, 0.0)
ahead_cnt = behind_cnt = 0
for _ in range(240):
    was = {L.index: L.stepping for L in s.legs}
    root = walk(s, root, (1, 0), 2.5, step_len=2.5)
    for leg in s.legs:
        if leg.palp or leg.index not in was:
            continue
        if leg.stepping and not was[leg.index]:
            # 本次迈步的**新落脚点**相对旧脚位，在世界系里应当沿前进方向
            old_w = world_of(s, root, leg.frm)
            new_w = world_of(s, root, leg.nxt)
            delta = new_w[0] - old_w[0]
            if delta > 1e-9:
                ahead_cnt += 1
            elif delta < -1e-9:
                behind_cnt += 1
check("C6 新落脚点在前进方向上", ahead_cnt > behind_cnt and behind_cnt == 0,
      "向前 %d / 向后 %d" % (ahead_cnt, behind_cnt))

print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：" + "、".join(FAIL))
sys.exit(1 if FAIL else 0)
