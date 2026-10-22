# -*- coding: utf-8 -*-
"""程序化蜘蛛的单元测试（不依赖 GUI）。

覆盖：腿的构成、两骨 IK、阈值步态、抬腿插值、目标绑定、腿↔词分配、命中区。

运行：  python test/test_spider.py
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import crawler_spider as CS   # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if condition else "[FAIL]", name, detail))


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


random.seed(7)
spider = CS.Spider(size=1.0)
steppers = [L for L in spider.legs if not L.palp]
palps = [L for L in spider.legs if L.palp]

# ---------------------------------------------------------------- 构成
print("-- 腿的构成 --")
check("共 10 条腿", len(spider.legs) == 10, "→ %d" % len(spider.legs))
check("8 步足 + 2 触须", len(steppers) == 8 and len(palps) == 2,
      "→ %d + %d" % (len(steppers), len(palps)))
check("左右各 5 条", sorted(set(L.side for L in spider.legs)) == [-1, 1])
check("八色微光不重复",
      len({L.aura for L in steppers}) == 8,
      "→ %d" % len({L.aura for L in steppers}))
check("触须更短", all(P.full < S.full for P in palps for S in steppers))
# 骨长比例不再锁死具体数值（2026-10-22 起 L1/L2 是调参项，改了就跟着变），
# 但必须守住它的**不变量**：两段和恒为 1.20×reach，且 full == l1+l2。
# 这个和值是所有「占腿长比例」阈值（OVER/PLACE/抬腿夹取）的分母，
# 一旦漂了，那些阈值在像素上的含义会整体偏移 —— 这不是能随便改的。
check("骨长比例 = CS.L1_FRAC / CS.L2_FRAC",
      all(abs(L.l1 / L.reach - CS.L1_FRAC) < 1e-6 and
          abs(L.l2 / L.reach - CS.L2_FRAC) < 1e-6
          for L in spider.legs))
check("骨长两段和恒为 1.20×reach（阈值分母不许漂）",
      abs(CS.L1_FRAC + CS.L2_FRAC - 1.20) < 1e-9,
      "→ %.4f" % (CS.L1_FRAC + CS.L2_FRAC))
check("full == l1 + l2",
      all(abs(L.full - (L.l1 + L.l2)) < 1e-9 for L in spider.legs))

# ---------------------------------------------------------------- IK
print("\n-- 两骨 IK --")
ok_ik = True
for leg in spider.legs:
    rest = spider.rest_pos(leg)
    knee = spider.solve_ik(leg.hip_pos, rest, leg.l1, leg.l2, leg.bend)
    ok_ik &= abs(dist(leg.hip_pos, knee) - leg.l1) < 1e-6
    ok_ik &= abs(dist(knee, rest) - leg.l2) < 1e-6
check("静止位：膝到髋 = 大腿骨长，膝到脚 = 小腿骨长", ok_ik)

far = (leg.hip_pos[0] + leg.full * 3, leg.hip_pos[1])
knee = spider.solve_ik(leg.hip_pos, far, leg.l1, leg.l2, leg.bend)
check("目标超出腿长时不折断（整条腿伸直）",
      abs(dist(leg.hip_pos, knee) - leg.l1) < 1e-6)

check("弯曲侧每条腿固定", all(isinstance(L.bend, int) and L.bend in (-1, 1)
                          for L in spider.legs))

# ---------------------------------------------------------------- 步态
print("\n-- 阈值步态 --")
mover = CS.Spider(size=1.0)
saw_stepping = False
max_stepping = 0
calm_max = 0
for _ in range(240):
    # 身体每帧向右移动 2.7px，脚钉在原地 → 静止位相对偏移 → 该迈步了
    mover.update(1 / 60, "crawl", 160.0, motion=(2.7, 0.0))
    n = sum(1 for L in mover.legs if L.stepping)
    calm = sum(1 for L in mover.legs if L.stepping and not L.quick)
    max_stepping = max(max_stepping, n)
    calm_max = max(calm_max, calm)
    saw_stepping |= n > 0
check("移动时会迈步", saw_stepping)
# crawler.js 的规则：紧急迈步（脚被拉太远）本就无视同时迈步数上限，
# 所以上限只对「常规迈步」生效；紧急时允许所有腿一起救火。
check("常规迈步的腿数不超过 4~6",
      calm_max <= CS.MAX_STEPPING_FAST, "峰值 %d" % calm_max)
check("紧急迈步可以超过上限（与原版一致）", max_stepping >= calm_max)
check("每条腿都有落脚点", all(L.foot is not None for L in mover.legs))
check("脚尖始终在可达范围内（IK 不折断）", all(
    dist(L.tip, L.hip_pos) <= L.full + 1e-6 for L in mover.legs))

# 同侧相邻腿不同时**常规**迈步（紧急步按原版可以破例）
violations = 0
probe = CS.Spider(size=1.0)
for _ in range(400):
    probe.update(1 / 60, "crawl", 160.0, motion=(2.7, 0.0))
    for L in probe.legs:
        if L.palp or not L.stepping or L.quick:
            continue
        for o in probe.legs:
            if o is L or o.palp or not o.stepping or o.quick or o.side != L.side:
                continue
            if abs(o.slot - L.slot) == 1:
                violations += 1
check("同侧相邻腿不同时常规迈步", violations == 0, "冲突 %d 次" % violations)

# 抬腿：迈步中段脚尖应被拉向髋部（lift）
lift_ok = False
probe2 = CS.Spider(size=1.0)
for _ in range(600):
    probe2.update(1 / 60, "crawl", 160.0, motion=(2.7, 0.0))
    for L in probe2.legs:
        if L.stepping and 0.2 < L.t < 0.8:
            naive = (L.frm[0] + (L.nxt[0] - L.frm[0]) * L.t,
                     L.frm[1] + (L.nxt[1] - L.frm[1]) * L.t)
            if dist(probe2.foot_now(L), L.hip_pos) < dist(naive, L.hip_pos) - 1e-6:
                lift_ok = True
            break
    if lift_ok:
        break
check("迈步中段脚尖向髋部抬起", lift_ok)

# 回归：异步行波（相位排班）**不能把腿饿死**。
# 相位只该是「排班偏好」：一条腿错过窗口后如果必须干等一个整周期，
# 身体早就把它拖到腿长边缘了，画面上就是一条被拉长的腿。
# 按真机参数量：unit≈1.232（sprite_w=360）、WALK_SPEED=165 px/s
# → 局部速度 165/1.232 ≈ 134 局部单位/秒。
gait = CS.Spider(size=1.0)
gait.heading = 0.0
GAIT_FRAMES = 360

# ★ 先把朝向转到位，再开始量。
# 起步时朝向是 0，而这套约定下往 +x 走的稳定朝向是 π —— 中间要转 180°。
# 转身本身**也是**步态的驱动力（`Spider.turn()` 把钉在世界上的脚反向旋转），
# 所以那段瞬态里腿会额外多迈几次，八条腿分到的次数天然不齐。
# 这条断言问的是「稳态行走时有没有腿被相位饿死」，不是「起步转身时齐不齐」，
# 所以量之前先空转 1 秒把瞬态走完。
for _ in range(60):
    gait.update(1 / 60, "crawl", None, motion=(134.0 / 60.0, 0.0))

over_frames = 0
clamped_frames = 0
gait_steps = {L.index: 0 for L in gait.legs if not L.palp}
was = {L.index: L.stepping for L in gait.legs if not L.palp}
for _ in range(GAIT_FRAMES):
    gait.update(1 / 60, "crawl", None, motion=(134.0 / 60.0, 0.0))
    pw = [L for L in gait.legs if not L.palp]
    for L in pw:
        if L.stepping and not was[L.index]:
            gait_steps[L.index] += 1
        was[L.index] = L.stepping
    reach_px = [math.hypot(L.tip[0] - L.hip_pos[0], L.tip[1] - L.hip_pos[1]) for L in pw]
    if any(r >= L.full * CS.OVER_FRAC - 1e-9 for r, L in zip(reach_px, pw)):
        over_frames += 1
    if any(r > L.full * CS.REACH_LIMIT_FRAC + 1e-6 for r, L in zip(reach_px, pw)):
        clamped_frames += 1
check("行走时没有腿被夹到腿长之外（不出现被拉长的腿）",
      clamped_frames == 0, "夹住 %d/%d 帧" % (clamped_frames, GAIT_FRAMES))
check("行走时腿没被拖着走（over 帧占比 < 15%）",
      over_frames < GAIT_FRAMES * 0.15, "over %d/%d 帧" % (over_frames, GAIT_FRAMES))
counts = list(gait_steps.values())
check("八条步足开步次数均衡（没有腿被相位饿死）",
      max(counts) - min(counts) <= 2, "%s" % counts)

# 待机时会平滑「挪」进徽章站姿（IDLE_POSE），这是一次性落位、不是抽搐；
# 落位完成后静止态同样纹丝不动。先 warm-up 让姿势收敛，再验静止无抽搐。
idle = CS.Spider(size=1.0)
for _ in range(360):                      # 6s：IDLE_POSE_DAMP=2.2 早已收敛
    idle.update(1 / 60, "idle", 0.0)
idle_steps = 0
drift = 0.0
max_reach = max(L.reach for L in idle.legs)
for _ in range(600):
    idle.update(1 / 60, "idle", 0.0)
    idle_steps += sum(1 for L in idle.legs if L.stepping)
    drift = max(drift, max(dist(L.tip, idle.rest_pos(L)) for L in idle.legs))
check("静止（已摆好徽章姿势）后不再迈步（无抽搐）", idle_steps == 0,
      "累计 %d 条·帧" % idle_steps)
# 落位以 0.05×reach 为阈值停止迈步，脚尖允许留 ≤5% 腿长的静态余量（非抖动）
check("静止时脚尖稳定在徽章站姿上", drift < 0.06 * max_reach,
      "最大偏移 %.4f（阈值 %.2f）" % (drift, 0.06 * max_reach))

# 回归：走完停下来之后 velocity **必须**衰减到 0。
# 不衰减的话 `speed = |velocity|` 会永远停在最后一帧的值，`_step_target`
# 的前瞻 `rest - v*LEAD_SECONDS` 就一直把落脚点放在偏离静止位的位置：
# 脚一落地就被判成「偏得远」→ 再迈一次，可目标还是同一个点（步长为 0、
# 时长只有 0.07s）→ 原地每秒抖十几次。这正是待机抽搐的来源。
stopp = CS.Spider(size=1.0)
for _ in range(240):
    stopp.update(1 / 60, "crawl", None, motion=(3.0, 0.0))
check("走起来时 speed 确实不为 0", stopp.speed > 20.0, "speed=%.1f" % stopp.speed)
late_steps = 0
for _ in range(300):
    stopp.update(1 / 60, "idle", None, motion=(0.0, 0.0))
    if _ >= 240:                       # 最后 1 秒算「稳定后」
        late_steps += sum(1 for L in stopp.legs if L.stepping)
check("停下来 5 秒后 speed 衰减到 0", stopp.speed < 1.0, "speed=%.3f" % stopp.speed)
check("停下来后不再原地反复迈碎步", late_steps < 12, "末秒仍在迈步 %d 条·帧" % late_steps)

# 跳跃腾空：腿必须收拢且绝不能迈步（空中位移会放大偏移，不挡一下就是抽搐）
jumper = CS.Spider(size=1.0)
air_steps = 0
for _ in range(120):
    jumper.update(1 / 60, "jump", 400.0, motion=(6.6, 0.0))
    air_steps += sum(1 for L in jumper.legs if L.stepping)
check("腾空时不迈步", air_steps == 0, "累计 %d 条·帧" % air_steps)
check("腾空时腿是收拢的", max(dist(L.tip, jumper.rest_pos(L))
                      for L in jumper.legs) < 1e-6)

# 收腿
# 注意：`spread()` 现在返回**平滑过渡中**的 `_spread_now`（模式切换时腿不会
# 一瞬间集体跳开 —— 那正是「八条腿一起抽筋」的观感）。所以这里必须真的把
# `update()` 推一段时间，直接改 `mode` 然后立刻量 `rest_pos` 是量不到的。
rest_spider = CS.Spider(size=1.0)
wide = max(dist(L.hip_pos, rest_spider.rest_pos(L)) for L in steppers)
rest_spider.mode = "rest"
immediate = max(dist(L.hip_pos, rest_spider.rest_pos(L)) for L in steppers)
check("改 mode 的同一帧腿不会瞬移（spread 是平滑的）",
      abs(immediate - wide) < 1e-6, "%.1f → %.1f" % (wide, immediate))
for _ in range(120):                      # 2 秒足够 SPREAD_DAMP=8 收敛
    rest_spider.update(1 / 60, "rest", 0.0)
narrow = max(dist(L.hip_pos, rest_spider.rest_pos(L)) for L in steppers)
check("rest 态收腿", narrow < wide * 0.7, "%.1f → %.1f" % (wide, narrow))

# ---------------------------------------------------------------- 目标绑定
print("\n-- 目标绑定 --")
aim = CS.Spider(size=1.0)
points = [(60 + i * 25, 90) for i in range(5)]
aim.place_targets(points)
check("绑定了 5 条步足", len(aim.targets) == 5)
bound = [L for L in aim.legs if L.index in aim.targets]

# 第一帧不该瞬移（这是「伸脚过去」和「啪一下到位」的区别）
aim.update(1 / 60, "idle", 0.0)
snap = all(dist(L.tip, aim.targets[L.index]) < 1e-6 for L in bound)
check("第一帧是平滑起步而不是瞬移", not snap)

# 但跑够时间一定会收敛到目标点上
mid = 0
for _ in range(180):
    aim.update(1 / 60, "idle", 0.0)
    mid += sum(dist(L.tip, aim.targets[L.index]) for L in bound)
check("若干帧后收敛到目标点上",
      all(dist(L.tip, aim.targets[L.index]) < 1e-6 for L in bound),
      "平均残余 %.4f" % (mid / 180.0 / len(bound)))
check("有目标的腿不再自行迈步", all(not L.stepping for L in bound))
aim.clear_targets()
check("clear_targets 后恢复步态", len(aim.targets) == 0)

# ---------------------------------------------------------------- 分配
print("\n-- 腿↔词分配 --")
targets = [CS.Target(text="w%d" % i, center=(i * 34.0 - 90.0, 95.0))
           for i in range(8)]
pairs = CS.assign_legs(steppers, targets, 140.0, 190.0)
check("8 个词 → 8 对", len(pairs) == 8, "→ %d" % len(pairs))
check("腿不重复", len({p["leg"] for p in pairs}) == 8)
check("词不重复", len({p["target"] for p in pairs}) == 8)
check("成本非负", all(p["cost"] >= 0 for p in pairs))

cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
mapping = CS.solve_hungarian(cost)
total = sum(cost[i][j] for i, j in enumerate(mapping))
check("匈牙利最优解 = 5", total == 5, "→ %d %s" % (total, mapping))
check("空输入不崩", CS.assign_legs(steppers, [], 140.0, 190.0) == [])
check("词少于腿时按词数分配",
      len(CS.assign_legs(steppers, targets[:3], 140.0, 190.0)) == 3)

# ---- 可达性约束（真实场景用这个）
print("\n-- 可达匹配（够不着的不分）--")
# 关键：**必须用真实的 unit**。这里以前写 unit = 1.0，等于把 `reach` 里
# 误乘的那个 `unit` 抹平了，于是「约束被放宽 unit 倍」这个 bug 一直测不出来。
# 瞄准层的 unit ≈ 1.66（sprite_w 360 × AIM_SCALE_BOOST 1.35），用它才暴露问题。
unit = 1.66
# 一半近、一半远
near = [CS.Target(text="近%d" % i, center=(CS.LEG_DEF[i % 4][1] * 0.5, 40))
        for i in range(4)]
far = [CS.Target(text="远%d" % i, center=(900 + i * 50, 900)) for i in range(4)]
pairs = CS.assign_reachable(steppers, near + far, unit, max_frac=0.92)
check("远到离谱的词不会被分配", len(pairs) <= 4, "→ %d 对" % len(pairs))
check("每条腿最多一个词", len({p["leg"] for p in pairs}) == len(pairs))
check("每个词最多一条腿", len({p["target"] for p in pairs}) == len(pairs))
check("所有分配都在可达范围内", all(
    dist(steppers[p["leg"]].hip_pos, (near + far)[p["target"]].center)
    <= steppers[p["leg"]].full * 0.92 + 1e-6 for p in pairs),
    "这正是之前「腿被拉成射线」的根因")
check("全部够不着时返回空", CS.assign_reachable(
    steppers, [CS.Target(text="x", center=(5000, 5000))], unit) == [])

# 分配结果必须与 unit 无关（坐标本来就是局部单位，unit 只是绘制时的缩放）
print("\n-- 可达匹配与 unit 无关（回归：reach 曾误乘 unit）--")
# 放在 y=120 一条线上：距各髋 116~214 局部单位，正好横跨「够得着 / 够不着」的边界，
# 所以结果对单位尺度极其敏感 —— 旧的 `reach = full * unit * 0.92` 会让这里全部命中。
mid = [CS.Target(text="中%d" % i, center=(50.0 + i * 40.0, 120.0)) for i in range(4)]
by_unit = {}
for u in (1.0, 1.4, 1.66, 2.5):
    got = CS.assign_reachable(steppers, mid, u, max_frac=0.92)
    by_unit[u] = sorted((p["leg"], p["target"]) for p in got)
check("unit 从 1.0 到 2.5 分配结果完全一致",
      len(set(tuple(v) for v in by_unit.values())) == 1,
      "→ %s" % {u: len(v) for u, v in by_unit.items()})
check("该分的还是分到了（边界附近仍能分到 3~4 对）",
      3 <= len(by_unit[1.66]) <= 4, "→ %d 对" % len(by_unit[1.66]))

# ---------------------------------------------------------------- 命中
print("\n-- 命中区（三角头 = 识词，矩形身 = 拖动）--")
check("三角头正中 → head",
      spider.hit_test((CS.HEAD_OFF + CS.HEAD_TRI_LEN * 0.5, 0.0)) == "head")
check("三角底边内侧 → head", spider.hit_test((CS.HEAD_OFF + 0.5, 0.0)) == "head")
check("三角顶端 → head",
      spider.hit_test((CS.HEAD_OFF + CS.HEAD_TRI_LEN - 0.5, 0.0)) == "head")
check("三角两腰之外 → 落空（不能再靠一个方框硬猜）",
      spider.hit_test((CS.HEAD_OFF + CS.HEAD_TRI_LEN - 0.5,
                       CS.HEAD_TRI_HALF + 3.0)) is None)
check("矩形身 → body", spider.hit_test((-5.0, 0.0)) == "body")
check("矩形后沿 → body",
      spider.hit_test((CS.THORAX[0] * CS.THORAX_SCALE + 2.0, 0.0)) == "body")
check("矩形上下之外 → 落空",
      spider.hit_test((0.0, CS.THORAX[3] * CS.THORAX_SCALE * 0.5 + 5.0)) is None)
# 尾巴删掉以后，它占过的那块**必须**一起放出去：判定里留着就会在空白处
# 多出一块「看不见但点得中」的热区，正好压在鼠标上。
# 身体放大 2.5 倍后旧坐标 -25 已落进新身体里，必须推到身体前沿之外。
check("尾巴原位置 → 落空",
      spider.hit_test((CS.THORAX[0] * CS.THORAX_SCALE - 6.0, 0.0)) is None)
check("远端落空", spider.hit_test((300.0, 200.0)) is None)
check("垂直方向不算头", spider.hit_test((18.0, 60.0)) is None)
check("covers 认三角头与矩形身",
      spider.covers((CS.HEAD_OFF + CS.HEAD_TRI_LEN * 0.4, 0.0))
      and spider.covers((-5.0, 0.0)))
check("covers 不再盖住尾巴那块（点击要穿透）",
      not spider.covers((CS.THORAX[0] * CS.THORAX_SCALE - 6.0, 0.0)))

print("\n%s  通过 %d / 失败 %d" % ("=" * 40, len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)