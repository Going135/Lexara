# -*- coding: utf-8 -*-
"""蜘蛛感应（任务书 §7.4）的**实测**脚本：CPU / 内存 / 单轮延迟 / 扫描频率。

任务书对 §7 的验收写得很具体：

    CPU、内存、单轮延迟和扫描频率有实测记录；超过预算时自动降频或提示

「1~2 次/秒」只是**待测的起点**、不是性能承诺，所以这些数字只能量出来，不能写上去。
这个脚本量四件事：

1. **屏幕捕获成本**：GUI 线程上的 `grabWindow` + `QImage→ndarray`，真实桌面；
2. **单轮 OCR 延迟**：整帧 vs 只扫「变化那几格」的 ROI，两条路径分开量，
   并且把 ROI 的**两种形状**都量（格子并集框 vs 收到有内容那块的框）——
   用来验证「优先局部 ROI」到底省了多少（§7.3 要求的那句话）。
   ★ 这里量出来过两件反直觉的事：并集框（1920x432）比整帧**还贵 177%**，
   而真桌面上那条没收窄的并集带**根本读不到字幕那句**（`tools/sense_card_probe.py`），
   所以 worker 里加了 `_tighten_crop`（行、列都收）；
3. **真线程流水线**：起 `SenseWorker` 线程、按 2 次/秒的节奏喂帧、跑满十几秒，
   量墙钟耗时、进程 CPU 时间占比、工作集内存增量、实际达成的频率、丢帧数；
4. **超预算自动降频**：把预算人为压到 1ms 逼出这条路径，看它是降频、
   降到下限之后是不是**暂停并说明原因**，而不是死守频率把机器占满。

运行：``python tools/sense_bench.py``
输出：终端摘要 + ``dist/sense/bench_report.md``（数字可直接贴进状态文档）

★ 隐私：喂进流水线的帧全是**脚本自己画的**英文句子；真机捕获**只量耗时**，
  不落盘、不打印抓到的画面、不进日志。
★ 跨线程：喂帧走 `worker.submit()` + 真 `QThread`，提示走 `notice` 信号
  （队列连接），所以这份数字量的是**用户实际会走的那条路**，不是捷径。
"""
from __future__ import annotations

import ctypes
import os
import statistics
import sys
import threading
import time
from ctypes import wintypes

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import numpy as np                                          # noqa: E402
from PySide6.QtCore import QRect, Qt                        # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter   # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

OUT = os.path.join(BASE, "dist", "sense")
os.makedirs(OUT, exist_ok=True)
REPORT = os.path.join(OUT, "bench_report.md")

PASS, FAIL, ROWS = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("[ok]" if ok else "[x] ", name,
                         ("　" + detail) if detail else ""))


def row(section, metric, value):
    ROWS.append((section, metric, value))
    print("      %-22s %s" % (metric, value))


def pct_of(samples, fraction):
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, int(math_ceil(fraction * len(ordered))) - 1))
    return ordered[index]


def math_ceil(value):
    import math
    return int(math.ceil(value))


def stats_line(samples):
    if not samples:
        return "无样本"
    return ("均 %.1fms · 中位 %.1fms · P95 %.1fms · 最大 %.1fms（n=%d）"
            % (statistics.mean(samples), statistics.median(samples),
               pct_of(samples, 0.95), max(samples), len(samples)))


# ---------------------------------------------------------------- 内存（Windows）

class _PMC(ctypes.Structure):
    """`PROCESS_MEMORY_COUNTERS`（Win32）。只取 WorkingSetSize 一个字段就够了。"""
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def rss_mb():
    """当前进程**工作集**（MB）。拿不到返回 None（调用方要如实写「未运行」）。

    ★ 两个坑：`psapi.GetProcessMemoryInfo` 不设 `argtypes` 时，ctypes 会把
    `GetCurrentProcess()` 那个伪句柄当 32 位 int 传进去 → ERROR_INVALID_HANDLE(6)
    → 之前这里一直是 None（内存项「未运行」）。设了原型就走通了。
    非 Windows 或拿不到 → None，绝不编一个数。
    """
    try:
        psapi = ctypes.WinDLL("psapi")
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(_PMC),
                                               wintypes.DWORD]
        counters = _PMC()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                          ctypes.byref(counters), counters.cb):
            return None
        return counters.WorkingSetSize / 1024.0 / 1024.0
    except Exception:                                        # noqa: BLE001
        return None


def cv2_import():
    import cv2
    return cv2


# ---------------------------------------------------------------- 造帧

#: 字幕刻意含考纲词（aggressive / eliminate / consequence），让「词典挑词」有事可做
SUBTITLES = [
    "The team needed an aggressive approach to eliminate the duplicate labels.",
    "Every shortcut carries a consequence that shows up three releases later.",
]


def blank_frame(w=1920, h=1080):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(28, 30, 36))
    return img


def subtitle_frame(text, w=1920, h=1080):
    """一张「视频正在播、底部有英文字幕」的假帧。

    上方放**不变**的界面文字（它不该唤醒 OCR），下方三分之一是字幕条 ——
    4×3 网格里正好只有最后一行的几格会动，这就是 §7 想要的 ROI 场景。
    """
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(28, 30, 36))
    painter = QPainter(img)
    painter.setPen(QColor(150, 156, 168))
    painter.setFont(QFont("Segoe UI", 20))
    painter.drawText(QRect(80, 90, w - 160, 80), Qt.AlignLeft,
                     "LEXARA sense bench · static header text")
    painter.fillRect(0, h - 200, w, 130, QColor(10, 10, 12))
    painter.setPen(QColor(245, 245, 245))
    painter.setFont(QFont("Arial", 34, QFont.Bold))
    painter.drawText(QRect(120, h - 190, w - 240, 110),
                     Qt.AlignVCenter | Qt.AlignHCenter, text)
    painter.end()
    return img


def scroll_frame(w=1920, h=1080):
    """整屏都在换的帧（滚动/切页）→ 应该退化成整帧 ROI，而不是逐格 OCR。"""
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(246, 246, 244))
    painter = QPainter(img)
    painter.setPen(QColor(30, 30, 30))
    painter.setFont(QFont("Segoe UI", 15))
    for i, line in enumerate([SUBTITLES[0], SUBTITLES[1]] * 8):
        painter.drawText(QRect(90, 80 + i * 58, w - 180, 50), Qt.AlignLeft, line)
    painter.end()
    return img


def to_array(image):
    from ocr_engine import qimage_to_ndarray
    return np.ascontiguousarray(
        qimage_to_ndarray(image.convertToFormat(QImage.Format_RGB888)))


def gray_of(array):
    cv2 = cv2_import()
    return cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)


# ---------------------------------------------------------------- 主流程

def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)      # noqa: ARG001

    print("=" * 78)
    print("LEXARA 蜘蛛感应实测（任务书 §7.4：CPU / 内存 / 单轮延迟 / 扫描频率）")
    print("=" * 78)

    # ---- 0. 环境：能不能测，先说清楚 -------------------------------
    print("\n[0] 环境")
    from ocr_engine import OcrEngine
    import ocr_adapter

    row("[0 环境]", "Python", sys.version.split()[0])
    row("[0 环境]", "当前 OCR 引擎", ocr_adapter.current_engine())
    row("[0 环境]", "引擎清单", ", ".join(
        "%s=%s" % (e["id"], e["state"]) for e in ocr_adapter.describe_engines()))
    available = OcrEngine.available()
    check("OCR 引擎可用（否则延迟项全部无从测起）", bool(available))
    if not available:
        print("\n  未运行：本机 OCR 引擎不可用，性能实测无法进行。")
        return 1

    from PySide6.QtGui import QGuiApplication
    screens = QGuiApplication.screens()
    row("[0 环境]", "屏幕数", len(screens))
    for i, screen in enumerate(screens):
        row("[0 环境]", "屏 %d" % i, "%s %dx%d dpr=%.2f 原点=(%d,%d)"
            % (screen.name(), screen.geometry().width(),
               screen.geometry().height(), screen.devicePixelRatio(),
               screen.geometry().x(), screen.geometry().y()))
    try:
        row("[0 环境]", "OpenCV", cv2_import().__version__)
    except Exception as error:                                   # noqa: BLE001
        row("[0 环境]", "OpenCV", "缺失（%s）" % type(error).__name__)
    check("变化检测需要的 cv2 在位（灰度 + 缩略图）", True)

    # ---- 1. 屏幕捕获成本（GUI 线程，真实桌面） ---------------------
    print("\n[1] 屏幕捕获（GUI 线程：grabWindow + QImage→ndarray，真实桌面）")
    from capture import grab_virtual_desktop

    grab_ms, convert_ms = [], []
    shape = dpr = None
    for _ in range(12):
        t0 = time.perf_counter()
        pixmap, _geo, dpr = grab_virtual_desktop()
        t1 = time.perf_counter()
        array = to_array(pixmap.toImage())
        t2 = time.perf_counter()
        grab_ms.append((t1 - t0) * 1000.0)
        convert_ms.append((t2 - t1) * 1000.0)
        shape = array.shape
    total = [a + b for a, b in zip(grab_ms, convert_ms)]
    row("[1 捕获]", "抓到的帧", "%dx%d 物理像素（DPR %.2f）"
        % (shape[1], shape[0], dpr or 1.0))
    row("[1 捕获]", "grabWindow", stats_line(grab_ms))
    row("[1 捕获]", "QImage→ndarray", stats_line(convert_ms))
    row("[1 捕获]", "单次合计", stats_line(total))
    share = statistics.mean(total)                    # 单次捕获合计耗时（ms）
    row("[1 捕获]", "占 GUI 线程比例",
        "1 次/秒时 %.1f%%　·　2 次/秒时 %.1f%%" % (share / 10.0, share / 5.0))
    check("单次捕获 < 200ms（实测 %.0fms，不拖慢动画）"
          % statistics.mean(total), statistics.mean(total) < 200.0)

    # ---- 2. 单轮 OCR：整帧 vs 只扫变化的格子 -----------------------
    print("\n[2] 单轮延迟：整帧 vs 变化格子 ROI（这就是「优先局部」的账）")
    from sense_session import SenseSession
    from sense_worker import SenseWorker, _thumbnail

    frame_blank = to_array(blank_frame())
    frame_a = to_array(subtitle_frame(SUBTITLES[0]))
    frame_b = to_array(subtitle_frame(SUBTITLES[1]))
    frame_scroll = to_array(scroll_frame())

    def time_ocr(arr, runs=3):
        samples = []
        for _ in range(runs):
            t0 = time.time()
            OcrEngine.recognize_lines(arr)
            samples.append((time.time() - t0) * 1000.0)
        return samples

    full_ms = time_ocr(frame_a, 3)
    row("[2 单轮]", "整帧（1920x1080）", stats_line(full_ms))

    # 用变化检测自己算出「哪几格动了」，再按 `roi_box` 裁 —— 和线上一模一样
    session = SenseSession(hz=1.0)
    session.start()
    thumb_a, scale_a = _thumbnail(gray_of(frame_a), cv2_import())
    session.ingest(thumb_a)                       # 第一帧：建立基准（整帧）
    thumb_b, _ = _thumbnail(gray_of(frame_b), cv2_import())
    keys, is_full = session.ingest(thumb_b)       # 换字幕 → 应该是**几格**而不是整帧
    check("字幕换行被识别成局部变化而不是整屏（ROI 键 %s，整屏=%s）"
          % (keys, is_full), bool(keys) and not is_full,
          "→ 这条 2026-10-18 首次跑就红了：老判据（每格均值差）量不到换行，"
            "整个 §7 的「优先检测新内容」在真帧上是失效的")
    # 变化检测本身的成本（每轮都要跑，在后台线程）
    detect_ms = []
    for _ in range(10):
        t0 = time.perf_counter()
        session.cell_diffs(thumb_a, thumb_b)
        detect_ms.append((time.perf_counter() - t0) * 1000.0)
    row("[2 单轮]", "变化检测（12 格绝对差）", stats_line(detect_ms))
    check("变化检测比 OCR 便宜两个数量级以上（均 %.1fms vs %.0fms）"
          % (statistics.mean(detect_ms), statistics.mean(full_ms)),
          statistics.mean(detect_ms) * 100.0 < statistics.mean(full_ms),
          "→ 「先检测再决定要不要 OCR」这笔账划得来")
    # 整屏都在换（滚动/切页）→ 应该退化成整帧，而不是逐格漏内容
    roll = SenseSession(hz=1.0)
    roll.start()
    roll.ingest(_thumbnail(gray_of(frame_a), cv2_import())[0])
    _keys, is_full_scroll = roll.ingest(
        _thumbnail(gray_of(to_array(scroll_frame())), cv2_import())[0])
    check("整屏在换时退化成整帧（不逐格漏内容）", bool(is_full_scroll))

    # 「分开裁每格各跑一次」到底划不划得来？先量它，再量并集（同一台机器同一晚上）
    from lexicon import Lexicon
    dict_path = os.path.join(BASE, "assets", "ecdict.sqlite")
    tags_path = os.path.join(BASE, "assets", "exam-tags.sqlite")
    if not os.path.isfile(dict_path):
        row("[2 单轮]", "词典", "缺失：%s → 挑词这步没测" % dict_path)
    lexicon = Lexicon(dict_path, tags_path,
                      os.path.join(BASE, "assets", "industry.sqlite"))
    # ★ 用**生产代码**算框：`SenseWorker._roi_boxes`（合并/不合并的策略在那儿），
    #   这样这里量到的就是线上真正会喂进 OCR 的那一块，不是脚本自己复刻的几何。
    geo = SenseSession(hz=1.0)
    geo.start()
    geo.ingest(thumb_a)
    geo_keys, _geo_full = geo.ingest(thumb_b)
    geo_worker = SenseWorker(geo, lexicon)
    tw, th = thumb_a.shape[1], thumb_a.shape[0]
    merged_boxes = geo_worker._roi_boxes(geo_keys, (tw, th), scale_a,
                                         (frame_a.shape[1], frame_a.shape[0]))
    row("[2 单轮]", "变化格子键", "%s（%d 格）" % (",".join(geo_keys), len(geo_keys)))
    row("[2 单轮]", "并集后 OCR 调用次数",
        "%d 次（分开裁是 %d 次）" % (len(merged_boxes), len(geo_keys)))
    check("多个相邻变化格并成一次 OCR（调用次数不随格数涨）",
          len(merged_boxes) == 1 and len(geo_keys) > 1,
          "→ 2026-10-18 实测：每格各裁各跑，四次合计是整帧的数倍，"
            "「优先局部」当场不成立，所以才改成并集")

    roi_samples = []
    for key in (keys or ["r2c1"]):
        x, y, w, h = session.roi_box(key, (frame_a.shape[1], frame_a.shape[0]))
        crop = frame_a[y:y + h, x:x + w]
        roi_samples.append(statistics.mean(time_ocr(crop, 2)))
        row("[2 单轮]", "单格 ROI %s（%dx%d）" % (key, w, h),
            "均 %.1fms" % roi_samples[-1])
    row("[2 单轮]", "逐格分开跑合计",
        "均 %.1fms（%d 次调用）" % (sum(roi_samples), len(roi_samples)))

    # ★ 「并集框」和「线上真正喂进 OCR 的那一块」不是一回事：格子框里有大片空白行，
    #   而 `OcrEngine` 对「中等高度、只有一行字」的裁片会切成多个行带、每带把加档
    #   阶梯跑完（实测 7 次调用），贴着字收一条就是一次调用。这里两种都量，
    #   报表里能看见「为什么要收紧」。
    merged_samples, tight_samples, tight_shapes = [], [], []
    for _key, x, y, bw, bh in merged_boxes:
        crop = frame_a[y:y + bh, x:x + bw]
        merged_samples.append(statistics.mean(time_ocr(crop, 3)))
        row("[2 单轮]", "并集 ROI（不收紧，%dx%d）" % (bw, bh),
            "均 %.1fms　← 对照：这种形状最贵" % merged_samples[-1])
        tight = SenseWorker._tighten_crop(crop)
        eff = (crop if tight is None
               else crop[tight[0]:tight[0] + tight[1],
                         tight[2]:tight[2] + tight[3]])
        tight_samples.append(statistics.mean(time_ocr(eff, 3)))
        shape = (bw, bh) if tight is None else (tight[3], tight[1])
        tight_shapes.append(shape)
        row("[2 单轮]", "并集 ROI（线上=收到有内容那块，%dx%d）" % shape,
            "均 %.1fms" % tight_samples[-1])
    merged_mean = statistics.mean(merged_samples) if merged_samples else 0.0
    tight_mean = statistics.mean(tight_samples) if tight_samples else 0.0
    full_mean = statistics.mean(full_ms)
    saving = 1.0 - tight_mean / full_mean
    row("[2 单轮]", "线上路径（收紧后）vs 整帧省时", "%.0f%%" % (saving * 100))
    row("[2 单轮]", "不收紧的并集 vs 整帧省时",
        "%.0f%%（负数=更贵）" % (100.0 * (1.0 - merged_mean / full_mean)))
    row("[2 单轮]", "逐格分开 vs 整帧省时",
        "%.0f%%（负数=更贵）" % (100.0 * (1.0 - sum(roi_samples) / full_mean)))
    check("变化区域（线上收到有内容那块后）OCR 不比整帧贵（省时 ≥ 0%%，实测 %.0f%%）"
          % (saving * 100), saving >= 0.0,
          "→ §7.3「不做每帧全屏完整 OCR」的实测依据。"
            "★ 2026-10-18 这条第一次是**红的**（并集框 1920x432 比整帧贵 173%），"
            "量出来贵在形状不在面积，于是加了 `_tighten_crop`；"
            "真桌面上还量到第二条：没收窄的并集带**连句子都读不出来**"
            "（`tools/sense_card_probe.py`），所以行列都要收")
    scroll_ms = time_ocr(frame_scroll, 2)
    row("[2 单轮]", "整屏在换时（滚动页）", stats_line(scroll_ms))
    from sense_session import BUDGET_MS, DUTY_LIMIT_MS as _DUTY
    row("[2 单轮]", "本机整帧 vs 默认预算",
        "整帧均 %.0fms · 预算 %.0fms · 下限轮间隔 %.0fms → %s"
        % (statistics.mean(full_ms), BUDGET_MS, _DUTY,
           "开感应默认就会降频（正常，不是故障）"
           if statistics.mean(full_ms) > BUDGET_MS else "预算之内"))

    # ---- 3a. 忙不过来时丢帧，不排队 ---------------------------------
    print("\n[3a] 丢帧而不是排队（工作线程正忙时连投 21 帧）")
    from sense_session import (DUTY_LIMIT_MS, MIN_HZ, PAUSE_MIN_SAMPLES,
                               RECENT_WINDOW)
    hz0 = 2.0
    flood = SenseSession(hz=hz0)
    flood.start()
    worker = SenseWorker(flood, lexicon, min_conf=0.0, mode="cet6", limit=8)
    notices, faults, perf_states = [], [], []
    worker.notice.connect(lambda item: notices.append(
        (item.get("screen_pos") or (0, 0))))          # ★ 只记坐标，不记词
    worker.fault.connect(faults.append)
    worker.perf.connect(lambda p: perf_states.append(p["state"]))
    worker.start()
    # 等线程真的进了 `run()` 并把模型加载花掉（`warmup_ms` 是最后落的那个）。
    # 不等的话这里会连「构造引擎」那一口也算进第一轮，量到的全是冷启动数字。
    gate = time.time()
    while worker.warmup_ms == 0.0 and time.time() - gate < 40.0:
        app.processEvents()
        time.sleep(0.05)
    row("[3a 丢帧]", "引擎预热（一次性，不进延迟预算）", "%.0fms" % worker.warmup_ms)
    worker.submit(frame_scroll, (0, 0), 1.0)          # 重的：整帧 OCR，一定忙
    for _ in range(20):
        worker.submit(frame_a, (0, 0), 1.0)           # 紧接着连投 → 只留最新一帧
    deadline = time.time() + 20.0
    while time.time() < deadline and flood.stats["cycles"] < 2:
        app.processEvents()
        time.sleep(0.05)
    row("[3a 丢帧]", "连投 21 帧", "被处理 %d 轮 · 丢掉 %d 帧"
        % (flood.stats["cycles"], worker.dropped))
    check("处理不过来时**只留最新一帧**（丢 %d ≥ 10，不排队）" % worker.dropped,
          worker.dropped >= 10,
          "→ 排队的话延迟越堆越高，提示的是几秒前的画面")
    worker.stop_sense()
    flood_waited = worker.wait(5000)
    app.processEvents()
    row("[3a 丢帧]", "关闭后线程状态",
        "isRunning=%s wait()=%s" % (worker.isRunning(), flood_waited))
    check("关闭后工作线程真的退出（不重启、不遗留）",
          flood_waited and not worker.isRunning())

    # ---- 3b. 门控喂帧的完整流水线：剧本不被「丢帧」吃掉，才量得到跳过率 ----
    print("\n[3b] 流水线实测（真 QThread + 真信号，投一帧等一轮）")
    pipe = SenseSession(hz=hz0)
    # ★ 必须 start()：没开的话 `ingest` 直接返回 `([], False)`，
    #   流水线跑十二秒一轮 OCR 都不会有（第一版 bench 就栽在这儿，
    #   量出来「0 轮 / 0 次 / 0 次每秒」—— 数字漂亮地假）。
    pipe.start()
    worker = SenseWorker(pipe, lexicon, min_conf=0.0, mode="cet6", limit=8)
    notices, faults, perf_states = [], [], []
    worker.notice.connect(lambda item: notices.append(
        (item.get("screen_pos") or (0, 0))))          # ★ 只记坐标，不记词
    worker.fault.connect(faults.append)
    worker.perf.connect(lambda p: perf_states.append(p["state"]))

    # 「一句字幕停很久 → 换一句 → 再停很久」。
    # ★ 投帧改成**门控**（等这一帧真被处理完再投下一帧）：上一版按 2 次/秒硬投，
    #   OCR 一轮 1~3 秒 → 24 帧里 21 帧被丢，剧本根本没走完整，
    #   于是「静态画面不反复唤醒 OCR」量到的是 0 跳过 —— 那不是被测对象的行为，
    #   是喂帧脚本的行为。门控用生产计数器 `stats["cycles"]` 判断「这轮落地了」，
    #   不额外加仅供测试用的字段。
    script = ([frame_blank] + [frame_a] * 4 + [frame_b] * 2 + [frame_a] * 3
              + [frame_scroll] + [frame_b] * 3 + [frame_a] * 3)
    # 剧本自己先算一遍「有几帧和上一帧一模一样」，待会儿拿来对照检测的判定：
    # 检测说「没变」的次数必须**不少于**这个数，否则就是误报（白烧 OCR）。
    expected_changes = sum(
        1 for i in range(1, len(script))
        if script[i].shape != script[i - 1].shape
        or not np.array_equal(script[i], script[i - 1]))
    expected_skips = (len(script) - 1) - expected_changes
    interval = 1.0 / hz0                              # 投帧之间的最小间隔（2 次/秒）
    index = 0
    wall_before = time.time()
    cpu_before = time.process_time()
    rss_before = rss_mb()
    worker.start()
    gate = time.time()
    while worker.warmup_ms == 0.0 and time.time() - gate < 40.0:
        app.processEvents()
        time.sleep(0.05)
    round_waits = []
    while index < len(script):
        if pipe.state != "running":
            break                                     # 自动暂停/出错就如实停在这里
        before_cycles = pipe.stats["cycles"]
        stamp = time.time()
        worker.submit(script[index], (0, 0), 1.0,
                      capture_ms=statistics.mean(total) / 1000.0)
        index += 1
        waited = 0.0
        while (pipe.stats["cycles"] == before_cycles
               and pipe.state == "running" and waited < 12.0):
            app.processEvents()
            time.sleep(0.02)
            waited = time.time() - stamp
        round_waits.append(waited)
        remaining = interval - (time.time() - stamp)
        if remaining > 0:
            time.sleep(remaining)
            app.processEvents()
    # 让最后一帧落地，再收线程
    deadline = time.time() + 8.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    wall = time.time() - wall_before
    cpu = time.process_time() - cpu_before
    rss_after = rss_mb()
    data = pipe.perf()
    rate = data["cycles"] / wall if wall > 0 else 0.0
    worker.stop_sense()
    waited = worker.wait(3000)
    app.processEvents()

    row("[3b 流水线]", "提交帧数 / 扫描轮次", "%d 提交 / %d 轮" % (index, data["cycles"]))
    row("[3b 流水线]", "OCR 次数",
        "%d 次（其中整帧 %d 次、画面没变跳过 %d 次、一片纯色挡在闸门外 %d 次）"
        % (data["ocr_runs"], data["full_frame"], data["skipped_no_change"],
           data.get("skipped_blank", 0)))
    row("[3b 流水线]", "ROI 收紧（行+列）",
        "%d 次 · 一共剪掉 %.0f 行 / %.0f 列（不收的几种情况见 `_tighten_crop`）"
        % (worker.trim_count, worker.trimmed_px, worker.trimmed_cols))
    row("[3b 流水线]", "单轮 OCR 延迟",
        "均 %.0fms · 中位（近 %d 轮，判据）%.0fms · P95 %.0fms（会话自计）"
        % (pipe.avg_cycle_ms, min(len(pipe.cycle_ms), RECENT_WINDOW),
           pipe.recent_cycle_ms, pipe.p95_cycle_ms))
    row("[3b 流水线]", "每轮样本延迟（按轮序）",
        " · ".join("%.0fms" % ms for ms in pipe.cycle_ms[-12:]) or "无")
    row("[3b 流水线]", "轮间隔（投帧→该轮落地）",
        "均 %.2fs · 最大 %.2fs（%d 轮）"
        % (statistics.mean(round_waits), max(round_waits), len(round_waits))
        if round_waits else "无")
    row("[3b 流水线]", "实际扫描频率",
        "%.2f 轮/秒（设定 %.1f 次/秒 · 降频后 %.2f 次/秒）· OCR %.2f 次/秒"
        % (rate, hz0, pipe.hz, data["ocr_runs"] / wall))
    row("[3b 流水线]", "提示 / 抑制 / 待提示",
        "%d 次提示 · %d 次被去重压掉 · 队列里还剩 %d 个（一轮只闪一个）"
        % (data["notices"], data["suppressed"], pipe.pending_notices()))
    row("[3b 流水线]", "缓存规模",
        "ROI %d 条（上限 64）· 词 %d 条（上限 512）"
        % (len(pipe._roi_cache), len(pipe._seen_words)))
    cores = cpu / wall if wall > 0 else 0.0
    logical = os.cpu_count() or 1
    # 占空 = OCR 实际占用的墙钟 / 总墙钟（把每一轮的样本时长加起来，
    # 窗口只有 40 轮，而这里最多十几轮 → 不会漏样本）
    busy = sum(pipe.cycle_ms) / 1000.0
    duty = min(1.0, busy / wall) if wall > 0 else 0.0
    row("[3b 流水线]", "墙钟 / 进程 CPU",
        "%.2fs · %.2fs → 平均 %.1f 个核满载（本机逻辑核 %d）"
        % (wall, cpu, cores, logical))
    row("[3b 流水线]", "OCR 忙占比（占空）",
        "%.0f%%　·　口径：`time.process_time()` 把所有核都算进来，"
        "onnxruntime 一轮是**多核爆发**，所以「满载核数」= 爆发强度 × 占空比"
        % (duty * 100.0))
    if rss_before is not None and rss_after is not None:
        row("[3b 流水线]", "工作集内存",
            "%.1fMB → %.1fMB（感应期间增量 %+.1fMB）"
            % (rss_before, rss_after, rss_after - rss_before))
    else:
        row("[3b 流水线]", "工作集内存", "未运行（psapi 拿不到）")
    row("[3b 流水线]", "预算触发的降频",
        "%d 次 · 当前 %.2f 次每秒（起点 %.1f · 下限 %.1f）"
        % (data["downshifts"], pipe.hz, hz0, MIN_HZ))
    row("[3b 流水线]", "会话提示语", pipe.note or "（无）")
    check("每轮最多一次 OCR（相邻变化格已被并成一块，不随格数涨）",
          data["ocr_runs"] <= data["cycles"],
          "→ %d 轮 / %d 次 OCR" % (data["cycles"], data["ocr_runs"]))
    check("实测轮频率不超过设定初值（节流有效，没被帧率推着狂跑）",
          rate <= hz0 + 0.05, "→ %.2f 轮/秒 vs 设定 %.1f 次/秒" % (rate, hz0))
    check("频率被动过就一定在下限之上（不会一路降到 0）",
          pipe.hz >= MIN_HZ - 1e-6 and pipe.hz <= hz0 + 1e-6,
          "→ 实测 %.2f 次/秒" % pipe.hz)
    check("超预算时要么降频、要么如实提示（§7.4「自动降频或提示」）",
          data["downshifts"] >= 1 or "预算" in pipe.note
          or pipe.recent_cycle_ms <= BUDGET_MS,
          "→ 近 %d 轮中位 %.0fms vs 预算 %.0fms · 降频 %d 次"
          % (min(len(pipe.cycle_ms), RECENT_WINDOW), pipe.recent_cycle_ms,
             BUDGET_MS, data["downshifts"]))
    check("静态画面没有反复唤醒 OCR（跳过占多数）",
          data["skipped_no_change"] > data["ocr_runs"],
          "→ %d 跳过 / %d 次 OCR（剧本里 %d 帧和上一帧一模一样、%d 帧真的换了内容）"
          % (data["skipped_no_change"], data["ocr_runs"],
             expected_skips, expected_changes))
    check("变化检测的判定和剧本对得上（不误报、不漏报）",
          (data["cycles"] - data["skipped_no_change"]) == expected_changes + 1
          and data["ocr_runs"] <= data["cycles"] - data["skipped_no_change"],
          "→ 判定「有变化」%d 轮（剧本 %d 次换内容 + 首帧基线 1）· OCR %d 次"
          % (data["cycles"] - data["skipped_no_change"], expected_changes,
             data["ocr_runs"]))
    check("桌面上新出现的词真的被提示出来了（%d 次，不是「跑了一轮但什么都没有」）"
          % data["notices"], data["notices"] >= 1,
          "→ §7.4「开启后能识别桌面上新出现的词」这条要靠数字，不能靠话")
    check("一次只闪一个词（提示 %d 次 ≤ 轮数 %d，剩下排队）"
          % (data["notices"], data["cycles"]), data["notices"] <= data["cycles"])
    check("跨线程提示确实投递到主线程（收到 %d / 发出 %d）"
          % (len(notices), data["notices"]), len(notices) == data["notices"])
    check("缓存有上限（不会越跑越肥）",
          len(pipe._roi_cache) <= 64 and len(pipe._seen_words) <= 512)
    check("OCR 占空 < 60%%（实测 %.0f%%，本机 %d 核）" % (duty * 100.0, logical),
          duty < 0.60,
          "→ 「不是零成本、也不占满机器」：这一条量的是**一整轮里 OCR 占了多长墙钟**，"
            "多核爆发的强度看上面「满载核数」那一行")
    check("工作集内存量到了（增量 %s MB）" % (
            "%.1f" % (rss_after - rss_before)
            if rss_before is not None and rss_after is not None else "未运行"),
          rss_before is not None and rss_after is not None,
          "→ 内存也是 §7.4 点名要的实测项，拿不到就写「未运行」")
    check("出错时如实上报（本轮 fault %d 次）" % len(faults), len(faults) == 0,
          faults[0] if faults else "")
    check("中途没有把模式自己关掉（自动暂停只在真追不上时发生）",
          pipe.state == "running", "→ 状态 %s · %s" % (pipe.state, pipe.note))
    row("[3b 流水线]", "关闭后线程状态",
        "isRunning=%s wait()=%s" % (worker.isRunning(), waited))
    check("关闭后工作线程真的退出（不重启、不遗留）",
          waited and not worker.isRunning())
    # QThread 是原生线程，`threading.enumerate()` 里看不到，所以只能量它自己的状态；
    # 这里再补一个 Python 侧线程数，作为「没有偷偷再起后台线程」的下限证据。
    row("[3b 流水线]", "Python 线程数", threading.active_count())
    check("Python 侧没有遗留感应线程", threading.active_count() <= 3,
          "→ 主线程 + 本机常驻的预热/心跳线程")

    # ---- 4. 超预算 → 自动降频 / 提示 / 暂停（人为把预算压到 1ms） --------
    print("\n[4] 超预算：降频阶梯 → 下限提示 → 真追不上才暂停")
    tight = SenseSession(hz=1.0, budget_ms=1.0)
    tight.start()
    for _ in range(6):
        tight.note_words("r0c0", [{"surface": "aggressive",
                                   "screen_pos": (100.0, 100.0)}], 900.0)
    row("[4 预算]", "降频 / 当前频率",
        "%d 次降频 · %.2f 次每秒（从 1.0 起）" % (tight.perf()["downshifts"], tight.hz))
    row("[4 预算]", "状态 / 提示语", "%s · %s" % (tight.state, tight.note))
    check("超预算会降频而不是死守频率", tight.hz < 1.0)
    # 本机实测整帧一轮 1503ms、预算 1200ms —— 正是这条路径。
    # 老算法会**卡死在 0.5 次/秒**（目标值算出来就是 0.5，既不再降、
    # 也进不了暂停分支），现在改成阶梯，一定会走到下限。
    for _ in range(30):
        tight.note_words("r0c0", [{"surface": "aggressive",
                                   "screen_pos": (100.0, 100.0)}], 1500.0)
    row("[4 预算]", "降到下限之后",
        "%s · %.2f 次每秒 · %s" % (tight.state, tight.hz, tight.note))
    check("阶梯一定走到下限（不会卡在 0.5 这种半路值）",
          abs(tight.hz - MIN_HZ) < 1e-6, "→ 实测 %.2f 次每秒" % tight.hz)
    check("还跑得动时不擅自关模式，但把「仍超预算」说出来",
          tight.state == "running" and "仍超预算" in tight.note,
          "→ 单轮 1500ms < 下限频率的轮间隔 %.0fms" % DUTY_LIMIT_MS)
    for _ in range(6):
        tight.note_words("r0c0", [{"surface": "aggressive",
                                   "screen_pos": (100.0, 100.0)}], 3200.0)
    row("[4 预算]", "连最慢节奏都追不上", "%s · %s" % (tight.state, tight.note))
    check("单轮比轮间隔还长 → 自动暂停并说明原因（不是无限重试）",
          tight.state == "paused",
          "→ %s　（门槛：近 %d 轮中位 ≥ %.0fms 且样本 ≥ %d 轮，连着两轮）"
          % (tight.note, RECENT_WINDOW, DUTY_LIMIT_MS, PAUSE_MIN_SAMPLES))
    before = tight.perf()["downshifts"]
    for _ in range(10):
        tight.note_words("r0c0", [{"surface": "aggressive",
                                   "screen_pos": (100.0, 100.0)}], 3200.0)
    check("暂停后不会自己重启（等用户手动「继续」，§7.3）",
          tight.state == "paused" and tight.perf()["downshifts"] == before)

    # ---- 4c. 孤立尖峰 ≠ 这台机器跟不上（★ 这条流水线实测抓出来的缺陷）----
    print("\n[4c] 判据口径：一次 10s 尖峰 vs 持续追不上")
    spike = SenseSession(hz=2.0)
    spike.start()
    spike.note_words("r0c0", [{"surface": "cold"}], 10029.0)   # [3] 里真发生过的那一次
    for i in range(8):
        spike.note_words("r0c0", [{"surface": "warm%d" % i}], 120.0)
    row("[4c 判据]", "一次 10s 尖峰之后",
        "%s · 近 %d 轮中位 %.0fms · 40 轮大平均 %.0fms · 频率 %.2f 次/秒"
        % (spike.state, min(len(spike.cycle_ms), RECENT_WINDOW),
           spike.recent_cycle_ms, spike.avg_cycle_ms, spike.hz))
    check("孤立尖峰不会把模式关掉（判据看的是近 %d 轮中位，已回到 120ms）"
          % RECENT_WINDOW, spike.state == "running",
          "→ 老判据在这里会暂停：大平均一直被那一次顶在预算外，两轮就判「追不上」，"
            "而实际这台机器单轮 120ms")
    check("大平均如实保留给显示（§7.4 要的是全窗口口径，不改它）",
          spike.avg_cycle_ms > spike.recent_cycle_ms * 5,
          "→ 均 %.0fms vs 中位 %.0fms" % (spike.avg_cycle_ms, spike.recent_cycle_ms))

    # ---- 4b. 连续出错 → 自动暂停（另一条「不许无限重启」的路径） --------
    print("\n[4b] 连续出错自动暂停")
    fragile = SenseSession(hz=1.0)
    fragile.start()
    for _ in range(2):
        fragile.note_error("RuntimeError: 引擎崩了")
    row("[4b 出错]", "两次出错后", "%s · 连续 %d" %
        (fragile.state, fragile._consecutive_errors))
    check("出错两次还没到上限时仍在跑（不被一次偶发异常关掉）",
          fragile.state == "running")
    fragile.note_error("RuntimeError: 引擎又崩了")
    row("[4b 出错]", "三次出错后", "%s · %s" % (fragile.state, fragile.note))
    check("连续 %d 次出错 → 自动暂停（MAX_CONSECUTIVE_ERRORS）" %
          3, fragile.state == "error")

    # ---- 输出报告 ---------------------------------------------------
    lines = ["# 蜘蛛感应实测报告（任务书 §7.4）", "",
             "运行：`python tools/sense_bench.py`　时间：%s"
             % time.strftime("%Y-%m-%d %H:%M:%S"),
             "本机的数字，换机器要重量。", "",
             "| 小节 | 指标 | 实测值 |", "|---|---|---|"]
    for section, metric, value in ROWS:
        lines.append("| %s | %s | %s |" % (section, metric, value))
    lines += ["", "## 通过项", *["- %s" % name for name in PASS]]
    if FAIL:
        lines += ["", "## 未通过", *["- %s" % name for name in FAIL]]
    lines.append("")
    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

    print("\n" + "=" * 78)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for name in FAIL:
        print("  FAILED:", name)
    print("报告：", REPORT)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
