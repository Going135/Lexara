# -*- coding: utf-8 -*-
"""「词蛛LEXARA · CET Spider」程序入口。

用法：
    正常启动          python src/main.py
    自检并截图        python src/main.py --selftest
    只测 OCR 链路     python src/main.py --ocr-test
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback

# ★ 必须在 numpy / cv2 / onnxruntime 被 import 之前设好：
#   OpenBLAS 默认按逻辑核数（本机 32）建线程池，每线程预留约 24MB 提交内存，
#   `import numpy` 一步就吃掉 795MB「私有提交」。夹到 1 线程后只剩 20MB，
#   而本项目里 numpy 只做 OCR 前的 resize / threshold / 卷积，全是小图单次操作，
#   多线程没有收益。用 setdefault 保留用户手动覆盖的余地。
for _env_name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                  "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_env_name, "1")

# ★ 必须在 QApplication 创建之前：QML 端自定义控件需要非原生样式（Basic），
#   Windows 默认 windowsvista 样式会忽略一切 contentItem/background 定制。
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QIcon, QImage,
                           QPainter)
from PySide6.QtWidgets import QApplication, QMessageBox

from wordbook import app_data_dir, resource_path

LOG_PATH = os.path.join(app_data_dir(), "run.log")


def log(message: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write("%s  %s\n" % (time.strftime("%H:%M:%S"), message))
    except Exception:                          # noqa: BLE001
        pass
    print(message, flush=True)


#: LEXARA_MEM_TRACE=1 时在启动关键点打印工作集，用来定位内存大头。
_MEM_TRACE = os.environ.get("LEXARA_MEM_TRACE") == "1"


def mem_trace(tag: str) -> None:
    """打印本进程当前内存（只在 `LEXARA_MEM_TRACE=1` 时生效）。

    必须**在进程内部**读：`.venv/Scripts/python.exe` 是 py.exe 的转发壳，
    外部按 pid 采 WorkingSet 只能量到那个 4MB 的空壳，数字全是假的。
    """
    if not _MEM_TRACE:
        return
    try:
        import ctypes
        import ctypes.wintypes as wt

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wt.HANDLE
        # ★ 必须声明 argtypes：64 位句柄超过 int 范围，不声明会按 int 转换并
        #   抛 OverflowError（外面看着像「打点没输出」）。
        psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC),
                                               wt.DWORD]
        psapi.GetProcessMemoryInfo.restype = wt.BOOL
        info = _PMC()
        info.cb = ctypes.sizeof(_PMC)
        psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                   ctypes.byref(info), info.cb)
        log("[mem] %-20s 工作集=%6.1fMB  私有=%6.1fMB"
            % (tag, info.WorkingSetSize / 2 ** 20, info.PrivateUsage / 2 ** 20))
    except Exception as error:                 # noqa: BLE001
        log("[mem] 打点失败: %r" % (error,))


def _install_crash_log() -> None:
    def hook(exc_type, exc, tb):
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write("\n[CRASH] %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                traceback.print_exception(exc_type, exc, tb, file=handle)
        except Exception:                      # noqa: BLE001
            pass
        traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = hook


# ---------------------------------------------------------------- 资源

def make_test_image() -> QImage:
    """合成一张英文测试图，用于 --ocr-test 与自检。"""
    image = QImage(1180, 300, QImage.Format_RGB888)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    painter.setPen(QColor(18, 20, 30))
    painter.setFont(QFont("Arial", 21))
    lines = [
        "The government decided to abandon the project because of",
        "insufficient funds and an absence of public support,",
        "which alarmed the committee that had supervised it.",
    ]
    for index, line in enumerate(lines):
        painter.drawText(QRect(34, 28 + index * 66, 1120, 60),
                         int(Qt.AlignLeft | Qt.AlignVCenter), line)
    painter.end()
    return image


def _describe_pixmap(pixmap) -> dict:
    """统计截图内容，用来判断「是不是白屏」。"""
    return _describe_image(pixmap.toImage())


def _describe_image(image) -> dict:
    """统计一张图的内容。

    抽成独立函数是因为本函数**很贵**（逐像素跑 Python）：自检里不能让它
    出现在定时器回调里 —— 一张 2560x1600 扫下来要好几秒，事件循环被卡住，
    后面排队的 `singleShot` 会成堆晚触发，时间线就全乱了。
    现在截图只存图 + 留一张缩略图，统计统一挪到 `finish()` 里做。
    """
    image = image.convertToFormat(QImage.Format_RGB32)
    step = 7
    total = 0
    non_dark = 0
    colors = {}
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            pixel = image.pixel(x, y)
            total += 1
            r = (pixel >> 16) & 0xFF
            g = (pixel >> 8) & 0xFF
            b = pixel & 0xFF
            if r > 40 or g > 40 or b > 40:
                non_dark += 1
            key = (r // 32, g // 32, b // 32)
            colors[key] = colors.get(key, 0) + 1
    top = sorted(colors.items(), key=lambda kv: -kv[1])[:5]
    return {"total": total, "non_dark": non_dark,
            "ratio": round(non_dark / max(1, total), 3),
            "top_colors": [(f"#{k[0]*32:02x}{k[1]*32:02x}{k[2]*32:02x}", v)
                           for k, v in top]}


# ---------------------------------------------------------------- 自检

def run_selftest(app: QApplication, pet) -> None:
    """按时间线触发各功能并逐帧截图，用于无人环境下核对结果。"""
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "dist", "selftest")
    os.makedirs(out_dir, exist_ok=True)
    log("[selftest] 输出目录 %s" % out_dir)

    report = []
    crop_dir = os.path.join(out_dir, "crop")
    os.makedirs(crop_dir, exist_ok=True)

    def _crop_pet(screen, pixmap, name: str) -> None:
        """按桌宠窗口的真实位置，从整屏截图里裁出它那一块。"""
        try:
            geo = pet.geometry()
            screen_geo = screen.geometry()
            dpr = pixmap.width() / float(max(1, screen_geo.width()))
            pad = 30
            rect = QRect(
                int((geo.x() - screen_geo.x() - pad) * dpr),
                int((geo.y() - screen_geo.y() - pad) * dpr),
                int((geo.width() + pad * 2) * dpr),
                int((geo.height() + pad * 2) * dpr),
            )
            rect = rect.intersected(QRect(0, 0, pixmap.width(), pixmap.height()))
            if rect.isEmpty():
                return
            pixmap.copy(rect).save(os.path.join(crop_dir, name + "_pet.png"))
        except Exception as error:             # noqa: BLE001
            log("[shot] %s 裁剪失败: %r" % (name, error))

    def shot(name: str):
        """截一帧。

        ★ 这里**只存图**，不做统计：逐像素统计要好几秒，放在定时器回调里
        会把事件循环整个卡住，后面排队的 `singleShot`（尤其折叠那几个探测点）
        会成堆晚触发，时间线失去意义 —— 实测「折叠动画进行中」读到的
        其实是已经跑完 4 秒的状态。统计改到 `finish()` 里用缩略图做。
        """
        def _do():
            try:
                screen = (QGuiApplication.screenAt(pet.center)
                          or QGuiApplication.primaryScreen())
                pixmap = screen.grabWindow(0)
                path = os.path.join(out_dir, name + ".png")
                ok = pixmap.save(path)
                thumb = pixmap.toImage().scaled(320, 200, Qt.IgnoreAspectRatio,
                                                Qt.FastTransformation)
                report.append([name, pixmap.width(), pixmap.height(), ok, thumb])
                log("[shot] %s %sx%s saved=%s" % (name, pixmap.width(),
                                                  pixmap.height(), ok))
                # 再裁一张「只看桌宠」的小图。整屏 2560x1600 里蜘蛛只有
                # 几百像素，肉眼根本核对不了收没收腿；裁剪图是按窗口真实
                # 位置切的，拿它当证据。
                _crop_pet(screen, pixmap, name)
                # 以及窗口自身的**同步渲染**（`grab()` 直接走一遍 paintEvent，
                # 不经过合成器）。整屏抓帧拿到的是 DWM 上一次合成的结果，
                # 跟窗口此刻真正画的东西可能有偏差 —— 两者一对比就知道
                # 是「画错了」还是「拍晚了」。
                pet.grab().save(os.path.join(crop_dir, name + "_widget.png"))
            except Exception as error:         # noqa: BLE001
                log("[shot] %s 失败: %r" % (name, error))
        return _do

    def simulate_ocr():
        """用合成图跑完整识词链路，验证 OCR→挑词→结果卡。"""
        from pet_window import OcrWorker
        image = make_test_image()
        worker = OcrWorker(image, pet.lexicon, pet.capture_mode,
                           pet.capture_limit, pet.capture_skip_stopwords,
                           min_conf=pet.min_conf, parent=pet)
        # 故意用一个**小选区**（<800px）：这条路径会触发 OCR 内部的 2 倍放大，
        # 正是以前词坐标错位一倍的地方，用来盯住这个回归。
        worker.capture_rect = QRect(300, 430, 560, 170)
        worker.dpr = 1.0
        worker.geo = QRect(0, 0, 1707, 1067)
        pet._workers.append(worker)
        worker.done.connect(
            lambda w, m, e, wk=worker: pet._on_ocr_done(w, m, e, wk))
        worker.finished.connect(pet._reap)
        worker.start()
        log("[selftest] 已启动 OCR 链路")

    def finish():
        log("[selftest] 汇总：%d 帧" % len(report))
        for row in report:
            name, w, h, ok, thumb = row
            info = _describe_image(thumb)
            log("  %-18s %4dx%-5d saved=%-5s 非暗=%3d%%"
                % (name, w, h, ok, int(info["ratio"] * 100)))
        log("[selftest] 完成")
        app.quit()

    # ---------------------------------------------------------------- 折叠观测
    #
    # ★ 折叠**不能**用「延时 + 到点探测」来验证。两个原因叠在一起：
    #   ① 抓一帧要 3~4 秒（`grabWindow` + 存 2560x1600 的 PNG），事件循环
    #      被占死，排队的定时器成堆晚触发 —— 探测点跑起来时动画早结束了，
    #      读出来永远是 1.0，什么也证明不了；
    #   ② `_leg_retract()` 是按**挂钟**算的，跟"跑了几帧"无关，所以哪怕
    #      只晚触发一次，读到的也不是想读的那一刻。
    #   改成：给主循环的定时器**再挂一个采样槽**逐帧记录。
    #
    #   注意别想着把 `pet._tick` 换掉 —— Qt 在 `__init__` 里连的是当时那个
    #   绑定方法对象，事后改属性**换不掉已经连上的槽**，采样永远是 0 条。
    #   多挂一个槽才是对的（这里踩过一次，日志里是「一帧都没采到」）。
    fold = {"on": False, "t0": 0.0, "rows": [], "tips": None, "settle": None,
            "unfold_at": None}

    def leg_tip_points():
        """八条步足脚尖的窗口像素坐标。借 `painter.to_screen` 换算，不另写几何。"""
        pet.painter.setup(pet._canvas_origin(), pet.unit, pet.spider.heading)
        sway = getattr(pet.spider, "body_sway", 0.0)
        transform = pet._scene_transform()
        points = []
        for leg in pet.spider.legs:
            if leg.palp:
                continue
            point = QPointF(*pet.painter.to_screen((leg.tip[0],
                                                    leg.tip[1] + sway)))
            if transform is not None:
                point = transform.map(point)
            points.append(point)
        return points

    def record_fold():
        if not fold["on"]:
            return
        value = pet._leg_retract()
        fold["rows"].append((time.monotonic() - fold["t0"], value,
                             pet.effect and pet.effect[0]))
        if fold["settle"] is None and value >= 0.999:
            fold["settle"] = len(fold["rows"]) - 1
            # 腿收到底的那一刻，真机验一次「腿的原位现在穿透了」
            tips = leg_tip_points()
            hit = [index for index, point in enumerate(tips)
                   if pet._on_spider(int(round(point.x())),
                                     int(round(point.y())))]
            fold["tips"] = (len(tips), hit)

    pet._timer.timeout.connect(record_fold)

    def spin(seconds: float) -> None:
        """把时间「空转」过去，同时让主循环照常跑帧。

        两次截图之间事件循环是自由的，但一旦开始 `shot()` 就会有 3~4 秒
        完全跑不到帧。要观察动画（收腿中途那一帧、以及"到位后一直保持"）
        就必须主动让出时间。用 `time.sleep` 不行 —— 那只是把两边一起冻住。
        """
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.005)

    def begin_fold():
        fold["rows"].clear()
        fold["tips"] = None
        fold["settle"] = None
        fold["unfold_at"] = None
        fold["t0"] = time.monotonic()
        fold["on"] = True
        pet.set_folded(True, silent=True)

    def report_fold():
        fold["on"] = False
        rows = fold["rows"]
        if not rows:
            log("[fold] !! 一帧都没采到，无法判断")
            return
        values = [value for _, value, _ in rows]
        times = [t for t, _, _ in rows]
        # 收腿段：从开头的 0 一路往上走到 1 的那些帧
        rising = []
        for value in values:
            rising.append(value)
            if value >= 0.999:
                break
        jumps = [abs(rising[i + 1] - rising[i]) for i in range(len(rising) - 1)]
        settle = fold["settle"]
        unfold_at = fold["unfold_at"]
        # 「待住」这一段：从腿收到位，一直数到开始展开为止
        stop = unfold_at if unfold_at is not None else len(rows)
        held = values[settle:stop] if settle is not None else []
        log("[fold] 逐帧采样 %d 帧：retract %.3f → %.3f，收腿段最大单帧跳变 %.4f"
            % (len(rows), values[0], values[-1],
               max(jumps) if jumps else 0.0))
        if settle is None:
            log("[fold] !! 腿一直没收到位")
        else:
            span = times[stop - 1] - times[settle] if stop - 1 > settle else 0.0
            log("[fold] 收腿 %.2fs 到位；此后连采 %d 帧（跨 %.2fs）retract "
                "最小 %.4f 最大 %.4f"
                % (times[settle], len(held), span,
                   min(held) if held else -1.0, max(held) if held else -1.0))
        log("[fold] 展开后 retract=%.4f（末帧 effect=%s）"
            % (values[-1], rows[-1][2]))
        if fold["tips"] is None:
            log("[fold] 腿没收到位，无法验证穿透")
        else:
            count, hit = fold["tips"]
            log("[fold] 折叠后腿尖 %d 个，仍吃点击的 %d 个 %s"
                % (count, len(hit), "← 有空地没穿透" if hit else "（全部穿透）"))

    def close_dialogs():
        # 用 hide() 而不是 close()：这些对话框设了 WA_DeleteOnClose，
        # close() 会把 C++ 对象销毁掉，之后任何悬垂的 Qt 定时器回调
        # （比如 start_capture/_capture_cancel）都会抛
        # "Internal C++ object already deleted" 把整个程序带崩。
        for key in ("book", "words"):
            dialog = pet._dialogs.get(key)
            if dialog is not None:
                try:
                    dialog.hide()
                except Exception:             # noqa: BLE001
                    pass

    def fold_now():
        """触发折叠，空转 0.25 秒（让主循环真的跑几帧），再抓一帧。

        不能靠「18000 触发折叠、18250 截图」：抓一帧要好几秒
        （`grabWindow` + 存 2560x1600 的 PNG），等截图跑起来时动画早结束了，
        拍到的一定是「已经收好」的样子，永远看不到收腿中途。
        """
        begin_fold()
        spin(0.25)
        shot("13_folding")()

    def unfold_now():
        fold["unfold_at"] = len(fold["rows"])   # 待住段到此为止
        pet.set_folded(False, silent=True)
        spin(0.25)
        shot("16_unfolded")()
        spin(0.60)                              # 等伸腿跑完，采样才收在 0

    # ------------------------------------------------------------ 瞄准层常驻
    #: 瞄准层第一次被看到的时刻，用来算「撑了多久」
    hold = {"t0": None}

    def aim_probe(label: str):
        """记一笔「此刻八腿踩词这层还在不在」。

        ★ 这个状态**不会自己结束**（原来是 11 秒自动关），所以必须有一条
          跨越 11 秒以上的证据，否则「改好了」和「忘了改」在日志里长得一样。
        """
        def _do():
            # 截图会把事件循环占住好几秒，时间线上的「踩词后立刻」常常
            # 还没轮到瞄准层起来 —— 第一版日志里就出现了「瞄准层=不在」，
            # 看着像没起来，其实只是还没轮到。所以先等它出现（有上限）。
            waited = 0.0
            while waited < 8.0:
                try:
                    probe = pet._dialogs.get("aim")
                    if probe is not None and probe.isVisible():
                        break
                except RuntimeError:
                    # `WA_DeleteOnClose`：已经被（真实点击）收掉了
                    break
                spin(0.2)
                waited += 0.2

            if hold["t0"] is None:
                hold["t0"] = time.monotonic()

            overlay = pet._dialogs.get("aim")
            try:
                alive = overlay is not None and overlay.isVisible()
                legs = 0 if overlay is None else len(overlay._pairs)
                hooked = bool(overlay is not None and overlay._hook)
                boxes = 0 if overlay is None else len(overlay._guides)
            except RuntimeError:
                # `WA_DeleteOnClose`：关完 C++ 对象就没了
                alive, legs, hooked, boxes = False, -1, False, 0
            log("[aimhold] %s：瞄准层=%s，已持续 %.1fs，踩词腿=%d 词框=%d，"
                "钩子在=%s 本体隐藏=%s"
                % (label, "在" if alive else "不在",
                   time.monotonic() - hold["t0"], legs, boxes,
                   hooked, not pet.isVisible()))
        return _do

    def spin_probe():
        """真机上转一圈，采样「腿到底有没有跟着倒换」。

        转身不走画面旋转（`Tf.rot`），而是推进 `spider.heading`；
        脚钉在世界坐标上（`Spider.turn()` 把脚在体坐标系里反向旋转），
        于是偏离静止位 → 阈值步态触发 → 腿跟着迈。
        这里量三件事：转过的角度、有多少条腿迈过步、脚有没有被拖出腿长。
        """
        import math as _m

        import anim

        def _do():
            spider = pet.spider
            h0 = spider.heading
            stepped = set()
            worst = 0.0
            log("[spin] 起转：朝向 %.2f rad" % h0)

            pet.spin_once()
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.005)
                for leg in spider.legs:
                    if leg.stepping:
                        stepped.add(leg.index)
                    hx, hy = leg.hip_pos
                    r = _m.hypot(leg.tip[0] - hx, leg.tip[1] - hy)
                    worst = max(worst, r / leg.full)

            turned = spider.heading - h0
            log("[spin] 转过 %.3f rad（目标 %.3f）参与迈步的腿=%d 条 "
                "脚最远伸到腿长的 %.0f%%"
                % (turned, anim.SPIN_ANGLE, len(stepped), worst * 100.0))
        return _do

    def aim_dismiss():
        """模拟「用户再点一下」：走的是真机上的同一条退出路径。"""
        def _do():
            overlay = pet._dialogs.get("aim")
            if overlay is None:
                log("[aimhold] 没有瞄准层可收")
                return
            try:
                overlay._dismiss()               # 钩子回调排的也是这一步
            except RuntimeError:
                return
            spin(0.4)
            log("[aimhold] 收起后：腿目标=%d 本体可见=%s"
                % (len(pet.spider.targets), pet.isVisible()))
        return _do

    #: 每一步都拿 `QTimer.singleShot` 排的话，截图会把事件循环占住几秒，
    #: 排队的定时器**成堆晚触发、而且顺序会乱**（实测 21500 排在 22450 前面，
    #: 实际却是 22450 先跑，`report_fold` 因此被 `finish` 抢了先、一个字没记）。
    #: 所以改成一条自己推进的时间线：每步做完再看下一步该不该跑，
    #: 顺序天然正确；晚了就如实记一笔，不装作准时。
    # ★ 折叠这一段必须排在 `simulate_ocr` **之前**。
    #   OCR 是另一个线程跑的，结果回来时（几秒后）`_on_ocr_done` 会调
    #   `travel_to()` 去站位，而「要走路就得有腿」这条不变式会自动伸腿 ——
    #   折叠刚生效就被自己展开了。这不是折叠的 bug，是用例把它排进了
    #   忙碌窗口（日志里能看到 set_folded(False) 的调用栈来自 _on_ocr_done）。
    timeline = [
        (700, shot("01_idle")),
        # 折叠（无腿模式）：收腿中途、收到位、待住，再展开。
        # 「有没有待住」不靠这几个探测点（会被截图拖延），靠挂在 `_tick`
        # 上的逐帧采样，见 `report_fold()`。
        (1000, fold_now),
        (2000, shot("14_folded_idle")),
        # 「待住」这一段不能只靠两张截图之间的间隔来凑：抓一张要 3~4 秒，
        # 期间事件循环完全跑不到帧，采样只有个位数。
        # 专门插一段只空转、不截图的步，把待住段拉到几百帧。
        (5000, lambda: spin(1.5)),
        (6600, shot("15_folded_still")),
        (7600, unfold_now),
        (8800, report_fold),
        (7300, lambda: pet.play("jump")),
        (7650, shot("02_jump")),
        (7900, lambda: pet.travel_to(pet.center + QPoint(320, 60))),
        (8900, shot("03_travel")),
        (9500, lambda: pet.travel_to(pet.center + QPoint(-620, -180), force_jump=True)),
        (10000, shot("04_jump_air")),
        (10600, shot("05_jump_landed")),
        (11100, lambda: pet._set_state("think")),
        (11600, shot("06_think")),
        (12100, lambda: pet._set_state("idle")),
        (12600, shot("07_idle_again")),
        # 转身：必须排在 OCR / 框选**之前**。
        # 那之后不是本体被隐藏（瞄准层常驻），就是窗口被遮罩占着，
        # 转起来根本看不见，采样也采不到。
        (12700, spin_probe),
        # 框选遮罩这一段挪到 OCR **之前**：OCR 之后就进「趴在词上」的常驻状态了，
        # 那时本体窗口是隐藏的，再开框选遮罩既不合逻辑，也会把瞄准层顶掉，
        # 后面的「一直持续」就没得验了。
        (13000, lambda: pet.start_capture()),
        (14300, shot("11_capture_overlay")),
        (14700, lambda: pet._capture_cancel()),
        (15300, shot("12_after_cancel")),
        (15800, simulate_ocr),
        (20600, shot("08_ocr_moving")),
        (22500, shot("09_aim_early")),
        (23700, shot("10_aim_stagger")),
        (24400, aim_probe("踩词后立刻")),
        # ★ 关键一步：纯空转 14 秒，跨过原来 `start(11000)` 的 11 秒自动关闭。
        #   注意这期间「再点一下」的钩子是开着的 —— 真有人点鼠标就会被收掉，
        #   日志里会如实写出「不在 / 已持续 Xs」，那是另一个功能，不是自动关闭。
        (25000, lambda: spin(14.0)),
        (39500, aim_probe("空转 14 秒后")),
        (40000, aim_dismiss),
        (40800, finish),
    ]

    state = {"index": 0, "t0": time.monotonic(), "busy": False}

    def pump():
        """自己推进时间线，而不是给每一步排一个 `singleShot`。

        截图一次要 3~4 秒，一次把到期步骤全部跑完就会把主循环的帧
        完全饿死（折叠采样会一条都收不到），所以**每跑完一步就让出一轮**。
        """
        if state["busy"]:
            # `spin()` 里的 `processEvents` 会把排队的 pump 也带进来。
            # 必须挡住：否则「折叠」这一步还在跑，后面的「展开」就抢进来
            # 把 `folded` 改回 False —— 采样出来恒为 0，看着像折叠没生效。
            QTimer.singleShot(20, pump)
            return
        if state["index"] >= len(timeline):
            finish()
            return
        delay, action = timeline[state["index"]]
        lag = (time.monotonic() - state["t0"]) * 1000.0 - delay
        if lag < 0:
            QTimer.singleShot(20, pump)
            return
        state["index"] += 1
        if lag > 600:
            log("[step] 第 %d 步晚了 %.1fs（截图阻塞事件循环）"
                % (delay, lag / 1000.0))
        state["busy"] = True
        try:
            action()
        except Exception:                      # noqa: BLE001
            log("[step] 第 %d 步出错:\n%s" % (delay, traceback.format_exc()))
        finally:
            state["busy"] = False
        QTimer.singleShot(0, pump)

    QTimer.singleShot(0, pump)


def run_ocr_test() -> int:
    """只跑 OCR + 挑词，把结果写到文件，便于脱离界面排查。"""
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "dist", "ocr_result.txt")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    lines = []
    try:
        from lexicon import Lexicon
        from ocr_engine import OcrEngine

        t0 = time.time()
        image = make_test_image()
        ocr_lines = OcrEngine.recognize_lines(image)
        text = "\n".join(line.text for line in ocr_lines)
        lines.append("OCR 耗时 %.2fs" % (time.time() - t0))
        lines.append("原始文本：")
        lines.append(text)

        lexicon = Lexicon(resource_path("assets", "ecdict.sqlite"),
                          resource_path("assets", "exam-tags.sqlite"),
                          resource_path("assets", "industry.sqlite"))
        lines.append("")
        lines.append("词典状态：%s" % lexicon.status())
        for mode in ("cet4", "cet6", "all"):
            words = lexicon.scan_text(text, mode=mode, limit=8)
            lines.append("")
            lines.append("=== 模式 %s → %d 个 ===" % (mode, len(words)))
            for item in words:
                lines.append("  %-14s %-18s %-16s %s"
                             % (item["lemma"], item["phonetic"], item["level"],
                                item["meaning"][:44]))
        code = 0
    except Exception:                          # noqa: BLE001
        lines.append("FAILED:\n" + traceback.format_exc())
        code = 1

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print("\n".join(lines))
    return code


# ---------------------------------------------------------------- 入口

def main() -> int:
    _install_crash_log()
    log("---- 启动 argv=%r frozen=%s" % (sys.argv, getattr(sys, "frozen", False)))

    # 改名迁移（2026-10-16：EightLegsGlow → Lexara）要在任何存储读写之前做
    from settings_store import migrate_app_dir
    migrate_app_dir()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Lexara")
    app.setApplicationDisplayName("词蛛LEXARA")
    # 任务栏 / Alt-Tab 的图标：exe 里嵌的那份只管「资源管理器里这个文件」的显示，
    # 程序跑起来之后的窗口图标必须由 QApplication 指定 —— 否则 Windows 会拿
    # Python 解释器的图标顶上（无边框置顶窗口尤其明显）。
    # 走 `resource_path` 才能兼容 PyInstaller onefile 解包到 _MEIPASS 的情况。
    _icon_path = resource_path("assets", "icon.ico")
    if os.path.exists(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))
    app.setFont(QFont("Microsoft YaHei UI", 9))
    log("QApplication 就绪 platform=%s" % app.platformName())
    mem_trace("QApplication 就绪")

    if "--ocr-test" in sys.argv:
        return run_ocr_test()

    # 音效预热：MCI 首次 open 实测 160~750 ms，全是同步阻塞。现在 `sfx.play()`
    # 本身只投递到后台线程（点按钮不再卡），但冷启动那一发仍会迟到半秒，
    # 所以启动时先把设备打开，把这份开销花在用户还没点的时候。
    from sfx import prewarm as _prewarm_sfx
    _prewarm_sfx()

    from lexicon import Lexicon
    from pet_window import PetWindow
    from settings_store import Settings
    from wordbook import Wordbook

    dict_path = resource_path("assets", "ecdict.sqlite")
    tags_path = resource_path("assets", "exam-tags.sqlite")
    log("词典 %s 存在=%s" % (dict_path, os.path.exists(dict_path)))

    lexicon = Lexicon(dict_path, tags_path,
                     resource_path("assets", "industry.sqlite"))
    status = lexicon.status()
    log("词典就绪 entries=%s 考纲=%s 行业词库=%s(%s 条)"
        % (status["entries"], status["exam"]["available"],
           status["industry"]["available"], status["industry"]["entryCount"]))
    if not lexicon.available:
        QMessageBox.critical(None, "词蛛LEXARA",
                             "找不到词典文件 assets/ecdict.sqlite")
        return 1
    mem_trace("词典就绪")

    book = Wordbook()
    settings = Settings(log=log)
    settings.load()

    # 后台预热 OCR，避免第一次识词时卡住。
    # 2026-10-17 修正：以前用 QTimer.singleShot(400, ...) 在**主线程**里同步建
    # RapidOCR 模型（ONNX 加载 1~3 秒），启动台会明显卡一下。真正的预热放到
    # daemon 线程；OcrEngine 内部有类级锁 + get() 惰性构造，线程安全。
    def _warm_ocr() -> None:
        try:
            import ocr_engine
            ocr_engine.OcrEngine.warmup()
            mem_trace("OCR 预热完成")
        except Exception as error:              # noqa: BLE001
            log("[ocr] 后台预热失败: %r" % (error,))

    # ★ 错峰：首帧渲染本身要吃 ~300MB 临时缓冲，如果 OCR 预热（又 +90MB）
    #   同时起来，启动峰值会从 600 顶到 900。排到窗口画完之后再热，用户感知
    #   不到差别，峰值能削掉一百多 MB。QTimer 在 exec 之后才会跑。
    _warm_thread = threading.Thread(target=_warm_ocr, name="ocr-warmup", daemon=True)
    QTimer.singleShot(1500, _warm_thread.start)

    # 空闲卸载 OCR：模型常驻约 90MB（onnxruntime 三份 session + 工作区），
    # 而背单词的人可能一小时才框选一次屏幕。8 分钟没动过就还回去，下次识词
    # 由 `OcrEngine.get()` 自动重建（1~2 秒，界面不卡）。60 秒查一次，开销可忽略。
    def _release_idle_ocr() -> None:
        try:
            import ocr_engine as _ocr
            if _ocr.OcrEngine.loaded() and _ocr.OcrEngine.idle_seconds() > 8 * 60:
                # 放到后台线程：`release()` 里有一次 `gc.collect()`，在 UI 线程
                # 跑会啃掉 100ms 左右，正好撞上用户的点击就显得卡了。
                threading.Thread(target=_ocr.OcrEngine.release,
                                 name="ocr-idle-release", daemon=True).start()
                log("[ocr] 空闲 8 分钟，释放模型（约 90MB）")
        except Exception as error:              # noqa: BLE001
            log("[ocr] 空闲释放失败: %r" % (error,))

    _idle_timer = QTimer()
    _idle_timer.setInterval(60 * 1000)
    _idle_timer.timeout.connect(_release_idle_ocr)
    _idle_timer.start()
    app._ocr_idle_timer = _idle_timer           # 持有引用，否则被 GC 掉计时就停了

    # --selftest 跳过启动台，直接建桌宠跑自检（保持原有行为）
    if "--selftest" in sys.argv:
        pet = PetWindow(lexicon, book)
        app._pet = pet
        app._lexicon = lexicon
        log("[selftest] 启动")
        run_selftest(app, pet)
        return app.exec()

    # ------------------------------------------------ 正常流程：先开启动台
    # QML 版启动台（2026-10-17）：旧 LauncherWindow 降级为隐藏控制器，
    # 由 launcher_qml.LauncherBridge 包装；要回旧界面设 LEXARA_LEGACY_LAUNCHER=1。
    bridge = None
    if os.environ.get("LEXARA_LEGACY_LAUNCHER") != "1":
        from launcher_qml import LauncherBridge
        bridge = LauncherBridge(lexicon, book, settings, log=log)
        launcher = bridge.launcher
    else:
        from launcher_window import LauncherWindow
        launcher = LauncherWindow(lexicon, book, settings, log=log)
    app._launcher = launcher
    app._lexicon = lexicon

    # ------------------------------------------------ 桌宠生命周期
    # 2026-10-18：部署/收回/退出/启动后自动部署统一交给 `app_lifecycle.PetLifecycle`。
    # 以前这三条是闭包 + `app._pet` 裸引用，重复触发只能靠各调用点自觉判断；
    # 现在「创建前看实例、销毁后清引用」写在同一个对象里，并且可被单测覆盖。
    from app_lifecycle import PetLifecycle
    lifecycle = PetLifecycle(launcher, lexicon, book, settings, log=log)
    lifecycle.wire()
    app._lifecycle = lifecycle

    # 启动台改设置 → 已部署的桌宠实时跟随。这两条以前是 main 里的闭包，
    # 现在收进 PetLifecycle（`test/test_app_lifecycle.py` 能直接断言）。
    # ★ 皮肤：以前 `payload` 读隐藏面板，QML 换皮不经过面板 → 部署时发的是旧
    #   皮肤；大小：以前只写 settings，没人调 `pet.set_scale()`。
    launcher.skin_changed.connect(lifecycle.sync_skin)
    launcher.scale_changed.connect(lifecycle.sync_scale)
    if bridge is not None:
        # QML 启动台：自动部署排在 `bridge.run()` 之前（exec 之后才会真的跑）。
        lifecycle.schedule_auto_deploy(1200)
        mem_trace("启动台就绪")
        if _MEM_TRACE:
            def _trace_window() -> None:
                win = getattr(bridge, "_window", None)
                if win is None:
                    return
                dpr = win.devicePixelRatio()
                log("[mem] 窗口 %.0fx%.0f  dpr=%.2f  物理 %.0fx%.0f"
                    % (win.width(), win.height(), dpr,
                       win.width() * dpr, win.height() * dpr))
            for _delay in (2000, 6000, 12000):
                QTimer.singleShot(_delay, lambda d=_delay: mem_trace("exec+%dms" % d))
            QTimer.singleShot(2000, _trace_window)
        return bridge.run()                      # QML 启动台（含 app.exec）
    launcher.show()
    lifecycle.schedule_auto_deploy(1200)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
