# -*- coding: utf-8 -*-
"""启动台（真机版）—— `ui-preview/启动台.html` 的 PySide6 移植。

读法（和原型一致，四轮纠偏后的定稿）：**整个窗口是一个圆柱玻璃瓶的正视图**。
`TitleBar` = 盖子、`JarView` = 透明瓶身、下半那块面板 = 瓶身的标签（所以是矩形）。
瓶身不画实体：Qt 里「透明」= **不绘制**，只画两条侧壁 + 底面椭圆。
（原型里那层整面磨砂在 Qt 版曾用品味等价实现过，2026-10-17 按用户要求删除。）

和原型的关键差别（都是「按源文件适配」的结果，不是偷懒）：
1. 瓶里的蜘蛛**不是 JS 那份移植**，而是直接用 `crawler_spider.Spider` +
   `spider_painter.SpiderPainter`（各自独立实例，不与桌宠共用），
   所以形象、配色、`THORAX_SCALE`、腿型永远和真机一致；
2. 瓶内蜘蛛**不再做任何磨砂/模糊**（2026-10-17 用户要求删除高斯模糊）——
   直接画进 QImage 贴到罩内，玻璃质感由 `glass_case.png` 素材承担；
3. 白闪做成**贴在瓶身上**的矩形（`JarView.flash`），不再开全屏窗：
   全屏纯白闪一下在真机上是「屏幕坏了」，而且要多一个顶层窗、要管多屏 DPI。
   时长和过渡照旧（瞬间不透明 → 110ms 淡出 → 兜底复位）。

时间轴（和原型同一套毫秒数）：
    部署  0 裂纹一档 / 180 二档 + 轻震 / 420 三档 + 重震 + 碎片 /
         620 破罐（蜘蛛冲出、瓶身淡出）/ 740 已部署 → 交给 `main.py` 建桌宠
    收回  0 罐内闪白 / 120 起落 / 250·330·400 三层依次愈合 / 555 落地 /
         620 上沿亮边复位 / 680 空闲
"""

from __future__ import annotations

import math
import os
import random
import time

from PySide6.QtCore import (QByteArray, Qt, QPointF, QRect, QRectF, QSize,
                            QPropertyAnimation, Property, QEasingCurve,
                            QEvent, QTimer, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QIcon, QImage,
                           QPainter, QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox,
                              QComboBox, QLineEdit,
                              QDialog, QFrame, QHBoxLayout, QLabel,
                              QPushButton, QScrollArea, QSizePolicy,
                              QSlider, QVBoxLayout, QWidget)

import crawler_spider as CS
import ui_theme
from spider_painter import (DEFAULT_SKIN, SKIN_SPECS, SpiderPainter, SpiderState,
                            skin_options)
from wordbook import DAY, STAGES
from lexara_theme import APP_QSS
# 2026-10-18：「最大识词」滑杆的区间要和 `settings_store.BOUNDS` 用同一个数，
# 否则会出现「滑杆拖到 12、存下来还是 8」。`settings_store` 不反向依赖本模块
# （它只在 `_skin_id` 里惰性 import 画笔），所以顶层 import 没有循环。
from settings_store import DEFAULTS, MAX_WORDS_RANGE

# ---------------------------------------------------------------- LEXARA design tokens

INK = QColor(21, 21, 21)
INK2 = QColor(43, 43, 43)
FAINT = QColor(116, 116, 116)
ACCENT = QColor(47, 107, 255)
ACCENT_DEEP = QColor(47, 107, 255)
ACCENT_GLOW = QColor(47, 107, 255)
GREEN = QColor(79, 118, 95)
WARN = QColor(138, 106, 43)
BAD = QColor(196, 77, 71)
LINE = "#E4E4DF"
LINE2 = "#CFCFCA"
RADIUS = 12
RADIUS_SM = 8

#: 瓶身比例（LEXARA desktop design system）。2026-10-16 深夜：52→36（整体 2/3）。
TITLEBAR_H = 36
STAGE_STRETCH = 58
PANEL_STRETCH = 42
JAR_MAX_W = 980.0
#: 瓶底椭圆高度 ÷ 瓶身高（paintEvent 第 3 步）。椭圆是画在 `rect.bottom()`
#: **上下各一份** ellipse_h 的，所以 `jar_rect()` 必须按 `1/(1+该值)` 收高，
#: 给下半份留出位置 —— 两个数必须一起改。
BOTTOM_ELLIPSE_FRAC = 0.13
#: 瓶身与托盘的间距（见 `jar_rect` / `plate_rect`）。
PLATE_PAD = 8.0
#: 六档按钮的行高与行距。玻璃罐现在就住在这一块的右半边，
#: 高度按 `6 × MODE_ROW_H + 5 × MODE_ROW_GAP` 定死（见 `Panel.__init__`），
#: 所以这三个数必须一起改 —— 单独改任一个，罐子就和按钮块对不齐了。
#: 用户 2026-10-16 深夜：整体收紧到原尺寸的 2/3（42→28 / 6→4 / 52→36）。
MODE_ROW_H = 28
MODE_ROW_GAP = 4
WALL_FRAC = 0.032          # 侧壁宽 = 瓶身宽的 3.2%（一律按比例，不写死 px）
CRACK_ON_ALPHA = 0.72      # 原型 `.crack.on{opacity:.72}`
IMPACT = (0.500, 0.440)    # 撞击点 = make_cracks.py 的 IMPACT，改动要一起改
#: 玻璃罩素材的比例（assets/ui/glass_case.png 1448×1086）。用素材后按它自身
#: 比例摆，不再走手绘椭圆那套 1.30 的站姿约束。
CASE_ASPECT = 1448.0 / 1086.0
#: 罩内地面线（占罩高比例）—— 素材底沿玻璃厚度约在 0.88 处，蜘蛛脚落在 0.86。
CASE_GROUND_FRAC = 0.58
FALL_SECONDS = 0.35
MONO = "Consolas"

# ---------------------------------------------------------------- SVG / micro-interaction helpers
# 所有功能图标统一走内联 SVG，避免系统字体/emoji 在不同 Windows 环境下出现字形跳变。
def _svg_icon(svg: str, size: int = 16) -> QIcon:
    """把轻量内联 SVG 渲染成 QIcon；失败时返回空图标，由按钮文字兜底。"""
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

CLOSE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="#2B2B2B" stroke-width="1.9" stroke-linecap="round">'
    '<path d="M7 7l10 10M17 7L7 17"/></svg>'
)
#: 用户 2026-10-16：窗口控制按钮（最小化 / 最大化·还原），放在关闭的左边。
MIN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="#2B2B2B" stroke-width="1.9" stroke-linecap="round">'
    '<path d="M6 12h12"/></svg>'
)
MAX_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="#2B2B2B" stroke-width="1.9" stroke-linejoin="round">'
    '<rect x="6.2" y="6.2" width="11.6" height="11.6" rx="1.6"/></svg>'
)
RESTORE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="#2B2B2B" stroke-width="1.9" stroke-linejoin="round">'
    '<path d="M9 8.6V6.6A1.6 1.6 0 0 1 10.6 5h6.8A1.6 1.6 0 0 1 19 6.6v6.8'
    'a1.6 1.6 0 0 1 -1.6 1.6h-2"/>'
    '<rect x="5" y="9" width="10" height="10" rx="1.6"/></svg>'
)


def _skin_swatch(leg_hex: str, outline_hex: str, size: int = 14) -> QIcon:
    """皮肤色板：一个带描边的圆点，取该皮肤的腿色。

    用它而不是真实渲染一只蜘蛛当缩略图：桌宠实际大小在 14px 下完全糊掉，
    而「腿色」恰好是四套皮肤最容易一眼区分的特征（蓝 / 白 / 黑 / 黄）。
    """
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    inset = 1.6
    painter.setBrush(QColor(leg_hex))
    painter.setPen(QPen(QColor(outline_hex), 1.3))
    painter.drawEllipse(QRectF(inset, inset, size - inset * 2, size - inset * 2))
    painter.end()
    return QIcon(QPixmap.fromImage(image))

BOOKMARK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="#2F6BFF" stroke-width="1.8" stroke-linejoin="round">'
    '<path d="M7 4.5h10a1 1 0 0 1 1 1V20l-6-3.6L6 20V5.5a1 1 0 0 1 1-1z"/></svg>'
)

BOOKMARK_FILLED_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<path fill="#2F6BFF" d="M7 4.5h10a1 1 0 0 1 1 1V20l-6-3.6L6 20V5.5a1 1 0 0 1 1-1z"/></svg>'
)

#: 六档学习范围：`key` 必须是 `lexicon.MODE_LABELS` 里的真键，
#: 词数从 `Lexicon.status()` 现取（不在这里写死数字，见 `_build_modes`）。
MODE_KEYS = ("cet4", "cet6", "ky", "ielts", "toefl", "industry")

def _fmt(n: int) -> str:
    """词数：`3,849 词`（原型用 mono + 千分位）。"""
    return "{:,} 词".format(int(n))


def _corners(rect: QRectF, radius: float, top: bool = True,
             bottom: bool = True) -> QPainterPath:
    """按哪几头要圆角拼一条闭合路径。

    ★ 别用「`addRoundedRect` 再 `subtracted` 掉 1px」去假装只圆一头 ——
      上圆角其实还在，只是被一条直角带盖住，接缝处会露出一圈不该有的弧。
      瓶子的读法是「盖子压瓶身、瓶身压标签」，相接的那两头**必须直角**。
    """
    r = max(0.0, radius)
    path = QPainterPath()
    if top:
        path.moveTo(rect.left(), rect.top() + r)
        path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
    else:
        path.moveTo(rect.left(), rect.top())
    path.lineTo(rect.right() - (r if top else 0), rect.top())
    if top:
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
    path.lineTo(rect.right(), rect.bottom() - (r if bottom else 0))
    if bottom:
        path.quadTo(rect.right(), rect.bottom(), rect.right() - r, rect.bottom())
    path.lineTo(rect.left() + (r if bottom else 0), rect.bottom())
    if bottom:
        path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - r)
    path.closeSubpath()
    return path


# ---------------------------------------------------------------- 小部件


class ModeRow(QAbstractButton):
    """一档一整行的长矩形：名称在左、词数靠右、选中记号钉在最右。

    继承 `QAbstractButton` 是为了拿到互斥（`QButtonGroup` 管）+ 键盘聚焦 +
    `accessibleName`，样式全部自绘 —— 和原型 `.mode` 那条规则一一对应。
    """

    def __init__(self, key: str, name: str, count_text: str, na: bool = False,
                 parent=None):
        super().__init__(parent)
        self.key = key
        self.name = name
        self.count_text = count_text
        self.na = na                     # 词表里没有这一档 → 可选但标黄
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(name)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(MODE_ROW_H)
        self._hover_progress = 0.0
        self._select_progress = 1.0 if self.isChecked() else 0.0
        self._hover_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(220)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._select_anim = QPropertyAnimation(self, b"selectProgress", self)
        self._select_anim.setDuration(220)
        self._select_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate_selected)

    def _get_hover(self) -> float:
        return self._hover_progress

    def _set_hover(self, value: float) -> None:
        self._hover_progress = float(value)
        self.update()

    hoverProgress = Property(float, _get_hover, _set_hover)

    def _get_selected(self) -> float:
        return self._select_progress

    def _set_selected(self, value: float) -> None:
        self._select_progress = float(value)
        self.update()

    selectProgress = Property(float, _get_selected, _set_selected)

    def _animate_selected(self, checked: bool) -> None:
        self._select_anim.stop()
        self._select_anim.setStartValue(self._select_progress)
        self._select_anim.setEndValue(1.0 if checked else 0.0)
        self._select_anim.start()

    def enterEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(200, MODE_ROW_H)

    def paintEvent(self, event):                    # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        checked = self.isChecked()
        hover = self._hover_progress
        selected = self._select_progress

        # LEXARA geometry: quiet surface + one accent + a small diagonal cut.
        fill = QColor(255, 255, 255)
        if hover > 0.01:
            fill = QColor(247, 247, 244)
        if selected > 0.01:
            fill = QColor(238, 243, 255)

        border = QColor(228, 228, 223, int(255 - 80 * hover))
        if selected > 0.01:
            border = QColor(47, 107, 255, int(110 + 90 * selected))

        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, RADIUS_SM, RADIUS_SM)

        # Selected marker: vertical accent with a geometric diagonal end.
        if selected > 0.01:
            accent = QColor(WARN if self.na else ACCENT)
            accent.setAlpha(int(255 * selected))
            x = rect.right() - 8
            y = rect.top() + 9
            h = rect.height() - 18
            path = QPainterPath()
            path.moveTo(x - 4, y)
            path.lineTo(x, y)
            path.lineTo(x, y + h)
            path.lineTo(x - 4, y + h)
            path.lineTo(x - 1, y + h / 2)
            path.closeSubpath()
            painter.setPen(Qt.NoPen)
            painter.setBrush(accent)
            painter.drawPath(path)

        name_color = QColor(WARN if self.na and checked else INK)
        if selected > 0.01 and not self.na:
            name_color = ACCENT
        painter.setPen(name_color)
        font = QFont(self.font())
        font.setPointSizeF(10.5)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(14, 0, rect.width() * 0.48, rect.height()),
                         int(Qt.AlignVCenter | Qt.AlignLeft), self.name)

        mono = QFont(MONO)
        mono.setPointSizeF(8.5)
        painter.setFont(mono)
        painter.setPen(FAINT)
        count_w = QFontMetrics(mono).horizontalAdvance(self.count_text)
        painter.drawText(QRectF(rect.width() - 52 - count_w, 0, count_w + 2,
                                rect.height()),
                         int(Qt.AlignVCenter | Qt.AlignRight), self.count_text)

        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(ACCENT, 1.5))
            painter.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5),
                                    RADIUS_SM + 1, RADIUS_SM + 1)
        painter.end()


class GearButton(QAbstractButton):
    """设置入口：inline SVG 画的齿轮（原型第四轮把「设置」两个字换成图标）。

    颜色跟 `currentColor` 走 → 用 `QPalette` 的文本色渲染，
    hover 时 SVG 本体转 45°（`_angle` 由一个 16ms 定时器插值）。
    """

    SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           'fill="none" stroke="currentColor" stroke-width="1.9" '
           'stroke-linecap="round">'
           '<circle cx="12" cy="12" r="3.7"/>'
           '<path d="M18.2 12h2.4M16.38 16.38l1.7 1.7M12 18.2v2.4 '
           'M7.62 16.38l-1.7 1.7M5.8 12H3.4M7.62 7.62L5.92 5.92M12 5.8V3.4 '
           'M16.38 7.62l1.7-1.7"/></svg>')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("gearBtn")
        self.setFixedSize(28, 28)
        self.setToolTip("设置")
        self.setAccessibleName("设置")
        self.setCursor(Qt.PointingHandCursor)
        self._angle = 0.0
        self._target = 0.0
        self._open = False
        try:
            from PySide6.QtSvg import QSvgRenderer
            self._renderer = QSvgRenderer(QByteArray(self.SVG.encode("utf-8")))
        except Exception:                          # noqa: BLE001
            self._renderer = None                  # 没有 QtSvg 就退成「设置」文字
        self._spin = QTimer(self, interval=16)
        self._spin.timeout.connect(self._step_angle)
        # 2026-10-17 性能修正：以前构造时就 `start()` 且永不停止 —— 每个齿轮
        # 一个 16ms 定时器，纯为「可能 hover」空转。现在只在真的需要插值时开。
        #: SVG 剪影 / tint 后贴图按颜色缓存（原来每次 paintEvent 重建两张 16px 图）
        self._stencil: QImage | None = None
        self._tint_cache: dict[str, QPixmap] = {}

    def _start_spin(self) -> None:
        if abs(self._angle - self._target) >= 0.4 and not self._spin.isActive():
            self._spin.start()

    def setOpenVisual(self, opened: bool) -> None:
        self._open = opened
        self.setProperty("open", "true" if opened else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def enterEvent(self, event):                   # noqa: ARG002
        self._target = 45.0
        self._start_spin()
        super().enterEvent(event)

    def leaveEvent(self, event):                   # noqa: ARG002
        self._target = 0.0
        self._start_spin()
        super().leaveEvent(event)

    def _step_angle(self) -> None:
        """16ms 一格的插值：`transform .32s ease` 的近似。到位即停定时器。"""
        if abs(self._angle - self._target) < 0.4:
            self._spin.stop()
            if self._angle != self._target:
                self._angle = self._target
                self.update()
            return
        self._angle += (self._target - self._angle) * 0.18
        self.update()

    def paintEvent(self, event):                   # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if self.underMouse() or self._open:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(238, 243, 255) if self._open else QColor(240, 240, 237))
            painter.drawRoundedRect(rect, RADIUS_SM, RADIUS_SM)

        color = QColor(ACCENT if self._open else
                       (INK if self.underMouse() else INK2))
        if self._renderer is None:
            painter.setPen(color)
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            painter.drawText(self.rect(), int(Qt.AlignCenter), "设置")
        else:
            painter.save()
            center = self.rect().center()
            painter.translate(center)
            painter.rotate(self._angle)
            painter.translate(-center)
            target = QRectF(center.x() - 8, center.y() - 8, 16, 16)
            # SVG 剪影只渲一次；tint 结果按颜色键缓存。
            # 原来每次 paintEvent 都要 render + 两张 16px 图重建，hover 期间
            # 配合 16ms 插值定时器等于每秒 ~60 次白干活。
            if self._stencil is None:
                stencil = QImage(16, 16, QImage.Format_ARGB32_Premultiplied)
                stencil.fill(Qt.transparent)
                inner = QPainter(stencil)
                inner.setRenderHint(QPainter.Antialiasing, True)
                self._renderer.render(inner, QRectF(0, 0, 16, 16))
                inner.end()
                self._stencil = stencil
            else:
                stencil = self._stencil
            cache_key = color.name()
            tinted = self._tint_cache.get(cache_key)
            if tinted is None:
                tinted = QPixmap(16, 16)
                tinted.fill(Qt.transparent)
                tp = QPainter(tinted)
                tp.setCompositionMode(QPainter.CompositionMode_Source)
                tp.fillRect(tinted.rect(), color)
                tp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                tp.drawImage(0, 0, stencil)
                tp.end()
                if len(self._tint_cache) > 8:      # 颜色只有 3 种，防万一
                    self._tint_cache.clear()
                self._tint_cache[cache_key] = tinted
            painter.drawPixmap(target, tinted, QRectF(0, 0, 16, 16))
            painter.restore()
        painter.end()


class WordChip(QPushButton):
    """一张复习卡：词 + 徽标 + 释义 + 四道间隔点（对应原型 `.word`）。"""

    def __init__(self, item, due_text: str, tone: str, stage: int, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("wordChip")
        self.setFixedSize(176, 44)
        self.setCursor(Qt.PointingHandCursor)
        self._word = item.get("word", "") if isinstance(item, dict) else item.word
        self._meaning = (item.get("meaning", "") if isinstance(item, dict)
                         else item.meaning)
        self._due_text = due_text
        self._tone = tone                        # today / later / done
        self._stage = stage
        self._hover_progress = 0.0
        self._hover_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(220)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setToolTip("%s　%s" % (self._word, self._meaning))

    def _get_hover(self) -> float:
        return self._hover_progress

    def _set_hover(self, value: float) -> None:
        self._hover_progress = float(value)
        self.update()

    hoverProgress = Property(float, _get_hover, _set_hover)

    def enterEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(176, 44)

    def paintEvent(self, event):                 # noqa: ARG002
        # Base button surface is provided by APP_QSS; custom content is drawn here.
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(10, 5, -10, -5)

        top = QFont("Microsoft YaHei UI", 10)
        top.setWeight(QFont.DemiBold)
        painter.setFont(top)
        fm = QFontMetrics(top)
        word_avail = max(0, rect.width() - 46)
        painter.setPen(INK)
        painter.drawText(QRect(rect.left(), rect.top(), word_avail, 16),
                         int(Qt.AlignVCenter | Qt.AlignLeft),
                         fm.elidedText(self._word, Qt.ElideRight, word_avail))

        badge = ACCENT if self._tone == "today" else INK2
        mono = QFont(MONO, 7)
        painter.setFont(mono)
        bf = QFontMetrics(mono)
        bw = bf.horizontalAdvance(self._due_text) + 8
        br = QRect(rect.right() - bw, rect.top() + 1, bw, 14)
        painter.setPen(QPen(QColor(badge), 1))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(br, 6, 6)
        painter.setPen(badge)
        painter.drawText(br, int(Qt.AlignCenter), self._due_text)

        mfont = QFont("Microsoft YaHei UI", 8)
        painter.setFont(mfont)
        mf = QFontMetrics(mfont)
        painter.setPen(INK2)
        dots_x = rect.right() - 4 * 11
        mean_avail = max(0, dots_x - rect.left() - 6)
        painter.drawText(QRect(rect.left(), rect.bottom() - 15, mean_avail, 14),
                         int(Qt.AlignVCenter | Qt.AlignLeft),
                         mf.elidedText(self._meaning, Qt.ElideRight, mean_avail))

        for index in range(4):
            on = index <= self._stage
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(ACCENT if on else 222, 222, 218) if not on else ACCENT)
            painter.drawRoundedRect(QRectF(dots_x + index * 11,
                                           rect.bottom() - 9.0, 8, 3), 1.5, 1.5)
        painter.end()


class TitleBar(QWidget):
    """盖子：自己接管那块玻璃（原型里 `.titlebar` 是独立的一条）。"""

    close_clicked = Signal()

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(TITLEBAR_H)
        self.setCursor(Qt.OpenHandCursor)
        self._drag = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(10)
        # 用户 2026-10-16 深夜：左上角让给 LEXARA logo，原「词蛛LEXARA」文字退场。
        # logo 是透明底深色字 PNG，贴白底正好；高度按标题栏内高自适应。
        # title/subtitle 仍保留属性（外部 `_on_mode_selected` 会改 subtitle 文本），
        # 但不再上屏 —— 位置腾给 logo，外部引用零改动。
        self.logo = QLabel()
        try:
            from wordbook import resource_path
            _logo_pix = QPixmap(resource_path("assets", "logo_lexara.png"))
        except Exception:  # noqa: BLE001   素材缺失时退回文字标题
            _logo_pix = QPixmap()
        if not _logo_pix.isNull():
            self.logo.setPixmap(_logo_pix.scaledToHeight(
                max(16, TITLEBAR_H - 14), Qt.SmoothTransformation))
        self.title = QLabel(title)
        self.title.setObjectName("winTitle")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("winTitleSub")
        self.chip = QLabel("● 待命 · 词表已就绪")
        self.chip.setObjectName("statusChip")
        self.gear = GearButton(self)
        # ★ 不能叫 `self.close`：那会**盖掉 `QWidget.close()` 方法**，
        #   之后谁写 `title_bar.close()` 都会炸。
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setAccessibleName("关闭启动台")
        self.close_btn.setToolTip("关闭启动台")
        self.close_btn.setIcon(_svg_icon(CLOSE_SVG, 16))
        self.close_btn.setIconSize(QSize(16, 16))
        self.close_btn.clicked.connect(self.close_clicked)

        # 用户 2026-10-16：右上角加「最小化 / 最大化」，放在关闭的左边。
        # 窗口是 FramelessWindowHint，系统自带的三颗钮没有 —— 这里手工补齐。
        # 最大化是**开关**：已最大化就还原，图标跟着切（ maximize ↔ restore）。
        self.min_btn = QPushButton()
        self.min_btn.setObjectName("winBtn")
        self.min_btn.setFixedSize(30, 30)
        self.min_btn.setCursor(Qt.PointingHandCursor)
        self.min_btn.setAccessibleName("最小化")
        self.min_btn.setToolTip("最小化")
        self.min_btn.setIcon(_svg_icon(MIN_SVG, 16))
        self.min_btn.setIconSize(QSize(16, 16))
        self.min_btn.clicked.connect(lambda: self.window().showMinimized())

        self.max_btn = QPushButton()
        self.max_btn.setObjectName("winBtn")
        self.max_btn.setFixedSize(30, 30)
        self.max_btn.setCursor(Qt.PointingHandCursor)
        self.max_btn.setAccessibleName("最大化")
        self.max_btn.setToolTip("最大化 / 还原")
        self.max_btn.setIcon(_svg_icon(MAX_SVG, 16))
        self.max_btn.setIconSize(QSize(16, 16))
        self.max_btn.clicked.connect(self._toggle_maximized)

        if not self.logo.pixmap().isNull():
            layout.addWidget(self.logo)
        else:
            layout.addWidget(self.title)   # 素材缺失时退回文字标题
        layout.addStretch(1)
        layout.addWidget(self.chip)
        layout.addWidget(self.gear)
        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

    def _toggle_maximized(self) -> None:
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()
        self.sync_max_icon()

    def sync_max_icon(self) -> None:
        """窗口状态变了（含用户从任务栏还原）→ 换 maximize / restore 图标。"""
        self.max_btn.setIcon(_svg_icon(
            RESTORE_SVG if self.window().isMaximized() else MAX_SVG, 16))

    def set_status(self, text: str, color: QColor) -> None:
        """状态条：点用 HTML 上色，正文保持规范色（原型 `.chip-status b`）。"""
        self.chip.setText('<span style="color:%s">●</span> %s'
                          % (color.name(), text))
        self.chip.setTextFormat(Qt.RichText)

    def paintEvent(self, event):                 # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = _corners(rect, RADIUS, top=True, bottom=False)
        painter.setPen(QPen(QColor(228, 228, 223), 1))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(235, 235, 231), 1))
        painter.drawLine(QPointF(rect.left() + RADIUS, rect.bottom() - 0.5),
                         QPointF(rect.right() - RADIUS, rect.bottom() - 0.5))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.window().pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------- 瓶身


class JarView(QWidget):
    """透明瓶身：两条侧壁 + 底面椭圆 + 三档裂纹 + 碎片 + 罐内白闪。

    z 序（原型的硬顺序，一层都不能倒；磨砂层 2026-10-17 已删，编号保留注释）：
    蜘蛛(1) → ~~磨砂(2)~~ → 瓶底椭圆(3) → 侧壁(4) → 裂纹(5) → 碎片(6) → 闪白(7)。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.spider = CS.Spider(size=1.0)
        self.spider.origin_px = (0.0, 0.0)
        # 自己的画笔实例：`SpiderPainter` 会缓存 `_unit/_origin/_cos/_sin`，
        # 和桌宠共用一个对象会互相踩掉变换矩阵。
        self.painter = SpiderPainter()
        self._rng = random.Random(20261015)

        self.phase = "idle"
        self.opened = False
        self.crack_level = 0
        self._crack_alpha = [0.0, 0.0, 0.0]
        self.fade = 1.0
        self._fade_target = 1.0
        self.flash = 0.0
        self.shake = 0.0
        self._shake_t = 0.0
        self.spider_visible = True
        self.debris = []
        self.fall = None                         # (t0, from_y, to_y)
        self._last = time.monotonic()

        # 瓶内位置（瓶身局部像素）
        self.x = 0.0
        self.y = 0.0
        self._last_x = 0.0
        self.dir = 1
        self._cracks = [QPixmap(), QPixmap(), QPixmap()]
        self._shatter = QPixmap()
        self._shatter_at = None
        self._crack_size = QSize(0, 0)
        #: 罐内有没有动画在跑（`_tick` 每帧更新，`_set_animating` 负责唤醒重绘）
        self._animating = True
        #: 相位切换等事件要求「下一帧必须重画一次」（见 `has_changed`）
        self._dirty = False
        #: 上一次 paintEvent 时的控件尺寸（resize 后强制重画一次用）
        self._last_paint_size = QSize(0, 0)
        self.set_crack_paths()

        self._timer = QTimer(self, interval=33)  # ~30fps，瓶内不需要 60fps
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------ 资源
    def set_crack_paths(self) -> None:
        from wordbook import resource_path
        for index in range(3):
            path = resource_path("assets", "jar_crack_0%d.png" % (index + 1))
            self._cracks[index].load(path)
        # ★ 2026-10-18（任务书 §2.4）：常驻玻璃罐素材**不再加载**。
        #   展示区改成「半透明白圆角矩形 + 蜘蛛 + 顶层裂纹/碎片」，玻璃瓶身
        #   与托盘一起下线；`glass_case.png` 仍留在 assets 里（旧 Widgets 界面
        #   与回退开关不需要它，但删素材没有收益）。
        self._shatter = QPixmap(resource_path("assets", "ui", "spider_web.png"))
        self._shatter_at = None
        self._crack_size = QSize(0, 0)
        self.update()

    # ------------------------------------------------ 几何
    def stage_rect(self) -> QRectF:
        """展示区 = 半透明白色圆角矩形（任务书 §2.4 的「最底层」）。

        整个控件就是展示区，只留 1px 描边余量 —— QML 那边给定尺寸，
        这里不再按玻璃罩比例反推，少一层「容器套容器」的空白。
        """
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        return QRectF(1.0, 1.0, w - 2.0, h - 2.0)

    def plate_rect(self) -> QRectF:
        """兼容旧诊断脚本（`tools/render_layout.py` 还在调）。"""
        return self.stage_rect()

    def jar_rect(self) -> QRectF:
        """兼容旧诊断脚本（`tools/launcher_probe.py` 还在调）。"""
        return self.stage_rect()

    def wall_w(self) -> float:
        """没有瓶壁了；保留方法以免旧脚本 KeyError。"""
        return 0.0

    def unit(self) -> float:
        rect = self.stage_rect()
        # 蜘蛛占展示区宽度的一半左右：再大就顶到圆角，再小就显得空
        return SpiderPainter.unit_for_width(min(rect.width() * 0.52,
                                                 rect.height() * 0.70))

    def bounds(self) -> tuple:
        """(ground, lo, hi, reach) —— 脚落在圆角矩形内部的地面线上。"""
        rect = self.stage_rect()
        unit = self.unit()
        reach = SpiderPainter.max_reach() * CS.BASE_SCALE * unit * CS.REST_K
        ground = min(rect.height() * 0.68,
                     rect.height() - reach - rect.height() * 0.06)
        return ground, rect.width() * 0.28, rect.width() * 0.72, reach

    # ------------------------------------------------ 时间轴接口
    def set_phase(self, phase: str) -> None:
        if phase != self.phase:
            self.phase = phase
            #: 相位一变，无论静不静止都要让 QML 侧重画一帧
            #: （罐子静止时 `_animating` 是 False，光靠它「收回」第一帧不会亮）。
            self._dirty = True
        if phase == "idle":
            self._fade_target = 1.0
            self.spider_visible = True

    def crack_on(self, index: int) -> None:
        self.crack_level = max(self.crack_level, index + 1)

    def crack_heal_to(self, level: int) -> None:
        self.crack_level = max(0, level)

    def start_shake(self, hard: bool = False) -> None:
        self.shake = 7.0 if hard else 3.0
        self._shake_t = 0.0

    def flash_now(self) -> None:
        """瞬间不透明 → 110ms 淡出（`JarView.paintEvent` 里按时间衰减）。"""
        self.flash = 1.0

    def burst_out(self) -> None:
        """破罐：蜘蛛冲出去、瓶身淡出、上沿亮边不再复位（罐子空着）。"""
        self.spider_visible = False
        self.opened = True
        self._fade_target = 0.0
        self._shatter_at = time.monotonic()   # 叠一层 spider_web 碎玻璃

    def begin_fall(self) -> None:
        """收回：从瓶口内侧（盖子接缝下沿）加速落回地面线。"""
        ground, _lo, _hi, _reach = self.bounds()
        top = max(ground - self.jar_rect().height() * 0.62,
                  self.jar_rect().height() * 0.04)
        self.spider_visible = True
        self._fade_target = 1.0
        self.fall = (time.monotonic(), top, ground)
        self.y = top

    def reset(self) -> None:
        """回到空闲：裂纹愈合、亮边回来、蜘蛛重新站上地面线。"""
        self.crack_level = 0
        self.opened = False
        self._fade_target = 1.0
        self.spider_visible = True
        self.debris.clear()
        self.fall = None
        self._shatter_at = None

    def spawn_debris(self) -> None:
        """46 片碎屑从撞击点往外崩（速度单位 = 瓶身像素/秒）。

        ★ 坐标一律用**瓶身局部 x**（0..瓶宽），和 `self.x`、蜘蛛图层同一套，
          绘制时再整体加 `rect.left()`。这里要是混用窗口坐标，瓶子居中后
          碎屑会整体左偏 `(窗宽-瓶宽)/2`。
        """
        rect = self.jar_rect()
        cx, cy = rect.width() * IMPACT[0], rect.height() * IMPACT[1]
        for _ in range(46):
            angle = self._rng.uniform(0.0, math.tau)
            speed = self._rng.uniform(90.0, 320.0)
            self.debris.append({
                "x": cx, "y": cy,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed - 40.0,
                "life": self._rng.uniform(0.5, 1.1),
                "size": self._rng.uniform(1.6, 4.2),
            })

    # ------------------------------------------------ 主循环
    def _set_animating(self, value: bool) -> None:
        """只在「从静止变运动 / 从运动变静止」时触发一次重绘。

        静止 = 罐子空着（已部署、fade≈0）且没有碎片/闪烁/抖动/坠落/淡变在跑。
        以前 `self.update()` 每 33ms 无条件调用，部署完罐子早就空了还在逐帧重绘，
        纯烧 CPU；QML 那边 `JarItem` 又叠了一层 33ms 定时刷新，双倍浪费。
        """
        if value != self._animating:
            self._animating = value
            self.update()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        ground, lo, hi, _reach = self.bounds()

        # 先判「这一帧有没有东西在动」，再决定要不要重绘。
        # 蜘蛛在罐里时永远在踱步 → 一直动；部署完罐子空了 → 立刻静止。
        jar_alive = self.fade > 0.01 or self._fade_target > 0.01
        moving = (jar_alive and self.spider_visible
                  and self.phase in ("idle", "deploying", "recalling"))
        animating = (self.fall is not None or bool(self.debris)
                     or self.flash > 0.0 or self.shake > 0.0 or moving
                     or abs(self.fade - self._fade_target) > 0.001
                     or self._shatter_at is not None
                     or any((1.0 if i < self.crack_level else 0.0) - a > 0.005
                            or a - (1.0 if i < self.crack_level else 0.0) > 0.005
                            for i, a in enumerate(self._crack_alpha)))
        self._set_animating(animating)

        if self.fall is not None:
            t0, from_y, to_y = self.fall
            progress = (now - t0) / FALL_SECONDS
            if progress >= 1.0:
                self.fall = None
                self.y = to_y
                self.start_shake(False)
                self.spawn_debris()          # 落地扫一点玻璃屑
            else:
                # u² = 自由落体的位移曲线
                self.y = from_y + (to_y - from_y) * progress * progress
            self._move_body(0.0, dt, ground)
        elif self.phase in ("idle", "deploying", "recalling") and self.spider_visible:
            speed = 0.30 * 60.0 * self.unit()      # 上限 0.30 局部单位/帧（实测）
            self.x += self.dir * speed * dt
            if self.x < lo:
                self.x, self.dir = lo, 1
            elif self.x > hi:
                self.x, self.dir = hi, -1
            self.y = ground
            self._move_body(self.x - self._last_x, dt, ground)
        else:
            self._last_x = self.x

        # 裂纹透明度：0.12s 线性淡入淡出（原型 `transition:opacity .12s linear`）
        for index in range(3):
            target = 1.0 if index < self.crack_level else 0.0
            delta = target - self._crack_alpha[index]
            step = dt / 0.12
            self._crack_alpha[index] += max(-step, min(step, delta))

        if self.flash > 0:
            self.flash = max(0.0, self.flash - dt / 0.11)
        if self.shake > 0.01:
            self.shake *= math.exp(-dt * 8.0)
            self._shake_t += dt
        else:
            self.shake = 0.0

        fade_delta = self._fade_target - self.fade
        if abs(fade_delta) > 0.001:
            self.fade += max(-dt / 0.30, min(dt / 0.30, fade_delta))

        for piece in list(self.debris):
            piece["life"] -= dt
            if piece["life"] <= 0:
                self.debris.remove(piece)
                continue
            piece["vy"] += 700.0 * dt
            piece["x"] += piece["vx"] * dt
            piece["y"] += piece["vy"] * dt

        if self._animating:
            self.update()

    def has_changed(self) -> bool:
        """QML 侧（`JarItem`）问这一句再决定要不要重画。

        JarView 是隐藏的控制器窗，它自己的 `update()` 在隐藏态不产生像素；
        真正出像素的是 QML 里那层 33ms 定时刷新的 `JarItem`。罐子静止时
        （已部署、里面空着）让 `JarItem` 也停刷，两边就都不做无效功了。

        顺带把「被 resize 后必须重画一次」也纳入：隐藏控件的 paintEvent
        不再跑，`_last_paint_size` 只能在这里对比（尺寸变了 = Qt 已自动
        重绘可见窗口；QML 侧则靠这一句触发 `JarItem.update()`）。
        """
        if self._dirty:
            self._dirty = False
            return True
        if self.size() != self._last_paint_size:
            self._last_paint_size = self.size()
            return True
        return self._animating

    def _move_body(self, dx_px: float, dt: float, ground: float) -> None:
        """把身体位移喂给步态引擎。

        ★ 和 `pet_window._tick` 一模一样：**换算成局部单位**再传
        （`advance()` 活在局部坐标系，喂像素等于把位移放大 `unit` 倍，
        桌宠放大时腿会一直抽）。符号也照抄，所以瓶里的姿态和部署后的
        桌宠是同一套运动学，不会出现「预览朝左、真身朝右」。
        """
        unit = self.unit() or 1.0
        motion = (dx_px / unit, 0.0)
        self._last_x = self.x
        moving = abs(dx_px) > 0.001
        mode = "crawl" if moving else "idle"
        self.spider.origin_px = (self.x, ground)
        self.spider.update(dt, mode, None, motion=motion)

    # ------------------------------------------------ 绘制
    def _spider_layer(self, size: QSize) -> QImage:
        """把蜘蛛画进一层透明 QImage（2026-10-17 起**不再做磨砂模糊**）。

        以前这里等价实现原型的 `backdrop-filter:blur(3.4px)`：先画进 QImage，
        再 cv2.GaussianBlur 一遍。用户明确要求删掉高斯模糊 —— 现在瓶里的蜘蛛
        以清晰姿态直接呈现，玻璃观感由 glass_case.png 素材自己的厚度与反光承担。
        """
        width, height = max(1, size.width()), max(1, size.height())
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        unit = self.unit()
        state = SpiderState(heading=self.spider.heading,
                            moving=abs(self.spider.velocity[0]) > 0.5,
                            dim=1.0)
        try:
            self.painter.paint(painter, self.spider, state, unit=unit,
                               origin_px=(self.x, self.y))
        finally:
            painter.end()
        # ★ 2026-10-17：高斯磨砂**已删除**（用户明确要求）。
        #   以前这里要过 cv2.GaussianBlur（每帧一次，窗口不聚焦时也照跑），
        #   现在蜘蛛直接以清晰姿态站在罩内 —— 玻璃质感交给 glass_case.png 本身。
        return image

    def _scaled(self, pixmap: QPixmap, size: QSize, key: str) -> QPixmap:
        """按目标尺寸缩放并缓存（裂纹/玻璃罩/碎裂图共用一套缓存）。"""
        if self._crack_size != size:
            self._scaled_cache = {}
            self._crack_size = size
        cache = getattr(self, "_scaled_cache", None)
        if cache is None:
            cache = self._scaled_cache = {}
        out = cache.get(key)
        if out is None:
            out = (pixmap.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                   if not pixmap.isNull() else QPixmap())
            cache[key] = out
        return out

    def _crack_pixmap(self, index: int, size: QSize) -> QPixmap:
        """裂纹图按展示区尺寸缩放后缓存 —— 每帧 `scaled()` 一次是白给的开销。"""
        return self._scaled(self._cracks[index], size, "crack%d" % index)

    def _shatter_pixmap(self, size: QSize) -> QPixmap:
        return self._scaled(self._shatter, size, "shatter")

    def paintEvent(self, event):                 # noqa: ARG002
        """三层结构（任务书 §2.4，从上到下）：

        1. 最上层：部署/收回动画用的裂纹、碎片、整块碎玻璃；
        2. 中间层：蜘蛛本体（程序化 IK 绘制，不是贴图）；
        3. 最底层：半透明白色圆角矩形（alpha 0.5）。

        绘制顺序与视觉层序相反 —— 先画底层，最后画顶层。
        常驻玻璃罐贴图已下线：`glass_case.png` 不再加载、不再绘制。
        """
        self._last_paint_size = self.size()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.stage_rect()
        if os.environ.get("LEXARA_JAR_DEBUG"):
            print("[jar] paint %dx%d rect=%.0fx%.0f unit=%.3f" % (
                self.width(), self.height(), rect.width(), rect.height(),
                self.unit()), flush=True)
        # `scaled()` / `drawImage()` 要的是整数 QSize，`rect.size()` 是 QSizeF
        jsize = QSize(int(rect.width()), int(rect.height()))
        radius = min(18.0, rect.height() * 0.08)

        # ---- 第 3 层（最底）：半透明白圆角矩形 -------------------------
        # alpha 128 / 255 ~= 0.5：既不是纯白不透明（会盖住卡片底色、像块白板），
        # 也不是完全透明（那就退回「一片空白」）。描边 1px 让边界可辨。
        # 2026-10-18：这两个值改成主题令牌（stage.overlayAlpha / stage.border），
        # 外部调参页拖一下就能改「白纱」浓淡，不必改源码。
        painter.setPen(QPen(ui_theme.color("stage.border", "#AAE2E1DA"), 1))
        painter.setBrush(ui_theme.stage_overlay())
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        offset = 0.0
        if self.shake > 0:
            offset = math.sin(self._shake_t * 90.0) * self.shake
        painter.save()
        painter.translate(offset, 0.0)

        fade = max(0.0, min(1.0, self.fade))
        if fade > 0.01:
            # ---- 第 2 层（中）：蜘蛛 -----------------------------------
            if self.spider_visible:
                layer = self._spider_layer(jsize)
                painter.setOpacity(fade)
                painter.drawImage(QPointF(rect.left(), rect.top()), layer)
                painter.setOpacity(1.0)

            # ---- 第 1 层（顶）：三档裂纹 -------------------------------
            # 只有 `crack_level > 0` 时才有 alpha；收回时间轴把 crack_level
            # 逐档打回 0，动画结束自然消失，不留任何不透明覆盖层。
            for index in range(3):
                alpha = self._crack_alpha[index]
                if alpha <= 0.01:
                    continue
                pixmap = self._crack_pixmap(index, jsize)
                if pixmap.isNull():
                    continue
                painter.setOpacity(CRACK_ON_ALPHA * alpha * fade)
                painter.drawPixmap(QPointF(rect.left(), rect.top()), pixmap)
            painter.setOpacity(1.0)

            # 碎片（46 片，寿命 0.5~1.1s，`_tick` 到点就移除）
            for piece in self.debris:
                painter.setOpacity(max(0.0, min(1.0, piece["life"])) * fade)
                painter.setBrush(QColor(255, 255, 255, 230))
                painter.setPen(Qt.NoPen)
                size = piece["size"]
                painter.drawRect(QRectF(piece["x"] + rect.left(), piece["y"],
                                        size, size * 0.6))
            painter.setOpacity(1.0)

        painter.restore()

        # ---- 第 1 层（顶）：整块碎玻璃 ----------------------------------
        # 破罐那 0.45s 叠一层 spider_web，放在 restore 之后：它不受 shake/fade
        # 影响 —— 罐子正在淡出，这一层仍要看得见，否则「敲碎」只有裂纹没有碎裂。
        if self._shatter_at is not None:
            age = time.monotonic() - self._shatter_at
            if age >= 0.45:
                self._shatter_at = None
            else:
                shatter = self._shatter_pixmap(jsize)
                if not shatter.isNull():
                    painter.setOpacity(max(0.0, 1.0 - age / 0.45))
                    painter.drawPixmap(QPointF(rect.left(), rect.top()), shatter)
                    painter.setOpacity(1.0)

        # 破罐瞬间的白闪：贴在展示区上（不是全屏），所以不受 shake/fade 影响
        if self.flash > 0.001:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, int(255 * self.flash)))
            painter.drawRoundedRect(rect, radius, radius)

        # 已部署：蜘蛛去桌面了，展示区空着。玻璃罐下线后这里没有瓶身可看，
        # 一块纯白圆角矩形会像是「没渲染出来」——补一句说明，并随 fade 淡入。
        if self.phase == "deployed" and fade < 0.995:
            self._paint_deployed_hint(painter, rect, fade)
        painter.end()

    def _paint_deployed_hint(self, painter: QPainter, rect: QRectF,
                             fade: float) -> None:
        """展示区空态文案（只在「已部署」且蜘蛛已淡出时出现）。"""
        alpha = max(0.0, min(1.0, 1.0 - fade))
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(max(12, int(min(19.0, rect.height() * 0.075))))
        painter.setFont(font)
        painter.setPen(QColor(150, 148, 140, int(220 * alpha)))
        painter.drawText(rect.adjusted(16.0, 0.0, -16.0, 0.0),
                         Qt.AlignCenter, "蜘蛛已经到桌面上了\n"
                                         "点右下角的「收回」，让它回来")

    def sizeHint(self) -> QSize:
        return QSize(1060, 430)


# ---------------------------------------------------------------- 面板 / 弹层

class SmoothScrollArea(QScrollArea):
    """轻量惯性滚动：只改变滚动条运动方式，不改变任何数据/事件逻辑。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scroll_anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_anim.setDuration(220)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)

    def wheelEvent(self, event) -> None:
        delta = event.pixelDelta().y()
        if not delta:
            delta = event.angleDelta().y()
        if not delta:
            super().wheelEvent(event)
            return

        bar = self.verticalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), bar.value() - int(delta)))
        if target == bar.value():
            event.accept()
            return

        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(bar.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.start()
        event.accept()


class SettingsSheet(QDialog):
    """设置弹层：第四轮之后只剩识别侧三项。"""

    changed = Signal(dict)

    def __init__(self, values: dict, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("sheet")
        self.setModal(True)
        self.setWindowTitle("设置")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(APP_QSS)
        self._values = dict(values)
        # 必须在第一次 `_slider_row()` 之前建好：`_slider_row` 会往里写
        self._sliders = {}
        # 无边框弹层的拖动锚点（用户 2026-10-16：设置界面拖不动 → 补拖动）
        self._drag = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(9)

        head = QHBoxLayout()
        title = QLabel("设置")
        title.setObjectName("sheetTitle")
        close = QPushButton()
        close.setObjectName("closeBtn")
        close.setFixedSize(30, 30)
        close.setCursor(Qt.PointingHandCursor)
        close.setAccessibleName("关闭设置")
        close.setToolTip("关闭设置")
        close.setIcon(_svg_icon(CLOSE_SVG, 16))
        close.setIconSize(QSize(16, 16))
        close.clicked.connect(self.reject)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(close)
        layout.addLayout(head)

        note = QLabel("改完即时写入 settings.json")
        note.setObjectName("sheetNote")
        layout.addWidget(note)

        # 识别引擎：源程序只打包了 RapidOCR（`ocr_engine.py` 的文档字符串里
        # 写明 PaddleOCR 因为非 ASCII 路径会直接崩，所以没引）。
        # ★ 2026-10-19：既然只有一档，就不再做「单选组」——一排只有一个亮按钮、
        #   另一个永远灰着的选项纯属噪音，整行删掉。要加第二个引擎时再恢复这里，
        #   并同步 `ocr_adapter._PROBES` 与 `ocr_registry._fallback_engines()`。

        # 最大识词（2026-10-18 起 1~48，见 `settings_store.MAX_WORDS_RANGE`：
        # 「八条腿」只是**同时**踩词的腿数，不再是本次能处理多少个词的上限）
        layout.addLayout(self._slider_row("最大识词", "max_words",
                                          MAX_WORDS_RANGE[0], MAX_WORDS_RANGE[1],
                                          int(self._values.get("max_words",
                                                               DEFAULTS["max_words"])),
                                          "{:d} 个"))
        # 最小置信度（原型 `min .5 max .99 step .01`，这里用百分数整数滑杆）
        layout.addLayout(self._slider_row("最小置信度", "min_conf",
                                          50, 99,
                                          int(round(float(self._values.get("min_conf", 0.6)) * 100)),
                                          "{:d}%"))

        foot = QHBoxLayout()
        reset = QPushButton("恢复默认")
        reset.setObjectName("segBtn")
        reset.clicked.connect(self._reset)
        done = QPushButton("完成")
        done.setObjectName("segBtn")
        done.clicked.connect(self.accept)
        foot.addWidget(reset)
        foot.addStretch(1)
        foot.addWidget(done)
        layout.addLayout(foot)

    def _slider_row(self, label: str, key: str, low: int, high: int,
                    value: int, fmt: str) -> QHBoxLayout:
        row = QHBoxLayout()
        text = QLabel(label)
        text.setObjectName("sheetLabel")
        text.setFixedWidth(78)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)
        slider.setMinimumWidth(150)
        out = QLabel(fmt.format(value))
        out.setObjectName("scaleOut")
        out.setFixedWidth(52)
        out.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(
            lambda v, k=key, o=out, f=fmt: self._slide(k, v, o, f))
        self._sliders[key] = slider
        row.addWidget(text)
        row.addWidget(slider, 1)
        row.addWidget(out)
        return row

    def _slide(self, key: str, raw: int, label, fmt: str) -> None:
        value = raw / 100.0 if key == "min_conf" else raw
        label.setText(fmt.format(raw))
        self._values[key] = value
        self.changed.emit({key: value})

    def _engine_clicked(self, index: int) -> None:
        # 保留：OCR 引擎单选组已随 PaddleOCR 一起去掉（见 `_build_sheet`），
        # 这里留着是为了将来加回第二个引擎时不用重新对接信号。
        button = self.engine_group.button(index)
        if button is None:
            return
        self._values["ocr_engine"] = "rapid" if button.text().startswith("Rapid") else "paddle"
        self.changed.emit({"ocr_engine": self._values["ocr_engine"]})

    def _reset(self) -> None:
        from settings_store import DEFAULTS
        self._values = dict(DEFAULTS)
        self._sliders["max_words"].setValue(int(DEFAULTS["max_words"]))
        self._sliders["min_conf"].setValue(int(round(DEFAULTS["min_conf"] * 100)))
        self.changed.emit(dict(self._values))

    def values(self) -> dict:
        return dict(self._values)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    # -- 用户 2026-10-16：设置界面「透明 + 拖不动」两连修 ------------------
    def paintEvent(self, event):                 # noqa: ARG002
        # ★ `WA_TranslucentBackground` 开着时，QSS 里 `#sheet{background:…}`
        #   不保证落到真实像素（用户实测整块是透明的）——这里自己把白底画死，
        #   圆角照旧，半透明只留给四个圆角外的像素。
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(228, 228, 223), 1))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                14, 14)
        painter.end()

    def mousePressEvent(self, event):
        # 滑杆/按钮自己消费点击，落不到这里；空白处和标题行都能拖。
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = None
        super().mouseReleaseEvent(event)


class Panel(QWidget):
    """标签与内容面板：白色实体表面、极浅中性边线与克制焦点色。

    64:36 之下面板净高只有 243px，内容要 386px —— 所以**内容自己滚、
    部署那一行钉在底部不动**，主按钮永远够得着。
    """

    def __init__(self, modes, stats_line: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = SmoothScrollArea(self)
        self.scroll.setObjectName("panelScroll")
        # ★ 关键：QAbstractScrollArea 的 minimumSizeHint 默认按内容算，会把
        #   面板撑到远超 36% 的设计高度（实测 354px vs 243px），让瓶身只剩 322。
        #   这里把最小高度归零 + Expanding，让 stretch 真正生效。
        self.scroll.setMinimumHeight(0)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollBar:vertical{width:6px;background:transparent;}"
            "QScrollBar::handle:vertical{background:rgba(26,26,26,.20);"
            "border-radius:3px;min-height:24px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")

        content = QWidget()
        # ★ scroll viewport 的 minimumSizeHint 由子控件累加而来（六行长矩形 +
        #   尺寸行 + 收藏条 + 状态行 ≈ 386px），会无视外层 scroll 的 setMinimumHeight(0)。
        #   把 content 的最小高度也归零，scroll 才能真正被 stretch 压到设计值。
        content.setMinimumHeight(0)
        # ★ 用户 2026-10-16「改成纯白不透明」：
        #   面板自己的画笔早就涂了纯白，但一直发灰 —— 灰的不是画笔，是
        #   **content 这层底板**：QSS 引擎 polish 时会把它的 autoFillBackground
        #   打开（setAutoFillBackground(False) 都压不住），于是它拿调色板的
        #   #F3F3F3 把面板整个盖掉。★ 另外：本文件顶上那份 QSS 字符串**从来没被
        #   setStyleSheet 应用过**（只有 dialogs.py 用它），所以改 QSS 在这里没用，
        #   必须改调色板。两层都涂纯白，谁盖谁都一样。
        self.scroll.viewport().setAutoFillBackground(False)
        pal = content.palette()
        pal.setColor(content.backgroundRole(), QColor(255, 255, 255))
        content.setPalette(pal)
        column = QVBoxLayout(content)
        column.setContentsMargins(26, 20, 26, 18)
        column.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("学习范围")
        title.setObjectName("panelHead")
        note = QLabel("只从这个词表里挑词；改完点「部署」写进设置")
        note.setObjectName("panelNote")
        head.addWidget(title)
        head.addWidget(note)
        head.addStretch(1)
        column.addLayout(head)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        modes_box = QVBoxLayout()
        modes_box.setSpacing(MODE_ROW_GAP)
        self._mode_rows = {}
        for entry in modes:
            row = ModeRow(entry["key"], entry["name"],
                          _fmt(entry["count"]) if not entry.get("na") else "无标签",
                          bool(entry.get("na")))
            row.setChecked(bool(entry.get("selected")))
            self.mode_group.addButton(row)
            modes_box.addWidget(row)
            self._mode_rows[entry["key"]] = row
        self.mode_group.buttonClicked.connect(self._mode_clicked)
        #: 六行一共 6×MODE_ROW_H + 5×MODE_ROW_GAP = 205px —— 面板净高不够时这就是要滚的原因
        self.modes_box = modes_box

        # ★ 用户 2026-10-16：玻璃罐从「窗口左边一大块」搬进面板，落在六档按钮的
        #   **右半边**；按钮相应缩到左半边。两边各占 1 份 stretch = 严格对半分。
        #   罐高**定死**成六行的高度，不跟着 stretch 走 —— 面板内容一旦超屏，
        #   可伸缩的罐子会被压到 minimumSizeHint(0)，直接消失。
        modes_area = QHBoxLayout()
        modes_area.setSpacing(28)
        modes_area.addLayout(modes_box, 1)
        self.jar = JarView(content)
        self.jar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.jar.setFixedHeight(len(modes) * MODE_ROW_H
                                + max(0, len(modes) - 1) * MODE_ROW_GAP)
        modes_area.addWidget(self.jar, 1, Qt.AlignTop)
        column.addLayout(modes_area)
        self.modes_area = modes_area

        # 桌宠大小 + 两个显示开关（窗口置顶 / 释义卡；「跟随鼠标」已按用户要求删除）
        controls = QHBoxLayout()
        controls.setSpacing(14)
        size_label = QLabel("桌宠大小")
        size_label.setObjectName("panelHead")
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(50, 220)
        self.scale_slider.setMinimumWidth(150)
        self.scale_out = QLabel("100%")
        self.scale_out.setObjectName("scaleOut")
        show_label = QLabel("显示")
        show_label.setObjectName("panelHead")
        self.checks = {}
        for key, text in (("always_on_top", "窗口置顶"),
                          ("show_meaning_card", "释义卡")):
            box = QCheckBox(text)
            box.setObjectName("check")
            box.setCursor(Qt.PointingHandCursor)
            self.checks[key] = box
        controls.addWidget(size_label)
        controls.addWidget(self.scale_slider, 1)
        controls.addWidget(self.scale_out)
        controls.addSpacing(10)
        controls.addWidget(show_label)
        for box in self.checks.values():
            controls.addWidget(box)
        column.addLayout(controls)
        self.controls_box = controls

        # 蜘蛛皮肤：四套共用一个 `settings["skin"]`，桌宠右键菜单里也有同一个入口。
        # 放在「桌宠大小」下面 —— 两者都是**外观**类设置，挨着更顺。
        skin_bar = QHBoxLayout()
        skin_bar.setSpacing(8)
        skin_title = QLabel("蜘蛛皮肤")
        skin_title.setObjectName("panelHead")
        skin_bar.addWidget(skin_title)
        self.skin_group = QButtonGroup(self)
        self.skin_group.setExclusive(True)
        self._skin_buttons = {}
        for skin_id, skin_name in skin_options():
            spec = SKIN_SPECS[skin_id]
            button = QPushButton(skin_name)
            button.setObjectName("segBtn")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIcon(_skin_swatch(spec.leg, spec.leg_outline))
            button.setIconSize(QSize(14, 14))
            self.skin_group.addButton(button)
            self._skin_buttons[skin_id] = button
            skin_bar.addWidget(button)
        skin_bar.addStretch(1)
        column.addLayout(skin_bar)
        self.skin_bar = skin_bar
        self.skin_group.buttonClicked.connect(self._skin_clicked)

        # 我的收藏
        words_bar = QHBoxLayout()
        words_bar.setSpacing(12)
        words_title = QLabel("我的收藏")
        words_title.setObjectName("sectionTitle")
        self.words_count = QLabel("0 词")
        self.words_count.setObjectName("wordsCount")
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        for index, text in enumerate(("全部", "待复习")):
            button = QPushButton(text)
            button.setObjectName("segBtn")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.filter_group.addButton(button, index)
            words_bar.addWidget(button)
        words_bar.insertWidget(0, words_title)
        words_bar.insertWidget(1, self.words_count)
        words_bar.addStretch(1)
        column.addLayout(words_bar)
        self.filter_group.idClicked.connect(self.filter_changed)

        self.words_scroll = QScrollArea()
        self.words_scroll.setObjectName("panelScroll")
        self.words_scroll.setFixedHeight(34)
        self.words_scroll.setWidgetResizable(True)
        self.words_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.words_scroll.setStyleSheet(
            "QScrollBar:horizontal{height:0;}QScrollBar::handle:horizontal{width:0;}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}")
        self.words_strip = QWidget()
        strip = QHBoxLayout(self.words_strip)
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(8)
        self.words_scroll.setWidget(self.words_strip)
        self.words_scroll.viewport().setAutoFillBackground(False)  # 同上，别让 #F3F3F3 盖住面板
        self.words_empty = QLabel()
        self.words_empty.setObjectName("wordEmpty")
        self.words_empty.setVisible(False)
        column.addWidget(self.words_scroll)
        column.addWidget(self.words_empty)

        # 数据来源状态条：富文本由 `LauncherWindow._stats_line()` 直接拼好
        # （带 ● 颜色点），这里不再二次包装。
        self.data_line = QLabel(stats_line)
        self.data_line.setObjectName("dataLine")
        self.data_line.setTextFormat(Qt.RichText)
        self.data_line.setTextInteractionFlags(Qt.NoTextInteraction)
        column.addWidget(self.data_line)

        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)

        # 取消装饰性渐隐：白色内容面本身已经足够清晰，避免滚动区域出现额外渐变。
        self.fade_strip = QFrame(self.scroll)
        self.fade_strip.setObjectName("scrollFade")
        self.fade_strip.setGeometry(0, 0, 10, 1)
        self.fade_strip.hide()

        foot = QWidget(self)
        foot.setObjectName("footRow")
        # 钉底行不参与 stretch：它的高度由内容决定（部署按钮 64px + 边距），
        # 上面 scroll 才是被 stretch 控制的那个。
        foot.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        foot_layout = QHBoxLayout(foot)
        foot_layout.setContentsMargins(26, 14, 26, 18)
        foot_layout.setSpacing(20)
        self.first_use = QLabel(
            "首次使用：点它的<u>头</u>框选识词，按住<u>肚子</u>拖动，滚轮缩放，右键菜单")
        self.first_use.setObjectName("firstUse")
        self.first_use.setWordWrap(True)
        self.first_use.setMaximumWidth(460)
        self.deploy = QPushButton("部 署")
        self.deploy.setObjectName("deployBtn")
        self.deploy.setCursor(Qt.PointingHandCursor)
        self.deploy.setProperty("mode", "deploy")
        foot_layout.addWidget(self.first_use)
        foot_layout.addStretch(1)
        foot_layout.addWidget(self.deploy)
        root.addWidget(foot, 0)
        self.foot = foot

        self.scale_slider.valueChanged.connect(
            lambda v: self.scale_out.setText("%d%%" % v))

    # ------------------------------------------------ 细节
    def resizeEvent(self, event):                # noqa: ARG002
        self.fade_strip.setGeometry(0, self.scroll.height() - 24,
                                    self.scroll.width(), 24)

    def set_mode(self, key: str) -> None:
        row = self._mode_rows.get(key)
        if row is not None:
            self.mode_group.setExclusive(False)
            for other in self._mode_rows.values():
                other.setChecked(other is row)
            self.mode_group.setExclusive(True)

    def current_mode(self) -> str:
        for key, row in self._mode_rows.items():
            if row.isChecked():
                return key
        return str(DEFAULTS["selected_mode"])

    def _mode_clicked(self, button) -> None:
        self.mode_selected(button.key)

    def mode_selected(self, key: str) -> None:
        """子类/外部挂信号的钩子（LauncherWindow 覆盖它）。"""

    # ------------------------------------------------ 皮肤
    def current_skin(self) -> str:
        for skin_id, button in self._skin_buttons.items():
            if button.isChecked():
                return skin_id
        return DEFAULT_SKIN

    def set_skin(self, skin_id: str) -> None:
        button = self._skin_buttons.get(str(skin_id).strip().lower())
        if button is None:
            return
        self.skin_group.setExclusive(False)
        for other in self._skin_buttons.values():
            other.setChecked(other is button)
        self.skin_group.setExclusive(True)

    def _skin_clicked(self, button) -> None:
        for skin_id, candidate in self._skin_buttons.items():
            if candidate is button:
                self.skin_selected(skin_id)
                return

    def skin_selected(self, skin_id: str) -> None:
        """外部覆盖：Panel 不自己写设置，交给 LauncherWindow 统一处理。"""

    def filter_changed(self, index: int) -> None:
        """外部覆盖：0=全部、1=待复习。"""

    def set_filter(self, only_due: bool) -> None:
        self.filter_group.button(1 if only_due else 0).setChecked(True)

    def set_word_cards(self, cards, empty_text: str) -> None:
        while self.words_strip.layout().count():
            item = self.words_strip.layout().takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not cards:
            self.words_scroll.setVisible(False)
            self.words_empty.setVisible(True)
            self.words_empty.setText(empty_text)
            return
        self.words_scroll.setVisible(True)
        self.words_empty.setVisible(False)
        for chip in cards:
            chip.clicked.connect(lambda _=False, c=chip: self.word_clicked(c))
            self.words_strip.layout().addWidget(chip)

    def word_clicked(self, chip) -> None:
        """外部覆盖：点一下记一次复习。"""

    def set_deploy_mode(self, mode: str, text: str, enabled: bool) -> None:
        self.deploy.setProperty("mode", mode)
        self.deploy.setText(text)
        self.deploy.setEnabled(enabled)
        self.deploy.style().unpolish(self.deploy)
        self.deploy.style().polish(self.deploy)

    def paintEvent(self, event):                 # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = _bottom_rounded(rect, RADIUS)
        painter.setPen(QPen(QColor(228, 228, 223), 1))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(241, 241, 237), 1))
        painter.drawLine(QPointF(rect.left() + RADIUS, rect.top() + 0.5),
                         QPointF(rect.right() - RADIUS, rect.top() + 0.5))
        painter.end()


def _bottom_rounded(rect: QRectF, radius: float) -> QPainterPath:
    """只圆下面两个角的矩形路径（上边是瓶盖/标签的接缝，必须直角）。"""
    return _corners(rect, radius, top=False, bottom=True)


# ---------------------------------------------------------------- 启动台


class ActivityGrid(QWidget):
    """Small real-data learning heatmap used by the desktop shell."""

    def __init__(self, book, parent=None):
        super().__init__(parent)
        self.book = book
        self.setObjectName("activityCard")
        self.setMinimumHeight(184)
        # 2026-10-17 性能修正：以前每次重绘都遍历全部事件重建 counts/reviews，
        # 再对 371 格逐格 strftime+localtime。事件列表只追加（wordbook 从不删），
        # 所以按「事件条数」做缓存键；日期串按「今天」缓存，跨天才重算。
        self._cache_key = None
        self._day_key = None
        self._grid_days: list = []
        self._month_at: dict = {}

    def _data_maps(self) -> tuple:
        study = getattr(self.book, "study_events", [])
        review = getattr(self.book, "review_events", [])
        key = (len(study), len(review))
        if key != self._cache_key:
            counts = {}
            for event in study:
                date = str(event.get("date", ""))
                counts[date] = counts.get(date, 0) + 1
            self._counts = counts
            self._reviews = {e.get("date") for e in review}
            self._cache_key = key
        return self._counts, self._reviews

    def _day_names(self, first: float, total: int) -> None:
        today_key = time.strftime("%Y-%m-%d")
        if today_key != self._day_key:
            self._grid_days = [time.strftime("%Y-%m-%d", time.localtime(first + i * DAY))
                               for i in range(total)]
            self._month_at = {}
            for index in range(total):
                stamp = first + index * DAY
                struct = time.localtime(stamp)
                if struct.tm_mday == 1:
                    self._month_at[index] = time.strftime("%m月", struct)
            self._day_key = today_key

    def paintEvent(self, event):  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        painter.setPen(QPen(QColor(LINE), 1))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(INK)
        painter.setFont(QFont("Microsoft YaHei UI", 11, QFont.DemiBold))
        painter.drawText(QRectF(16, 12, 220, 22), Qt.AlignLeft, "学习活动")
        painter.setPen(FAINT)
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.drawText(QRectF(rect.right() - 160, 12, 140, 22),
                         Qt.AlignRight, "日   周   月   年")
        counts, reviews = self._data_maps()
        today = time.time()
        columns, rows = 53, 7
        cell = max(10.0, min(15.0, (self.width() - 42) / columns - 3))
        gap = 3.0
        start_x, start_y = 18.0, 46.0
        first = today - (columns * rows - 1) * DAY
        total = columns * rows
        self._day_names(first, total)
        scanned = QColor("#B9DCC1")
        reviewed = QColor("#4F765F")
        idle = QColor("#EEF0EE")
        no_pen = Qt.PenStyle.NoPen
        small_font = QFont("Microsoft YaHei UI", 8)
        painter.setFont(small_font)
        for index, day in enumerate(self._grid_days):
            color = reviewed if day in reviews else (
                scanned if counts.get(day, 0) > 0 else idle)
            x = start_x + (index // rows) * (cell + gap)
            y = start_y + (index % rows) * (cell + gap)
            painter.setPen(no_pen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, y, cell, cell), 3, 3)
            label = self._month_at.get(index)
            if label:
                painter.setPen(FAINT)
                painter.setFont(small_font)
                painter.drawText(QRectF(x, start_y + rows * (cell + gap) + 5, 42, 16),
                                 Qt.AlignLeft, label)
        painter.setPen(FAINT)
        painter.setFont(small_font)
        painter.drawText(QRectF(rect.right() - 165, rect.bottom() - 20, 150, 16),
                         Qt.AlignRight, "浅绿：扫描　深绿：已复习")
        painter.end()


class LauncherWindow(QWidget):
    """启动台：先开它，点「部署」才建桌宠，点「收回」删掉桌宠。"""

    deploy_requested = Signal(dict)
    recall_requested = Signal()
    quit_requested = Signal()
    #: 皮肤变了。桌宠已经部署时，main.py 接这个信号**实时**换皮，
    #: 不用等用户再点一次「部署」。
    skin_changed = Signal(str)
    #: 桌宠大小变了（1.0 = 100%）。同理，已部署的桌宠接这个信号**实时**改尺寸。
    #: 2026-10-18：以前只写 settings，已部署的桌宠要等下次部署才变 ——
    #: 用户看到的就是「调大小对蜘蛛没作用」。
    scale_changed = Signal(float)

    def __init__(self, lexicon, book, settings, log=None, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(APP_QSS)
        self.lexicon = lexicon
        self.book = book
        self.settings = settings
        self.log = log or (lambda message: None)
        self.phase = "idle"
        self.sheet = None
        self.only_due = False
        #: ★ 无头模式（2026-10-18）：QML 启动台把本窗口当**隐藏控制器**用时置 True。
        #: 此时任何 `show()` 都必须被忽略 —— 否则旧 Widgets 界面会露出来（重复 UI），
        #: 而且 QML 的 `JarItem.paint` 正在 `render()` 本窗口里那个 JarView，
        #: 一个 widget 同时被 Qt 自己的 backing store 和 render() 画 → access
        #: violation（实测 exit 139，见 `tools/deploy_cycle_probe.py`）。
        self.headless = False
        #: 无头模式要「把启动台带到前台」时的替代动作（由 QML 桥接注入）。
        self.present_callback = None

        self.setWindowTitle("词蛛LEXARA · 启动台")
        # 用户 2026-10-16 深夜：整体缩为原来的 2/3（1200×720 → 800×480），
        # 最小尺寸也同步缩（820×560 必须跟着降，否则比默认值还大、窗口缩不下去）。
        self.resize(1180, 760)
        self.setMinimumSize(940, 640)

        # 布局（用户 2026-10-16 第二次拍板）：**窗口里只剩一张大卡片**。
        # 原来「左边玻璃罐 + 右边卡片」的横向两块，现在把玻璃罐搬进面板内部
        # （六档按钮的右半边，见 `Panel.__init__`），于是卡片直接吃满可用区域。
        # 卡片本身仍是「TitleBar 在上 + Panel 在下」拼成的圆角矩形
        # （上圆角来自 TitleBar、下圆角来自 Panel，中间 0 间距接成一条缝）。
        self._margin = 10

        # ★ 这里**不能用布局**：布局会把子控件的 fixedSize 当成窗口的最小尺寸，
        #   最大化之后再还原，窗口就被卡在最大化时的高度上回不来
        #   （实测：最大化 1707×1019 → 还原只剩 1200×**1019**，高度回不去）。
        #   卡片的落位完全交给下面的 resizeEvent 用 setGeometry 摆。
        self._margin = 10

        import lexicon as L
        self.title_bar = TitleBar("词蛛LEXARA", "启动台 · %s" % L.MODE_DISPLAY.get(
            settings.get("selected_mode"), "六级"), self)

        # 旧面板仍保留为真实设置/部署状态源；新的 shell 只负责呈现布局。
        self.right = QWidget(self)
        right_layout = QVBoxLayout(self.right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.title_bar, 0)

        self.panel = Panel(self._mode_entries(), self._stats_line(), self.right)
        right_layout.addWidget(self.panel, 1)

        # 罐子现在住在面板里，这里只留一个别名 —— 下面所有 `self.jar.xxx`
        # （换皮、部署/收回那串动画）一行都不用改。
        self.jar = self.panel.jar

        self.panel.mode_selected = self._on_mode_selected
        self.panel.filter_changed = self._on_filter_changed
        self.panel.word_clicked = self._on_word_clicked
        self.panel.skin_selected = self._on_skin_selected
        self.panel.deploy.clicked.connect(self.on_deploy_button)
        self.title_bar.gear.clicked.connect(self.open_sheet)
        self.title_bar.close_clicked.connect(self.quit_requested.emit)
        self.panel.scale_slider.setValue(int(settings.get("pet_scale") * 100))
        self.panel.scale_slider.valueChanged.connect(self._on_scale_changed)
        for key, box in self.panel.checks.items():
            box.setChecked(bool(settings.get(key)))
            box.toggled.connect(lambda v, k=key: self._on_toggle(k, v))
        self.panel.set_mode(settings.get("selected_mode"))
        # 罐子里那只蜘蛛也要跟着皮肤走 —— 用户在启动台就能直接看到效果，
        # 不用先部署再右键改。这里不改 `settings`（只是把已存的值读出来用）。
        self.panel.set_skin(settings.get("skin"))
        self.jar.painter.set_skin(self.panel.current_skin())
        self.jar.spider.body_scale = self.jar.painter.skin_spec().body_scale
        self._refresh_words()

        self._deploy_hold = False

        self._build_desktop_shell()

    def _build_desktop_shell(self) -> None:
        """Competition desktop shell: sidebar + companion + activity + AI bar.

        Existing Panel remains the source of truth for settings and deployment, so this
        presentation layer cannot change OCR, wordbook, or spider behavior.
        """
        self.right.hide()
        shell = QHBoxLayout(self)
        shell.setContentsMargins(18, 18, 18, 18)
        shell.setSpacing(16)
        sidebar = QFrame(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(252)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 20, 18, 18)
        side.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("logo")
        logo.setToolTip("词蛛 · AI 语言学习 Agent")
        from wordbook import resource_path
        # 侧栏是浅色底 → 用墨黑那版；透明底的象牙白版专供 QML 的墨绿顶栏
        logo_pix = QPixmap(resource_path("assets", "ui", "lexara_logo_ink.png"))
        if not logo_pix.isNull():
            logo.setPixmap(logo_pix.scaledToWidth(142, Qt.SmoothTransformation))
        else:
            logo.setText("LEXARA")
        side.addWidget(logo)
        sub = QLabel("具身化语言学习")
        sub.setObjectName("sideSub")
        side.addWidget(sub)
        review = QFrame()
        review.setObjectName("reviewCard")
        rv = QVBoxLayout(review)
        rv.setContentsMargins(13, 12, 13, 12)
        rt = QLabel("今日复习")
        rt.setObjectName("sideTitle")
        rv.addWidget(rt)
        self._review_due = QLabel("剩余 0 未复习")
        self._review_total = QLabel("总共 0 词")
        for label in (self._review_due, self._review_total):
            label.setObjectName("sideMetric")
            rv.addWidget(label)
        side.addSpacing(12)
        side.addWidget(review)
        fav = QPushButton("▣   收藏夹")
        fav.setObjectName("sideAction")
        fav.clicked.connect(self.open_wordbook)
        side.addWidget(fav)
        review_action = QPushButton("▶   背单词")
        review_action.setObjectName("sideAction")
        review_action.clicked.connect(self.start_review)
        side.addWidget(review_action)
        side.addStretch(1)
        skin = QPushButton("◈   换皮肤")
        skin.setObjectName("sideAction")
        skin_pix = QPixmap(resource_path("assets", "ui", "icon_skin.png"))
        if not skin_pix.isNull():
            skin.setIcon(QIcon(skin_pix))
            skin.setIconSize(QSize(18, 18))
            skin.setText("换皮肤")
        skin.clicked.connect(self.open_sheet)
        settings = QPushButton("⚙   设置")
        settings.setObjectName("sideAction")
        settings_pix = QPixmap(resource_path("assets", "ui", "icon_settings.png"))
        if not settings_pix.isNull():
            settings.setIcon(QIcon(settings_pix))
            settings.setIconSize(QSize(18, 18))
            settings.setText("设置")
        settings.clicked.connect(self.open_sheet)
        side.addWidget(skin)
        side.addWidget(settings)
        shell.addWidget(sidebar)

        main = QWidget(self)
        main.setObjectName("mainContent")
        main.setStyleSheet("background:#FFFFFF; border:1px solid #E5E5E0; border-radius:18px;")
        column = QVBoxLayout(main)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(14)
        header = QHBoxLayout()
        brand = QLabel("桌面学习空间")
        brand.setObjectName("pageTitle")
        header.addWidget(brand)
        header.addStretch(1)
        self._status = QLabel("待命 · 词表已就绪")
        self._status.setObjectName("pageStatus")
        header.addWidget(self._status)
        column.addLayout(header)

        hero = QFrame()
        hero.setObjectName("heroCard")
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(12, 8, 12, 8)
        hero_title = QLabel("蜘蛛桌宠")
        hero_title.setObjectName("cardTitle")
        hv.addWidget(hero_title)
        self.jar.show()
        self.jar.setMinimumHeight(300)
        hv.addWidget(self.jar, 1)
        column.addWidget(hero, 1)

        self.activity = ActivityGrid(self.book, main)
        column.addWidget(self.activity, 0)

        bottom = QHBoxLayout()
        input_card = QFrame()
        input_card.setObjectName("inputCard")
        iv = QHBoxLayout(input_card)
        iv.setContentsMargins(10, 8, 10, 8)
        iv.setSpacing(8)
        engine = QComboBox()
        engine.setObjectName("compactControl")
        engine.addItem("RapidOCR")
        engine.setToolTip("识别引擎")
        api = QPushButton("API")
        api.setObjectName("compactControl")
        api.clicked.connect(self.open_sheet)
        self.ai_input = QLineEdit()
        self.ai_input.setPlaceholderText("输入一句英文，让 AI 帮你挑出值得学习的词…")
        self.ai_input.setObjectName("aiInput")
        send = QPushButton("发送")
        send.setObjectName("sendButton")
        send.clicked.connect(self._shell_send)
        iv.addWidget(engine)
        iv.addWidget(api)
        iv.addWidget(self.ai_input, 1)
        iv.addWidget(send)
        bottom.addWidget(input_card, 1)
        deploy = QPushButton("部 署")
        deploy.setObjectName("shellDeploy")
        deploy.clicked.connect(self.on_deploy_button)
        self.shell_deploy = deploy
        bottom.addWidget(deploy, 0)
        column.addLayout(bottom)
        shell.addWidget(main, 1)
        self._shell_root = shell
        self._refresh_shell_stats()

    def _shell_send(self) -> None:
        """Keep the AI bar honest: text entry is a visual shell affordance.

        Real OCR remains the existing screen capture flow on the deployed spider.
        """
        text = self.ai_input.text().strip() if hasattr(self, "ai_input") else ""
        self._status.setText("已收到输入 · 请用蜘蛛头部框选屏幕" if text else
                             "请先输入英文或用蜘蛛头部框选")

    def _refresh_shell_stats(self) -> None:
        stats = self.book.stats()
        self._review_due.setText("剩余 %d 未复习" % stats.get("due", 0))
        self._review_total.setText("总共 %d 词" % stats.get("total", 0))
        if hasattr(self, "activity"):
            self.activity.update()

    # ------------------------------------------------ 数据装配
    def _mode_entries(self) -> list:
        """六档学习范围：键必须能在 `lexicon.MODE_LABELS` 里查到，
        词数从 `Lexicon.status()` 现取 —— 不在界面上写死任何数字。"""
        import lexicon as L
        status = self.lexicon.status()
        counts = (status.get("exam") or {}).get("counts") or {}
        industry = status.get("industry") or {}
        selected = self.settings.get("selected_mode")
        entries = []
        for key in MODE_KEYS:
            if key == "industry":
                count = int(industry.get("entryCount") or 0)
                na = not bool(industry.get("available"))
            else:
                count = int(counts.get(key) or 0)
                na = count == 0
            entries.append({"key": key, "name": L.MODE_DISPLAY.get(key, key),
                            "count": count, "na": na,
                            "selected": key == selected})
        return entries

    def _stats_line(self) -> str:
        status = self.lexicon.status()
        exam = status.get("exam") or {}
        industry = status.get("industry") or {}
        ok = bool(status.get("available")) and bool(exam.get("available"))
        color = GREEN if ok else WARN
        entries = int(status.get("entries") or 0)
        tags = sum((exam.get("counts") or {}).values()) if exam.get("available") else 0
        text = ("<b>词表</b> ecdict {entries:,} 条 · 考纲标签 {tags:,} 次 · "
                "行业词 {ind:,} 条").format(entries=entries, tags=tags,
                                            ind=int(industry.get("entryCount") or 0))
        return ("<span style='color:%s'>●</span> %s"
                % (color.name(), text))

    # ------------------------------------------------ 状态
    @property
    def payload(self) -> dict:
        """部署时发给桌宠的那一份设置（`deploy_requested` 的载体）。

        ★ 2026-10-18 22:45：`skin` / `pet_scale` 改成读 **settings**，不再读隐藏
          面板（`self.panel`）。QML 启动台根本不点那排旧控件，改皮肤 /
          拖大小都只写 settings —— 读面板就会拿到上一次在旧界面选的值，
          表现就是「切换皮肤后部署仍是原皮肤」「调了大小部署出来没变」。
          这两个键在启动台与桌宠之间本来就是共享的，settings 才是唯一真相
          （桌宠右键换皮也写同一个键，读面板同样会把它覆盖回去）。
        """
        values = self.settings.as_dict()
        values["selected_mode"] = self.panel.current_mode()
        # 滑杆那条路有 300ms 去抖：拖动完立刻点部署时 settings 还没落盘，
        # 用**待写值**顶上，避免「最后一格拖动丢了」。
        pending = getattr(self, "_scale_pending", None)
        if pending is not None:
            values["pet_scale"] = pending / 100.0
        else:
            values["pet_scale"] = float(values.get("pet_scale") or 1.0)
        values["skin"] = str(values.get("skin") or self.panel.current_skin())
        for key, box in self.panel.checks.items():
            values[key] = bool(box.isChecked())
        return values

    def _write_settings(self, changed: dict) -> None:
        self.settings.update(changed)

    def _on_skin_selected(self, skin_id: str) -> None:
        """启动台换皮肤：写设置 → 刷新罐子预览 → 通知已部署的桌宠。"""
        self._write_settings({"skin": skin_id})
        # 隐藏面板那排旧按钮也要跟着走：`payload` / 托盘 / 老界面都读它。
        # `Panel.set_skin()` 只改选中态、不发 `skin_selected`，不会递归回来。
        try:
            self.panel.set_skin(skin_id)
        except (AttributeError, ValueError):
            pass
        # 罐子里那只：只改渲染层，不重建 Spider，动画不会跳。
        self.jar.painter.set_skin(skin_id)
        # 罐内蜘蛛的命中判定也要跟着放大（与桌宠同一套 `_in_thorax`）。
        try:
            self.jar.spider.body_scale = self.jar.painter.skin_spec().body_scale
        except (AttributeError, ValueError):
            pass
        self.jar.update()
        self.log("[launcher] 皮肤 → %s" % skin_id)
        self.skin_changed.emit(skin_id)

    def _on_mode_selected(self, key: str) -> None:
        self._write_settings({"selected_mode": key})
        import lexicon as L
        self.title_bar.subtitle.setText("启动台 · %s" % L.MODE_DISPLAY.get(key, key))

    def _on_filter_changed(self, index: int) -> None:
        self.only_due = index == 1
        self._refresh_words()

    def _on_scale_changed(self, value: int) -> None:
        """桌宠尺寸滑杆：拖动中只记意图，停手 300ms 后才落盘一次。

        `settings.update()` 每次调用都写一遍磁盘，而 QSlider 拖动时
        `valueChanged` 是**逐像素**发的 —— 一次拖到底 = 几十次同步写盘。
        QML 侧 `setPetScalePct` 走的也是这个滑杆（`setValue` 会发
        `valueChanged`），所以那半边一并被去抖覆盖。
        """
        self._scale_pending = value
        if not hasattr(self, "_scale_debounce"):
            self._scale_debounce = QTimer(self, interval=300)
            self._scale_debounce.setSingleShot(True)
            self._scale_debounce.timeout.connect(self._flush_scale)
        self._scale_debounce.start()

    def set_pet_scale_pct(self, value: int) -> None:
        """桌宠大小的**即时**写入路径（给 QML / 桥接用）。

        为什么和滑杆那条路分开：拖动时 `valueChanged` 是逐像素发的，
        `_on_scale_changed` 做 300ms 去抖是为了不把磁盘写成筛子；
        但 QML 面板是一次性赋值，**必须马上落盘**，否则「刚改完立刻读
        settings」会读到旧值（`tools/qml_bridge_probe.py` 就是在查这件事）。
        这里先屏蔽信号再 setValue，就不会触发去抖分支，也不会丢 payload 同步。
        """
        value = max(50, min(150, int(value)))
        slider = self.panel.scale_slider
        was_blocked = slider.blockSignals(True)
        try:
            slider.setValue(value)
        finally:
            slider.blockSignals(was_blocked)
        self._write_settings({"pet_scale": value / 100.0})
        # 已部署的桌宠实时跟着变（`main.py` 接这个信号调 `pet.set_scale()`）。
        # 这里屏蔽了滑杆信号，所以不会额外触发 `_flush_scale` 再发一次。
        self.scale_changed.emit(value / 100.0)

    def _flush_scale(self) -> None:
        value = getattr(self, "_scale_pending", None)
        if value is not None:
            self._scale_pending = None
            self._write_settings({"pet_scale": value / 100.0})
            self.scale_changed.emit(value / 100.0)

    def _on_toggle(self, key: str, value: bool) -> None:
        self._write_settings({key: bool(value)})

    def _on_word_clicked(self, chip) -> None:
        """点一下记一次复习：`Wordbook.grade(word, correct=True)`。"""
        try:
            self.book.grade(chip._word, True)
        except Exception as error:             # noqa: BLE001
            self.log("[wordbook] 复习失败: %r" % (error,))
        self._refresh_words()

    def _open_wordbook_dialog(self, review: bool, category: str = "") -> None:
        """词库弹窗的公共路径（收藏夹 / 背单词只差 `start_review()` 一行）。"""
        from dialogs import WordbookDialog
        dialog = WordbookDialog(None, self.book, category=category,
                                lexicon=self.lexicon)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.show()
        dialog.raise_()
        if review:
            dialog.start_review()
        self._wordbook_dialog = dialog

    def open_wordbook(self, category: str = "") -> None:
        """打开收藏夹。``category`` 非空时按考纲分类过滤（任务书 §2.2）。"""
        self._open_wordbook_dialog(review=False, category=category)

    def start_review(self) -> None:
        self._open_wordbook_dialog(review=True)

    def _refresh_words(self) -> None:
        stats = self.book.stats()
        self.panel.words_count.setText(
            "%d 词 · 今日待复习 %d · 今日学习 %d" %
            (stats["total"], stats["due"], stats.get("today", 0)))
        cards = []
        now = time.time()
        last_stage = len(STAGES) - 1
        for item in self.book.review_queue():
            # 三种徽标（原型 `today / later / done`）：
            # 到期 → 今天；走完最后一档且还没到期 → 已掌握；其余 → 约 N 天后。
            # （曾经写成「`due_days<=0` 两个分支 + `mastered is False`」，
            #   条件重复 yet 互相矛盾，结果已掌握的词永远显示「今天」。）
            due_days = math.ceil((item.due_at - now) / DAY) if item.due_at else 0
            if item.due_at and due_days > 0 and item.stage >= last_stage:
                tone, text = "done", "已掌握"
            elif due_days <= 0:
                tone, text = "today", "今天"
            else:
                tone, text = "later", "约 %d 天后" % due_days
            if self.only_due and tone != "today":
                continue
            cards.append(WordChip({"word": item.word, "meaning": item.meaning},
                                  text, tone, max(0, item.stage)))
        self.panel.set_word_cards(
            cards[:12], "这一轮没有要复习的词<br><b>到日子蜘蛛会自己跳到前台提醒</b>")
        self.panel.data_line.setText(self._stats_line())
        if hasattr(self, "_review_due"):
            self._refresh_shell_stats()

    # ------------------------------------------------ 部署 / 收回
    def _set_deploy_buttons(self, mode: str, text: str, enabled: bool) -> None:
        """部署按钮的「一处真相」。

        旧代码在四个阶段各写两遍（panel 的 `set_deploy_mode` + shell 的
        `setText/setEnabled`），加一个新状态要改四处 —— 收敛成这一个 helper。
        """
        self.panel.set_deploy_mode(mode, text, enabled)
        deploy = getattr(self, "shell_deploy", None)
        if deploy is not None:
            deploy.setText(text)
            deploy.setEnabled(enabled)

    def on_deploy_button(self) -> None:
        if self.phase == "idle":
            self.begin_deploy()
        elif self.phase == "deployed":
            self.begin_recall()

    # ------------------------------------------------ 可见性
    def show(self) -> None:                      # noqa: D401
        """无头模式下 `show()` 一律是空操作。

        这是 §4「收回时出现重复 UI 并闪退」的**根因修复**（2026-10-18）：
        `begin_recall()` 以前会 `self.show()` 把启动台露出来，而 QML 模式下
        本窗口只是一个隐藏控制器 —— show 出来的结果就是第二个启动台界面；
        同时 JarView 变成可见 widget，QML 的 `JarItem.paint` 还在 `render()`
        它，两个绘制路径撞在一起直接段错误（探针实测 exit 139）。
        """
        if self.headless:
            self.log("[launcher] headless：忽略 show()（前台是 QML 启动台）")
            return
        super().show()

    def _present(self) -> None:
        """把启动台带到用户面前（无头模式下交给 QML 桥接）。"""
        if self.headless:
            callback = self.present_callback
            if callback is not None:
                callback()
            return
        self.show()
        self.raise_()
        self.activateWindow()

    def begin_deploy(self) -> None:
        if self.phase != "idle":
            return                              # 防重复点击（不依赖按钮禁用）
        self.close_sheet()
        self.phase = "deploying"
        self.jar.set_phase("deploying")
        self._set_deploy_buttons("deploy", "部署中…", False)
        self.title_bar.set_status("写入设置 · 破罐释放", WARN)
        self._write_settings(self.payload)
        # ★ 每个 singleShot 都带 self 作 context object（2026-10-17）：
        #   不带的话，用户在 740ms 动画半途关掉启动台（C++ 对象已析构），
        #   这些回调会打在死人对象上抛「C++ object already deleted」。
        #   带 context 的定时器在接收者销毁时自动取消。毫秒数与原型一致。
        QTimer.singleShot(0, self, lambda: self.jar.crack_on(0))
        QTimer.singleShot(180, self, lambda: (self.jar.crack_on(1), self.jar.start_shake(False)))
        QTimer.singleShot(420, self, lambda: (self.jar.crack_on(2), self.jar.start_shake(True),
                                              self.jar.spawn_debris()))
        QTimer.singleShot(620, self, lambda: (self.jar.burst_out(), self.jar.flash_now()))
        QTimer.singleShot(740, self, self._deployed)

    def _deployed(self) -> None:
        if self.phase != "deploying":
            return
        self.phase = "deployed"
        self.title_bar.set_status("已部署 · 蜘蛛在桌面上", GREEN)
        self._set_deploy_buttons("recall", "收 回", True)
        self.jar.set_phase("deployed")
        self.log("[launcher] 部署 → %s" % self.payload)
        self.deploy_requested.emit(self.payload)
        # 部署后**不再自动隐藏启动台**（旧版 300ms 后 hide，导致用户找不到「收回」）。
        # 启动台留着、按钮变成「收回」，随时能点回来；桌宠是独立置顶窗，浮在它上面。
        if not self.headless:
            self.raise_()

    def begin_recall(self) -> None:
        if self.phase != "deployed":
            return
        self.phase = "recalling"
        self.jar.set_phase("recalling")
        self._set_deploy_buttons("recall", "收回中…", False)
        self.title_bar.set_status("收回 · 蜘蛛回罐", WARN)
        self._present()
        self.jar.flash_now()
        QTimer.singleShot(0, self, self.recall_requested.emit)    # 桌宠在这里被删掉
        QTimer.singleShot(120, self, self.jar.begin_fall)
        QTimer.singleShot(250, self, lambda: self.jar.crack_heal_to(2))
        QTimer.singleShot(330, self, lambda: self.jar.crack_heal_to(1))
        QTimer.singleShot(400, self, lambda: self.jar.crack_heal_to(0))
        QTimer.singleShot(620, self, lambda: self.jar.reset())
        QTimer.singleShot(680, self, self._recalled)

    def _recalled(self) -> None:
        self.phase = "idle"
        self.jar.set_phase("idle")
        self._set_deploy_buttons("deploy", "部 署", True)
        self.title_bar.set_status("待命 · 词表已就绪", GREEN)

    def recall_from_pet(self) -> None:
        """桌宠那边点「回到启动台」：先露出来，再走同一条收回时间轴。"""
        if self.phase == "deployed":
            self.begin_recall()
        else:
            self._present()

    # ------------------------------------------------ 设置弹层
    def open_sheet(self) -> None:
        if self.sheet is not None:
            self.sheet.raise_()
            return
        self.sheet = SettingsSheet(self.payload, self)
        self.sheet.changed.connect(self._write_settings)
        self.title_bar.gear.setOpenVisual(True)
        self.sheet.finished.connect(self._sheet_closed)
        self.sheet.show()
        self.sheet.raise_()

    def _sheet_closed(self, _result=0) -> None:
        self.title_bar.gear.setOpenVisual(False)
        self.sheet = None

    def close_sheet(self) -> None:
        if self.sheet is not None:
            self.sheet.reject()

    # ------------------------------------------------ 事件

    def paintEvent(self, event) -> None:             # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(225, 225, 220), 1))
        painter.setBrush(QColor(243, 241, 215))
        painter.drawRoundedRect(rect, 16, 16)
        painter.end()

    def resizeEvent(self, event) -> None:
        """整张卡片吃满可用区域（玻璃罐已搬进面板，窗口里不再分左右两块）。
        ★ 用 setGeometry 而不是 setFixedSize：后者会把窗口的最小尺寸顶到
        当前卡片大小，最大化→还原时窗口就卡在大尺寸上回不来。"""
        super().resizeEvent(event)
        m = self._margin
        self.right.setGeometry(m, m,
                               max(1, self.width() - 2 * m),
                               max(1, self.height() - 2 * m))

    def changeEvent(self, event) -> None:
        """窗口状态变了（最大化/还原，含从任务栏操作）→ 同步最大化按钮图标。"""
        if event.type() == QEvent.Type.WindowStateChange:
            self.title_bar.sync_max_icon()
        super().changeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            if self.sheet is not None:
                self.close_sheet()
            elif self.phase == "deployed":
                self.recall_from_pet()
            return
        super().keyPressEvent(event)
