# -*- coding: utf-8 -*-
"""一个测试文件一个进程地跑完整回归。

为什么不用 `python -m unittest discover`
----------------------------------------
这些测试里有三种「进程级副作用」，同进程混跑必然互相污染：

1. `test_fold / test_click_through / test_aim_hold / test_leg_stretch`
   在 **import 期** 就 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`。
   `discover` 是先把所有模块 import 完再执行用例的，于是
   `test_ai` 里那张真 OCR 图会在 offscreen 下渲染 —— 没有可用字体库，
   文字画得出来但 OCR 读不出，结果是 `words == []`（假失败）。
2. `QApplication` 是进程单例：`test_word_box_fit` 在 import 期建一个，
   别的用例又建一个 → `libshiboken: Please destroy the QApplication
   singleton before creating a new QApplication instance.`
3. OCR 引擎（RapidOCR 的 ONNX session）与各测试自己的 monkeypatch 共享
   同一个模块状态，跑序不同结论不同。

所以这里只做一件事：给每个文件起一个干净的子进程，收退出码和摘要。
用法：``python test/run_all.py``（或 ``--only ai,word_box``）。
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DIR = os.path.join(BASE, "test")
TOOLS_DIR = os.path.join(BASE, "tools")

#: 每个文件超时（秒）。OCR 相关的实测 3~25s，留足余量。
TIMEOUT = 600

#: (标签, 相对路径, 判定成功的方式)
#:  - ``unittest``：unittest 用例，看退出码 + `Ran N tests`
#:  - ``script``  ：脚本式断言，看退出码 + 「通过 N / 失败 M」或 ``[ok]`` 计数
CASES = [
    ("spider 步态/IK", "test/test_spider.py", "script"),
    ("步态不变量：脚钉住 + 头前导（§4）", "test/test_locomotion.py", "script"),
    ("走/跳阈值与滞回（§3）", "test/test_walk_jump.py", "script"),
    ("跳跃状态机 + 身体形变（§9.2）", "test/test_jump_motion.py", "script"),
    ("腿长倍率", "test/test_leg_stretch.py", "script"),
    ("折叠（无腿模式）", "test/test_fold.py", "script"),
    ("逐腿折叠 + 身体向头部收拢（§6 §7）",
     "test/test_leg_fold_assignment.py", "script"),
    ("转圈姿态", "test/test_spin.py", "script"),
    ("皮肤资源", "test/test_skin.py", "script"),
    ("点击穿透", "test/test_click_through.py", "script"),
    ("连续扫词队列（§6）", "test/test_scan_queue.py", "unittest"),
    ("超八腿：身体走完整条路径（§8）", "test/test_path_walk.py", "script"),
    ("瞄准层保持", "test/test_aim_hold.py", "script"),
    ("OCR 坐标换算", "test/test_ocr_coords.py", "script"),
    ("词框贴合（§4）", "test/test_word_box_fit.py", "script"),
    ("覆盖层只亮框不重画词（§5）", "test/test_overlay_box_only.py", "script"),
    ("词典行业标签", "test/test_industry.py", "script"),
    ("复习会话", "test/test_review_session.py", "unittest"),
    # 背单词卡片的 AI 辅助（造句 / 同义词）：提示词口径 + 状态机 + 缓存/作废。
    # 一次网络都不发，worker 是注入的假实现。
    ("背单词 AI 辅助（造句/同义词）", "test/test_study_help.py", "unittest"),
    # 默写判分：纯函数，守的是「拼写对就不算错」的口径（大小写/标点/连字符）。
    ("默写单词判分", "test/test_spell_check.py", "unittest"),
    # 2026-10-18 新增（任务书 §2.2 / §4 / §5 / §6 / §7）：
    # 收藏夹分类统计、桌宠生命周期幂等、日历/成就口径、导出 PNG、开机自启动。
    ("收藏夹五分类与兜底（§2.2）", "test/test_favorites.py", "unittest"),
    ("桌宠生命周期：部署/收回/自动部署（§4 §6）", "test/test_app_lifecycle.py", "unittest"),
    ("学习日历与成就（§7）", "test/test_activity.py", "unittest"),
    ("导出学习日历 PNG（§7.4）", "test/test_calendar_export.py", "unittest"),
    ("开机自启动（§5）", "test/test_autostart.py", "unittest"),
    ("展示区图层不透明度（§2.4）", "test/test_jar_stage.py", "unittest"),
    # 主题令牌体系（外部调参）：令牌自洽 / @引用 / 校验 / 原子写 / 热重载 / CLI。
    # 顺带守住「QML 里不许再写死颜色」和「tv[] 的键必须存在」两条。
    ("主题令牌与外部调参", "test/test_theme.py", "unittest"),
    ("背会提示音（§2.6）", "test/test_sfx.py", "unittest"),
    # 打包瘦身：spec 必须剔除 cv2 的 FFmpeg 视频插件（29MB），但**不许**排除 cv2
    # 本身（RapidOCR 硬依赖）。体积体检工具在 tools/package_size_audit.py。
    ("打包瘦身与体积守卫", "test/test_packaging.py", "unittest"),
    ("后台 OCR 线程", "test/test_thread_ocr.py", "script"),
    ("AI：本地先行 + 按需云端（§5）", "test/test_ai.py", "unittest"),
    # 人设（persona）：三个出网点共用一份提示词，且「无论问什么都要收在英语上」
    # + 四六级事实表锁死。防止以后有人在某个调用点又自己拼一份提示词。
    ("AI 人设与四六级引导", "test/test_persona.py", "unittest"),
    ("结果卡按需 AI 探针（§5）", "tools/result_card_probe.py", "script"),
    ("感应调度核心（§7）", "test/test_sense_session.py", "unittest"),
    ("感应后台线程（§7）", "test/test_sense_worker.py", "unittest"),
    ("感应覆盖层（§7）", "test/test_sense_overlay.py", "script"),
    ("感应实测：捕获/OCR 延迟与开销（§7.4）", "tools/sense_bench.py", "script"),
    ("端到端：框选→踩词→结果卡", "tools/aim_e2e.py", "script"),
    ("运动对照图 + 像素朝向断言（§4 §8）", "tools/locomotion_sheet.py", "script"),
    ("端到端：桌面感应→提示→释义（§7.4）", "tools/sense_e2e.py", "script"),
]

_PASS = re.compile(r"^Ran (\d+) test", re.M)
_FAILED = re.compile(r"^(FAILED|ERROR:)", re.M)
_PAIR = re.compile(r"通过\s*(\d+)\s*/\s*失败\s*(\d+)")
_ALL_OK = re.compile(r"全部通过：(\d+)")
_OK = re.compile(r"\[ok\]", re.I)
_X = re.compile(r"\[(?:x|FAIL|✗)\]", re.I)


def run_one(label: str, rel: str, mode: str) -> dict:
    path = os.path.join(BASE, rel)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, path], cwd=BASE, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=TIMEOUT)
        out = proc.stdout.decode("utf-8", errors="replace")
        code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as error:
        out = (error.stdout or b"").decode("utf-8", errors="replace")
        code, timed_out = -9, True
    elapsed = time.time() - started

    counted, failed = None, 0
    if mode == "unittest":
        match = _PASS.search(out)
        counted = int(match.group(1)) if match else 0
        passed = (code == 0 and not timed_out and _FAILED.search(out) is None
                  and counted > 0)
    else:
        pair = _PAIR.search(out)
        all_ok = _ALL_OK.search(out)
        if pair:
            counted, failed = int(pair.group(1)) + int(pair.group(2)), \
                int(pair.group(2))
        elif all_ok:
            counted, failed = int(all_ok.group(1)), len(_X.findall(out))
        else:
            ok, bad = len(_OK.findall(out)), len(_X.findall(out))
            counted, failed = (ok + bad if ok or bad else None), bad
        passed = code == 0 and not timed_out and failed == 0

    tail = "\n".join(out.strip().splitlines()[-12:])
    return {"label": label, "file": rel, "mode": mode, "code": code,
            "elapsed": elapsed, "passed": passed, "counted": counted,
            "output": out, "tail": tail}


def main(argv) -> int:
    only = None
    if "--only" in argv:
        only = [part.strip() for part in
                argv[argv.index("--only") + 1].split(",") if part.strip()]
    cases = CASES
    if only:
        cases = [case for case in CASES
                 if any(token in case[0] or token in case[1] for token in only)]

    # 串行跑：这些用例都会开真实窗口/OCR，并行会把 CPU 抢成一团糊。
    results = [run_one(*case) for case in cases]

    print("\n" + "=" * 68)
    print("LEXARA 回归结果（每个文件独立进程）")
    print("=" * 68)
    failures = []
    for result in results:
        mark = "[OK]  " if result["passed"] else "[FAIL]"
        print("%s %-34s %-28s %-6s %5.1fs (exit=%d)"
              % (mark, result["label"], result["file"],
                 "-" if result["counted"] is None
                 else "%d 项" % result["counted"],
                 result["elapsed"], result["code"]))
        if not result["passed"]:
            failures.append(result)
    total = sum(r["counted"] or 0 for r in results)
    print("-" * 68)
    print("文件 %d 个通过 / %d，累计检查项 %d"
          % (len(results) - len(failures), len(results), total))
    for result in failures:
        print("\n--- %s (%s) 末尾输出 ---\n%s"
              % (result["file"], result["label"], result["tail"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
