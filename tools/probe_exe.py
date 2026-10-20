# -*- coding: utf-8 -*-
"""启动打包好的 exe，等它起来后截图，再关掉 —— 用来验证「双击能不能用」。"""
import os
import subprocess
import sys
import time

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QGuiApplication

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(BASE, "dist", "Lexara.exe")
OUT = os.path.join(BASE, "dist", "selftest", "exe_probe.png")

app = QApplication(sys.argv)

print("启动:", EXE, os.path.exists(EXE))
t0 = time.time()
proc = subprocess.Popen([EXE], cwd=os.path.join(BASE, "dist"))
print("pid =", proc.pid)

# 首次启动要解压运行库（内含 64MB 词典）
for stage in range(1, 13):
    time.sleep(3)
    alive = proc.poll() is None
    print("  +%2ds  进程存活=%s  累计=%.0fs" % (stage * 3, alive, time.time() - t0))
    if not alive:
        print("!! exe 提前退出，返回码 =", proc.returncode)
        break

if proc.poll() is None:
    screen = QGuiApplication.primaryScreen()
    pixmap = screen.grabWindow(0)
    pixmap.save(OUT)
    print("截图:", OUT, pixmap.width(), pixmap.height())

    # 只截右下角（蜘蛛应该在那里）
    crop = pixmap.copy(int(pixmap.width() - 620), int(pixmap.height() - 560), 620, 560)
    crop.save(os.path.join(BASE, "dist", "selftest", "exe_probe_pet.png"))
    print("裁剪:", os.path.join(BASE, "dist", "selftest", "exe_probe_pet.png"))

    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("已关闭 exe")
else:
    print("exe 未能保持运行")
