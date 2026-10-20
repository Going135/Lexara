# -*- coding: utf-8 -*-
"""未分配腿逐条折回 + 折叠时身体向头部收拢（任务书 §5、§6）。

以前只有「全局折叠」（右键无腿模式）这一个开关。识别时八条腿一律撑在静止位
上，三个词就是「三条腿干活、五条腿杵着」，看着不像蜘蛛在按词，像断了腿。
现在腿有各自的 `fold / fold_target / assigned`，身体再按折叠量轻微收拢。

四组断言：

    ① 意图：`set_leg_assignment()` 只动步足，派到的伸、没派到的收；
    ② 平滑：逐帧缓动（不许瞬移），并且 0.6 秒内基本收完；
    ③ 像素：按生产 paintEvent 渲染，收回的腿在**原脚尖位置**不再有一个像素，
       伸着的腿照旧踩得住；头部素材的位置/尺寸分毫不动，身体后缘真的缩短；
    ④ 命中：折叠后「看不见的地方」不再点得中（身体后缘），头部照点得中；
    ⑤ 集成：`AimOverlay` 派完腿确实把折叠意图报给了模型。

运行：  python test/test_leg_fold_assignment.py
输出：  dist/shape/leg_fold_sheet.png
"""

from __future__ import annotations

import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt          # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QPainter,     # noqa: E402
                           QPen)
from PySide6.QtWidgets import QApplication                      # noqa: E402

import crawler_spider as CS                                     # noqa: E402
import locomotion                                               # noqa: E402
import pet_window as PW                                         # noqa: E402
from spider_painter import SpiderState                          # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

OUT = os.path.join(BASE, "dist", "shape")
os.makedirs(OUT, exist_ok=True)

PASS, FAIL = [], []
STEP = 1.0 / 60.0


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-58s %s" % ("ok" if ok else "FAIL", name, detail))


def font(px, bold=False):
    f = QFont()
    f.setPointSize(px)
    f.setBold(bold)
    return f


steppers = lambda s: [L for L in s.legs if not L.palp]          # noqa: E731

print("\n[①] 折叠意图：派到词的伸着，没派到的收回")

spider = CS.Spider(size=1.0)
for _ in range(120):
    spider.update(STEP)                       # 先散开站好

keep = {L.index for L in steppers(spider)[:3]}
spider.set_leg_assignment(keep, retract_unassigned=True)
check("派到词的 3 条腿 fold_target=0",
      all(L.fold_target == 0.0 for L in spider.legs if L.index in keep))
check("其余 5 条步足 fold_target=1",
      all(L.fold_target == 1.0 for L in steppers(spider)
          if L.index not in keep))
check("触须不参与逐腿折叠（永远是伸的）",
      all(L.fold_target == 0.0 for L in spider.legs if L.palp))
check("assigned 标记与派单一致",
      all(L.assigned == (L.index in keep) for L in steppers(spider)))
check("fold_amount = 步足折叠量平均（开局还是 0）",
      abs(spider.fold_amount) < 1e-9, "→ %.3f" % spider.fold_amount)

spider.set_leg_assignment(None)
check("传 None = 全部伸回（覆盖层收工）",
      all(L.fold_target == 0.0 and L.assigned for L in steppers(spider)))

print("\n[②] 平滑：逐帧缓动，不许瞬移")

spider = CS.Spider(size=1.0)
for _ in range(120):
    spider.update(STEP)
foldable = [L for L in steppers(spider) if L.index not in keep]
spider.set_leg_assignment(keep, retract_unassigned=True)

jumps, track = [], []
for frame in range(60):
    before = [L.fold for L in spider.legs]
    spider.update(STEP)
    for leg, was in zip(spider.legs, before):
        jumps.append(abs(leg.fold - was))
    track.append((frame, spider.fold_amount, spider.body_fold))

check("单帧折叠量变化 <=0.12（没有「啪」地一下）", max(jumps) <= 0.12,
      "→ 最大 %.4f" % max(jumps))
check("0.6 秒内未分配腿基本收完（fold >= 0.95）",
      all(L.fold >= 0.95 for L in foldable),
      "→ 最小 %.3f" % min(L.fold for L in foldable))
check("派到词的腿一条都没收", all(L.fold == 0.0 for L in spider.legs
                                  if L.index in keep))
check("fold_amount 跟着走（5/8 收 → ≈0.625）",
      abs(spider.fold_amount - 5.0 / 8.0) < 0.05,
      "→ %.3f" % spider.fold_amount)
check("身体折叠量滞后于腿（先收腿、再收身）",
      track[-1][2] < track[-1][1] and track[-1][2] > 0.0,
      "→ body %.3f vs legs %.3f" % (track[-1][2], track[-1][1]))
check("骨长在折叠过程中恒定",
      all(abs(L.l1 + L.l2 - L.full) < 1e-9 for L in spider.legs))

print("\n[③] 像素与命中：按生产 paintEvent 渲染")


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def strftime(self, fmt):
        import time as real
        return real.strftime(fmt)


clock = Clock()
PW.time = clock

pet = PW.PetWindow(None, None, sprite_w=360.0)
pet.effect = None
pet.resize(*pet._window_size())
pet._timer.stop()
pet.bubble.hide_now()
screen = pet._screen_rect()
pet.center = QPoint(int(screen.center().x()), int(screen.center().y()))


def run(frames):
    for _ in range(frames):
        clock.t += 1.0 / 60.0
        pet._tick()


def freeze():
    """停掉呼吸侧摆与转弯倾斜，再量东西。

    体轴扫描线是「过画布原点、沿 forward」的那条线，而 `body_sway` 会把
    身体整块**垂直于体轴**挪开（±1.6 局部单位 ≈ ±2px）。不冻结的话：
      · 扫描线切在椭圆的边上，量到的后缘凭空靠前好几像素；
      · 后面的腿恰好压在扫描线上，`min` 会一路量到脚尖去。
    两处都会让「画 vs 点」的对比失去意义，所以每次测量前都归零。
    """
    pet.spider.lean = 0.0
    pet.spider.body_sway = 0.0


run(150)
pet.spider.clear_targets()
freeze()


def render():
    image = QImage(pet.width(), pet.height(), QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    pet.render(image)
    pet.render(image)          # 第一次可能命中旧缓存层
    return image


def ink_near(image, point, radius=3.0):
    """某个屏幕点附近有没有墨（返回最大 alpha）。"""
    x0 = max(0, int(point[0] - radius))
    x1 = min(image.width() - 1, int(point[0] + radius))
    y0 = max(0, int(point[1] - radius))
    y1 = min(image.height() - 1, int(point[1] + radius))
    best = 0
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            best = max(best, image.pixelColor(x, y).alpha())
    return best


def axis_point(t):
    """体轴上距原点 t 像素的窗口像素坐标。"""
    ox, oy = pet._canvas_origin()
    fx, fy = pet.spider.forward()
    return ox + fx * t, oy + fy * t


def walk_outward(has_ink, limit=260):
    """从体心沿体轴向两侧走，走到「连续墨迹」断掉为止 → (前缘, 后缘)。

    不能直接取全轴的最小/最大有墨点：后腿会横穿这条轴，那样量到的是脚尖。
    身体是一块连着的，从原点往外走第一次断掉的地方就是轮廓边缘。
    """
    def edge(sign):
        last = 0
        t = 0
        while True:
            t += sign
            if abs(t) > limit or not has_ink(t):
                break
            last = t
        return last
    return edge(1), edge(-1)


def axis_hit(t):
    """体轴上「距原点 t 个窗口像素」这一点语义是什么。

    走**生产路径**：窗口像素 → `PetWindow._to_local`（含一次性形变与朝向）
    → `Spider.hit_test`。测试自己拼局部坐标的话，`unit` / `body_scale` /
    `heading` 三层缩放关系很容易对不上，那样根本测不出「画与点一致」。
    """
    return pet.spider.hit_test(pet._to_local(*axis_point(t)))


def hit_extent():
    """可点区沿体轴的 [前缘, 后缘]（窗口像素，和墨迹一样从体心往外走）。"""
    return walk_outward(lambda t: axis_hit(t) in ("head", "body"))


def measure(assigned):
    """设好折叠意图、缓动到稳定，返回 (图, 各脚尖位置, 身体前后缘像素)。"""
    # `retract_unassigned=True`：这组测的就是「没派到的腿折回去」这条旧路径，
    # 而生产里的扫描默认不折（见 `set_leg_assignment` 的说明）。
    pet.spider.set_leg_assignment(assigned, retract_unassigned=True)
    for _ in range(70):
        run(1)
    freeze()
    image = render()
    pet.painter.setup(pet._canvas_origin(), pet.unit, pet.spider.heading)
    tips = {L.index: pet.painter.to_screen(L.tip) for L in steppers(pet.spider)}
    hips = {L.index: pet.painter._hip_screen(L) for L in steppers(pet.spider)}

    def ink(t):
        x, y = axis_point(t)
        if not (0 <= int(x) < image.width() and 0 <= int(y) < image.height()):
            return False
        return image.pixelColor(int(x), int(y)).alpha() > 60

    front, back = walk_outward(ink)
    return image, tips, hips, front, back


all8 = {L.index for L in steppers(pet.spider)}
img_open, tips_open, hips_open, front_open, back_open = measure(all8)
hf_open, hb_open = hit_extent()
check("八腿全伸时脚尖位置都有墨（取样点有效）",
      all(ink_near(img_open, tips_open[i]) > 40 for i in tips_open),
      "→ 最小 alpha %d" % min(ink_near(img_open, tips_open[i])
                              for i in tips_open))

keep3 = {L.index for L in steppers(pet.spider)[:3]}
img_fold, tips_fold, hips_fold, front_fold, back_fold = measure(keep3)

folded_idx = [i for i in tips_fold if i not in keep3]
out_idx = [i for i in tips_fold if i in keep3]
gone = [ink_near(img_fold, tips_fold[i]) for i in folded_idx]
check("收回的腿在原脚尖处不再画东西（5 条全空）",
      all(a <= 20 for a in gone),
      "→ 最大 alpha %d（阈值 20）" % max(gone))
staying = [ink_near(img_fold, tips_fold[i]) for i in out_idx]
check("派到词的 3 条腿照常伸着踩住",
      all(a > 40 for a in staying),
      "→ 最小 alpha %d" % min(staying))
hip_ink = [ink_near(img_fold, hips_fold[i], 4.0) for i in folded_idx]
check("收回的腿在髋部附近收拢成一小截（不是整条消失）",
      all(a > 20 for a in hip_ink),
      "→ 髋部最小 alpha %d" % min(hip_ink))

check("头部最前缘像素不动（±3px）",
      abs(front_fold - front_open) <= 3.0,
      "→ %.0f → %.0f" % (front_open, front_fold))
# 上界放宽到「可见体长的一半」：这是**等比缩**，后缘行程 = 体长 × 22%，
# 但白蛛素材四周有透明留白，像素量到的可见体长比几何框小得多，
# 拿几何框的比例当上界会把一次正常的 22% 缩放判成「压扁了」。
check("身体后缘向前收（缩短 >=8px，且 <=可见体长的一半）",
      8.0 <= (back_fold - back_open) <= abs(back_open) * 0.5 + 1.0,
      "→ 后缘 %.0f → %.0f（收 %.0fpx）" % (back_open, back_fold,
                                            back_fold - back_open))

check("八腿全伸：可点前缘就是头部三角尖（>=70px）",
      hf_open >= 70, "→ %spx" % hf_open)
check("八腿全伸：可点后缘贴着画出来的肚尾（±5px）",
      abs(hb_open - back_open) <= 5.0,
      "→ 点 %.0f / 画 %.0f" % (hb_open, back_open))

hf_fold, hb_fold = hit_extent()
check("命中判定：折叠后头部三角尖照判 head（前缘分毫不动）",
      abs(hf_fold - hf_open) <= 1.0, "→ %.0f → %.0f" % (hf_open, hf_fold))
check("命中判定：可点后缘跟着身体一起往前收",
      4.0 <= hb_fold - hb_open <= 25.0,
      "→ %.0f → %.0f（收 %.0fpx）" % (hb_open, hb_fold, hb_fold - hb_open))
check("命中判定：收进去的那一段不再是「看不见却点得中」",
      abs(hb_fold - back_fold) <= 5.0,
      "→ 点 %.0f / 画 %.0f" % (hb_fold, back_fold))
mid = axis_hit(hb_fold + 20)
check("命中判定：身体中段照常判 body", mid == "body", "→ %s" % mid)

# ---- ④b 判定框与画面同源（纯几何，不受取整/抗锯齿影响） ----
#
# 渲染层的肚尾在局部坐标里落在哪，是 `_folded_body_rect` + `_body_draw_rect`
# 这两个函数说了算；命中层必须算出同一个数。像素对比有 ±2px 的量化噪声，
# 抓不住 `body_scale` 那一档 4px 的系统偏差，所以这里直接比两边的解析结果。
def drawn_rear_local(spider) -> float:
    """画出来的身体后缘（局部单位），走渲染层自己的两个框函数。"""
    u = pet.unit
    ts = u * CS.THORAX_SCALE
    raw = QRectF(CS.THORAX[0] * ts, CS.THORAX[1] * ts,
                 CS.THORAX[2] * ts, CS.THORAX[3] * ts)
    rect = pet.painter._body_draw_rect(
        pet.painter._folded_body_rect(raw, spider))
    return rect.left() / u


def hit_rear_local(spider) -> float:
    """判定后缘（局部单位）：沿体轴二分找 `_in_thorax` 的翻转点，容差取 0。"""
    lo, hi = -220.0, (CS.THORAX[0] + CS.THORAX[2]) * CS.THORAX_SCALE
    for _ in range(60):
        mid_x = (lo + hi) / 2.0
        if spider._in_thorax(spider._body_point((mid_x, 0.0)), pad=0.0):
            hi = mid_x
        else:
            lo = mid_x
    return hi


baseline_fold = pet.spider.body_fold
try:
    for fold in (0.0, 0.6, 1.0):
        pet.spider.body_fold = fold
        d, h = drawn_rear_local(pet.spider), hit_rear_local(pet.spider)
        check("判定后缘 == 画出后缘（body_fold=%.1f）" % fold,
              abs(d - h) <= 1.5, "→ 画 %.2f / 点 %.2f 单位" % (d, h))
    pet.spider.body_fold = 0.0
    rear_open_u = drawn_rear_local(pet.spider)
    pet.spider.body_fold = 1.0
    rear_full_u = drawn_rear_local(pet.spider)
    check("身体收拢量 = 框宽 × BODY_FOLD_SHRINK（锚在前缘、朝头等比缩小）",
          abs((rear_full_u - rear_open_u)
              - CS.THORAX[2] * CS.THORAX_SCALE * CS.BODY_FOLD_SHRINK
              * pet.spider.body_scale) < 0.6,
          "→ 收 %.2f 单位（框宽 %.2f）"
          % (rear_full_u - rear_open_u,
             CS.THORAX[2] * CS.THORAX_SCALE * pet.spider.body_scale))
finally:
    pet.spider.body_fold = baseline_fold

pet.spider.set_leg_assignment(None)
for _ in range(90):
    run(1)
check("清掉派单后所有腿伸回（fold 归零）",
      all(L.fold < 0.02 for L in pet.spider.legs),
      "→ 最大 %.3f" % max(L.fold for L in pet.spider.legs))

print("\n[⑤] 集成：AimOverlay 派完腿确实把折叠意图报给模型")

from aim_overlay import AimOverlay                            # noqa: E402


class StubPet:
    """只提供 AimOverlay 需要的字段，不建真桌宠。"""

    def __init__(self):
        self.sprite_w = 360.0
        self.spider = CS.Spider(size=1.0)
        from spider_painter import SpiderPainter
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


def overlay_with(n_words):
    stub = StubPet()
    words = [{"lemma": "w%d" % i, "surface": "w%d" % i,
              "screen_pos": (600.0 + i * 30.0, 300.0),
              "screen_box": (590.0 + i * 30.0, 288.0, 22.0, 26.0)}
             for i in range(n_words)]
    overlay = AimOverlay(stub, words, stagger=0.0)
    return stub, overlay


for n in (1, 3, 8):
    stub, overlay = overlay_with(n)
    assigned = {L.index for L in steppers(stub.spider) if L.fold_target == 0.0}
    folded = {L.index for L in steppers(stub.spider) if L.fold_target == 1.0}
    check("%d 个词：派到腿的条数 == %d，其余全部报收" % (n, n),
          len(assigned) >= min(n, 8) and len(assigned) + len(folded) == 8,
          "→ 伸 %d / 收 %d" % (len(assigned), len(folded)))
    overlay.close()
    after = {L.index for L in steppers(stub.spider) if L.fold_target == 1.0}
    check("%d 个词：覆盖层收工后八条腿全部报伸回" % n, not after,
          "→ 还报收的 %s" % sorted(after))

# ------------------------------------------------------------------ 对照图
BG = QColor(11, 16, 23)
INK = QColor(150, 175, 190)
TITLE = QColor(46, 230, 214)
CELL = 260

sheet = QImage(CELL * 3 + 40, CELL + 120, QImage.Format_ARGB32)
sheet.fill(BG)
painter = QPainter(sheet)
painter.setPen(QPen(TITLE))
painter.setFont(font(12, True))
painter.drawText(QRectF(24, 14, sheet.width() - 48, 28), Qt.AlignLeft,
                 "逐腿折叠：八腿全伸 / 只派 3 条 / 只派 1 条（生产 paintEvent）")
cells = [("8 条全伸", img_open), ("3 条伸 · 5 条收", img_fold)]
pet.spider.set_leg_assignment({steppers(pet.spider)[0].index})
for _ in range(80):
    run(1)
cells.append(("1 条伸 · 7 条收", render()))
for index, (label, image) in enumerate(cells):
    x = 20 + index * CELL
    painter.setPen(QPen(INK))
    painter.setFont(font(9, True))
    painter.drawText(QRectF(x, 46, CELL - 8, 18), Qt.AlignLeft, label)
    scale = min((CELL - 16) / image.width(), (CELL - 60) / image.height())
    w, h = image.width() * scale, image.height() * scale
    painter.drawImage(QRectF(x + (CELL - w) / 2, 70, w, h), image)
painter.end()
sheet_path = os.path.join(OUT, "leg_fold_sheet.png")
sheet.save(sheet_path)
print("\n  图：%s" % sheet_path)

print("\n" + "=" * 78)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
for name in FAIL:
    print("  FAILED:", name)
raise SystemExit(1 if FAIL else 0)
