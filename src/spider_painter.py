# -*- coding: utf-8 -*-
"""把 `crawler_spider` 的程序化几何画成 web-crawlers 那只蜘蛛。

画法照搬 crawler.js 的 `draw()`，只砍掉了尾巴：
    腿       髋→膝→脚 两段细线，天蓝；最后一条腿用高光色
    关节     膝与脚尖都是红点（触须更小）
    身体     圆角头胸矩形 + 朝前的头部三角 + 头顶红点
             （原版的「头→体心→腹→纺器」点链与腹部连接线已删，见 `_paint_body`）

「八足微光」的加成（不影响本体形象）：
    瞄准时每条步足额外叠一层与词框同色的辉光，关节球按状态脉动。

★ 皮肤（2026-10-16）：`original` 之外新增三套「图皮」——
  白跳蛛 / 像素蛛 / 奶蛛，只把**身体与头部**换成轻量透明 PNG，腿仍是同一套
  IK / 步态程序画的，只改颜色。四套皮肤的腿长、腿根、命中区、窗口尺寸
  **完全一致**，切换不重建 `Spider`，所以不会打断正在走的步态。

坐标：`crawler_spider` 用局部坐标（原点在体心、朝向 +x），
本模块负责按 heading 旋转、按 unit 缩放，再平移到画布上的体心位置。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QPainter, QPen, QPixmap, QPolygonF,
                           QRadialGradient)

import crawler_spider as CS


def qcolor(hex_str: str, alpha: float = 1.0) -> QColor:
    c = _parsed_color(hex_str)
    if alpha < 1.0:
        # ★ 必须返回**新实例**：QColor 是可变的，调用方（画笔、辉光）会改它，
        #   共享缓存对象会互相踩色。只有「纯解析」结果才进缓存。
        c = QColor(c)
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


#: hex → 基准 QColor 的解析缓存（每条腿每一帧都在 `QColor("#5cc1fc")`，
#: 字符串解析是最便宜也最白给的一档开销 —— 一帧 10 条腿 × 多图层能解析上百次）。
_COLOR_CACHE: dict = {}


def _parsed_color(hex_str: str) -> QColor:
    c = _COLOR_CACHE.get(hex_str)
    if c is None:
        c = QColor(hex_str)
        if len(_COLOR_CACHE) > 256:
            _COLOR_CACHE.clear()
        _COLOR_CACHE[hex_str] = c
    return c


# ============================================================ 皮肤
@dataclass(frozen=True)
class SkinSpec:
    """一套蜘蛛皮肤。

    身体/头部图片**只替换原来的几何身体**，不参与腿部 IK。
    所有皮肤共用同一套局部坐标框（`CS.THORAX` / `CS.HEAD_TRI_*`），
    因此切换皮肤不会改变腿根、步态、命中区域或窗口尺寸。

    `aiming_uses_aura = True`（默认）在瞄准时把腿染成八色词框色 ——
    这是「八足微光」的原始视觉：腿、词框、释义卡色条三处同色，
    用户就是靠这个对应关系看出「哪条腿按着哪个词」。
    皮肤若想让腿保持自己的颜色（只叠同色辉光），把它设成 False。
    """

    skin_id: str
    name: str
    body_file: str | None
    head_file: str | None
    leg: str
    leg_hi: str
    leg_outline: str
    joint: str
    aiming_uses_aura: bool = True
    #: 身体（腹部）贴图的额外放大倍数，1.0 = 严格铺满 `CS.THORAX` 框。
    #: 2026-10-17 用户要求：白跳蛛 / 奶蛛的身子看着太小，要**放大两倍**。
    #: 只放大身体，不动头、不动腿、不动命中判定（那套是几何，见 `hit_test`）。
    #: 放大锚点在身体**前缘中心**（肚子往后长，头和身体不脱节），
    #: 见 `_paint_image_body` 里的 `_body_draw_rect`。
    body_scale: float = 1.0


def _skin_dir() -> str:
    """皮肤素材目录。走 `wordbook.resource_path` 以兼容 PyInstaller 的 `_MEIPASS`。

    这里**惰性导入**（不是模块顶层）：`wordbook` 与渲染层没有依赖关系，
    但放模块顶层会让「导入画笔」顺带把词典模块也拉进来，没必要。
    """
    from wordbook import resource_path
    return resource_path("assets", "skins")


def skin_asset_path(filename: str | None) -> str | None:
    """素材文件名 → 绝对路径（没有文件名返回 None）。

    对外公开是因为「皮肤换图之后缩略图缓存要失效」这件事要看素材的
    mtime/大小（见 `launcher_qml._skin_thumb_signature`），
    而那套缓存逻辑不该自己拼一遍目录规则。
    """
    if not filename:
        return None
    return os.path.join(_skin_dir(), filename)


#: 缺省皮肤。用户明确要求**默认就是白跳蛛**（manifest 里写的是 original，
#: 以用户口径为准），所以这里不走 manifest 的 `default_skin`。
DEFAULT_SKIN = "white_jump_spider"

SKIN_SPECS = {
    "original": SkinSpec(
        "original", "原皮 · 词蛛", None, None,
        CS.COLORS["leg"], CS.COLORS["leg_hi"], CS.COLORS["body_fill"],
        CS.COLORS["joint"], True,
    ),
    "white_jump_spider": SkinSpec(
        "white_jump_spider", "白跳蛛",
        "white_jump_spider_body.png", "white_jump_spider_head.png",
        "#F2F4F7", "#FFFFFF", "#7F8790", "#8C959E",
        body_scale=1.5,
    ),
    "pixel_spider": SkinSpec(
        "pixel_spider", "像素蛛",
        "pixel_spider_body.png", "pixel_spider_head.png",
        "#242424", "#3A3A3A", "#090909", "#505050",
    ),
    "milk_spider": SkinSpec(
        "milk_spider", "奶蛛",
        "milk_spider_body.png", "milk_spider_head.png",
        "#F2C34A", "#FFE08A", "#A9791F", "#D99D2E",
        body_scale=1.5,
    ),
}

#: 稳定的展示顺序（菜单/启动台都按它排，不依赖 dict 插入序以外的任何东西）
SKIN_ORDER = ("original", "white_jump_spider", "pixel_spider", "milk_spider")


def skin_options() -> tuple[tuple[str, str], ...]:
    """给菜单/启动台用的 (skin_id, 中文名) 列表。"""
    return tuple((sid, SKIN_SPECS[sid].name) for sid in SKIN_ORDER)


def is_skin_id(value) -> bool:
    return str(value).strip().lower() in SKIN_SPECS


_OUTLINE_ALPHA_CACHE: dict = {}


def outline_alpha(leg_hex: str) -> float:
    """腿部外描边的不透明度 —— 按腿色明度分档（结果按色值缓存）。

    原皮是「深蓝描边 + 亮蓝内芯」，0.55 刚好压住边又不抢内芯。
    但**白跳蛛的腿是近白色**，而它的描边是中灰（#7F8790）：
    同样的 0.55 铺在**白色文档**上基本看不见，八条腿会断成一串灰点朝各方向散开，
    远看像屏幕上落了灰。桌宠的主战场恰恰就是白底文档/网页，所以浅色腿要更实的边。

    深色腿（像素蛛 #242424）不需要动：它在浅底上本来就靠自己的深色成形。
    """
    cached = _OUTLINE_ALPHA_CACHE.get(leg_hex)
    if cached is not None:
        return cached
    color = QColor(leg_hex)
    luminance = (0.299 * color.red() + 0.587 * color.green()
                 + 0.114 * color.blue()) / 255.0
    out = 0.55 if luminance < 0.6 else 0.88
    _OUTLINE_ALPHA_CACHE[leg_hex] = out
    return out


@dataclass
class SpiderState:
    """一帧的附加状态（几何与步态都在 `crawler_spider.Spider` 里）。"""

    #: 整体亮度 0..1
    dim: float = 1.0
    #: 思考/瞄准：关节球亮起
    focus: bool = False
    #: 关节球亮度倍率
    joint_glow: float = 1.0
    #: 朝向（弧度）。0 = 面朝右，π = 面朝左
    heading: float = 0.0
    #: 是否正在移动
    moving: bool = False
    #: 收腿系数 0..1：0 = 全伸，1 = 完全收回（只剩本体）
    leg_retract: float = 0.0


class SpiderPainter:
    """把程序化蜘蛛渲染到任意 QPainter 上。"""

    def __init__(self):
        self._unit = 1.0
        self._origin = (0.0, 0.0)
        self._cos = 1.0
        self._sin = 0.0
        #: 身体侧摆 + 起伏/压低下沉的**相对像素偏移**（由 paint() 每帧算好）。
        #: 作用于身体与髋部，脚尖不受影响（脚是钉住的）。
        #: 这里给类级默认值，是为了让 `_hip_screen()` 在 paint() 之外
        #: （比如探针脚本单独调 `_paint_legs`）也能安全取到值。
        self._sway_offset = (0.0, 0.0)
        #: 膝盖的偏移 = 侧摆全量 + 下沉的 `CS.KNEE_FOLLOW` 档（脚尖 0 档）。
        self._knee_offset = (0.0, 0.0)
        #: 身体压扁强度 0..1（`painter.scale` 用，屏幕竖直方向）。
        self._body_squash = 0.0
        self._body_heading = 0.0

        #: 当前皮肤。只影响渲染层。
        self._skin_id = DEFAULT_SKIN
        #: 素材缺省时退回原皮，记一次就不再反复查磁盘。
        self._skin_missing: set[tuple[str, str]] = set()
        #: 原始 QPixmap 按 (皮肤, 部位) 缓存；只在首次使用时从磁盘加载。
        self._skin_source_cache: dict[tuple[str, str], QPixmap | None] = {}
        #: 按最终屏幕尺寸缓存缩放结果，避免 60fps 逐帧 resize。
        self._skin_scaled_cache: dict[tuple[str, str, int, int], QPixmap] = {}
        #: QPen 缓存（2026-10-17 性能）：腿每帧要建 4~7 支笔，10 条腿 × 60fps
        #: ≈ 每秒几千次 QPen+QColor 分配。alpha 量化到 1/255、线宽量化到 0.05，
        #: 视觉无差、基数可控。
        self._pen_cache: dict = {}

    # ------------------------------------------------ 画笔缓存
    def _cached_pen(self, hex_str: str, alpha: float, width: float) -> QPen:
        key = (hex_str, min(255, max(0, int(round(alpha * 255.0)))),
               int(round(width * 20.0)))
        pen = self._pen_cache.get(key)
        if pen is None:
            pen = QPen(qcolor(hex_str, key[1] / 255.0))
            pen.setWidthF(key[2] / 20.0)
            pen.setCapStyle(Qt.RoundCap)
            if len(self._pen_cache) > 6000:
                self._pen_cache.clear()
            self._pen_cache[key] = pen
        return pen

    # ------------------------------------------------ 皮肤
    @property
    def skin_id(self) -> str:
        return self._skin_id

    @property
    def skin_name(self) -> str:
        return SKIN_SPECS[self._skin_id].name

    def set_skin(self, skin_id: str) -> SkinSpec:
        """切换皮肤。

        只改渲染层：`Spider` / `Leg` 状态、IK、步态、动画**完全不重建**，
        所以正在走路、正在瞄准时切皮肤也不会抽一下。
        """
        key = str(skin_id).strip().lower()
        if key not in SKIN_SPECS:
            raise ValueError("未知蜘蛛皮肤: %s" % skin_id)
        self._skin_id = key
        # 换皮后旧腿色的笔不会再用（键里带 hex，不会画错），只是占缓存 —— 清掉。
        self._pen_cache.clear()
        return SKIN_SPECS[key]

    def skin_spec(self) -> SkinSpec:
        return SKIN_SPECS[self._skin_id]

    def _skin_pixmap(self, kind: str, width: int, height: int) -> QPixmap | None:
        """取指定皮肤在目标尺寸下的图片；素材缺失返回 None（调用方回退原皮）。

        两级缓存：源图只从磁盘读一次，缩放结果按尺寸缓存 ——
        缩放比读盘便宜得多，但也没必要每帧做。
        """
        spec = self.skin_spec()
        filename = spec.body_file if kind == "body" else spec.head_file
        if not filename:
            return None

        key = (spec.skin_id, kind)
        if key not in self._skin_source_cache:
            path = os.path.join(_skin_dir(), filename)
            pixmap = QPixmap(path) if os.path.exists(path) else QPixmap()
            if pixmap.isNull():
                self._skin_missing.add(key)
                self._skin_source_cache[key] = None
            else:
                self._skin_source_cache[key] = pixmap

        source = self._skin_source_cache[key]
        if source is None or width <= 0 or height <= 0:
            return None

        scaled_key = (spec.skin_id, kind, int(width), int(height))
        cached = self._skin_scaled_cache.get(scaled_key)
        if cached is not None:
            return cached

        # IgnoreAspectRatio 是**刻意的**：素材已按标准框裁好
        # （身体有效区 252×152、头部 156×166），要严格铺满局部坐标框，
        # 保比例反而会留白、让不同皮肤大小不一。像素蛛用 NEAREST 会更好看，
        # 但只在缩放倍率大时才看得出差别，这里统一 Smooth 换取简单。
        scaled = source.scaled(int(width), int(height),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._skin_scaled_cache[scaled_key] = scaled
        return scaled

    def missing_assets(self) -> tuple[str, ...]:
        """缺失的素材（皮肤 id / 部位），供自检和日志用。"""
        return tuple("%s/%s" % (sid, kind) for sid, kind in sorted(self._skin_missing))

    # ------------------------------------------------ 坐标变换
    def setup(self, origin_px, unit: float, heading: float) -> None:
        self._unit = unit
        self._origin = (float(origin_px[0]), float(origin_px[1]))
        cos_h, sin_h = math.cos(heading), math.sin(heading)
        self._cos, self._sin = cos_h, sin_h

    def to_screen(self, local):
        x, y = local[0] * self._unit, local[1] * self._unit
        return (self._origin[0] + x * self._cos - y * self._sin,
                self._origin[1] + x * self._sin + y * self._cos)

    def to_local(self, px, py):
        dx, dy = px - self._origin[0], py - self._origin[1]
        return ((dx * self._cos + dy * self._sin) / self._unit,
                (-dx * self._sin + dy * self._cos) / self._unit)

    # ------------------------------------------------ 尺寸
    @staticmethod
    def max_reach() -> float:
        return max(reach for _, reach, _ in CS.LEG_DEF)

    @staticmethod
    def unit_for_width(width: float) -> float:
        """让蜘蛛**静止站姿**的宽度约等于 ``width`` 像素时的 unit。

        基准要按 REST_K（0.8）算：静止时脚尖只伸到 reach 的 0.8，
        直接拿 max_reach 当跨度会算大 1/0.8，蜘蛛会比设定小两成。
        """
        span = 2 * SpiderPainter.max_reach() * CS.BASE_SCALE * CS.REST_K
        return width / span

    def body_radius_px(self, unit: float) -> float:
        return CS.HEAD_OFF * CS.BASE_SCALE * unit * 2.0

    # ------------------------------------------------ 主绘制
    def paint(self, painter: QPainter, spider: CS.Spider, state: SpiderState,
              unit: float = None, origin_px=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        unit = spider.size if unit is None else unit
        if origin_px is None:
            origin_px = getattr(spider, "origin_px", (0.0, 0.0))
        self.setup(origin_px, unit, state.heading)

        # 渲染层是皮肤的**唯一**持有者，所以顺手把 `body_scale` 写回模型：
        # `hit_test` / `covers`（鼠标穿透）都靠它把判定框放大到画出来的大小。
        # 每帧写一次的成本可以忽略，好处是「换皮后立刻点得中」不需要额外的同步点。
        try:
            spider.body_scale = self.skin_spec().body_scale
        except AttributeError:            # 极简替身对象（探针里的 mock）没有这个字段
            pass

        dim = max(0.2, min(1.0, state.dim))
        # ★ 2026-10-22：上游是 `1.25*sqrt(SCALE)` 与 `SCALE**.6`，这里改成
        #   1.42 / **.52 —— 腿更粗、关节球更大。桌宠是要压在文档上看的，
        #   粗一档在浅底文字里才不断线；顺带把这两个直接照搬的系数换掉了。
        lw = 1.42 * math.sqrt(CS.BASE_SCALE) * unit
        dr = (CS.BASE_SCALE ** 0.52) * unit

        # 身体侧摆（垂直于朝向的偏移，局部单位）：腿的髋部跟着身体一起晃，
        # 脚钉在地上不动 → 视觉上就是躯干在腿上轻轻转移重心。
        # 注意：to_screen 返回的是绝对屏幕坐标（含 origin），
        # sway_offset 必须是**相对偏移**，所以要减去原点。
        sway = getattr(spider, "body_sway", 0.0)
        sway_abs = self.to_screen((0.0, sway))
        self._sway_offset = (sway_abs[0] - self._origin[0],
                             sway_abs[1] - self._origin[1])
        # ── 身体反馈（§9.2B/C）：走路起伏 / 蓄力压低 / 落地压缩 ──────────────
        # 三个量都只挪**画出来**的身体、髋部和膝盖，`leg.tip` 一个像素都不动 ——
        # 脚是钉子，身体从脚上方通过，视觉上就是「压下去 → 弹回来」。
        # ★ 下沉走**屏幕竖直**方向（不是体坐标 +y）：朝向朝左时体坐标的 +y 是
        #   屏幕水平方向，那样「蓄力」会变成身体横着飘出去。
        # ★ `body_bob` 在模型里已乘过体型 scale，`crouch` / `landing_compression`
        #   是 0..1 系数，乘 CS.CROUCH_SINK / CS.LAND_SINK 得局部单位 —— 两类
        #   在这里统一乘 `unit` 换像素。
        bob = getattr(spider, "body_bob", 0.0)
        crouch = getattr(spider, "crouch", 0.0)
        compress = getattr(spider, "landing_compression", 0.0)
        sink_px = (crouch * CS.CROUCH_SINK + compress * CS.LAND_SINK
                   - bob) * self._unit
        self._sway_offset = (self._sway_offset[0],
                             self._sway_offset[1] + sink_px)
        self._knee_offset = (self._sway_offset[0],
                             self._sway_offset[1] - sink_px * (1.0 - CS.KNEE_FOLLOW))
        # 压扁强度：落地那一下最重，蓄力算半档（免得蹲下时身体就瘪一半）
        self._body_squash = max(0.0, min(1.0, compress + crouch * 0.6))
        # 转弯倾斜：只作用于身体（头胸矩形），腿不倾
        self._body_heading = state.heading + getattr(spider, "lean", 0.0)

        # 用户 2026-10-16：简易阴影 —— 一枚压在脚下的柔边椭圆。
        # ★ 不随朝向旋转：影子躺在地上，不会跟着身体转。
        #   落点按实测脚位：静止时脚尖在体心下方 ~0.53×可达半径
        #   （pose 6× 实测，影子中心再压低一点点到 0.56），
        #   半宽 0.72×可达半径（八条腿是摊开的，影子要比身体宽）。
        #   ★ 折叠（leg_retract）时影子跟着收：腿收起来 = 蜘蛛离地，
        #     影子变小变淡直至消失 —— 否则折叠态脚下凭空多一团墨，
        #     `test_fold` 的 B1/B4（折叠后膝脚一个像素都不能有）会红。
        retract = max(0.0, min(1.0, state.leg_retract))
        # 逐腿折叠也算进来，但按「还伸着的那条腿」算：八条里只要还有一条
        # 完全伸着撑着地，脚下就该是完整一圈影子 —— 用平均折叠量会把影子
        # 提前收掉一半，看着像蜘蛛悬空。
        extended = max((1.0 - max(0.0, min(1.0, leg.fold)))
                       for leg in spider.legs if not leg.palp)
        spread = (1.0 - retract) * extended
        if spread > 0.01:
            reach_px = self.max_reach() * CS.BASE_SCALE * unit * CS.REST_K
            ground_y = origin_px[1] + reach_px * 0.56 * spread
            rx = reach_px * 0.72 * spread
            ry = max(1.5, rx * 0.26)
            # 淡出节奏与腿一致：前半段只收缩，后半段才淡出
            fade = 1.0 if retract < 0.5 else max(0.0, 1.0 - (retract - 0.5) * 2.0)
            shadow = QRadialGradient(QPointF(origin_px[0], ground_y), rx)
            shadow.setColorAt(0.0, QColor(0, 0, 0, int(42 * dim * fade)))
            shadow.setColorAt(0.55, QColor(0, 0, 0, int(18 * dim * fade)))
            shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(shadow))
            painter.drawEllipse(QPointF(origin_px[0], ground_y), rx, ry)

        painter.save()
        painter.setBrush(Qt.NoBrush)
        self._paint_legs(painter, spider, state, lw, dr, dim)
        self._paint_body(painter, spider, state, lw, dr, dim)
        painter.restore()

    def _hip_screen(self, leg):
        """髋部屏幕坐标 = to_screen(hip_pos) + 身体侧摆。"""
        hx, hy = self.to_screen(leg.hip_pos)
        return (hx + self._sway_offset[0], hy + self._sway_offset[1])

    # ------------------------------------------------ 腿
    def _paint_legs(self, painter: QPainter, spider: CS.Spider,
                    state: SpiderState, lw: float, dr: float, dim: float) -> None:
        aiming = bool(spider.targets)
        glow = max(0.0, min(1.0, state.joint_glow))
        retract_global = max(0.0, min(1.0, state.leg_retract))
        if retract_global >= 0.999:
            return  # 完全收回：不画腿，只剩本体
        # 收腿时腿整体往髋部缩（膝/脚 lerp 到髋），同时透明度衰减。
        # 透明度从 retract>0.5 才开始降，前半段只做收缩，后半段淡出，
        # 这样「收进去」的过程更清楚，不会一上来就半透明。
        # 全局折叠与逐腿折叠取更收的那一档：谁收得多就按谁淡出。
        leg_alpha = (1.0 if retract_global < 0.5
                     else (1.0 - (retract_global - 0.5) * 2.0))
        spec = self.skin_spec()

        for leg in spider.legs:
            # 全局折叠（右键「折叠」/无腿模式）之上再叠一层**逐腿**折叠：
            # 这一批没派到词的腿各自往自己髋部收，派到的那条照常伸着。
            retract = max(retract_global, max(0.0, min(1.0, leg.fold)))
            if retract >= 0.999:
                continue
            fade = (1.0 if retract < 0.5 else (1.0 - (retract - 0.5) * 2.0))
            hip = self._hip_screen(leg)
            knee_raw = self.to_screen(leg.knee)
            knee_raw = (knee_raw[0] + self._knee_offset[0],
                        knee_raw[1] + self._knee_offset[1])
            foot_raw = self.to_screen(leg.tip)
            knee = (knee_raw[0] + (hip[0] - knee_raw[0]) * retract,
                    knee_raw[1] + (hip[1] - knee_raw[1]) * retract)
            foot = (foot_raw[0] + (hip[0] - foot_raw[0]) * retract,
                    foot_raw[1] + (hip[1] - foot_raw[1]) * retract)
            width = lw * (0.75 if leg.palp else 1.0)
            d = dim * fade

            lit = aiming and not leg.palp
            base_hex = leg.aura if (lit and spec.aiming_uses_aura) else spec.leg

            if lit:
                # 「八足微光」：瞄准时这条腿叠一层同色辉光。
                for width_k, alpha in ((3.2, 16.0), (2.0, 34.0), (1.25, 64.0)):
                    painter.setPen(self._cached_pen(
                        leg.aura, alpha / 255.0 * d, width * width_k))
                    painter.drawLine(QPointF(*hip), QPointF(*knee))
                    painter.drawLine(QPointF(*knee), QPointF(*foot))

            # 深色外描边 + 亮色内芯：桌面上背景千变万化，只靠一根 1.5px
            # 浅蓝线会断成「红点 + 断续细线」，根本认不出是腿。
            # 描边色走皮肤：原皮是深蓝底、白跳蛛是灰描边、像素蛛近黑；
            # 不透明度还要按腿色明度分档（浅色腿用更实的边，见 outline_alpha）。
            painter.setPen(self._cached_pen(
                spec.leg_outline, d * outline_alpha(spec.leg),
                max(1.4, width * 1.9)))
            painter.drawLine(QPointF(*hip), QPointF(*knee))
            painter.drawLine(QPointF(*knee), QPointF(*foot))

            painter.setPen(self._cached_pen(base_hex, d, max(1.2, width * 1.35)))
            painter.drawLine(QPointF(*hip), QPointF(*knee))

            # 膝 → 脚（最后一条步足用高光色，照搬原版）
            shin_hex = spec.leg_hi if (leg.slot == 3 and not leg.palp) else base_hex
            painter.setPen(self._cached_pen(shin_hex, d, max(1.2, width * 1.35)))
            painter.drawLine(QPointF(*knee), QPointF(*foot))

            # 膝部红点
            joint_hex = leg.aura if (lit and spec.aiming_uses_aura) else spec.joint
            radius = (1.5 if leg.palp else 2.0) * dr
            if lit:
                halo = QRadialGradient(QPointF(*knee), radius * 3.4)
                halo.setColorAt(0.0, qcolor(leg.aura, 0.7 * d * glow))
                halo.setColorAt(1.0, qcolor(leg.aura, 0.0))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(halo))
                painter.drawEllipse(QPointF(*knee), radius * 3.4, radius * 3.4)

            painter.setPen(Qt.NoPen)
            painter.setBrush(qcolor(joint_hex, (0.55 + 0.45 * glow) * d))
            painter.drawEllipse(QPointF(*knee), radius, radius)

            # 脚尖
            painter.setBrush(qcolor(joint_hex, d))
            tip_r = (1.3 if leg.palp else 1.8) * dr
            painter.drawEllipse(QPointF(*foot), tip_r, tip_r)

    # ------------------------------------------------ 身体
    def _paint_body(self, painter: QPainter, spider: CS.Spider,
                    state: SpiderState, lw: float, dr: float, dim: float) -> None:
        """只画**头胸一块**：圆角矩形 + 头部三角（+ 压在底下的头部关节）。

        ★ 头部那颗关节点的**绘制顺序**很关键，见本函数末尾的注释：
          它必须画在身体/头部图层**之下**。

        **这里没有尾巴**。以前照搬 crawler.js，还会画「头 → 体心 → 腹 → 纺器」
        的点链（身体后面拖着两小段线 + 两个红点）以及「腹部 → 同侧 1、3 号腿髋部」
        的四条半透明连线。用户看图后的反馈是「矩形下方有个尾巴，两条线两个点，
        感觉多余」，所以整块删掉了 —— 连那四条连接线也一起删：它们的锚点就是
        被删掉的腹部，留着就变成四条线汇聚到一个看不见的点上。

        `spider.body` 里的 `abd` / `spin` 还在（模型层，`update()` 仍在阻尼跟随），
        只是不再参与绘制；将来想把尾巴加回来，照这段注释补几笔即可。
        """
        body = spider.body
        sox, soy = self._sway_offset
        origin = self.to_screen((0.0, 0.0))
        p = (origin[0] + sox, origin[1] + soy)
        head = (self.to_screen(body["head"])[0] + sox,
                self.to_screen(body["head"])[1] + soy)

        spec = self.skin_spec()

        # ---- 头部关节（点 + 思考/瞄准时的辉光）：**先画，压在身体/头部之下** ----
        # 原稿把这两笔画在最上层。那是给「深蓝头胸 + 红点」的几何皮配的关节
        # 语汇（膝、脚尖、头都是点），但图皮的头部素材画的是一张**脸**：
        # 这颗点换算过去正好落在「脸部横向 32%、垂直居中」，于是白跳蛛 /
        # 像素蛛 / 奶蛛的脸上都多出一颗来路不明的「痣」，辉光再叠一圈灰晕。
        # 压到图层下方之后，不透明的身/头素材会把它整颗盖住 ——
        # 视觉上等于没有这个点，但关节语义还留在渲染顺序里：
        # 将来哪张皮的头部素材中间是镂空的，它会正确地从底下透出来。
        # 位置落在头胸内部，所以被盖住这件事对四套皮肤都成立（几何皮的
        # 头部三角是实心填充，同样盖得住）。
        glow = max(0.0, min(1.0, state.joint_glow))
        radius = 2.2 * dr
        if state.focus:
            halo = QRadialGradient(QPointF(*head), radius * 4.0)
            halo.setColorAt(0.0, qcolor(spec.joint, 0.75 * dim * glow))
            halo.setColorAt(1.0, qcolor(spec.joint, 0.0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(QPointF(*head), radius * 4.0, radius * 4.0)

        painter.setPen(Qt.NoPen)
        painter.setBrush(qcolor(spec.joint, dim))
        painter.drawEllipse(QPointF(*head), radius, radius)

        # 头胸矩形（局部坐标随朝向旋转；转弯时额外倾斜 lean）
        painter.save()
        painter.translate(p[0], p[1])
        # ★ 压扁夹在 translate 和 rotate **中间**：QPainter 的变换是
        #   translate·scale·rotate，于是 scale 作用在屏幕轴上 —— 身体永远是
        #   「竖直压扁 + 水平鼓出」，不会朝向左走时变成横向压扁。
        if self._body_squash > 1e-3:
            painter.scale(1.0 + CS.SQUASH_SX * self._body_squash,
                          1.0 - CS.SQUASH_SY * self._body_squash)
        painter.rotate(math.degrees(self._body_heading))
        unit = self._unit
        # 头胸按 CS.THORAX_SCALE 放大：原版 18×11 是配 SCALE=1.45 调的，
        # 桌宠整体缩得比原版小，原尺寸下它只有 ~17px 宽，在浅色桌面上
        # 只剩一圈亮边看着像个白方块。放大后才是能认出「身体」的形状。
        ts = unit * CS.THORAX_SCALE
        rect = QRectF(CS.THORAX[0] * ts, CS.THORAX[1] * ts,
                      CS.THORAX[2] * ts, CS.THORAX[3] * ts)
        # 腿收回来的时候身体轻微向头部收拢（后缘往前，前缘不动 → 头不变）
        rect = self._folded_body_rect(rect, spider)
        # 头部三角的局部框。图皮按**同一个框**铺满 —— 这是「换皮不改大小」
        # 的关键：素材已按标准框裁好（身体有效区 252×152、头部 156×166），
        # 与这里的 18:11 / 17:18 比例一致，严格铺满即可。
        head_rect = QRectF(CS.HEAD_OFF * unit,
                           -CS.HEAD_TRI_HALF * unit,
                           CS.HEAD_TRI_LEN * unit,
                           2.0 * CS.HEAD_TRI_HALF * unit)

        if spec.skin_id == "original":
            self._paint_geometric_body(painter, rect, lw, dim)
        elif not self._paint_image_body(painter, rect, head_rect, dim):
            # 素材缺失 → 回退几何身体，绝不留下「一只没有身体的蜘蛛」
            self._paint_geometric_body(painter, rect, lw, dim)
        painter.restore()

    def _paint_geometric_body(self, painter: QPainter, rect: QRectF,
                              lw: float, dim: float) -> None:
        """原皮的身体：多边形腹部 + 带口器缺口的多边形头部。

        进到这里时画笔已经 translate/rotate 到体心，`rect` 也已按 unit 缩放过。
        """
        unit = self._unit

        # 先铺一层外扩的柔光，让身体在深色壁纸/浅色文档上都能看清 ——
        # 只靠一圈亮边的话，浅底上就糊成一个白方块。
        halo = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 1.15)
        halo.setColorAt(0.0, qcolor(CS.COLORS["leg"], 0.34 * dim))
        halo.setColorAt(0.6, qcolor(CS.COLORS["leg"], 0.12 * dim))
        halo.setColorAt(1.0, qcolor(CS.COLORS["leg"], 0.0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(rect.center(), rect.width() * 1.15, rect.height() * 1.7)

        # 参考用户草图：腹部是后宽前窄的盾形，头部是独立的前置多边形，
        # 下缘留一个小口器缺口。所有点仍由 rect/head 常量实时缩放，
        # 不影响腿部 IK、命中区和旋转。
        pen = QPen(qcolor(CS.COLORS["body"], dim), max(1.6, lw * 1.5))
        fill = QColor(CS.COLORS["body_fill"])
        painter.setPen(pen)
        painter.setBrush(fill)
        x0, x1 = rect.left(), rect.right()
        # 保持在原有圆角命中区的有效内接范围内，避免透明点击语义与新轮廓分离。
        y0, y1 = rect.top() + rect.height() * .10, rect.bottom() - rect.height() * .10
        body = QPolygonF([
            QPointF(x0 + rect.width() * .16, y0),
            QPointF(x1 - rect.width() * .16, y0),
            QPointF(x1, rect.center().y()),
            QPointF(x1 - rect.width() * .16, y1),
            QPointF(x0 + rect.width() * .16, y1),
            QPointF(x0, rect.center().y()),
        ])
        painter.drawPolygon(body)

        # 头部恢复为与命中区一致的三角形，尖端朝 +x（蜘蛛前进方向）。
        hx = CS.HEAD_OFF * unit
        apex = QPointF(hx + CS.HEAD_TRI_LEN * unit, 0.0)
        base1 = QPointF(hx, -CS.HEAD_TRI_HALF * unit)
        base2 = QPointF(hx, CS.HEAD_TRI_HALF * unit)
        painter.drawPolygon(QPolygonF([base1, apex, base2]))

    def _folded_body_rect(self, rect: QRectF, spider: CS.Spider) -> QRectF:
        """身体随「腿收回去多少」**朝头部等比缩小**：前缘（靠头那侧）不动。

        任务书 §6 的口径：折叠时身体/腹部略微缩短并向头部收拢，而头部的
        尺寸与位置保持不变。锚点选前缘正好满足这两条 —— 头框 `head_rect`
        是另一套常量算出来的，这里根本不碰它。

        ★ 2026-10-19：以前只把后缘往前挪（宽 -12%、高不变），观感是「肚子
          被压扁」而不是「缩回脑袋后面」。现在**宽高一起按同一个倍率缩**，
          不动点仍在前缘中心 —— 后缘往前、上下往中轴收，整块身子朝着头
          那侧缩进去。`_body_draw_rect`（皮肤放大）也锚在前缘，两步合成后
          等价于「以 x1 为不动点缩 `(1-BODY_FOLD_SHRINK×fold)×body_scale` 倍」。

        命中判定在 `crawler_spider._in_thorax` 里读同一个常量、同一个不动点，
        所以缩进去的那一段不会留下「看不见却点得中」的死角。
        """
        # 逐腿折叠（覆盖层没派到词）与**右键折叠**取较大者，见 `Spider.fold_depth`
        fold = max(0.0, min(1.0, getattr(spider, "fold_depth", 0.0)))
        if fold <= 1e-4:
            return rect
        keep = 1.0 - CS.BODY_FOLD_SHRINK * fold
        w = max(1.0, rect.width() * keep)
        h = max(1.0, rect.height() * keep)
        # 前缘不动、垂直居中：缩放中心 = (right, center.y)
        return QRectF(rect.right() - w, rect.center().y() - h / 2.0, w, h)

    def _body_draw_rect(self, rect: QRectF) -> QRectF:
        """按 `SkinSpec.body_scale` 把身体框放大，锚点=前缘中心（朝头那一边）。"""
        scale = float(getattr(self.skin_spec(), "body_scale", 1.0) or 1.0)
        if abs(scale - 1.0) < 1e-6:
            return rect
        w, h = rect.width() * scale, rect.height() * scale
        # 前缘（局部 +x，也就是头那侧）不动，身体往后、向两侧长。
        # 这里用的是**局部坐标**：画笔已经 translate+rotate 过，rect 本身
        # 与朝向无关，right 边永远对应「朝头」那一侧。
        return QRectF(rect.right() - w, rect.center().y() - h / 2.0, w, h)

    def _paint_image_body(self, painter: QPainter, rect: QRectF,
                          head_rect: QRectF, dim: float) -> bool:
        """图皮的身体：把身体/头部 PNG 铺进原几何的同一个局部框。

        返回 False 表示素材不可用（调用方会回退几何版）。
        躯干先画、头部后画，交叠处的层次和原版一致。

        ★ 图皮**不铺那层蓝色柔光**：柔光是为「深色身躯 + 一圈亮蓝边」配的，
          套在白色/黄色身上会糊出一圈脏边。图皮的立体感由素材自己的
          描边和阴影提供。浅底上认不认得出，靠的是素材里的灰描边。
        """
        body_pix = self._skin_pixmap("body", max(1, round(rect.width())),
                                     max(1, round(rect.height())))
        head_pix = self._skin_pixmap("head", max(1, round(head_rect.width())),
                                     max(1, round(head_rect.height())))
        if body_pix is None or head_pix is None:
            return False

        # 身体放大（`SkinSpec.body_scale`）。锚点取**前缘中心**而不是几何中心：
        # 肚子往前长会把头整个吞进去（头框 30..72.5 落在放大后的身体里），
        # 往后长才是「腰粗了」的观感，头和躯干也还连在一起。
        # 贴图按放大后的尺寸重新取一张（`_skin_pixmap` 有按尺寸的缓存），
        # 所以放大不会糊 —— 不是把小图拉大，而是按目标像素重采样。
        body_rect = self._body_draw_rect(rect)
        if not body_rect.isNull() and (body_rect.width() != rect.width()
                                       or body_rect.height() != rect.height()):
            bigger = self._skin_pixmap("body", max(1, round(body_rect.width())),
                                       max(1, round(body_rect.height())))
            if bigger is not None:
                body_pix, rect = bigger, body_rect

        opacity = max(0.2, min(1.0, dim))
        painter.setOpacity(opacity)
        painter.drawPixmap(
            rect, body_pix,
            QRectF(0.0, 0.0, float(body_pix.width()), float(body_pix.height())))

        # 用户 2026-10-16：除原皮外，所有图皮的头部素材**逆时针转 90°** 再铺。
        # 做法：把画笔绕头框中心转 -90°（Qt 的 y 轴朝下，正角是顺时针），
        # 再画一个**宽高互换**的框 —— 转回去之后正好落在原来的头框里，
        # 「换皮不改大小」的契约不动（几何指纹测试照旧）。
        center = head_rect.center()
        w, h = head_rect.width(), head_rect.height()
        painter.save()
        painter.translate(center.x(), center.y())
        painter.rotate(-90.0)
        painter.translate(-center.x(), -center.y())
        painter.drawPixmap(
            QRectF(center.x() - h / 2.0, center.y() - w / 2.0, h, w),
            head_pix,
            QRectF(0.0, 0.0, float(head_pix.width()), float(head_pix.height())))
        painter.restore()
        painter.setOpacity(1.0)
        return True

    # ------------------------------------------------ 命中
    def hit_test_px(self, px: float, py: float, spider: CS.Spider, unit: float):
        return spider.hit_test(self.to_local(px, py))
