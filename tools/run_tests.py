# -*- coding: utf-8 -*-
"""跑一遍全部自检 —— 一条命令出一张验收表。

用法：：

    python tools/run_tests.py            # 全跑
    python tools/run_tests.py --quick    # 只跑不涉及真实识词/图形的那部分

为什么要有它
------------
项目里的自检脚本是各自 Evolve 出来的：`test/*.py` 里既有 unittest
（"OK"），也有自己写的计数打印（"通过 N / 失败 0"），还有纯叙述式输出。
以前靠人眼看尾巴决定是否通过，容易漏。这里统一判断：

- **优先看退出码**（脚本自己判定完会给出非 0）；
- 退出码缺失的，退回模式匹配（`OK` / `通过 N / 失败 0` / `PASS`）；
- 只要输出里出现 ``Traceback`` 或 ``FAIL`` 字样，一律记为 FAIL 并把尾巴打出来。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TESTS = [
    ("词典·基础", "test/test_ai.py"),
    ("AI 人设/四六级引导", "test/test_persona.py"),
    ("AI 配置/密钥安全", "test/test_ai_config.py"),
    ("瞄准按压", "test/test_aim_hold.py"),
    ("点击穿透", "test/test_click_through.py"),
    ("折叠动画", "test/test_fold.py"),
    ("逐腿折叠+身体收拢", "test/test_leg_fold_assignment.py"),
    ("行业词库", "test/test_industry.py"),
    ("腿部伸展", "test/test_leg_stretch.py"),
    ("步态不变量（脚钉住/头前导）", "test/test_locomotion.py"),
    ("OCR 坐标", "test/test_ocr_coords.py"),
    ("覆盖层只亮框", "test/test_overlay_box_only.py"),
    ("走/跳阈值滞回", "test/test_walk_jump.py"),
    ("OCR 引擎注册表", "test/test_ocr_registry.py"),
    ("复习会话调度", "test/test_review_session.py"),
    ("连续扫词队列", "test/test_scan_queue.py"),
    ("超八腿身体走路径", "test/test_path_walk.py"),
    # 2026-10-18 新增（任务书 §2.2 / §4 / §5 / §6 / §7）
    ("收藏夹五分类", "test/test_favorites.py"),
    ("桌宠生命周期", "test/test_app_lifecycle.py"),
    ("学习日历与成就", "test/test_activity.py"),
    ("导出日历 PNG", "test/test_calendar_export.py"),
    ("开机自启动", "test/test_autostart.py"),
    ("展示区图层不透明度", "test/test_jar_stage.py"),
    ("主题令牌与外部调参", "test/test_theme.py"),
    ("背会提示音", "test/test_sfx.py"),
    ("打包瘦身守卫", "test/test_packaging.py"),
    ("皮肤渲染", "test/test_skin.py"),
    ("蜘蛛几何", "test/test_spider.py"),
    ("原地转身", "test/test_spin.py"),
    ("线程 OCR", "test/test_thread_ocr.py"),
    ("词框贴合", "test/test_word_box_fit.py"),
]

TOOLS = [
    ("QML 启动台冒烟", "tools/qml_smoke.py"),
    ("QML 桥接自检", "tools/qml_bridge_probe.py"),
    ("UI 自检（背单词/AI/引擎/帮助）", "tools/ui_probe.py"),
]

QUICK_SKIP = {"test/test_ocr_coords.py", "test/test_thread_ocr.py",
              "test/test_word_box_fit.py", "test/test_skin.py"}


def python() -> str:
    """挑解释器：优先项目虚拟环境（OCR 依赖只在那里）。"""
    venv = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if os.path.isfile(venv):
        return venv
    return sys.executable


#: 输出里只要出现这些，就说明脚本自己判了失败
_FAIL_MARKS = ("[FAIL]", "FAILED (", "ui-probe] FAIL",
               "Traceback (most recent call last)")
#: 认这些就算自己在说“过了”
_PASS_MARKS = ("OK", "失败 0", "PASS", "全部通过", "✓")


def judge(returncode: int, text: str) -> tuple:
    """判定单个脚本的结果，返回 ``(ok, 说明)``。

    退出码是**第一依据**：这些脚本都会在自己判失败时给非 0。
    文本匹配只作为「退出码为 0 但里面有失败痕迹」的二次校验 ——
    避免出现「日志里打了 traceback 但退出码还是 0」被当成通过。
    """
    tail = text[-2000:]
    if returncode != 0:
        return False, "退出码 %d" % returncode
    for mark in _FAIL_MARKS:
        if mark in tail:
            return False, "输出里出现 %r" % mark
    if not any(mark in tail for mark in _PASS_MARKS):
        return True, "退出码 0（脚本未自报，可能是纯叙述式输出）"
    return True, ""


def run(name: str, rel: str) -> tuple:
    proc = subprocess.run([python(), rel], cwd=ROOT,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    text = (proc.stdout or "") + (proc.stderr or "")
    ok, note = judge(proc.returncode, text)
    return ok, note, text


def main() -> int:
    # GBK 控制台下 `test_spider.py` / `test_thread_ocr.py` 的 print 会崩成
    # exit 1（既有现象，非功能回归）—— 子进程继承这里设好的 UTF-8 就不会。
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true",
                        help="跳过依赖真实识词/图形渲染的用例")
    args = parser.parse_args()

    print("解释器：%s" % python())
    print("-" * 72)
    results = []
    for name, rel in TESTS + TOOLS:
        if args.quick and rel in QUICK_SKIP:
            print("[跳过] %-38s %s" % (name, rel))
            continue
        ok, note, text = run(name, rel)
        results.append((ok, name, rel, text))
        # flush：这个脚本常被 `| tail` 或 CI 日志管道接走，
        # 不 flush 的话管道里是块缓冲，跑完才吐——中途卡住就完全看不到进度。
        print("[%s] %-38s %s%s" % ("ok" if ok else "FAIL", name, rel,
                                   ("　← " + note) if note else ""), flush=True)

    print("-" * 72)
    failed = [r for r in results if not r[0]]
    if failed:
        print("以下 %d 项未通过，输出尾巴如下：" % len(failed))
        for _, name, rel, text in failed:
            print("\n===== %s (%s) =====" % (name, rel))
            print("\n".join(text.strip().splitlines()[-25:]))
        return 1
    print("全部通过：%d 项" % len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
