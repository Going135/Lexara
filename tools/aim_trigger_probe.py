# -*- coding: utf-8 -*-
"""「八腿踩词」**触发率**体检：把每一类可能让它不出现的情况各跑一遍称重。

为什么要单开一个脚本
--------------------
`tools/aim_e2e.py` 只证明「一次正常流程能跑通」，它是**单场景**的。
但用户反馈的是「不是百分百触发」—— 那就是**分支**的问题，不是主路径的问题。
所以这里按「事件序列」而不是「几何」来测：调位途中被点了一下、双击头、
OCR 飞快先回来、选区贴着屏幕角、词群比腿长还宽……逐条跑，统计
「瞄准层起没起」「八条腿绑到几个词」。

判定标准（这三条都过才算触发成功）：
    1. `pet._dialogs["aim"]` 存在（覆盖层起来了）；
    2. `overlay._pairs` 非空（至少有一条腿真的伸出去踩词）；
    3. `overlay._guides` == 词数（每个词都有框）。

运行：  python tools/aim_trigger_probe.py
输出：  dist/aim/trigger_matrix.txt   逐场景结果
"""
from __future__ import annotations

import io
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt     # noqa: E402
from PySide6.QtGui import QMouseEvent                            # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

import aim_overlay as AO                                          # noqa: E402
import pet_window as PW                                          # noqa: E402
from pet_window import OcrWorker, PetWindow                       # noqa: E402

OUT = os.path.join(BASE, "dist", "aim")
os.makedirs(OUT, exist_ok=True)


# ------------------------------------------------------------------ 基础设施
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


class StubOcrWorker(OcrWorker):
    payload = None

    def run(self) -> None:
        words, meta = self.payload or ([], {"positions": {}, "lines": []})
        # 只替换「OCR 认出了什么」，坐标换算走生产代码（`OcrWorker.locate`）——
        # 这样「选区跟着这次识别走」这件事也在被测之列。
        self.locate(words, meta.get("positions", {}))
        self.done.emit(words, meta, "")


class _FakeBook:
    def __init__(self):
        self._s = set()

    def has(self, w):
        return w in self._s

    def add(self, item):
        self._s.add(item["lemma"])
        return True

    def remove(self, w):
        self._s.discard(w)

    def __len__(self):
        return len(self._s)

    def stats(self):
        return {}

    def items(self):
        return []

    def review_queue(self):
        return []

    def record_learning(self, words) -> int:
        # 测试桩：不落盘，仅占位以走通生产 _on_ocr_done 的同一代码路径。
        return 0


app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

pet = PetWindow(None, _FakeBook(), sprite_w=360.0)
pet._timer.stop()
pet._idle_timer.stop()
pet.bubble.hide_now()
SCREEN = pet._screen_rect()


def pump(frames: int, dt: float = 1 / 60.0) -> None:
    for _ in range(frames):
        pet._last = clock.t
        clock.t += dt
        pet._tick()
        app.processEvents()


def wait_until(predicate, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.004)
    return predicate()


def mouse(kind, local_x, local_y, global_xy=None):
    """造一个真 QMouseEvent 丢给窗口 —— 走的是生产代码里的那个槽。"""
    gx, gy = global_xy if global_xy else (local_x, local_y)
    return QMouseEvent(kind, QPointF(local_x, local_y), QPointF(gx, gy),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def click_body(drag_px=0):
    """在窗口中心按一下（= 矩形身体上）。drag_px>0 表示拖动。"""
    local = QPointF(pet.width() / 2.0, pet.height() / 2.0)
    glob = QPointF(pet.center.x(), pet.center.y())
    pet.mousePressEvent(mouse(QEvent.MouseButtonPress, local.x(), local.y(),
                              (glob.x(), glob.y())))
    if drag_px:
        pet.mouseMoveEvent(mouse(QEvent.MouseMove, local.x() + drag_px, local.y(),
                                 (glob.x() + drag_px, glob.y())))
    pet.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, local.x(), local.y(),
                                (glob.x(), glob.y())))


def double_click_body():
    click_body()
    pet.mouseDoubleClickEvent(mouse(QEvent.MouseButtonDblClick,
                                    pet.width() / 2.0, pet.height() / 2.0,
                                    (pet.center.x(), pet.center.y())))
    pet.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease,
                                pet.width() / 2.0, pet.height() / 2.0,
                                (pet.center.x(), pet.center.y())))


# ------------------------------------------------------------------ 造选区/词
NAMES = ["abandon", "committee", "government", "supervise",
         "project", "support", "absence", "insufficient"]


def make_case(rect, spots, names=None, dpr=1.0):
    names = names or NAMES[:len(spots)]
    words, positions = [], {}
    for name, (fx, fy) in zip(names, spots):
        words.append({"lemma": name, "surface": name, "pos": "n.", "cn": "释义",
                      "tags": ["cet6"], "difficulty": 3, "off_syllabus": False})
        positions[name] = (rect.width() * fx, rect.height() * fy)
    return words, positions, dpr


def fire_ocr(words, positions, rect, dpr=1.0):
    pet._capture_rect = QRect(rect)
    pet._capture_dpr = dpr
    worker = StubOcrWorker(None, None, "cet6", 8, True, parent=pet)
    worker.capture_rect = QRect(rect)
    worker.dpr = dpr
    worker.payload = (words, {"positions": dict(positions), "lines": []})
    pet._workers.append(worker)
    worker.done.connect(pet._on_ocr_done)
    worker.finished.connect(lambda item=worker: pet._reap(item))
    worker.start()
    return worker


def reset(start_xy=None):
    """把窗口恢复成「刚启动、还没识词」的样子。"""
    if pet._capture_busy:
        pet._capture_cancel()
    old = pet._dialogs.pop("aim", None)
    if old is not None:
        old.hide()
    pet._dialogs.pop("words", None)
    pet._travel = None
    pet._travel_done = None
    pet._aim_pending = None
    pet._aim_at = None
    pet._capture_rect = None
    pet.spider.clear_targets()
    pet._pressed = False
    pet.dragging = False
    pet._dbl = False
    pet._click_timer.stop()
    pet.effect = None
    pet._set_state("idle")
    pet.center = QPoint(*[int(v) for v in (start_xy or PET_HOME)])
    pet._last_x, pet._last_y = float(pet.center.x()), float(pet.center.y())


PET_HOME = (SCREEN.width() // 2, SCREEN.height() - 120)

RESULTS = []


def run_case(name, expectation, setup, want_legs=None):
    """跑一个场景，返回 dict（触发与否 + 腿数）。"""
    reset()
    setup()
    # 跑到瞄准层出现，或 6 秒（假钟）都没有
    for _ in range(420):
        if pet._dialogs.get("aim") is not None:
            break
        pump(1)
    overlay = pet._dialogs.get("aim")
    legs = len(overlay._pairs) if overlay is not None else 0
    boxes = len(overlay._guides) if overlay is not None else 0
    ok = overlay is not None and legs > 0
    if want_legs is not None and legs != want_legs:
        ok = False
    RESULTS.append({"name": name, "ok": ok, "overlay": overlay is not None,
                    "legs": legs, "boxes": boxes,
                    "expect": expectation, "detail": setup_detail})
    flag = "ok  " if ok else "FAIL"
    print("  [%s] %-40s 覆盖层=%-3s 腿=%-2d 框=%-2d  %s"
          % (flag, name, "有" if overlay is not None else "无", legs, boxes,
             expectation))
    return RESULTS[-1]


setup_detail = ""


# ------------------------------------------------------------------ 场景
print("=" * 78)
print("八腿踩词 · 触发率体检")
print("=" * 78)
print("屏幕 %dx%d   蜘蛛初始 %s" % (SCREEN.width(), SCREEN.height(), PET_HOME))

CENTRAL = QRect(int(SCREEN.width() * 0.10), int(SCREEN.height() * 0.12),
                int(SCREEN.width() * 0.80), int(SCREEN.height() * 0.40))
TIGHT = [(0.12, 0.16), (0.32, 0.13), (0.54, 0.17), (0.80, 0.12),
         (0.18, 0.72), (0.40, 0.74), (0.64, 0.70), (0.86, 0.76)]
WIDE = [(0.02, 0.10), (0.15, 0.12), (0.30, 0.10), (0.45, 0.13),
        (0.58, 0.11), (0.72, 0.14), (0.86, 0.11), (0.97, 0.13)]

print("\n[A] 主路径")
setup_detail = "8 个词挤在选区中央"
w, p, d = make_case(CENTRAL, TIGHT)
run_case("A1 正常：词群在屏幕中央", "必须触发", lambda: fire_ocr(w, p, CENTRAL, d))

# --- 调位途中被点一下（最容易丢回调的一条）
setup_detail = "OCR 回来后 3 帧（正在走去停靠点）在身体上按一下、不拖"
w, p, d = make_case(CENTRAL, TIGHT)


def case_click_during_travel():
    fire_ocr(w, p, CENTRAL, d)
    wait_until(lambda: pet._travel is not None, 4.0)
    pump(3)
    click_body()          # 只按一下，不拖


run_case("A2 调位途中按一下（不拖）", "必须触发，且调位不被打断 → 8 条腿",
         case_click_during_travel, want_legs=8)


# --- 调位途中把蜘蛛拖走：调位被打断，但**结果还在手上**，必须照样踩词
setup_detail = "OCR 回来后 3 帧把蜘蛛拖走 120px"


def case_drag_during_travel():
    fire_ocr(w, p, CENTRAL, d)
    wait_until(lambda: pet._travel is not None, 4.0)
    pump(3)
    click_body(drag_px=120)


run_case("A2b 调位途中拖走（调位被打断）", "必须仍然触发（站哪踩哪）",
         case_drag_during_travel)

# --- OCR 飞快先回来：蜘蛛还在去 coarse 的路上
setup_detail = "OCR 结果比第一段调位还快回来"
w, p, d = make_case(CENTRAL, TIGHT)
run_case("A4 OCR 先回来（第一段调位未完）", "必须触发",
         lambda: (fire_ocr(w, p, CENTRAL, d), pump(0)))

print("\n[B] 距离与位置")
# --- 远距离（>260px 会改成跳跃）
FAR = QRect(int(SCREEN.width() * 0.10), int(SCREEN.height() * 0.05),
            int(SCREEN.width() * 0.80), int(SCREEN.height() * 0.22))
setup_detail = "词群在屏幕上方，蜘蛛在下方 → 触发跳跃"
w, p, d = make_case(FAR, TIGHT)
run_case("B1 远距离（走不下去了，改跳）", "必须触发",
         lambda: fire_ocr(w, p, FAR, d))

# --- 贴屏幕左下角：停靠点会被 _clamp_point 拉走
CORNER = QRect(0, int(SCREEN.height() * 0.55), int(SCREEN.width() * 0.22),
               int(SCREEN.height() * 0.30))
CORNER_SPOTS = [(0.10, 0.15), (0.30, 0.18), (0.55, 0.14), (0.85, 0.16),
                (0.14, 0.70), (0.36, 0.74), (0.60, 0.68), (0.88, 0.76)]
setup_detail = "选区贴屏幕左下角，停靠点会被安全边距拉走"


def case_corner():
    w, p, d = make_case(CORNER, CORNER_SPOTS)
    pet.center = QPoint(int(SCREEN.width() * 0.18), int(SCREEN.height() * 0.40))
    pet._last_x, pet._last_y = float(pet.center.x()), float(pet.center.y())
    fire_ocr(w, p, CORNER, d)


run_case("B2 选区贴屏幕角（停靠点被夹）", "必须触发", case_corner)

print("\n[C] 词群形状")
# --- 只有一个词
ONE = QRect(int(SCREEN.width() * 0.30), int(SCREEN.height() * 0.18), 260, 90)
setup_detail = "只框到一个词"
w, p, d = make_case(ONE, [(0.5, 0.5)], names=["abandon"])
run_case("C1 只识别出 1 个词", "至少有 1 条腿踩上去",
         lambda: fire_ocr(w, p, ONE, d))

# --- 词群比腿还宽（八个词横跨整个屏幕宽）
setup_detail = "八个词横跨整条屏幕宽 → 必然有够不着的"
w, p, d = make_case(CENTRAL, WIDE)
run_case("C2 词群远超腿长（横跨全屏）", "至少 2 条腿踩到（不能 0）",
         lambda: fire_ocr(w, p, CENTRAL, d))

# --- 词群很小很挤（词与词之间挤在一起）
TINY = QRect(int(SCREEN.width() * 0.40), int(SCREEN.height() * 0.16), 220, 80)
TINY_SPOTS = [(0.20, 0.25), (0.45, 0.22), (0.70, 0.26), (0.30, 0.70),
              (0.55, 0.72), (0.78, 0.66), (0.40, 0.48), (0.62, 0.50)]
setup_detail = "八个词挤在一小块（220×80）里"
w, p, d = make_case(TINY, TINY_SPOTS, names=NAMES)
run_case("C3 词群极挤（腿会互相穿插）", "必须触发", lambda: fire_ocr(w, p, TINY, d))

print("\n[D] 连发与重入")
setup_detail = "同一秒内连发两次识别"


def case_double_fire():
    w, p, d = make_case(CENTRAL, TIGHT)
    fire_ocr(w, p, CENTRAL, d)
    pump(2)
    fire_ocr(w, p, CENTRAL, d)


run_case("D1 连发两次识别（第二次覆盖第一次）", "必须触发且只留一个覆盖层",
         case_double_fire)


# --- 调位途中双击：**语义是「我要重新框选」**，所以旧结果作废是对的。
# 要盯的是「只起一个遮罩、不会二次开框选」——双击曾经会开两次框选，
# 屏幕上叠两个全屏遮罩（关掉上面那个，下面那个就露出来，看着像卡死）。
setup_detail = "调位途中双击 = 重新框选，旧结果作废但要干净"


def case_dblclick_timer():
    reset()
    w, p, d = make_case(CENTRAL, TIGHT)
    fire_ocr(w, p, CENTRAL, d)
    wait_until(lambda: pet._travel is not None, 4.0)
    pump(3)
    double_click_body()
    ok = (pet._capture_busy and pet._aim_pending is None
          and not pet._click_timer.isActive())
    RESULTS.append({"name": "D3 调位途中双击 → 切新框选",
                    "ok": ok, "overlay": None, "legs": -1, "boxes": -1,
                    "expect": "遮罩只起一个、旧结果作废、不会二次开框选",
                    "detail": setup_detail})
    print("  [%s] %-40s 框选中=%-3s 旧结果=%-3s 单击定时器=%s"
          % ("ok  " if ok else "FAIL", "D3 调位途中双击 → 切新框选",
             "是" if pet._capture_busy else "否",
             "已清" if pet._aim_pending is None else "还在",
             "跑着" if pet._click_timer.isActive() else "已停"))
    return RESULTS[-1]


setup_detail = "一次双击只允许开一次框选"


def case_dblclick_only():
    reset()
    double_click_body()
    alive = pet._click_timer.isActive()
    RESULTS.append({"name": "D2 双击后单击定时器已停", "ok": not alive,
                    "overlay": None, "legs": -1, "boxes": -1,
                    "expect": "定时器必须已停（否则会二次开框选）",
                    "detail": setup_detail})
    print("  [%s] %-40s 定时器 %s"
          % ("ok  " if not alive else "FAIL", "D2 双击后单击定时器已停",
             "仍在跑（会二次开框选）" if alive else "已停"))
    return RESULTS[-1]


case_dblclick_only()
case_dblclick_timer()

print("\n[E] 选区跟着识别走：两次框选重入不串坐标")
# 用户框了一次 → OCR 要跑 3~5 秒 → 觉得没反应，又框了一次。
# 后一次会把窗口上的 `_capture_rect` 覆盖掉。如果「截图坐标 → 屏幕坐标」
# 是主线程从窗口上读选区，那**第一次的结果就会被算到第二次的坐标系上**，
# 八条腿直接踩到一片空白。所以这步换算必须由 worker 带着自己那份选区做完。
OLD = QRect(100, 100, 300, 200)
NEW = QRect(900, 700, 300, 200)


def case_worker_rect():
    reset()
    w, p, _ = make_case(OLD, [(0.5, 0.5)], names=["abandon"])
    pet._capture_rect = QRect(NEW)          # 模拟「用户已经又框了一次」
    worker = StubOcrWorker(None, None, "cet6", 8, True, parent=pet)
    worker.capture_rect = QRect(OLD)        # worker 攥着自己那次的选区
    worker.dpr = 1.0
    worker.payload = (w, {"positions": dict(p), "lines": []})
    pet._workers.append(worker)
    worker.done.connect(pet._on_ocr_done)
    worker.finished.connect(lambda item=worker: pet._reap(item))
    worker.start()
    wait_until(lambda: pet._aim_pending is not None, 6.0)
    return pet._aim_pending


pending = case_worker_rect()
pos = pending[0][0]["screen_pos"] if pending else None
inside = bool(pos) and OLD.contains(QPoint(int(pos[0]), int(pos[1])))
RESULTS.append({"name": "E1 旧 worker 用自己那份选区", "ok": inside,
                "overlay": None, "legs": -1, "boxes": -1,
                "expect": "落在旧选区 %s 内（不是新选区 %s）" % (OLD, NEW),
                "detail": "窗口上的 _capture_rect 已被覆盖成新选区"})
print("  [%s] %-40s screen_pos=%s  旧选区=%s  窗口上=%s"
      % ("ok  " if inside else "FAIL", "E1 旧 worker 用自己那份选区",
         tuple(round(v, 1) for v in pos) if pos else None, OLD, pet._capture_rect))

print("\n[F] 几何前提")
print("  · 单腿可达半径（局部单位）: %s" % [
    round(L.full, 1) for L in pet.spider.legs if not L.palp][:4])
# 可达半径 = full × unit，而瞄准层还额外乘「放大倍数」和「腿长倍率」。
# 这三个数里任何一个变了，「够不够得着某片词」的结论就变，所以这里全部走常量，
# 不要写死 —— 之前这里硬编码 205.3，腿长一改数字就是错的。
# 另外要用 `rest_r × 1.2`（构造期的天然腿长）而不是 `full`：探针跑到这里时
# 可能刚过一层瞄准层，共享的 Spider 还带着拉长倍率，直接读 full 会偏大。
_far = max(L.rest_r for L in pet.spider.legs if not L.palp) * 1.2
print("  · unit=%.4f  → 天然最远一条腿 %.0fpx；瞄准层（放大 ×%.2f、腿长 ×%.1f）后 %.0fpx"
      % (pet.unit, _far * pet.unit, AO.AIM_SCALE_BOOST, AO.AIM_LEG_STRETCH_MAX,
         _far * pet.unit * AO.AIM_SCALE_BOOST * AO.AIM_LEG_STRETCH_MAX))

# ------------------------------------------------------------------ 汇总
lines = []
bad = [r for r in RESULTS if not r["ok"]]
lines.append("八腿踩词 · 触发率体检   %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
lines.append("屏幕 %dx%d" % (SCREEN.width(), SCREEN.height()))
for r in RESULTS:
    lines.append("%-6s %-42s 覆盖层=%-3s 腿=%-3s 框=%-3s  %s"
                 % ("ok" if r["ok"] else "FAIL", r["name"],
                    "有" if r["overlay"] else "无", r["legs"], r["boxes"],
                    r["expect"]))
lines.append("")
lines.append("触发成功 %d / %d" % (len(RESULTS) - len(bad), len(RESULTS)))
with io.open(os.path.join(OUT, "trigger_matrix.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")

print("\n" + "=" * 78)
print("触发成功 %d / %d" % (len(RESULTS) - len(bad), len(RESULTS)))
for r in bad:
    print("  FAILED:", r["name"], "→", r["expect"])
print("明细 → dist/aim/trigger_matrix.txt")
raise SystemExit(1 if bad else 0)
