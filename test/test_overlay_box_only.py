# -*- coding: utf-8 -*-
"""词框「框 + 框内生成词 + 发光」回归测试。

2026-10-19 起，词框不再只是一只空描边框：**框里画一个我们生成的词**。
视觉是旧版《八足微光》那一套：暗色玻璃牌面 + 近白粗体字 + 1.6px 描边
+ 同色径向辉光，描边颜色 = **踩住这个词那条腿**的颜色。

要守住的规矩因此从「只出现一次原词」变成了**「同一个词只出现一次」**：
框内必须有字，但底下原词必须被牌面盖住，否则就是原文 + 生成词叠在一起的重影。

五道闸：
    ① 调用侧：每个词**恰好画一次**，且画的是屏幕上的 `surface`（不是词典原形）；
    ② 像素侧：牌面够实（暗色、alpha 高），并且真的有近白字形像素；
    ③ 发光：框外沿有 aura 色的光环（辉光别又被删掉）；
    ④ 同色：`guide["aura"]` == `item["aura"]`（框 / 腿 / 释义卡色条同一色号）；
    ⑤ 尺寸：字号由**框高**反推 —— 框等比放大，字号跟着放大，宽度不溢出。

★ 不要设 `QT_QPA_PLATFORM=offscreen`：离屏平台没有字体数据库，
   `render()` 出来的像素不可信（见 `test_word_box_fit.py` 同段说明）。

运行：  python test/test_overlay_box_only.py
"""

from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QPoint, QRect, QRectF, Qt           # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter            # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-56s %s" % ("ok" if ok else "FAIL", name, detail))


class StubPet:
    """只提供 AimOverlay 需要的字段，不建真桌宠（真桌宠会拉起定时器）。"""

    def __init__(self):
        import crawler_spider as CS_
        from spider_painter import SpiderPainter
        self.sprite_w = 360.0
        self.spider = CS_.Spider(size=1.0)
        self.painter = SpiderPainter()
        self.center = QPoint(500, 500)

        class _Bubble:
            def hide_now(self):
                pass

        self.bubble = _Bubble()

    def _build_state(self):
        class _S:
            dim = 1.0
        return _S()

    def _mode_label(self):
        return "cet6"

    def _place_dialog(self, *a, **k):
        pass

    def char_rect(self):
        return QRect(480, 480, 40, 40)

    def show(self):
        pass

    def raise_(self):
        pass


# 词表：既有宽词也有窄词，都带 OCR 词本体框（`screen_box`），走 `fitted` 分支。
# 第三条刻意让 surface != lemma：框里必须画屏幕上那个形态。
WORDS = [
    {"lemma": "committee", "surface": "committee",
     "screen_pos": (700.0, 180.0), "screen_box": (640.0, 168.0, 122.0, 26.0)},
    {"lemma": "i", "surface": "i",
     "screen_pos": (900.0, 180.0), "screen_box": (896.0, 168.0, 8.0, 26.0)},
    {"lemma": "abandon", "surface": "abandoned",
     "screen_pos": (1100.0, 180.0), "screen_box": (1030.0, 168.0, 140.0, 26.0)},
]

from aim_overlay import AimOverlay, BOX_ALPHA, WORD_TEXT_FIT   # noqa: E402

overlay = AimOverlay(StubPet(), WORDS, stagger=0.0)
overlay._timer.stop()          # 只要一次确定性重绘，不要定时器在旁边抢帧

# ---------------------------------------------------------------- ① 调用侧
print("\n[①] drawText 调用：每个词只画一次，且画的是屏幕形态")

records = []
real_draw_text = QPainter.drawText


def _draw_text(*args, **kwargs):
    """记下 drawText 的文本参数，再转给真实现（后面的像素检查看不到假画）。"""
    for a in args:
        if isinstance(a, str):
            records.append(a)
            break
    return real_draw_text(*args, **kwargs)


QPainter.drawText = _draw_text
try:
    img = QImage(int(overlay.width()), int(overlay.height()),
                 QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    overlay.render(img)
finally:
    QPainter.drawText = real_draw_text

texts = [t for t in records if t.strip()]
print("      drawText →", texts)

for word in WORDS:
    surface = word["surface"]
    check("「%s」在框里画了恰好一次" % surface,
          texts.count(surface) == 1, "→ 出现 %d 次" % texts.count(surface))

check("画的是 surface 不是 lemma（abandoned ≠ abandon）",
      "abandoned" in texts and "abandon" not in texts,
      "→ records 里的词：%s" % [t for t in texts if t not in ("再点一下",)])

# 状态提示不在这一层画（`_draw_hint` 由别处驱动），这里只守「别多画东西」
extra = [t for t in texts if t not in [w["surface"] for w in WORDS]]
check("除了词本身没有多画文案", not extra, "→ %s" % (extra or "无"))

# ---------------------------------------------------------------- ② 像素侧
print("\n[②] 像素：暗色牌面压住原文 + 框内真有字形")

img2 = QImage(img.width(), img.height(), QImage.Format_ARGB32_Premultiplied)
img2.fill(Qt.transparent)
overlay.render(img2)

scale = img2.width() / float(max(1, overlay.width()))
check("渲染倍率换算可用（0.5 ≤ scale ≤ 4）", 0.5 <= scale <= 4.0,
      "→ scale=%.3f, image=%dx%d" % (scale, img2.width(), img2.height()))


def px(x, y):
    return QColor(img2.pixelColor(int(x * scale), int(y * scale)))


def scan_box(box):
    """统计框内部的牌面像素与字形像素，返回 (最多 alpha, 牌面色, 字形点数)。"""
    plate_alpha = 0
    plate = None
    ink = 0
    x = box.left() + 2.0
    while x < box.right() - 2.0:
        y = box.top() + 2.0
        while y < box.bottom() - 2.0:
            c = px(x, y)
            # 牌面是暗色玻璃：只看「暗且不透明」的像素，别把字算进去
            dark = c.red() < 40 and c.green() < 40 and c.blue() < 50
            if dark and c.alpha() > plate_alpha:
                plate_alpha = c.alpha()
                plate = c
            # 字形：近白（`WORD_INK = #F2FFFD`），压在暗牌面上
            if c.alpha() > 200 and c.red() > 200 and c.green() > 200 \
                    and c.blue() > 200:
                ink += 1
            y += 1.0
        x += 1.0
    return plate_alpha, plate, ink


fitted = [g for g in overlay._guides if g.get("fitted")]
check("走的是贴合词框分支（否则下面取样没有意义）", len(fitted) == len(WORDS),
      "→ %d/%d" % (len(fitted), len(WORDS)))

worst_alpha, plate_color, ink_dots = 0, None, 0
for g in fitted:
    a, color, dots = scan_box(g["box"])
    worst_alpha = max(worst_alpha, a)
    ink_dots += dots
    if color is not None:
        plate_color = color

check("牌面够实（alpha ≥ %d×0.9，原文被盖住）" % BOX_ALPHA,
      worst_alpha >= int(BOX_ALPHA * 0.9),
      "→ 最高 alpha=%d，牌面 %s" % (worst_alpha,
                                 plate_color.name() if plate_color else "?"))
check("框内确实有近白字形像素", ink_dots >= 40,
      "→ %d 个字形象素（阈值 40）" % ink_dots)


def _near(color, target, tolerance):
    """颜色近似：辉光叠在桌面/透明底上，色值不会和 aura 完全相等。"""
    return (abs(color.red() - target.red()) <= tolerance
            and abs(color.green() - target.green()) <= tolerance
            and abs(color.blue() - target.blue()) <= tolerance)


def border_alpha(box):
    """沿框上边扫一圈，取最不透明的一个像素 —— 证明框线还在。"""
    best = 0
    x = box.left()
    while x < box.right():
        c = px(x, box.top())
        if c.alpha() > best:
            best = c.alpha()
        x += 1.0
    return best


bars = [border_alpha(g["box"]) for g in fitted]
check("框线确实被画出来了（不是糊成一整块色）",
      bool(bars) and min(bars) >= 150,
      "→ 上边线最小 alpha=%d" % (min(bars) if bars else -1))

# ---------------------------------------------------------------- ③ 发光
print("\n[③] 发光：框外沿必须有一圈同色光环")

glow_hits = 0
for g in fitted:
    box = g["box"]
    aura = QColor(g["aura"])
    # 取框上边**外**一点点（描边之外）的像素：辉光就在这一圈
    y = box.top() - 3.0
    x = box.left() + 2.0
    while x < box.right() - 2.0:
        c = px(x, y)
        if c.alpha() > 8 and _near(c, aura, 70):
            glow_hits += 1
        x += 1.0
check("框外侧有 aura 色辉光（不是一根光秃秃的描边）", glow_hits >= 12,
      "→ %d 个光环像素" % glow_hits)

# ---------------------------------------------------------------- ④ 同色
print("\n[④] 同色：框 / 腿 / 释义卡色条读同一个色号")
import crawler_spider as CS_                                   # noqa: E402

by_word = {g["surface"]: g for g in overlay._guides}
same = 0
for word in WORDS:
    guide = by_word.get(word["surface"])
    if guide is not None and guide["aura"] == word.get("aura"):
        same += 1
check("每个词的框色 == item[\"aura\"]（释义卡色条读的就是它）",
      same == len(WORDS), "→ %d/%d" % (same, len(WORDS)))
check("色号取自八足微光八色表",
      all(w.get("aura") in CS_.LEG_AURA for w in WORDS),
      "→ %s" % [w.get("aura") for w in WORDS])

# ---------------------------------------------------------------- ⑤ 尺寸侧
print("\n[⑤] 尺寸：字号只由框高决定（框 → 字 的单向链）")

from PySide6.QtGui import QFontMetricsF as _QFM                  # noqa: E402

box_small = QRectF(0, 0, 122, 26)
# 等比放大：长词的字号是**宽度**先撞线的，只放大高度不会变字号（这是对的）
box_big = QRectF(0, 0, 244, 52)
font_small = AimOverlay._build_word_font("committee", box_small)
font_big = AimOverlay._build_word_font("committee", box_big)
check("框等比翻倍 → 字号跟着翻倍（±10%）",
      1.9 <= font_big.pixelSize() / float(font_small.pixelSize()) <= 2.1,
      "→ %dpx vs %dpx" % (font_small.pixelSize(), font_big.pixelSize()))

# 字号的上限由**高度**决定 —— 选一个不会被框宽卡住的短词来验这条
tall_font = AimOverlay._build_word_font("at", QRectF(0, 0, 122, 26))
check("字号与 WORD_TEXT_FIT 同源（框高 26 → 约 %.0fpx）"
      % (24 * WORD_TEXT_FIT),
      abs(tall_font.pixelSize() - 24 * WORD_TEXT_FIT) <= 1.5,
      "→ %dpx" % tall_font.pixelSize())

long_font = AimOverlay._build_word_font("committee", QRectF(0, 0, 122, 26))
advance = _QFM(long_font).horizontalAdvance("committee")
check("长词不溢出框宽（advance ≤ 框宽-4，容差 1px）", advance <= 122 - 4 + 1.0,
      "→ %.1fpx / 118px" % advance)

# 框宽只**收缩**、绝不放大：同一个词放进更窄的框，字号只能变小或不变
narrow_font = AimOverlay._build_word_font("it", QRectF(0, 0, 34, 26))
wide_font = AimOverlay._build_word_font("it", QRectF(0, 0, 122, 26))
check("框宽只做收缩（窄框字号 ≤ 宽框字号）",
      narrow_font.pixelSize() <= wide_font.pixelSize(),
      "→ 窄框 %dpx / 宽框 %dpx" % (narrow_font.pixelSize(),
                                   wide_font.pixelSize()))
check("窄框里的短词不溢出（advance ≤ 框宽-4）",
      _QFM(narrow_font).horizontalAdvance("it") <= 34 - 4 + 1.0,
      "→ %.1fpx / 30px" % _QFM(narrow_font).horizontalAdvance("it"))

overlay.close()
overlay.deleteLater()

print("\n" + "=" * 78)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
for name in FAIL:
    print("  FAILED:", name)
raise SystemExit(1 if FAIL else 0)
