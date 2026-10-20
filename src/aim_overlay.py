# -*- coding: utf-8 -*-
"""瞄准覆盖层：识词完成后，蜘蛛爬到全屏透明层上，八条步足各自踩向
被挑中的单词，词的位置亮起与那条腿同色的光框。

「词框」是这一层的核心产出：每个词一只圆角**暗色玻璃牌**（`#0a1016`），
外沿一圈**与那条腿同色的辉光**，牌面上重新排一个该词（近白粗体、框高定字号）；
几何完全贴合 OCR 词本体框。腿色↔框色的对应记在 `guide["aura"]` 里，
同一个色号也写进 `item["aura"]`，释义卡左侧的色条读它 ——
**框、腿、卡片三处必然同色**，这是「哪条腿按着哪个词」的唯一线索。
没派到腿的词（够不着 / 还没轮到）只亮框、腿不伸过去 ——
宁可少踩一个，也不把腿拉成射线。

设计要点：
  · 覆盖整个虚拟桌面、整体透明、**鼠标穿透**（WA_TransparentForMouseEvents），
    显示期间用户仍能正常操作其他窗口；
  · **不会自己结束**：趴在词上这个状态一直保持，直到用户**点蜘蛛的头或身子**
    才收起、恢复成普通桌宠形态（点屏幕其它任何地方都不收，也不吞这一次点击）。
    因为整层是鼠标穿透的，Qt 收不到任何鼠标事件，这一下只能用 `WH_MOUSE_LL`
    全局钩子在消息进系统之前截一笔（见 `_install_hook`）；落在我们自己窗口
    （结果卡）上的点击不算，点词框则打开该词的释义。
  · 八词以内是**原地定位**：蜘蛛站定后身子一步都不走，全靠八条步足伸出去踩词
    （`_compact_scan` + `AIM_LEG_STRETCH_HOLD_MAX`）；超过八词才启用
    「身体沿路径一站一站走过去」的连续扫描（见下面 §8 那段）。
  · 蜘蛛本体在覆盖层上重画（`pet.hide()`），腿才能跨出小窗口；
    **注意 `spider.update()` 仍由桌宠本体的 `_tick()` 驱动**（两边共用同一个
    Spider 对象，`hide()` 不停止本体的定时器）；覆盖层自己的 `_tick()` 只负责
    「按错峰把目标下发给各腿」+ 重绘。改这块时两者都要照顾到。
  · 腿↔词的分配用 `crawler_spider.assign_reachable`（可达性硬约束 + 贪心），
    **全部是局部单位**，别再把 `unit` 乘进 `reach`（踩过坑，见该函数注释）；
  · 太靠近身体的词不让腿去踩 —— 八个词往往挤在一小块区域，
    硬派给腿只会让八条腿在身体周围挤成一团，这种词亮光框就够了。

任务书 §8（超过八条腿的词）之后，这一层多了一件事：**身体会沿路径真的走**。
以前只把腿拉长，识词时看到的是「头和身子钉在原地，只有腿在不断伸出去」，
而词一多就有半数只能「亮框不算踩到」。现在的路数（`_route` / `mover`）：

  1. 开层时按 `ScanSession.order`（阅读顺序）**一次性**规划整条路径
     （`locomotion.plan_route`）：每个词一个停靠点，够得着的词停靠点就是当前位置
     （让腿去够，别为它挪窝），够不着的词站到 `可达半径 × 0.62` 处。
     之后不再逐帧重排 —— 路径中途变向就是「蜘蛛乱跑」。
  2. `locomotion.MotionController` 逐帧推进身体（走/跳按 §3 的阈值分工），
     落点写回**唯一权威** `PetWindow.center`（`_apply_root`），
     步态引擎从中心点的逐帧差值里自己拿到位移，不需要第二条通路。
  3. 每落到一个停靠点：`note_progress()` 续一次「这批没卡住」的计时 →
     按这一站重算腿长 → 重派腿 → 停在原地等这一站的词落定（§8.2.6 的
     「落脚/扫描确认」，见 `_contact_stop` / `_release_contact`）。
     **必须等**：脚尖盯的是屏幕上的词在体坐标系里的投影，身体一动投影就漂，
     落位判据一直不成立（实测 8 词长条只有 2 个真被踩到）。
  4. 队列的时钟 `_queue_now` 只在**身体停着**的时候推进（见 `_tick`）：
     两处时钟口径不一致，第一批会被立刻判卡死，重试三轮后整批 failed。
  5. 暂停/继续/关闭都要连 `mover` 一起管（§8.4），否则覆盖层收了身体还在后台飘。
"""

from __future__ import annotations

import ctypes
import math
import time
from ctypes import wintypes

from PySide6.QtCore import (QPointF, QPoint, QRect, QRectF, QSizeF, Qt,
                            QTimer)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF,
                           QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

import crawler_spider as CS
import locomotion
# 队列层不依赖 Qt（见 `scan_session` 模块头），这里顶层 import 没有循环风险；
# `LEG_COUNT` 在 `_hint_text` / `__init__` 两处都要用，所以不放函数里。
from scan_session import (ACTIVE, COMPLETED, FAILED, LEG_COUNT, SKIPPED,
                          ScanSession)
from spider_painter import SpiderPainter, SpiderState

#: 「这个词已经处理完」的三个终态：踩住、够不着只亮框、失败了。
#: >8 词的连续扫描只在词变成这三种之一时才亮它的框（见 `_reveal`），
#: 也就是「腿落下去，框跟着亮起来」。
DONE_STATES = (COMPLETED, SKIPPED, FAILED)

ACCENT = QColor(47, 107, 255)

#: 词框相对 OCR 给出的**词本体**框再放宽多少逻辑像素。
#: 任务书 §4 写死了上限：只允许 1~2px 的可配置边距。原来这里是
#: `pad_x, pad_y = 9.0, 5.0` 再加一圈「按字号估的宽高」，
#: 于是框比词宽出一整截、还以中心点为准飘在词的上方，看着像单词上凭空多了一张卡片。
WORD_BOX_PAD = 1.5

#: 框内生成词的墨色：近白（旧版词框就是 `#f2fffd`，压在暗色牌面上最清楚）。
WORD_INK = QColor(242, 255, 253)

#: 词框牌面的暗色底（旧版 `#0a1016` @210）。框里要写我们生成的词，
#: 底下原文必须被压住，所以 alpha 抬到 236 —— 再透一点就会看到
#: 「原文 + 生成词」两种字形叠在一起。
BOX_ALPHA = 236

#: 字号系数：**由框高反推**。框高 = OCR 词本体高 + 2×`WORD_BOX_PAD`，
#: 而字面高约占 0.75em，1.30 是「字面刚好顶满框高」的那一档。
#: ★ 这个系数是词框与词的唯一纽带：框变高（词大），字就跟着变大，反方向也是。
WORD_TEXT_FIT = 1.30

#: 字号下限：再小就没法读了，宁可让极小的词框留白。
WORD_TEXT_MIN_PX = 7

#: 是否给「够不着、只亮框」的词画一条从蜘蛛牵过去的发光引导线。
#: **默认关**：八个词常挤在一小块区域，这些线会互相交叉织成一张网，
#: 看起来就是「八条腿汇成一把射线」——正是之前被吐槽的那个观感。
#: 想要的话改成 True 即可（`_draw_guide` 是二次曲线 + 途中渐隐，不会糊成一片）。
GUIDE_LINES = False

#: 词框是否改用「踩它那条腿」的颜色。
#:
#: 现在是**唯一的着色方式**（旧版视觉契约）：框、腿、释义卡左边的小色条
#: 三处必须是同一个色号，用户就是靠这个对应关系一眼看出「哪条腿按着哪个词」。
#: 关掉它会让八个框一起退回品牌蓝，等于把这条语义链打断 —— 别关。
LEG_TINTED_BOXES = True


def _log(message: str) -> None:
    """运行日志（和桌宠本体用同一个文件，便于连着看时间线）。"""
    try:
        import os
        from wordbook import app_data_dir
        with open(os.path.join(app_data_dir(), "run.log"), "a",
                  encoding="utf-8") as handle:
            handle.write("%s %s\n" % (time.strftime("%H:%M:%S"), message))
    except Exception:                            # noqa: BLE001
        pass


_FONT_CACHE: dict = {}


def font_(size: int, bold: bool = False) -> QFont:
    """默认字族 + 指定字号（按 (size, bold) 缓存）。

    以前每帧每个词框都新建 QFont + QFontMetricsF —— 全屏覆盖层 60fps 下
    每秒要建几十上百个，纯属白给。QFont 是值语义、QPainter.setFont 内部拷贝，
    共享同一实例没有副作用。

    别写死 ``Microsoft YaHei UI``：脱离桌面会话（离屏渲染 / 某些打包环境）时
    枚举不到这个字族，Qt 会退化成一个缺字形的字体，中文全画成豆腐块。
    系统默认字族在中文 Windows 上本来就是雅黑，观感一致。
    """
    key = (int(size), bool(bold))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = QFont()
        font.setPointSize(key[0])
        font.setBold(key[1])
        _FONT_CACHE[key] = font
    return font


def union_geometry() -> QRect:
    """所有屏幕拼接后的逻辑几何（覆盖层要罩住整个桌面）。"""
    from PySide6.QtGui import QGuiApplication
    result = QRect()
    for screen in QGuiApplication.screens():
        result = result.united(screen.geometry())
    return result


# ---------------------------------------------------------------- 常量

#: 瞄准时蜘蛛相对平时的放大倍数。
#: 平时是桌面小宠物，但趴到文字上时要够得着一片词群 —— 腿长 = full×unit，
#: 不放大就只有一半的词踩得到。放大只在瞄准层里生效，本体窗口不受影响。
AIM_SCALE_BOOST = 1.35

#: 瞄准时八条步足的腿长**上限**倍率（触须不变）。
#:
#: 「放大倍数」和「腿长倍率」是两件事，别混：
#:   · `AIM_SCALE_BOOST` 放大的是绘制用的 `unit`，**身子和腿等比放大** ——
#:     像素可达半径确实变大，但腿相对身体的比例没变，看着只是「更大的蜘蛛」。
#:   · 腿长倍率动的是几何本身，腿**相对**身子变长 —— 够得更远，也更像蛛形纲。
#:
#: **不是每次都拉满**：进场时按「最远的那个词」算需要多少（`_needed_stretch`），
#: 够用即可。词就在嘴边时还硬拉长，只会把腿拉成射线。
#: 这个常量是那次计算的上限：1920 宽屏下后足可达半径 335px → 537px。
#:
#: 上界别贪：腿长与静止跨度是 1.5 倍关系（`full = 1.2×reach`，静止只伸
#: `0.8×reach`），想要 600px 的可达半径，静止跨度就得 800px —— 整只蜘蛛
#: 会占掉半个屏幕。1.6 是「够得着」和「不吓人」之间的折中。
#:
#: ★ 这个上限只管**会走位的扫描**（超过八词、身体沿路径一站一站走的那种）。
#:   八词以内的「原地定位」另有一档，见 `AIM_LEG_STRETCH_HOLD_MAX`。
AIM_LEG_STRETCH_MAX = 1.6

#: 八词以内（`_compact_scan`）的腿长上限。
#:
#: 这个模式的产品语义是「蜘蛛选好位置后**身子不动**，全靠腿伸出去定位」，
#: 所以它没有「身体走过去」这条兜底路径 —— 够不着就是真的够不着。
#: 于是腿必须给得比走位模式更长：一片横跨 1400px 的词群，站在原地只靠
#: 1.6 倍腿（≈450px 半径）能踩到的不到一半，剩下的词会被反复判
#: 「够不着」→ 重开批次 → 腿重新派，用户看到的就是「根本没保持住状态」。
#:
#: 2.6 是实测下来的折中：1920 宽屏里 1400px 见方的选区基本都能罩住，
#: 而腿长到 2.6 倍时仍然读得成「一只八条腿张开的蜘蛛」而不是八根射线
#: （射线是静止跨度也跟着无限拉长才会出现的观感，`set_leg_stretch` 会
#: 同步放大静止位半径，八只脚各自踩着自己的方向，不会并到一起）。
AIM_LEG_STRETCH_HOLD_MAX = 2.6

#: 可达判定用的比例。**必须和 `CS.assign_reachable()` 的 `max_frac` 默认值一致** ——
#: 那个函数用 `full × 0.92` 决定「这个词派不派腿」，这里算需要拉多长时按同一个
#: 口子算，才不会出现「拉长了却仍然够不着」的临界误差。
ASSIGN_REACH_FRAC = 0.92

#: 算出来的倍率再乘一点余量。不加的话会出现「算出来的可达半径正好等于词距」的
#: 临界情形，派不派腿由浮点末位决定 —— 实测 400px 的八词环只派到 2 条腿。
#: 8% 的余量足够跨过这个坎，又不会让腿看起来比需要的长。
STRETCH_MARGIN = 1.08

#: 兜底：全局钩子装不上时（极少数环境 / 权限受限）就没法靠「再点一下」退出，
#: 退回定时关闭，免得用户被永久钉在这个状态里出不来。正常情况下永不触发。
AIM_FALLBACK_MS = 60_000


# ---------------------------------------------------------------- 全局鼠标钩子
#
# 覆盖层是「全屏 + 鼠标穿透」的，点击会径直穿到下层窗口，Qt 一个鼠标事件都
# 收不到 —— 所以「再点一下退出」这件事只能绕到系统那层去截。
# `WH_MOUSE_LL` 是**低级**钩子：它不注入别的进程，只在消息进入系统之前
# 给安装它的线程看一眼。安装它的线程必须有消息循环，这里是 Qt 主线程，
# 事件分发器一直在 `PeekMessage`，所以回调会正常触发。
#
# 两个必须守住的坑：
#   · 回调对象（`HOOKPROC` 实例）**必须自己留一份引用**。ctypes 不会帮你持有，
#     回调被 GC 掉之后下一次鼠标事件就是一段野指针调用 —— 直接崩进程。
#   · 回调里**不要直接关窗口**。它跑在系统消息泵里，此刻正在拆消息；
#     只记一笔，回到事件循环再收（`QTimer.singleShot(0, ...)`）。

WH_MOUSE_LL = 14
HC_ACTION = 0

WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_NCLBUTTONDOWN = 0x00A1
WM_NCRBUTTONDOWN = 0x00A4

#: 「点一下」的标准：按下就收，不等抬起 —— 等抬起的话双击、拖拽也会被算进去，
#: 而且按住不放的那段时间蜘蛛一直卡在瞄准态。
BUTTON_DOWN_MSGS = (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN,
                    WM_NCLBUTTONDOWN, WM_NCRBUTTONDOWN)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


#: LRESULT = LONG_PTR。64 位上是 64 位有符号，32 位上是 long；
#: 写死成 c_long 在 64 位上会被截断，钩子返回值一乱整个鼠标就废了。
_LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)


def _bind_user32():
    """给要用到的几个 user32 函数**显式声明签名**。

    ★ 这一步不是洁癖，是必须的：ctypes 对没声明 `argtypes` 的外部函数，
      默认把 Python 整数按 **32 位 `c_int`** 传。64 位进程的窗口句柄和
      `LPARAM` 指针轻松超过 2^31，于是 `CallNextHookEx` 直接抛
      `OverflowError: int too long to convert` —— 而这个调用在钩子回调的
      try 块**外面**，异常冒出去之后 ctypes 只能返回 0，
      **整条鼠标消息链就断在钩子这儿了**：瞄准层一开，鼠标全废。
    """
    user32 = ctypes.windll.user32
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC,
                                         wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = _LRESULT
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    return user32


_USER32 = _bind_user32()

#: 瞄准时的不透明度：趴���文字上得能看见底下的词
AIM_OPACITY = 0.88


class AimOverlay(QWidget):
    """八腿踩词的全屏透明层。

    ★ 2026-10-18（任务书 §6）：**这里不再有 `[:8]` 截断**。
    选区里的词全部进 `ScanSession` 队列，覆盖层每帧问一次「该换批了吗」，
    一批最多派 `LEG_COUNT` 条腿；旧批次踩过的词**框留在原地不消失**，
    蜘蛛把腿收回来去踩下一批。所以「八条腿」是同时踩词的能力，
    不是能处理多少个词的上限 —— 以前第 9 个词是**静默丢掉**的。
    """

    def __init__(self, pet, words, stagger: float = 0.0, session=None,
                 on_progress=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlag(Qt.WindowTransparentForInput, True)
        self.setWindowOpacity(AIM_OPACITY)

        geo = union_geometry()
        self.setGeometry(geo)
        self._offset = geo.topLeft()

        self.pet = pet
        self.spider = pet.spider
        self.painter = pet.painter
        #: 瞄准层专用缩放（比本体大）
        self.unit = SpiderPainter.unit_for_width(pet.sprite_w * AIM_SCALE_BOOST)
        #: 全部有坐标的词（**不截断**）：点词看释义、结果卡、队列都用它
        self.words = [w for w in words if w.get("screen_pos")]
        #: ── 色号 seed：进场就按词序把八色定下来 ──
        #: 词框、腿、释义卡左侧色条共用 `item["aura"]`。腿踩上来之后会被
        #: `_assign()` 改成**那条腿**的色号（框和腿必须同色），没派到腿的词
        #: 就沿用这里定下的值 —— 于是三处永远是同一个色号，且跨批次不再变色。
        for _i, _w in enumerate(self.words):
            _w["aura"] = CS.LEG_AURA[_i % len(CS.LEG_AURA)]
        #: ★ 队列的时钟走「身体已经站到词跟前之后的时间」，不是挂钟。
        #:   任务书 §8.2.6：「身体到达当前 waypoint 后，进入短暂的落脚/扫描确认
        #:   阶段，再前往下一个」。走过去的那 1~2 秒不该算进批次停留/超时，
        #:   否则远一点的批次会被 `stall` 判成「这批卡住了」而反复重开。
        self._queue_now = 0.0
        self.session = session or ScanSession(
            self.words, batch=LEG_COUNT, origin=(pet.center.x(), pet.center.y()),
            # ★ 传**惰性取值**而不是 `time.monotonic` 本身：本模块的 `time`
            #   在离线测试里会被整体换成假时钟（`test_aim_hold`），默认参数在
            #   定义期就绑死了真挂钟，那样「批次停留/超时」和覆盖层的帧时间
            #   各走各的表 —— 表现是模拟 60 秒却一帧都不换批。
            clock=lambda: self._queue_now)
        self.session.on_batch = self._on_batch
        self.session.on_finish = self._on_finish
        self.on_progress = on_progress
        self._scan_stats = None
        self._elapsed = 0.0
        self._last_clock = None      # 上一帧的真实时刻（算 dt 用）

        #: 各脚错峰伸出：第 i 只脚在 stagger*i 秒后才去踩它那个词
        self.stagger = max(0.0, float(stagger))
        self._pairs = []
        #: `_pairs` 的**屏幕坐标**版本（任务书 §8.1：腿的目标不能只记局部坐标，
        #: 身体一动，同一个词在体坐标系里就换了位置）
        self._pair_screen = []
        self._body_px = self._local((pet.center.x(), pet.center.y()))
        # 小批量扫描的产品语义是「蜘蛛停下、八腿定位」；只有超过八个目标
        # 才启用连续停靠路线。这样不会把 1~8 个词拆成逐词走位。
        self._compact_scan = len(self.session.order) <= LEG_COUNT
        self._guides = []
        #: 已经亮出来的框（按 `word_id` 记账）。>8 词的连续扫描里框是
        #: **踩到一个亮一个**，靠这份集合去重；见 `_reveal()`。
        self._guide_ids = set()
        #: 框内生成词的字体缓存：键 = (文本, 框宽, 框高)。
        #: 字体度量不便宜，而八个词每帧都要画 —— 尺寸稳定时一次就够。
        self._word_fonts = {}
        #: 错峰计时基准：每开一批就归零到当时的 `_elapsed`，
        #: 否则第二批起 `_elapsed` 早已大于所有 delay，「一只一只伸出去」没了
        self._stagger_base = 0.0
        #: 腿长的缓动目标（见 `_on_batch` / `_ease_stretch`）
        self._stretch_target = None

        # ── 身体路径（任务书 §8）────────────────────────────────
        # 规划**一次**：词的顺序就是队列的顺序（`ScanSession.order`：行优先
        # 阅读顺序 + 行内最近邻），每个词配一个「身体停靠点」。
        # 逐帧重算路径是 §8.5 明令避免的（会抖、会原地换路线）。
        self._route = [] if self._compact_scan else locomotion.plan_route(
            [target.item for target in self.session.order],
            (pet.center.x(), pet.center.y()),
            reach_of=self._max_reach_px,
            body_radius_of=self._body_radius_px,
            threshold_of=self._jump_threshold_px)
        self._route_of = {stop["word_id"]: stop for stop in self._route}
        #: 身体已经踩过去的词（停靠点）。没踩到的词**不许**被判「够不着、只亮框」
        self._visited = set()
        self._stop_now = None
        #: 正在「落脚/扫描确认」的那一站（§8.2.6）；None = 没有要等的词
        self._contact_stop = None
        #: 这一批是不是「走到那儿才踩」—— 是的话换批计时要等身体落地
        self._walking = False
        self.mover = locomotion.MotionController(
            (pet.center.x(), pet.center.y()), on_root=self._apply_root)
        self.mover.bind_spider(self.spider)
        # 覆盖层接管根节点：桌宠自己那段位移（`_travel`）必须让位，
        # 否则两处同时写 `center`，身体会一边跳一边被拽回去。
        travel = getattr(pet, "_travel", None)
        if travel is not None:
            pet._travel = None
            pet._travel_done = None

        # ★ 必须在 `_assign()` **之前**把腿拉长：可达匹配判的是 `leg.full`，
        #   拉长之后才有更多词落在可达半径内、派得到腿。
        self.leg_stretch = self._needed_stretch()
        self._stretch_target = self.leg_stretch
        self.spider.set_leg_stretch(self.leg_stretch)
        self._guides = []
        self.session.start()      # 会回调 `_on_batch` → `_assign()` → `_cache_boxes()`

        #: 全局钩子：用来收「再点一下」
        self._hook = None
        self._hook_cb = None         # 必须自己持有，见 HOOKPROC 上的说明
        self._dismissing = False     # 已经收到那一下，正在事件循环里收尾

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        # 2026-10-17 性能：整块全屏覆盖层的全速重绘是 GPU 大户。
        # 错峰伸腿 0.06s/条、脉动周期 ~2s —— 33ms（~30fps）完全够读，
        # 重绘量直接砍半；模型 dt 用真实时钟（`_last_clock`），不跟着掉档。
        self._timer.start(33)

    # ------------------------------------------------ 批次回调
    def _apply_stretch(self, need: float) -> None:
        """把腿长抬到 `need`：**变长立刻生效，缩回去交给 `_ease_stretch` 淡出**。

        为什么必须立刻变长：`assign_reachable` 判可达用的是**当前**的 `leg.full`，
        腿还短着就派不到远词，那些词会被当成「够不着、只亮框」直接结掉 ——
        队列明明能踩到，却因为动画没走完而少踩几个，属于最难查的那种错。
        为什么缩可以缓：`set_leg_stretch` 是瞬时的，换站时往回弹一下很扎眼，
        缓动把它变成「把腿收回来」。
        """
        if need > self.leg_stretch:
            self.leg_stretch = need
            self.spider.set_leg_stretch(need)
        self._stretch_target = need

    def _on_batch(self, targets) -> None:
        """队列开了新一批：先定身体要走去哪，再算腿长、派腿、画框。"""
        # ★ 顺序很重要：**先定停靠点**，腿长才有「站在哪儿算」的基准。
        #   反过来（先按当前位置拉长、再决定要不要走过去）的观感是
        #   「腿先被拉成射线，等身体走到了又缩回来」—— 任务书 §8.3 不要这个。
        self._set_waypoint()
        self._apply_stretch(self._stretch_target)
        self._assign()
        if self.on_progress:
            self.on_progress(self.session.stats())

    def _on_finish(self, stats) -> None:
        """队列跑完（或被取消）：把统计落到日志，UI 上也有「已扫完」的依据。"""
        self._scan_stats = stats
        _log("[scan] 队列结束：识别 %d · 完成 %d · 跳过 %d · 失败 %d · 批次 %d"
             % (stats["recognized"], stats["completed"], stats["skipped"],
                stats["failed"], stats["batches"]))
        if self.on_progress:
            self.on_progress(stats)

    # ------------------------------------------------ 身体路径（任务书 §8）

    def _max_reach_px(self, _word_px=None) -> float:
        """腿**拉到上限**时能够到的半径（屏幕逻辑像素）。

        这是「身体要不要挪位置」的唯一判据：词在这个半径之内就站着让腿去够，
        在它之外才走过去（`locomotion.approach_point` 吃的就是这一个数）。

        用**最短那条步足**的半径，和 `_needed_stretch()` 的分母同一个口径 ——
        按最长的算会出现「身体没挪、腿却够不着」的死角。
        基准是 `rest_r × 1.2`（构造期的天然腿长）而不是当前的 `leg.full`：
        后者可能还带着上一次拉长的倍率，那样这个半径会跟着历史漂。
        """
        steppers = [leg for leg in self.spider.legs if not leg.palp]
        if not steppers:
            return 1.0
        return min(leg.rest_r * 1.2 * ASSIGN_REACH_FRAC
                   for leg in steppers) * self.unit * AIM_LEG_STRETCH_MAX

    def _body_radius_px(self) -> float:
        """身体从体心到**后缘**的距离（屏幕逻辑像素）。

        停靠点至少要比它远一点，否则身体直接压在词框上，原词被盖住。
        用渲染层同一套常量（`THORAX` × `THORAX_SCALE` × 皮肤的 `body_scale`），
        不要另拍一个数 —— 换皮时身体会变，判定和停靠点得跟着变。
        """
        return abs(CS.THORAX[0]) * CS.THORAX_SCALE * self.unit \
            * max(1.0, float(self.spider.body_scale))

    def _jump_threshold_px(self, _word_px=None) -> float:
        """走/跳分界（逻辑像素）。瞄准层的 `unit` 比本体大，阈值也跟着大。"""
        return locomotion.walk_jump_threshold(self.spider, self.unit)

    def _apply_root(self, root) -> None:
        """控制器算出的新位置写回**唯一权威**：`PetWindow.center`。

        桌宠的 `_tick()` 正是拿 `center` 的逐帧差值喂给步态引擎的
        （`motion=`），所以「身体真的在走」这件事不需要第二条通路：
        写中心点 → 引擎看到位移 → 脚先钉住、过阈值再迈步。
        """
        self._body_px = self._local(root)
        self.pet.center = QPoint(int(round(root[0])), int(round(root[1])))

    #: 「身体已经站在这一站上」的容差（屏幕逻辑像素）。
    #: 取控制器到达判定（`ARRIVE_PX`）的两倍：一站本身算到 8px 就算到达，
    #: 下一站又落在它 8px 内时，两段的误差要一起放过。
    STOP_ALREADY_THERE_PX = 2 * locomotion.ARRIVE_PX

    def _next_stop(self):
        """当前批次里**身体还没踩过去**的第一个词（按规划好的路径顺序）。

        ★ 必须遍历 `session.order`（阅读顺序）而不是 `current_batch()`：
        后者来自 `by_state()`，走的是 `self.targets` —— 那是 **OCR 给词的顺序**，
        和阅读顺序无关。拿它派停靠点，身体会在屏幕两头来回弹，
        而队列是按 `order` 换批的 —— 两处顺序不一致就是「蜘蛛乱跑」的真身。

        ★ 已经站在上面的一站**不算任务**，直接看下一个词。
        `approach_point` 对「够得着的词」返回的就是当前光标位置，所以一片密集词
        会产出许多个**零长度**的停靠点。留着它们的后果：身体一落地就「到达」了
        下一站，然后每一站都要等 §8.2.6 的落脚确认落定才起程 —— 8 个能并行踩完
        的词被拆成 8 次「站着不动的等待」，一次框选从 1 秒拖成 3 秒。
        这些词照样由腿处理（`_assign()` 管的是整批），少掉的只是没有意义的走位。
        """
        if self._compact_scan:
            return None
        session = getattr(self, "session", None)
        if session is None:
            return None
        active_ids = {target.word_id for target in session.current_batch()}
        rx, ry = self.mover.root
        for target in session.order:
            word_id = target.word_id
            if word_id not in active_ids or word_id in self._visited:
                continue
            stop = self._route_of.get(word_id)
            if stop is None:
                continue
            ax, ay = stop["approach_px"]
            if math.hypot(ax - rx, ay - ry) <= self.STOP_ALREADY_THERE_PX:
                continue
            return stop
        return None

    def _set_waypoint(self) -> None:
        """把身体的下一个停靠点交给控制器，并按**那个点**重算需要的腿长。

        腿长按停靠点算而不是按当前位置：不然第一批离得远，腿会先被拉成射线、
        等身体走到了又缩回来 —— 任务书 §8.3 明确不要这个效果。
        """
        stop = self._next_stop()
        self._stop_now = stop
        #: 站在这一站上等它落定（§8.2.6 的「落脚/扫描确认」），见 `_on_arrive`
        self._contact_stop = None
        if stop is None:
            self.mover.set_waypoint(None)
            self._walking = False
        else:
            self._walking = True
            self.mover.set_waypoint(stop["approach_px"],
                                    self._jump_threshold_px(stop["word_px"]))
        self._stretch_target = self._needed_stretch()

    def _on_arrive(self, stop) -> None:
        """身体落到一个停靠点：记下来、重新派腿（§8.2 的「落脚/扫描确认」）。"""
        if stop is not None:
            self._visited.add(stop["word_id"])
        # ★ 每落到一个停靠点就重置一次「这批卡住了」的计时（`ScanSession.stall`）。
        #   不重置的话：一批 8 个词散布在一片区域，身体要挨个走过去，
        #   每个停靠点上等腿落位都要零点几秒，累加起来轻松超过 `stall`（0.9s）——
        #   队列会把**还没轮到**的词一律打回 pending 重开一批，
        #   三次之后全部判 failed。表现就是「一个词都没踩到，8 个失败」。
        #   这里的语义是「队列在实质前进」，所以推进一次就续一次命。
        session = getattr(self, "session", None)
        if session is not None:
            session.note_progress()
        # ★ 落定之后**先按这一站重算腿长，再派腿**（顺序不能反：可达判据是
        #   `leg.full`，腿短着派不到词，词就被判成「够不着、只亮框」）。
        #   赶路途中不需要长腿（§8.3：远词由身体走过去解决），但到了这一站
        #   就得给够 —— 实测 4×4 词阵里就有一个词的停靠点和上一站重合，
        #   身体走到了、腿还是上一站那副长度，于是它成了唯一的「只亮框」。
        self._apply_stretch(self._needed_stretch())
        self._assign()
        if stop is None:
            self._contact_stop = None
            self._set_waypoint()
            return
        # ★ 落地之后**先别起程**（§8.2.6「进入短暂的落脚/扫描确认阶段，
        #   确认对应目标已处理，再前往下一个」）。
        #   一落地就走，腿永远追不上目标：脚尖要盯的是一个**在动的屏幕点**，
        #   身体一走它就在体坐标系里持续漂移，`leg.target_now == center`
        #   这个落位判据一直不成立 —— 实测 8 词长条只有 2 个真被踩到，
        #   剩下 6 个全被误判成「够不着、只亮框」。
        self._contact_stop = stop

    def _release_contact(self, session) -> None:
        """「落脚/扫描确认」到点了就起程（§8.2.6）。

        等的就是这一站的词被**结清**（踩到 / 判够不着只亮框 / 失败 / 被打回待办），
        结清了才把下一个停靠点交给控制器。

        为什么必须有这一段：腿的落位判据是「脚尖 == 目标点」，而目标点是
        屏幕上的词在**体坐标系**里的投影。身体一动，投影就一直漂，脚尖追不上，
        于是每一站都「到了但没踩到」。实测 8 个词一长条：只有 2 个真被踩到。
        """
        stop = self._contact_stop
        if stop is None or not self.mover.arrived:
            return
        target = session.get(stop["word_id"])
        if target is not None and target.state == ACTIVE:
            return
        self._contact_stop = None
        self._set_waypoint()

    def _advance_body(self, dt: float) -> bool:
        """推进身体一帧；正好落地的话触发一次重新派腿。"""
        before = self.mover.root
        was_moving = self.mover.moving
        self.mover.step(dt)
        if was_moving and not self.mover.moving:
            self._on_arrive(self._stop_now)
        return self.mover.root != before

    def _fit_rect(self, screen_box):
        """把「词本体」框（屏幕逻辑像素）搬到覆盖层坐标系。

        `screen_box` 由 `OcrWorker.locate` 从 OCR 的 `_snap_edges` 结果换算而来：
        先除 DPR、再加选区原点，和 `screen_pos` 走的是同一套换算 ——
        坐标系只在那一处换算，这里只做平移，不再引入第二种口径。
        """
        bx, by, bw, bh = screen_box
        return QRectF(bx - self._offset.x(), by - self._offset.y(),
                      max(4.0, bw), max(4.0, bh))

    def _cache_boxes(self) -> None:
        """把每个词框的屏幕矩形与文本尺寸算好。

        `_guides` 里的 ``to`` 是**局部坐标**，而覆盖层的 `painter.setup`
        用的是 `_body_px + unit + heading`。

        ★ 2026-10-18（任务书 §8）：身体会沿路径走，所以这三样**每帧都可能变**，
          本函数跟着 `_tick()` 每帧走一遍。词框本身钉在屏幕上不动 ——
          `fit` 来自 OCR，只是几个 `QRectF.adjusted`；量字宽那条兜底路径
          改成按需构造 `QFontMetricsF`，不然每帧白建一次字体度量。

        ★ 框的几何**优先来自 OCR 的词本体框**（`guide["fit"]`）：
        宽高都跟着词走，斜体、i/l 这类窄词、m/w 这类宽词、带标点的词，
        框都不一样大。只有拿不到词框时（旧的调用方、单元测试里的假词）
        才退化成「按字号估一只」，并且把 `fitted=False` 记下来，
        方便评测和日志区分这两条路径。
        """
        self.painter.setup(self._body_px, self.unit, self.spider.heading)
        metrics = None
        pad_x, pad_y = 9.0, 5.0
        for guide in self._guides:
            screen = guide.get("screen")
            if screen is None:
                # 旧调用方（或测试里手塞的 guide）只给了 `to`：按当前画布换回去
                screen = self.painter.to_screen(guide["to"])
            center = (float(screen[0]), float(screen[1]))
            guide["center"] = center
            guide["to"] = self.painter.to_local(center[0], center[1])
            fitted = guide.get("fit")
            if fitted is not None:
                guide["box"] = fitted.adjusted(-WORD_BOX_PAD, -WORD_BOX_PAD,
                                               WORD_BOX_PAD, WORD_BOX_PAD)
                guide["fitted"] = True
            else:
                if metrics is None:
                    metrics = QFontMetricsF(font_(11, bold=True))
                text_w = metrics.horizontalAdvance(guide["text"])
                text_h = metrics.height()
                guide["box"] = QRectF(center[0] - text_w / 2 - pad_x,
                                      center[1] - text_h / 2 - pad_y,
                                      text_w + pad_x * 2, text_h + pad_y * 2)
                guide["fitted"] = False

    # ------------------------------------------------ 几何与分配
    def _local(self, screen_point):
        return (screen_point[0] - self._offset.x(), screen_point[1] - self._offset.y())

    def _batch_words(self) -> list:
        """当前这一批（腿要踩的）词卡。没队列时退化成「全部词」。"""
        session = getattr(self, "session", None)
        if session is None:
            return self.words
        return [target.item for target in session.current_batch()]

    def _needed_stretch(self) -> float:
        """这次要拉多长腿 —— 按**站在这一站的停靠点上、还要靠腿去够的那些词**
        里最远的那个算，够用即可。

        为什么不无脑拉满：腿越长越像射线。词群本来就在嘴边时还硬拉到上限，
        等于白白把蜘蛛拉成一只长脚怪，画面反而更差。

        ★ 2026-10-18（任务书 §6）：算的是 `session.current_batch()` 而不是全部词 ——
        连续扫词时分批再定位，每一批只需要够着自己那一片，
        拿整个选区的最远距离去拉长腿，等于第一批就被拉成射线。

        算法：
        1. 每个词算出「离它最近的那条腿的髋部还有多远」（`min`），
           **比一个腿展还远的词跳过**（那些由身体走过去），剩下的取最大 ——
           这就是**必须靠腿覆盖到的距离** `worst`。
        2. 除以**最短那条腿**的可达半径 `min(天然腿长) × 0.92` —— 得到需要的倍率。
        3. 乘 `STRETCH_MARGIN`，夹到 `[1.0, AIM_LEG_STRETCH_MAX]`。

        ★ 两个「不能省」的地方，都是实测出来的：

        **不能用「离体心的距离」当 `worst`**：八条腿的髋部离体心其实都只有
        十来个局部单位，用体心距离会和髋部距离差出十几单位，正好卡在边界上。

        **分母不能用最长那条腿**：八条腿**不等长**（前足 205、中足 184、后足 219）。
        按最长腿算，倍率看着够了，但负责那几个方向的中足依然够不着 ——
        实测 400px 的八词环只派得出 **4 条腿**（分到词的全是前足/后足，
        中足一条腿都没用上，等于白长）。按最短腿算，八条腿才都有活干。

        基准用 `rest_r × 1.2`（构造期的天然腿长）而不是当前的 `leg.full`：
        后者可能还带着上一次拉长的倍率。天然腿长 = `l1 + l2 = 1.2 × reach × scale`。

        ★ 2026-10-18（任务书 §8）：量的是**站在当前位置**还差多远 —— 这个函数只在
          开批和落地重派时调用，那两处「当前位置」就是这一站的停靠点。

        ★ 2026-10-19：**八词以内（`_compact_scan`）是例外**。这个模式的产品语义是
          「站定之后身子一步不走」，没有「走过去」这条兜底 —— 所以下面那道
          「太远的词交给身体」的闸门整段跳过，上限也换成 `AIM_LEG_STRETCH_HOLD_MAX`。
          真够不着的词由 `_assign()` 当场判「只亮框」，不进重试循环。
        """
        origin = self._body_px
        self.painter.setup(origin, self.unit, self.spider.heading)
        steppers = [leg for leg in self.spider.legs if not leg.palp]
        batch = self._batch_words()
        if not steppers or not batch:
            return 1.0

        # 最短那条腿的可达半径 —— 拿它当基准，八条腿才都够得着
        shortest_reach = min(leg.rest_r * 1.2 * ASSIGN_REACH_FRAC
                             for leg in steppers)
        if shortest_reach <= 0.0:
            return 1.0

        # §8.3：「若目标不可达，应**先移动身体**」—— 所以这里只算**这一站脚下**
        # 的词：停靠点就在脚下 = 这一站不再挪，全靠腿，必须给够倍率；
        # 停靠点在别处 = 腿拉多长都没用，身体会走过去，到那一站再算。
        # 少了这道闸（只按「离得远近」筛），散布在一条长线上的 8 个词会把腿长
        # 钉死在上限 ×1.6 —— 身体明明要走到词跟前，腿却保持着够向屏幕另一头的
        # 长度，正是任务书要根除的那个「只有腿在动」的观感。
        # 没有停靠点的词（旧的直接构造调用方）退回按最大可达半径筛，
        # 那个数和 `approach_point` 判「要不要挪身体」用的是同一个口径。
        walk_limit = self._max_reach_px() / max(self.unit, 1e-6)
        rx, ry = self.mover.root
        # ★ 八词以内是「原地定位」：身体**不会**走（`_next_stop()` 直接返回 None），
        #   所以「走过去再踩」这条闸门必须整段跳过，否则远端那几个词会被当成
        #   「反正身体会走过去」而永远等不到 —— 实测 1400px 见方的八词选区，
        #   腿长因子停在 ×1.0、只派得出 4 条腿，剩下 4 个词在三次重试后判失败。
        compact = bool(getattr(self, "_compact_scan", False))
        cap = AIM_LEG_STRETCH_HOLD_MAX if compact else AIM_LEG_STRETCH_MAX
        worst = 0.0
        for word in batch:
            x, y = self._local(word["screen_pos"])
            local = self.painter.to_local(x, y)
            nearest = min(math.hypot(local[0] - leg.hip_pos[0],
                                     local[1] - leg.hip_pos[1])
                          for leg in steppers)
            if not compact:
                stop = self._route_of.get(word.get("word_id") or "")
                if stop is not None:
                    if math.hypot(stop["approach_px"][0] - rx,
                                  stop["approach_px"][1] - ry) \
                            > self.STOP_ALREADY_THERE_PX:
                        continue
                elif nearest > walk_limit:
                    continue
            worst = max(worst, nearest)

        if worst <= 0.0:
            return 1.0
        # 余量乘在倍率上（放大一点）。**不能除在分母上** —— 那样算出来的倍率更小，
        # 正好卡在「可达半径 = 词距」的临界处，派不派腿由浮点末位决定。
        return max(1.0, min(cap, worst / shortest_reach * STRETCH_MARGIN))

    def _assign(self) -> None:
        """把**当前这一批**的步足绑到够得着的词上，并把**所有**词的框画好。

        两件事必须分开（任务书 §6.1）：
          · 腿 = 只踩 `session.current_batch()`，最多八只，一批一批往前挪；
          · 框 = 队列里每一个词都有，**包括还没轮到的**（淡一档），
            所以第 9 个之后的词从头到尾都挂在屏幕上，不是「消失了」。

        `assign_reachable` 吃的是**局部单位**，所以这里先 `to_local` 把屏幕点
        换算过去；`unit` 只用于换算，不要传进可达判断（详见该函数注释）。

        ★ 词↔腿的配对**全程用 `id(cs_target)` / `word_id`，不用文本**：
        以前这里用 `bound.add(target.text)` 记「哪些词派到腿了」，
        同一句里 `the` 出现三次时，第二次之后全被当成「已分配」，
        连框都不画 —— 这正是 §6 要根除的静默丢词。
        """
        self.painter.setup(self._body_px, self.unit, self.spider.heading)

        steppers = [L for L in self.spider.legs if not L.palp]
        session = self.session
        # 没有队列（旧的直接构造调用方、单元测试里的假词表）时退化成「全部词一批踩完」
        # ★ 这里必须 `.item` 解包成 dict：`current_batch()` 给的是 `ScanTarget` 对象，
        #   而下面按 `item["screen_pos"]` 取值。WorkBuddy 2026-10-18 01:05 的 blocker
        #   就是这里 —— 契约里定的是「队列对象是 ScanTarget，词卡字段读它的 `.item`」，
        #   `_batch_words()` 早就解包了，唯独这里漏了，`test_word_box_fit` 直接 TypeError。
        batch = [target.item for target in session.current_batch()] \
            if session is not None else self.words

        cs_targets, owner = [], {}
        for item in batch:
            x, y = self._local(item["screen_pos"])
            target = CS.Target(text=(item.get("lemma") or item.get("surface") or "?"),
                               center=self.painter.to_local(x, y))
            cs_targets.append(target)
            # 词↔腿的配对全程按 `id(target)` 记账：`CS.Target` 只有 text/center
            # 两个字段，而同一批里同一个词可以出现多次，用文本当键必然撞车。
            owner[id(target)] = item

        # 只有够得着的才分配；够不着的只亮词框 —— 否则腿会被拉成射线
        pairs = CS.assign_reachable(steppers, cs_targets)

        # ★ 这一批**没派到词**的腿各自收回去（任务书 §5）。以前八条腿一律
        #   撑在静止位上，三个词就是「三条腿干活、五条腿杵着」，
        #   看着像断腿而不是像蜘蛛。这里只报意图，收/伸由 `Spider.update()`
        #   逐帧缓动；下一批重新派腿时它们又会自己伸回来。
        self.spider.set_leg_assignment(
            {steppers[pair["leg"]].index for pair in pairs})

        self.spider.targets = {}
        self._guides = []
        self._pairs = []
        self._pair_screen = []
        self._stagger_base = self._elapsed
        aura_of = {}
        for order, pair in enumerate(pairs):
            leg = steppers[pair["leg"]]
            target = cs_targets[pair["target"]]
            item = owner[id(target)]
            # 按「脚在词群里从下往上的顺序」错峰，观感更像依次伸出去按住
            delay = self.stagger * order
            word_id = item.get("word_id") or ""
            self._pairs.append((leg.index, target.center, delay, word_id))
            # ★ 同一份配对再记一条**屏幕坐标**版：身体会沿路径走（§8），
            #   局部坐标每帧都在变，只有屏幕坐标才是「这个腿踩这个词」的恒等式。
            self._pair_screen.append(
                (leg.index, self._local(item["screen_pos"]), delay, word_id))
            if word_id:
                aura_of[word_id] = leg.aura
                # ★ 框要到「落位」才亮（`_reveal()`），但色号必须**现在就定**：
                #   等到亮的时候再去查配对表，那批可能已经换掉了。
                item["aura"] = leg.aura

        # 这批里**没派到腿**的词：框照样亮。但只有「身体已经走到它跟前、
        # 腿还是够不着」才当场判「够不着、只亮框」（`pegged=False`）。
        # ★ 身体还在路上时**不能提前结掉** —— 那些词走过去就够得着了，
        #   现在结掉就是 §6 要根除的静默丢词换了个理由重演一遍。
        #   不结掉的话它会占着这一批，队列自然等身体走过去（`_queue_now`
        #   在身体移动期间不推进，见 `_tick`）。
        # ★ 八词以内的「原地定位」是例外：身体根本不会动（`_next_stop()`
        #   恒为 None），这些词永远等不到「走过去」的那一天。不在这里结掉，
        #   它们就会一直挂在 ACTIVE，0.9s 后 `stall` 把整批打回待办重开、
        #   重派腿（腿重新伸一遍）—— 表现正是用户说的「没保持住状态」，
        #   三轮之后还会被记成 failed。原地模式下这一条就是**终局**：
        #   框留着、腿不再伸，等用户点蜘蛛收起。
        if session is not None:
            for item in batch:
                word_id = item.get("word_id") or ""
                if not word_id or word_id in aura_of:
                    continue
                if self._compact_scan or word_id in self._visited:
                    session.mark_landed(word_id, pegged=False)

        # ── 词框 ──
        # ★ 2026-10-19 用户口径：**踩到一个词才出现一个框**。
        #   >8 词的连续扫描里，框不再跟着「批」一起出现（以前一开批就亮 8 只，
        #   像一组弹窗同时弹出来），而是跟着**落位**一个一个亮：
        #   这一轮只补「已经结清」的词，剩下的由 `_reveal()` 每帧补齐。
        #   ≤8 词的原地定位不分批、八条腿同时伸出去，仍然是整批一起亮。
        self._guide_ids = set()
        if session is not None and not self._compact_scan:
            done_ids = {t.word_id for t in session.targets if t.state in DONE_STATES}
            box_items = [t.item for t in session.order if t.word_id in done_ids]
        else:
            box_items = [t.item for t in session.order] if session is not None else list(self.words)
        pending_ids = {t.word_id for t in session.pending()} if session is not None else set()
        for index, item in enumerate(box_items):
            word_id = item.get("word_id") or ""
            # ── 色号只有一条来源链 ──
            # 腿踩上来的词，色号就是**那条腿**的（`aura_of` 在配对时写入）；
            # 还没派到腿的词沿用进场时定下的色号（`__init__` 里按词序 seed，
            # 与释义卡左侧色条同一个下标）。
            aura = aura_of.get(word_id) or item.get("aura") \
                or CS.LEG_AURA[index % len(CS.LEG_AURA)]
            self._add_guide(item, aura,
                            lit=0.42 if word_id in pending_ids else 1.0)

        # ★ 词框几何必须**跟着 `_assign()` 一起重算**，不能只在构造时算一次。
        #   `_guides` 每次分配都是整个重建的，而 `_draw_word_box` 读的是
        #   `guide["box"]` —— 谁来二次调一次 `_assign()`（换批次、重排路径、
        #   或测试里开 GUIDE_LINES）而没重算几何，下一帧 paintEvent 就是
        #   `KeyError('box')`：Qt 里裸抛的 Python 异常会把进程直接带崩
        #   （aim_e2e 第 6 步实测到退出码 127、日志尾部只留一个 FAIL）。
        self._cache_boxes()

    def _add_guide(self, item, aura, lit: float = 1.0) -> None:
        """给一个词挂上它的框（`_guides` + `_guide_ids` 的唯一写入点）。"""
        word_id = item.get("word_id") or ""
        # ★ 必须回写进 `item`：释义卡是另一套 UI，它读 `item["aura"]`，
        #   两边各算一次迟早会错开一位，用户看到的就是「框和卡片不同色」。
        if word_id:
            item["aura"] = aura
            self._guide_ids.add(word_id)
        x, y = self._local(item["screen_pos"])
        self._guides.append({
            # 画线用髋部：脚尖已经在词上了（`GUIDE_LINES` 默认关，见模块头）
            "from": None,
            # ★ 词的位置以**屏幕坐标**为准（`to` 只是每帧刷新的局部坐标）
            "screen": (x, y),
            "to": self.painter.to_local(x, y),
            "aura": aura,
            "text": item.get("lemma") or item.get("surface") or "?",
            #: 框里要画的是**屏幕上那个形态**（`surface`），不是词典原形。
            #: 原文 "abandoned" 被换成 "abandon" 就等于把屏幕上的句子改了。
            "surface": item.get("surface") or item.get("lemma") or "?",
            "fit": self._fit_rect(item["screen_box"])
                   if item.get("screen_box") else None,
            "line": GUIDE_LINES,
            # 还没轮到的词淡一档：一眼分得清「踩过」和「排在后面」
            "lit": lit,
        })

    def _reveal(self) -> None:
        """踩到一个词，才补上它那只框（>8 词的连续扫描）。

        以前框是跟着**批次**一次性亮出来的：一开批 8 只同时出现，和腿一条一条
        伸出去的节奏完全脱节。用户要的是「腿落下去，框跟着亮起来」。

        判据只看队列状态：`COMPLETED`（踩住 / 够不着只亮框）/ `FAILED` /
        `SKIPPED` 都算「这个词处理完了」，谁刚变成这三种之一就补谁的框。
        `_guide_ids` 去重，所以每只框只亮一次，不会随换批闪。
        """
        session = getattr(self, "session", None)
        if session is None or self._compact_scan:
            return
        revealed = False
        for index, target in enumerate(session.order):
            if target.state not in DONE_STATES:
                continue
            if target.word_id in self._guide_ids:
                continue
            item = target.item
            # 色号优先用**踩住它的那条腿**（`_assign()` 配对时就写进 item 了），
            # 没派到腿的词沿用进场时 seed 的那一色 —— 和释义卡色条同源。
            aura = item.get("aura") or CS.LEG_AURA[index % len(CS.LEG_AURA)]
            self._add_guide(item, aura)
            revealed = True
        if revealed:
            self._cache_boxes()

        # ★ 词框几何必须**跟着 `_assign()` 一起重算**，不能只在构造时算一次。
        #   `_guides` 每次分配都是整个重建的，而 `_draw_word_box` 读的是
        #   `guide["box"]` —— 谁来二次调一次 `_assign()`（换批次、重排路径、
        #   或测试里开 GUIDE_LINES）而没重算几何，下一帧 paintEvent 就是
        #   `KeyError('box')`：Qt 里裸抛的 Python 异常会把进程直接带崩
        #   （aim_e2e 第 6 步实测到退出码 127、日志尾部只留一个 FAIL）。
        self._cache_boxes()

    # ------------------------------------------------ 帧循环
    def _tick(self) -> None:
        # 按真实 dt 推进，别写死 0.016：错峰时序一旦跟着掉帧走，
        # 机器卡一下腿就慢半拍，而这里正是要「快」的地方。
        now = time.monotonic()
        if self._last_clock is None:
            self._last_clock = now
        dt = min(0.05, max(0.0, now - self._last_clock))
        self._elapsed += dt
        self._last_clock = now

        self._ease_stretch(dt)
        # ★ 身体先走，再把新位置换算出的目标下发给腿：顺序反了会有一帧
        #   「腿踩在旧位置换算出的局部坐标上」，身体一动就是几像素的错位。
        moved = self._advance_body(dt)
        self._apply_pending(repositioned=moved)
        self._settle_legs()
        # ★ 队列推进：停留计时到点就开下一批（`on_batch` → `_assign()` 重派腿）。
        #   这是「超过八个也能全部踩完」的唯一驱动源 —— 覆盖层不自己数批次。
        #
        # ★ 时钟走 `_queue_now` 而**不是挂钟**，且只在身体已经站定时推进（§8.2.6）。
        #   两件事必须成对：`ScanSession.tick()` 拿这个时刻和 `_batch_started` 比，
        #   而 `_batch_started` 也是 `clock()`（= `_queue_now`）记的。
        #   以前这里传的是 `time.monotonic()` 而 session 的 clock 已经换成了
        #   `_queue_now`（恒为 0）—— 于是 `now - _batch_started` 一上来就是
        #   「开机至今的秒数」，远超 `stall`，第一批直接被判定卡住，
        #   重试 3 轮后 **8 个词全部 failed**（实测提示条：「已全部踩完 0 个词 ·
        #   3 批 · 8 个失败」）。一张表，两处读，就是这么贵的一条教训。
        session = getattr(self, "session", None)
        if session is not None:
            # 这一站的词结清了才起程（§8.2.6）。放在时钟之前：落地那一帧就该放行。
            self._release_contact(session)
            if self.mover.arrived:
                self._queue_now += dt
            session.tick(self._queue_now)
        # 本帧刚落位的词当场补框（放在队列推进之后：换批不会把刚亮的框吞掉）
        self._reveal()
        self.update()

    def _ease_stretch(self, dt: float) -> None:
        """腿长缓动：只在「该缩」时缓，约 0.4s 收回来。

        `set_leg_stretch` 本身是瞬时的，换批时直接缩回去会让八条腿一起弹一下；
        这里把差值摊到若干帧上，观感就是「把腿收回来准备够下一个词」。
        增大不走这条路（见 `_on_batch`：可达判定要用真腿长，必须先给够）。
        """
        goal = getattr(self, "_stretch_target", None)
        if goal is None or abs(goal - self.leg_stretch) < 1e-3:
            if goal is not None and self.leg_stretch != goal:
                self.leg_stretch = goal
                self.spider.set_leg_stretch(goal)
            return
        self.leg_stretch += (goal - self.leg_stretch) * min(1.0, dt * 3.0)
        self.spider.set_leg_stretch(self.leg_stretch)

    def _apply_pending(self, repositioned: bool = False) -> None:
        """按时序把目标下发给各条腿 —— 一只一只伸出去，而不是八只一起扑。

        ★ 2026-10-18（任务书 §8.1）：局部坐标**每帧重算**。
        `self._pair_screen`（腿 i 踩屏幕上的这个词）才是恒等式；
        「哪条腿踩哪个词」不随身体移动改变，而体坐标系里的目标点必须跟着
        身体的新位置重新投影 —— 只记局部坐标的话，身体一走，八条腿会全部
        指向身后（那正是「身体不动、只有腿在伸缩」的根因）。
        """
        self.painter.setup(self._body_px, self.unit, self.spider.heading)
        targets = {}
        pairs = []
        base = getattr(self, "_stagger_base", 0.0)
        for leg_index, screen, delay, word_id in self._pair_screen:
            local = self.painter.to_local(screen[0], screen[1])
            pairs.append((leg_index, local, delay, word_id))
            if self._elapsed - base >= delay:
                targets[leg_index] = local
        self._pairs = pairs
        self.spider.targets = targets
        if repositioned:
            # 词框的 `to`（局部坐标）也跟着身体重算；框本身钉在屏幕上不动。
            self._cache_boxes()

    def _settle_legs(self) -> None:
        """把「脚尖已经落到词上」这件事回执给队列。

        队列要知道每一批什么时候踩完才敢换批（§6.3 的「每批完成后再定位下一批」），
        而只有蜘蛛自己知道腿落没落 —— 所以这里逐条比对 `leg.target_now` 和目标点。
        `crawler_spider` 在靠近到 `TARGET_EPS` 时会把 `target_now` **直接赋成目标
        元组本身**，所以判等是可靠的，不需要自己再量一遍欧氏距离。

        `mark_landed` 幂等（已完成的目标不会重复计数），所以每帧都报没事。
        """
        session = getattr(self, "session", None)
        if session is None:
            return
        base = getattr(self, "_stagger_base", 0.0)
        for leg_index, center, delay, word_id in self._pairs:
            if not word_id or self._elapsed - base < delay:
                continue
            leg = self.spider.legs[leg_index]
            if leg.target_now == center:
                session.mark_landed(word_id, pegged=True)

    # ------------------------------------------------ 「点蜘蛛」退出
    def start(self) -> None:
        """铺开覆盖层。

        **没有自动关闭**：趴在词上这个状态一直保持，由用户**点蜘蛛的头或身子**
        来收（`_hook_proc`）。点屏幕其它地方既不收也不吞。
        """
        self.pet.hide()          # 蜘蛛爬到覆盖层上，本体窗口暂时让位
        self.show()
        self.raise_()
        if not self._install_hook():
            # 钩子不可用时也不能按固定时长自动关闭：大范围扫描可能需要多批
            # 定位，超时会让蜘蛛突然恢复原状、腿目标被清空。保持覆盖层常驻，
            # 直到用户明确点击蜘蛛或其它位置结束本次扫描。
            _log("[aim] 全局鼠标钩子安装失败，覆盖层保持常驻等待用户结束")

    def _install_hook(self) -> bool:
        try:
            self._hook_cb = HOOKPROC(self._hook_proc)
            handle = _USER32.SetWindowsHookExW(
                WH_MOUSE_LL, self._hook_cb, None, 0)
            self._hook = int(handle) if handle else None
        except Exception as error:               # noqa: BLE001
            _log("[aim] SetWindowsHookEx 异常: %r" % (error,))
            self._hook, self._hook_cb = None, None
        return self._hook is not None

    def _release_hook(self) -> None:
        """卸载钩子。

        必须在 `closeEvent` 里卸：钩子回调持有 `self`，只要钩子还挂着，
        这个窗口就永远不会被回收 —— 关一次漏一个，多框几次就是一串幽灵钩子。
        """
        if self._hook:
            try:
                _USER32.UnhookWindowsHookEx(wintypes.HHOOK(self._hook))
            except Exception:                    # noqa: BLE001
                pass
        self._hook = None
        self._hook_cb = None

    def _own_hwnds(self) -> set:
        """我们自己的顶层窗口。

        点在这些上面**不算**「再点一下」：结果卡上有「加入单词本」之类的按钮，
        用户在那儿点半天是想背词，不是想让蜘蛛变回去。
        """
        handles = set()
        try:
            for widget in QApplication.topLevelWidgets():
                if widget.isVisible():
                    handles.add(int(widget.winId()))
        except Exception:                        # noqa: BLE001
            pass
        return handles

    def _hwnd_at(self, l_param) -> int:
        """光标底下那个窗口的句柄（取不到返回 0）。

        单独拆一个方法是为了留出测试缝：整条链路要靠 `WindowFromPoint`
        问系统，而离屏渲染下窗口根本没有真实句柄，测不了「点在自己窗口上」
        这个分支。
        """
        try:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            return int(_USER32.WindowFromPoint(info.pt) or 0)
        except Exception:                        # noqa: BLE001
            return 0

    def _over_own_window(self, l_param) -> bool:
        hwnd = self._hwnd_at(l_param)
        if not hwnd:
            # 判不出来就当点在自己窗口上：宁可多留一会儿，也别误收。
            # 误收的代价是用户刚框完词、手一抖就回到原形态，白框一次。
            return True
        return hwnd in self._own_hwnds()

    def _logical_point(self, pt) -> tuple:
        """把全局钩子给的光标点换算成**逻辑像素**。

        `WH_MOUSE_LL` 的 `pt` 是物理像素，而 `screen_pos` / `_body_px` 全是
        Qt 的逻辑坐标（125%/150% 缩放下两者差 1.25/1.5 倍）。以前这里直接拿
        `info.pt.x` 和 `screen_pos` 比，100% 缩放的机器上恰好相等所以没人发现，
        高缩放的机器上会**点中词旁边的空白也算点词**。
        """
        try:
            dpr = float(self.devicePixelRatioF()) or 1.0
        except Exception:                        # noqa: BLE001
            dpr = 1.0
        return (pt.x / dpr, pt.y / dpr)

    def _over_spider(self, screen_point) -> bool:
        """这一点落在蜘蛛的**头或身子**上吗（只有这里才收起本次识词）。

        ★ 用画出来的形状本身判定（`Spider.hit_test`：头三角 + 头胸矩形/肚子），
          **不按半径画圆** —— 原地定位模式下腿会拉到两倍多长，按半径算会把
          半条腿甚至腿间的空白都算成「身体」，用户点屏幕中间一大片都会把
          蜘蛛收掉。腿不是命中区：用户要的是「点头或身子才回去」。

        传进来的是**屏幕逻辑坐标**，而 `_body_px` 是覆盖层局部坐标，
        所以先 `_local()` 再交给 `painter.to_local()`（后者还要除 `unit`、
        反旋转 heading）—— 坐标系别在这里混用。
        """
        bx, by = self._body_px
        lx, ly = self._local(screen_point)
        try:
            if self.spider.hit_test(self.painter.to_local(lx, ly)):
                return True
        except Exception:                        # noqa: BLE001
            pass
        # 兜底：极小皮 / 离屏环境下三角+矩形可能只有十来个像素，
        # 给一个「至少这么大」的圆，保证还点得中。
        radius = self.painter.body_radius_px(self.unit) * 0.4
        return math.hypot(lx - bx, ly - by) <= max(10.0, radius)

    def _toggle_pause(self) -> None:
        """队列的暂停 / 继续（任务书 §6.4 + §8.4）。

        ★ 2026-10-19：**不再挂在「点蜘蛛」上**。用户定的语义是「点蜘蛛的头或
        身子 = 结束本次识词、恢复原来形态」，一个点击不能既是暂停又是退出。
        方法保留给程序化调用（测试 / 将来的快捷键入口），钩子不再调它。
        暂停只冻住「换批」：在途的腿不收回、框不消失。

        ★ 任务书 §8.4 还要「暂停时身体停下」：§8 之后身体会沿路径走，
        只冻队列的话，蜘蛛会在用户以为「已经停了」的时候继续往下一个词走。
        所以这里连 `mover` 一起停；继续时把**同一个**停靠点重新交回去
        （`_stop_now` 没清，走的是同一条路，不会换目标）。
        """
        session = getattr(self, "session", None)
        if session is None:
            return
        if session.paused:
            session.resume()
            self._set_waypoint()
            _log("[scan] 继续扫描")
        else:
            session.pause()
            self.mover.cancel()
            _log("[scan] 已暂停（点蜘蛛继续）")
        self.update()

    def _word_at(self, point):
        """光标底下是哪个词框（没有返回 None）。"""
        for word in self.words:
            wx, wy = word["screen_pos"]
            text = word.get("surface") or word.get("lemma") or ""
            if abs(point[0] - wx) <= max(28, len(text) * 5) \
                    and abs(point[1] - wy) <= 18:
                return dict(word)
        return None

    def _hook_proc(self, n_code, w_param, l_param):
        """在消息进系统之前看一眼：是不是点在蜘蛛的头/身子上。

        ★ 只有**点蜘蛛**才收起（用户定的出入口）。以前是「点屏幕上任何地方
          都收起」，大范围识词时手一抖就白框一次；现在其余位置的点击一概
          放行（覆盖层是鼠标穿透的，用户该能照常点底下的窗口）。
        """
        try:
            if n_code == HC_ACTION and int(w_param) in BUTTON_DOWN_MSGS \
                    and not self._dismissing:
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                point = self._logical_point(info.pt)
                if self._over_spider(point):
                    # 点到蜘蛛的头或身子：本次识词结束，恢复识词前形态。
                    self._dismissing = True
                    QTimer.singleShot(0, self._dismiss)
                    return 1
                # 点在自己的窗口（结果卡）上：交给 Qt 处理，不当成「点蜘蛛」
                if not self._over_own_window(l_param):
                    word = self._word_at(point)
                    if word is not None:
                        # 看释义；吞掉这一下，别同时点中底下的窗口
                        QTimer.singleShot(
                            0, lambda item=word: self._explain_word(item))
                        return 1
                # 其余位置：什么都不做，让这一下照常落到下层窗口。
                # **不要**在这里收起 —— 定位完成后这个状态要一直保持。
        except Exception:                        # noqa: BLE001
            pass
        if self._hook:
            return _USER32.CallNextHookEx(wintypes.HHOOK(self._hook),
                                       n_code, w_param, l_param)
        return 0

    def _explain_word(self, item) -> None:
        from dialogs import WordResultDialog
        dialog = WordResultDialog(None, [item], self.pet.book, self.pet._mode_label())
        self.pet._keep('word_explanation', dialog)
        dialog.show()
        self.pet._place_dialog(dialog)
        dialog.raise_()

    def _dismiss(self) -> None:
        """回到事件循环之后才真正收起（钩子回调里只负责排队）。"""
        _log("[aim] 收到「再点一下」，恢复原来形态")
        self.close()

    def closeEvent(self, event) -> None:
        self._release_hook()
        self._timer.stop()
        # ★ 队列必须结清：取消会把还没轮到的词一律记成 skipped 并触发
        #   `on_finish`（日志里那句「识别 N · 完成 N · 跳过 N」就是从这儿来的），
        #   不然「用户中途关掉覆盖层」和「词被静默丢掉」在数据上长得一模一样。
        #   进度回调先摘掉：窗口正在销毁，回调那头（桌宠的提示行）不该再动它。
        session = getattr(self, "session", None)
        if session is not None:
            self.on_progress = None
            session.cancel()
        # ★ 身体也要停下：控制器一停，`PetWindow.center` 就停在最后落点，
        #   桌宠接着在那儿爬 —— 这是对的（它确实走到了那儿）。
        #   但**没停的 mover 会继续每帧写 center**，覆盖层收了它还在后台拽，
        #   表现为「桌宠自己往一个方向飘，拖回来又走」。
        mover = getattr(self, "mover", None)
        if mover is not None:
            mover.cancel()
        self.spider.clear_targets()
        # ★ 腿长必须还原。`Spider` 是**和本体共用**的实例，漏了这一步，
        #   瞄准层虽然收了，桌面上的小宠物会顶着一副长腿继续爬。
        #   放在 `clear_targets()` 之后：先把脚尖目标清掉，再缩回去，
        #   脚不会被 `limit_to_reach` 拽着走一下。
        self.spider.set_leg_stretch(1.0)
        # 逐腿折叠也要还原：`Spider` 和本体共用，漏了这一步的话，
        # 覆盖层收了、桌面上那只蜘蛛还顶着五条空髋部继续爬。
        # 这里只清**意图**（fold_target），实际收回去仍由 `update()` 缓动，
        # 所以退出动作是「腿依次伸回来」，不是「啪」地弹开。
        self.spider.set_leg_assignment(None)
        self.pet.show()
        self.pet.raise_()
        super().closeEvent(event)

    # ------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 1) 蜘蛛本体（脚尖指向词）
        state = SpiderState(dim=self.pet._build_state().dim,
                            focus=True,
                            joint_glow=1.0,
                            heading=self.spider.heading,
                            moving=False)
        self.spider.origin_px = self._body_px
        self.painter.paint(painter, self.spider, state,
                           unit=self.unit, origin_px=self._body_px)

        # 2) 引导线（只有需要时才画）
        for guide in self._guides:
            if guide.get("from") is not None and guide.get("line"):
                self._draw_guide(painter, guide)
        for guide in self._guides:
            self._draw_word_box(painter, guide)

        painter.end()

    def _hint_text(self) -> str:
        """提示条文案：出口说明 + 队列进度。

        任务书 §6.9 要「结束时给出 识别/完成/跳过/失败 计数」，
        而连续扫词进行中同样得让人知道「还剩多少」，
        否则一片淡框杵在那儿，用户无法区分「排在后面」和「丢了」。
        """
        base = "点蜘蛛的头或身子 · 恢复原来形态"
        session = getattr(self, "session", None)
        if session is None:
            return base
        stats = session.stats()
        total, done = stats["total"], stats["completed"]
        tail = ""
        if stats["box_only"]:
            tail += "　·　%d 个只亮框" % stats["box_only"]
        if stats["failed"]:
            tail += "　·　%d 个失败" % stats["failed"]
        if stats["skipped"]:
            tail += "　·　%d 个未处理" % stats["skipped"]
        if stats["cancelled"]:
            return "已停止　·　踩了 %d/%d%s　·　%s" % (done, total, tail, base)
        if stats["paused"]:
            return "已暂停　·　已踩 %d/%d" % (done, total)
        if not stats["remaining"]:
            # 队列走完了要给一句明确的「扫完」，不能只把进度停在 24/24 ——
            # 用户分不清「踩完了」和「卡住了」。
            return "已全部踩完 %d 个词 · %d 批%s　·　%s" % (
                done, stats["batches"], tail, base)
        if total > 1:
            return "%s　·　已踩 %d/%d%s" % (base, done, total, tail)
        return base + tail

    def _draw_hint(self, painter: QPainter) -> None:
        """屏幕底部一句「点蜘蛛的头或身子 · 恢复原来形态　·　已踩 8/23」。

        这个状态**不会自己结束**，不给一句常驻提示，用户会以为程序卡死了，
        或者发现不了这个出口。
        """
        text = self._hint_text()
        font = font_(12)
        # 文案会随进度变（但每批只变一次），按文本缓存尺寸，避免逐帧量字宽
        boxes = getattr(self, "_hint_boxes", None)
        if boxes is None:
            boxes = self._hint_boxes = {}
        size = boxes.get(text)
        if size is None:
            metrics = QFontMetricsF(font)
            size = QSizeF(metrics.horizontalAdvance(text) + 30,
                          metrics.height() + 16)
            if len(boxes) > 64:            # 防泄漏：文案组合是有限的，超了就是异常
                boxes.clear()
            boxes[text] = size
        box = QRectF(QPointF(0, 0), size)
        box.moveCenter(QPointF(self.width() / 2.0, self.height() - 46.0))
        painter.setFont(font)

        # 呼吸感：前 1.2 秒亮一点把眼睛引过去，之后稳定在较暗的亮度，
        # 免得一直闪反而干扰看词。
        settle = min(1.0, self._elapsed / 1.2)
        alpha = int(150 + 70 * (1.0 - settle))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 218))
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QPen(QColor(0, 102, 255, alpha), 1.2))
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QColor(26, 26, 26, min(255, alpha + 60)))
        painter.drawText(box, Qt.AlignCenter, text)

    def _draw_guide(self, painter: QPainter, guide: dict) -> None:
        """从脚尖牵向词框的弧线。

        直线汇聚起来就是「一把伞」，看着像射线；改成**垂直于连线鼓起**的二次曲线，
        再用渐变笔刷从脚尖（亮）渐隐到词框（淡），读起来才像「腿伸出去碰这个词」。
        """
        start = self.painter.to_screen(guide["from"])
        end = self.painter.to_screen(guide["to"])
        span = math.hypot(end[0] - start[0], end[1] - start[1])
        if span < 2.0:
            return

        # 垂直于连线的法向，用来做弧线鼓起
        nx, ny = -(end[1] - start[1]) / span, (end[0] - start[0]) / span
        bulge = min(72.0, span * 0.2)
        control = ((start[0] + end[0]) / 2 + nx * bulge,
                   (start[1] + end[1]) / 2 + ny * bulge)

        path = QPainterPath()
        path.moveTo(*start)
        path.quadTo(control[0], control[1], end[0], end[1])

        painter.setBrush(Qt.NoBrush)
        pen = QPen(QColor(47, 107, 255, 105), 1.2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawPath(path)

        # 词框处一个小十字，标出「这条线指的是这个词」
        painter.setPen(QPen(QColor(47, 107, 255, 120), 1.2))
        painter.drawLine(QPointF(end[0] - 5, end[1]), QPointF(end[0] + 5, end[1]))
        painter.drawLine(QPointF(end[0], end[1] - 5), QPointF(end[0], end[1] + 5))

    def _draw_word_box(self, painter: QPainter, guide: dict) -> None:
        """词框 = 暗色牌面 + 同色辉光 + 框内生成的词。

        视觉是旧版定的（用户明确要求「除了文字和框大小，其余完全还原」）：
          · 牌面 `#0a1016` 暗色玻璃，把底下原文压住；
          · 描边 1.6px，颜色 = **踩这个词那条腿的色号**（八足微光八色）；
          · 描边外一圈同色径向辉光，呼吸节奏与腿一致；
          · 框内词近白粗体，字号由框高反推。

        ★ 颜色链：`guide["aura"]` 从腿来（`_assign()` 里按配对写入），
          同一个值也写进了 `item["aura"]`，释义卡左侧色条读的就是它 ——
          框、腿、卡片三处必然同色，不能各自再算一套。

        ★ 几何只来自 `_cache_boxes()`：`box` 仍是「OCR 词本体框 ± `WORD_BOX_PAD`」，
          这里**不改宽高**；字号由 `_build_word_font()` 从框高反推，
          于是「词大 → 框大 → 字大」是一条单向链。
        """
        # 几何来自 `_cache_boxes()`（每次 `_assign()` 算好）；逐帧的只有 pulse。
        box = guide["box"]
        # 「还没轮到」的词淡一档（`_assign()` 里按队列状态给 `lit`），
        # 踩过的/在踩的满亮度。连续扫词时这一档深浅就是进度条。
        # ★ 只调「辉光 + 描边 + 字」，**牌面 alpha 恒不透明**：牌面一变透，
        #   底下的原文就会透上来，和框里生成的词叠成双影。
        lit = float(guide.get("lit", 1.0))
        tone = 0.7 + 0.3 * lit
        pulse = 0.75 + 0.25 * math.sin(self._elapsed * 3.0)
        accent = QColor(guide.get("aura") or ACCENT.name())

        radius = (min(5.0, max(2.0, box.height() / 4.0))
                  if guide.get("fitted") else 6.0)

        # ── 同色径向辉光：旧版是 `aura @0.28*pulse` 铺到整个框外沿 ──
        # 半径取框宽，光晕就正好罩住整只框；这是「发光效果」的本体，
        # 别删（删掉之后框就只剩一根硬描边，和屏幕上的文字糊在一起）。
        reach = max(6.0, box.width())
        glow = QRadialGradient(box.center(), reach)
        glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(),
                                    int(255 * 0.28 * pulse * tone)))
        glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(box.center(), reach, reach)

        # ── 牌面：暗色玻璃（`#0a1016`），alpha 固定，保证压住原文 ──
        plate = QColor(10, 16, 22, BOX_ALPHA)
        border = QColor(accent.red(), accent.green(), accent.blue(),
                        int(230 * tone))
        painter.setPen(QPen(border, 1.6))
        painter.setBrush(plate)
        painter.drawRoundedRect(box, radius, radius)

        self._draw_inside_word(painter, box, guide, tone)

    def _draw_inside_word(self, painter: QPainter, box: QRectF,
                          guide: dict, lit: float = 1.0) -> None:
        """把词画进框里，尺寸**只由框决定**（框高定字号，框宽只做收缩）。"""
        text = (guide.get("surface") or guide.get("text") or "").strip()
        if not text:
            return
        font = self._word_font(text, box)
        metrics = QFontMetricsF(font)
        ink = metrics.tightBoundingRect(text)
        advance = metrics.horizontalAdvance(text)

        painter.setFont(font)
        painter.setPen(QColor(WORD_INK.red(), WORD_INK.green(), WORD_INK.blue(),
                              int(245 * lit)))
        # 水平居中用 advance；垂直居中用**墨迹**框而不是行高 ——
        # 行高带 ascent/descent 留白，按行高居中会整体偏上几像素。
        x = box.center().x() - advance / 2.0
        base = box.center().y() - ink.top() - ink.height() / 2.0
        painter.drawText(QPointF(x, base), text)

    def _word_font(self, text: str, box: QRectF) -> QFont:
        """按「文本 + 框尺寸」缓存字体：每批八个词，逐帧重算字体度量太浪费。"""
        key = (text, int(round(box.width())), int(round(box.height())))
        cached = self._word_fonts.get(key)
        if cached is not None:
            return cached
        font = self._build_word_font(text, box)
        if len(self._word_fonts) > 256:
            # 词框尺寸理论上每批固定，超过就是异常/长跑遗留，整体清掉即可
            self._word_fonts.clear()
        self._word_fonts[key] = font
        return font

    @staticmethod
    def _build_word_font(text: str, box: QRectF) -> QFont:
        """**框 → 字号**：框高定字号，框宽只做压缩，绝不反过来撑框。

        旧版词框是「默认字族 + 粗体」（`font_(11, bold=True)`），这里沿用同一
        字族与字重，只把字号从固定 11pt 改成按框高反推 —— 于是词大框大、
        框大字也大，而字形观感和旧版一致。
        """
        # 四边各留一点内缩：字形贴到圆角上会被描边吃掉（降部尤其明显）。
        # 这不是改框，框仍然是 `box`；只是字在框里退半步。
        inner_w = max(4.0, box.width() - 6.0)
        inner_h = max(4.0, box.height() - 3.0)
        px = max(float(WORD_TEXT_MIN_PX), inner_h * WORD_TEXT_FIT)

        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(1, int(round(px))))
        metrics = QFontMetricsF(font)
        ink = metrics.tightBoundingRect(text)
        if ink.height() > inner_h > 0:
            px = max(float(WORD_TEXT_MIN_PX), px * inner_h / ink.height())
            font.setPixelSize(max(1, int(round(px))))
            metrics = QFontMetricsF(font)

        # 宽度：长词一定会比原词宽，按比例往下收。
        # 一次按比例收缩会因像素取整差 0.5~1px，量到还超就再收一档。
        for _ in range(3):
            advance = metrics.horizontalAdvance(text) or 1.0
            if advance <= inner_w:
                break
            # 向下取整：`round` 会把 23.8 抬成 24，字又比框宽出半像素
            px = max(float(WORD_TEXT_MIN_PX), float(int(px * inner_w / advance)))
            font.setPixelSize(max(1, int(round(px))))
            metrics = QFontMetricsF(font)
        return font

