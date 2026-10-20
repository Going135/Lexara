# -*- coding: utf-8 -*-
"""形象对照表：把蜘蛛的几种关键姿态并排画出来，肉眼核对形象与动画。

覆盖六格：
  1. 待机（idle，朝向 π/2 —— 真正的蜘蛛俯视站姿）
  2. 行走中（crawl，喂真实位移，看步态相位与抬腿）
  3. 转弯（heading 变化中，看 lean 身体倾斜）
  4. 瞄准（四条腿踩住目标，看是否被拉成射线）
  5. 收腿一半（leg_retract = 0.5，看腿向髋部收缩 + 淡出）
  6. 收腿到底（leg_retract = 1.0，应该只剩本体）

另外单独出一张「浅色背景」对照：身体是深蓝填充 + 亮边，
浅色文档上不该糊成一个白方块。

用法：python tools/shape_sheet.py
输出：dist/shape/sheet.png、dist/shape/light.png
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

import crawler_spider as CS
from spider_painter import SpiderPainter, SpiderState

app = QApplication(sys.argv)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist", "shape")
os.makedirs(OUT, exist_ok=True)

WIDTH = 230.0            # 每格期望的静止站姿宽度（像素）
CELL = 420               # 每格画布边长
WALK_PX = 165.0          # 与 pet_window.WALK_SPEED 保持一致（像素/秒）

#: 本表用的 unit。喂给 `update()` 的 motion 必须是**局部单位**，
#: 所以要拿像素速度除以 unit 换算 —— 直接写「每帧 3 个单位」会跟真实
#: 步速脱节，量出来的伸展比例也就不能代表真机表现。
UNIT = SpiderPainter.unit_for_width(WIDTH)
STEP_LOCAL = WALK_PX / UNIT / 60.0


def fresh() -> CS.Spider:
    s = CS.Spider(size=1.0)
    s.heading = math.pi / 2          # 面朝屏幕下方 = 蜘蛛俯视站姿
    # 身体点链按新朝向摆好（正常由 __post_init__ 完成，这里改了朝向要重摆）
    fx, fy = math.cos(s.heading), math.sin(s.heading)
    s.body = {
        "head": [fx * CS.HEAD_OFF * s.scale, fy * CS.HEAD_OFF * s.scale],
        "p": [0.0, 0.0],
        "abd": [fx * CS.ABD_OFF * s.scale, fy * CS.ABD_OFF * s.scale],
        "spin": [fx * (CS.ABD_OFF + CS.SPIN_OFF) * s.scale,
                 fy * (CS.ABD_OFF + CS.SPIN_OFF) * s.scale],
    }
    s._prev_heading = s.heading
    return s


def idle() -> CS.Spider:
    """静置到**稳态**的待机蜘蛛。

   为什么是 180 帧而不是 120：待机姿势淡入期间静止位在缓慢移动，脚要跟着
   挪，而 `_start_step` 的步时长是随机的（0.06~0.36s）。实测 120 帧（2s）
   时有 25% 的概率捕捉到「某条腿仍在迈步中」，150 帧起收敛、180 帧 20/20 全稳。
   这里要呈现代价是**稳态待机**（用户要求纹丝不动的那一刻），不是姿势淡入期。
   """
    s = fresh()
    for _ in range(180):
        s.update(1 / 60, "idle", None, motion=(0.0, 0.0))
    return s


def walking() -> CS.Spider:
    """走了 2 秒（真实步速），抓一个「多数腿已经迈过一轮」的瞬间。"""
    s = fresh()
    for _ in range(120):
        s.update(1 / 60, "crawl", None, motion=(STEP_LOCAL, 0.0))
    return s


def turning() -> CS.Spider:
    """先向右走，再往左上拐 —— 抓 heading 正在变的那一刻看 lean。"""
    s = fresh()
    for _ in range(60):
        s.update(1 / 60, "crawl", None, motion=(STEP_LOCAL, 0.0))
    for _ in range(10):
        s.update(1 / 60, "crawl", None, motion=(-STEP_LOCAL, -STEP_LOCAL * 0.45))
    return s


def aiming() -> CS.Spider:
    """模拟 AimOverlay._assign()：屏幕点 → 局部点 → 可达匹配 → 直接写 targets。

    **不要用 `place_targets()`**：它是按 stepper 顺序 zip 的，会把左腿的目标
    发给右腿，画出来八条腿全部交叉 —— 那正是要避免的观感。生产链路上
    AimOverlay 是按 `assign_reachable` 给出的 (腿, 词) 对逐条绑定的，这里照做。
    """
    s = fresh()
    pts = [(95, -75), (-100, -65), (110, 60), (-105, 70), (0, 330)]
    targets = [CS.Target(text="t%d" % i, center=p) for i, p in enumerate(pts)]
    steppers = [L for L in s.legs if not L.palp]
    pairs = CS.assign_reachable(steppers, targets, 1.0, max_frac=0.92)

    s.targets = {}
    for p in pairs:
        s.targets[steppers[p["leg"]].index] = targets[p["target"]].center
    for _ in range(150):
        s.update(1 / 60, "idle", None, motion=(0.0, 0.0))
    return s


def retracted(k: float) -> CS.Spider:
    return idle()


PANELS = [
    ("待机 idle", idle, 0.0),
    ("行走 crawl", walking, 0.0),
    ("转弯 lean", turning, 0.0),
    ("瞄准（4 腿踩词）", aiming, 0.0),
    ("收腿 retract=0.5", lambda: retracted(0.5), 0.5),
    ("收腿 retract=1.0", lambda: retracted(1.0), 1.0),
]


def draw_cell(painter: QPainter, spider: CS.Spider, label: str, retract: float,
              bg: QColor, text_color: QColor, spine: bool) -> None:
    painter.fillRect(QRectF(0, 0, CELL, CELL), bg)
    p = SpiderPainter()
    unit = SpiderPainter.unit_for_width(WIDTH)
    origin = (CELL / 2.0, CELL / 2.0)
    state = SpiderState(heading=spider.heading, leg_retract=retract)
    p.paint(painter, spider, state, unit=unit, origin_px=origin)

    if spine:
        # 参考：静止位（小空心圆）。能直观看出脚是不是站在站姿上。
        pen = QPen(QColor(255, 255, 255, 45))
        pen.setWidthF(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for leg in spider.legs:
            rp = p.to_screen(spider.rest_pos(leg))
            painter.drawEllipse(int(rp[0]) - 3, int(rp[1]) - 3, 6, 6)

    font = QFont()
    font.setPointSize(10)
    painter.setFont(font)
    painter.setPen(QPen(text_color))
    painter.drawText(QRectF(0, CELL - 30, CELL, 24), Qt.AlignHCenter, label)


# ---------------------------------------------------------------- 主表（深色底）
sheet = QImage(CELL * 3, CELL * 2, QImage.Format_ARGB32)
sheet.fill(QColor(14, 18, 26))
sp = QPainter(sheet)
sp.setRenderHint(QPainter.Antialiasing, True)
for idx, (label, factory, retract) in enumerate(PANELS):
    cx, cy = (idx % 3) * CELL, (idx // 3) * CELL
    sp.save()
    sp.translate(cx, cy)
    draw_cell(sp, factory(), label, retract, QColor(14, 18, 26), QColor(200, 220, 255), True)
    sp.restore()
    sp.setPen(QPen(QColor(255, 255, 255, 26)))
    sp.drawRect(QRectF(cx + 0.5, cy + 0.5, CELL - 1, CELL - 1))
sp.end()
sheet_path = os.path.join(OUT, "sheet.png")
sheet.save(sheet_path)
print("saved", sheet_path)

# ---------------------------------------------------------------- 浅色底对照
light = QImage(CELL * 2, CELL, QImage.Format_ARGB32)
light.fill(QColor(250, 250, 248))
lp = QPainter(light)
lp.setRenderHint(QPainter.Antialiasing, True)
for idx, (label, factory, retract) in enumerate(
        [("浅底 待机", idle, 0.0), ("浅底 瞄准", aiming, 0.0)]):
    lp.save()
    lp.translate(idx * CELL, 0)
    draw_cell(lp, factory(), label, retract, QColor(250, 250, 248), QColor(60, 70, 90), False)
    lp.restore()
    lp.setPen(QPen(QColor(0, 0, 0, 30)))
    lp.drawRect(QRectF(idx * CELL + 0.5, 0.5, CELL - 1, CELL - 1))
lp.end()
light_path = os.path.join(OUT, "light.png")
light.save(light_path)
print("saved", light_path)

# ---------------------------------------------------------------- 几何自检
# 这一步同时充当**渲染冒烟测试**：能跑到这里就说明 SpiderState 的新字段
# （leg_retract）、CS 的新常量（THORAX_RADIUS / HEAD_TRI_*）都在，
# 少任何一个都会先在这里抛异常，而不是等到用户点开 exe 才发现。
print("\n-- 几何自检（每条腿的伸展 / 抬脚数）--")
failures = 0
for label, factory, retract in PANELS:
    s = factory()
    worst = max(math.hypot(L.tip[0] - L.hip_pos[0], L.tip[1] - L.hip_pos[1]) / L.full
                for L in s.legs)
    stepping = sum(1 for L in s.legs if L.stepping)
    print("  %-18s 最远伸展 %.3f×腿长   迈步中 %d 条   speed=%6.1f" %
          (label, worst, stepping, s.speed))
    if worst > CS.REACH_LIMIT_FRAC + 1e-6:
        print("    [FAIL] 伸展超过腿长上限 %.3f" % CS.REACH_LIMIT_FRAC)
        failures += 1

idle_spider = idle()
if any(L.stepping for L in idle_spider.legs) or idle_spider.speed > 1e-6:
    print("    [FAIL] 待机时腿在动（用户要求待机纹丝不动）")
    failures += 1

if not (0.0 <= CS.IDLE_TWITCH_RATE <= 1e-9):
    print("    [FAIL] IDLE_TWITCH_RATE 被改成正数了（待机会抽搐）")
    failures += 1

print("\nunit=%.3f  行走每帧喂入 %.3f 局部单位（= %.0f px/s）" %
      (UNIT, STEP_LOCAL, WALK_PX))
if failures:
    print("\n========================================  失败 %d 项" % failures)
    sys.exit(1)
print("========================================  通过")
