# -*- coding: utf-8 -*-
"""微光桌宠主窗口。

窗口完全透明、无边框、置顶；蜘蛛本体由 `crawler_spider` 实时解算、
`spider_painter` 逐帧画出，不用贴图。

交互：
    · 单击头部 / 双击任意处 —— 框选识词
    · 按住拖动 —— 移动（八条腿按阈值步态小跑）
    · 单击身体 —— 随机互动（跳 / 压扁 / 抖动 / 冲刺）
    · 滚轮 —— 放大缩小
    · 右键 —— 功能菜单

状态机 idle / crawl / think / rest / jump：
    前四者只影响步态参数（收腿程度、亮度、关节光晕），
    跳跃弧线等一次性形变见 `anim.py`。
"""

from __future__ import annotations

import ctypes
import math
import random
import re
import time
from ctypes import wintypes

from PySide6.QtCore import (QAbstractNativeEventFilter, QByteArray, QEvent, QPoint, QPointF, QRect, QRectF,
                            Qt, QThread, QTimer, Signal)
from PySide6.QtGui import (QAction, QIcon, QImage, QPainter, QPixmap, QTransform, QCursor, QGuiApplication, QKeySequence, QShortcut)
from PySide6.QtWidgets import (QApplication, QMenu, QMessageBox, QSystemTrayIcon,
                               QWidget)

import anim
import content
import crawler_spider as CS
import locomotion
from bubble import BubbleWindow
from capture import CaptureOverlay, grab_virtual_desktop
from dialogs import ModeDialog, WordResultDialog, WordbookDialog
from ocr_engine import OcrEngine, qimage_to_ndarray
from sense_overlay import SenseOverlay
# 兜底初值和启动台用同一份默认值，免得「没开启动台」和「开过启动台」的
# 桌宠一次处理不同数量的词（`settings_store` 不 import 桌宠，没有循环）。
from settings_store import DEFAULTS as SETTINGS_DEFAULTS
from settings_store import SENSE_HZ_RANGE
from spider_painter import SpiderPainter, SpiderState, skin_options

TICK_MS = 16
#: 空闲降频（2026-10-17）：蜘蛛彻底站定时（无动画/无位移/没被拖/瞄准层没开/
#: 步态里一条腿都不在迈/徽章站姿已混合到位），60fps 主循环就纯属烧 CPU。
#: 连续 `IDLE_SETTLE_FRAMES` 帧判为静止后，定时器降到 `IDLE_TICK_MS`，
#: 且 `_tick` 不再推进模型、不再重绘；任意输入或状态切换立刻唤醒回 16ms。
IDLE_SETTLE_FRAMES = 30
IDLE_TICK_MS = 60
MIN_SCALE, MAX_SCALE = 0.5, 2.2

# ---------------------------------------------------------------- Win32 消息
# 用来在 WM_NCHITTEST 里告诉系统「这个像素不属于我」，让点击落到下面的窗口。
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1


class MSG(ctypes.Structure):
    """Win32 `MSG`。只用到 message 与 lParam（鼠标屏幕坐标）。"""

    _fields_ = [("hWnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG)]

WM_HOTKEY = 0x0312
HOTKEY_ID = 0x4C58
MOD_ALT, MOD_CONTROL, MOD_SHIFT = 0x0001, 0x0002, 0x0004

class _GlobalScanHotkey(QAbstractNativeEventFilter):
    """Windows 全局 Ctrl+Shift+S；Qt 窗口未聚焦时也能启动框选。"""
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = False
        try:
            self.registered = bool(ctypes.windll.user32.RegisterHotKey(
                None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT, ord("S")))
        except Exception:
            self.registered = False

    def nativeEventFilter(self, eventType, message):
        if self.registered and str(eventType) in ("windows_generic_MSG", "windows_dispatcher_MSG"):
            try:
                msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
                if msg.message == WM_HOTKEY and int(msg.wParam) == HOTKEY_ID:
                    QTimer.singleShot(0, self.callback)
                    return True, 0
            except Exception:
                pass
        return False, 0

    def unregister(self):
        if self.registered:
            try: ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception: pass
            self.registered = False

#: 判定为「拖动」而非「点击」的位移阈值（像素）
DRAG_THRESHOLD = 5

#: 「走 vs 跳」的分界**不在这里**，见 `locomotion.walk_jump_threshold()`：
#: 它按腿展算，跟着桌宠缩放走，还带滞回。写死的 260px 在 50% 尺寸下是三个身位、
#: 在 200% 尺寸下不到一个腿展，同一个数字说的是两件事。

#: 跳跃基准时长与抛物线高度（参考像素；时长会按距离被 `locomotion.jump_duration` 拉长）
#: 数值单一来源在 `locomotion`：桌宠在桌面上跳、瞄准层踩着词走，用的是同一套手感，
#: 分两处写死迟早会变成「桌面上跳 0.78s、覆盖层里 0.9s」这种对不上的东西。
JUMP_DURATION = locomotion.JUMP_BASE_SECONDS
JUMP_ARC = locomotion.JUMP_ARC_PX

#: 行走速度（像素/秒）
WALK_SPEED = locomotion.WALK_SPEED_PX

#: 识别时，「各脚依次伸出去踩词」的间隔（秒）。
#: 八条腿全伸完要 stagger×7，0.06 时约 0.42s —— 再慢就有人以为卡住了；
#: 再快就分不出「依次伸出」的错峰感，看起来像八条腿一起弹出去。
LEG_STAGGER = 0.06

#: 调位被打断后，等多长时间再踩词（秒）。
#: 一次点击要等 press→release 走完、200ms 后才知道是单击还是双击、落在头还是
#: 身上 —— 踩词比这慢一点，才不会「遮罩刚起来，用户这一下又把框选叫了出来」。
AIM_GRACE = 0.32

MENU_QSS = """
QMenu {
  background:#FFFFFF;
  border:1px solid #E4E4DF;
  border-radius:10px;
  padding:6px;
  color:#2B2B2B;
  font-size:12px;
}
QMenu::item {
  min-height:32px;
  padding:6px 30px 6px 10px;
  border-radius:7px;
}
QMenu::item:selected {
  background:#EEF3FF;
  color:#2F6BFF;
}
QMenu::item:disabled { color:#A0A09B; }
QMenu::separator {
  height:1px;
  background:#EEEEEA;
  margin:5px 8px;
}
QMenu::indicator { width:16px; height:16px; }
QMenu::right-arrow { width:12px; height:12px; }
"""
MENU_ICON_SVGS = {
    "capture": '<path d="M4 7V4h3M17 4h3v3M20 17v3h-3M7 20H4v-3"/>',
    "book": '<path d="M5 4.5A2.5 2.5 0 0 1 7.5 2H19v17H7.5A2.5 2.5 0 0 0 5 21.5z"/><path d="M5 4.5v17"/><path d="M9 6h6"/>',
    "settings": '<circle cx="12" cy="12" r="3.2"/><path d="M18.4 12h2M15.9 15.9l1.4 1.4M12 18.4v2M8.1 15.9l-1.4 1.4M5.6 12h-2M8.1 8.1L6.7 6.7M12 5.6v-2M15.9 8.1l1.4-1.4"/>',
    "size": '<path d="M5 9V5h4M19 15v4h-4M9 19H5v-4M15 5h4v4"/>',
    "skin": '<circle cx="12" cy="12" r="8.2"/><path d="M12 3.8c2.6 2.3 4 5.1 4 8.2s-1.4 5.9-4 8.2c-2.6-2.3-4-5.1-4-8.2s1.4-5.9 4-8.2z"/><path d="M4.2 9.4h15.6M4.2 14.6h15.6"/>',
    "fold": '<path d="M5 6h5M5 12h4M5 18h5M19 6h-5M19 12h-4M19 18h-5"/>',
    "spin": '<path d="M5 12a7 7 0 1 0 2-4.9"/><path d="M5 5v4h4"/>',
    "pin": '<path d="M8 4h8M9 4l1 7-4 3h12l-4-3 1-7M12 14v6"/>',
    "click": '<path d="M5 4l7 16 2-7 6-2z"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.7 9a2.4 2.4 0 1 1 4.1 1.7c-1 .9-1.8 1.2-1.8 2.8M12 17h.01"/>',
    "home": '<path d="M3.5 11.5L12 4l8.5 7.5"/><path d="M5.5 10.5V20h13v-9.5M9.5 20v-5h5v5"/>',
    "exit": '<path d="M10 5H5v14h5M14 8l4 4-4 4M18 12H9"/>',
    # 蜘蛛感应：一只眼睛 + 两道「在看」的弧线。语义上比雷达更贴 §7.2 的
    # 「持续、可停止的观察」，而且和「框选识词」那种取景框图标不会看混。
    "eye": '<path d="M2.6 12S6 6.4 12 6.4 21.4 12 21.4 12 18 17.6 12 17.6 2.6 12 2.6 12z"/>'
           '<circle cx="12" cy="12" r="2.6"/>',
}

def _menu_icon(kind: str, size: int = 18) -> QIcon:
    body = MENU_ICON_SVGS.get(kind, "")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        'fill="none" stroke="#4A4A4A" stroke-width="1.7" '
        'stroke-linecap="round" stroke-linejoin="round">' + body + '</svg>'
    )
    try:
        from PySide6.QtSvg import QSvgRenderer
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(
            painter, QRectF(0, 0, size, size))
        painter.end()
        return QIcon(QPixmap.fromImage(image))
    except Exception:  # noqa: BLE001
        return QIcon()



def _log(message: str) -> None:
    """运行日志（落到 %APPDATA%/Lexara/run.log）。"""
    try:
        import os
        import time as _time
        from wordbook import app_data_dir
        path = os.path.join(app_data_dir(), "run.log")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("%s  %s\n" % (_time.strftime("%H:%M:%S"), message))
    except Exception:                          # noqa: BLE001
        print(message, flush=True)


def _clamp_sense_hz(value: float) -> float:
    """感应频率夹到启动台滑杆的同一区间。

    区间只有 `settings_store.SENSE_HZ_RANGE` 一个来源：桌宠在这里夹、
    设置层在 `BOUNDS` 里夹、启动台滑杆读同一对数字。
    各写一份的话，就会出现「滑杆能拖到 2.0、桌宠偷偷按 1.0 跑」。
    """
    low, high = SENSE_HZ_RANGE
    return float(min(high, max(low, float(value))))


#: 退出应用时，给「已请求停止、还卡在最后一次识别里」的感应线程的总宽限（毫秒）。
#: 为什么需要这么一笔：本机一次 OCR 段最长实测 14620ms（`dist/sense/shape_probe.log`），
#: 关闭感应那 3 秒经常等不到它；§7.2 要求的是「不会留下永远在跑的后台线程」，
#: 所以先记下线程、退出时再等一轮，而不是让 GUI 线程无限期冻住。
SENSE_EXIT_GRACE_MS = 12000


def _current_engine_id() -> str:
    """当前生效的 OCR 引擎 ID，**只用于日志**。

    惰性导入 + 兜底：`ocr_adapter` 拉进了 numpy/paddle 的探测代码，
    在探测还没跑完（或导入失败）的早期阶段，日志不该因此炸掉 ——
    宁可写一个「还没探测」的默认值，也不要让一行日志把部署流程打断。
    """
    try:
        import ocr_adapter
        return ocr_adapter.current_engine()
    except Exception:                          # noqa: BLE001
        return "rapid"


class OcrWorker(QThread):
    """OCR 放到独立线程，避免识别时界面卡住。"""

    done = Signal(list, dict, str)

    def __init__(self, image, lexicon, mode: str, limit: int, skip_stopwords: bool,
                 min_conf: float = 0.0, parent=None):
        super().__init__(parent)
        # QImage → ndarray 属于 GUI 线程的操作，必须在**构造时（主线程）**做完，
        # worker 里只跑纯 numpy + onnxruntime。放错线程会让进程直接崩掉。
        from ocr_engine import qimage_to_ndarray
        try:
            self.array = qimage_to_ndarray(image) if image is not None else None
        except Exception as error:            # noqa: BLE001
            self.array = None
            _log("[ocr] 图像转换失败: %r" % (error,))
        self.lexicon = lexicon
        self.mode = mode
        self.limit = limit
        self.skip_stopwords = skip_stopwords
        self.min_conf = min_conf
        #: 本轮**实际**跑的引擎（不是界面期望值）。回退时这里会变，
        #: 配合 `engine_note` 一起交给结果卡显示，避免「界面写 Paddle、
        #: 后台跑 Rapid」那种不诚实状态（§3.2）。
        self.engine_id = "rapid"
        self.engine_note = ""
        self.capture_rect = None
        self.dpr = 1.0
        self.learning_history = []

    @staticmethod
    def phrase_point(surface: str, lines):
        """多词术语的落点：取同一行里各单词中心的中点。

        缩写、多词术语（`preventive maintenance`）在 OCR 结果里是**好几个**
        `OcrWord`，而 `positions` 的键是单个词，直接查必然落空 ——
        落空的词条拿不到 `screen_pos`，瞄准层就把它算成「够不着」而不派腿。
        所以必须按行把各单词凑齐再取中点。

        只认**同一行内**凑齐的：跨行拼出来的中点会落在行间的空白上，
        腿踩过去看着像踩空。凑不齐就返回 None，交给调用方当普通落空处理。
        """
        picked = OcrWorker.phrase_words(surface, lines)
        if not picked:
            return None
        return (sum(p.cx for p in picked) / len(picked), picked[0].cy)

    @staticmethod
    def phrase_words(surface: str, lines):
        """按行找出构成 `surface` 的那些 `OcrWord`（凑不齐返回空列表）。

        `phrase_point` / `phrase_box` 共用这一份判据：**同一行内凑齐才算**，
        跨行拼出来的中点会落在行间的空白上，腿踩过去看着像踩空。
        """
        if not surface or not lines:
            return []
        tokens = [t for t in re.split(r"[\s\-–—]+", surface.strip()) if t]
        if len(tokens) < 2:
            return []
        for line in lines:
            index = {}
            for word in getattr(line, "words", None) or []:
                index.setdefault(str(word.text).strip("-'.,:;").lower(), word)
            picked = [index.get(t.lower()) for t in tokens]
            if any(p is None for p in picked):
                continue
            return picked
        return []

    @staticmethod
    def phrase_box(surface: str, lines):
        """多词术语的**贴合框**：同一行各词框的外接矩形（图像像素）。

        单词术语直接查 `boxes` 就行；多词术语（`preventive maintenance`）在
        `boxes` 里没有键，必须把各单词的框并起来 —— 否则覆盖层只能退化成
        「按字号另估一只框」，又变回压在词上的那张独立卡片。
        """
        picked = OcrWorker.phrase_words(surface, lines)
        if not picked:
            return None
        left = min(p.left for p in picked)
        top = min(p.top for p in picked)
        right = max(p.right for p in picked)
        bottom = max(p.bottom for p in picked)
        return (left, top, max(1.0, right - left), max(1.0, bottom - top))

    def locate(self, words, positions, lines=None, boxes=None) -> None:
        """把 `words` 里每个词的「截图内坐标」换算成**屏幕坐标**（原地写回）。

        这一步**必须在 worker 里、用 worker 自己那份选区做**，不能挪到主线程的
        槽里读窗口状态：用户框一次要等 OCR 3~5 秒，中途很可能再框一次，
        窗口上的 `_capture_rect` 会被覆盖 —— 那样第一次的结果就会被算到
        第二次的坐标系上，八条腿齐齐踩到一片空白。

        单独抽成方法还有一个好处：测试里只替换 `run()`（假 OCR 结果）、
        其余照走生产代码，这条换算也在被测之列。
        """
        rect, dpr = self.capture_rect, (self.dpr or 1.0)
        if rect is None or dpr <= 0:
            return
        for item in words:
            surface = item.get("surface")
            point = positions.get(surface)
            box = (boxes or {}).get(surface)
            if not point and surface and " " in surface:
                point = self.phrase_point(surface, lines)
                box = self.phrase_box(surface, lines)
            if point:
                item["screen_pos"] = (rect.x() + point[0] / dpr,
                                      rect.y() + point[1] / dpr)
            if box:
                # 换算顺序和 `screen_pos` 严格一致：先除 DPR，再加选区原点。
                # 覆盖层拿到的就是**逻辑像素**的屏幕矩形，可以直接画。
                item["screen_box"] = (rect.x() + box[0] / dpr,
                                      rect.y() + box[1] / dpr,
                                      box[2] / dpr, box[3] / dpr)

    def run(self) -> None:
        started = time.perf_counter()
        timings = {}
        words, error = [], ""
        analysis = {}
        positions, boxes, lines = {}, {}, []
        engine_note = ""
        try:
            # ★ 引擎切换的唯一落点（任务书 §3.2）：**只换推理实现**，
            #   下游的词典 / 词框 / 八腿链路吃的还是同一套 `OcrLine`。
            #   `engine_lines()` 返回的 `note` 非空 = 发生了回退，
            #   这里把它塞进 meta，由主线程明确告诉用户 —— 不静默假装在跑 Paddle。
            from ocr_adapter import engine_lines
            t0 = time.perf_counter()
            lines, self.engine_id, engine_note = engine_lines(self.array)
            timings["ocr_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
            # ★ min_conf 过滤：启动台新增的「最小置信度」阈值。
            #   score 缺失或为 0 时视为通过（兼容旧引擎 / 合成测试图）。
            if self.min_conf > 0:
                lines = [ln for ln in lines
                         if getattr(ln, "score", None) is None
                         or ln.score <= 0
                         or ln.score >= self.min_conf]
            text = "\n".join(line.text for line in lines)
            # 候选池 = `max(48, 用户上限)`：`scan_text` 先按考纲/难度排好一整列，
            # 再由 `prepare_local` 按用户的「最大识词」截断。池子比截断值还小的话，
            # 用户把滑杆拖到 48 也只能拿到池子里那点词 —— 那是假象，不是筛选结果。
            t0 = time.perf_counter()
            words = self.lexicon.scan_text(
                text, mode=self.mode, limit=max(48, int(self.limit)),
                skip_stopwords=self.skip_stopwords)
            timings["lexicon_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
            # ★ 任务书 §5.1：默认识词链路**不发云端请求**。
            #   以前这里同步调 `LearningRouter.select()`，没配 key 走异常兜底、
            #   配了 key 要等 12 秒，用户看到的是「蜘蛛踩词慢」。
            #   现在只做本地规则排序 + 词典标注（`source='local'`），
            #   云端语境分析改成结果卡上的按钮（`ai/context_request.py`）。
            from ai.router import LearningRouter
            t0 = time.perf_counter()
            words, analysis = LearningRouter().prepare_local(
                text, words, self.learning_history, self.mode, self.limit)
            timings["local_analysis_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
            # 记录每个单词在**截图内**的位置，供八条腿踩上去
            for line in lines:
                for word in line.words:
                    positions.setdefault(word.text, (word.cx, word.cy))
                    # ★ 词**本体**的外接框（图像像素）。`_snap_edges` 已经按墨迹
                    #   投影收紧过左右上下四条边，这里原样带上游，覆盖层就不必
                    #   「拿中心 + 字号」再估一只 —— 那只框既盖住原词又会飘在上方。
                    #   同一个词在选区里出现多次时，这里记的是**第一次**出现的位置
                    #   （`lexicon.scan_text` 按 lemma 去重，一个词本来只出一张卡，
                    #   所以「一个词一个落点」和上游是一致的）；
                    #   队列层的重复由 `scan_session` 的词级 `word_id` 保证不撞车。
                    boxes.setdefault(
                        word.text,
                        (word.left, word.top,
                         max(1.0, word.right - word.left),
                         max(1.0, word.bottom - word.top)))
            # ★ `lines` 必须原样传进 `locate`：多词术语的落点/词框
            #   （`phrase_point` / `phrase_box`）要靠行里的 `OcrWord` 现算，
            #   `meta["lines"]` 落盘时已经压成 (text, box) 元组、不够用了。
            t0 = time.perf_counter()
            self.locate(words, positions, lines, boxes)
            timings["locate_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        except Exception as error_obj:          # noqa: BLE001
            error = str(error_obj)
        self.engine_note = engine_note
        timings["total_worker_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        self.done.emit(words, {"positions": positions,
                               "analysis": analysis,
                               "timings": timings,
                               "boxes": boxes,
                               "engine": self.engine_id,
                               "engine_note": engine_note,
                               "lines": [(ln.text, ln.box) for ln in lines]}, error)


class PetWindow(QWidget):
    """桌宠本体。"""

    def __init__(self, lexicon, wordbook, sprite_w: float = 360.0,
                 base_scale: float = 1.0, settings=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.OpenHandCursor)

        self.lexicon = lexicon
        self.book = wordbook
        #: 启动台的设置存储（可选）。有了它，右键切皮肤才能回写、
        #: 下次开启动台时高亮才对得上。没有（比如 --selftest）就只切不存。
        self.settings = settings
        self.spider = CS.Spider(size=1.0)
        self.spider.origin_px = (0.0, 0.0)
        self.painter = SpiderPainter()
        #: 皮肤只存在于渲染层，不参与 Spider 的状态机。
        if settings is not None:
            try:
                self.painter.set_skin(settings.get("skin"))
            except Exception as error:          # noqa: BLE001
                _log("[skin] 初始皮肤 %r 不合法，用默认: %r"
                     % (settings.get("skin"), error))
        self.skin_id = self.painter.skin_id
        # 初始皮肤的身体放大倍数先同步一次，别等第一帧画面才生效（见 _in_thorax）。
        self.spider.body_scale = self.painter.skin_spec().body_scale

        self.base_sprite_w = sprite_w
        self.scale = base_scale
        self.on_top = True
        #: 空处点击是否穿透到下层窗口（事件级命中测试，见 nativeEvent）
        self.click_through = True

        #: 「折叠（无腿模式）」—— 常驻状态，不是一次性动画。
        #:
        #: 为什么不能只靠 `play("hide_legs")`：形变播完 `self.effect` 一清空，
        #: `_current_tf()` 就变回 `IDENT`（retract=0），收进去的腿会当场弹回来。
        #: 所以折叠必须有独立状态兜底，见 `_leg_retract()`。
        self.folded = False
        #: 切换折叠时的起始收腿深度：半路反向（收一半又点展开）时从这里接着走，
        #: 腿才不会先弹出去再收回来。
        self._leg_from = 0.0

        # 状态机
        self.state_name = "idle"
        self.state_t = 0.0
        self.effect = None           # (name, 起始时刻, 时长)
        self._last = time.monotonic()
        self._last_active = time.monotonic()
        #: 空闲降频状态（见 `IDLE_TICK_MS`）：连续静止帧计数 + 当前是否已降频
        self._idle_frames = 0
        self._downshifted = False

        # 交互
        self.dragging = False
        self._pressed = False
        self._press_global = QPoint()
        self._press_center = QPoint()
        self._press_on_head = False
        #: 这次按下是不是「双击的第二下」—— 双击后跟的那个 release
        #: 不能再启动单击定时器，否则 200ms 后会再开一次框选（两个全屏遮罩叠着）
        self._dbl = False

        # 位移：走 or 跳
        #
        # ★ 唯一权威是 `self.mover`（`locomotion.MotionController`，任务书 §9.2A）：
        #   根节点位置、走/跳决定、跳跃四段（蓄力/腾空/落地/恢复）全在里面推进，
        #   和踩词覆盖层用的是**同一个类**。下面这个 `_travel` 只是这一段的**快照**
        #   （起点/终点/起始时刻/时长/是否跳跃），给旧调用方、测试和探针读；
        #   它不作为第二个积分器参与位移计算，所以两处不会各写一半 `center`。
        #   谁把 `_travel` 置成 None（拖动、覆盖层接手、取消），`_tick` 就在下一帧
        #   `mover.cancel()` —— 控制器只在 `_travel is not None` 时推进。
        self.mover = locomotion.MotionController(
            (0.0, 0.0), on_root=self._apply_travel_root,
            speed=WALK_SPEED, jump_seconds=JUMP_DURATION, arc=JUMP_ARC)
        self.mover.bind_spider(self.spider)
        self._travel = None       # (from, to, t0, dur, jump)
        self._travel_done = None   # 到位后的回调
        self.behavior_mode = "idle"
        self._behavior_next_pick = 0.0
        self._behavior_pause_until = 0.0
        self._behavior_last_mouse = None
        self.scan_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self.scan_shortcut.setContext(Qt.ApplicationShortcut)
        self.scan_shortcut.activated.connect(self.start_capture)
        self._global_scan_hotkey = _GlobalScanHotkey(self.start_capture)
        QApplication.instance().installNativeEventFilter(self._global_scan_hotkey)
        if not self._global_scan_hotkey.registered:
            _log("[hotkey] 全局 Ctrl+Shift+S 注册失败，保留应用内快捷键")

        # 识词
        self.capture_mode = "cet6"
        # 「一次最多处理多少个词」。2026-10-18 之前这里是 8，等于把腿的条数
        # 当成词数上限（第 9 个之后静默丢掉）。现在八条腿只是**并行度**，
        # 队列会分批往前踩，所以兜底初值跟启动台默认值走。
        self.capture_limit = int(SETTINGS_DEFAULTS["max_words"])
        self.capture_skip_stopwords = True
        #: 最小置信度阈值（启动台新增，源程序原本没有）。0 = 不过滤。
        self.min_conf = 0.0
        #: 是否弹出释义卡（启动台的「显示释义卡」开关）
        self.show_meaning_card = True
        #: 收回回调：由 main.py 在部署时设置，点右键「回到启动台」触发
        self.recall_callback = None
        self._overlay = None
        self._capture_busy = False   # 框选遮罩已起或已排期，防重入
        self._workers = []
        self._pending_rect = None
        #: 最近一次识别的选区与 DPR（屏幕坐标换算的输入），存在窗口上而不是 worker 上
        self._capture_rect = None
        self._capture_dpr = 1.0
        self._words_pending = None   # OCR 未回时先记下选区，动画先行
        #: 识别结果**拿在手上还没踩词**的那一份 (`aim_words`, `words`)。
        #: 调位可能被点击 / 新的调位 / 再次框选打断，靠它兜底：只要它还非空、
        #: 又没有正在进行的调位，`_tick` 一定会把瞄准层起来（见 `_fire_aim`）。
        self._aim_pending = None
        self._aim_at = None          # 到点就踩词（GRACE 秒后）

        self.bubble = BubbleWindow()
        self._dialogs = {}

        #: ---- 蜘蛛感应（任务书 §7）：默认**关**，用户不主动开就绝不看屏幕 ----
        self.sense_enabled = False
        self.sense_session = None
        self.sense_worker = None
        self._sense_overlay = None
        self._sense_timer = None
        #: 已经请求停止、但还卡在**当前这一次识别**里的线程（一次 OCR 在本机
        #: 可达十几秒，见 `dist/sense/shape_probe.log`）。GUI 线程不能为了等它
        #: 把界面冻住，所以先记下，`shutdown()` 退出时再收尾（§7.2）。
        self._sense_lingering = []
        #: 频率兜底初值；真正生效的值来自启动台 `sense_hz`
        self.sense_hz = float(SETTINGS_DEFAULTS.get("sense_hz", 1.0))

        #: 蜘蛛身体中心（屏幕坐标）—— 取屏幕前必须先有值
        self.center = QPoint(0, 0)
        self._last_x = 0.0           # 上一帧体心位置，用来算身体位移喂给步态
        self._last_y = 0.0
        screen = self._screen_rect()
        self.center = QPoint(screen.right() - 170, screen.bottom() - 150)
        self._last_x = float(self.center.x())
        self._last_y = float(self.center.y())
        # 控制器里那份 root 只是逐帧积分的起点，窗口位置才是权威（见 `sync_root`）。
        self.mover.sync_root((float(self.center.x()), float(self.center.y())))

        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(200)
        self._click_timer.timeout.connect(self._on_single_click)

        self._apply_geometry()
        self.show()
        self.play("pop")

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(TICK_MS)

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._idle_say)
        self._idle_timer.start(random.randint(45000, 85000))

        self._make_tray()
        # 带 context（self）：桌宠在 600ms 内被收回时，这个回调自动取消，
        # 不会打在一个已经关掉的窗口上。
        QTimer.singleShot(600, self, lambda: self.say(
            f"我是{content.PET_NAME}，点我的头就能识词。", 3400))

    # ------------------------------------------------ 几何
    @property
    def sprite_w(self) -> float:
        return self.base_sprite_w * self.scale

    @property
    def unit(self) -> float:
        """局部坐标 → 像素的缩放。

        以前每次访问都重算一遍 `unit_for_width`（一帧里 paint/state/命中
        会读三四次）；它是纯函数，按 `sprite_w` 缓存即可，缩放变了自动失效。
        """
        key = self.sprite_w
        if key != getattr(self, "_unit_key", None):
            self._unit_key = key
            self._unit_value = SpiderPainter.unit_for_width(key)
        return self._unit_value

    #: 窗口尺寸的余量（像素）：腿的描边、关节红点、瞄准辉光都在这之内
    WINDOW_MARGIN = 12.0

    def _window_size(self) -> tuple:
        """窗口要装得下整只蜘蛛。

        没有遮罩以后，**窗口边界是唯一还能把蜘蛛切掉的东西**，所以这里按几何
        上界来算：每条腿「髋部偏移 + 腿伸直的长度」，取最大值再留一点余量。

        原来是拍脑袋的 2.45/1.95 倍，纵向只有 444px（半窗 222px）。可
        行走时脚会被步态甩到 226px 外、识词时能伸到 259px —— 朝上下伸的腿
        会被窗口边缘切掉几个像素（`test_click_through.py` 的 240 帧用例抓到）。
        窗口大一点不花钱：透明处本来就穿透，看不见也不挡鼠标。
        """
        unit = self.unit
        half = 0.0
        for leg in self.spider.legs:
            if leg.palp:
                continue
            hip = math.hypot(leg.hip_pos[0], leg.hip_pos[1])
            half = max(half, hip + leg.full)          # 局部单位
        side = int(math.ceil(half * unit + self.WINDOW_MARGIN)) * 2
        return side, side

    def _apply_geometry(self, resize: bool = True) -> None:
        if resize:
            width, height = self._window_size()
            if self.width() != width or self.height() != height:
                self.resize(width, height)
        self.move(int(self.center.x() - self.width() / 2),
                  int(self.center.y() - self.height() / 2))

    def _canvas_origin(self) -> tuple:
        return (self.width() / 2.0, self.height() / 2.0)

    def _scene_transform(self) -> QTransform:
        """本帧的「一次性形变」矩阵（跳跃/压扁/抖动/旋转）。

        `paintEvent` 与鼠标命中测试（`_to_local`）必须共用这一份，
        否则跳跃腾空时点和画就对不上了。
        """
        tf = self._current_tf()
        if not (tf.dx or tf.dy or tf.rot
                or tf.sx != 1.0 or tf.sy != 1.0):
            return None
        ox, oy = self._canvas_origin()
        k = self.sprite_w / anim.REFERENCE_WIDTH
        transform = QTransform()
        transform.translate(ox + tf.dx * k, oy + tf.dy * k)
        if tf.rot:
            transform.rotate(tf.rot)
        if tf.sx != 1.0 or tf.sy != 1.0:
            transform.scale(tf.sx, tf.sy)
        transform.translate(-ox, -oy)
        return transform

    # ------------------------------------------------ 鼠标命中（替代窗口遮罩）

    #: 「点算点在腿上」的宽松度（屏幕像素，单边）。
    #: 腿本体的描边只有 ~3.5px，判定放宽到 12px，点腿才好点。
    HIT_LEG_PAD_PX = 6.0
    #: 身体（矩形 + 三角）的容差（屏幕像素，单边）：够吃掉取整误差与手抖，
    #: 又远小于身体尺寸，不会把旁边那圈柔光也算成实体。
    HIT_BODY_PAD_PX = 2.0
    #: 腿被收到这个深度以上，就认为它「已经离位」、不再吃点击。
    #:
    #: painter 是按 `retract` 把膝/脚往髋部 lerp 的，而 `covers()` 只认
    #: **原位**的腿。不在这里收口的话，一条正在往回缩的腿会在它原来的位置
    #: 留下一块「看不见却点得中」的空地 —— 和删掉的那条尾巴是同一个坑。
    #: 取 0.25 而不是 0：留一点余量，免得刚起步的几帧就判成离位。
    LEG_HIT_MAX_RETRACT = 0.25

    def _local_per_px(self) -> float:
        """1 个窗口像素 = 多少局部单位（含一次性形变的缩放）。

        弹出/压扁/抖动会把整个蜘蛛缩放，局部坐标系跟着被拉长缩短：
        `squash` 后半段整体缩到六成时，1 局部单位只剩 0.7px，写在局部坐标里的
        容差（1 单位）就只剩 0.7px —— 一次取整就把它吃光。所以容差要按
        窗口像素给、在运行时换回局部单位。
        """
        k = self.unit
        transform = self._scene_transform()
        if transform is not None:
            k *= max(1e-3, math.hypot(transform.m11(), transform.m12()))
        return k

    def _to_local(self, px: float, py: float):
        """窗口像素 → 蜘蛛局部坐标（含朝向与一次性形变）。"""
        point = (float(px), float(py))
        transform = self._scene_transform()
        if transform is not None:
            inverted, ok = transform.inverted()
            if ok:
                mapped = inverted.map(QPointF(point[0], point[1]))
                point = (mapped.x(), mapped.y())
        self.painter.setup(self._canvas_origin(), self.unit, self.spider.heading)
        return self.painter.to_local(point[0], point[1])

    def _on_spider(self, px: float, py: float) -> bool:
        """这个窗口像素是不是落在蜘蛛身上。"""
        local = self._to_local(px, py)
        per_px = self._local_per_px()
        # 腿一旦开始收（折叠、或收/伸动画进行到一半），就不再吃点击：
        # 它已经不在原位了，而 `covers()` 只认原位。不收口就会留下
        # 一圈「看不见但点得住」的空地 —— 和被删掉的那条尾巴是同一个坑。
        in_place = self._leg_retract() < self.LEG_HIT_MAX_RETRACT
        leg_pad = self.HIT_LEG_PAD_PX / per_px if in_place else 0.0
        return self.spider.covers(
            local,
            leg_pad=leg_pad,
            body_pad=max(self.spider.HIT_PAD, self.HIT_BODY_PAD_PX / per_px))

    def nativeEvent(self, event_type, message):
        """在 `WM_NCHITTEST` 里按真实轮廓决定「吃不吃这次点击」。

        为什么不设窗口遮罩（`setMask`）：
            · 透明窗口（`WA_TranslucentBackground`）在 Windows 上本身就是
              按 alpha 抠图的图层窗口，alpha=0 的像素**天然就不接鼠标** ——
              遮罩能做的事，系统已经做了。
            · 遮罩唯一多出来的作用，是连蜘蛛周围那圈 alpha 1~8 的柔光也
              一起穿透。而遮罩的代价是每帧调一次 Win32 `SetWindowRgn`：
              分层透明窗口反复改窗口区域会让 DWM 不停重算，
              拖动时就是卡顿；而且遮罩一旦和画面不同步（朝向差一个角、
              形变没跟上），蜘蛛就会被裁得支离破碎。
            · 事件级命中测试没有这两个问题：每次点击现算，永远和画面一致，
              平时零开销。
        """
        if event_type == b"windows_generic_MSG" and self.click_through:
            # 拖动中一律自己接着：手甩快一点光标会离开轮廓，
            # 这时候要是返回穿透，拖动会中途断掉。
            if not (self.dragging or self._pressed):
                msg = MSG.from_address(int(message))
                if msg.message == WM_NCHITTEST:
                    sx = ctypes.c_short(msg.lParam & 0xFFFF).value
                    sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    dpr = self.devicePixelRatioF() or 1.0
                    geo = self.geometry()
                    # 物理屏幕像素 → 本窗口逻辑像素
                    x = (sx - geo.left() * dpr) / dpr
                    y = (sy - geo.top() * dpr) / dpr
                    if not self._on_spider(x, y):
                        return True, HTTRANSPARENT
        return False, 0

    def set_click_through(self, enabled: bool) -> None:
        """空处点击是否穿透到下层窗口。关掉的话，透明矩形会挡住桌面。"""
        self.click_through = bool(enabled)
        self.say("空处点击：%s" % ("穿透" if enabled else "不再穿透，会挡住下面的窗口"),
                 2000)

    def _screen_rect(self) -> QRect:
        from PySide6.QtGui import QGuiApplication
        point = getattr(self, "center", None)
        screen = QGuiApplication.screenAt(point) if point else None
        screen = screen or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def char_rect(self) -> QRect:
        """蜘蛛身体的外接矩形（气泡定位、对话框避让都用它）。

        按 **painter 的真实画法**算：三角头顶端 = `(HEAD_OFF + HEAD_TRI_LEN)`
        个局部单位，头胸后沿 = `THORAX[0] * THORAX_SCALE`，半高取「矩形半高
        与三角底半宽里的较大者」再加一点余量。以前用的是 `ABD_OFF + SPIN_OFF`
        来当后沿（那是尾巴的位置），尾巴删了以后那样算会多出一大截空白。
        """
        unit = self.unit
        front = (CS.HEAD_OFF + CS.HEAD_TRI_LEN) * unit
        back = CS.THORAX[0] * CS.THORAX_SCALE * unit
        half_h = max(CS.THORAX[3] * CS.THORAX_SCALE * 0.5, CS.HEAD_TRI_HALF) * unit + 6.0
        return QRect(int(self.center.x() + back), int(self.center.y() - half_h),
                     int(front - back), int(half_h * 2))

    # ------------------------------------------------ 渲染
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        origin = self._canvas_origin()
        state = self._build_state()

        # 一次性形变（跳跃弧线等）绕体心作用。矩阵由 `_scene_transform` 统一给出，
        # 遮罩用的是同一份 —— 两边各算各的迟早会错位。
        transform = self._scene_transform()
        painter.save()
        if transform is not None:
            painter.setTransform(transform, True)

        self.painter.paint(painter, self.spider, state,
                           unit=self.unit, origin_px=origin)
        painter.restore()
        painter.end()

    def _current_tf(self) -> anim.Tf:
        """一次性形变；没有时返回单位变换（本体不做呼吸动画，那是 crawler 的步态负责的）。"""
        if self.effect is not None:
            name, started, duration = self.effect
            return anim.apply_effect(name, (time.monotonic() - started) / duration)
        return anim.IDENT

    def _drop_effect(self) -> None:
        """清掉一次性形变。

        **收腿 / 伸腿不能清**：它们是状态切换动画，`retract` 的连续性全靠它。
        清了之后 `_leg_retract()` 会立刻落到 `self.folded` 那一端，
        腿当场从半路瞬移到位（看着像抽搐）。按下鼠标、开始框选、开始走位
        这三处以前都是无脑 `self.effect = None`。
        """
        if self.effect is not None and self.effect[0] not in anim.LEG_EFFECTS:
            self.effect = None

    def _leg_retract(self) -> float:
        """本帧该把腿收到什么深度（0 = 全伸，1 = 全收）。

        单独抽出来是因为 **不能直接读 `Tf.retract`**：
        `jump`/`squash`/`shake` 这些反馈类形变的 `retract` 恒等于 0，
        读它的话「折叠着的时候被压扁一下」腿就全弹出来了。
        所以只有正在播腿动画时才认它，其余时候一律看 `self.folded`。

        半路反向（收一半又点展开）时，从切换那一刻的实际深度 `_leg_from`
        接着往新目标插值，而不是从动画的固定端点起步 —— 否则腿会先跳一下。
        """
        if self.effect is not None and self.effect[0] in anim.LEG_EFFECTS:
            name = self.effect[0]
            raw = self._current_tf().retract
            if name == "hide_legs":
                progress, target = raw, 1.0        # eff_hide_legs: 0 → 1
            else:
                progress, target = 1.0 - raw, 0.0  # eff_show_legs: 1 → 0
            return self._leg_from + (target - self._leg_from) * progress
        return 1.0 if self.folded else 0.0

    def _build_state(self) -> SpiderState:
        name = self.state_name
        if self.dragging or (self._travel is not None and not self._travel[4]):
            name = "crawl"
        # 收腿/伸腿是一次性形变，但**腿的收缩幅度必须走 SpiderState**：
        # painter 是在 `_paint_legs` 里按 state.leg_retract 把膝/脚往髋部 lerp 的，
        # 不走这里的话形变就只有身体在缩放、腿纹丝不动。
        tf = self._current_tf()
        return SpiderState(
            dim=CS.MODE_DIM.get(name, 1.0),
            focus=(self.state_name == "think"),
            joint_glow=anim.joint_glow(self.state_name, self.state_t),
            heading=self.spider.heading,
            moving=(self.dragging or
                     (self._travel is not None and not self._travel[4])),
            leg_retract=self._leg_retract(),
        )

    def _hit(self, px: float, py: float):
        """画布像素 → 头/身体命中测试。

        注意别在这里写死 heading —— 腿与「头的方向」都是相对朝向定义的，
        写死 0 的话蜘蛛转过身后，点头就点不中头了。
        """
        return self.spider.hit_test(self._to_local(px, py))

    # ------------------------------------------------ 主循环
    def _busy(self) -> bool:
        """这一帧有没有「必须逐帧推进」的事。判据宁松勿紧：漏判一次只是少省电，
        误判静止会让动画卡住。"""
        if (self.effect is not None or self.dragging or self._travel is not None
                or self._aim_pending is not None or self._capture_busy
                or "aim" in self._dialogs):
            return True
        # 步态没站定（任何一条腿还在迈 / 徽章站姿还没混到位 / 身体还在滑）
        spider = self.spider
        if spider._idle_pose_t < 0.99:
            return True
        if any(leg.stepping for leg in spider.legs):
            return True
        # 逐腿折叠/伸回是纯状态缓动，没有事件源，必须算「有事做」
        if spider.folding():
            return True
        # 落地回弹 / 蓄力释放 / 走路起伏还没衰减完 —— 降频会让最后那一点
        # 回弹以 60ms 的步长走，看着像「啪」地一下定住。
        if (abs(spider.body_bob) > 0.02 or spider.crouch > 1e-3
                or spider.landing_compression > 1e-3):
            return True
        vx, vy = spider.velocity
        return math.hypot(vx, vy) > 0.5

    def _set_idle(self, idle: bool) -> None:
        """空闲降频：连续静止够久才降，一动立刻恢复 60fps。"""
        if idle:
            self._idle_frames += 1
            if self._idle_frames >= IDLE_SETTLE_FRAMES and not self._downshifted:
                self._downshifted = True
                self._timer.start(IDLE_TICK_MS)
        else:
            self._idle_frames = 0
            if self._downshifted:
                self._downshifted = False
                self._timer.start(TICK_MS)

    def wake(self) -> None:
        """从空闲降频里唤醒（任意输入、或外部改了状态时调用）。"""
        self._last_active = time.monotonic()
        if self._downshifted:
            self._idle_frames = 0
            self._downshifted = False
            self._timer.start(TICK_MS)
            self.update()

    def event(self, e):
        # 唤醒钩子挂在事件入口：鼠标/滚轮/键盘任意一发都回到 60fps。
        # 不用 HoverMove 感知「路过」—— 桌宠是穿透点击窗， hover 本就不开。
        et = e.type()
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                  QEvent.Type.MouseMove, QEvent.Type.Wheel,
                  QEvent.Type.KeyPress):
            self.wake()
        return super().event(e)

    def _tick(self) -> None:
        if self._downshifted and not self._busy():
            # 降频态且仍然静止：模型一步都不用推进，画面一个像素都不会变。
            # `_last` 不在这里更新 —— dt 是「距上次真正推进的时间」，
            # 唤醒后第一帧会拿到略大的 dt（已钳在 0.05），动画不会跳。
            return
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        self.state_t += dt
        self._tick_behavior(now)

        if self.effect is not None:
            name, started, duration = self.effect
            if now - started >= duration:
                self.effect = None
                # 这里**原来**无条件接一段 `show_legs`（L/H 彩蛋的「收 → 伸」演示）。
                # 但折叠现在是一个常驻状态：收完必须停住，由 `self.folded` 继续
                # 维持 retract=1。要不要伸回去由 `set_folded(False)` 决定，
                # 不再由动画自己决定 —— 否则菜单一折叠，0.55 秒后腿自己弹回来了。
                # 到位后 `_leg_retract()` 自然落到 `self.folded` 那一端，无需额外处理。
            elif name == "spin":
                # 转身：转的是**模型里的朝向**，不是画好的那张图。
                # 身体一转，`Spider.turn()` 会把钉在世界上的脚在体坐标系里反向旋转，
                # 偏离静止位 → 步态阈值触发 → 腿跟着一蹬一蹬地迈。
                # 走匀角速度，整圈 SPIN_ANGLE 在 duration 内转完（有 easing 的话
                # 转身会「甩头」，而且慢下来那一段腿会明显跟不上）。
                self.spider.heading += anim.SPIN_ANGLE * dt / max(duration, 1e-3)
                # 速度清零：`update()` 里 heading 会朝**速度方向**插值，
                # 不清零的话自转和那个插值会打架，转不满一圈就被拽回去。
                self.spider.velocity = (0.0, 0.0)

        # 位移：近距离走、远距离跳 —— 控制器逐帧推进，`_travel` 只是这一段快照
        if self._travel is not None:
            _frm, to, _t0, _dur, _is_jump = self._travel
            self.mover.step(dt)
            if not self.mover.moving:       # 走/跳的最后一段（落地）结束
                self.center = QPoint(to)
                finished = self._travel_done
                self._travel = None
                self._travel_done = None
                self._set_state("idle")
                # 移动结束后保持自然站姿，不再播放“压扁”停止反馈；跳跃自身的
                # 落地压缩仍由 MotionController/crawler_spider 负责。
                if finished:
                    finished()
        elif self.mover.movement_mode != locomotion.IDLE:
            # 快照被别的入口清空了（按下打断、覆盖层接手、任务取消）：控制器必须
            # 跟着停，并且把积分状态对回窗口现在真的在哪儿的位置。
            self.mover.cancel()
            self.mover.sync_root((float(self.center.x()), float(self.center.y())))

        # ★ 兜底：识别结果还攥在手上，就必须把瞄准层起来。
        #
        # 调位这一步（走去最优停靠点）原本是**唯一**通向 `_launch_aim` 的路，
        # 而它挂在 `_travel_done` 上 —— 这个回调用处太多、太容易被冲掉：
        #   · `mousePressEvent` 里「按下即打断位移」会把它清掉；
        #   · 再来一次 `travel_to` 会把它覆盖掉；
        #   · `start_capture()` 也会清。
        # 任何一条走过去，用户看到的就是「八个词框和八条腿**再也不会出现**」
        # ——这正是「不是百分百触发」的真身。所以改成：只要 `_aim_pending`
        # 还在、且当前没有正在进行的调位、也没在被拖走，就（等一个 AIM_GRACE
        # 让这次的点击判定先走完）直接踩词。调位只是「站得更好看」，不是触发的前提。
        # 拖动中要等一下：手正捏着蜘蛛，这时候把本体一藏、覆盖层一铺，
        # 拖动会当场断掉。松手后这一条自然会满足。
        if (self._aim_pending is not None and self._travel is None
                and not self.dragging):
            if self._aim_at is None:
                self._aim_at = now + AIM_GRACE
            elif now >= self._aim_at:
                self._fire_aim()

        # 喂给步态引擎的模式（§9.2C.3「空中不应继续执行普通地面迈步逻辑」）：
        # 跳跃段里**只有蓄力和腾空**走 jump（腿收拢、不迈步），
        # 转身预瞄和落地那两档还在地上，照常 crawl —— 落地后要重新建立支撑点。
        #
        # ★ 覆盖层开着的时候，推进身体的是**它那台**控制器（`_advance_body`），
        #   本体那台已经被 `_travel = None` 空转掉了 —— 所以「此刻是不是腾空」
        #   必须问覆盖层，不能问自己。两边共用同一个 `Spider`，但每个参数只有
        #   一个写的人（§9.2E）。
        overlay = self._dialogs.get("aim")
        mover = getattr(overlay, "mover", None) or self.mover
        traveling = self._travel is not None or overlay is not None
        segment = mover.movement_mode
        if self.dragging:
            mode = "crawl"
        elif traveling and segment in (locomotion.JUMP_PREPARE,
                                       locomotion.JUMP_AIRBORNE):
            mode = "jump"
        elif traveling:
            mode = "crawl"
        else:
            mode = self.state_name
        if mode not in CS.MODES:
            mode = "idle"
        # 身体位移必须喂给引擎：脚钉在原地，身体一动静止位就相对偏移，
        # 偏移够大才迈步 —— 这正是阈值步态的驱动力。
        #
        # **必须换成局部单位**：`advance()` 活在蜘蛛的局部坐标系里
        # （`to_screen` 会把局部坐标乘 `unit` 才是像素），喂像素进去等于
        # 把位移放大 `unit` 倍。桌宠放大到 200% 时 unit≈2.5，脚一帧被拖
        # 两倍半的行程，步态全程贴着硬上限跑，腿就一直「啪、啪」地抽。
        #
        # speed 不再从外面传：引擎现在直接从 velocity 推算（拖动时鼠标多快
        # 就多快）。以前这里写死 140.0，导致拖动时步态阈值永远是「快走」档，
        # 抬腿幅度也和真实速度脱节。
        unit = self.unit
        motion = ((float(self.center.x()) - self._last_x) / unit,
                  (float(self.center.y()) - self._last_y) / unit)
        self._last_x, self._last_y = float(self.center.x()), float(self.center.y())
        # ★ 把「这一刻腿收到多深」交给模型：右键折叠走的是渲染层的
        #   `leg_retract` 缓动，`leg.fold` 一点都不动 —— 不写进去的话，
        #   折叠时身体永远不会朝头部缩（`Spider.fold_depth` 只看 `body_fold`）。
        #   给的是**这一帧的实际插值深度**，所以身体和腿是同步缩的，
        #   半路点「展开」也能接着往回长，不会跳一下。
        self.spider.retract_fold = self._leg_retract()
        self.spider.update(dt, mode, None, motion=motion)

        # 这里以前每帧重建一次窗口遮罩（setMask），是拖动卡顿的根源：
        # 分层透明窗口反复 SetWindowRgn 会让 DWM 不停重算，而且遮罩一旦和
        # 画面不同步就会把蜘蛛裁碎。现在改为事件级命中测试，主循环里零开销。
        self._apply_geometry(resize=False)
        self.update()
        # 空闲降频记账：本帧推进完之后再看「还有没有事要做」。
        # 放在 `_apply_geometry` 之后，因为它可能刚把尺寸变回来（缩放 = 忙）。
        self._set_idle(not self._busy())

    def set_behavior_mode(self, mode: str) -> None:
        mode = str(mode or "idle").lower()
        if mode not in ("idle", "free_move", "follow_mouse"):
            mode = "idle"
        self.behavior_mode = mode
        self._behavior_next_pick = 0.0
        self._behavior_last_mouse = None
        if mode == "idle" and self._travel is not None and getattr(self, "_travel_source", "") == "behavior":
            self._travel = None
            self._travel_done = None
            self.mover.cancel()
            self.mover.sync_root((float(self.center.x()), float(self.center.y())))
        self.wake()

    def _tick_behavior(self, now: float) -> None:
        if self.behavior_mode == "idle" or self._overlay is not None or self.dragging:
            return
        if self._travel is not None or now < self._behavior_pause_until:
            return
        if self.behavior_mode == "follow_mouse":
            pos = QCursor.pos()
            last = self._behavior_last_mouse
            self._behavior_last_mouse = (pos.x(), pos.y())
            if last is not None and abs(pos.x()-last[0]) + abs(pos.y()-last[1]) < 4:
                return
            dx, dy = pos.x()-self.center.x(), pos.y()-self.center.y()
            dist = math.hypot(dx, dy)
            if dist < 150:
                return
            target = (pos.x()-dx/max(dist, 1)*105, pos.y()-dy/max(dist, 1)*105)
        else:
            if now < self._behavior_next_pick:
                return
            screen = QGuiApplication.screenAt(self.center) or QGuiApplication.primaryScreen()
            if screen is None:
                return
            r = screen.availableGeometry().adjusted(100, 100, -100, -120)
            target = (random.uniform(r.left(), r.right()), random.uniform(r.top(), r.bottom()))
        screen = QGuiApplication.screenAt(QPoint(int(target[0]), int(target[1]))) or QGuiApplication.primaryScreen()
        if screen is not None:
            r = screen.availableGeometry().adjusted(80, 80, -80, -100)
            target = (max(r.left(), min(r.right(), target[0])), max(r.top(), min(r.bottom(), target[1])))
        self._travel_source = "behavior"
        # 自由移动/跟随鼠标只走路，避免随机漫游突然起跳遮挡用户操作。
        self.travel_to(QPoint(int(target[0]), int(target[1])), force_jump=False)
        self._behavior_pause_until = now + 0.8
        self._behavior_next_pick = now + (2.5 if self.behavior_mode == "free_move" else 0.4)

    def _set_state(self, name: str) -> None:
        if self.state_name != name:
            self.state_name = name
            self.state_t = 0.0

    def play(self, effect_name: str, duration: float = None) -> None:
        duration = duration or anim.EFFECT_DURATION.get(effect_name, 0.6)
        self.effect = (effect_name, time.monotonic(), max(0.12, duration))
        # 形变可能由托盘菜单发起（不经过本窗口 event()），降频态要唤醒。
        self.wake()

    def spin_once(self) -> None:
        """原地转一圈。

        转身是**真的转身体**（`_tick` 里推进 `spider.heading`），脚钉在原地不动，
        所以八条腿会被步态系统驱动着依次倒换 —— 不是整张图打转。
        正在走位或正被拖着时不接：那时 heading 归速度方向管，插一脚会打架。
        """
        if self._travel is not None or self.dragging:
            return
        self.play("spin")

    def say(self, text: str, duration: int = 2600) -> None:
        # 收回后仍有排期的台词（`QTimer.singleShot(600, …)`）会落在这里：
        # 已经关掉的桌宠不该再弹气泡，否则桌面上会留下无主的小窗。
        if not self.isVisible():
            return
        if text:
            self.bubble.show_message(text, self.char_rect(), self._screen_rect(), duration)

    def _touch(self) -> None:
        self._last_active = time.monotonic()

    # ------------------------------------------------ 鼠标
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self._touch()
        pos = event.position().toPoint()
        self._pressed = True
        self.dragging = False
        self._press_global = event.globalPosition().toPoint()
        self._press_center = QPoint(self.center)
        # 头（三角）还是身（矩形）—— 语义严格按画出来的形状来，见
        # `crawler_spider.hit_test`。腿和空白都返回 None，等同于「身」。
        self._press_on_head = (self._hit(pos.x(), pos.y()) == "head")
        self._drop_effect()
        # **这里不再打断走/跳**。单纯按一下不该把「正在走向识词停靠点」掐掉：
        # 掐掉之后蜘蛛停在半路，够得着的词少一大半（实测 8 个词只剩 3 个踩得到）。
        # 真正要接管的是「拖」，所以改到 `mouseMoveEvent` 里、拖动成立的那一刻才打断。
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._pressed:
            return
        current = event.globalPosition().toPoint()
        delta = current - self._press_global
        if not self.dragging and (abs(delta.x()) > DRAG_THRESHOLD
                                  or abs(delta.y()) > DRAG_THRESHOLD):
            self.dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self._set_state("crawl")
            # 拖起来了：手要接管，打断正在进行的走/跳。
            # 但**识别结果不能跟着一起丢** —— 调位被拖断时把 `_aim_pending`
            # 留着，`_tick` 会在 AIM_GRACE 之后直接从当前位置把瞄准层起来
            # （以前这里把 `_travel_done` 一清，「八腿踩词」就永远不出现了）。
            self._travel = None
            self._travel_done = None
            if self._aim_pending is not None:
                self._aim_at = time.monotonic() + AIM_GRACE
        if self.dragging:
            self.center = self._press_center + delta
            self._clamp_to_screen()
            if self.bubble.isVisible():
                self.bubble.move(
                    int(self.char_rect().center().x() - self.bubble.width() / 2),
                    int(self.char_rect().top() - self.bubble.height() + 4))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        was_drag = self.dragging
        self._pressed = False
        self.dragging = False
        self.setCursor(Qt.OpenHandCursor)
        if self._dbl:
            # 这一下 release 是双击的第二下。**不能**启动单击定时器：
            # 双击已经在 `mouseDoubleClickEvent` 里开框选了，再启动一次
            # 会让 200ms 后再开一个全屏遮罩（两个叠着，选完一个另一个还晾在桌上）。
            self._dbl = False
        elif not was_drag:
            self._click_timer.start()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._click_timer.stop()
            self._pressed = False
            self.dragging = False
            self._dbl = True        # 标记「随后的 release 不算单击」
            self.start_capture()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.09 if delta > 0 else 1 / 1.09
        self.set_scale(self.scale * factor)

    def keyPressEvent(self, event):
        """键盘彩蛋：L / H 折叠与展开（和右键菜单同一件事）。

        以前这里是「收腿 → 自动伸腿」的一次性演示；折叠变成常驻状态之后，
        再接自动伸腿就自相矛盾了，所以改成切换。
        """
        if event.key() in (Qt.Key_L, Qt.Key_H):
            self.toggle_fold()
            event.accept()
            return
        super().keyPressEvent(event)

    def _clamp_to_screen(self) -> None:
        screen = self._screen_rect()
        margin = int(self.sprite_w * 0.35)
        self.center.setX(min(max(self.center.x(), screen.left() + margin),
                             screen.right() - margin))
        self.center.setY(min(max(self.center.y(), screen.top() + margin),
                             screen.bottom() - margin))

    def _on_single_click(self) -> None:
        """单击的语义：**点三角头 = 识词，点矩形身 = 拖动**。

        判定用的是 `hit_test` 的真形状（三角 / 矩形），所以戳到三角外面、
        或者点在后半身，都不会再误触发识词。
        身上那一下只负责「拖走」（按下即进拖动流程，见 `mousePressEvent`），
        单击本身不再附带任何动作 —— 随机跳一下 / 抖动一下会把蜘蛛挪出原位，
        和「待机时身体不动」冲突。
        """
        if self._press_on_head:
            self.start_capture()

    def travel_to(self, target: QPoint, done=None, force_jump: bool = None) -> None:
        """走到（或跳到）某个屏幕位置。

        近距离用八腿走（crawl 步态），远过阈值才跳跃 —— 阈值按**腿展**算，
        集中在 `locomotion`：跟着桌宠缩放走，还带滞回（目标在阈值附近抖几个像素
        不会走/跳反复切换），而且这一段一旦启动，`_travel[4]` 就锁定到落地。

        这里只**下决定 + 记快照**，位置由 `self.mover.step()` 每帧推进（§9.2A）。
        """
        # 不变式：**要走路就得有腿**。折叠着的时候腿是收起来的，
        # 真让它「crawl」出来就是本体在屏幕上平移，很怪。识别链路
        # （`start_capture`）已经会先伸腿，这里再兜一道，防止别的入口漏掉。
        if self.folded:
            self.set_folded(False, silent=True)
        target = QPoint(target)
        self._clamp_point(target)
        # 开局先对一次表：中途蜘蛛可能被拖走、被托盘挪过、上一段被别的入口取消，
        # 那些都不经过控制器（`sync_root` 的说明）。
        self.mover.sync_root((float(self.center.x()), float(self.center.y())))
        distance = math.hypot(target.x() - self.center.x(),
                               target.y() - self.center.y())
        threshold = locomotion.walk_jump_threshold(self.spider, self.unit)
        if distance < 2:
            # 已经在目标上了：**连正在跑的那一段也一起结束**。
            # 不然旧的 `_travel` / `_travel_done` 还挂着，会在几帧后自己
            # 「到位」，把蜘蛛再拖回上一个目标去（踩词时表现为「覆盖层都起来了，
            # 蜘蛛还在走」）。
            self.center = target
            self._travel = None
            self._travel_done = None
            self.mover.cancel()
            self.mover.sync_root((float(target.x()), float(target.y())))
            self.mover.choice = None
            self._set_state("idle")
            if done:
                done()
            return

        self.mover.set_waypoint(
            (float(target.x()), float(target.y())), threshold,
            force=(None if force_jump is None else
                   (locomotion.JUMP if force_jump else locomotion.WALK)))
        is_jump = self.mover.choice == locomotion.JUMP
        # 时长与控制器内部用的是**同一个公式**（`_begin_jump` 里那份），
        # 所以快照里的 `dur` 就是真实那一段的长度，不是估计值。
        duration = (locomotion.jump_duration(distance, threshold, JUMP_DURATION)
                    if is_jump
                    else max(0.25, distance / max(WALK_SPEED, 1.0)))
        self._travel = (QPoint(self.center), target, time.monotonic(),
                        duration, is_jump)
        self._travel_done = done
        self._set_state("jump" if is_jump else "crawl")
        self._drop_effect()

    def _apply_travel_root(self, point) -> None:
        """控制器的 `on_root`：身体新位置写回窗口。

        ★ 除了这里，`_tick` 里没有任何地方会为了位移写 `center` ——
          两个积分器各写一半是 §9.2A 点名要禁掉的毛病。
        """
        self.center = QPoint(int(round(point[0])), int(round(point[1])))

    @property
    def _movement_choice(self) -> str | None:
        """上一段的「走/跳」决定。滞回的历史只存在控制器里一份（§9.2A），
        这个名字留给旧调用方和测试读写。"""
        return self.mover.choice

    @_movement_choice.setter
    def _movement_choice(self, value) -> None:
        self.mover.choice = value

    def _clamp_point(self, point: QPoint) -> None:
        screen = self._screen_rect()
        margin = int(self.sprite_w * 0.45) + 20
        point.setX(min(max(point.x(), screen.left() + margin),
                       screen.right() - margin))
        point.setY(min(max(point.y(), screen.top() + margin * 0.6),
                       screen.bottom() - margin * 0.6))

    def _idle_say(self) -> None:
        if not self.dragging and self._travel is None and self.effect is None:
            self.say(content.bubble_for("idle"), 3000)
        self._idle_timer.start(random.randint(45000, 85000))

    # ------------------------------------------------ 缩放
    def set_scale(self, value: float) -> None:
        value = max(MIN_SCALE, min(MAX_SCALE, value))
        if abs(value - self.scale) < 0.001:
            return
        self.scale = value
        # 缩放可能来自托盘菜单/滚轮/启动台（tray 菜单不经过本窗口的 event()），
        # 空闲降频时必须显式唤醒，否则尺寸变了画面还停在旧帧上。
        self.wake()
        self._apply_geometry(resize=True)
        if getattr(self, "tray", None):
            self.tray.setToolTip(
                f"{content.PET_NAME}　大小 {int(value * 100)}%")

    # ------------------------------------------------ 启动台对接
    def apply_settings(self, values: dict) -> None:
        """把启动台的 payload 应用到桌宠。

        由 main.py 在 deploy_requested 时调用，覆盖 __init__ 里的默认值。
        每个键都是可选的：缺省就保持当前值，方便增量更新。
        """
        if "selected_mode" in values:
            self.capture_mode = str(values["selected_mode"])
        if "max_words" in values:
            self.capture_limit = int(values["max_words"])
        if "min_conf" in values:
            self.min_conf = float(values["min_conf"])
        if "pet_scale" in values:
            self.set_scale(float(values["pet_scale"]))
        if "always_on_top" in values:
            want = bool(values["always_on_top"])
            if want != self.on_top:
                self.toggle_top()
        if "show_meaning_card" in values:
            self.show_meaning_card = bool(values["show_meaning_card"])
        if "ocr_engine" in values:
            # 引擎选择在启动台里也能改（`launcher_window` 的那排按钮），
            # 所以这里必须接住：不接的话「界面显示 PaddleOCR、桌宠跑 RapidOCR」。
            self.set_engine(str(values["ocr_engine"]))
        if "skin" in values:
            # 皮肤在 __init__ 里已经按 settings 设过一次；这里再设一次是为了
            # 「启动台改了皮肤再点部署」能生效（payload 覆盖构造期的默认值）。
            # persist=False：值本来就从 settings 来，别多写一次磁盘。
            self.set_skin(str(values["skin"]), persist=False)
        # ---- 蜘蛛感应（§7）--------------------------------------------------
        # 顺序很重要：**先认频率，再决定开不开**。反过来（先按旧的 `sense_hz`
        # 起线程、再改属性）会得到「启动台选了 2 次/秒、实际按 1 次/秒在跑」，
        # 而这种分叉在界面上完全看不出来。
        if "sense_hz" in values:
            self.sense_hz = float(values["sense_hz"])
            if self.sense_session is not None:
                self.sense_session.hz = _clamp_sense_hz(self.sense_hz)
                if self._sense_timer is not None:
                    self._sense_timer.start(int(1000 / self.sense_session.hz))
        if "sense_enabled" in values:
            want = bool(values["sense_enabled"])
            if want and not self.sense_enabled:
                self._start_sense(self.sense_hz)
            elif not want and self.sense_enabled:
                self._stop_sense()
        _log("[pet] apply_settings: mode=%s limit=%d min_conf=%.2f scale=%.2f "
             "top=%s card=%s skin=%s sense=%s@%.1f/s engine=%s"
             % (self.capture_mode, self.capture_limit, self.min_conf,
                self.scale, self.on_top, self.show_meaning_card,
                self.painter.skin_id, self.sense_enabled, self.sense_hz,
                _current_engine_id()))

    # ------------------------------------------------ OCR 引擎（任务书 §3）
    def set_engine(self, engine_id: str) -> bool:
        """按启动台的选择切引擎；**切不动就保持原样并把原因写进日志**。

        ★ 这里绝不做「返回成功但实际还在跑 RapidOCR」的假切换（§3.2 硬性要求）。
          探测还没跑完时也不能「先答应了回头再补」—— 桌宠刚部署那一秒用户可能就
          要点识别，所以本轮明确按未切换处理，同时请求一次后台探测，
          下一次部署/识别就是真实状态。
        """
        try:
            import ocr_adapter
        except Exception as error:                 # noqa: BLE001
            _log("[engine] ocr_adapter 导入失败：%r（维持当前引擎）" % (error,))
            return False
        wanted = (ocr_adapter.ENGINE_PADDLE
                  if str(engine_id).strip().lower().startswith("paddle")
                  else ocr_adapter.ENGINE_RAPID)
        state = ocr_adapter.probe_state(wanted)
        if state in ("unknown", "loading"):
            self.probe_engines(then=wanted)
            _log("[engine] %s 状态=%s（还没探测完）→ 已请求后台探测，"
                 "本轮仍用 %s" % (wanted, state, ocr_adapter.current_engine()))
            return False
        ok, reason = ocr_adapter.configure(wanted)
        _log("[engine] 请求 %s → %s（实际生效 %s）%s"
             % (wanted, "已切换" if ok else "未切换",
                ocr_adapter.current_engine(),
                "" if not reason else "：%s" % reason))
        return bool(ok)

    def probe_engines(self, then: str = None) -> None:
        """在**子线程**跑一次真实探测（import + 构造 + 一次最小推理）。

        阻塞几秒，所以绝不放主线程；`ocr_adapter` 内部按引擎缓存结果，
        重复调用不会重复付代价。`then` 非空时探测完顺势试一次切换 ——
        用户看到的是「过几秒再部署就切过去了」，而不是永远切不动。
        """
        import threading

        def _run() -> None:
            try:
                import ocr_adapter
                for row in ocr_adapter.probe():
                    _log("[engine] 探测 %s → %s%s"
                         % (row["id"], row["state"],
                            "" if not row.get("reason")
                            else " · %s" % str(row["reason"])[:180]))
                if then:
                    ok, reason = ocr_adapter.set_engine(then)
                    _log("[engine] 探测后补切 %s → %s%s"
                         % (then, "已切换" if ok else "未切换",
                            "" if not reason else "：%s" % reason))
            except Exception as error:             # noqa: BLE001
                _log("[engine] 后台探测失败: %r" % (error,))

        threading.Thread(target=_run, name="engine-probe", daemon=True).start()

    def shutdown(self) -> None:
        """收回销毁：停定时器、收子窗口、关本体。

        源文件没有任何销毁 API，quit_app() 会杀掉整个程序。
        这里只拆桌宠自己，让启动台继续活着。
        """
        _log("[pet] shutdown 开始")
        try:
            QApplication.instance().removeNativeEventFilter(self._global_scan_hotkey)
            self._global_scan_hotkey.unregister()
        except Exception:
            pass
        # ★ 感应必须**最先**停：它有一个自转的抓屏 QTimer 和一个后台线程。
        #   先收窗口再停线程的话，线程会在窗口已经没了之后仍可能推一个 notice
        #   过来（`_on_sense_notice` 碰已销毁的覆盖层 = RuntimeError），
        #   而 QTimer 会继续抓屏 —— 「退出应用时强制清理后台线程与屏幕捕获」
        #   （§7.2）要求的就是这个顺序。
        if self.sense_enabled:
            self._stop_sense()
        # 关感应那一步只等 3 秒（不能让界面冻住）；**退出应用**可以慢慢等，
        # 这里就是 §7.2「退出时强制清理后台线程」的收尾点。
        stragglers = self._drain_sense_workers()
        if stragglers:
            _log("[sense] 退出时仍有 %d 个感应线程未退出（已请求停止、不会自动重启）"
                 % stragglers)
        for timer_name in ("_timer", "_idle_timer", "_click_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass
        try:
            self.bubble.dispose()
        except Exception:
            pass
        if getattr(self, "tray", None):
            try:
                self.tray.hide()
            except Exception:
                pass
        for key in list(self._dialogs.keys()):
            dialog = self._dialogs.pop(key, None)
            if dialog is not None:
                try:
                    dialog.hide()
                except Exception:
                    pass
        if self._overlay is not None:
            try:
                self._overlay.hide()
            except Exception:
                pass
        for worker in list(self._workers):
            try:
                worker.quit()
                worker.wait(2000)
            except Exception:
                pass
        self._workers.clear()
        self.close()
        _log("[pet] shutdown 完成")

    # ------------------------------------------------ 动作
    def toggle_top(self) -> None:
        self.on_top = not self.on_top
        flags = self.windowFlags()
        if self.on_top:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        position = self.pos()
        self.setWindowFlags(flags)
        self.show()
        self.move(position)
        self._apply_geometry(resize=True)
        if getattr(self, "act_top", None):
            self.act_top.setChecked(self.on_top)
        self.say("已置顶" if self.on_top else "已取消置顶", 1400)

    # ------------------------------------------------ 折叠（无腿模式）
    def toggle_fold(self) -> None:
        """右键菜单那一项：折叠 / 展开。"""
        self.set_folded(not self.folded)

    def set_folded(self, folded: bool, silent: bool = False) -> None:
        """把八条腿收起来（无腿模式）或伸回去。

        折叠是一个**常驻状态**而不是一次播放：动画只负责「收回/伸出」这一段，
        到位之后由 `self.folded` 一直维持（见 `_leg_retract()`）。

        折叠时会顺手把「走位」和「攥在手上的识词结果」清掉：
        腿都收起来了，再走去停靠点、再去踩词都无从谈起 —— 留着只会在
        展开的瞬间突然开始走，看着像抽风。识词入口（`start_capture`）
        会先把腿伸开再走，所以不想丢结果时重新框一次即可。
        """
        folded = bool(folded)
        if folded == self.folded:
            return
        # 先记下「这一刻腿实际收到哪了」，半路反向时才能接得上，不会跳一下。
        self._leg_from = self._leg_retract()
        self.folded = folded
        if folded:
            self._travel = None
            self._travel_done = None
            self._aim_pending = None
            self._aim_at = None
            self.spider.clear_targets()
        # `eff_hide_legs` 是 0→1、`eff_show_legs` 是 1→0，起点天然等于
        # 切换前的常驻值，所以两个方向都连续。
        self.play("hide_legs" if folded else "show_legs")
        if not silent:
            self.say(content.bubble_for("fold" if folded else "unfold"), 2400)
        self.update()

    # ------------------------------------------------ 蜘蛛感应（任务书 §7）
    def _sense_log(self, message: str) -> None:
        """感应链路专用日志。

        ★ 这里**只允许**出现计数、耗时、网格坐标和异常类型。
          屏幕上被识别到的文本一个字都不落盘（任务书 §7.3 隐私边界）：
          桌面里可能是邮件、合同、聊天记录，「日志不记用户文本全文」
          在这种模式下不是修辞，是硬要求。
        """
        _log(message)

    def _sense_exclude_rects(self) -> list:
        """本程序自己的窗口在**图像像素**里的矩形，用来避免「蜘蛛认出自己」。

        不排除的话：状态条 / 提示框里的英文单词会被下一轮 OCR 认成屏幕上
        新出现的词 → 再提示一次 → 再认一次，形成自我识别循环（§7.3 明令避免）。

        ★ 但**全屏透明层必须排除在排除表之外**：`SenseSession._excluded_cells`
          只屏蔽「整格都落在自己窗口里」的格子，而感应覆盖层 / 瞄准层铺满整个
          虚拟桌面 → 12 格全中 → 开启感应等于把自己整个弄瞎（实测就是这样，
          直到 `tools/sense_e2e.py` 把它抓出来）。真正会被认成英文的只有
          **状态条那一小块文字**，所以这里按内容排除那一块，而不是按整层。

        换算：图像像素 = (逻辑屏幕坐标 - 虚拟桌面原点) × DPR。
        ★ 桌面原点和 DPR 直接从 `QGuiApplication.screens()` 算，
          **不在这调 `grab_virtual_desktop()`** —— 那是整屏抓图，
          为了拿两个数字多抓一次屏，等于把每轮的捕获成本翻倍。
        """
        from PySide6.QtGui import QGuiApplication
        geo = QRect()
        dpr = 1.0
        for screen in QGuiApplication.screens():
            geo = geo.united(screen.geometry())
            dpr = max(dpr, float(screen.devicePixelRatio()))
        scale = float(dpr or 1.0)
        desktop_area = max(1.0, float(geo.width() * geo.height()))
        rects = []

        def add_logical(x, y, w, h, label=""):
            """按**逻辑屏幕坐标**加一块排除区；全屏级的大块直接拒收。"""
            if w <= 0 or h <= 0:
                return
            if w * h > 0.6 * desktop_area:
                # 见上面的 ★：这一条就是「别把整层挡掉」的硬护栏
                self._sense_log("[sense] 排除区 %s 覆盖整屏（%.0f%%），已忽略"
                                % (label or "窗口", w * h / desktop_area * 100))
                return
            rects.append(((x - geo.x()) * scale, (y - geo.y()) * scale,
                          w * scale, h * scale))

        def add(widget):
            try:
                if widget is None or not widget.isVisible():
                    return
                pos, size = widget.mapToGlobal(QPoint(0, 0)), widget.size()
                add_logical(pos.x(), pos.y(), size.width(), size.height(),
                            widget.metaObject().className())
            except Exception:                           # noqa: BLE001
                pass

        add(self)
        add(self.bubble)
        for key in ("words", "wordbook", "aim"):
            add(self._dialogs.get(key))
        # 感应覆盖层：只排状态条，不排整层
        overlay = self._sense_overlay
        try:
            if overlay is not None and overlay.isVisible():
                cx, cy, cw, ch = overlay.chip_rect()
                add_logical(cx, cy, cw, ch, "感应状态条")
        except Exception:                               # noqa: BLE001
            pass
        return rects

    def _start_sense(self, hz: float = None) -> None:
        if self.sense_enabled:
            return
        if not OcrEngine.available():
            self.say("缺少 OCR 组件，无法开启感应", 2600)
            return
        from sense_session import SenseSession
        from sense_worker import SenseWorker
        value = float(hz if hz is not None else SETTINGS_DEFAULTS["sense_hz"])
        self.sense_hz = _clamp_sense_hz(value)
        self.sense_session = SenseSession(
            hz=self.sense_hz, mode=self.capture_mode, limit=self.capture_limit,
            clock=lambda: time.monotonic())
        self.sense_session.start()
        self._sense_busy = False
        self.sense_worker = SenseWorker(self.sense_session, self.lexicon,
                                        parent=self, min_conf=self.min_conf,
                                        mode=self.capture_mode,
                                        limit=self.capture_limit,
                                        skip_stopwords=self.capture_skip_stopwords)
        self.sense_worker.notice.connect(self._on_sense_notice)
        self.sense_worker.perf.connect(self._on_sense_perf)
        # ★ 每次开启都重新起算日志的「上次状态」，否则第二次开感应时
        #   第一次遗留的 hz/state 会让第一条降频记录被当成「没变化」吞掉。
        self._sense_logged_hz = None
        self._sense_logged_state = None
        # ★ 走 `_on_worker_fault`：线程侧的 `handle_error` 已经 `note_error` 过一次，
        #   直接连 `_on_sense_fault` 会双倍计数，「连续 3 次自动暂停」两次错误就触发。
        self.sense_worker.fault.connect(self._on_worker_fault)
        self.sense_worker.start()

        overlay = SenseOverlay(self, self.sense_session,
                               on_word_click=self._on_sense_word_click)
        self._keep("sense", overlay)
        overlay.start()
        self._sense_overlay = overlay

        self._sense_timer = QTimer(self)
        self._sense_timer.timeout.connect(self._sense_capture_tick)
        self._sense_timer.start(int(1000 / self.sense_hz))
        self.sense_enabled = True
        self._sense_log("[sense] 已开启：%.1f 次/秒 · 网格 %dx%d · 本地识别（不发网络）"
                        % (self.sense_hz, self.sense_session.rows,
                           self.sense_session.cols))
        self.say("感应中 · 只在本机识别", 2600)

    def _stop_sense(self) -> None:
        """关闭：停定时器 → 停线程 → 收覆盖层 → 丢弃会话状态。

        顺序不能反：线程还在跑时收覆盖层，下一次 `notice.emit` 会打到已销毁的
        C++ 对象上（`AimOverlay` 那次的同类问题，见 `_launch_aim` 注释）。
        """
        self.sense_enabled = False
        timer, self._sense_timer = getattr(self, "_sense_timer", None), None
        if timer is not None:
            try:
                timer.stop()
            except Exception:                           # noqa: BLE001
                pass
        worker, self.sense_worker = getattr(self, "sense_worker", None), None
        if worker is not None:
            self._sense_lingering = [w for w in self._sense_lingering
                                     if w.isRunning()]
            try:
                worker.stop_sense()
                if not worker.wait(3000):
                    # ★ 3 秒等不到**不等于**「线程没被清理」。它此刻大概率正卡在
                    #   一次 OCR 调用里（本机实测单段最长 14620ms，
                    #   `dist/sense/shape_probe.log` 的 G 条1），而 `_stop` 已经置上、
                    #   会话也已 `stop()` → 那一调用返回后 `run()` 的 while 立刻退出。
                    #   在 GUI 线程上继续 `wait()` 把它等死是更糟的选择（界面直接冻住）。
                    #   所以：留引用 + 说真话，`shutdown()` 收尾（§7.2「强制清理」）。
                    self._sense_lingering.append(worker)
                    _log("[sense] 线程还在收尾当前这一次识别（3s 未退出），"
                         "已请求停止，退出应用时会再等它")
            except Exception:                           # noqa: BLE001
                pass
        overlay, self._sense_overlay = getattr(self, "_sense_overlay", None), None
        if overlay is not None:
            try:
                overlay.close()
            except Exception:                           # noqa: BLE001
                pass
        session = getattr(self, "sense_session", None)
        if session is not None:
            session.stop()
        if getattr(self, "_sense_lingering", None):
            self._sense_log("[sense] 已关闭：捕获与调度都停了，"
                            "%d 个线程还在收尾最后一次识别"
                            % len(self._sense_lingering))
        else:
            self._sense_log("[sense] 已关闭（线程与捕获都已释放）")

    def _drain_sense_workers(self, budget_ms: float = None) -> int:
        """等「已请求停止、还卡在最后一次识别里」的感应线程真退出。

        只在 `shutdown()` 用（关闭感应那一步只等 3 秒，见 `_stop_sense`）。
        返回值是**收尾后仍在跑**的线程数：非零时由调用方写进日志，不静默吞掉
        —— 「强制清理后台线程」（§7.2）的诚实版本是「等过、等不到就说」，
        而不是假装等到了。
        """
        budget = SENSE_EXIT_GRACE_MS if budget_ms is None else int(budget_ms)
        lingering = getattr(self, "_sense_lingering", None) or []
        if not lingering:
            return 0
        deadline = time.monotonic() + budget / 1000.0
        still_running = []
        for worker in lingering:
            try:
                worker.stop_sense()
                left = max(0.0, deadline - time.monotonic())
                if worker.isRunning() and not worker.wait(int(left * 1000)):
                    still_running.append(worker)
            except Exception:                           # noqa: BLE001
                pass
        self._sense_lingering = still_running
        return len(still_running)

    def toggle_sense(self) -> None:
        if self.sense_enabled:
            self._stop_sense()
        else:
            self._start_sense()
        if getattr(self, "tray", None):
            try:
                self.tray.setContextMenu(self._make_menu())
            except Exception:                           # noqa: BLE001
                pass

    def sense_pause_resume(self) -> None:
        session = self.sense_session
        if session is None:
            return
        from sense_session import RUNNING
        if session.state == RUNNING:
            session.pause("用户暂停")
        else:
            session.resume()

    def sense_report(self) -> None:
        """「查看性能/错误信息」（§7.3）。全是计数与耗时，无屏幕内容。"""
        session = self.sense_session
        if session is None:
            self.say("感应未开启", 2200)
            return
        from sense_session import RECENT_WINDOW
        data = session.perf()
        worker = self.sense_worker
        text = ("轮 %d · 跳过 %d · 纯色挡住 %d · OCR %d 次 · "
                "平均 %.0fms · 近 %d 轮中位 %.0fms（降频判据）· P95 %.0fms · "
                "提示 %d · 抑制 %d · 待提示 %d · 降频 %d · 错误 %d · "
                "丢帧 %d · 捕获 %.0fms · 预热 %.0fms · 引擎 %s"
                % (data["cycles"], data["skipped_no_change"],
                   data.get("skipped_blank", 0), data["ocr_runs"],
                   session.avg_cycle_ms, RECENT_WINDOW,
                   session.recent_cycle_ms, session.p95_cycle_ms,
                   data["notices"], data["suppressed"],
                   session.pending_notices(), data["downshifts"],
                   data["errors"], getattr(worker, "dropped", 0),
                   getattr(worker, "capture_ms", 0.0) * 1000,
                   getattr(worker, "warmup_ms", 0.0),
                   data["engine"]))
        self._sense_log("[sense] %s" % text)
        box = QMessageBox(QMessageBox.NoIcon, "感应 · 性能与状态",
                          text + "\n\n" + session.status_text(), parent=self)
        box.setAttribute(Qt.WA_DeleteOnClose, True)
        box.show()

    def _sense_capture_tick(self) -> None:
        """按 `sense_hz` 抓一帧，交给后台线程；**这里不跑 OCR**。

        四件事必须在这里（GUI 线程）做完，别的都归 worker：
          1. `grab_virtual_desktop()`（Qt 抓屏只能在 GUI 线程）；
          2. `QImage → ndarray`（同上，`OcrWorker` 里那个 exit 127 的坑）；
          3. 记下自己那些窗口的矩形，别让蜘蛛认出自己的状态条；
          4. 用户正在框选 / 踩词 / 拖窗口的话，这一帧直接**跳过**，
             不去排队 —— 否则框选遮罩那张「冻结的整屏截图」会被当成新内容，
             把遮罩里的英文提示词全感应一遍。
        """
        session = self.sense_session
        worker = self.sense_worker
        if session is None or worker is None or not self.sense_enabled:
            return
        if session.state != "running":
            return
        if self._capture_busy or "aim" in self._dialogs or self.dragging \
                or self._words_pending is not None:
            return
        if worker.isRunning() is False:
            self._on_sense_fault("感应线程已退出，已停止（不会自动重启）")
            self._stop_sense()
            return
        started = time.perf_counter()
        try:
            pixmap, geo, dpr = grab_virtual_desktop()
            array = qimage_to_ndarray(pixmap.toImage())
        except Exception as error:                       # noqa: BLE001
            self._on_sense_fault("捕获失败 %s" % type(error).__name__)
            return
        capture_ms = time.perf_counter() - started
        session.set_exclude_rects(self._sense_exclude_rects())
        worker.submit(array, (geo.x(), geo.y()), dpr, capture_ms)
        # 频率会被 `_apply_budget` 自动下调，这里跟着定时器一起跟上，
        # 否则「会话已经降到 0.6 次/秒」但定时器还按 1 秒 2 次狂抓屏。
        interval = int(1000 / _clamp_sense_hz(session.hz))
        if abs(interval - self._sense_timer.interval()) >= 120:
            self._sense_timer.start(interval)

    def _on_sense_notice(self, item: dict) -> None:
        """后台挑出一个要提示的词：只闪射线和高亮，**腿不参与**（§7.2）。"""
        overlay = self._sense_overlay
        if overlay is None:
            return
        overlay.show_notice(item)
        # 日志里只有坐标和计数，没有词本身
        pos = item.get("screen_pos") or (0, 0)
        self._sense_log("[sense] 提示 @(%d,%d) · 待提示 %d 个"
                        % (pos[0], pos[1],
                           self.sense_session.pending_notices()))

    def _on_sense_word_click(self, item: dict) -> None:
        """点了高亮的词 → 弹**本地**释义卡。AI 语境分析仍然要用户在卡上主动按
        （§5.2 / §7.2：感应模式不引入任何自动云端调用）。

        ★ 这里**不看** `show_meaning_card` 开关：那个开关管的是「识别完自动弹卡」，
          而这一次点击本身就是用户主动要的释义 —— 关掉开关还把点击吞掉，
          就成了「感应只能看不能问」。
        """
        dialog = WordResultDialog(None, [item], self.book, self._mode_label())
        self._keep("words", dialog)
        dialog.show()
        self._place_dialog(dialog, item.get("screen_box"))
        dialog.raise_()

    def _on_sense_fault(self, reason: str, counted: bool = True) -> None:
        """把故障记进会话（连续 N 次 → 自动暂停并停线程，§7.3）。

        ★ `counted=False` 是给**线程侧故障**用的：`SenseWorker.handle_error` 里
          已经先 `session.note_error()` 再 `fault.emit()`，这里再记一次就是双倍计数
          —— 两次真错误就会越过「连续 3 次」的阈值，日志里的 `errors` 也虚高。
          GUI 侧的故障（捕获失败 / 线程已退出）没人在别处记，所以默认 `counted=True`。
        """
        session = self.sense_session
        if session is not None and counted:
            session.note_error(reason)
        self._sense_log("[sense] %s" % reason)
        if session is not None and session.state == "error":
            # 出错自动暂停并提示，**不重启线程**（§7.3）
            self._stop_sense()
            self.say("感应出错，已暂停", 3200)

    def _on_worker_fault(self, reason: str) -> None:
        """`SenseWorker.fault` 的槽：线程里已经记过账了，这里只负责播报。"""
        self._on_sense_fault(reason, counted=False)

    def _on_sense_perf(self, data: dict) -> None:
        """`SenseWorker.perf` 的槽：把**降频**和**自动暂停**这两类状态变化记进日志。

        §7.3 要求「超过预算时自动降频或提示」「出错时自动暂停并提示」——
        状态条上一直在刷 `status_text()`，但那是瞬时显示，用户回头看不到；
        这里按「状态变了才记一行」的方式留一条可查的痕迹，
        而且只在变化时记，不会每秒刷一行日志。
        词的内容一个字都不写，只写计数与耗时（§7.3 的隐私边界）。
        """
        state, hz = data.get("state"), float(data.get("hz") or 0.0)
        if hz != getattr(self, "_sense_logged_hz", None):
            if getattr(self, "_sense_logged_hz", None) is not None:
                self._sense_log("[sense] 已自动降频到 %.2f 次/秒（设定 %.2f）· %s"
                                % (hz, data.get("hz_start", hz),
                                   data.get("note", "")))
            self._sense_logged_hz = hz
        if state != getattr(self, "_sense_logged_state", None):
            if state in ("paused", "error"):
                self._sense_log("[sense] 状态 → %s：%s"
                                % (state, data.get("note", "（无说明）")))
            self._sense_logged_state = state

    # ------------------------------------------------ 菜单
    def _make_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)

        def add(text, handler, checkable=False, checked=False, icon_kind=None):
            action = QAction(text, menu)
            if icon_kind:
                action.setIcon(_menu_icon(icon_kind))
            action.setCheckable(checkable)
            action.setChecked(checked)
            action.triggered.connect(handler)
            menu.addAction(action)
            return action

        add("框选识词", self.start_capture, icon_kind="capture")
        add("我的单词本", self.open_wordbook, icon_kind="book")
        add("识词设置（%s）" % self._mode_label(), self.open_settings, icon_kind="settings")
        menu.addSeparator()

        submenu = menu.addMenu("大小")
        submenu.setIcon(_menu_icon("size"))
        submenu.setStyleSheet(MENU_QSS)
        for label, value in (("变小 (-10%)", self.scale / 1.1),
                             ("变大 (+10%)", self.scale * 1.1),
                             ("小号 80%", 0.8),
                             ("中号 100%", 1.0),
                             ("大号 140%", 1.4),
                             ("超大 190%", 1.9)):
            action = QAction(label, submenu)
            action.triggered.connect(lambda _=False, v=value: self.set_scale(v))
            submenu.addAction(action)

        # 皮肤：四套形象共用同一套腿长/命中区，切换不重建 Spider。
        # 启动台右侧也有同一个入口（两处共用 `settings["skin"]`）。
        skin_menu = menu.addMenu("皮肤")
        skin_menu.setIcon(_menu_icon("skin"))
        skin_menu.setStyleSheet(MENU_QSS)
        for skin_id, skin_name in skin_options():
            action = QAction(skin_name, skin_menu)
            action.setCheckable(True)
            action.setChecked(skin_id == self.painter.skin_id)
            action.triggered.connect(
                lambda _=False, sid=skin_id: self.set_skin(sid))
            skin_menu.addAction(action)

        # 折叠 / 展开：标签写**点了会发生什么**，而不是当前状态 ——
        # 这个菜单本来就是「先点再发生」，写动作比写状态更少歧义。
        add("展开（伸出八条腿）" if self.folded else "折叠（收起八条腿）",
            self.toggle_fold, icon_kind="fold")
        add("转个圈（整理丝线）", self.spin_once, icon_kind="spin")
        behavior = menu.addMenu("行为模式")
        behavior.setStyleSheet(MENU_QSS)
        for mode, label in (("idle", "普通待机"), ("free_move", "自由移动"),
                            ("follow_mouse", "跟随鼠标")):
            action = QAction(label, behavior)
            action.setCheckable(True)
            action.setChecked(self.behavior_mode == mode)
            action.triggered.connect(lambda _=False, m=mode: self.set_behavior_mode(m))
            behavior.addAction(action)
        # 窗口置顶、空处点击穿透、蜘蛛感应属于内部行为，暂不在用户菜单暴露。
        menu.addSeparator()

        menu.addSeparator()
        add("使用帮助", self.show_help, icon_kind="help")
        # 「回到启动台」只在有 recall_callback 时显示（由 main.py 在部署时设置）
        if self.recall_callback is not None:
            add("回到启动台（收回）", self._do_recall, icon_kind="home")
        add("退出", self.quit_app, icon_kind="exit")
        return menu

    def _do_recall(self) -> None:
        """右键菜单「回到启动台」：调用 main.py 设置的回调。"""
        if self.recall_callback is not None:
            self.recall_callback()

    def contextMenuEvent(self, event):
        self._click_timer.stop()
        self._make_menu().exec(event.globalPos())

    def _mode_label(self) -> str:
        import lexicon
        return lexicon.MODE_DISPLAY.get(self.capture_mode, self.capture_mode)

    # ------------------------------------------------ 功能入口
    def open_wordbook(self) -> None:
        dialog = WordbookDialog(None, self.book)
        self._keep("book", dialog)
        dialog.show()
        stats = self.book.stats()
        self.say(f"单词本里 {stats['total']} 个词，今天该复习 {stats['due']} 个", 2400)

    def open_settings(self) -> None:
        dialog = ModeDialog(None, self.capture_mode, self.capture_skip_stopwords,
                            self.capture_limit)
        if dialog.exec():
            values = dialog.values()
            self.capture_mode = values["mode"]
            self.capture_limit = values["limit"]
            self.capture_skip_stopwords = values["skip_stopwords"]
            self.say(f"识词模式：{self._mode_label()}", 1800)

    def set_skin(self, skin_id: str, persist: bool = True) -> bool:
        """切换蜘蛛皮肤。

        只动渲染层：不重建 `Spider`，所以正在走的步态、跳跃、瞄准踩词
        都不会被打断。返回值表示是否真的切过去了（未知 ID 返回 False）。

        `persist=True` 时回写 `settings["skin"]` —— 启动台和桌宠共用这一个键，
        所以在这里切了，回启动台时右侧那排按钮的高亮也是对的。
        """
        try:
            spec = self.painter.set_skin(skin_id)
        except ValueError:
            _log("[skin] 未知皮肤 %r，忽略" % (skin_id,))
            return False

        self.skin_id = spec.skin_id
        # 判定框跟着皮肤走：2 倍身子的皮肤，肚子后半截也得能点中（见 _in_thorax）。
        self.spider.body_scale = spec.body_scale
        # 换皮只改像素不改动画：wake() 负责「降频态立刻重画一帧」，
        # 非降频时下面这句 update() 也照常生效。
        self.wake()
        self.update()

        if persist and self.settings is not None:
            self.settings.set("skin", spec.skin_id)

        # 托盘图标与提示同步更新；没有托盘时不影响桌宠运行。
        tray = getattr(self, "tray", None)
        if tray is not None:
            try:
                tray.setIcon(self._make_icon())
                tray.setToolTip("%s · %s　大小 %d%%"
                                % (content.PET_NAME, spec.name,
                                   int(self.scale * 100)))
            except Exception:                  # noqa: BLE001
                pass

        self.say("已切换皮肤：%s" % spec.name, 1400)
        _log("[skin] 已切换 → %s（%s）" % (spec.skin_id, spec.name))
        return True

    def show_help(self) -> None:
        QMessageBox.information(None, "微光 · 使用帮助", content.HELP_TEXT)

    def quit_app(self) -> None:
        try:
            self.bubble.hide_now()
            if getattr(self, "tray", None):
                self.tray.hide()
        except Exception:                      # noqa: BLE001
            pass
        QApplication.quit()

    def _keep(self, key: str, dialog) -> None:
        self._dialogs[key] = dialog
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)

    # ------------------------------------------------ 框选识词
    def start_capture(self) -> None:
        if not OcrEngine.available():
            self.say("缺少 OCR 组件，无法识词", 2600)
            return
        if self._capture_busy:
            # 上一次框选还没走完（遮罩正开着）。再走一遍会在屏幕上**叠出第二个
            # 全屏遮罩**：选完把上面那个关掉，下面那个就露出来了 —— 满屏冻结的
            # 截图 + 十字光标，看着像卡死，再点一下还会再发一次 selected。
            return
        self._capture_busy = True
        self._touch()
        # 折叠状态下识词：八条腿都收着，踩词无从谈起 —— **先伸腿**，
        # 再走正常流程。这里用 `silent`，免得「正在读这段文字…」的提示
        # 和「腿都伸开了」撞在一起。
        if self.folded:
            self.set_folded(False, silent=True)
        self._click_timer.stop()
        self.bubble.hide_now()
        self._drop_effect()
        self._travel = None
        self._travel_done = None
        # 重新识词 = 主动放弃上一次的结果，撤掉兜底，别让它待会儿又踩一次词
        self._aim_pending = None
        self._aim_at = None
        self.spider.clear_targets()
        self.hide()
        QTimer.singleShot(260, self._capture_go)

    def _capture_go(self) -> None:
        try:
            pixmap, geometry, dpr = grab_virtual_desktop()
        except Exception:                      # noqa: BLE001
            self._capture_busy = False
            self.show()
            self.say("屏幕截图失败了，稍后再试。", 2600)
            return
        try:
            stale = self._overlay
            if stale is not None:
                stale.close()
            self._overlay = CaptureOverlay(pixmap, geometry)
            self._overlay.selected.connect(
                lambda rect: self._on_region(rect, pixmap, dpr, geometry))
            self._overlay.cancelled.connect(self._capture_cancel)
            self._overlay.show()
            self._overlay.raise_()
            self._overlay.activateWindow()
        except Exception:                      # noqa: BLE001
            self._overlay = None
            self._capture_busy = False
            self.show()
            self.say("框选启动失败，稍后再试。", 2600)

    def _capture_cancel(self) -> None:
        self._capture_busy = False
        self._overlay = None
        self.show()

    def _on_region(self, rect: QRect, pixmap: QPixmap, dpr: float, geo: QRect) -> None:
        self._overlay = None
        self._capture_busy = False
        # 上一次的瞄准层要是还挂着（它的寿命有 11 秒），先收掉 ——
        # 不然新一次的词框会跟旧的叠在一起，两份词框谁也看不懂。
        stale = self._dialogs.pop("aim", None)
        if stale is not None:
            try:
                stale.close()
            except Exception:                  # noqa: BLE001
                pass
        self.show()
        if dpr <= 0:
            dpr = 1.0

        device = QRect(int(rect.x() * dpr), int(rect.y() * dpr),
                       max(4, int(rect.width() * dpr)),
                       max(4, int(rect.height() * dpr)))
        image = pixmap.toImage().copy(device)

        # 不再「跳到选区旁边干等 + 弹个正在识别」。
        # 蜘蛛立刻自己走过去（近）或跳过去（远），OCR 在后台并行跑；
        # 到位后进入 think 姿态 —— 关节球亮起，就是它在干活的全部提示。
        self._pending_rect = QRect(rect)
        self._apply_geometry()
        coarse = QPoint(int(rect.center().x()),
                        int(rect.center().y() + self.sprite_w * 0.5))
        self.travel_to(coarse, done=self._enter_think)

        #: 本次识别的选区与 DPR —— **存在窗口上，不要挂在 worker 上**。
        #: 槽拿不到 worker 的历史原因见 `_on_ocr_done` 的注释（信号只有 3 个参数，
        #: 而 `sender()` 在 PySide6 的队列连接里返回 None，实测过，靠不住）。
        #: 窗口同一时刻只跑一次识别，`_capture_rect` 覆盖写完全够用。
        self._capture_rect = QRect(rect)
        self._capture_dpr = dpr

        worker = OcrWorker(image, self.lexicon, self.capture_mode,
                           self.capture_limit, self.capture_skip_stopwords,
                           min_conf=self.min_conf, parent=self)
        worker.learning_history = [item.to_dict() for item in self.book.items]
        worker.capture_rect = QRect(rect)      # 留一份，方便单独调试 worker
        worker.dpr = dpr
        self._workers.append(worker)
        # 必须连成绑定方法并给 worker 一个 parent（pet）：
        # 连到普通 lambda 时 PySide6 会用 DirectConnection，槽在 worker 线程里跑，
        # 里面一碰 GUI 就出问题，表现为 done 信号「像是没送到」。
        worker.done.connect(self._on_ocr_done)
        # finished 不带参数，用默认参数把 worker 绑进闭包 —— 这里**不能**依赖
        # `sender()`（实测返回 None）。闭包是普通可调用对象，可能被以
        # DirectConnection 在 worker 线程里执行，所以 `_reap` 只做线程安全的操作。
        worker.finished.connect(lambda item=worker: self._reap(item))
        worker.start()

    def _enter_think(self) -> None:
        """到位：关节球亮起，宣告「我在读这块字」。"""
        self._set_state("think")

    def _best_stop_point(self, words):
        """在词群里找一个**站得下、又能踩到最多词**的位置。

        目标不是质心 —— 质心常常正好压在某个词上。做法是网格搜索一圈候选点，
        每个候选点按「够得着的词数」和「够不着的词的距离和」打分，
        再减去「自己盖住词」的惩罚，最后按到中心的偏好打破平局。
        """
        points = [w["screen_pos"] for w in words]
        if not points:
            return None

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

        from aim_overlay import AIM_SCALE_BOOST
        unit = self.unit
        reach = max((leg.full for leg in self.spider.legs if not leg.palp),
                    default=100.0) * unit * AIM_SCALE_BOOST * 0.92
        body_clear = self.sprite_w * 0.32      # 站上去不能压着词

        step = max(40.0, self.sprite_w * 0.22)
        best, best_score = None, None
        for gx in range(-3, 4):
            for gy in range(-3, 4):
                point = QPoint(int(cx + gx * step), int(cy + gy * step))
                # **先夹再打分**：`travel_to()` 会把目标往屏幕里收（安全边距），
                # 拿没夹过的候选点打分等于「照一个到不了的位置选最优」——
                # 选中的点被夹走后离词群就远了，够得着的词少一大半。
                # 夹过的点才是蜘蛛真正会站的地方。
                self._clamp_point(point)
                px, py = float(point.x()), float(point.y())
                reachable = 0
                penalty = 0.0
                for wx, wy in points:
                    d = math.hypot(px - wx, py - wy)
                    if d <= reach:
                        reachable += 1
                    else:
                        penalty += min(d - reach, 500.0)
                    if d < body_clear:            # 压在词上，重罚
                        penalty += (body_clear - d) * 6.0
                score = reachable * 1000.0 - penalty - math.hypot(px - cx, py - cy) * 0.05
                if best_score is None or score > best_score:
                    best, best_score = (px, py), score
        return QPoint(int(best[0]), int(best[1])) if best else None

    def _fire_aim(self) -> None:
        """把攥在手上的识别结果真正踩出来。

        幂等：先把 `_aim_pending` 取走再启动，所以无论它是被「调位到位」、
        被「调位被打断后的兜底」还是被「没有停靠点」触发，都只会踩一次词。
        """
        payload, self._aim_pending = self._aim_pending, None
        self._aim_at = None
        if payload is not None:
            self._launch_aim(*payload)

    def _launch_aim(self, aim_words, words) -> None:
        """到位之后：各脚依次伸出去踩词，同时弹出结果卡。"""
        try:
            from aim_overlay import AimOverlay
            # 上一次的瞄准层**可能已经被销毁了**：`_keep()` 给它挂了
            # `WA_DeleteOnClose`，而它现在是靠「再点一下」关的 —— 关完 C++ 对象
            # 就没了，这里再碰一下就是 RuntimeError，整个瞄准层起不来。
            # 所以这里的清理必须自己吞异常（第一次进来时 `stale` 是 None）。
            stale = self._dialogs.pop("aim", None)
            if stale is not None:
                try:
                    stale.close()
                except Exception:                # noqa: BLE001
                    pass
            self._set_state("idle")
            # 防御：万一上一层的腿长倍率没还原（C++ 对象被直接销毁、
            # 走不到 `closeEvent`），这里先归零，免得越框越长。
            self.spider.set_leg_stretch(1.0)

            def _progress(stats) -> None:
                """队列进度 → 落到运行日志。

                **这里不能用 `self.say()`**：瞄准层一开，本体窗口就 `hide()` 了，
                气泡画在一个不可见的窗口上等于没说话。完成时的可见反馈走覆盖层
                自己的提示条（`_hint_text`：已踩 N/M、扫完/停止/失败的口径）。
                """
                if stats["cancelled"] or stats["remaining"]:
                    return
                _log("[aim] 队列完成：%d 个词 · %d 批 · 只亮框 %d · 失败 %d"
                     % (stats["completed"], stats["batches"],
                        stats["skipped"], stats["failed"]))

            overlay = AimOverlay(self, aim_words, stagger=LEG_STAGGER,
                                 on_progress=_progress)
            self._keep("aim", overlay)
            overlay.start()
            _log("[aim] 瞄准层已起：本批 %d 条腿踩词、队列 %d 个词 / %d 个框"
                 "（够不着的不派腿，只亮框）；腿长 ×%.2f（按本批最远的词算，上限 ×%.1f）"
                 % (len(overlay._pairs), len(overlay.words),
                    len(overlay._guides),
                    getattr(overlay, "leg_stretch", 1.0),
                    __import__("aim_overlay").AIM_LEG_STRETCH_MAX))
        except Exception as error:              # noqa: BLE001
            _log("[aim] 瞄准层启动失败: %r" % (error,))
            # `AimOverlay.__init__` 里会先 `set_leg_stretch(k)` 再做别的；
            # 如果它在中途抛了，closeEvent 永远不会走，腿就**永久**是伸长态，
            # 下次启动还会叠一层。这里兜底归位。
            try:
                self.spider.set_leg_stretch(1.0)
            except Exception:                   # noqa: BLE001
                pass

        # ★ show_meaning_card 开关：关掉时只踩词不弹释义卡
        if self.show_meaning_card:
            dialog = WordResultDialog(None, words, self.book, self._mode_label())
            self._keep("words", dialog)
            dialog.show()
            self._place_dialog(dialog, self._pending_rect)
            dialog.raise_()

    def _reap(self, *args) -> None:
        """worker 结束时回收。

        两个坑：
        1. QThread 的 `finished` 信号**不带参数**，以前写 `args[0] if args else None`
           会一直拿到 None 直接 return —— `self._workers` 里的 worker 从来没被回收过
           （线程对象泄漏）。现在由调用方用闭包把 worker 传进来。
        2. 闭包是普通可调用对象，可能被以 DirectConnection 在 **worker 线程**里执行，
           所以这里只做线程安全的操作：动 list（有 GIL）和 `deleteLater()`（Qt 保证线程安全）。
        """
        worker = args[0] if args and args[0] is not None else None
        if worker is None:
            return
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def _on_ocr_done(self, words, meta, error, worker=None) -> None:
        if error:
            self._set_state("idle")
            self.say(content.bubble_for("ocr_fail"), 2600)
            return
        if not words:
            self._set_state("idle")
            self.say(content.bubble_for("ocr_empty"), 2800)
            return

        # ★ 引擎回退必须**说出来**（§3.2 诚实性硬性要求）：启动台选了 PaddleOCR、
        #   这一轮实际跑的是 RapidOCR 时，日志和气泡都要写明，
        #   绝不能维持「界面显示 Paddle、后台其实 Rapid」的不诚实状态。
        engine_note = meta.get("engine_note") or ""
        if engine_note:
            _log("[ocr] %s（本轮实际引擎 %s）"
                 % (engine_note, meta.get("engine", "?")))
        self.book.record_learning(words)

        analysis = meta.get("analysis") or {}
        # `source='local'` 是 §5.1 的默认路径：本地词典 + 规则，没发过云端请求。
        # 老日志里那句「AI 已分析 N 个候选词」是**假宣传**（那时也确实可能只是
        # 规则兜底），现在按来源分开说，用户能看出这次到底有没有联网。
        source = analysis.get("source")
        if source == "local":
            _log("[ocr] 本地词典完成：候选 %d，出卡 %d（未调用云端）"
                 % (analysis.get("candidate_count", len(words)), len(words)))
            self.say("本地词典认出 %d 个词，点卡片可以让 AI 讲语境" % len(words), 2400)
        elif source == "rules":
            _log("[ai] 本轮使用规则兜底：%s" %
                 (analysis.get("reason") or "未配置云端 AI"))
            self.say("已分析 %d 个候选词，推荐 %d 个" %
                     (analysis.get("candidate_count", len(words)), len(words)), 2400)
        else:
            _log("[ai] 云端分析完成：候选 %d，入选 %d" %
                 (analysis.get("candidate_count", len(words)), len(words)))
            self.say("AI 已分析 %d 个候选词，推荐 %d 个" %
                      (analysis.get("candidate_count", len(words)), len(words)), 2400)

        # 把截图内的单词位置换算成屏幕坐标，交给腿去踩。
        #
        # **这里踩过一个很贵的坑**：`done = Signal(list, dict, str)` 只有三个参数，
        # Qt 按信号传参，所以 `_on_ocr_done(..., worker=None)` 的第四个参数
        # **永远收不到**；而 `self.sender()` 在 PySide6 的队列连接里实测返回 None，
        # 也拿不到。于是 `rect` 恒为 None → 屏幕坐标一个都算不出来 → `aim_words`
        # 为空 → **「八腿踩词 + 词框」从来就没起来过**。
        # 真机日志的表现是：`[aim] 词 5 个，拿到屏幕坐标 0 个`。
        # 现在选区由 `_on_region` 直接存在窗口上，不走信号也不走 sender()。
        rect = self._capture_rect
        dpr = self._capture_dpr if worker is None else (getattr(worker, "dpr", 1.0) or 1.0)
        if rect is None and worker is not None:
            rect = getattr(worker, "capture_rect", None)
        if dpr is None or dpr <= 0:
            dpr = 1.0
        if rect is None:
            # 拿不到选区就没有屏幕坐标，八条腿无处可踩 —— 这一定是接错线了，
            # 别静默降级成「只弹结果卡」，否则 bug 会被当成「设计如此」。
            _log("[aim] !! 没有选区（_capture_rect 为空），瞄准层无法启动")
        else:
            positions = meta.get("positions", {})
            boxes = meta.get("boxes") or {}
            for item in words:
                if item.get("screen_pos"):
                    continue    # worker 已经用**它自己那次**的选区换算过了
                point = positions.get(item.get("surface"))
                box = boxes.get(item.get("surface"))
                if point:
                    item["screen_pos"] = (rect.x() + point[0] / dpr,
                                          rect.y() + point[1] / dpr)
                if box:
                    item["screen_box"] = (rect.x() + box[0] / dpr,
                                          rect.y() + box[1] / dpr,
                                          box[2] / dpr, box[3] / dpr)

        aim_words = [w for w in words if w.get("screen_pos")]
        # 落一条日志：这是「八腿踩词」链路的唯一入口，缺了它就只能靠截图猜
        # （位置表以 OCR 原文小写为键，查表用 lexicon 的 `surface`，两者由
        #  WORD_RE `[A-Za-z]+(?:['-][A-Za-z]+)*` 保证一致，不会留标点）。
        _log("[aim] 词 %d 个，拿到屏幕坐标 %d 个%s"
             % (len(words), len(aim_words),
                "" if len(aim_words) == len(words)
                else "  ← 有词没匹配上位置表: %s"
                     % [w.get("surface") for w in words if not w.get("screen_pos")]))

        if aim_words:
            # 二次调位：站到「词与词之间」的最优点，到位后各脚依次踩上去。
            # 结果先攥在手上（`_aim_pending`），调位只是「站得更好看」——
            # 万一调位被点击、被新的 travel_to 打断，`_tick` 里的兜底会在
            # AIM_GRACE 之后照样把瞄准层起来。
            stop = self._best_stop_point(aim_words)
            self._aim_pending = (aim_words, words)
            self._aim_at = None
            _log("[aim] 最优停靠点 %s（蜘蛛在 %s），开始调位" % (stop, self.center))
            self._set_state("crawl")
            if stop is not None:
                self.travel_to(stop, done=self._fire_aim)
            else:
                self._fire_aim()
            return

        self._set_state("idle")
        self.say(content.ocr_done(len(words)), 2600)
        # ★ show_meaning_card 开关：关掉时只播报不弹释义卡
        if self.show_meaning_card:
            dialog = WordResultDialog(None, words, self.book, self._mode_label())
            self._keep("words", dialog)
            dialog.show()
            self._place_dialog(dialog, rect)
            dialog.raise_()

    def _place_dialog(self, dialog, avoid=None) -> None:
        """把对话框挪到不遮挡蜘蛛（也不遮挡选区）的位置。"""
        spider = self.char_rect()
        size = dialog.size()
        screen = self._screen_rect()
        blocked = [spider]
        if avoid is not None:
            blocked.append(QRect(avoid).adjusted(-8, -8, 8, 8))

        candidates = [
            (spider.left() - size.width() - 16, spider.top()),
            (spider.right() + 16, spider.top()),
            (spider.left(), spider.bottom() + 12),
            (screen.left() + 24, screen.top() + 24),
            (screen.right() - size.width() - 24, screen.top() + 24),
        ]
        best = None
        for x, y in candidates:
            probe = QRect(int(x), int(y), size.width(), size.height())
            if probe.right() > screen.right() or probe.bottom() > screen.bottom():
                continue
            if not any(probe.intersects(rect) for rect in blocked):
                best = probe
                break
            if best is None:
                best = probe
        if best is not None:
            dialog.move(best.topLeft())

    # ------------------------------------------------ 托盘
    def _make_tray(self) -> None:
        try:
            self.tray = QSystemTrayIcon(self._make_icon(), self)
            self.tray.setToolTip(f"{content.PET_NAME}　大小 {int(self.scale * 100)}%")
            self.tray.setContextMenu(self._make_menu())
            self.tray.activated.connect(self._tray_activated)
            self.tray.show()
        except Exception:                      # noqa: BLE001
            self.tray = None

    def _make_icon(self) -> QIcon:
        """托盘/程序图标直接用蜘蛛本体渲染，保证形象一致。"""
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        unit = SpiderPainter.unit_for_width(size * 0.94)
        state = SpiderState(focus=True, heading=0.0)
        self.painter.paint(painter, self.spider, state, unit=unit,
                           origin_px=(size / 2.0, size / 2.0))
        painter.end()
        return QIcon(pixmap)

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.show()
            self.raise_()
            screen = self._screen_rect()
            self.center = QPoint(self.center.x(),
                                 min(self.center.y(), screen.bottom() - 150))
            self._apply_geometry()
