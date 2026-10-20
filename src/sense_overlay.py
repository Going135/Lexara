# -*- coding: utf-8 -*-
"""蜘蛛感应的覆盖层（任务书 §7.2）：**射线 + 细边框 + 状态条**，腿不参与。

和瞄准层（`aim_overlay.AimOverlay`）的区别是硬的，不是「参数不同」：

|            | 瞄准层（§6）              | 感应层（§7）                        |
|----------|-----------------------|---------------------------------|
| 腿        | 八条腿伸出去踩词            | **不动**（腿保持当前步态）                   |
| 提示       | 亮框 + 脚尖按住             | 身体→词的一条短射线，随后词本体上闪一下细边框          |
| 生命周期     | 一次选区，点一下就收           | 跟着「感应中」常驻，逐个目标闪                   |
| 点击       | 吞掉那一下（防误点）           | **绝不吞**：只观察，该点哪就点哪               |

最后一条是任务书要的「不遮挡视频控制、不劫持用户输入」：
瞄准层用 `WH_MOUSE_LL` 是要「再点一下收起」，所以必须吞；
这里装同一个钩子只为判断「用户是不是点了那只高亮的词」，
回调**永远 `CallNextHookEx` 并返回 0**，也就是一下都不吞。

钩子的 ctypes 那套（签名声明、回调自持引用、DPR 换算）和瞄准层是同一份坑，
所以直接从 `aim_overlay` 复用，不在这里再抄一遍 —— 抄第二份就迟早会分叉。
"""
from __future__ import annotations

import ctypes
import math
import time
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPainterPath,
                           QPen, QPolygonF)
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QWidget

from aim_overlay import (HC_ACTION, MSLLHOOKSTRUCT, WH_MOUSE_LL,
                         WM_LBUTTONDOWN, HOOKPROC, _USER32, union_geometry)

# ---------------------------------------------------------------- 观感参数

INK = QColor(21, 21, 21)
ACCENT = QColor(47, 107, 255)
HAZE = QColor(47, 107, 255, 36)
CHIP_BG = QColor(255, 255, 255, 232)
CHIP_BORDER = QColor(228, 228, 223, 255)
SUB = QColor(116, 116, 116)

#: 一次提示的总时长：射线先亮，再闪边框，然后自己淡掉（§7.2「短暂高亮」）。
RAY_MS = 700.0
FLASH_MS = 900.0
#: 刷新节奏：16ms 只是为了淡出顺眼，**和扫描频率无关**（扫描节流在 `SenseSession`）。
PAINT_MS = 60
#: 高亮框相对词本体框的外扩（逻辑像素）
BOX_PAD = 3.0


class SenseOverlay(QWidget):
    """鼠标穿透的全屏提示层。腿不参与，所以这里不碰 `pet.spider` 的任何目标。"""

    def __init__(self, pet, session, on_word_click=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlag(Qt.WindowTransparentForInput, True)
        #: 不遮住底下的内容：整层最 opaque 的地方也就是那只细边框
        self.setWindowOpacity(0.92)

        geo = union_geometry()
        self.setGeometry(geo)
        self._offset = geo.topLeft()

        self.pet = pet
        self.session = session
        #: 点了高亮的词 → 由 `pet_window` 决定弹本地释义（AI 仍然要用户主动按）
        self.on_word_click = on_word_click

        self._notice = None          # {"item":…, "t0":…, "box":…, "point":…}
        self._hook = None
        self._hook_cb = None         # ★ 必须自持引用，被 GC 掉下次鼠标事件就是野指针
        self._clicked = False        # 钩子只记一笔，回事件循环再处理

        #: 状态条的字体与度量。`QFontMetrics` 每帧新建是白费（16ms 一次），
        #: 而且 `chip_rect()` 要和绘制用**同一份**度量，所以在这里建一次。
        self._chip_font = QFont("Microsoft YaHei UI", 9)
        self._chip_metrics = QFontMetrics(self._chip_font)
        self._chip_cache = (None, "")     # (session id/hash, 文本) —— 见 `_chip_text`

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(PAINT_MS)

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> None:
        self.show()
        self.raise_()
        if not self._install_hook():
            # 装不上钩子不影响「看到提示」，只影响「点词看释义」，
            # 所以这里**只记一笔**，不把整个模式关掉。
            self.session.note = "点击看释义不可用（全局钩子安装失败）"

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._uninstall_hook()
        self.on_word_click = None
        super().closeEvent(event)

    # ---------------------------------------------------------------- 提示
    def show_notice(self, item) -> None:
        """把当前要闪的那个词交进来（`screen_pos` / `screen_box` 是逻辑像素屏幕坐标）。"""
        if not item:
            return
        box = item.get("screen_box")
        point = item.get("screen_pos")
        if point is None:
            return
        if not box:
            # 没有词本体框时退化成「以落点为中心的一只小框」：
            # 宁可框粗一点，也不能没有视觉回执（§7.4 要求看得到提示）。
            box = (point[0] - 26.0, point[1] - 9.0, 52.0, 18.0)
        self._notice = {"item": item, "t0": time.monotonic(),
                        "box": tuple(float(v) for v in box),
                        "point": (float(point[0]), float(point[1]))}
        self.update()

    def _tick(self) -> None:
        if self._clicked:
            self._clicked = False
            self._open_gloss()
        if self._notice is not None:
            age = (time.monotonic() - self._notice["t0"]) * 1000.0
            if age > max(RAY_MS, FLASH_MS):
                self._notice = None
        self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._draw_chip(painter)
        if self._notice is not None:
            self._draw_ray(painter)
            self._draw_flash(painter)
        painter.end()

    def _local(self, screen_point):
        """屏幕坐标 → 本层局部坐标。两种入参都得吃：

        `pet.center` 是 **QPoint**（不能下标），而词卡里的 `screen_pos` 是 tuple。
        以前这里只写 `screen_point[0]`，射线和状态条每帧都在 `paintEvent` 里抛
        `TypeError`（Qt 会吞掉并反复打印），表现为「感应开着但什么提示都没有」。
        """
        if hasattr(screen_point, "x"):
            x, y = float(screen_point.x()), float(screen_point.y())
        else:
            x, y = float(screen_point[0]), float(screen_point[1])
        return (x - self._offset.x(), y - self._offset.y())

    def _body_radius(self, ray_length: float = 0.0) -> float:
        """身体（含头部）在屏幕上的半径，逻辑像素。

        射线要从**身体边缘**起笔，不能从体心算固定比例：
        词就在脚边上时（感应场景里很常见 —— 字幕往往就在蜘蛛旁边），
        固定 `0.32` 的起笔点会落在身体**外面**，那束光就凭空从半空中开始，
        用户看到的是「来路不明的一条斜杠」。

        桌宠桩（单元测试里的 `FakePet`，没有 painter / sprite_w）退回
        「距离 >120px 时空出前 32%」这条老规则，测试语义不变。
        """
        try:
            painter = self.pet.painter
            spec = painter.skin_spec()
            _sx, _sy, body_w, body_h = painter.body_size(self.pet.sprite_w)
            head = spec.head_l * 0.5 * (body_w / 2.4)
            return max(24.0, max(body_w, body_h) * 0.5 + head)
        except Exception:                             # noqa: BLE001
            return 0.32 * ray_length if ray_length > 120 else 0.0

    def _draw_ray(self, painter) -> None:
        """身体中心 → 词的一束渐细短射线，700ms 内淡出。

        不画「从脚出去」：§7.2 明说腿不伸向词，射线的起点必须是身体/头部，
        不然用户看到的就是「蜘蛛想踩又没踩」，和瞄准层分不清。
        """
        age = (time.monotonic() - self._notice["t0"]) * 1000.0
        k = max(0.0, min(1.0, age / RAY_MS))
        alpha = int(150 * (1.0 - k))
        if alpha <= 6:
            return
        start = self._local(self.pet.center)
        end = self._local(self._notice["point"])
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux
        # 从身体边缘起笔（见 `_body_radius`）：身体和它自己的阴影会盖住这一段
        offset = min(self._body_radius(length), length * 0.8)
        p0 = (start[0] + ux * offset, start[1] + uy * offset)
        base = 5.0 * (1.0 - k * 0.5)
        tip = 0.8
        poly = QPolygonF([
            QPointF(p0[0] + nx * base, p0[1] + ny * base),
            QPointF(end[0] + nx * tip, end[1] + ny * tip),
            QPointF(end[0] - nx * tip, end[1] - ny * tip),
            QPointF(p0[0] - nx * base, p0[1] - ny * base),
        ])
        path = QPainterPath()
        path.addPolygon(poly)
        painter.fillPath(path, QColor(ACCENT.red(), ACCENT.green(),
                                      ACCENT.blue(), alpha))

    def _draw_flash(self, painter) -> None:
        """词本体上的细边框：先快速闪一下再淡掉（不填满、不盖字）。"""
        age = (time.monotonic() - self._notice["t0"]) * 1000.0
        k = max(0.0, min(1.0, age / FLASH_MS))
        # 前 120ms 满亮，之后线性淡出；`0.35 + 0.65*(1-k)` 保证淡出尾段还能看见
        alpha = int(255 * (0.35 + 0.65 * (1.0 - k))) if age > 120 else 255
        x, y, w, h = self._notice["box"]
        rect_x = x - self._offset.x() - BOX_PAD
        rect_y = y - self._offset.y() - BOX_PAD
        pen = QPen(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), alpha))
        pen.setWidthF(1.6)
        painter.setPen(pen)
        painter.setBrush(HAZE)
        painter.drawRoundedRect(rect_x, rect_y, w + BOX_PAD * 2, h + BOX_PAD * 2, 3.0, 3.0)

    def _draw_chip(self, painter) -> None:
        """状态条（§7.3「感应中 · 本地识别 · 最近扫描时间」）。

        贴在蜘蛛身体旁边而不是屏幕角上：屏幕角会压着任务栏/视频控件，
        而蜘蛛在哪用户本来就在看哪。
        """
        text = self.session.status_text()
        metrics = self._chip_metrics
        x, y, width, height = self._chip_geometry(metrics)
        painter.setFont(self._chip_font)
        painter.setPen(QPen(CHIP_BORDER, 1.0))
        painter.setBrush(CHIP_BG)
        painter.drawRoundedRect(x, y, width, height, 8.0, 8.0)
        painter.setPen(INK if self.session.state == "running" else SUB)
        painter.drawText(x + 10, y + 10 + metrics.ascent(), text)

    def _chip_geometry(self, metrics) -> tuple:
        """状态条的矩形（**局部坐标** x, y, w, h）。

        绘制和 `chip_rect()`（给感应排除区用）必须走同一份算法，
        否则「挡掉自己那行字」会挡到别处去。
        """
        text = self.session.status_text()
        width = metrics.horizontalAdvance(text) + 20
        height = metrics.height() + 12
        center = self._local(self.pet.center)
        x = max(8.0, min(self.width() - width - 8.0, center[0] - width / 2))
        y = max(8.0, center[1] + 46)
        return (x, y, width, height)

    def chip_rect(self) -> tuple:
        """状态条在**屏幕逻辑坐标**里的矩形 `(x, y, w, h)`。

        为什么单独暴露：这一层铺满整个虚拟桌面，不能整层塞进「别认出自己」的
        排除区（那样 12 个格子会被全部屏蔽 → 感应直接看不见屏幕，
        实测踩过，见 `pet_window._sense_exclude_rects`）。这层上唯一可能被
        OCR 认成屏幕英文的东西就是这行状态文字，所以只排它这一小块。
        """
        x, y, width, height = self._chip_geometry(self._chip_metrics)
        return (x + self._offset.x(), y + self._offset.y(), width, height)

    # ---------------------------------------------------------------- 点击（只观察，不吞）
    def _install_hook(self) -> bool:
        try:
            self._hook_cb = HOOKPROC(self._hook_proc)
            handle = _USER32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_cb, None, 0)
            if not handle:
                self._hook_cb = None
                return False
            self._hook = handle
            return True
        except Exception as error:                    # noqa: BLE001
            self._hook_cb = None
            _log_hook = getattr(self.pet, "_sense_log", None)
            if callable(_log_hook):
                _log_hook("[sense] SetWindowsHookEx 异常: %r" % (error,))
            return False

    def _uninstall_hook(self) -> None:
        if self._hook:
            try:
                _USER32.UnhookWindowsHookEx(self._hook)
            finally:
                self._hook = None
                self._hook_cb = None

    def _logical_point(self, pt) -> tuple:
        """钩子给的是**物理像素**，而 `screen_box` 是 Qt 逻辑像素 —— 高缩放不除 DPR 会点空。

        和 `aim_overlay._logical_point` 同一个坑、同一个解法（那边实测过：
        125%/150% 下直接比物理坐标，「点中词旁边的空白也算点词」）。
        """
        try:
            dpr = float(self.devicePixelRatioF()) or 1.0
        except Exception:                             # noqa: BLE001
            dpr = 1.0
        return (pt.x / dpr, pt.y / dpr)

    def _hook_proc(self, n_code, w_param, l_param):
        # ★ 这条路径**永远返回 0 且不吞事件**：视频控制条、游戏 UI、
        #   任何用户点击都必须照常落到底下的窗口（§7.2）。
        try:
            if n_code == HC_ACTION and w_param == WM_LBUTTONDOWN \
                    and self._notice is not None:
                info = _hook_point(l_param)
                if info is not None:
                    point = self._logical_point(info.pt)
                    if self._over_notice(point):
                        # 钩子跑在系统消息泵里，这里**不能**开窗口；
                        # 记一笔，回事件循环再处理（和瞄准层同一个规矩）。
                        self._clicked = True
        except Exception:                             # noqa: BLE001
            pass
        return _USER32.CallNextHookEx(wintypes.HHOOK(self._hook),
                                      n_code, w_param, l_param)

    def _over_notice(self, point) -> bool:
        x, y, w, h = self._notice["box"]
        pad = BOX_PAD + 4.0
        return (x - pad <= point[0] <= x + w + pad
                and y - pad <= point[1] <= y + h + pad)

    def _open_gloss(self) -> None:
        if self.on_word_click is None or self._notice is None:
            return
        # 先取词再清提示：回调里可能弹卡片、可能抛异常，别让 UI 停在半亮状态
        item = self._notice["item"]
        self._notice = None
        self.on_word_click(item)


# ---------------------------------------------------------------- ctypes 小工具
#
# 单独包一层是为了让 `test_sense_overlay` 能在没有真鼠标的情况下伪造一次点击。


def _hook_point(l_param):
    """`LPARAM` → 钩子结构体；拿不到就返回 None（**不抛**，钩子里抛异常会断消息链）。"""
    try:
        return ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
    except Exception:                                           # noqa: BLE001
        return None
