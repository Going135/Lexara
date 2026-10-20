# -*- coding: utf-8 -*-
"""任务书 §8 验收：识词超过八条腿时，**身体必须沿路径真的走过去**。

盯的是「身体动没动」这一件事，不是「腿伸得够不够远」。
所以断言全部是几何量（停靠点、位移、脚尖到髋部的距离），
而不是截图对比 —— 截图另由 `tools/locomotion_sheet.py` 出。

四组场景（§8 验收原文要 1 / 8 / 9 / 16 个目标）：

  A. 1 个词在远处（≤8 词）    —— **身体不动**，腿拉长去踩（2026-10-19 口径）
  B. 8 个词排成一长条（≤8 词） —— **身体不动**，八条腿全伸出去，一个都不许「只亮框」
  C. 9 个词（首批溢出）        —— 至少 2 批，全部完成，每个词最多完成一次
  D. 16 个词（4×4 网格）       —— 全部完成、路径总长够长、腿长始终受限
  E. 暂停 / 继续 / 中途关闭    —— 身体必须真的停下，不会「以为停了其实还在走」

运行：  python test/test_path_walk.py
"""

import math
import os
import random
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from PySide6.QtCore import QPoint                                    # noqa: E402
from PySide6.QtGui import QGuiApplication                            # noqa: E402
from PySide6.QtWidgets import QApplication                           # noqa: E402

import aim_overlay as AO                                             # noqa: E402
import crawler_spider as CS                                          # noqa: E402
import locomotion                                                    # noqa: E402
import pet_window as PW                                              # noqa: E402
from pet_window import PetWindow                                     # noqa: E402
from scan_session import COMPLETED                                   # noqa: E402

PASS, FAIL = [], []


class Clock:
    """假时钟：`pet_window` 和 `aim_overlay` 各 import 一份 `time`，两边都要换。"""

    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def strftime(self, fmt):
        import time as real
        return real.strftime(fmt)


clock = Clock()
PW.time = clock
AO.time = clock


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    # 控制台是 GBK：断言文案里混进 `↔` 这类不在码表里的符号，`print` 会直接抛
    # UnicodeEncodeError 把整轮测试打断（第一次跑就死在这儿）。打印前按 GBK
    # 兜底替换 —— 中文本身都在码表里，真实信息不丢。
    line = "%s %s %s" % ("[ok]  " if ok else "[fail]", name, detail)
    print(line.encode("gbk", "replace").decode("gbk"))


class _FakeBook:
    def __init__(self):
        self._s = set()

    def has(self, w):
        return w in self._s

    def add(self, item):
        self._s.add(item["lemma"])
        return True

    def stats(self):
        return {"total": len(self._s), "due": 0, "today": 0}

    def review_queue(self):
        return []


app = QApplication(sys.argv)
random.seed(11)

window = PetWindow(None, _FakeBook(), sprite_w=360.0)
window.resize(*window._window_size())
window._timer.stop()
window.start_capture = lambda *a, **k: None
window.bubble.hide_now()

SCREEN = QGuiApplication.primaryScreen().geometry()
print("屏幕逻辑几何 %r" % (SCREEN.getRect(),))

STEP = 1.0 / 60.0
for _ in range(150):
    window.spider.update(STEP, motion=(0.0, 0.0))
window.spider.lean = 0.0
window.spider.body_sway = 0.0


def place(x, y):
    """把桌宠摆到指定屏幕位置（起点可控，路径长度才算得准）。"""
    window.center = QPoint(int(x), int(y))
    window._last_x, window._last_y = float(x), float(y)
    window._apply_geometry(resize=False)


def word(x, y, tag):
    return {
        "lemma": tag, "surface": tag, "meaning": "释义·" + tag, "level": "",
        "screen_pos": (float(x), float(y)),
        # 词本体框：`row_of()` 按它分行，所以必须给，否则整片词会被挤成一行
        "screen_box": (float(x) - 30.0, float(y) - 9.0, 60.0, 18.0),
    }


def worst_stretch(overlay):
    """这一帧「脚尖离髋部最远」的那条腿，是它自己腿长的多少倍。

    §8.3 的硬边界是不许把腿拉成射线：`limit_to_reach` 把脚尖夹在
    `0.99 × full` 之内，所以这里 >0.995 就是有人绕过了那道夹子。
    （以前这里放宽到 1.001，是因为 `_ease_stretch` 在**模型推进之后**才改小
    `full`，那一帧读的是旧脚尖配新腿长。`Spider.set_leg_stretch` 现在改完长度
    就顺手夹一次脚尖，例外帧没了，界也就收回来了。）
    """
    worst = 0.0
    for leg in window.spider.legs:
        hx, hy = leg.hip_pos
        ratio = math.hypot(leg.tip[0] - hx, leg.tip[1] - hy) / max(leg.full, 1e-6)
        worst = max(worst, ratio)
    return worst


def run(words, max_seconds=120.0, until=None):
    """起覆盖层、逐帧推进到队列走完（或 `until` 满足），返回一份轨迹。

    `until(overlay, frame)` 用来在「身体正走在半路上」这一刻截停 ——
    E 组要测暂停，必须停在**位移途中**而不是停在原地。
    """
    overlay = AO.AimOverlay(window, words, stagger=PW.LEG_STAGGER)
    overlay.start()
    start = (float(window.center.x()), float(window.center.y()))
    trace = {"overlay": overlay, "start": start, "path": 0.0, "max_step": 0.0,
             "modes": set(), "stretch_max": 0.0, "tip_max": 0.0,
             "frames": 0, "stops": []}
    previous = start
    limit = int(max_seconds / STEP)
    for frame in range(limit):
        clock.t += STEP
        window._tick()
        overlay._tick()
        trace["frames"] = frame + 1
        root = overlay.mover.root
        hop = math.hypot(root[0] - previous[0], root[1] - previous[1])
        trace["path"] += hop
        trace["max_step"] = max(trace["max_step"], hop)
        previous = root
        trace["modes"].add(overlay.mover.movement_mode)
        trace["stretch_max"] = max(trace["stretch_max"], overlay.leg_stretch)
        trace["tip_max"] = max(trace["tip_max"], worst_stretch(overlay))
        if overlay._stop_now is not None \
                and overlay._stop_now["word_id"] not in trace["stops"]:
            trace["stops"].append(overlay._stop_now["word_id"])
        stats = overlay.session.stats()
        if stats["cancelled"] or not stats["remaining"]:
            break
        if until is not None and until(overlay, frame):
            break
    place(*start)
    return trace


# ================================================================ A 一个远词（≤8：原地定位）
# 用户口径（2026-10-19）：**八个词以内**，蜘蛛选好位置后身子一步不走，
# 全靠八条步足拉长去踩；踩住的姿势一直保持，直到点蜘蛛的头或身子。
# 所以这里盯的是「身体不动 + 腿真的伸长 + 词被踩到」，
# 而不是旧版任务书 §8 那句「身体走过去」——那句只管超过八词的长队列（C/D 组）。
place(700, 860)
ORIGIN = (700.0, 860.0)
FAR = word(1250, 860, "faraway")
a = run([FAR], max_seconds=30.0)
overlay = a["overlay"]
stats = overlay.session.stats()
check("A1 八词以内不规划身体路径（原地定位）",
      overlay._compact_scan and overlay._route == [],
      "→ compact=%s 停靠点 %d" % (overlay._compact_scan, len(overlay._route)))
check("A2 腿真的伸长了（不是够不着就只亮框）",
      a["stretch_max"] > 1.05, "→ 峰值 ×%.2f" % a["stretch_max"])
check("A3 身体一步都没走", a["path"] < 1e-6, "→ 位移 %.3fpx" % a["path"])
check("A4 词被腿踩到了（不是「够不着、只亮框」）",
      stats["completed"] == 1 and stats["pegged"] == 1,
      "→ 完成 %d · 踩到 %d · 只亮框 %d" % (stats["completed"],
                                            stats["pegged"], stats["box_only"]))
check("A5 只开了一批（够不着也不会反复重开）",
      stats["batches"] == 1, "→ %d 批" % stats["batches"])
check("A6 全程没有一条腿超过自己的长度", a["tip_max"] <= 0.995,
      "→ 最坏 %.4f×full" % a["tip_max"])
overlay.close()
QApplication.processEvents()


# ================================================================ B 八个词（原地定位，长条）
# 间距 180px、铺开 1260px：远超「不伸长时的腿展」，但仍在原地定位的
# 伸长上限（×%.1f）之内 —— 八个词必须全被踩到，一个都不许「只亮框」。
place(1240, 860)
LINE = [word(600 + i * 180, 860, "line%02d" % i) for i in range(8)]
b = run(LINE, max_seconds=60.0)
overlay = b["overlay"]
stats = overlay.session.stats()
check("B1 身体一步都没走（长条也不许走动）", b["path"] < 1e-6,
      "→ 位移 %.3fpx" % b["path"])
check("B2 腿长拉过 ×1.0（宽跨度全靠腿补）",
      b["stretch_max"] > 1.2, "→ 峰值 ×%.2f" % b["stretch_max"])
check("B3 八个词全部被腿踩到，没有一个「只亮框」",
      stats["completed"] == 8 and stats["box_only"] == 0,
      "→ 完成 %d · 踩到 %d · 只亮框 %d · 失败 %d"
      % (stats["completed"], stats["pegged"], stats["box_only"], stats["failed"]))
check("B4 只开了一批（没有 stall 反复重开、腿没被重新派过）",
      stats["batches"] == 1, "→ %d 批" % stats["batches"])
check("B5 每个目标最多完成一次",
      len({t.word_id for t in overlay.session.by_state(COMPLETED)}) == 8)
check("B6 全程没有一条腿超过自己的长度", b["tip_max"] <= 0.995,
      "→ 最坏 %.4f×full" % b["tip_max"])
overlay.close()
QApplication.processEvents()


# ================================================================ C 九个词（首批溢出）
place(240, 860)
NINE = [word(600 + (i % 5) * 300, 300 + (i // 5) * 260, "nine%02d" % i)
        for i in range(9)]
c = run(NINE, max_seconds=180.0)
overlay = c["overlay"]
stats = overlay.session.stats()
check("C1 9 个词全部进队列（第 9 个不再被丢掉）",
      stats["total"] == 9 and len(overlay._guides) == 9,
      "→ 队列 %d · 框 %d" % (stats["total"], len(overlay._guides)))
check("C2 分批真的发生（≥2 批）", stats["batches"] >= 2,
      "→ %d 批" % stats["batches"])
check("C3 9 个词全部完成", stats["completed"] == 9,
      "→ 完成 %d · 待办 %d · 在途 %d · 失败 %d"
      % (stats["completed"], stats["pending"], stats["active"], stats["failed"]))
check("C4 每个目标最多完成一次",
      len({t.word_id for t in overlay.session.by_state(COMPLETED)}) == 9)
check("C5 一批最多派 8 条腿（八腿=并行度，不是词数上限）",
      stats["active"] <= 8, "→ 在途 %d" % stats["active"])
check("C6 身体在走，不是钉在原地", c["path"] > 200.0,
      "→ 位移 %.0fpx" % c["path"])
check("C7 全程没有一条腿超过自己的长度", c["tip_max"] <= 0.995,
      "→ 最坏 %.4f×full" % c["tip_max"])
overlay.close()
QApplication.processEvents()


# ================================================================ D 16 个词（4×4）
place(240, 860)
GRID = [word(500 + col * 400, 200 + row * 220, "grid%02d" % (row * 4 + col))
        for row in range(4) for col in range(4)]
d = run(GRID, max_seconds=400.0)
overlay = d["overlay"]
stats = overlay.session.stats()
check("D1 16 个词全部完成", stats["completed"] == 16,
      "→ 完成 %d · 只亮框 %d · 失败 %d · 剩 %d"
      % (stats["completed"], stats["box_only"], stats["failed"],
         stats["remaining"]))
check("D2 每个目标最多完成一次",
      len({t.word_id for t in overlay.session.by_state(COMPLETED)}) == 16)
check("D3 至少 2 批（16 个词一批踩不完）", stats["batches"] >= 2,
      "→ %d 批" % stats["batches"])
check("D4 身体走过一半以上的停靠点", len(d["stops"]) >= 8,
      "→ %d/16 个" % len(d["stops"]))
# 剩下的词为什么可以不站过去：它们就在相邻停靠点**一腿之内**。
# 「不许隔空踩词」这件事由 D7 守：脚尖永远不出这条腿自己的长度。
check("D4b 没站过去的词也都是「踩到」而不是「只亮框」",
      stats["box_only"] == 0, "→ 只亮框 %d" % stats["box_only"])
check("D5 位移量级对得起 16 个词（≥2000px）", d["path"] >= 2000.0,
      "→ %.0fpx" % d["path"])
check("D6 腿长始终不超上限", d["stretch_max"] <= AO.AIM_LEG_STRETCH_MAX + 1e-9,
      "→ 峰值 ×%.3f" % d["stretch_max"])
check("D7 全程没有一条腿超过自己的长度", d["tip_max"] <= 0.995,
      "→ 最坏 %.4f×full" % d["tip_max"])
check("D8 一帧之内的位移有界（是走的/跳的，不是瞬移）",
      d.get("max_step", 0.0) <= 40.0, "→ 单帧最大 %.1fpx" % d.get("max_step", 0.0))
check("D9 统计与列表一致：完成+失败+跳过 == 16",
      stats["completed"] + stats["failed"] + stats["skipped"] == 16)
overlay.close()
QApplication.processEvents()


# ================================================================ E 暂停 / 继续 / 关闭
place(240, 860)


def mid_walk(overlay, frame):
    """停在「身体正在半路上」的时候。"""
    return overlay.mover.moving and frame > 5


e = run(NINE, max_seconds=60.0, until=mid_walk)
overlay = e["overlay"]
check("E0 截停时身体确实在半路", overlay.mover.moving,
      "→ mode=%s 距停靠点 %.0fpx" % (overlay.mover.movement_mode,
                                      overlay.mover.distance_to_waypoint()))
overlay._toggle_pause()
check("E1 暂停后队列状态是 paused", overlay.session.paused)
check("E2 暂停后身体立刻停了（不是只冻换批）", not overlay.mover.moving,
      "→ mode=%s" % overlay.mover.movement_mode)
frozen = overlay.mover.root
batch_frozen = overlay.session.stats()["batches"]
for _ in range(180):
    clock.t += STEP
    window._tick()
    overlay._tick()
check("E3 暂停期间身体一个像素都没动", overlay.mover.root == frozen,
      "→ %s vs %s" % (tuple(round(v, 1) for v in overlay.mover.root),
                      tuple(round(v, 1) for v in frozen)))
check("E4 暂停期间不再换批",
      overlay.session.stats()["batches"] == batch_frozen,
      "→ %d 批（暂停时 %d）" % (overlay.session.stats()["batches"], batch_frozen))
overlay._toggle_pause()
check("E5 继续之后身体重新朝**同一个**停靠点走",
      overlay.mover.current_waypoint is not None
      and overlay.mover.movement_mode in (locomotion.WALK, locomotion.ORIENT,
                                          locomotion.JUMP_PREPARE),
      "→ mode=%s" % overlay.mover.movement_mode)
for _ in range(3000):
    clock.t += STEP
    window._tick()
    overlay._tick()
    if overlay.session.stats()["completed"] == 9:
        break
check("E6 继续之后能走到完", overlay.session.stats()["completed"] == 9,
      "→ 完成 %d" % overlay.session.stats()["completed"])
overlay.close()
QApplication.processEvents()

# 中途关闭：`closeEvent` 必须把控制器停掉，否则覆盖层收了身体还在被拽着走
place(240, 860)
mid = AO.AimOverlay(window, NINE, stagger=PW.LEG_STAGGER)
mid.start()
for _ in range(60):
    clock.t += STEP
    window._tick()
    mid._tick()
mid.close()
QApplication.processEvents()
left = (float(window.center.x()), float(window.center.y()))
for _ in range(120):
    clock.t += STEP
    window._tick()
check("E7 关闭后身体不再被后台控制器拖着走",
      (float(window.center.x()), float(window.center.y())) == left,
      "→ %s vs %s" % ((window.center.x(), window.center.y()),
                      tuple(round(v) for v in left)))
check("E8 关闭后腿长归位", abs(window.spider.leg_stretch - 1.0) < 1e-9,
      "→ ×%.3f" % window.spider.leg_stretch)

print()
print("=" * 70)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    for name in FAIL:
        print("  FAILED: %s" % name)
    sys.exit(1)
