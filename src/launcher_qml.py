# -*- coding: utf-8 -*-
"""LEXARA 启动台 · QML 版。

设计决策（为什么这样拆）：
- **旧 `LauncherWindow` 不删不弃，而是作为「隐藏控制器」实例化** —— 部署/收回的
  完整时间轴（jar 裂纹→碎片→放出→收回坠落）、设置弹层 `SettingsSheet`、词库弹窗
  `WordbookDialog`、payload 组装、设置写盘、皮肤切换全在它身上，且已被 13 项
  测试覆盖。QML 只负责呈现，业务零复制、零分叉。
- 桌宠窗口（`PetWindow`）仍然是 Qt Widgets：全透明置顶 + 区域穿透点击 +
  `QPainter` 逐帧画腿，这些是 Widgets/QPainter 的强项，不迁。
- 桥接采用 **250ms 轮询** 而不是逐个转发信号：`LauncherWindow` 的状态散落在
  `phase / title_bar.chip / panel` 多处，轮询一处读齐，QML 侧只绑定属性，简单可靠。

打包注意：PyInstaller 需要额外收集 QtQuick/QML 模块与 `src/qml` 目录，
见 `tools/build_exe.bat`。
"""
from __future__ import annotations

import math
import os
import sys
import time

from PySide6.QtCore import (QMetaObject, QPoint, QRectF, QStandardPaths, QTimer,
                            QUrl, Qt, QObject, Property, Signal, Slot)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QRegion
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuick import QQuickPaintedItem
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from launcher_window import LauncherWindow
from lexicon import FAVORITE_CATEGORIES, OTHER_CATEGORY
import sfx
from wordbook import resource_path
from settings_store import (DEFAULTS, MAX_WORDS_CHOICES, MAX_WORDS_RANGE,
                            normalize_max_words)
# 主题令牌（2026-10-18）：QML 与 Python 画笔共用同一份值，外部改 theme.json
# 后由 ThemeStore 发信号，两边一起重绘。
import ui_theme

# 业务层模块（2026-10-17 抽出，供 QML 与旧 Widgets 共用）：
#   review_session —— 复习会话的流程编排（调度仍归 wordbook.Wordbook.grade）
#   ai.config      —— AI 非密配置 + DPAPI 密钥存储
#   ai.chat        —— 真正的对话式 AI（后台线程）
#   ocr_registry   —— OCR 引擎真实状态发现（不自建 OCR 实例）
#   help_content   —— 产品教学文案（可被测试校验）
from review_session import DEFAULT_SESSION_LIMIT, ReviewSession, due_overview
from ai.chat import EXAMPLE_PROMPTS, ChatService
from ai.config import AIConfig, SecretStore
from ai.study_help import StudyHelpService
from help_content import STEPS, STATE_LABELS
import ocr_registry

# ------------------------------------------------ 调色（与参考截图一致的浅色系）
INK = "#1F1F1F"
TEXT = "#2B2B2B"
MUTED = "#747474"
LINE = "#E7E6E0"
BG_MAIN = "#FAFAF7"
BG_SIDE = "#F0EFE9"
CARD = "#FFFFFF"
ACCENT = "#2F6BFF"
ACCENT_SOFT = "#EEF3FF"
GOOD = "#4F765F"
GOOD_SOFT = "#B9DCC1"
EMPTY = "#EEF0EE"


# ---------------------------------------------------------------- 皮肤缩略图缓存
#: 缩略图**渲染管线**版本。改了构图（画布尺寸、unit、origin、朝向）就 +1。
#: 素材本身的变动不用手工 +1 —— 指纹里已经带了 body/head 的字节数与 mtime。
_THUMB_VERSION = 6


def _thumb_dir() -> str:
    """缩略图缓存目录（系统临时目录下的专用子目录，不碰任何用户文件）。"""
    return os.path.join(
        QStandardPaths.writableLocation(QStandardPaths.TempLocation),
        "lexara_skin_thumbs")


def _skin_thumb_signature(skin_id: str) -> str:
    """该皮肤缩略图的**内容指纹**（8 位）。素材或渲染参数一变，它就变。

    为什么要有指纹（2026-10-18 修的真实 bug）
    ----------------------------------------
    缩略图以前写死叫 `v5_<skin>.png`，只在文件不存在时才画。于是用户换了
    蜘蛛的头/身体贴图之后，临时目录里那批老图还在，文件名没变 → 一直复用
    → 设置里「选皮肤」看到的还是**换素材之前的蜘蛛**。

    现在把下面这些打进指纹：
      * `_THUMB_VERSION`（构图版本）
      * body / head 素材的**字节数 + mtime_ns + 内容摘要**（贴图换了必然变；
        只看大小/时间的话，哪天解压一个保留了原始 mtime 的皮肤包会漏掉）
      * 该皮肤的腿色、身体缩放（改代码调色也会自然失效）

    `original` 是程序化几何、没有素材文件，就只靠版本号与腿色兜底。
    """
    import hashlib

    from spider_painter import SKIN_SPECS, skin_asset_path

    spec = SKIN_SPECS[skin_id]
    parts = [str(_THUMB_VERSION), skin_id, "%.4f" % float(spec.body_scale),
             spec.leg, spec.leg_hi, spec.leg_outline, spec.joint]
    for filename in (spec.body_file, spec.head_file):
        path = skin_asset_path(filename)
        try:
            info = os.stat(path) if path else None
        except OSError:
            info = None
        if info is None:
            parts.append("none")
            continue
        digest = "unreadable"
        try:
            with open(path, "rb") as handle:
                digest = hashlib.sha1(handle.read(262144)).hexdigest()[:12]
        except OSError:
            pass
        parts.append("%d:%d:%s" % (info.st_size, int(info.st_mtime_ns), digest))
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:8]


def _drop_stale_thumbs(base: str, skin_id: str, keep: str) -> None:
    """删掉这个皮肤的旧缩略图（**只删本目录里按本程序命名规则的文件**）。

    命名规则外的文件一律不碰：这是临时目录，但不是我们独占的，
    宁可留几个垃圾也不误删别人的东西。
    """
    for name in os.listdir(base):
        if name == keep:
            continue
        # `milk_spider.png` / `v5_milk_spider.png` / `t1a2b3c4_milk_spider.png`
        if name == "%s.png" % skin_id or (
                name.endswith("_%s.png" % skin_id)
                and name[0] in ("v", "t")):
            try:
                os.remove(os.path.join(base, name))
            except OSError:
                pass


# ---------------------------------------------------------------- 收藏夹统计
# 为什么放模块级而不是桥的私有方法：实例化 `LauncherBridge` 会连带拉起整个
# 隐藏控制器（词典、词库、一堆定时器），单测「数一数收藏」不该付这个代价。
# 下面三个函数只依赖 duck-typed 的 lexicon / items，`test/test_favorites.py`
# 直接构造假词典调用，和线上走的是同一份代码。


def category_total(lexicon, key: str, cache: dict | None = None):
    """该分类词库**实际可用**词条总数；不可用时返回 None（UI 显示 —）。

    分母只来自真实元数据，取不到就显示「—」，绝不编数字：
      cet4/cet6/ielts/toefl → assets/exam-tags.sqlite 的 meta.counts
      industry              → assets/industry.sqlite 的 meta.entryCount
    """
    if cache is not None and key in cache:
        return cache[key]
    total = None
    try:
        if key == "industry":
            industry = getattr(lexicon, "industry", None)
            if industry is not None and industry.available:
                total = int(industry.entry_count) or None
        else:
            tags = getattr(lexicon, "tags", None)
            if tags is not None and tags.available:
                total = int(tags.counts.get(key, 0)) or None
    except Exception:                           # noqa: BLE001
        total = None
    if cache is not None:
        cache[key] = total
    return total


def tags_of(lexicon, item) -> set:
    """收藏项的考纲标签集合。

    2026-10-18 之前的收藏记录可能没有 `tags`（老版本 `Wordbook.add()` 只存
    word/meaning），这里**回查词典**补齐，而不是把老词都丢进「未分类」。
    """
    tags = set(getattr(item, "tags", []) or [])
    if tags:
        return tags
    try:
        return set(lexicon.tags_of(item.word))
    except Exception:                           # noqa: BLE001
        return set()


def favorite_rows(items, lexicon, cache: dict | None = None) -> list:
    """收藏夹六行：五个真实分类 + 「未分类」兜底。

    一行 = {id, label, count, total, known, display}：
      count   用户收藏且命中该分类的**去重词数**（一词可属多分类，只存一份）；
      total   该分类词库总词条数，不可用时 -1；
      display 展示串，分母不可用是「3/—」；「未分类」只给计数 —— 它没有
              外部词库，写成「4/4」读起来像「4 个里收藏了 4 个」，是误导。
    """
    items = list(items or [])
    keys = {key for key, _label in FAVORITE_CATEGORIES}
    rows = []
    for key, label in FAVORITE_CATEGORIES:
        count = sum(1 for item in items if key in tags_of(lexicon, item))
        total = category_total(lexicon, key, cache)
        rows.append({"id": key, "label": label, "count": count,
                     "total": total if total is not None else -1,
                     "known": total is not None,
                     "display": ("%d/%d" % (count, total)) if total is not None
                                else ("%d/—" % count)})
    other = sum(1 for item in items if not (tags_of(lexicon, item) & keys))
    rows.append({"id": OTHER_CATEGORY[0], "label": OTHER_CATEGORY[1],
                 "count": other, "total": -1, "known": False,
                 "display": str(other)})
    return rows


FONT = "Microsoft YaHei UI"

def _base_dir() -> str:
    """资源根目录：打包后在 _MEIPASS，开发时在项目根。"""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return base


def _qml_url(name: str) -> QUrl:
    dev = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml", name)
    if os.path.isfile(dev):
        return QUrl.fromLocalFile(dev)
    return QUrl.fromLocalFile(os.path.join(_base_dir(), "qml", name))


def _assets_url() -> QUrl:
    return QUrl.fromLocalFile(os.path.join(_base_dir(), "assets") + os.sep)


def _asset(name: str) -> QUrl:
    return QUrl.fromLocalFile(os.path.join(_base_dir(), "assets", "ui", name))


# ------------------------------------------------ QQuick 自绘件
class JarItem(QQuickPaintedItem):
    """把旧 `JarView`（QWidget）渲染进 QML。

    JarView 自带 33ms 模型定时器（蜘蛛步态、裂纹 alpha、碎片物理都在里面推进），
    这里只负责把它的 `paintEvent` 输出画到 QQuickPaintedItem 上 —— 因此
    部署/收回的整条动画时间轴（crack_on / burst_out / begin_fall / reset）
    原样可用，一行没改。

    2026-10-17 性能修正：以前这里无条件每 33ms `update()` 一次，和 JarView
    内部的 33ms 模型定时器叠成「双层全速重绘」，罐子空着（已部署）时也在烧 CPU。
    现在先问 `JarView.has_changed()`：模型侧说「这帧没东西动」就不重画。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jar: QWidget | None = None
        self._timer = QTimer(self, interval=33, timeout=self._refresh)

    def _refresh(self) -> None:
        jar = self._jar
        if jar is None:
            return
        # has_changed 兼顾三件事：动画在跑 / 相位刚切换 / 尺寸刚变
        if jar.has_changed():
            self.update()

    def get_jar(self) -> QObject:
        return self._jar

    def set_jar(self, jar) -> None:
        self._jar = jar
        if self._jar is not None:
            # ★ 2026-10-18：解除 Widgets 版对 JarView 的尺寸约束。
            #   `LauncherWindow` 的面板把 JarView 设成「固定高 = 六档按钮高度」
            #   （setFixedHeight(300)），QML 端要按 2:1 展示区的实际尺寸渲染。
            #   固定高会夹住 `resize()`：item 明明是 444×222，widget 仍是
            #   444×300 → 蜘蛛按 300 高算 unit 却画进 222 高的纹理，
            #   看起来就是「蜘蛛偏大、腿压出圆角矩形」。
            jar.setMinimumSize(0, 0)
            jar.setMaximumSize(16777215, 16777215)
            jar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            self._timer.start()

    jar = Property(QObject, get_jar, set_jar)

    def geometryChanged(self, new_geometry, old_geometry) -> None:
        """尺寸变了必须重画一帧（2026-10-18 修）。

        `JarView` 的**唯一** resize 点在 `paint()` 里；而 `paint()` 只有被
        `update()` 才会跑。窗口缩放后 QQuickPaintedItem 会把**旧纹理拉伸**到
        新尺寸 —— 展示区看起来「蜘蛛变扁、还越出圆角矩形」，本体其实一直是
        上一次的 444×300 帧。`geometryChanged` 是 QQuickItem 的尺寸变化回调，
        在这里补一次 `update()`，`has_changed()` 里的尺寸判定才会真正生效。
        """
        super().geometryChanged(new_geometry, old_geometry)
        self.update()

    @staticmethod
    def draw_jar(painter: QPainter, jar: QWidget, w: int, h: int) -> None:
        """把 JarView 画到 `painter` 上（`paint()` 的唯一绘制点）。

        抽成静态方法是给 `test/test_jar_stage.py` 用的：测试能直接走**真实的
        这条渲染路径**去量像素，而不是另写一份等价代码自证。
        """
        jar.resize(w, h)
        if jar.width() != w or jar.height() != h:      # 兜底：布局又改回来了
            jar.setFixedSize(w, h)
        # ★ 2026-10-18：必须显式去掉 `DrawWindowBackground`。
        #   `QWidget.render()` 默认 flags = DrawWindowBackground | DrawChildren，
        #   会先把整块区域用调色板 Window 色**不透明地**填一遍（实测
        #   rgba(249,249,249,255)），`JarView.paintEvent` 里那层
        #   `QColor(255,255,255,128)` 被压在下面 → 展示区看起来是一块死白的板子，
        #   即用户说的「说好 50% 透明度呢」。
        #   只画 DrawChildren（= paintEvent 的输出），圆角外自然透出卡片渐变。
        jar.render(painter, QPoint(0, 0), QRegion(0, 0, w, h),
                   QWidget.RenderFlag.DrawChildren)

    def paint(self, painter: QPainter) -> None:
        jar = self._jar
        w, h = int(self.width()), int(self.height())
        if jar is None or w < 4 or h < 4:
            return
        # ★ 守卫（2026-10-18）：JarView 一旦**可见**，说明有人把隐藏控制器
        #   `show()` 出来了。此时 Qt 自己的 backing store 正在画这个 widget，
        #   这里再 `render()` 会经由 `resize()` 触发同步重排 → 重入 paint →
        #   access violation（`tools/deploy_cycle_probe.py` 实测 exit 139）。
        #   根因已在 `LauncherWindow.show()` 里堵掉（headless 忽略 show），
        #   这道守卫是第二层保险：宁可这一帧空着，也不要把进程带走。
        if jar.isVisible():
            return
        self.draw_jar(painter, jar, w, h)


class HeatGrid(QQuickPaintedItem):
    """学习日志点阵（7 行 × 53 列左右），数据来自 `activity` 的真实事件表。

    三色语义（任务书 §2.5 / §7.2，与成就判定共用同一份口径）：

    - 灰（#EEF0EE）：当天没有任何学习活动；
    - 浅绿（#B9DCC1）：当天至少完成一次蜘蛛扫描；
    - 深绿（#4F765F）：当天至少完成一次背单词复习或主动 AI 提问（同日优先）。

    ★ 2026-10-18：日 / 周 / 月 / 年四档选择器**已删除**（任务书 §2.6）。
      格子按可用宽度铺满，标题也不再由这里画：QML 用一个真 Label
      显示「学习日志 · 已打卡 XX 天」，并在旁边放 `?` 说明按钮。

    ★ 2026-10-19：窗口从「滚动近一年」改成**自然年**（`activity.year_span`），
      用户口径是「1-12 月从左到右」。月份标签画在每月 1 号那一列下方，
      顺序天然递增；两端补位格（去年 12 月末 / 明年 1 月初）画成暗色。
      右下角那行「浅色：扫描过　深色：复习 / 问 AI　灰：没有学习」**已删除**
      —— 颜色语义由标题旁的 `?` 弹层负责，底下一行纯属重复占地方。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._book = None
        # 缓存（2026-10-17）：事件只追加不删除，按条数做键即可；
        # 整年的日期串/月标签按「今天」缓存，跨天才重算。
        # QML 侧这个件是被随时无条件 update() 触发的，逐帧重建代价更大。
        self._cache_key = None
        self._levels: dict = {}
        self._cells: list = []
        self._day_key = None
        self._month_at: dict = {}

    def get_book(self) -> QObject:
        return self._book

    @Slot(QObject)
    def attachBook(self, book) -> None:
        """由 Python 侧在 QML 加载完后调用（QML 里绑 book Property 会在
        engine.load 期间触发段错误，见 2026-10-17 调试记录）。"""
        self._book = book
        self._cache_key = None          # 换库必须重建计数
        self.update()

    #: 让 QML 侧能在学习活动后主动刷新（不需要等 250ms 轮询）。
    @Slot()
    def refresh(self) -> None:
        self.update()

    def _data_maps(self) -> dict:
        if self._book is None:
            return {}
        study = getattr(self._book, "study_events", [])
        review = getattr(self._book, "review_events", [])
        ai = getattr(self._book, "ai_events", [])
        key = (len(study), len(review), len(ai))
        if key != self._cache_key:
            try:
                import activity
                self._levels = activity.learning_map(self._book)
            except Exception:               # noqa: BLE001
                self._levels = {}
            self._cache_key = key
        return self._levels

    def _day_names(self) -> None:
        today_key = time.strftime("%Y-%m-%d")
        if today_key != self._day_key:
            try:
                import activity
                self._cells = activity.calendar_cells(self._book)
            except Exception:               # noqa: BLE001
                self._cells = []
            self._month_at = {}
            for index, cell in enumerate(self._cells):
                day = cell.get("date", "")
                # 两端补位格（去年 12 月 1 日那种）不标月份，否则左上角会多出
                # 一个「12月」，让人以为这一年从 12 月开始。
                if day.endswith("-01") and not cell.get("outOfYear"):
                    # 去掉前导零：「1月」而不是「01月」—— 12 个标签横排时
                    # 两位数字会显得挤，而且用户平时也不这么写月份。
                    self._month_at[index] = "%d月" % int(day[5:7])
            self._day_key = today_key

    def paint(self, painter: QPainter) -> None:
        w, h = self.width(), self.height()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        # 卡片底/描边也走主题（2026-10-18）：换成夜间预设时，这块白底会
        # 把浅色标题压得看不见 —— 它本来就是界面的一部分，不该有自己的色。
        painter.setPen(ui_theme.color("base.line", LINE))
        painter.setBrush(ui_theme.color("base.card", CARD))
        painter.drawRoundedRect(rect, 12, 12)
        self._data_maps()
        self._day_names()

        weeks, rows = 53, 7
        # ★ 2026-10-19：日历改成**自然年**之后，列数不再恒等于 53 ——
        #   1/1 与 12/31 各落在周中哪一天，会让年窗口是 53 列或 54 列
        #   （周对齐后 371~378 天）。写死 53 的话，54 列的那一年最后一列
        #   会画到卡片外面去。这里按真实格子数反推。
        if self._cells:
            weeks = max(1, (len(self._cells) + rows - 1) // rows)
        # 顶部 46px 留给 QML 的标题行（「学习日志 · 已打卡 XX 天」+ ? 按钮），
        # 底部 30px 留给月份标签。
        start_x, start_y = 18.0, 46.0
        gap = 3.0
        # 格子按可用宽度铺满：以前上限 15px，删掉日/周/月/年之后多出来的
        # 横向空间本来会变成两边的空白。现在按列数平分，上限抬到 18px。
        cell = (w - start_x * 2 - (weeks - 1) * gap) / weeks
        cell = max(6.0, min(18.0, cell))
        empty = ui_theme.color("heat.empty", EMPTY)
        dim = ui_theme.color("base.line", "#F4F5F3")
        scan_c = ui_theme.color("heat.light", GOOD_SOFT)
        study_c = ui_theme.color("heat.deep", GOOD)
        no_pen = Qt.PenStyle.NoPen
        faint = ui_theme.color("base.subtle", "#9A9A96")
        small = QFont(FONT)
        small.setPixelSize(11)

        for index, cell_data in enumerate(self._cells):
            col = index // rows
            future = bool(cell_data.get("future"))
            # 两端补位格（去年 12 月末 / 明年 1 月初）不算今年，画成暗色 ——
            # 网格保持完整的一整块，但一眼能看出「这一格不属于这一年」。
            outside = bool(cell_data.get("outOfYear"))
            level = cell_data.get("level", "none")
            if future or outside:
                color = dim
            elif level == "study":
                color = study_c
            elif level == "scan":
                color = scan_c
            else:
                color = empty
            x = start_x + col * (cell + gap)
            y = start_y + (index % rows) * (cell + gap)
            painter.setPen(no_pen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, y, cell, cell), 3, 3)
            label = self._month_at.get(index)
            if label:
                painter.setPen(faint)
                painter.setFont(small)
                painter.drawText(QRectF(x, start_y + rows * (cell + gap) + 4,
                                        42, 16), Qt.AlignLeft, label)


# ------------------------------------------------ 桥接
def build_engine(bridge, theme, parent=None, on_warnings=None) -> QQmlApplicationEngine:
    """建 QML 引擎、注入上下文、载入 Main.qml —— **唯一的装配点**。

    2026-10-18：以前 `run()`、`tools/ui_probe.py`、`tools/deploy_cycle_probe.py`
    各自复刻一遍「注册类型 + setContextProperty + load」。主题一加进去，两个
    探针就漏了 `theme`，测出来的是「一份没有主题的界面」（84 条 undefined
    警告），而真正的窗口是正常的 —— 这种偏差比测试失败更难发现。
    现在三处共用这一个函数，加新上下文属性只要改这里。
    """
    qmlRegisterType(JarItem, "Lexara", 1, 0, "SpiderJar")
    qmlRegisterType(HeatGrid, "Lexara", 1, 0, "HeatGrid")
    engine = QQmlApplicationEngine(parent)
    if on_warnings is not None:
        engine.warnings.connect(on_warnings)
    ctx = engine.rootContext()
    ctx.setContextProperty("bridge", bridge)
    ctx.setContextProperty("theme", theme)
    for prop, name in (("logoUrl", "lexara_logo.png"),
                       ("skinIconUrl", "icon_skin.png"),
                       ("settingsIconUrl", "icon_settings.png")):
        ctx.setContextProperty(prop, _asset(name))
    engine.load(_qml_url("Main.qml"))
    return engine


class LauncherBridge(QObject):
    """QML ↔ 旧 LauncherWindow（隐藏控制器）的轮询桥。"""

    def __init__(self, lexicon, book, settings, log=None, parent=None,
                 secrets: SecretStore | None = None):
        super().__init__(parent)
        self._log = log or (lambda message: None)
        self.launcher = LauncherWindow(lexicon, book, settings, log=log)
        # ★ 隐藏控制器不许自己 show（§4 重复 UI + 段错误的根因）：
        #   本文件持有真正的可见窗口（QML 的 ApplicationWindow），旧窗口只出像素、
        #   不出界面。要「把启动台带到前台」时走 present_callback。
        self.launcher.headless = True
        self.launcher.present_callback = self.present_window
        self._book = book
        self._settings = settings
        self._lexicon = lexicon
        #: 收藏夹分母缓存（key -> int|None）；词典不可用时也会缓存 None，
        #: 避免每次读属性都去问一遍 sqlite。
        self._category_totals: dict = {}
        self._engine: QQmlApplicationEngine | None = None
        self._window = None
        self._notice = ""
        self._skins: list | None = None

        # ---- 背单词：流程状态在这里，调度算法仍在 wordbook.py
        self._review = ReviewSession(book, limit=DEFAULT_SESSION_LIMIT)
        #: ``home`` → 复习入口页；``card`` → 卡片；``done`` → 完成页
        self._review_stage = "home"

        # ---- AI：配置 + 对话
        # ``secrets`` 可注入：自动化测试用一个临时目录，避免碰到用户真实密钥。
        self._secrets = secrets or SecretStore()
        self._ai_config = AIConfig(settings, self._secrets)
        self._chat = ChatService(self._ai_config, self)
        self._chat.messagesChanged.connect(self._on_chat_changed)
        self._chat.busyChanged.connect(self._on_chat_changed)
        self._chat.statusChanged.connect(self._on_chat_changed)
        self._chat.testingChanged.connect(self._on_chat_changed)
        self._chat.testFinished.connect(self._on_test_finished)
        #: 只有**真的拿到回复**才算一次「主动 AI 提问」学习活动（深绿）。
        #: 失败 / 取消 / 未配置都不会走到这里。
        self._chat.askSucceeded.connect(self._on_ask_succeeded)
        #: 背单词卡片的「造句 / 同义词」。**独立的服务实例**：它不该把消息塞进
        #: 对话页，也不该受对话上下文影响（同一张卡片两次点击要给同样的东西）。
        self._study_help = StudyHelpService(self._ai_config, self)
        self._study_help.changed.connect(self._on_chat_changed)
        self._last_test: dict = {}
        #: 学习日历 / 成就的缓存键（事件条数 + 今天），避免 250ms 轮询里重算 371 格
        self._activity_key = None
        self._activity: dict = {}
        self._achievement_ids: tuple = ()
        #: QML 里的点阵实例（加载后 findChildren 填），学习活动变化时主动重绘
        self._grids: list = []

        self._values = {
            "phase": "", "deployText": "", "deployEnabled": True,
            "due": 0, "total": 0, "status": "",
        }
        self._poll = QTimer(self, interval=250, timeout=self._refresh)
        self._poll.start()

    # ---- QML 属性（共用 changed 通知）
    def _changed_emit(self) -> None:
        self.changed.emit()

    changed = Signal()

    def _get(self, key):
        return self._values[key]

    phase = Property(str, lambda self: self._get("phase"), notify=changed)
    deployText = Property(str, lambda self: self._get("deployText"), notify=changed)
    deployEnabled = Property(bool, lambda self: self._get("deployEnabled"),
                             notify=changed)
    due = Property(int, lambda self: self._get("due"), notify=changed)
    total = Property(int, lambda self: self._get("total"), notify=changed)
    status = Property(str, lambda self: self._get("status"), notify=changed)
    notice = Property(str, lambda self: self._notice, notify=changed)

    def _get_jar(self) -> QObject:
        return self.launcher.jar

    jar = Property(QObject, _get_jar, notify=changed)

    def _get_book(self) -> QObject:
        return self._book

    book = Property(QObject, _get_book, notify=changed)

    # ---- 设置面板要用的实时值（每次读都从 settings 现取，不缓存）
    def _values_now(self) -> dict:
        return self.launcher.settings.as_dict()

    maxWords = Property(int, lambda self: int(self._values_now().get(
        "max_words", DEFAULTS["max_words"])), notify=changed)
    #: 「最大识词」的**四档**候选（8 / 16 / 32 / 48），唯一来源是
    #: `settings_store.MAX_WORDS_CHOICES`。2026-10-19 从连续滑杆改成档位按钮，
    #: QML 里不写字面量 —— 那个数字今年已经改过一次（8 → 24 → 四档）。
    maxWordsChoices = Property("QVariantList",
                               lambda self: list(MAX_WORDS_CHOICES),
                               constant=True)
    minConfPct = Property(
        int, lambda self: int(round(float(self._values_now().get("min_conf", 0.6)) * 100)),
        notify=changed)
    petScalePct = Property(
        int, lambda self: int(round(float(self._values_now().get("pet_scale", 1.0)) * 100)),
        notify=changed)
    alwaysOnTop = Property(
        bool, lambda self: bool(self._values_now().get("always_on_top", True)),
        notify=changed)
    showMeaningCard = Property(
        bool, lambda self: bool(self._values_now().get("show_meaning_card", True)),
        notify=changed)
    engineName = Property(str, lambda self: self._engine_label(), notify=changed)
    currentEngineState = Property(dict, lambda self: self._engine_state(),
                                  notify=changed)
    currentSkin = Property(str, lambda self: str(self._values_now().get("skin", "")),
                           notify=changed)
    # ---- 界面主题（白天/夜晚/跟随系统）。预设数据源是 ui_theme.PRESETS。
    #: 设置面板只摆这两套 + 一个自动档 —— ink/ocean/paper 是给 theme_tool
    #: 命令行留的，七个胶囊挤在一行里反而没人用得起来。
    UI_THEME_PRESETS = ("forest", "midnight")
    #: 「跟随系统」不是配色，是第三颗胶囊的虚拟 id（不进 PRESETS）。
    THEME_AUTO_ID = "auto"

    #: 面板上用的短名：PRESETS 里的 label（「墨绿 · 象牙白（默认）」）是给
    #: 命令行列表看的，塞进 26px 高的胶囊只会撑破行。
    UI_THEME_LABELS = {"forest": "白天", "midnight": "夜晚"}

    themePresets = Property(
        "QVariantList",
        lambda self: [{"id": pid,
                       "label": LauncherBridge.UI_THEME_LABELS.get(
                           pid, ui_theme.PRESETS[pid][0])}
                      for pid in LauncherBridge.UI_THEME_PRESETS
                      if pid in ui_theme.PRESETS]
        + [{"id": LauncherBridge.THEME_AUTO_ID, "label": "跟随系统"}],
        notify=changed)

    def _current_theme_preset(self) -> str:
        """当前预设：theme.json 的 `_preset` 是真源，settings 里的只是副本。"""
        store = getattr(self, "_theme", None)
        preset = store.current_preset() if store is not None else None
        if preset:
            return preset
        return str(self._values_now().get("theme_preset") or "forest")

    themeAuto = Property(bool, lambda self: bool(
        self._values_now().get("theme_auto", False)), notify=changed)

    currentThemePreset = Property(
        str,
        lambda self: (LauncherBridge.THEME_AUTO_ID if self.themeAuto
                      else self._current_theme_preset()),
        notify=changed)

    # ---- 背单词（只读 QML 用；所有写操作走 Slot → ReviewSession → Wordbook）
    reviewOverview = Property(
        dict, lambda self: due_overview(self._book), notify=changed)
    reviewCard = Property(dict, lambda self: self._review.card(), notify=changed)
    reviewSummary = Property(dict, lambda self: self._review.summary(),
                             notify=changed)
    reviewStage = Property(str, lambda self: self._review_stage, notify=changed)
    #: AI 辅助（造句 / 同义词）的当前状态。字段：
    #: `state` idle|loading|done|error、`word`、`mode`、`modeLabel`、
    #: `text`、`error`、`code`。QML 只读，动作走 `reviewHelpRequest()`。
    reviewHelp = Property(dict, lambda self: self._study_help.state,
                          notify=changed)
    #: 模型是否配置好。**没配时按钮仍然可点**：点了会得到一条「缺什么、去哪填」
    #: 的说明 —— 比一个灰按钮更能让用户知道这功能存在（`aiReady` 同理）。
    reviewHelpReady = Property(bool, lambda self: self._ai_config.configured(),
                               notify=changed)

    # ---- AI 对话 / 配置
    aiReady = Property(bool, lambda self: self._ai_config.configured(),
                       notify=changed)
    aiSnapshot = Property(dict, lambda self: self._ai_config.snapshot(),
                          notify=changed)
    chatMessages = Property(list, lambda self: self._chat.messages, notify=changed)
    chatBusy = Property(bool, lambda self: self._chat.busy, notify=changed)
    chatTesting = Property(bool, lambda self: self._chat.testing, notify=changed)
    chatStatus = Property(dict, lambda self: self._chat.status, notify=changed)
    chatExamples = Property(list, lambda self: list(EXAMPLE_PROMPTS),
                            notify=changed)

    # ---- OCR 引擎（状态由 ocr_registry 问 Qoder 的实现，UI 不编造）
    engines = Property(list, lambda self: ocr_registry.list_engines(),
                       notify=changed)
    currentEngine = Property(
        str, lambda self: ocr_registry.current_engine_id(self._settings),
        notify=changed)
    currentEngineName = Property(str, lambda self: self._engine_label(),
                                 notify=changed)
    engineSwitchable = Property(
        bool,
        lambda self: len([e for e in ocr_registry.list_engines()
                          if e["state"] == "available"]) > 1,
        notify=changed)

    # ---- 帮助
    helpSteps = Property(list, lambda self: [
        dict(step, stateLabel=STATE_LABELS.get(step["state"], ""))
        for step in STEPS], notify=changed)

    def _engine_label(self) -> str:
        """当前引擎的显示名；**不可用时连状态一起显示**，不让用户蒙在鼓里。"""
        chosen = ocr_registry.current_engine_id(self._settings)
        engines = {e["id"]: e for e in ocr_registry.list_engines()}
        picked = engines.get(chosen)
        if picked is None:
            return chosen
        if picked["state"] == "available":
            return picked["name"]
        return "%s · %s" % (picked["name"], picked["stateLabel"])

    def _engine_state(self) -> dict:
        """当前引擎的完整状态（含官方给的原因），供 QML 显示 tooltip / 说明文案。"""
        chosen = ocr_registry.current_engine_id(self._settings)
        for row in ocr_registry.list_engines():
            if row["id"] == chosen:
                return row
        return {"id": chosen, "name": chosen, "state": "unknown",
                "stateLabel": ocr_registry.STATE_LABELS["unknown"], "reason": "",
                "version": ""}

    # ------------------------------------------------ 收藏夹（任务书 §2.2）
    #: 五分类 + 顺序即 QML 展示顺序，统计逻辑在模块级 `favorite_rows()` 里
    #: （纯函数，不依赖 QObject，便于单测直接调用）。

    def _category_total(self, key: str):
        """该分类词库**实际可用**词条总数；不可用时返回 None（UI 显示 —）。"""
        return category_total(self._lexicon, key, self._category_totals)

    def _tags_of(self, item) -> set:
        return tags_of(self._lexicon, item)

    def _favorite_rows(self) -> list:
        return favorite_rows(self._book.items, self._lexicon,
                             self._category_totals)

    favorites = Property(list, lambda self: self._favorite_rows(), notify=changed)

    @Slot(str)
    def openWordbookCategory(self, category: str) -> None:
        """点分类 → 打开单词本并按该分类过滤（同一个收藏数据，不复制）。"""
        self.launcher.open_wordbook(category or "")

    # ------------------------------------------------ 学习日历（任务书 §2.5 / §7）
    def _activity_snapshot(self) -> dict:
        key = (len(getattr(self._book, "open_dates", []) or []),
               len(getattr(self._book, "study_events", []) or []),
               len(getattr(self._book, "review_events", []) or []),
               len(getattr(self._book, "ai_events", []) or []),
               time.strftime("%Y-%m-%d"))
        if getattr(self, "_activity_key", None) != key:
            import activity
            self._activity = activity.summary(self._book)
            self._activity_key = key
        return getattr(self, "_activity", {})

    activity = Property(dict, lambda self: self._activity_snapshot(),
                        notify=changed)

    def _achievement_snapshot(self) -> dict:
        import activity
        return activity.pending_payload(self._book)

    achievement = Property(dict, lambda self: self._achievement_snapshot(),
                           notify=changed)

    @Slot(bool, result=dict)
    def dismissAchievement(self, save_image: bool) -> dict:
        """成就弹窗的两个按钮。

        - `save_image=True`：弹系统保存对话框 → 画 PNG → 成功后才标记已读；
        - `False`：只标记已读，不生成任何文件，也不重复弹。
        取消保存时**不**标记已读（用户还能再点一次），也不会误报成功。
        """
        import activity
        import calendar_export
        payload = activity.pending_payload(self._book)
        if not payload:
            return {"ok": False, "message": "没有待展示的成就。"}
        if save_image:
            path = self._ask_calendar_path(payload)
            if not path:
                return {"ok": False, "cancelled": True,
                        "message": "已取消保存，成就仍会保留在这里。"}
            result = calendar_export.export(self._book, path)
            if not result.get("ok"):
                self._notice = result.get("message", "保存失败。")
                self.changed.emit()
                QTimer.singleShot(6000, self, self._clear_notice)
                return dict(result, ok=False)
            self._notice = result.get("message", "已保存日历图片")
        else:
            self._notice = "已记录成就，这次不保存图片"
        activity.mark_seen(self._book, [payload["id"]])
        self.changed.emit()
        QTimer.singleShot(5000, self, self._clear_notice)
        return {"ok": True}

    @Slot(result=dict)
    def exportCalendar(self) -> dict:
        """面板里的「导出日历图片」入口（不依赖成就弹窗）。"""
        import calendar_export
        path = self._ask_calendar_path({})
        if not path:
            return {"ok": False, "cancelled": True, "message": "已取消"}
        result = calendar_export.export(self._book, path)
        self._notice = result.get("message", "")
        self.changed.emit()
        QTimer.singleShot(6000, self, self._clear_notice)
        return result

    def _ask_calendar_path(self, payload: dict) -> str:
        """系统保存对话框，默认 PNG + 日期文件名。"""
        from PySide6.QtWidgets import QFileDialog
        default = os.path.join(
            QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            or os.path.expanduser("~"),
            "词蛛学习日历_%s.png" % time.strftime("%Y%m%d"))
        name = (payload or {}).get("name") or ""
        if name:
            default = default.replace("学习日历", "学习日历_%s" % name)
        path, _filter = QFileDialog.getSaveFileName(
            None, "保存学习日历图片", default, "PNG 图片 (*.png)")
        return path or ""

    # ------------------------------------------------ 启动行为（任务书 §5 / §6）
    def _autostart_state(self) -> dict:
        import autostart
        return autostart.state()

    autostartState = Property(dict, lambda self: self._autostart_state(),
                              notify=changed)
    autoDeployOnStart = Property(
        bool, lambda self: bool(self._values_now().get("auto_deploy_on_start", True)),
        notify=changed)

    @Slot(bool, result=dict)
    def setAutoDeployOnStart(self, value: bool) -> dict:
        self.launcher._write_settings({"auto_deploy_on_start": bool(value)})
        self._notice = ("启动后将自动部署蜘蛛" if value
                        else "启动后停留在启动台，需要手动部署")
        self.changed.emit()
        QTimer.singleShot(4000, self, self._clear_notice)
        return {"ok": True}

    @Slot(bool, result=dict)
    def setAutostart(self, enabled: bool) -> dict:
        """开机自启动开关。失败时**回滚 UI**（不改设置位）并说明原因。"""
        import autostart
        result = autostart.enable() if enabled else autostart.disable()
        self._notice = result.get("message", "")
        self.changed.emit()
        QTimer.singleShot(8000, self, self._clear_notice)
        return result

    def _skin_options(self) -> list:
        """4 套皮肤的缩略图（首次调用时用 SpiderPainter 现画到临时目录）。

        为什么不直接贴 skin 的 body/head png：原始皮肤是程序化几何、没有素材，
        而且贴图皮肤也需要腿色/关节一起出效果 —— 用真实渲染器画一张 170px
        的图，四套观感才一致。

        ★ 缓存文件名带**素材指纹**（2026-10-18 修）：
        以前文件名写死成 `v5_<skin>.png`，皮肤贴图换了但文件名没变，临时目录里
        10 月 17 日那批缩略图就一直被复用 —— 用户看到的是**旧蜘蛛的预览**，
        和换过的头/身体对不上。现在文件名由 :func:`_skin_thumb_signature` 决定，
        素材一变指纹就变、URL 就变，QML 的 Image 也就不会拿旧图。
        """
        if self._skins is not None:
            return self._skins
        import crawler_spider as CS
        from spider_painter import SKIN_ORDER, SKIN_SPECS, SpiderPainter, SpiderState
        base = _thumb_dir()
        os.makedirs(base, exist_ok=True)
        out = []
        for skin_id in SKIN_ORDER:
            name = "t%s_%s.png" % (_skin_thumb_signature(skin_id), skin_id)
            path = os.path.join(base, name)
            _drop_stale_thumbs(base, skin_id, keep=name)
            if not os.path.isfile(path):
                image = QImage(170, 170, QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.Antialiasing, True)
                spider = CS.Spider(size=1.0)
                # ★ 两个坑（2026-10-17 实测）：
                # 1) heading 必须 PI/2。crawler_spider 的注释写得很清楚：0 是「上四下四」
                #    的螃蟹站法，PI/2 才是左上二/左下二/右上二/右下二的蜘蛛俯视。
                # 2) 新建的 Spider 腿还没落位，必须先跑几帧 update，否则 8 条腿全缩在
                #    髋部，画出来只有一颗光秃秃的身体（第一版就是这样）。
                spider.heading = math.pi / 2
                for _ in range(20):
                    spider.update(0.016, "idle", None, motion=(0.0, 0.0))
                renderer = SpiderPainter()
                renderer.set_skin(skin_id)
                unit = SpiderPainter.unit_for_width(144)
                renderer.paint(painter, spider,
                               SpiderState(heading=math.pi / 2, moving=False, dim=1.0),
                               unit=unit, origin_px=(85.0, 92.0))
                painter.end()
                image.save(path)
            out.append({"id": skin_id, "name": SKIN_SPECS[skin_id].name,
                        "thumb": QUrl.fromLocalFile(path).toString()})
        self._skins = out
        return out

    skins = Property(list, lambda self: self._skin_options(), notify=changed)

    # ---- QML 槽
    @Slot()
    def deployOrRecall(self) -> None:
        self.launcher.on_deploy_button()

    @Slot()
    def openSettings(self) -> None:
        self.launcher.open_sheet()

    @Slot()
    def openWordbook(self) -> None:
        self.launcher.open_wordbook()

    @Slot()
    def startReview(self) -> None:
        self.launcher.start_review()

    @Slot(str, result=bool)
    def send(self, text: str) -> bool:
        """发送一条对话消息。返回 False 表示**没有发出请求**。

        2026-10-17：这里以前只回一条 notice，是「看起来能聊」的假对话。
        现在真的走 `ai.chat.ChatService`（后台线程发 OpenAI 兼容请求）；
        没配置模型时拒绝发送并由 QML 把发送按钮置灰，而不是假装成功。
        """
        ok = self._chat.send(text)
        if not ok and not self._chat.busy:
            status = self._chat.status
            self._notice = status.get("message", "输入框不能为空。")
            QTimer.singleShot(5000, self, self._clear_notice)
        self.changed.emit()
        return ok

    @Slot()
    def cancelChat(self) -> None:
        self._chat.cancel()
        self.changed.emit()

    @Slot()
    def newChatSession(self) -> None:
        self._chat.newSession()
        self.changed.emit()

    @Slot(str, result=bool)
    def copyText(self, text: str) -> bool:
        """复制到系统剪贴板（「复制回复」按钮用）。失败返回 False，UI 不撒谎。"""
        text = text or ""
        if not text:
            return False
        try:
            clipboard = QGuiApplication.clipboard()
            if clipboard is None:
                return False
            clipboard.setText(text)
            return True
        except Exception:                          # noqa: BLE001
            return False

    @Slot(str, result=str)
    def lastReply(self, fallback: str = "") -> str:
        """给「复制回复」用。没有可复制的内容就返回空串，让 UI 自己禁用。"""
        return self._chat.copyLastReply()

    # ------------------------------------------------ AI 配置面板
    @Slot(str, str, str, result=dict)
    def saveAiConfig(self, base_url: str, model: str, api_key: str) -> dict:
        """保存 AI 配置。``api_key`` 留空 = **不改动**已保存的密钥。"""
        try:
            result = self._ai_config.update(base_url or "", model or "",
                                            (api_key or "").strip())
            self._notice = ("已保存 · %s" % result["endpoint"]
                            if not api_key.strip() and not result["keySaved"]
                            else "已保存模型配置")
        except Exception as error:                  # noqa: BLE001
            # 异常文案里可能带 URL，但**绝不会**带密钥（config.mask 已处理）
            self._notice = "保存失败：%s" % (error,)
            result = {"ok": False, "message": str(error)}
        self.changed.emit()
        QTimer.singleShot(4000, self, self._clear_notice)
        return result

    @Slot(result=dict)
    def clearAiKey(self) -> dict:
        result = self._ai_config.clear_key()
        self._notice = "已清除已保存的 API Key" if result.get("cleared") \
            else "本机没有保存过 API Key"
        self.changed.emit()
        QTimer.singleShot(4000, self, self._clear_notice)
        return result

    @Slot(result=bool)
    def testAiConnection(self) -> bool:
        """异步测试连接。结果通过 `chatStatus` / `notice` 回传。"""
        return self._chat.testConnection()

    # ------------------------------------------------ OCR 引擎选择
    @Slot(str, result=dict)
    def selectEngine(self, engine_id: str) -> dict:
        result = ocr_registry.switch_engine(self._settings, engine_id)
        self._notice = result.get("message", "")
        self.changed.emit()
        QTimer.singleShot(5000, self, self._clear_notice)
        return result

    # ------------------------------------------------ 界面主题
    def _apply_theme_preset(self, preset: str) -> None:
        store = getattr(self, "_theme", None)
        if store is not None:
            store.apply_preset(preset)
        else:
            # 无头/测试路径没有 store：直接落文件，语义与 apply_preset 一致。
            raw, _ = ui_theme.read_raw()
            ui_theme.write_file(None, ui_theme.apply_preset_to_raw(raw, preset))

    @Slot(str, result=dict)
    def setThemePreset(self, preset_id: str) -> dict:
        """切换启动台整套配色（白天 forest / 夜晚 midnight / 跟随系统 auto）。

        两步要一起做完：把预设整套盖进 theme.json（`ThemeStore.apply_preset`
        会 emit `valuesChanged`，QML 绑定 + Python 画笔自动重绘），再把选中的
        id 记进 settings.json 当副本。自动档下 `theme_preset` 存的是用户
        **上一次手动**选的预设，切回手动时那颗胶囊还能还原。不认识就拒绝。
        """
        if preset_id == self.THEME_AUTO_ID:
            target = ui_theme.system_preset()
            self._apply_theme_preset(target)
            self.launcher._write_settings({"theme_preset": target,
                                           "theme_auto": True})
            self.changed.emit()
            return {"ok": True, "message": ""}
        if preset_id not in ui_theme.PRESETS:
            return {"ok": False, "message": "未知主题预设 %s" % preset_id}
        self._apply_theme_preset(preset_id)
        self.launcher._write_settings({"theme_preset": preset_id,
                                       "theme_auto": False})
        self.changed.emit()
        return {"ok": True, "message": ""}

    def _start_theme_follow_timer(self) -> None:
        """60 秒看一眼系统深浅色。轮询很便宜（一次注册表读 + 两次 dict.get），
        而系统换深浅色没有可靠的 Qt 事件可挂；只有真变了才写盘重绘。"""
        timer = QTimer(self)
        timer.setInterval(60_000)
        timer.timeout.connect(self._follow_system_theme)
        timer.start()
        self._theme_follow_timer = timer

    def _follow_system_theme(self) -> None:
        try:
            if not bool(self._values_now().get("theme_auto", False)):
                return
            target = ui_theme.system_preset()
            if self._current_theme_preset() == target:
                return
            self._apply_theme_preset(target)
            self.launcher._write_settings({"theme_preset": target})
            self.changed.emit()
        except Exception as error:          # noqa: BLE001 —— 定时器不许把主循环带崩
            self._log("[theme] 跟随系统失败: %r" % (error,))

    # ------------------------------------------------ 背单词
    @Slot()
    def openReview(self) -> None:
        """打开复习面板并刷新入口页统计（数据全部来自真实词库）。"""
        self._review_stage = "home"
        self.changed.emit()

    @Slot(bool)
    def startReviewSession(self, due_only: bool = False) -> None:
        summary = self._review.start(include_upcoming=not bool(due_only))
        self._review_stage = "card" if summary["total"] else "home"
        self._study_help.reset()          # 新一局：上一张的 AI 结果不能跟过来
        self.changed.emit()

    @Slot()
    def reviewReveal(self) -> None:
        self._review.reveal()
        self.changed.emit()

    @Slot(bool)
    def reviewGrade(self, correct: bool) -> None:
        """自评 → `ReviewSession.grade()` → `Wordbook.grade()` → 真实 1/3/7/14 调度。"""
        self._review.grade_and_advance(bool(correct))
        if correct:
            # 「记住了」的提示音。放在 grade 之后：写盘失败也不该少这一声，
            # 但**必须先判 true** —— 「没记住」不该有庆祝音。
            sfx.play_ding()
        if self._review.summary()["finished"]:
            self._review_stage = "done"
        # 卡片已经换人：在途的造句请求作废，避免「上一张的例句」盖到下一张。
        self._study_help.reset()
        self.changed.emit()

    @Slot(int)
    def reviewStep(self, delta: int) -> None:
        self._review.step(int(delta))
        self._study_help.reset()
        self.changed.emit()

    @Slot()
    def reviewRetryWrong(self) -> None:
        summary = self._review.start_wrong_only()
        self._review_stage = "card" if summary["total"] else "done"
        self._study_help.reset()
        self.changed.emit()

    @Slot()
    def reviewExit(self) -> None:
        """退出本轮。已产生的复习记录保留（不会被回滚）。"""
        self._review.exit_session()
        self._review_stage = "home"
        self._study_help.reset()
        self.changed.emit()

    # ---- AI 辅助（造句 / 同义词）
    @Slot(str)
    def reviewHelpRequest(self, mode: str) -> None:
        """点了「造句」或「同义词」。**只在答案已揭示时有效** ——

        没看到释义就让它造句，等于把「先回忆再看答案」这一步跳过去，
        卡片就退化成一本例句书了。
        """
        card = self._review.card()
        if not card.get("revealed"):
            return
        self._study_help.request(card.get("word") or "",
                                 card.get("meaning") or "", str(mode or ""))

    @Slot()
    def reviewHelpClose(self) -> None:
        """收起辅助结果（**保留缓存**：再点同一个词是秒回）。"""
        self._study_help.reset()
        self.changed.emit()

    # ---- 信号转发（ChatService 在后台线程发回来）
    def _on_chat_changed(self, *_args) -> None:
        self.changed.emit()

    def _on_test_finished(self, result: dict) -> None:
        self._last_test = dict(result)
        self._notice = result.get("message", "")
        self.changed.emit()
        QTimer.singleShot(6000, self, self._clear_notice)

    @Slot()
    def _clear_notice(self) -> None:
        if self._notice:
            self._notice = ""
            self.changed.emit()

    @Slot()
    def minimize(self) -> None:
        if self._window is not None:
            self._window.showMinimized()

    @Slot()
    def toggleMaximize(self) -> None:
        win = self._window
        if win is None:
            return
        if win.visibility() == 4:              # QWindow.Maximized
            win.showNormal()
        else:
            win.showMaximized()

    @Slot()
    def quitApp(self) -> None:
        self.launcher.quit_requested.emit()

    # ---- 设置 / 换装（QML 面板写回，走旧 LauncherWindow 的同一条写盘路径）
    @Slot(str)
    def setSkin(self, skin_id: str) -> None:
        self.launcher._on_skin_selected(skin_id)
        self.changed.emit()

    @Slot(int)
    def setMaxWords(self, value: int) -> None:
        # 档位来自 `settings_store.MAX_WORDS_CHOICES`（2026-10-19 起 8/16/32/48）：
        # 以前这里写死 `min(8, …)`，和「八条腿」耦合 —— 队列化之后 8 只是
        # **同时**踩词的腿数，不再是一次能处理的词数上限。
        # 现在再收成档位：写了 12 这种中间值也不怕，`normalize_max_words`
        # 会把它落到最近的一档，UI 上永远点得亮一个。
        self.launcher._write_settings({"max_words": normalize_max_words(value)})
        self.changed.emit()

    @Slot(int)
    def setMinConfPct(self, value: int) -> None:
        pct = max(50, min(99, int(value)))
        self.launcher._write_settings({"min_conf": pct / 100.0})
        self.changed.emit()

    @Slot(int)
    def setPetScalePct(self, value: int) -> None:
        # 走「即时写盘」分支（旧的自绘滑杆只负责呈现）。
        # 以前这里 setPetScalePct 会被 300ms 去抖拖住，
        # 导致「改完马上读 settings.json」读到的是上一次的值。
        self.launcher.set_pet_scale_pct(max(50, min(150, int(value))))
        self.changed.emit()

    @Slot(bool)
    def setAlwaysOnTop(self, value: bool) -> None:
        box = self.launcher.panel.checks.get("always_on_top")
        if box is not None:
            box.setChecked(bool(value))
        else:
            self.launcher._write_settings({"always_on_top": bool(value)})
        self.changed.emit()

    @Slot(bool)
    def setShowMeaningCard(self, value: bool) -> None:
        box = self.launcher.panel.checks.get("show_meaning_card")
        if box is not None:
            box.setChecked(bool(value))
        else:
            self.launcher._write_settings({"show_meaning_card": bool(value)})
        self.changed.emit()

    @Slot()
    def resetSettings(self) -> None:
        from settings_store import DEFAULTS
        values = dict(DEFAULTS)
        # 「恢复默认」恢复的是识词/部署这些行为参数；用户主动选过的界面主题
        # （含「跟随系统」开关）不在「捣乱参数」之列，别顺手跳回白天。
        values["theme_preset"] = self._current_theme_preset()
        values["theme_auto"] = bool(self._values_now().get("theme_auto", False))
        self.launcher._write_settings(values)
        self.launcher.panel.scale_slider.setValue(int(round(values["pet_scale"] * 100)))
        for key, box in self.launcher.panel.checks.items():
            if key in values:
                box.setChecked(bool(values[key]))
        self.launcher._on_skin_selected(values.get("skin", "white_jump_spider"))
        self._notice = "已恢复默认设置"
        self.changed.emit()
        QTimer.singleShot(3000, self, self._clear_notice)

    # ---- 轮询刷新
    def _refresh(self) -> None:
        phase = self.launcher.phase
        text, enabled = {
            "idle": ("部 署", True),
            "deploying": ("部署中…", False),
            "deployed": ("收 回", True),
            "recalling": ("收回中…", False),
        }.get(phase, ("部 署", False))
        stats = self._book.stats()
        status = self.launcher.title_bar.chip.text()
        # 学习活动变了（扫描 / 复习 / AI 提问）→ 点阵立即重画，不等用户切页
        before_key = self._activity_key
        self._activity_snapshot()
        if self._activity_key != before_key or before_key is None:
            self._touch_grids()
        values = {"phase": phase, "deployText": text, "deployEnabled": enabled,
                  "due": int(stats.get("due", 0)), "total": int(stats.get("total", 0)),
                  "status": status}
        # ---- 成就：数据够了就认领（只认领不展示；展示由 QML 的弹窗做）
        # 每个成就 ID 只会被写进 `book.achievements` 一次，所以这里反复调用
        # 不会重复弹窗；`pending()` 里 seen=False 的才会继续留在 pending。
        fresh = self._claim_achievements()
        pending_ids = tuple(row.get("id") for row in self._pending_achievements())
        changed_pending = pending_ids != self._achievement_ids
        if changed_pending:
            self._achievement_ids = pending_ids
        if values != self._values or self._values["phase"] != phase or fresh \
                or changed_pending:
            self._values = values
            self.changed.emit()

    def _claim_achievements(self) -> list:
        try:
            import activity
            return activity.claim_new(self._book)
        except Exception as error:              # noqa: BLE001
            self._log("[activity] 成就判定失败: %r" % (error,))
            return []

    def _record_app_open(self) -> None:
        """记「今天打开过」（同一天只算一次），再算一次成就。"""
        try:
            fresh = self._book.record_app_open()
            if fresh:
                self._log("[activity] 记录打开日期 %s" % time.strftime("%Y-%m-%d"))
        except Exception as error:              # noqa: BLE001
            self._log("[activity] 记录打开日期失败: %r" % (error,))
        self._activity_key = None
        self._claim_achievements()
        self.changed.emit()

    def _touch_grids(self) -> None:
        for grid in self._grids:
            try:
                grid.refresh()
            except Exception:                   # noqa: BLE001
                pass

    def _on_theme_changed(self) -> None:
        """主题热重载后的善后：让 Python 画笔也重画一遍。

        QML 那侧不需要通知 —— 它的颜色全部绑在 `theme.v` 上，重载时那个
        QVariantMap 整个换掉，绑定自然重算。但**罐子展示区**和**学习日志点阵**
        是在 Python 里 `paintEvent` 画的，它们只是「每次绘制时读一次当前值」，
        得有人催一帧，否则要等到下次尺寸变化才变。
        """
        jar = getattr(self.launcher, "jar", None)
        if jar is not None:
            try:
                jar.update()
            except Exception:                   # noqa: BLE001
                pass
        for grid in getattr(self, "_grids", ()) or ():
            try:
                grid.update()
            except Exception:                   # noqa: BLE001
                pass

    def _pending_achievements(self) -> list:
        try:
            import activity
            return activity.pending(self._book)
        except Exception:                       # noqa: BLE001
            return []

    def _on_ask_succeeded(self) -> None:
        """AI 对话成功 → 记一个学习活动日（同一天只记一次）。"""
        try:
            self._book.record_ai_ask()
        except Exception as error:              # noqa: BLE001
            self._log("[activity] 记录 AI 提问失败: %r" % (error,))
        self._activity_key = None
        self.changed.emit()

    # ---- 启动
    def set_window(self, window) -> None:
        self._window = window

    def present_window(self) -> None:
        """把 QML 启动台带到前台。

        无头控制器（`LauncherWindow`）里的 `_present()` 会把这件事委托给这里：
        用户从桌宠右键「回到启动台」时，该露出来的是 QML 窗口，而不是第二份
        旧 Widgets 界面。
        """
        window = self._window
        if window is None:
            return
        try:
            window.show()
            window.raise_()
            window.requestActivate()
        except Exception as error:              # noqa: BLE001
            self._log("[qml] 前置启动台失败: %r" % (error,))

    def run(self) -> int:
        # 样式由 main.py 在创建 QApplication 之前设好（QT_QUICK_CONTROLS_STYLE=Basic）；
        # 这里再兜底一次不影响已启动的样式选择。
        if os.environ.get("QT_QUICK_CONTROLS_STYLE") is None:
            os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
        # 主题：先建 store（会在文件缺失时落一份默认值），再注入 QML。
        # `watch=True` 让它盯着 theme.json —— 外部工具写完文件，这里 140ms 后
        # 自动重载，QML 绑定和 Python 画笔同时跟着变，不用重启启动器。
        self._theme = ui_theme.ThemeStore(watch=True, parent=self)
        self._theme.problem.connect(lambda message: self._log("[theme] %s" % message))
        self._theme.valuesChanged.connect(self._on_theme_changed)
        ui_theme.set_active(self._theme)
        self._log("[theme] %s" % self._theme.path)
        self._start_theme_follow_timer()
        self._engine = build_engine(self, self._theme, parent=self,
                                    on_warnings=self._qml_warnings)
        roots = self._engine.rootObjects()
        if not roots:
            self._log("[qml] Main.qml 加载失败")
            return 1
        self.set_window(roots[0])
        self._grids = list(roots[0].findChildren(HeatGrid))
        for grid in self._grids:
            grid.attachBook(self._book)
        self.launcher.log = self._log
        #: 「每个自然日第一次成功进入主工作状态」= QML 主窗口真的立起来了这一刻。
        self._record_app_open()
        shot = os.environ.get("LEXARA_QML_SHOT")
        if shot:
            # 全部带 self 作 context（2026-10-17）：调试窗口若在超时前被关掉，
            # 不带 context 的 singleShot 会打在已析构的 C++ 对象上。
            QTimer.singleShot(2600, self, lambda: self._shot(shot))
        panel = os.environ.get("LEXARA_QML_PANEL")
        if panel and self._window is not None:
            # 调试用：LEXARA_QML_PANEL=skins|settings 直接展开覆盖面板再截图
            QTimer.singleShot(700, self, lambda: self._open_debug_overlay(panel))
        # 调试用（只影响开发期截图，正式流程不读这两个变量）：
        #   LEXARA_QML_FAV=1        展开收藏夹（看五个分类与计数）
        #   LEXARA_QML_LEGEND=1     展开「日历颜色怎么读」弹层（验三色说明）
        #   LEXARA_QML_SIZE=980x660 指定窗口尺寸（验窄/矮窗口下的布局）
        if self._window is not None:
            if os.environ.get("LEXARA_QML_FAV"):
                self._window.setProperty("favOpen", True)
            if os.environ.get("LEXARA_QML_LEGEND"):
                QTimer.singleShot(900, self, self._open_debug_legend)
            size = (os.environ.get("LEXARA_QML_SIZE") or "").lower()
            if "x" in size:
                try:
                    width, height = (int(part) for part in size.split("x", 1))
                    self._window.resize(width, height)
                except ValueError:
                    self._log("[qml] LEXARA_QML_SIZE 解析失败: %r" % size)
        if os.environ.get("LEXARA_QML_TEST"):
            QTimer.singleShot(2600, self, self._test_flow)
        return QApplication.instance().exec()

    def _open_debug_overlay(self, panel: str) -> None:
        window = self._window
        if window is not None:
            window.setProperty("overlay", panel)

    def _open_debug_legend(self) -> None:
        """调试用：把学习日志的「颜色怎么读」弹层打开，方便截图核对。"""
        window = self._window
        popup = window.findChild(QObject, "legendPopup") if window is not None else None
        if popup is None:
            self._log("[qml] 找不到 legendPopup")
            return
        QMetaObject.invokeMethod(popup, "open")

    def _qml_warnings(self, warnings) -> None:
        for warning in warnings:
            self._log("[qml] %s" % warning.toString())

    def _test_flow(self) -> None:
        """自动化交互验证：设置弹层能开能关、AI 输入走诚实提示。"""
        self.launcher.open_sheet()
        QTimer.singleShot(1200, self, self._test_step2)

    def _test_step2(self) -> None:
        opened = self.launcher.sheet is not None
        self._log("[qml-test] 设置弹层打开=%s" % opened)
        self.launcher.close_sheet()
        self.send("hello spider")
        QTimer.singleShot(400, self, self._test_step3)

    def _test_step3(self) -> None:
        self._log("[qml-test] notice=%r" % self._notice)
        self._log("[qml-test] 阶段=%s 词库 due=%d" %
                  (self.launcher.phase, self._book.stats().get("due", 0)))
        self._test_portal()
        QApplication.instance().quit()

    def _test_portal(self) -> None:
        """自检：展示区的「镂空」必须正好盖住 JarView 的展示区。

        展示区是两层卡片（外壳 + 主卡片）上各挖的一个洞，坐标靠
        `jarItem.mapToItem()` 算。布局没算完、或者哪天有人改了展示区的边距，
        洞就会和底板错位 —— 错位不会崩，只会露出一圈卡片底色，很难靠肉眼发现。
        这里把「洞 == 展示区内缩 1px 且完全落在主卡片内」钉成自检项。
        """
        window = self._window
        item = window.findChild(QObject, "spiderJar") if window else None
        hero = window.findChild(QObject, "heroCard") if window else None
        hole = window.property("portalInHero") if window else None
        ok = False
        if item is not None and hero is not None and hole is not None:
            w, h = item.property("width"), item.property("height")
            hw, hh = hero.property("width"), hero.property("height")
            ok = (abs(hole.width() - (w - 2)) < 1.5
                  and abs(hole.height() - (h - 2)) < 1.5
                  and hole.x() >= -1 and hole.y() >= -1
                  and hole.x() + hole.width() <= hw + 1
                  and hole.y() + hole.height() <= hh + 1)
            self._log("[qml-test] portal=%dx%d@(%.1f,%.1f) 卡片=%dx%d 展示区=%dx%d"
                      % (hole.width(), hole.height(), hole.x(), hole.y(),
                         hw, hh, w, h))
        self._log("[qml-test] portal校验=%s" % ok)

    def _shot(self, path: str) -> None:
        if self._window is None:
            return
        # `LEXARA_QML_SHOT_SCREEN=1`：截**整块屏幕**而不是窗口。
        # 展示区现在是「挖洞看桌面」，`grabWindow()` 只会给出 alpha=0 的空洞，
        # 验不了「桌面到底透没透进来」，必须连背景一起截。
        if os.environ.get("LEXARA_QML_SHOT_SCREEN"):
            screen = self._window.screen()
            image = screen.grabWindow(0)
            if image.isNull():
                image = self._window.grabWindow()
        else:
            image = self._window.grabWindow()
        image.save(path)
        # 顺手把几何打出来：截图会被 DPI 放大，「像素量出来的展示区尺寸」
        # 不能直接和 QML 逻辑尺寸对比，靠这几行才对得上账。
        jar_size = self.launcher.jar.size()
        item = self._window.findChild(QObject, "spiderJar")
        item_size = ("%dx%d" % (item.width(), item.height())) if item is not None else "?"
        self._log("[qml] 截图 %dx%d dpr=%.2f item=%s 展示区=%dx%d → %s" % (
            self._window.width(), self._window.height(),
            image.devicePixelRatio() or self._window.devicePixelRatio(),
            item_size, jar_size.width(), jar_size.height(), path))
        QApplication.instance().quit()
