# -*- coding: utf-8 -*-
"""跳跃状态机 + 身体形变的回归（任务书 §9.2A/C，§9.3「断言那一半」）。

六组，逐条对上任务书：

    A. 跳跃是**独立状态机**（§9.2C.1-5）：准备 → 空中 → 落地 → 恢复，
       起点/终点/时长可测，蓄力段 root 不许动，空中是抛物线。
    B. 三段形变的时序与幅值：蓄力压到底、起跳撤目标、落地满冲量、
       之后自己回弹；走停给一次轻冲量。
    C. 腾空不继续地面迈步（§9.2C.3）、腿不拉长、骨长不变、
       脚尖不越可达（§9.3 的几何断言）。
    D. 唯一权威（§9.2A）：取消之后没有第二个主人还在写 `center`。
    E. 渲染层（§9.2B/C）：身体下沉 + 屏幕竖直压扁，而**脚尖像素一个都不动**。
    F. 起伏的来源是「此刻有几条腿抬着」（不是独立振荡器）：站定零起伏、
       走路有轻起伏且夹在上限内、停下平滑归零。

时间全部走假时钟（`FakeClock`）：`_tick` 一帧 = 1/60 秒，可复现。
截图留给 `tools/locomotion_sheet.py`（§9.3 要求两者都要）。

运行：  python test/test_jump_motion.py
"""

from __future__ import annotations

import math
import os
import sys
import time as real_time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QPoint                          # noqa: E402
from PySide6.QtGui import QImage, QPainter, Qt             # noqa: E402
from PySide6.QtWidgets import QApplication                # noqa: E402

import crawler_spider as CS                                # noqa: E402
import locomotion                                          # noqa: E402
from spider_painter import SpiderPainter, SpiderState      # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-56s %s" % ("ok" if ok else "FAIL", name, detail))


FRAME = 1.0 / 60.0


class FakeClock:
    """把 `pet_window` 的时钟接管过来：`_tick` 变成确定性的逐帧推进。

    为什么要接管：`_tick` 用 `time.monotonic()` 求 dt，真实时钟下每帧 dt 都不
    一样，「蓄力段有几帧」「落地冲量多大」就没法断言。从接管那一刻的真实读数
    起步（否则 `_last` 是旧值、第一帧会拿到负 dt），之后只有 `tick()` 显式
    advance 才前进 —— 生产代码一行都不用改。
    """

    def __init__(self):
        self.t = real_time.monotonic()

    def monotonic(self):
        return self.t

    def perf_counter(self):
        return self.t

    def time(self):
        return self.t


CLOCK = FakeClock()

import pet_window as PW                                    # noqa: E402
PW.time = CLOCK            # 只换这个模块里的名字，别的一概不碰


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
pet._movement_choice = None          # 从「没决定过」开始，滞回不带历史

screen = pet._screen_rect()
home = QPoint(int(screen.center().x()), int(screen.center().y()))
threshold = locomotion.walk_jump_threshold(pet.spider, pet.unit)
spider = pet.spider


def tick(frames: int = 1, until=None) -> int:
    """按固定步长跑 `_tick`；`until()` 为真就提前停，返回实际帧数。"""
    for i in range(frames):
        CLOCK.t += FRAME
        pet._tick()
        if until is not None and until():
            return i + 1
    return frames


def park(center=None) -> None:
    """摆回起点并**结束上一段位移**（`_travel` 不清会劫持下一段的起点）。"""
    pet._travel = None
    pet._travel_done = None
    pet.effect = None
    pet.center = QPoint(center or home)
    tick(1)                       # 让 `_tick` 的守卫顺手把控制器停掉
    pet._movement_choice = None
    tick(90)                      # 站姿混到位、腿钉住、上一段形变衰减完


def run_segment(seconds: float, hook) -> None:
    """跑完当前这一段位移，每帧回调 `hook(帧号)`；`_travel` 清空就停。"""
    for i in range(int(60 * seconds) + 5):
        CLOCK.t += FRAME
        pet._tick()
        hook(i)
        if pet._travel is None:
            return


print("\n[A] 跳跃是独立状态机：准备 → 空中 → 落地 → 恢复（§9.2C）")

park()
target = QPoint(int(home.x() + threshold * 3.0), home.y())
pet.travel_to(target)
check("启动后由控制器接管（模式不是 idle，快照也在）",
      pet._travel is not None and pet.mover.moving,
      "→ %s" % pet.mover.movement_mode)

jump_dur = pet._travel[3]
dest = pet._travel[1]          # 夹到屏幕内之后的**真正**终点（不是我想去的那个点）
start_root = pet.mover.root
seen, roots, air = [], [], []


def watch_a(i):
    mode = pet.mover.movement_mode
    if not seen or seen[-1] != mode:
        seen.append(mode)
    roots.append((pet.mover.root, mode))
    if mode == locomotion.JUMP_AIRBORNE:
        air.append(pet.mover.root)


run_segment(jump_dur + 2.0, watch_a)
# 起点朝向可能就对着目标（ORIENT 有 0.55rad 容差），那时这一段没有转身档
if seen and seen[0] == locomotion.ORIENT:
    seen = seen[1:]
check("四段依次各出现一次：%s" % seen,
      seen == [locomotion.JUMP_PREPARE, locomotion.JUMP_AIRBORNE,
               locomotion.LAND, locomotion.IDLE])
check("落点精确等于目标（`_clamp_point` 之后的那一个，误差 ≤1px）",
      math.hypot(pet.center.x() - dest.x(), pet.center.y() - dest.y()) <= 1.0,
      "→ 差 %.2fpx" % math.hypot(pet.center.x() - dest.x(),
                                 pet.center.y() - dest.y()))
check("起点也可测：空中第一帧就站在位移的起点上（±1px）",
      bool(air) and math.hypot(air[0][0] - start_root[0],
                               air[0][1] - start_root[1]) <= 1.0,
      "→ 差 %.2fpx" % (math.hypot(air[0][0] - start_root[0],
                                  air[0][1] - start_root[1]) if air else -1))
check("段结束后快照与控制器一起归位（§9.2A 不留第二个主人）",
      pet._travel is None and pet.mover.movement_mode == locomotion.IDLE
      and pet.mover.arrived)

prepare_roots = {r for r, m in roots if m == locomotion.JUMP_PREPARE}
check("蓄力段 root 不许动（起跳前不能先漂出去）",
      len(prepare_roots) <= 1, "→ %d 帧里 root 有 %d 个值"
      % (len([1 for _, m in roots if m == locomotion.JUMP_PREPARE]),
         len(prepare_roots)))

if len(air) > 4:
    (x0, y0), (x1, y1) = air[0], air[-1]
    mid = air[len(air) // 2]
    check("空中是抛物线：中点比直线高 ≥8px（§9.2C.2）",
          (y0 + y1) / 2.0 - mid[1] >= 8.0,
          "→ 抬起 %.1fpx" % ((y0 + y1) / 2.0 - mid[1]))
    check("空中水平持续推进（不是瞬移到终点）", x1 - x0 > 1.0,
          "→ %.1f → %.1f" % (x0, x1))
    monotone = all(b[0] >= a[0] - 0.51 for a, b in zip(air, air[1:]))
    check("空中不回头（前向单调）", monotone)
else:
    check("空中至少 5 帧可采样", False, "→ 只有 %d 帧" % len(air))

check("快照时长就是空中那一段的时长（远跳比基准 0.78s 长）",
      jump_dur > PW.JUMP_DURATION, "→ %.2fs" % jump_dur)

print("\n[B] 三段形变的时序与幅值（§9.2C.1/3/4）")

park()
pet.travel_to(QPoint(int(home.x() + threshold * 3.0), home.y()))
jump_dur = pet._travel[3]
crouch_peak, land_impulse, air_targets = 0.0, 0.0, []
prev = None
# 冲量是 `mover.step()` 给的，而 `_tick` 同一帧后面就 `spider.update()` 衰减了
# 一格 —— 钩子看到的是「已经过了一帧」的值，所以比对的是衰减后的那一个
# （顺带也证明了「真的每帧在自己回弹」）。
ONE_FRAME = math.exp(-CS.COMPRESSION_RATE * FRAME)


def watch_b(i):
    global crouch_peak, land_impulse, prev
    mode = pet.mover.movement_mode
    if mode == locomotion.JUMP_PREPARE:
        crouch_peak = max(crouch_peak, spider.crouch)
    if mode == locomotion.JUMP_AIRBORNE and prev != mode:
        air_targets.append(spider.crouch_target)
    if mode == locomotion.LAND and prev == locomotion.JUMP_AIRBORNE:
        land_impulse = spider.landing_compression
    prev = mode


run_segment(jump_dur + 2.0, watch_b)
check("蓄力把身体压到底（crouch ≥ 0.8，0.16s 的准备段配得上 CROUCH_RATE）",
      crouch_peak >= 0.8, "→ 峰值 %.2f" % crouch_peak)
check("起跳那一刻撤掉蓄力目标（弹开，抬升交给抛物线）",
      air_targets and air_targets[0] == 0.0, "→ %s" % air_targets[:1])
check("落地瞬间给满冲量（一帧衰减后仍是 1×e^-k·dt 那一档）",
      locomotion.JUMP_LAND_IMPULSE * ONE_FRAME * 0.99 <= land_impulse
      <= locomotion.JUMP_LAND_IMPULSE,
      "→ 实测 %.3f / 期望 %.3f" % (land_impulse,
                                   locomotion.JUMP_LAND_IMPULSE * ONE_FRAME))

tick(150, until=lambda: spider.landing_compression < 0.02)
rising, last = [], 1.0
spider.landing_compression = last
for _ in range(150):
    CLOCK.t += FRAME
    pet._tick()
    v = spider.landing_compression
    rising.append(v > last + 1e-9)
    last = v
check("落地后自己回弹：单调衰减且 ≤2.5s 归零（没人再清它）",
      not any(rising) and spider.landing_compression < 0.02,
      "→ 反向 %d 帧 / 用了 %d 帧" % (sum(rising), len(rising)))

park()
pet.travel_to(QPoint(int(home.x() + threshold * 0.35), home.y()))
walk_dur = pet._travel[3]
stop_impulse = 0.0


def watch_b2(i):
    global stop_impulse
    stop_impulse = max(stop_impulse, spider.landing_compression)


run_segment(walk_dur + 1.0, watch_b2)
check("走停也给一次「收住」（轻冲量：够 WALK_STOP，明显轻于跳跃落地）",
      locomotion.WALK_STOP_IMPULSE * ONE_FRAME * 0.99 <= stop_impulse
      < locomotion.JUMP_LAND_IMPULSE * ONE_FRAME * 0.8,
      "→ %.3f（跳的是 %.3f）" % (stop_impulse,
                                 locomotion.JUMP_LAND_IMPULSE * ONE_FRAME))

print("\n[C] 腾空不迈步 / 形变不动脚 / 骨长与可达（§9.2C.3、§9.3）")

park()
pet.travel_to(QPoint(int(home.x() + threshold * 3.0), home.y()))
jump_dur = pet._travel[3]
new_steps, spread_min, stretch = 0, 9.9, set()
prev_stepping = set()


def watch_c(i):
    global new_steps, spread_min, prev_stepping
    mode = pet.mover.movement_mode
    if mode in (locomotion.JUMP_PREPARE, locomotion.JUMP_AIRBORNE):
        now = {id(L) for L in spider.legs if L.stepping}
        new_steps += len(now - prev_stepping)
        prev_stepping = now
        spread_min = min(spread_min, spider._spread_now)
    else:
        prev_stepping = {id(L) for L in spider.legs if L.stepping}
    stretch.add(round(spider.leg_stretch, 9))


run_segment(jump_dur + 2.0, watch_c)
tick(60)                      # 落地后腿要重新撑开：给 spread 缓动一点时间（1 秒）
check("空中不出现「新的迈步」（地面步态逻辑暂停）",
      new_steps == 0, "→ %d 次" % new_steps)
check("空中腿收拢到 jump 档（spread 明显小于 1）",
      spread_min < CS.MODE_SPREAD["jump"] + 0.3, "→ 最小 %.2f" % spread_min)
check("落地后腿重新撑开（spread 回到 1 附近）",
      spider._spread_now > 0.9, "→ %.2f" % spider._spread_now)
check("整段跳跃不改腿长倍率（远跳不许把腿拉长，§9.2C 最后一句）",
      stretch == {1.0}, "→ %s" % sorted(stretch))

park()
pet.travel_to(QPoint(int(home.x() - threshold * 3.0), home.y()))
jump_dur = pet._travel[3]
worst_ratio, bone_drift = 0.0, 0.0


l1l2 = {L.index: (L.l1, L.l2) for L in spider.legs}


def watch_c4(i):
    global worst_ratio, bone_drift
    for L in spider.legs:
        if L.palp:
            continue
        reach = math.hypot(L.tip[0] - L.hip_pos[0], L.tip[1] - L.hip_pos[1])
        worst_ratio = max(worst_ratio, reach / max(L.full, 1e-6))
        bone_drift = max(bone_drift, abs(L.l1 - l1l2[L.index][0]),
                         abs(L.l2 - l1l2[L.index][1]))


run_segment(jump_dur + 2.0, watch_c4)
check("脚尖从不越过腿长（含落地那一下）",
      worst_ratio <= 0.995, "→ 最大 %.4f×full" % worst_ratio)
check("骨长一帧都没变（形变只挪身体，不伸腿）",
      bone_drift == 0.0, "→ 漂移 %.1e" % bone_drift)

print("\n[D] 唯一权威：谁能写 center（§9.2A）")

park()
pet.travel_to(QPoint(int(home.x() + threshold * 3.0), home.y()))
tick(6)
check("位移进行中：控制器确实在逐帧推进",
      pet.mover.moving and pet._travel is not None
      and pet.mover.movement_mode != locomotion.IDLE,
      "→ %s" % pet.mover.movement_mode)
root_before = pet.mover.root
pet._travel = None                    # 别的入口（拖动 / 覆盖层接手）的取消方式
tick(3)
check("取消之后控制器不再推进（下一帧守卫就把它停了）",
      pet.mover.movement_mode == locomotion.IDLE
      and pet.mover.root == root_before,
      "→ root %s → %s" % (tuple(round(v, 1) for v in root_before),
                          tuple(round(v, 1) for v in pet.mover.root)))
check("取消后 root 对回窗口真实位置（下次不会从「记忆里」起跳）",
      math.hypot(pet.mover.root[0] - pet.center.x(),
                 pet.mover.root[1] - pet.center.y()) <= 1.0,
      "→ root %s / center %s" % (tuple(round(v, 1) for v in pet.mover.root),
                                 (pet.center.x(), pet.center.y())))
check("滞回历史只有一份（`_movement_choice` 就是控制器里那个对象）",
      pet._movement_choice is pet.mover.choice, "→ %s" % (pet._movement_choice,))

print("\n[E] 渲染层：身体下沉 + 屏幕竖直压扁，脚尖像素一个都不动")

UNIT = 1.232
SIZE = 420
CENTER = (SIZE / 2.0, SIZE / 2.0)


def render(model, painter, retract=0.0, heading=0.0):
    image = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    qp = QPainter(image)
    painter.paint(qp, model, SpiderState(heading=heading, dim=1.0,
                                         leg_retract=retract),
                  unit=UNIT, origin_px=CENTER)
    qp.end()
    return image


def bbox(image, cutoff=40):
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > cutoff:
                if x < x0:
                    x0 = x
                if y < y0:
                    y0 = y
                if x > x1:
                    x1 = x
                if y > y1:
                    y1 = y
    return None if x1 < 0 else (x0, y0, x1, y1)


def ink_patch(image, cx, cy, radius=2, cutoff=40):
    """脚尖那一小块：墨迹质心的 y + 像素数（盯住「脚尖这一点有没有挪」）。"""
    num = den = count = 0
    for y in range(int(cy - radius), int(cy + radius) + 1):
        for x in range(int(cx - radius), int(cx + radius) + 1):
            if not (0 <= x < image.width() and 0 <= y < image.height()):
                continue
            a = image.pixelColor(x, y).alpha()
            if a > cutoff:
                num += a * y
                den += a
                count += 1
    return (num / den if den else None, count)


def settled_model():
    m = CS.Spider(size=1.0)
    for _ in range(240):
        m.update(FRAME, "idle", None, motion=(0.0, 0.0))
    m.origin_px = CENTER
    return m


painter = SpiderPainter()
RETRACTED = 1.0          # 只画身体：腿全收，bbox 量的就是头胸那一块

# 下面三组要「一次只量一件事」，所以临时把另一个通道关掉。
# 原值存下来，末尾统一还原 —— 测试跑完别的产品代码不能带着被改过的常量继续走。
ORIG = (CS.CROUCH_SINK, CS.LAND_SINK, CS.SQUASH_SY, CS.SQUASH_SX)


def restore_constants():
    CS.CROUCH_SINK, CS.LAND_SINK, CS.SQUASH_SY, CS.SQUASH_SX = ORIG

# —— 下沉：单独量（临时把压扁关掉，否则顶边「下移 + 变矮」两笔混在一起）——
model = settled_model()
CS.SQUASH_SY, CS.SQUASH_SX = 0.0, 0.0
flat = bbox(render(model, painter, retract=RETRACTED))
model.crouch = 1.0
crouched = bbox(render(model, painter, retract=RETRACTED))
model.crouch = 0.0
model.landing_compression = 1.0
landed = bbox(render(model, painter, retract=RETRACTED))
model.landing_compression = 0.0
restore_constants()

sink_c = CS.CROUCH_SINK * UNIT
sink_l = CS.LAND_SINK * UNIT
check("蓄力那一下身体往影子里沉 ≈CS.CROUCH_SINK×unit（%.1fpx）" % sink_c,
      abs((crouched[1] - flat[1]) - sink_c) <= 1.5,
      "→ 实测 %.1fpx" % (crouched[1] - flat[1]))
check("落地那一下比蓄力更沉（LAND_SINK > CROUCH_SINK 要看得出来）",
      (landed[1] - flat[1]) > (crouched[1] - flat[1])
      and abs((landed[1] - flat[1]) - sink_l) <= 1.5,
      "→ %.1fpx vs %.1fpx" % (landed[1] - flat[1], crouched[1] - flat[1]))

# —— 压扁：单独量（临时把下沉关掉，只看形状变化）——
CS.CROUCH_SINK = CS.LAND_SINK = 0.0
model = settled_model()
f2 = bbox(render(model, painter, retract=RETRACTED))
model.landing_compression = 1.0
s2 = bbox(render(model, painter, retract=RETRACTED))
model.landing_compression = 0.0
restore_constants()
h0 = f2[3] - f2[1]
h1 = s2[3] - s2[1]
w0, w1 = f2[2] - f2[0], s2[2] - s2[0]
check("压扁按 SQUASH_SY 生效：竖直变矮（≥一半的量）",
      h0 - h1 >= CS.SQUASH_SY * h0 * 0.5, "→ 高 %d → %d" % (h0, h1))
check("压扁同时水平鼓出（SQUASH_SX）", w1 >= w0 + 1, "→ 宽 %d → %d" % (w0, w1))

model = settled_model()
model.crouch = 1.0
model.landing_compression = 1.0
both = bbox(render(model, painter, retract=RETRACTED))
model.crouch = model.landing_compression = 0.0
check("形变幅度是「克制」的量级：身体最多沉 1/4 个身位",
      (both[1] - f2[1]) <= 0.25 * h0,
      "→ 沉 %.1fpx / 身位高 %dpx" % (both[1] - f2[1], h0))

# —— 朝向 180°（头朝左）：压扁必须还在屏幕竖直轴上 ——
left = settled_model()
CS.SQUASH_SY, CS.SQUASH_SX = 0.0, 0.0
g0 = bbox(render(left, painter, retract=RETRACTED, heading=math.pi))
left.crouch = 1.0
g1 = bbox(render(left, painter, retract=RETRACTED, heading=math.pi))
restore_constants()
check("头朝左时身体也是「往下沉」而不是「往右沉」（sink 走屏幕竖直轴）",
      g1 is not None and abs((g1[1] - g0[1]) - sink_c) <= 1.5
      and abs((g1[0] - g0[0])) <= 1,
      "→ 下移 %.1fpx，横移 %.1fpx" % (g1[1] - g0[1], g1[0] - g0[0]))

# —— 脚尖不许被身体带着走（这是 §9.2B「站定阶段脚不动」的绘制层版本）——
model = settled_model()
img_flat = render(model, painter)
model.crouch = 1.0
model.landing_compression = 1.0
img_sunk = render(model, painter)
model.crouch = model.landing_compression = 0.0
moved, gone = [], []
for L in [x for x in model.legs if not x.palp]:
    fx, fy = painter.to_screen(L.tip)
    c0, n0 = ink_patch(img_flat, fx, fy)
    c1, n1 = ink_patch(img_sunk, fx, fy)
    if n0 < 3 or n1 < 3:
        gone.append((L.slot, n0, n1))
    elif abs(c0 - c1) > 1.2:
        moved.append((L.slot, round(c0 - c1, 2)))
check("八只脚尖那一小块墨迹原地不动（身体下沉/压扁都不带走脚）",
      not gone and not moved, "→ 丢了 %s / 漂了 %s" % (gone, moved))

print("\n[F] 起伏挂在「抬着的腿」上，不是独立振荡器（§9.2B 最后一句）")

walker = CS.Spider(size=1.0)
# 新建的腿还缩在体心，要空跑够帧数才会各自走到静止位并钉住（那期间确实在迈步，
# 起伏不是零也没关系 —— 这里要断言的是「真的站定了之后」不许有起伏）。
for _ in range(300):
    walker.update(FRAME, "idle", None, motion=(0.0, 0.0))
bob_still = walker.body_bob
check("（前提）站定 = 八条腿都不在迈、腿也全伸着",
      not any(L.stepping for L in walker.legs) and not walker.folding(),
      "→ bob %.4f" % bob_still)
peak, stepping_frames = 0.0, 0
for _ in range(900):
    walker.update(FRAME, "crawl", None, motion=(2.2, 0.0))
    peak = max(peak, walker.body_bob)
    stepping_frames += 1 if any(L.stepping for L in walker.legs) else 0
check("站定时身体一点起伏都没有（待机不许抽搐，用户明确要求）",
      abs(bob_still) < 1e-9, "→ %.4f" % bob_still)
check("走路有轻起伏，且夹在 BOB_MAX×体型之内（不踩高跷）",
      0.05 < peak <= CS.BOB_MAX * walker.scale + 1e-6,
      "→ 峰值 %.2f / 上限 %.2f 局部单位（≈%.1fpx）"
      % (peak, CS.BOB_MAX * walker.scale, CS.BOB_MAX * walker.scale * UNIT))
check("起伏与迈步同拍（大部分帧都有腿正抬着）",
      stepping_frames > 200, "→ %d/900 帧" % stepping_frames)
for _ in range(300):
    walker.update(FRAME, "idle", None, motion=(0.0, 0.0))
check("停下后起伏平滑归零", walker.body_bob < 0.02, "→ %.4f" % walker.body_bob)

pet.close()

print("\n" + "=" * 78)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
for name in FAIL:
    print("  FAILED:", name)
raise SystemExit(1 if FAIL else 0)
