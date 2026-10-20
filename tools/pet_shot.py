# -*- coding: utf-8 -*-
"""真实窗口抓拍 —— 确认蜘蛛在屏幕上**没有缺块**。

窗口是逐像素透明的（`WA_TranslucentBackground`），早先还用 `setMask`
做操作系统级硬裁剪，那个裁剪 `QWidget.grab()` 抓不到，必须整屏抓。
现在遮罩已经去掉，窗口不再有任何 OS 级裁剪，`QWidget.grab()` 就等于
屏幕最终像素，所以两路都拍：自抓（判据，不受别的窗口干扰）+ 整屏（看合成效果）。

**不靠 QTimer。** 定时器和事件循环会被启动期的一次性开销顶住，积压后一次性触发，
几枪打到同一帧上（实测 idle / walking / airborne 抓出来的图 md5 完全一样）。
这里改成手动推进：**注入假时钟**（`_tick` 里 dt 用参数、位移进度却读挂钟，
只伪造 dt 会让跳跃永远不落地），帧数完全可控。

运行：  python tools/pet_shot.py
输出：  dist/selftest/own_*.png（含 alpha）、dist/selftest/screen_*.png（整屏裁剪）
"""
import math
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QPoint, QRect                     # noqa: E402
from PySide6.QtGui import QGuiApplication                    # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

import pet_window                                            # noqa: E402
from lexicon import Lexicon                                  # noqa: E402
from pet_window import PetWindow                             # noqa: E402
from wordbook import Wordbook, resource_path                 # noqa: E402

OUT = os.path.join(BASE, "dist", "selftest")
os.makedirs(OUT, exist_ok=True)


class Clock:
    """假时钟：让挂钟与 dt 永远同步（见模块 docstring）。"""

    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def strftime(self, fmt):
        import time as _real
        return _real.strftime(fmt)


clock = Clock()
pet_window.time = clock

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

lexicon = Lexicon(resource_path("assets", "ecdict.sqlite"),
                  resource_path("assets", "exam-tags.sqlite"))
pet = PetWindow(lexicon, Wordbook())
pet._timer.stop()                      # 时间由我们说了算
pet.start_capture = lambda *a, **k: None
pet.bubble.hide_now()

report = []
total_px = [0, 0]


def run(frames, dt=1 / 60.0):
    for _ in range(frames):
        pet._last = clock.t
        clock.t += dt
        pet._tick()
        time.sleep(1 / 300.0)          # 让 Qt 处理重绘


def shot(name):
    # 一路：控件自抓（含透明通道）。取消 setMask 之后，窗口不再有任何
    # 操作系统级裁剪，QPainter 画了什么就显示什么 —— 所以这一张就是
    # 屏幕上的最终像素，且不受其他窗口干扰，是最可靠的判据。
    own = pet.grab()
    own_path = os.path.join(OUT, "own_%s.png" % name)
    own.save(own_path)

    # 二路：整屏抓拍（看它在真实桌面上的合成效果）
    screen = QGuiApplication.screenAt(pet.center) or QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio()
    cx, cy = pet.center.x() * dpr, pet.center.y() * dpr
    half_w, half_h = 400 * dpr, 330 * dpr
    rect = QRect(int(cx - half_w), int(cy - half_h),
                 int(half_w * 2), int(half_h * 2))
    rect = rect.intersected(QRect(0, 0, screen.geometry().width() * dpr, 10 ** 9))
    screen.grabWindow(0).copy(rect).save(os.path.join(OUT, "screen_%s.png" % name))

    # 覆盖率：自抓图里有多少像素是真的有内容的
    image = own.toImage()
    solid = counted = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            counted += 1
            if image.pixelColor(x, y).alpha() > 24:
                solid += 1
    report.append(name)
    total_px[0] += solid
    total_px[1] += counted
    worst = max(math.hypot(L.tip[0] - L.hip_pos[0], L.tip[1] - L.hip_pos[1]) / L.full
                for L in pet.spider.legs)
    print("[shot] %-14s mode=%-5s heading=%6.1f°  实心 %4.1f%%  伸展峰值 %.2f×腿长  → %s"
          % (name, pet.spider.mode, math.degrees(pet.spider.heading) % 360,
             solid * 100.0 / max(counted, 1), worst, os.path.basename(own_path)),
          flush=True)


def place():
    screen = pet._screen_rect()
    pet.center = QPoint(screen.right() - 320, screen.bottom() - 300)
    pet._apply_geometry(resize=True)


print("抓拍中 ...", flush=True)

place()
run(90)
shot("idle")

# 这一趟约 220px：不显式指定 `force_jump` 的话，会按 `locomotion.walk_jump_threshold()`
# （真机 ≈259px）判走；这里点名 force_jump，免得以后阈值调小后抓拍变成跳跃，抓不到步态
pet.travel_to(pet.center + QPoint(-200, -90), force_jump=False)
run(20)
shot("walking")
run(20)
shot("walking2")

pet.travel_to(pet.center + QPoint(520, 230), force_jump=True)
run(14)
shot("airborne")
run(60)
shot("landed")

pet.play("jump")
run(5)
shot("effect_jump")
pet.effect = None
run(30)

pet.play("shake")
run(4)
shot("effect_shake")
pet.effect = None
run(30)

pet._set_state("think")
unit = pet.unit
pet.spider.place_targets(
    [(150.0 / unit, 80.0 / unit), (60.0 / unit, 150.0 / unit),
     (-120.0 / unit, 90.0 / unit), (-160.0 / unit, -40.0 / unit),
     (-90.0 / unit, -150.0 / unit), (40.0 / unit, -160.0 / unit),
     (130.0 / unit, -110.0 / unit), (170.0 / unit, 10.0 / unit)])
run(70)
shot("aim")

print("\n完成，共 %d 张：%s" % (len(report), ", ".join(report)))
print("整体实心像素占比 %.1f%%（窗口 %dx%d）"
      % (total_px[0] * 100.0 / max(total_px[1], 1), pet.width(), pet.height()))
print("输出：%s" % OUT)
