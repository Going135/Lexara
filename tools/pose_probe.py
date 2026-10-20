# -*- coding: utf-8 -*-
"""姿态出图 —— 确定性驱动真窗口，给每个状态出一张整身照。

为什么不靠 QTimer 实拍：定时器和事件循环会被启动期的一次性开销顶住，
积压后一次性触发，几枪打到同一帧上（实测 idle / walking / airborne 抓出来
的图 md5 完全一样，白折腾）。这里改成**手动推进**：伪造 ``_last`` 再调
``_tick()``，帧数完全可控，同一份输入永远出同一张图。

运行：  python tools/pose_probe.py
输出：  dist/pose/<名字>.png（含透明通道，深色底可看柔光）
"""
import math
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint                      # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

import pet_window                                      # noqa: E402
from pet_window import PetWindow                       # noqa: E402

OUT = os.path.join(BASE, "dist", "pose")
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)


class Clock:
    """假时钟。

    `_tick` 里 **dt 用参数、位移进度却读挂钟**（`now - t0`），只伪造 dt
    的话两者会分家：帧推进 60 帧但挂钟才走了 0.4 秒，跳跃永远不落地。
    把 `pet_window` 模块里的 `time` 换成这个，两者就永远同步。
    """

    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def strftime(self, fmt):                            # 供 _log 用
        import time as _real
        return _real.strftime(fmt)


clock = Clock()
pet_window.time = clock

# 不带词典，纯粹看画面
pet = PetWindow(None, None, sprite_w=380.0)
pet._timer.stop()                      # 时间由我们说了算
pet.start_capture = lambda *a, **k: None
pet.bubble.hide_now()


def run(frames, dt=1 / 60.0):
    """推进 ``frames`` 帧：假时钟与 dt 同步前进，再调一次真正的 `_tick`。"""
    for _ in range(frames):
        pet._last = clock.t
        clock.t += dt
        pet._tick()
        time.sleep(1 / 300.0)          # 让 Qt 有机会处理重绘请求


def shot(name):
    from PySide6.QtGui import QColor, QImage, QPainter

    canvas = pet.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    # 深色底：柔光/半透明部分在透明 PNG 里看不出，垫一层深色便于肉眼检查
    view = QImage(canvas.size(), QImage.Format_ARGB32)
    view.fill(QColor(16, 22, 30))
    painter = QPainter(view)
    painter.drawImage(0, 0, canvas)
    painter.end()
    path = os.path.join(OUT, "%s.png" % name)
    view.save(path)

    worst = max(math.hypot(L.tip[0] - L.hip_pos[0], L.tip[1] - L.hip_pos[1]) / L.full
                for L in pet.spider.legs)
    reached = max(math.hypot(L.tip[0], L.tip[1]) for L in pet.spider.legs)
    print("  %-12s mode=%-5s heading=%6.1f°  伸展峰值 %.2f×腿长  脚最远 %.0fpx"
          % (name, pet.spider.mode, math.degrees(pet.spider.heading) % 360,
             worst, reached * pet.unit))


print("窗口 %dx%d   unit=%.3f" % (pet.width(), pet.height(), pet.unit))

print("待机")
pet._set_state("idle")
run(60)
shot("01_idle")

print("行走（持续推进 90 帧，中途取三张）")
pet.travel_to(pet.center + QPoint(-230, -110), force_jump=False)
run(25)
shot("02_walk_a")
run(25)
shot("03_walk_b")
run(40)
shot("04_walk_c")

print("转向行走（走到屏幕另一侧）")
pet.travel_to(pet.center + QPoint(300, -180), force_jump=False)
run(30)
shot("05_turn")
run(40)
shot("06_walk_d")

print("跳跃")
pet.travel_to(pet.center + QPoint(-520, -260), force_jump=True)
run(12)
shot("07_jump_rise")
run(14)
shot("08_jump_peak")
run(18)
shot("09_jump_fall")
run(45)
shot("10_landed")

print("一次性形变")
for name, effect in (("11_effect_jump", "jump"), ("12_effect_squash", "squash"),
                     ("13_effect_shake", "shake"), ("14_effect_spin", "spin")):
    pet.play(effect)
    run(6)
    shot(name)
    pet.effect = None
    run(20)

print("识词瞄准（八条腿伸向八个目标）")
pet._set_state("think")
unit = pet.unit
points = [(150.0 / unit, 80.0 / unit), (60.0 / unit, 150.0 / unit),
          (-120.0 / unit, 90.0 / unit), (-170.0 / unit, -30.0 / unit),
          (-90.0 / unit, -150.0 / unit), (40.0 / unit, -160.0 / unit),
          (140.0 / unit, -110.0 / unit), (180.0 / unit, 20.0 / unit)]
pet.spider.place_targets(points)
run(30)
shot("15_aim")
run(40)
shot("16_aim_settled")
pet.spider.clear_targets()

print("缩放 50% / 200%")
for tag, scale in (("17_scale_50", 0.5), ("18_scale_200", 2.0)):
    pet.clear_targets() if hasattr(pet, "clear_targets") else None
    pet._set_state("idle")
    pet.set_scale(scale)
    pet._apply_geometry(resize=True)
    run(50)
    pet.travel_to(pet.center + QPoint(int(-200 * scale), int(-90 * scale)),
                  force_jump=False)
    run(30)
    shot(tag)

print("\n输出目录：" + OUT)
