# -*- coding: utf-8 -*-
"""「八腿踩词」的速度 + 常驻回归测试。

两件事，都是踩过坑之后才立的规矩：

**速度**
    · 错峰时序原来按 **写死的 0.016 秒**推进（`_elapsed += 0.016`）。掉一帧，
      整套错峰就慢半拍；机器越卡，腿伸得越慢 —— 恰恰是最该快的地方最慢。
      改成读真实 dt 之后，这里要断言「推了多久就走多久」。
    · 脚尖靠近目标的速率是 `TARGET_APPROACH_K`（指数平滑的 k）。指数平滑的
      尾巴极长，k=7 时要快 0.6 秒才把最后 5% 的距离走完，肉眼看着就是
      「伸过去了还在那儿蹭」。调到 16 之后整段踩词应该压进 1 秒内。

**常驻**
    · 覆盖层原来 `start(11000)`：11 秒后自己关。用户还没看完词就变回去了。
      现在改成**永不自动关闭**，由用户再点一下收。
    · 整层是鼠标穿透的，Qt 一个鼠标事件都收不到，所以「再点一下」是用
      `WH_MOUSE_LL` 钩子截的。这里盯住三件必须成立的事：
        1. 钩子装上了（装不上必须退回定时关闭，不能把用户钉死）；
        2. 点在自己的窗口（结果卡）上**不算**，否则点「加入单词本」就把蜘蛛收了；
        3. 收的时候**钩子必须卸掉** —— 钩子回调持有 `self`，漏卸一个，
           这个窗口就永远不被回收，多框几次就是一串幽灵钩子，每次点击都被吞。
    · 覆盖层挂了 `WA_DeleteOnClose`，关完 C++ 对象就没了。所以下一次
      `_launch_aim()` 清理上一个时**必须自己吞异常**，否则第二次框选永远起
      不来层（这个坑以前是存在的：第一次框完词、第二次只弹卡片不出腿）。

运行：  python test/test_aim_hold.py
"""

import ctypes
import math
import os
import random
import sys
from ctypes import wintypes

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtWidgets import QApplication                    # noqa: E402

import aim_overlay as AO                                      # noqa: E402
import crawler_spider as CS                                   # noqa: E402
import pet_window as PW                                       # noqa: E402
from pet_window import PetWindow                              # noqa: E402
from spider_painter import SpiderPainter                      # noqa: E402
# E7 要按 `word_id` 去重核对「每个目标最多完成一次」，状态常量和队列同一份来源
from scan_session import COMPLETED                            # noqa: E402

PASS, FAIL = [], []


class Clock:
    """假时钟。

    `pet_window` 和 `aim_overlay` 各 `import time` 一份，两边都要换掉，
    否则覆盖层的错峰时序走真挂钟，而这个测试要跑「模拟 60 秒」。
    """

    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def strftime(self, fmt):
        import time as real
        return real.strftime(fmt)


clock = Clock()
PW.time = clock
AO.time = clock


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if ok else "[fail]", name, detail))


class _FakeBook:
    """只为撑住结果卡片的构造。"""
    def __init__(self):
        self._s = set()

    def has(self, w):
        return w in self._s

    def add(self, item):
        self._s.add(item["lemma"])
        return True

    # 接手者加了「我的收藏 · 今日复习」统计行（launcher `_refresh_words`
    # 会调 book.stats() / book.review_queue()），桩补齐这两块。
    def stats(self):
        return {"total": len(self._s), "due": 0, "today": 0}

    def review_queue(self):
        return []


app = QApplication(sys.argv)
random.seed(7)

window = PetWindow(None, _FakeBook(), sprite_w=360.0)
window.resize(*window._window_size())
window._timer.stop()
window.start_capture = lambda *a, **k: None
window.bubble.hide_now()

STEP = 1.0 / 60.0


# 先让腿从「全缩在体心」散到静止位（新建的 Spider 腿尖是 (0,0)）
for _ in range(150):
    window.spider.update(STEP, motion=(0.0, 0.0))
window.spider.lean = 0.0
window.spider.body_sway = 0.0

# ---------------------------------------------------------------- 造 8 个假词
# 绕着体心摆一圈，半径压在腿长之内，保证八条腿都够得着。
CENTER = (window.center.x(), window.center.y())
RADIUS = 110.0
WORDS = []
for i in range(8):
    angle = i * (2.0 * math.pi / 8.0) + 0.2
    WORDS.append({
        "lemma": "word%d" % i,
        "surface": "word%d" % i,
        "meaning": "释义%d" % i,
        "level": "",
        "screen_pos": (CENTER[0] + RADIUS * math.cos(angle),
                       CENTER[1] + RADIUS * math.sin(angle)),
    })


def tip_error(leg_index, goal):
    """某条腿的脚尖离它那个词还有多远（局部单位）。"""
    leg = next(L for L in window.spider.legs if L.index == leg_index)
    return math.hypot(leg.tip[0] - goal[0], leg.tip[1] - goal[1])


# ================================================================ A 速度
# 整段从 `_elapsed == 0` 起算，错峰 + 逼近一起量 —— 分开量会漏掉
# 「最后那条腿下发完还得再飞一段」这段，那正是最慢的一条腿。
timed = AO.AimOverlay(window, WORDS, stagger=PW.LEG_STAGGER)
timed.start()
check("A0 八条腿都分到了词", len(timed._pairs) == 8,
      "→ %d 组" % len(timed._pairs))

early = 0
settle_t = None
frames_run = 0
for frame in range(600):                       # 最多跑 10 秒
    clock.t += STEP
    window._tick()
    timed._tick()
    frames_run = frame + 1
    if frame == 0:
        early = len(timed.spider.targets)
    if max(tip_error(idx, goal) for idx, goal, _, _ in timed._pairs) <= 2.0:
        # 2 局部单位 ≈ 2~3 屏幕像素，肉眼已经是「踩住了」
        settle_t = timed._elapsed
        break

check("A1 错峰时序按真实 dt 走（不是写死 16ms）",
      abs(timed._elapsed - frames_run * STEP) < 0.02,
      "_elapsed=%.4f vs 推了 %.4f" % (timed._elapsed, frames_run * STEP))
check("A2 起步时只伸出一部分（是错峰不是齐射）", 0 < early < 8,
      "第 1 帧只下发了 %d 条" % early)
check("A3 落位时八条腿的目标都已下发",
      len(timed.spider.targets) == len(timed._pairs),
      "%d/%d" % (len(timed.spider.targets), len(timed._pairs)))
check("A4 八个脚尖全部踩到词上（误差 ≤2 局部单位）", settle_t is not None,
      "%s" % ("用时 %.2fs" % settle_t if settle_t is not None else "10 秒未到位"))
check("A5 整段踩词 ≤1 秒（错峰 %.2fs + 逼近）"
      % (PW.LEG_STAGGER * 7,),
      settle_t is not None and settle_t <= 1.0,
      "实测 %.2fs" % settle_t if settle_t is not None else "-")

# A6 逼近速率确实比改之前快：指数平滑走到 eps 之内有解析解，直接对照
def approach_time(k: float, distance: float, eps: float = CS.TARGET_EPS) -> float:
    if distance <= eps:
        return 0.0
    return math.log(distance / eps) / k


D = 60.0
t_new = approach_time(CS.TARGET_APPROACH_K, D)
t_old = approach_time(7.0, D)
check("A6 逼近速率比改之前（k=7）明显快", t_new < t_old * 0.6,
      "k=%.1f → %.3fs，k=7.0 → %.3fs" % (CS.TARGET_APPROACH_K, t_new, t_old))

timed.close()
QApplication.processEvents()


# ================================================================ B 常驻
overlay = AO.AimOverlay(window, WORDS, stagger=PW.LEG_STAGGER)
overlay.start()
check("B1 全局鼠标钩子装上了", overlay._hook is not None,
      "hook=%s" % overlay._hook)
check("B2 钩子回调被自己持有（否则会被 GC，下次鼠标事件就崩）",
      overlay._hook_cb is not None,
      "cb=%s" % type(overlay._hook_cb).__name__)

# B3 关键：模拟 60 秒之后还必须开着（原来是 11 秒自己关）
for _ in range(int(60.0 / STEP)):
    clock.t += STEP
    window._tick()
    overlay._tick()
check("B3 过了 60 秒仍未自动关闭（原来是 11 秒就没了）",
      overlay.isVisible() and overlay._hook is not None,
      "visible=%s" % overlay.isVisible())

# B4 自己的窗口要能认出来
own = overlay._own_hwnds()
check("B4 认得出自己的顶层窗口（结果卡等）", len(own) >= 1,
      "%d 个可见顶层窗口" % len(own))


_LPARAM_HOLD = []


def fake_lparam(x: int, y: int):
    info = AO.MSLLHOOKSTRUCT()
    info.pt = wintypes.POINT(x, y)
    # ★ 必须自己留一份引用：`addressof` 只是把结构体的地址传出去，
    #   局部变量一返回就被回收，钩子回调读到的可能是已经被复用的内存
    #   （表现为「明明点的是体心，判出来却在屏幕角落」）。
    _LPARAM_HOLD.append(info)
    return ctypes.addressof(info)


# 「不吞」的分支会真的走到 `CallNextHookEx`，把这条**伪造**的鼠标消息
# 继续往系统钩子链里传 —— 那是把假数据喂给别人的钩子，测个试不该这么干。
# 这里把它换成桩：只关心我们的返回值，不关心系统链条。
_real_next = AO._USER32.CallNextHookEx
AO._USER32.CallNextHookEx = lambda *a: 0


# B5 点在自己窗口上 → 不收
real_hwnd_at = overlay._hwnd_at
overlay._hwnd_at = lambda lp: next(iter(own)) if own else 0
r = overlay._hook_proc(AO.HC_ACTION, AO.WM_LBUTTONDOWN, fake_lparam(10, 10))
check("B5 点在自己窗口上不算「点蜘蛛」",
      r == 0 or r != 1,
      "钩子返回值=%s（非 1 = 不吞这次点击）" % r)
check("B5b 覆盖层还开着", overlay.isVisible() and not overlay._dismissing)
overlay._hwnd_at = real_hwnd_at

# B6 点在**屏幕空白处** → 既不收起、也不吞（2026-10-19 用户定的语义：
#    只有点蜘蛛的头/身子才回去；以前点哪儿都收，手一抖就白框一次）
overlay._hwnd_at = lambda lp: 0x1234        # 一个不属于我们的句柄
r = overlay._hook_proc(AO.HC_ACTION, AO.WM_LBUTTONDOWN, fake_lparam(10, 10))
check("B6 点屏幕空白处不收起、也不吞这一下", int(r) != 1 and not overlay._dismissing,
      "钩子返回值=%s · dismissing=%s" % (r, overlay._dismissing))
check("B6b 覆盖层仍然开着", overlay.isVisible())
overlay._hwnd_at = real_hwnd_at

# B7 点在蜘蛛**身体**上 → 收起（用户指定的唯一出口）
_bx, _by = overlay._body_px
r = overlay._hook_proc(AO.HC_ACTION, AO.WM_LBUTTONDOWN,
                       fake_lparam(int(_bx + overlay._offset.x()),
                                   int(_by + overlay._offset.y())))
check("B7 点蜘蛛身体才收起，并吞掉这一下", int(r) == 1 and overlay._dismissing,
      "钩子返回值=%s · dismissing=%s" % (r, overlay._dismissing))

# B7 回到事件循环之后真的收了：钩子卸掉、腿的目标清空、本体窗口回来
QApplication.processEvents()
check("B7 收到点击后覆盖层关闭", not overlay.isVisible(),
      "visible=%s" % overlay.isVisible())
check("B8 钩子已卸载（回调持有 self，漏卸就永远回收不掉）",
      overlay._hook is None and overlay._hook_cb is None)
check("B9 腿的目标已清空（恢复原来形态）",
      not window.spider.targets, "%r" % window.spider.targets)
check("B10 本体窗口重新显示", window.isVisible(), "visible=%s" % window.isVisible())


# ================================================================ C 二次框选
# 覆盖层挂了 WA_DeleteOnClose，B7 关完 C++ 对象就没了。
# 下一次 _launch_aim() 清理它时必须自己吞异常，否则第二次框选起不来层。
try:
    window._launch_aim(WORDS, WORDS)
    second = window._dialogs.get("aim")
    ok = second is not None and len(second._pairs) == 8
    check("C1 第二次框选照样起得住瞄准层", ok,
          "pairs=%s" % (len(second._pairs) if second is not None else "无"))
    check("C2 第二次也装上了钩子",
          second is not None and second._hook is not None)
    if second is not None:
        second.close()
        QApplication.processEvents()
except Exception as error:                                    # noqa: BLE001
    check("C1 第二次框选照样起得住瞄准层", False, "抛异常: %r" % (error,))
    check("C2 第二次也装上了钩子", False, "")
finally:
    AO._USER32.CallNextHookEx = _real_next


# ================================================================ D 远词可达
# 需求：「蜘蛛离远的单词是够不到的」。
#
# 场景构造成最锋利的样子：每个词放在**原腿长的 1.35 倍**处。
# 老代码的可达上限是 `full × 0.92`，1.35 > 0.92 → 一个都够不着、一条腿都
# 派不出去（只剩词框）；拉长 1.6 倍后上限变成 `full × 1.472` → 八个词全进圈。
probe = CS.Spider(size=1.0)
for _ in range(120):
    probe.update(STEP, motion=(0.0, 0.0))

steppers = [L for L in probe.legs if not L.palp]
palps = [L for L in probe.legs if L.palp]
full_before = [L.full for L in steppers]
palp_before = [L.full for L in palps]


def ring_targets(spider, factor: float):
    """每个词都放在「该腿髋部方向 × 腿长 × factor」处（局部坐标）。"""
    out = []
    for leg in spider.legs:
        if leg.palp:
            continue
        hx, hy = leg.hip_pos
        span = math.hypot(hx, hy) or 1.0
        radius = leg.full * factor
        out.append(CS.Target(text="t%d" % leg.index,
                             center=(hx + hx / span * radius,
                                     hy + hy / span * radius)))
    return out


far_words = ring_targets(probe, 1.35)
before = len(CS.assign_reachable(steppers, far_words))
check("D1 老腿长下这些远词一条腿都派不到（所以画面上只剩词框）",
      before == 0, "→ 派到 %d 条腿" % before)

probe.set_leg_stretch(AO.AIM_LEG_STRETCH_MAX)
after = len(CS.assign_reachable(steppers, far_words))
check("D2 拉长 %.1f 倍后八个远词全部可达" % AO.AIM_LEG_STRETCH_MAX,
      after == len(steppers), "→ %d/%d" % (after, len(steppers)))

ratios = [L.full / base for L, base in zip(steppers, full_before)]
check("D3 八条步足按倍率等比变长",
      all(abs(r - AO.AIM_LEG_STRETCH_MAX) < 1e-6 for r in ratios),
      "→ 倍率 %s" % sorted({round(r, 4) for r in ratios}))

check("D4 触须不跟着变长（头部观感不变）",
      all(abs(L.full - base) < 1e-9 for L, base in zip(palps, palp_before)),
      "→ 触须 %s" % [round(L.full, 1) for L in palps])

# 静止位半径由 `leg.reach` 算，必须一起变大 —— 只改画面不改几何的话，
# 脚会钉在原处、腿被拉直，正是「八条腿汇成射线」那个老毛病。
# 注意：待机徽章姿势（IDLE_POSE）会把静止位再乘一个伸展系数，这里先把它
# 归零，只看「最朴素 reach×REST_K」这条链，否则姿势系数会污染断言。
probe._idle_pose_t = 0.0
probe._spread_now = 1.0
check("D5 静止位半径跟着变大（不是只把画面拉长）",
      all(abs(math.hypot(probe.rest_pos(L)[0] - L.hip_pos[0],
                         probe.rest_pos(L)[1] - L.hip_pos[1]) - L.reach * CS.REST_K)
          < 1e-6 for L in steppers),
      "→ 与 reach×REST_K 一致")

# 反复进出不能漂移：`set_leg_stretch` 存的是构造期的原始值，不是连着乘
for _ in range(3):
    probe.set_leg_stretch(1.0)
    probe.set_leg_stretch(AO.AIM_LEG_STRETCH_MAX)
probe.set_leg_stretch(1.0)
check("D6 反复进出三趟，腿长精确回到原值（不累积漂移）",
      all(abs(L.full - base) < 1e-9 for L, base in zip(steppers, full_before)),
      "→ 最大偏差 %.2e"
      % max(abs(L.full - base) for L, base in zip(steppers, full_before)))

# 真机链路：瞄准层和本体**共用同一个 Spider 实例**，所以进场拉长、退场必须还原。
#
# 这一段最要紧的是「**按需**」两个字：拉多少不是常量，是按「最远的那个词」
# 算出来的 —— 词就在嘴边时硬拉到上限，只会把腿拉成射线。
near = AO.AimOverlay(window, WORDS, stagger=PW.LEG_STAGGER)   # RADIUS=110，够得着
check("D7 词就在嘴边时不拉长（够用即可，不无谓拉成射线）",
      abs(near.leg_stretch - 1.0) < 1e-9, "→ ×%.3f" % near.leg_stretch)
near.close()
QApplication.processEvents()

# 把词挪到 400px 外（老腿长够不着），这次必须拉长
FAR_WORDS = []
for i in range(8):
    angle = i * (2.0 * math.pi / 8.0) + 0.2
    FAR_WORDS.append({
        "lemma": "far%d" % i,
        "surface": "far%d" % i,
        "meaning": "释义%d" % i,
        "level": "",
        "screen_pos": (CENTER[0] + 400.0 * math.cos(angle),
                       CENTER[1] + 400.0 * math.sin(angle)),
    })
far = AO.AimOverlay(window, FAR_WORDS, stagger=PW.LEG_STAGGER)
check("D8 词在 400px 外时按需拉长，且不超过上限",
      1.0 < far.leg_stretch <= AO.AIM_LEG_STRETCH_MAX + 1e-9,
      "→ ×%.3f（上限 ×%.1f）" % (far.leg_stretch, AO.AIM_LEG_STRETCH_MAX))
check("D9 拉长之后八条腿都派到了词（自适应倍率确实够用）",
      len(far._pairs) == 8, "→ %d 条腿" % len(far._pairs))
far.close()
QApplication.processEvents()
check("D10 收起来之后腿长复原（不会留在桌宠身上）",
      abs(window.spider.leg_stretch - 1.0) < 1e-9,
      "→ ×%.3f" % window.spider.leg_stretch)

# 像素可达半径：这是「够不够得着」在屏幕上的真实数字
unit_aim = SpiderPainter.unit_for_width(window.sprite_w * AO.AIM_SCALE_BOOST)
reach_before = unit_aim * full_before[3] * 0.92
probe.set_leg_stretch(AO.AIM_LEG_STRETCH_MAX)
reach_now = unit_aim * [L for L in probe.legs if not L.palp][3].full * 0.92
check("D11 后足像素可达半径上限 ≥480px（改之前只有 %.0fpx）" % reach_before,
      reach_now >= 480.0, "→ %.0f px" % reach_now)


# ================================================================ E 连续扫词（§6）
# 「八条腿」是**同时**踩词的并行度，不是能处理多少个词的上限。
# 这一段用 24 个词（3 批）盯住四件必须成立的事：
#   1. 一个都不丢：24 个词全部进队列、全部有框；
#   2. 腿不会贪：一批最多派 8 条，剩下的一批一批往前走；
#   3. 换批是真的发生（`batches >= 3`），不是靠「够不着」蒙过去的；
#   4. 暂停 / 继续 / 关闭都有对应的状态，不是一句「出错了」。
GRID = []
for r in range(4):
    for c in range(6):
        GRID.append({
            "lemma": "g%02d" % (r * 6 + c),
            "surface": "g%02d" % (r * 6 + c),
            "meaning": "释义%d" % (r * 6 + c),
            "level": "",
            # 6 列 × 4 行，横向 ±175px、纵向 ±90px：一批 8 个词够得着的范围
            "screen_pos": (CENTER[0] - 175.0 + c * 70.0,
                           CENTER[1] - 90.0 + r * 60.0),
        })

queue = AO.AimOverlay(window, GRID, stagger=PW.LEG_STAGGER)
queue.start()
check("E1 24 个词全部进队列（没有 `[:8]` 截断）",
      len(queue.session.targets) == 24, "→ %d 个" % len(queue.session.targets))
check("E2 第一批只派 8 条腿（八腿=并行度）",
      len(queue._pairs) <= 8 and len(queue._pairs) >= 4,
      "→ 首批 %d 条腿" % len(queue._pairs))
check("E3 开批这一帧还没有框（框要等腿踩上去才亮，不是整批齐刷刷弹出）",
      len(queue._guides) == 0, "→ %d 只" % len(queue._guides))

# 跑 1.5 秒（一批落位大约 0.7s）：中途必须看到「只亮了 1~7 只」的帧，
# 这就是「踩到一个词才出现一个框」的证据。
partial = 0
for _ in range(90):
    clock.t += STEP
    window._tick()
    queue._tick()
    count = len(queue._guides)
    if 0 < count < 8:
        partial = max(partial, count)
check("E3b 框是一个一个亮的（中途出现过 1~7 只，不是 8 只一起蹦出来）",
      partial > 0, "→ 中途最多只亮了 %d 只" % partial)
check("E3c 亮框数和已完成的词数对得上（每踩住一个才多一只框）",
      len(queue._guides) == queue.session.stats()["completed"],
      "→ 框 %d 只 · 已完成 %d 个" % (len(queue._guides),
                                  queue.session.stats()["completed"]))
check("E4 词↔腿的配对按 word_id 记账，不是按文本",
      all(len(p) == 4 and p[3] for p in queue._pairs),
      "→ %s" % (queue._pairs[:1],))

for _ in range(2400):                            # 最多模拟 40 秒
    clock.t += STEP
    window._tick()
    queue._tick()
    if queue.session.stats()["completed"] == 24:
        break

stats = queue.session.stats()
check("E5 24 个词全部踩完（真的一批批走完，不是丢掉）",
      stats["completed"] == 24,
      "→ 完成 %d · 待办 %d · 在途 %d · 失败 %d"
      % (stats["completed"], stats["pending"], stats["active"], stats["failed"]))
check("E6 分批真的发生（24 个词至少 3 批）",
      stats["batches"] >= 3, "→ %d 批" % stats["batches"])
check("E7 每个目标最多完成一次（不重复计数）",
      len({t.word_id for t in queue.session.by_state(COMPLETED)}) ==
      stats["completed"], "→ %d" % stats["completed"])
check("E8 全程没有静默丢词：完成+失败+跳过 == 总数",
      stats["completed"] + stats["failed"] + stats["skipped"] == 24,
      "→ %d + %d + %d" % (stats["completed"], stats["failed"], stats["skipped"]))
check("E9 踩完之后框还在（换批不抹掉旧词）",
      len(queue._guides) == 24, "→ %d 只" % len(queue._guides))
check("E10 提示条说出「已全部踩完」",
      "已全部踩完" in queue._hint_text(), "→ %s" % queue._hint_text())

# 暂停 / 继续：用第二个队列测（第一个已经跑完，没有「在途」可暂停）
part = AO.AimOverlay(window, GRID, stagger=PW.LEG_STAGGER)
part.start()
for _ in range(60):
    clock.t += STEP
    window._tick()
    part._tick()
part.session.pause()
done_paused = part.session.stats()["completed"]
batch_paused = part.session.stats()["batches"]
for _ in range(240):
    clock.t += STEP
    window._tick()
    part._tick()
check("E11 暂停后不再推进（批次数冻住）",
      part.session.stats()["batches"] == batch_paused,
      "→ %d 批（暂停时 %d）" % (part.session.stats()["batches"], batch_paused))
check("E12 提示条写明「已暂停」", "已暂停" in part._hint_text(),
      "→ %s" % part._hint_text())
part.session.resume()
for _ in range(1200):
    clock.t += STEP
    window._tick()
    part._tick()
check("E13 继续之后能走到完", part.session.stats()["completed"] == 24,
      "→ 完成 %d" % part.session.stats()["completed"])

# 点蜘蛛身体 = 暂停/继续（覆盖层鼠标穿透，这是唯一还够得着的入口）
_center_screen = (queue._body_px[0] + queue._offset.x(),
                  queue._body_px[1] + queue._offset.y())
check("E14 落在蜘蛛身上的点被认成「暂停/继续」而不是「收起」",
      queue._over_spider(_center_screen), "→ 体心 %s" % (
          tuple(round(v) for v in _center_screen),))
check("E15 远处的点不算在蜘蛛身上（点了不收起）",
      not queue._over_spider((_center_screen[0] + 900.0, _center_screen[1] + 400.0)))
_before = queue.session.paused
queue._toggle_pause()
check("E16 点一下确实切换了暂停状态", queue.session.paused != _before,
      "→ paused=%s" % queue.session.paused)
queue._toggle_pause()

# 中途关掉 = 取消：还没轮到的词记成 skipped，日志和统计都对得上
mid = AO.AimOverlay(window, GRID, stagger=PW.LEG_STAGGER)
mid.start()
for _ in range(90):
    clock.t += STEP
    window._tick()
    mid._tick()
mid.close()
QApplication.processEvents()
mstats = mid.session.stats()
check("E17 中途关闭会取消队列（没有词悬在途）",
      mstats["active"] == 0 and mstats["pending"] == 0,
      "→ 在途 %d · 待办 %d" % (mstats["active"], mstats["pending"]))
check("E18 没轮到的词算 skipped，不是凭空消失",
      mstats["completed"] + mstats["skipped"] + mstats["failed"] == 24,
      "→ %d + %d + %d" % (mstats["completed"], mstats["skipped"], mstats["failed"]))
check("E19 关闭时腿长归位（桌宠不会顶着一副长腿继续爬）",
      abs(window.spider.leg_stretch - 1.0) < 1e-9,
      "→ ×%.3f" % window.spider.leg_stretch)


# ================================================================ F 原地定位（≤8）
# 用户口径（2026-10-19）：**八个词以内**，蜘蛛选好位置后**身子一步不走**，
# 八条腿拉长去踩，踩完一直保持这个姿势，直到点蜘蛛的头或身子才回去。
#
# 改之前两处都不成立：
#   · `_needed_stretch` 对「身体会走过去」的那类词直接 `continue`，
#     于是宽跨度选区里所有远词的贡献都被跳过，腿长停在 ×1.0，
#     八条腿只派得出 4 条 —— 表现就是「腿根本没伸长」；
#   · 没派到腿的词既不会落位、也不会被结掉，0.9s 后 `stall` 把整批打回
#     待办重开、腿重新派一次，三轮之后判 failed —— 表现就是「没保持住」。
WIDE = []
for _i in range(8):
    _col, _row = _i % 4, _i // 4
    WIDE.append({
        "lemma": "wide%d" % _i,
        "surface": "wide%d" % _i,
        "meaning": "释义%d" % _i,
        "level": "",
        # 横向 ±700px、纵向 ±140px：远超 ×1.6 腿长的可达半径
        "screen_pos": (CENTER[0] - 700.0 + _col * 466.0,
                       CENTER[1] - 140.0 + _row * 280.0),
    })

hold = AO.AimOverlay(window, WIDE, stagger=PW.LEG_STAGGER)
window._dialogs["aim"] = hold          # 本体 `_busy()` 靠它保持全速（别被空闲降频冻住）
hold.start()
_body0 = (float(window.center.x()), float(window.center.y()))
check("F1 八词以内走原地定位（不规划身体路径）",
      hold._compact_scan and not hold._route)
check("F2 宽跨度下腿真的拉长了（超过走位模式的 ×%.1f 上限）"
      % AO.AIM_LEG_STRETCH_MAX,
      hold.leg_stretch > AO.AIM_LEG_STRETCH_MAX,
      "→ ×%.2f" % hold.leg_stretch)
check("F3 八个词全部派到了腿（不再只派得出 4 条）",
      len(hold._pairs) == 8, "→ %d 条腿" % len(hold._pairs))

for _ in range(int(4.0 / STEP)):
    clock.t += STEP
    window._tick()
    hold._tick()
hst = hold.session.stats()
check("F4 身体一步都没走（原地定位）",
      math.hypot(window.center.x() - _body0[0],
                 window.center.y() - _body0[1]) < 1e-6,
      "→ 位移 %.2fpx" % math.hypot(window.center.x() - _body0[0],
                                   window.center.y() - _body0[1]))
check("F5 只开过一批（没有 stall 反复重开、腿也没有重新派过）",
      hst["batches"] == 1, "→ %d 批" % hst["batches"])
check("F6 八个词全部被腿踩到（pegged）",
      hst["pegged"] == 8, "→ 踩到 %d · 失败 %d" % (hst["pegged"], hst["failed"]))
check("F7 状态保持：4 秒后每条腿还踩在自己的词上",
      all(leg.target_now is not None for leg in window.spider.legs if not leg.palp))

window._dialogs.pop("aim", None)
hold.close()
QApplication.processEvents()
check("F8 收起之后腿长还原", abs(window.spider.leg_stretch - 1.0) < 1e-9,
      "→ ×%.3f" % window.spider.leg_stretch)

# F9 真够不着的词（3000px 外）：只亮框、不失败、不进重试循环 —— 「保持」的
#    另一面是「不许因为够不着就反复重开批次」。
EDGE = [dict(w) for w in WIDE[:7]]
EDGE.append({"lemma": "edge", "surface": "edge", "meaning": "释义",
             "level": "", "screen_pos": (CENTER[0] + 3000.0, CENTER[1])})
edge = AO.AimOverlay(window, EDGE, stagger=PW.LEG_STAGGER)
window._dialogs["aim"] = edge
edge.start()
for _ in range(int(3.0 / STEP)):
    clock.t += STEP
    window._tick()
    edge._tick()
est = edge.session.stats()
check("F9 够不着的词只亮框（不判失败、不重开批次）",
      est["box_only"] >= 1 and est["failed"] == 0 and est["batches"] == 1,
      "→ 只亮框 %d · 失败 %d · %d 批" % (est["box_only"], est["failed"],
                                        est["batches"]))
window._dialogs.pop("aim", None)
edge.close()
QApplication.processEvents()

print()
print("=" * 70)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    for name in FAIL:
        print("  FAILED: %s" % name)
    sys.exit(1)
