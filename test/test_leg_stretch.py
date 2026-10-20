# -*- coding: utf-8 -*-
"""腿**不被拉长**的回归测试。

这一条是「蜘蛛支离破碎 / 腿鬼畜」的根因检查。之前那批测试全是纯几何
（给定脚的位置算 IK），绕过了唯一会出错的一环：**窗口把身体位移喂给步态**。
那里有单位换算，错一次就全盘皆输：

    · `advance()` 活在蜘蛛局部坐标系里（`to_screen` 会把局部坐标 × `unit`
      才是像素）。喂像素进去 = 位移放大 `unit` 倍（200% 大小下 ≈ 2.5 倍），
      脚一帧被拖两倍半的行程，步态全程贴着硬上限跑。
    · 腾空时脚若不同步重钉，一次 500px 的跳跃会把八只脚拖到腿长的 4 倍外，
      落地瞬间同时抽回 —— 屏幕上就是一把射线。

所以这里**真的驱动窗口**跑完整的时间轴，每一帧量「脚尖离髋多远」，
超过腿全长就算失败。运行：python test/test_leg_stretch.py
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint                      # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from pet_window import PetWindow                       # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-46s %s" % ("ok" if ok else "!!", name, detail), flush=True)
    return ok


app = QApplication(sys.argv)
window = PetWindow(None, None, sprite_w=360.0)
window._timer.stop()                       # 手动按固定节奏推进，测试要可复现
window.start_capture = lambda *a, **k: None

#: 允许的超出比例。`Spider.foot_now()` 会把脚尖夹到
#: `crawler_spider.REACH_LIMIT_FRAC`（0.99×腿长）之内，所以这里留 1% 浮点余量就够了。
#: 以前写 1.02 —— 那是「没夹」时代的数值，结果行走时约一半的随机步长会摸到 1.03×，
#: 测试随机挂；现在夹住了，阈值收紧到 1.00 才是真正在守这条不变式。
SLACK = 1.00


def sample():
    """量一次：每只脚离自己髋部多远，以及离体心多远。"""
    worst_leg, worst_hip, worst_tip = 0.0, None, 0.0
    for leg in window.spider.legs:
        d_hip = math.hypot(leg.tip[0] - leg.hip_pos[0], leg.tip[1] - leg.hip_pos[1])
        d_body = math.hypot(leg.tip[0], leg.tip[1])
        if d_hip / max(leg.full, 1e-6) > worst_leg:
            worst_leg = d_hip / leg.full
            worst_hip = leg.index
        worst_tip = max(worst_tip, d_body)
    return worst_leg, worst_hip, worst_tip


def drive(frames, tag):
    """推进 ``frames`` 帧，返回 (最差伸展比, 是哪条腿, 脚离体心的最远像素)。"""
    peak, peak_leg, peak_px = 0.0, None, 0.0
    for _ in range(frames):
        window._last = time.monotonic() - 1 / 60.0
        window._tick()
        ratio, leg, tip = sample()
        if ratio > peak:
            peak, peak_leg = ratio, leg
        peak_px = max(peak_px, tip * window.unit)
        time.sleep(1 / 120.0)
    print("       %-10s 最差伸展 %5.2f×腿长 (leg%s)   脚最远 %.0fpx"
          % (tag, peak, peak_leg, peak_px), flush=True)
    return peak, peak_leg, peak_px


print("-- 缩放 50% / 100% / 200% 各走一段、跳一段 --")
for scale in (0.5, 1.0, 2.0):
    window.set_scale(scale)
    window._apply_geometry(resize=True)
    unit = window.unit

    # 走动（crawl）：位移全部来自 `_tick` 里的 motion 喂给步态
    window.travel_to(window.center + QPoint(int(-160 * scale), int(-70 * scale)),
                     force_jump=False)
    peak, leg, _ = drive(90, "走 %3d%%" % int(scale * 100))
    check("缩放 %3d%%：走动时腿没被拉长" % int(scale * 100), peak <= SLACK,
          "→ %.2f×腿长（unit=%.2f）" % (peak, unit))

    # 腾空（jump）：最容易出事的一段
    window.travel_to(window.center + QPoint(int(-420 * scale), int(-240 * scale)),
                     force_jump=True)
    peak, leg, _ = drive(90, "跳 %3d%%" % int(scale * 100))
    check("缩放 %3d%%：腾空时腿没被拉长" % int(scale * 100), peak <= SLACK,
          "→ %.2f×腿长" % peak)

    # 落地之后要回得到自然站姿
    peak, leg, _ = drive(60, "站 %3d%%" % int(scale * 100))
    check("缩放 %3d%%：落地后回到正常站姿" % int(scale * 100), peak <= SLACK,
          "→ %.2f×腿长" % peak)

print()
print("-- 连续长距离跳跃（偏移会累积的情形）--")
window.set_scale(1.0)
for i in range(5):
    window.travel_to(window.center + QPoint(-420, -220), force_jump=True)
    peak, leg, tip_px = drive(70, "第%d跳" % (i + 1))
    if not check("第 %d 次跳跃腿没被拉长" % (i + 1), peak <= SLACK,
                 "→ %.2f×腿长，脚最远 %.0fpx" % (peak, tip_px)):
        break

print()
print("-- 拖动（鼠标快速甩动）--")
window.center = QPoint(window.center.x() - 30, window.center.y() - 20)
peak, _, _ = drive(80, "拖动")
check("拖动时腿没被拉长", peak <= SLACK, "→ %.2f×腿长" % peak)

print()
print("=" * 48)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    for name in FAIL:
        print("  失败：" + name)
sys.exit(1 if FAIL else 0)
