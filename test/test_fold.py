# -*- coding: utf-8 -*-
"""折叠（无腿模式）回归测试。

需求：右键菜单新增「折叠」，点了播收腿动画、然后**以无腿模式待机**；
再点「展开」把腿伸回去。

这块最容易做错的地方是**把折叠当成一次性动画**：

    · `play("hide_legs")` 播完，`self.effect` 一清空，`_current_tf()` 就变回
      `IDENT`（retract=0）—— 腿会当场弹回来，「无腿模式」根本待不住。
    · 而且 `_tick` 里原来还有一段「收完自动接 `show_legs`」，那是 L/H 彩蛋的
      「收 → 伸」演示，和「折叠」语义正好相反：菜单一点，0.55 秒后腿自己回来了。
    · 腿收起来了，`covers()` 却只认几何、不知道腿没了 —— 不掐掉 `leg_pad`，
      原地就会留下一圈「看不见但点得住」的空地（和删掉的那条尾巴同一个坑）。

所以这里盯住四组不变式：
    A. **待得住**：动画结束后 retract 停在 1.0，且长时间不回落。
    B. **画得出就对**：折叠后腿的位置真的没有像素，本体还在。
    C. **看不见就点不中**：腿的落点全部穿透，身体照旧点得中；展开后恢复。
    D. **切换不跳**：收/伸过程逐帧连续，半路反向（收一半又点展开）也不跳。

运行：  python test/test_fold.py
"""

import math
import os
import random
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtCore import QPoint, QPointF                    # noqa: E402
from PySide6.QtGui import QImage, QPainter                    # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

import anim                                                   # noqa: E402
import crawler_spider as CS                                   # noqa: E402
import pet_window as PW                                       # noqa: E402
from pet_window import PetWindow                              # noqa: E402

PASS, FAIL = [], []


class Clock:
    """假时钟。主循环与形变进度都读挂钟，必须能一帧一帧地推。"""

    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def strftime(self, fmt):
        import time as real
        return real.strftime(fmt)


clock = Clock()
PW.time = clock


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if ok else "[fail]", name, detail))


app = QApplication(sys.argv)
random.seed(11)

window = PetWindow(None, None, sprite_w=360.0)
window.resize(*window._window_size())

STEP = 1.0 / 60.0
#: 主循环每帧最多允许的收腿深度变化（60fps 下 ease-in-out 的理论峰值约 0.05）
MAX_JUMP = 0.12


def settle() -> None:
    """清掉开局那个 `pop`，并把状态放回静止，作为每个用例的起点。"""
    window.effect = None
    window.folded = False
    window._leg_from = 0.0
    window._set_state("idle")
    window.spider.lean = 0.0
    window.spider.body_sway = 0.0
    window.spider.clear_targets()


def advance(seconds, step=STEP) -> None:
    """按假时钟推进若干帧，每帧跑一次主循环。"""
    for _ in range(max(1, int(round(seconds / step)))):
        clock.t += step
        window._tick()


def retract() -> float:
    return window._leg_retract()


# ---------------------------------------------------------------- 渲染采样

def opaque_far(image: QImage, center: QPointF, radius: float = 60.0) -> int:
    """离体心 `radius` 像素之外的不透明采样点个数。

    本体（头胸矩形 + 头部三角）在 unit≈1.23 下半径约 35px，都落在 60px 以内；
    腿一伸就是 200px 开外。所以这个数**只反映腿**，不受本体大小干扰 ——
    比「整幅图的不透明像素数」干净得多（本体占了相当大一块，那个比值很钝）。
    """
    total = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if image.pixelColor(x, y).alpha() <= 8:
                continue
            if math.hypot(x - center.x(), y - center.y()) > radius:
                total += 1
    return total


def leg_points(parts=("knee", "tip")):
    """步足的膝 / 脚尖的**窗口像素**坐标（照 painter 复刻）。

    故意**不含髋部**：髋就是腿和身体的连接点，落在本体轮廓里面 ——
    腿收起来了那里也还有本体，所以「折叠后该没有像素 / 该穿透」的点
    只能是膝和脚尖。

    腿只随 `heading` 转（不随 `lean`，见 `Spider._leg_point`），
    并且所有髋膝脚都带一个 `body_sway` 的侧摆。这两条抄错就测了个寂寞。
    """
    heading = window.spider.heading
    sway = getattr(window.spider, "body_sway", 0.0)
    ox, oy = window._canvas_origin()
    unit = window.unit
    ch, sh = math.cos(heading), math.sin(heading)
    transform = window._scene_transform()

    out = []
    for leg in window.spider.legs:
        if leg.palp:
            continue
        for tag, local in (("hip", leg.hip_pos), ("knee", leg.knee),
                           ("tip", leg.tip)):
            if tag not in parts:
                continue
            x, y = local[0] * unit, (local[1] + sway) * unit
            point = QPointF(ox + x * ch - y * sh, oy + x * sh + y * ch)
            if transform is not None:
                point = transform.map(point)
            out.append(("leg%d.%s" % (leg.index, tag), point))
    return out


def body_point() -> QPointF:
    """体心（本体一定画在这里）。"""
    heading = window.spider.heading
    sway = getattr(window.spider, "body_sway", 0.0)
    ox, oy = window._canvas_origin()
    x, y = 0.0, sway * window.unit
    point = QPointF(ox + x * math.cos(heading) - y * math.sin(heading),
                    oy + x * math.sin(heading) + y * math.cos(heading))
    transform = window._scene_transform()
    return transform.map(point) if transform is not None else point


def render() -> QImage:
    """按当前状态渲染一张与窗口同尺寸的图（走的是生产 painter）。"""
    image = QImage(int(window.width()), int(window.height()),
                   QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    transform = window._scene_transform()
    if transform is not None:
        painter.setTransform(transform, True)
    window.painter.paint(painter, window.spider, window._build_state(),
                         unit=window.unit, origin_px=window._canvas_origin())
    painter.end()
    return image


def alpha_near(image: QImage, point: QPointF, radius: int = 2) -> int:
    """取点周围一小片的最大 alpha。

    取邻域是因为腿宽只有几像素、又有抗锯齿，正好采样到半透明边缘
    （alpha=3）会被误判成「没画」。
    """
    best = 0
    cx, cy = int(round(point.x())), int(round(point.y()))
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x, y = cx + dx, cy + dy
            if 0 <= x < image.width() and 0 <= y < image.height():
                best = max(best, image.pixelColor(x, y).alpha())
    return best



# ---------------------------------------------------------------- A 待得住

settle()
check("A1 默认是展开的", window.folded is False and retract() == 0.0,
      "folded=%s retract=%.3f" % (window.folded, retract()))

window.set_folded(True, silent=True)
advance(0.70)                      # hide_legs 时长 0.55s
check("A2 收腿动画按时结束（不会卡在动画里）", window.effect is None,
      "effect=%r" % (window.effect,))
check("A3 ★ 收腿到位后 retract 停在 1.0（不是弹回 0）",
      abs(retract() - 1.0) < 1e-6, "retract=%.4f" % retract())

advance(3.0)                       # 再待 3 秒
check("A4 ★ 无腿模式待得住（3 秒后 retract 仍是 1.0）",
      abs(retract() - 1.0) < 1e-6 and window.folded,
      "retract=%.4f folded=%s" % (retract(), window.folded))

# 折叠期间被别的反馈形变扫过，腿也不能弹出来。
# （这就是 `_leg_retract()` 不敢直接读 `Tf.retract` 的原因：squash 的 retract 恒为 0。）
window.play("squash")
advance(0.10)
check("A5 ★ 折叠中被压扁一下，腿不会弹出来",
      abs(retract() - 1.0) < 1e-6,
      "effect=%r retract=%.4f" % (window.effect and window.effect[0], retract()))
advance(1.0)

# 待机时本体不动（折叠态也得守住这条老规矩）
settle()
window.set_folded(True, silent=True)
advance(0.70)
before = body_point()
advance(2.0)
after = body_point()
drift = math.hypot(after.x() - before.x(), after.y() - before.y())
check("A6 无腿模式待机时本体纹丝不动", drift < 1e-6, "漂移 %.6f px" % drift)

# ---------------------------------------------------------------- B 画得出就对

folded_image = render()
folded_leg_alpha = [(tag, alpha_near(folded_image, p))
                    for tag, p in leg_points()]
folded_body_alpha = alpha_near(folded_image, body_point())
# 本体半径必须按**真实几何**给，否则会把本体自己算成「远处像素」。
# 2026-10-17：白跳蛛/奶蛛的 `body_scale = 2`，肚子往后长了一倍，
# 原来的「头三角最远角 × 1.1」只盖到 +72.5，盖不住 -110.5 的肚尾。
_body_scale = window.spider.body_scale
_rear = abs(CS.THORAX[0] * CS.THORAX_SCALE
            - CS.THORAX[2] * CS.THORAX_SCALE * (_body_scale - 1.0))
_half = max(abs(CS.THORAX[1] * CS.THORAX_SCALE), CS.HEAD_TRI_HALF)
body_radius_px = math.hypot(max(_rear, CS.HEAD_OFF + CS.HEAD_TRI_LEN),
                            _half) * window.unit * 1.1
folded_far = opaque_far(folded_image, body_point(), radius=body_radius_px)

settle()
advance(0.05)
open_image = render()
open_leg_alpha = [(tag, alpha_near(open_image, p)) for tag, p in leg_points()]
open_far = opaque_far(open_image, body_point(), radius=body_radius_px)

check("B1 ★ 折叠后膝与脚尖一个像素都没有",
      all(a == 0 for _, a in folded_leg_alpha),
      "最大 alpha=%d" % max(a for _, a in folded_leg_alpha))
check("B2 折叠后本体照旧画着", folded_body_alpha > 200,
      "体心 alpha=%d" % folded_body_alpha)
check("B3 展开时腿是真的画出来的",
      all(a > 0 for _, a in open_leg_alpha),
      "最小 alpha=%d" % min(a for _, a in open_leg_alpha))
check("B4 ★ 折叠后离体心（本体半径外）整片空白（腿真的收进身体了）",
      folded_far == 0 and open_far > 100,
      "折叠 %d vs 展开 %d 个远处不透明采样点（半径 %.0fpx）"
      % (folded_far, open_far, body_radius_px))

# ---------------------------------------------------------------- C 看不见就点不中

settle()
window.set_folded(True, silent=True)
advance(0.70)

missed = [tag for tag, p in leg_points()
          if window._on_spider(int(round(p.x())), int(round(p.y())))]
center = body_point()
center_hit = window._on_spider(int(round(center.x())), int(round(center.y())))
check("C1 ★ 折叠后腿的落点全部穿透（不留看不见却点得中的空地）",
      not missed, "仍然吃点击的点: %s" % (missed or "无"))
check("C2 折叠后本体仍然点得中（还能拖动）", center_hit)

window.set_folded(False, silent=True)
advance(0.70)
missed2 = [tag for tag, p in leg_points()
           if not window._on_spider(int(round(p.x())), int(round(p.y())))]
check("C3 展开后腿又能点中了", not missed2,
      "点不中的点: %s" % (missed2 or "无"))

# C4：**收腿动画中途**腿已经往髋部 lerp 了，而 covers() 只认原位 ——
# 所以只要开始收，原位那一片就必须停止吃点击，否则动画那 0.55 秒里
# 会留下一圈「看不见却点得中」的空地。
settle()
window.set_folded(True, silent=True)
advance(0.30)                      # 收到约六成
mid_retract = retract()
mid_missed = [tag for tag, p in leg_points()
              if window._on_spider(int(round(p.x())), int(round(p.y())))]
check("C4 ★ 收腿动画中途，腿的原位也停止吃点击",
      mid_retract > window.LEG_HIT_MAX_RETRACT and not mid_missed,
      "中途 retract=%.3f，仍吃点击的点: %s" % (mid_retract, mid_missed or "无"))

# 刚起步那几帧腿基本还在原位，仍然应该点得中（不然一按菜单腿就「消失」一下）
settle()
window.set_folded(True, silent=True)
advance(0.05)
early = retract()
early_missed = [tag for tag, p in leg_points()
                if not window._on_spider(int(round(p.x())), int(round(p.y())))]
check("C5 刚起步时腿还在原位，仍然点得中",
      early < window.LEG_HIT_MAX_RETRACT and not early_missed,
      "retract=%.3f，点不中的点: %s" % (early, early_missed or "无"))

# ---------------------------------------------------------------- D 切换不跳

settle()
window.set_folded(True, silent=True)
samples = [retract()]
for _ in range(int(round(0.55 / STEP))):
    clock.t += STEP
    window._tick()
    samples.append(retract())
steps = [samples[i + 1] - samples[i] for i in range(len(samples) - 1)]
check("D1 收腿全程单调不回弹",
      all(s >= -1e-9 for s in steps),
      "最小步长 %.4f" % min(steps))
check("D2 收腿逐帧连续（不瞬移）",
      max(abs(s) for s in steps) < MAX_JUMP,
      "最大步长 %.4f（阈值 %.2f）" % (max(abs(s) for s in steps), MAX_JUMP))
check("D3 收腿从 0 走到 1",
      abs(samples[0]) < 1e-6 and abs(samples[-1] - 1.0) < 0.02,
      "%.3f → %.3f" % (samples[0], samples[-1]))

# 半路反向：收一半就点展开，必须从当前深度接着往回走，不能先弹到 1 再收
settle()
window.set_folded(True, silent=True)
advance(0.25)                          # hide_legs 播到约一半
mid = retract()
check("D4 半路反向的起点确实在中间", 0.15 < mid < 0.95, "中途 retract=%.3f" % mid)

window.set_folded(False, silent=True)
first = retract()
check("D5 ★ 半路点展开不跳变（从当前深度接着走）",
      abs(first - mid) < 1e-6, "切换前后 %.4f → %.4f" % (mid, first))

rev = [first]
for _ in range(int(round(0.60 / STEP))):
    clock.t += STEP
    window._tick()
    rev.append(retract())
rev_steps = [rev[i + 1] - rev[i] for i in range(len(rev) - 1)]
check("D6 反向伸腿单调、连续、走到 0",
      all(s <= 1e-9 for s in rev_steps)
      and max(abs(s) for s in rev_steps) < MAX_JUMP
      and abs(rev[-1]) < 0.02,
      "最大步长 %.4f 终点 %.4f" % (max(abs(s) for s in rev_steps), rev[-1]))

# ---------------------------------------------------------------- E 与其它功能的交界

# E1：折叠时识词要先伸腿（腿收着没法踩词）
settle()
window.set_folded(True, silent=True)
advance(0.70)


class _FakeOcr:
    @staticmethod
    def available():
        return True


_real_ocr = PW.OcrEngine
_real_go = window._capture_go
PW.OcrEngine = _FakeOcr
window._capture_go = lambda: None       # 别真去截屏开遮罩
window.start_capture()
unfolded_for_capture = (window.folded is False
                        and window.effect is not None
                        and window.effect[0] == "show_legs")
check("E1 ★ 折叠状态下识词会先自动伸腿",
      unfolded_for_capture,
      "folded=%s effect=%r" % (window.folded,
                               window.effect and window.effect[0]))
PW.OcrEngine = _real_ocr
window._capture_go = _real_go
window._capture_busy = False
window.show()

# E2：折叠时被叫去走位也要先伸腿（要走路就得有腿）
settle()
window.set_folded(True, silent=True)
advance(0.70)
window.travel_to(QPoint(window.center.x() + 240, window.center.y()))
check("E2 ★ 折叠状态下走位会先自动伸腿",
      window.folded is False
      and window.effect is not None and window.effect[0] == "show_legs"
      and window._travel is not None,
      "folded=%s travel=%s" % (window.folded, window._travel is not None))

# E3：按下鼠标 / `_drop_effect()` 不能打断收腿动画（打断了腿会瞬移）
settle()
window.set_folded(True, silent=True)
advance(0.20)
window._drop_effect()
check("E3 ★ 收腿动画不会被 _drop_effect 打断",
      window.effect is not None and window.effect[0] == "hide_legs",
      "effect=%r" % (window.effect and window.effect[0],))

# 反过来：普通反馈形变该清还是要清
settle()
window.play("squash")
window._drop_effect()
check("E4 普通反馈形变照旧被清掉", window.effect is None)

# E5：重复折叠是幂等的，不会重播动画
settle()
window.set_folded(True, silent=True)
advance(0.70)
window.set_folded(True, silent=True)
check("E5 重复折叠幂等（不重播动画）",
      window.effect is None and abs(retract() - 1.0) < 1e-6,
      "effect=%r retract=%.4f" % (window.effect, retract()))

# E6：菜单项的文案要跟着状态走，点了要真的切换
settle()


def fold_action():
    menu = window._make_menu()
    for action in menu.actions():
        if "八条腿" in action.text():
            return action
    return None


open_action = fold_action()
open_text = open_action.text() if open_action else ""
check("E6 展开态菜单显示「折叠」", "折叠" in open_text, repr(open_text))

if open_action is not None:
    open_action.trigger()
advance(0.70)
folded_action = fold_action()
folded_text = folded_action.text() if folded_action else ""
check("E7 菜单点一下真的折叠了", window.folded,
      "folded=%s" % window.folded)
check("E8 折叠态菜单显示「展开」", "展开" in folded_text, repr(folded_text))

if folded_action is not None:
    folded_action.trigger()
advance(0.70)
check("E9 再点一下真的展开了",
      window.folded is False and abs(retract()) < 0.02,
      "folded=%s retract=%.4f" % (window.folded, retract()))

# ---------------------------------------------------------------- 汇总
print()
print("=" * 48)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    for name in FAIL:
        print("  ✗ %s" % name)
sys.exit(1 if FAIL else 0)
