# -*- coding: utf-8 -*-
"""点击命中 / 不被裁剪的回归测试。

窗口是逐像素透明的（`WA_TranslucentBackground`），Windows 会把 alpha=0 的像素
自动穿透，而蜘蛛周围那圈柔光 alpha 只有 1~8、照样吃点击 —— 所以窗口在
`WM_NCHITTEST` 里按真实轮廓回 `HTTRANSPARENT`（见 `PetWindow.nativeEvent`）。

这里盯住三条不变式：
    A. **点得到的**：画出来的每一处（腿的髋/膝/脚尖、身体点链、头胸）
       都必须在命中测试里判为「在蜘蛛身上」。
    B. **穿得透的**：离蜘蛛明显远的地方必须判为「不在身上」，能穿透。
    C. **不裁的**：所有绘制点都必须落在窗口矩形内 —— 没有遮罩以后，
       窗口边界是唯一还能把蜘蛛切掉的东西。

以前那版用的是 `setMask`，而且朝向写死成 0（蜘蛛实际面朝下），
于是遮罩和画面差了整整一个直角，蜘蛛被裁成一地碎屑；
原来的 `test_spider.py` 全是纯几何断言，绕过了窗口这一层，一路绿灯放行。

运行：  python test/test_click_through.py
"""

import math
import os
import random
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtCore import QPointF                      # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

import anim                                             # noqa: E402
import crawler_spider as CS                             # noqa: E402
import pet_window as PW                                 # noqa: E402
from pet_window import PetWindow                        # noqa: E402

PASS, FAIL = [], []


class Clock:
    """假时钟：一次性形变的进度读的是挂钟，必须能冻住。

    不冻的话，`drawn_points()` 采样的那一刻和随后逐个 `_on_spider()` 判定
    的那一刻会差几十到几百毫秒（几百次判定累加），`shake` 这种高频晃动
    在这期间已经甩开好几像素 —— 于是「画出来的点」和「判定用的变换」对不上，
    测试开始随机报假失败。冻结后每张对比都是同一瞬间的快照。
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


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if ok else "[fail]", name, detail))


app = QApplication(sys.argv)
random.seed(5)

window = PetWindow(None, None, sprite_w=360.0)
window.resize(*window._window_size())
UNIT = window.unit
SPAN = CS.THORAX_SCALE


def drawn_points(with_samples=True):
    """本帧实际会画到窗口上的关键点 → `[(标签, 窗口像素), ...]`。

    带标签是为了**失败时能直接说出是哪个点没点中** —— 只报坐标的话，
    还得回去反推「(264,293) 到底是哪个部位」，两个朝向一来就懵了。

    这里要**照着 painter 复刻**，否则测的是「不会被画出来的点」：
      · 头胸矩形不是按 heading 画，而是按 `heading + lean`（转弯时额外倾斜）；
      · 髋/膝/脚都带一个 `body_sway` 的侧摆位移（`_hip_screen`）。
    """
    heading = window.spider.heading
    lean = getattr(window.spider, "lean", 0.0)
    sway = getattr(window.spider, "body_sway", 0.0)
    ox, oy = window._canvas_origin()
    cos_h, sin_h = math.cos(heading), math.sin(heading)

    def to_screen(local):
        # 侧摆是**整体平移**（painter 给身体和所有髋部都加了），
        # 所以在局部坐标里统一 +y 就行
        x, y = local[0] * UNIT, (local[1] + sway) * UNIT
        return QPointF(ox + x * cos_h - y * sin_h, oy + x * sin_h + y * cos_h)

    points = []
    for leg in window.spider.legs:
        tag = "palp" if leg.palp else "leg%d" % leg.index
        hip, knee, tip = (to_screen(leg.hip_pos), to_screen(leg.knee),
                          to_screen(leg.tip))
        points += [("%s.hip" % tag, hip), ("%s.knee" % tag, knee),
                   ("%s.tip" % tag, tip)]
        if with_samples:
            for a, b, seg in ((hip, knee, "hip-knee"), (knee, tip, "knee-tip")):
                for k in (0.3, 0.6, 0.9):
                    points.append(("%s.%s@%.1f" % (tag, seg, k),
                                   QPointF(a.x() + (b.x() - a.x()) * k,
                                           a.y() + (b.y() - a.y()) * k)))

    center = to_screen((0.0, 0.0))
    points.append(("head.dot", to_screen(window.spider.body["head"])))
    points.append(("center", center))

    # 头胸矩形：painter 里绕体心转 `heading + lean`
    body_heading = heading + lean
    cb, sb = math.cos(body_heading), math.sin(body_heading)
    ts = UNIT * SPAN
    x0, y0, rw, rh = CS.THORAX
    for lx, ly in ((x0, y0), (x0 + rw, y0), (x0, y0 + rh), (x0 + rw, y0 + rh)):
        px, py = lx * ts, ly * ts
        points.append(("thorax(%.1f,%.1f)" % (lx, ly),
                       QPointF(center.x() + px * cb - py * sb,
                               center.y() + px * sb + py * cb)))

    # 头部三角：painter 用的是 `CS.HEAD_OFF * unit`（**不乘 THORAX_SCALE**），
    # 顶点再朝前伸 HEAD_TRI_LEN。
    for lx, ly in ((CS.HEAD_OFF, -CS.HEAD_TRI_HALF),
                   (CS.HEAD_OFF, 0.0),
                   (CS.HEAD_OFF, CS.HEAD_TRI_HALF),
                   (CS.HEAD_OFF + CS.HEAD_TRI_LEN, 0.0)):
        px, py = lx * UNIT, ly * UNIT
        points.append(("head.tri(%.1f,%.1f)" % (lx, ly),
                       QPointF(center.x() + px * cb - py * sb,
                               center.y() + px * sb + py * cb)))

    transform = window._scene_transform()
    if transform is not None:
        points = [(tag, transform.map(p)) for tag, p in points]
    return points


def audit(tag, want_clear=True):
    """返回 (没被命中判定的点, 判定为命中的窗外点, 超出窗口的点) —— 都带标签。"""
    missed, bad_far, outside = [], [], []
    rect = window.rect()
    for label, point in drawn_points():
        x, y = int(round(point.x())), int(round(point.y()))
        if not rect.contains(x, y):
            outside.append((label, x, y))
        if not window._on_spider(x, y):
            missed.append((label, x, y))
    if want_clear:
        # 窗口四角离蜘蛛很远，必须判为可穿透
        for x, y in ((4, 4), (rect.width() - 5, 4), (4, rect.height() - 5),
                     (rect.width() - 5, rect.height() - 5)):
            if window._on_spider(x, y):
                bad_far.append((x, y))
    return missed, bad_far, outside


# ---------------------------------------------------------------- A/B 朝向
print("-- 各朝向：点得到的 / 穿得透的 --")
for degrees in (90, 0, 180, 45, 135, -90, 225, 315):
    window.spider.heading = math.radians(degrees)
    missed, bad_far, outside = audit("heading")
    check("heading=%3d° 腿身全部可点中" % degrees, not missed,
          "" if not missed else "→ %d 处点不中：%s" % (len(missed), missed[:3]))
    check("heading=%3d° 四角可穿透" % degrees, not bad_far,
          "" if not bad_far else "→ %s 被判成蜘蛛" % bad_far)

# ---------------------------------------------------------------- C 一次性形变
print("\n-- 一次性形变（跳跃/压扁/抖动）--")
for name in ("jump", "squash", "shake", "pop", "spin"):
    duration = anim.EFFECT_DURATION.get(name, 0.6)
    worst_miss, worst_out = [], []
    for progress in (0.0, 0.2, 0.45, 0.7, 0.95):
        window.spider.heading = math.pi / 2
        # 用假时钟：这一帧的进度在整轮 audit 里保持不变（见 Clock 的说明）
        window.effect = (name, clock.t - progress * duration, duration)
        missed, _, outside = audit(name)
        worst_miss += missed[:2]
        worst_out += outside[:2]
    window.effect = None
    check("%-7s 全程可点中" % name, not worst_miss,
          "" if not worst_miss else "→ %s" % worst_miss[:3])
    check("%-7s 全程没被窗口裁掉" % name, not worst_out,
          "" if not worst_out else "→ %s" % worst_out[:3])

# ---------------------------------------------------------------- D 动态步态
print("\n-- 动态步态（走 + 转 + 迈步，连续 240 帧）--")
worst_miss, worst_out = [], []
for frame in range(240):
    window.spider.update(1 / 60, "crawl", 165.0,
                         motion=(3.0, 1.5) if frame < 150 else (0.0, -2.0))
    missed, _, outside = audit("frame", want_clear=False)
    if missed:
        worst_miss.append((frame, missed[:2]))
    if outside:
        worst_out.append((frame, outside[:2]))
check("240 帧中每一处都点得中", not worst_miss,
      "" if not worst_miss else "→ %d 帧有问题，例如 %s" % (len(worst_miss), worst_miss[0]))
check("240 帧中没有任何一处被窗口裁掉", not worst_out,
      "" if not worst_out else "→ %d 帧有问题，例如 %s" % (len(worst_out), worst_out[0]))

# ---------------------------------------------------------------- E 识词伸展
print("\n-- 识词伸展（脚伸到最远处，最容易顶出窗口）--")
window.spider.heading = math.pi / 2
window.effect = None
window._set_state("think")
far = []
for leg in window.spider.legs:
    if leg.palp:
        continue
    reach = leg.full * 0.92
    far.append((leg.hip + math.cos(leg.ang) * reach,
                leg.hip_y + math.sin(leg.ang) * reach))
window.spider.place_targets(far)
for _ in range(120):
    window.spider.update(1 / 60, "think", 0.0)
missed, _, outside = audit("reach")
print("      窗口 %dx%d   最远脚距体心 %.0fpx   半窗 %.0fpx×%.0fpx" % (
    window.width(), window.height(),
    max(math.hypot(p[0], p[1]) for p in far) * UNIT,
    window.width() / 2, window.height() / 2))
check("伸到最远时每一处都点得中", not missed,
      "" if not missed else "→ %s" % missed[:3])
check("伸到最远时没有被窗口裁掉", not outside,
      "" if not outside else "→ %s（窗口得加大）" % outside[:3])

# ---------------------------------------------------------------- F 点头命中
print("\n-- 点头识词：头的方位要跟着朝向 --")
for degrees in (0, 90, 180, 270):
    heading = math.radians(degrees)
    window.spider.heading = heading
    window.spider.clear_targets()
    window.effect = None
    ox, oy = window._canvas_origin()
    cos_h, sin_h = math.cos(heading), math.sin(heading)
    hx, hy = window.spider.body["head"]
    px = ox + hx * UNIT * cos_h - hy * UNIT * sin_h
    py = oy + hx * UNIT * sin_h + hy * UNIT * cos_h
    got = window._hit(px, py)
    check("朝向 %3d° 时点头命中「头」" % degrees, got == "head", "→ %r" % got)

# ---------------------------------------------------------------- G 点击语义
print("\n-- 点击语义：三角头 = 识词，矩形身 = 拖动，尾巴那块 = 穿透 --")
window.effect = None
window.spider.heading = math.pi / 2
window.spider.body_sway = 0.0
window.spider.lean = 0.0
window.spider.clear_targets()


def where(local):
    """局部坐标 → 窗口像素（走窗口自己的那套变换，不在测试里另写一份）。"""
    window.painter.setup(window._canvas_origin(), UNIT, window.spider.heading)
    return window.painter.to_screen(local)


#: 当前皮肤的实际身体后缘（局部单位）。
#: 2026-10-17 起白跳蛛 / 奶蛛的 `body_scale = 2`，肚子往后长了一倍，
#: 判定框必须跟着走 —— 否则「点大半个肚子没反应，却能点中肚子外面那块空气」。
#: 老断言写死「尾巴原位置（-40）必须穿透」，那是 1 倍身子时代的事实，
#: 现在 -40 确实在画面里，穿透反而是 bug。这里按真实后缘动态取点。
BODY_REAR = (CS.THORAX[0] * CS.THORAX_SCALE
             - CS.THORAX[2] * CS.THORAX_SCALE
             * (window.spider.body_scale - 1.0))

SEMANTICS = (
    ("三角头中心", (CS.HEAD_OFF + CS.HEAD_TRI_LEN * 0.45, 0.0), "head"),
    ("三角底边内侧", (CS.HEAD_OFF + 1.0, 0.0), "head"),
    ("矩形身中心", (0.0, 0.0), "body"),
    ("矩形后半", (CS.THORAX[0] * CS.THORAX_SCALE + 3.0, 0.0), "body"),
    # 放大后的肚子中段：画得出，就该点得中（body_scale=1 时这里会落空）
    ("放大后的肚子", (BODY_REAR * 0.6, 0.0),
     "body" if window.spider.body_scale > 1.0 else None),
    # 身子真正的外面：不管放大几倍都该穿透
    ("身体后缘之外", (BODY_REAR - 6.0, 0.0), None),
    ("三角尖之外", (CS.HEAD_OFF + CS.HEAD_TRI_LEN + 8.0, 0.0), None),
    ("身体上方空白", (0.0, CS.THORAX[3] * CS.THORAX_SCALE * 0.5 + 12.0), None),
)
for label, local, want in SEMANTICS:
    got = window._hit(*where(local))
    check("点%s → %s" % (label, want if want else "落空"), got == want,
          "→ %r" % got)

# 语义要落到「吃不吃这次点击」上：头和身必须吃，身子外面必须穿透。
# 注意只能拿**确定没有腿经过**的点来验穿透 —— 腿也是蜘蛛的一部分，
# 腿底下那点空白本来就应该吃点击。
SHOOT_THROUGH = ("身体后缘之外", "三角尖之外")
check("三角头会吃点击（识词入口）",
      window._on_spider(*where((CS.HEAD_OFF + 4.0, 0.0))))
check("矩形身会吃点击（拖动入口）", window._on_spider(*where((0.0, 0.0))))
missing = [label for label, local, want in SEMANTICS
           if want is None and label in SHOOT_THROUGH
           and window._on_spider(*where(local))]
check("「身子外」「三角之外」真的穿透（不挡下面的窗口）", not missing,
      "" if not missing else "→ 仍然吃点击：%s" % missing)

# ---------------------------------------------------------------- 汇总
print("\n================================================")
print("通过 %d / %d" % (len(PASS), len(PASS) + len(FAIL)))
if FAIL:
    print("失败：")
    for name in FAIL:
        print("  - %s" % name)
sys.exit(1 if FAIL else 0)
