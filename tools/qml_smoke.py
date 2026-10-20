# -*- coding: utf-8 -*-
"""QML 启动台冒烟测试（build_exe.bat 第 7 步）。

拉起真实 QML 启动台（复用主入口 main），验证三件事后自动退出：
1. Main.qml 加载成功（有 root object）；
2. 设置弹层能打开（SettingsSheet 走隐藏控制器的真实代码路径）；
3. AI 输入的"诚实提示"与状态机可读。

退出码 0 = 全过；非 0 = 打包中止。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

env = dict(os.environ, LEXARA_QML_TEST="1")
env.pop("LEXARA_QML_SHOT", None)
result = subprocess.run([PY, os.path.join(ROOT, "src", "main.py")],
                        capture_output=True, text=True, env=env,
                        encoding="utf-8", errors="replace", timeout=120,
                        cwd=ROOT)
out = (result.stdout or "") + (result.stderr or "")
print(out[-1200:] if len(out) > 1200 else out)

ok = ("设置弹层打开=True" in out and "notice=" in out
      and "portal校验=True" in out
      and "Main.qml 加载失败" not in out)
print("[qml-smoke] %s" % ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
