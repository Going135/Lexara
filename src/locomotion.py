# -*- coding: utf-8 -*-
"""移动决策：什么时候「走过去」、什么时候「跳过去」。

任务书 §4 要求把这条决策从散落的魔法数字变成一个**集中、随体型缩放、
且不抖**的策略。以前它是 `pet_window.JUMP_THRESHOLD = 260.0` 一个写死的像素数：
桌宠缩到 50% 时 260px 已经是三个身位，蜘蛛还在走；放到 200% 时 260px 不到
一个腿展，抬腿没迈完就该跳了 —— 同一个数字在两种尺寸下说的是两件事。

这里的尺度用的是**腿展**（`2 × 最长步足 full × unit`，也就是八条腿能撑出的
那个圆的直径）。它天然跟着体型走，而且正是「一步能不能迈到」的物理量：
比腿展小 → 走几步就到；比腿展大得多 → 走要几十步，看着就累，跳。

    · `walk_jump_threshold()`  —— 阈值（逻辑像素），随 sprite 尺寸缩放并夹在合理区间
    · `decide_movement()`      —— 带滞回的走/跳判定（纯函数，好测）

★ 坐标系只有一处：`pet_window` 传进来的距离是**屏幕逻辑像素**
  （`self.center` 与目标点都是逻辑像素），阈值也从逻辑像素的 `unit` 算出来。
  物理像素（DPR）不参与这里的任何比较。
"""

from __future__ import annotations

import math

#: 两种移动方式
WALK = "walk"
JUMP = "jump"

#: 阈值 = 腿展 × 这个比例。**待调参数**，不是物理常量：
#: 0.48 是从旧行为（`JUMP_THRESHOLD = 260px` @ sprite_w=360，腿展 540px）
#: 反推出来的起点，这样改了口径也不改变真机上已经调好的手感。
SPAN_FRACTION = 0.48

#: 上下限（逻辑像素）：小尺寸时别让「挪一个指节」也触发跳跃，
#: 大尺寸时也别让蜘蛛贴着屏幕对角慢爬。
MIN_THRESHOLD_PX = 110.0
MAX_THRESHOLD_PX = 520.0

#: 滞回带宽（占阈值的比例）。落进 `[阈值×(1-带宽), 阈值]` 这段区间时
#: **保持上一次的决定**，于是目标在阈值附近来回抖几个像素不会走/跳反复切换。
HYSTERESIS = 0.15


def leg_span_px(spider, unit: float) -> float:
    """腿展（逻辑像素）= 2 × 最长步足的 `full` × `unit`。

    只看步足（`palp=False`）：触须短，拿它当尺度会让阈值莫名偏小。
    """
    fulls = [leg.full for leg in spider.legs if not leg.palp]
    return 2.0 * max(fulls) * max(unit, 1e-6)


def walk_jump_threshold(spider, unit: float) -> float:
    """这一档体型下，「多远以内走、多远以上跳」的分界（逻辑像素）。"""
    value = leg_span_px(spider, unit) * SPAN_FRACTION
    return min(MAX_THRESHOLD_PX, max(MIN_THRESHOLD_PX, value))


def decide_movement(distance_px: float, threshold_px: float,
                    previous: str = None) -> str:
    """走还是跳。

    `previous` 是上一次的决定（`None` 当作「没有历史」，直接按阈值判）。
    滞回的形状：
        distance > threshold            → jump（上穿）
        distance < threshold×(1-带宽)   → walk（下穿）
        中间那段                         → 维持 `previous`
    """
    if previous not in (WALK, JUMP):
        return JUMP if distance_px > threshold_px else WALK
    if distance_px > threshold_px:
        return JUMP
    if distance_px < threshold_px * (1.0 - HYSTERESIS):
        return WALK
    return previous


def jump_duration(distance_px: float, threshold_px: float,
                  base_seconds: float) -> float:
    """跳跃时长：远一点的跳慢一点，不然 3 个腿展和 1 个腿展都是 0.78s，
    远的那一下像被瞬移。倍数夹在 [0.85, 1.6]，再远也不至于拖成慢动作。
    """
    ratio = distance_px / max(threshold_px, 1e-6)
    factor = min(1.6, max(0.85, 0.72 + 0.28 * ratio))
    return base_seconds * factor


# ------------------------------------------------------------------ 移动控制器
#
# 任务书 §8.1 的口径：「同一时刻不能只更新腿的 target 而不更新 body root；
# 需要一个明确的移动控制器/状态机负责 root position、heading、速度和当前
# waypoint」。下面这个类就是那一个所有者。
#
# ★ 它**不持有** heading。朝向的唯一真源是 `Spider.heading`：模型在
#   `update()` 里把 heading 朝**世界位移方向**插值（§4 修好的那条），
#   控制器只负责给出位移。两处各转一次 heading 的话，头就不领路了。
#   同理，根节点位置写回 `PetWindow.center`（桌宠窗口的权威位置），
#   控制器里那份只是这一帧的积分状态。

#: 走路速度（逻辑像素/秒）。`crawler_spider` 的步态注释里量过：
#: 真机 unit≈1.232 时 165px/s ≈ 134 局部单位/秒，正好是「一步一步迈」的档位。
WALK_SPEED_PX = 240.0

#: 跳跃的基准时长与弧线高度（逻辑像素）。和桌宠在桌面上跳的是同一套手感。
JUMP_BASE_SECONDS = 0.55
JUMP_ARC_PX = 110.0

#: 起跳前的下蹲/转身时间，和落地后的稳定时间。
JUMP_PREPARE_SECONDS = 0.16
JUMP_LAND_SECONDS = 0.14

#: 离停靠点多近算「到了」。8px ≈ 一个腿描边的宽度，再小就是逐帧抖。
ARRIVE_PX = 8.0

#: 身体该停在离词框多远的位置（占「腿能够到的半径」的比例）。
#:
#: 太近（<0.4）身体直接压在词上，框被盖住、OCR 原词看不见；
#: 太远（>0.85）腿又得拉成射线，回到重做之前的老毛病。
#: 0.62 实测是「腿自然伸出去一小截就踩得住」的那一档。
APPROACH_STANDOFF_FRAC = 0.62

#: 停靠点至少要比身体的半径远这么多，否则「身体盖住单词」。
#: 身体半径 = 头胸前沿到体心的距离 × `body_scale`，再留 12px 余量给词框。
APPROACH_BODY_CLEARANCE_PX = 12.0

#: 起跳前允许的最大转向误差（弧度）。小于它就直接起跳，
#: 不然每次跳跃前都要原地扭一下，看着像抽搐。
ORIENT_TOLERANCE = 0.55

#: 原地转身的角速度（弧度/秒）。比 `spin` 彩蛋慢一档：这是干活时的转身。
ORIENT_RATE = 4.2

#: 跳跃三段的**形变冲量**（任务书 §9.2C）。控制器只管「什么时候给多少」，
#: 怎么缓动、怎么画归 `crawler_spider` / `spider_painter`：
#:   · 蓄力：`crouch_target = JUMP_CROUCH`（身体压低、腿弯一点，不改 root）；
#:   · 腾空：`crouch_target = 0`（身体跟着 root 的抛物线抬起，腿收拢）；
#:   · 落地：`landing_compression = JUMP_LAND_IMPULSE`（一次冲量，模型自己衰减回去）。
#: 走路停下也给一点（`WALK_STOP_IMPULSE`）：八条腿同时收住的那一下有落地感，
#: 不是「走得好好的突然静止」。
JUMP_CROUCH = 1.0
JUMP_LAND_IMPULSE = 1.0
WALK_STOP_IMPULSE = 0.45

IDLE = "idle"
ORIENT = "orient"
JUMP_PREPARE = "jump_prepare"
JUMP_AIRBORNE = "jump_airborne"
LAND = "land"
DONE = "done"


def approach_point(word_px, root_px, reach_px, body_radius_px=0.0) -> tuple:
    """词的**停靠点**：身体要走到哪儿，才既够得着这个词、又不压在它上面。

    `reach_px` 传的是「腿**拉到上限**时的可达半径」，于是这一个参数管两个口子：

        词在 `reach_px` 之内  → 原地不动，让腿去够（§6 的老行为，一次就踩完）
        词在 `reach_px` 之外  → 走过去，站到离词 `reach_px × 0.62` 的地方

    两个方向都不能省：
      · 少了「够得着就别动」—— 8 个词挤在一小片区域时身体也会挨个挪过去，
        本来 1 秒踩完的一次框选被拖成 8 站，慢而且没有信息量；
      · 少了 `× 0.62` 这一档 —— 走过去之后腿还得再拉满一次才能踩到，
        画面就是「人到了、腿还伸得笔直」，正是要修的那个观感。

    停靠点还不得比 `身体半径 + 余量` 更近，否则身体直接压在词框上。
    """
    wx, wy = float(word_px[0]), float(word_px[1])
    rx, ry = float(root_px[0]), float(root_px[1])
    dx, dy = wx - rx, wy - ry
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return (wx, wy)
    if dist <= reach_px:
        return (rx, ry)
    stand_off = max(reach_px * APPROACH_STANDOFF_FRAC,
                    body_radius_px + APPROACH_BODY_CLEARANCE_PX)
    k = (dist - stand_off) / dist
    return (rx + dx * k, ry + dy * k)


def plan_route(items, origin, reach_of, body_radius_of=lambda: 0.0,
               threshold_of=None) -> list:
    """把「一串词」规划成「身体要依次踩到的停靠点」。

    `items` 必须已经是**规划好的顺序**（`ScanSession.order`：行优先阅读顺序，
    行内最近邻）。这里不再自己排序 —— 两处排序迟早会给出两条路径，
    而队列按 A 顺序换批、身体按 B 顺序走，看起来就是「蜘蛛乱跑」。

    每个停靠点带上该词、词的屏幕坐标、身体的停靠坐标、距离与走/跳决定。
    距离是**相对上一个停靠点**算的（身体真的会走到那儿），不是相对原点。

    函数是纯的：给定同样的输入必给同样的路径，测试可以直接复现。
    """
    route = []
    cursor = (float(origin[0]), float(origin[1]))
    previous_choice = None
    for item in items:
        pos = item.get("screen_pos") if isinstance(item, dict) \
            else getattr(item, "screen_pos", None)
        if not pos:
            continue
        word_px = (float(pos[0]), float(pos[1]))
        approach = approach_point(word_px, cursor, reach_of(word_px),
                                  body_radius_of())
        distance = math.hypot(approach[0] - cursor[0], approach[1] - cursor[1])
        threshold = threshold_of(word_px) if threshold_of else None
        mode = (decide_movement(distance, threshold, previous_choice)
                if threshold else WALK)
        previous_choice = mode
        route.append({"word_id": (item.get("word_id") if isinstance(item, dict)
                                  else getattr(item, "word_id", "")) or "",
                      "word_px": word_px,
                      "approach_px": approach,
                      "distance_px": distance,
                      "mode": mode})
        cursor = approach
    return route


class MotionController:
    """身体的所有者：`root_position` / `velocity` / `movement_mode`
    / `current_waypoint` 都只在这里推进（任务书 §9.2A）。

    两个宿主共用这一类，谁在管身体谁就**独占**它：
      · `PetWindow`：桌宠在桌面上的走位（`travel_to`）；
      · `AimOverlay`：踩词时沿路径挨个走停靠点（§8）。
    覆盖层开着的时候桌宠那台控制器必须是取消状态（`aim_overlay` 接手时会
    `pet._travel = None`），否则两台各写一次 `center`，身体一边跳一边被拽回去。

    用法（每帧一次）：

        mover.set_waypoint(stop_point, threshold_px)   # 换批/换词时（这里才定走或跳）
        mover.step(dt)                                 # 每帧一次

    `step()` 把新位置写进 `self.root`，并通过 `on_root` 回调交给宿主
    （桌宠写回 `PetWindow.center`）。位移同时喂给 `Spider.update(motion=)`，
    脚先钉住、偏移过阈值再迈步 —— 步态引擎不需要知道这里有条路径。

    跳跃的三段形变（蓄力 / 弹开 / 落地压缩，§9.2C）由控制器**发给模型**：
    它只负责「什么时候给多少」，缓动速率和怎么画归 `crawler_spider` 与
    `spider_painter`。没 `bind_spider()` 时这些写入自动跳过，控制器照样能跑
    （纯几何测试就是这么用的）。
    """

    def __init__(self, root, on_root=None, speed: float = WALK_SPEED_PX,
                 jump_seconds: float = JUMP_BASE_SECONDS,
                 arc: float = JUMP_ARC_PX):
        self.root = (float(root[0]), float(root[1]))
        self.velocity = (0.0, 0.0)
        self.movement_mode = IDLE
        self.current_waypoint = None
        self.on_root = on_root
        self.speed = float(speed)
        self.jump_seconds = float(jump_seconds)
        self.arc = float(arc)
        self._phase_t = 0.0
        self._jump_from = self.root
        self._jump_to = self.root
        self._jump_dur = self.jump_seconds
        #: 上一段的走/跳决定（滞回要用它）。**公开**：桌宠的 `travel_to` 和测试
        #: 都要读同一个数，别再存第二份历史 —— 两处历史一旦分叉，
        #: 「这一段到底该走还是该跳」就没有答案了。
        self.choice = None
        self._threshold = None
        #: 转身要改模型朝向，所以身体得知道「谁的 heading」。没绑就不能 orient。
        self.spider = None

    # ---------------------------------------------------------------- 查询
    @property
    def arrived(self) -> bool:
        """身体已经站在当前停靠点上（或根本没有要去的点）。"""
        if self.current_waypoint is None:
            return True
        return self.movement_mode in (IDLE, DONE)

    @property
    def moving(self) -> bool:
        return self.movement_mode in (ORIENT, WALK,
                                      JUMP_PREPARE, JUMP_AIRBORNE, LAND)

    def distance_to_waypoint(self) -> float:
        if self.current_waypoint is None:
            return 0.0
        return math.hypot(self.current_waypoint[0] - self.root[0],
                          self.current_waypoint[1] - self.root[1])

    # ---------------------------------------------------------------- 指令
    def sync_root(self, point) -> None:
        """把控制器的积分状态对到「身体现在真的在哪儿」。

        唯一权威是宿主的位置（桌宠的 `PetWindow.center`），控制器里那份只是
        逐帧积分。所以**任何**绕过控制器的移动之后都要同步一次：
        用户把蜘蛛拖走了、覆盖层接手了、或者上一段被取消了 —— 不同步的话
        下一段会从「记忆里的那个位置」起跳，画面就是原地一闪又回到正轨。
        """
        self.root = (float(point[0]), float(point[1]))
        self.velocity = (0.0, 0.0)

    def set_waypoint(self, point, threshold_px: float = None,
                     force: str = None) -> None:
        """下一个要去的地方。`None` = 没有任务，回到待机。

        `force`（`locomotion.JUMP` / `locomotion.WALK`）用来让调用方**替它决定**：
        桌宠的 `travel_to(force_jump=True/False)` 有显式入口，而那一趟的时长
        也要按同一次决定算 —— 两处各判一次就会出现「按跳的时长走路」。
        给了 `force` 就不走滞回（这一趟本来就是指定的）。
        """
        if point is None:
            self.current_waypoint = None
            self.movement_mode = IDLE
            self.velocity = (0.0, 0.0)
            self._crouch_off()
            return
        self.current_waypoint = (float(point[0]), float(point[1]))
        self._phase_t = 0.0
        self._threshold = threshold_px
        distance = self.distance_to_waypoint()
        if force in (WALK, JUMP):
            self.choice = force
        elif threshold_px:
            self.choice = decide_movement(distance, threshold_px, self.choice)
        else:
            self.choice = WALK
        if self.choice == JUMP:
            self.movement_mode = ORIENT
        else:
            self.movement_mode = WALK

    def cancel(self) -> None:
        self.set_waypoint(None)

    # ---------------------------------------------------------------- 形变
    def _crouch_off(self) -> None:
        """把「蓄力压低」收掉（没绑模型就什么都不做）。"""
        spider = self.spider
        if spider is not None:
            spider.crouch_target = 0.0

    def _impulse(self, amount: float) -> None:
        """给一次落地压缩冲量（模型自己衰减，见 `crawler_spider.update`）。"""
        spider = self.spider
        if spider is not None and amount > spider.landing_compression:
            spider.landing_compression = amount

    # ---------------------------------------------------------------- 推进
    def _face(self, point, dt: float) -> float:
        """原地把头转向目标，返回「还差多少弧度」。

        只改 `Spider.heading`，不动 `velocity`：模型里 heading 会朝速度方向
        插值，所以腾空/走路时这个函数不再被调用，两者不会打架
        （和 `spin` 彩蛋同一套做法：自转期间速度必须清零）。
        """
        spider = self.spider
        want = math.atan2(point[1] - self.root[1], point[0] - self.root[0])
        have = spider.heading
        delta = (want - have + math.pi) % (2.0 * math.pi) - math.pi
        if abs(delta) <= ORIENT_TOLERANCE:
            return 0.0
        step = math.copysign(min(abs(delta), ORIENT_RATE * dt), delta)
        spider.heading += step
        spider.velocity = (0.0, 0.0)
        return abs(delta)

    def bind_spider(self, spider) -> None:
        """转身要改模型的朝向，所以得知道模型是谁（不传就没法 orient）。"""
        self.spider = spider

    def step(self, dt: float) -> tuple:
        """推进一帧，返回这一帧身体位移 `(dx, dy)`（逻辑像素）。

        ★ 这里**没有** threshold 参数：走还是跳在 `set_waypoint()` 那一刻就定了
        （路径也是那时一次性规划的，§8.5）。逐帧重判会让身体在同一段路上
        一会儿要跳一会儿要走 —— 滞回只救得了「距离抖几个像素」，救不了改主意。
        """
        mode = self.movement_mode
        self.velocity = (0.0, 0.0)
        if self.current_waypoint is None or mode in (IDLE, DONE):
            return self.velocity

        if mode == ORIENT:
            if self.spider is None or self._face(self.current_waypoint, dt) == 0.0:
                self._begin_jump()
            return self.velocity

        if mode == WALK:
            dx = dy = 0.0
            remaining = self.distance_to_waypoint()
            if remaining <= ARRIVE_PX:
                self._land(walk=True)
                return self.velocity
            step = min(self.speed * dt, remaining)
            ux, uy = ((self.current_waypoint[0] - self.root[0]) / remaining,
                      (self.current_waypoint[1] - self.root[1]) / remaining)
            dx, dy = ux * step, uy * step
            self._move_to((self.root[0] + dx, self.root[1] + dy))
            self.velocity = (dx / max(dt, 1e-6), dy / max(dt, 1e-6))
            if self.distance_to_waypoint() <= ARRIVE_PX:
                self._land(walk=True)
            return (dx, dy)

        if mode == JUMP_PREPARE:
            # 蓄力：身体压低、腿弯一点（root 还不动 —— 起跳前不能先漂出去）。
            # 放在这里而不是 `_begin_jump` 里：目标要**持续**给，模型才是往它缓动，
            # 只给一次的话 0.16 秒内压不满，看着像没蓄力。
            spider = self.spider
            if spider is not None:
                spider.crouch_target = JUMP_CROUCH
            self._phase_t += dt
            if self._phase_t >= JUMP_PREPARE_SECONDS:
                self.movement_mode = JUMP_AIRBORNE
                self._phase_t = 0.0
                self._crouch_off()          # 弹开：压低立刻归零，抛物线接管
            return self.velocity

        if mode == JUMP_AIRBORNE:
            self._phase_t += dt
            u = min(1.0, self._phase_t / max(self._jump_dur, 1e-3))
            ease = 1.0 - (1.0 - u) ** 2
            x = self._jump_from[0] + (self._jump_to[0] - self._jump_from[0]) * ease
            y = self._jump_from[1] + (self._jump_to[1] - self._jump_from[1]) * ease
            y -= self.arc * 4.0 * u * (1.0 - u)      # 抛物线抬起
            self._move_to((x, y))
            if u >= 1.0:
                self.movement_mode = LAND
                self._phase_t = 0.0
                self._move_to(self._jump_to)         # 落点必须精确
                self._impulse(JUMP_LAND_IMPULSE)     # 落地那一下压到底，再回弹
            return self.velocity

        if mode == LAND:
            self._phase_t += dt
            if self._phase_t >= JUMP_LAND_SECONDS:
                self._land()
            return self.velocity

        return self.velocity

    # ---------------------------------------------------------------- 内部
    def _begin_jump(self) -> None:
        self._jump_from = self.root
        self._jump_to = self.current_waypoint
        distance = math.hypot(self._jump_to[0] - self._jump_from[0],
                             self._jump_to[1] - self._jump_from[1])
        threshold = self._threshold
        if not threshold and self.spider is not None:
            # 没传阈值就用体型自己算一遍：`unit=1.0` 时阈值是「局部单位」，
            # 而这里的距离是屏幕像素，所以调用方**必须**传自己的阈值，
            # 这条兜底只是保证「绝不会拿到 None 去算时长」。
            threshold = walk_jump_threshold(self.spider, 1.0)
        self._jump_dur = jump_duration(distance, threshold or MIN_THRESHOLD_PX,
                                      self.jump_seconds)
        self.movement_mode = JUMP_PREPARE
        self._phase_t = 0.0

    def _move_to(self, point) -> None:
        self.root = (float(point[0]), float(point[1]))
        if self.on_root is not None:
            self.on_root(self.root)

    def _land(self, walk: bool = False) -> None:
        """这一段结束：停稳、回到 IDLE，并把落点写准。

        `walk=True` 时给一次**较轻**的落地冲量（§9.2B「运动停止后平滑稳定」）：
        走停了也该有个「收住」的动作，而不是走得好好的突然静止。
        跳的落地冲量在 `JUMP_AIRBORNE` 那一支给（那里才是重落地）。
        """
        self.movement_mode = IDLE
        self.velocity = (0.0, 0.0)
        if walk:
            self._impulse(WALK_STOP_IMPULSE)
        if self.current_waypoint is not None:
            self._move_to(self.current_waypoint)

