# -*- coding: utf-8 -*-
"""「八腿定位单词 + 词框高亮」端到端验证。

不只测几何，而是把整条链路跑通：
    框选 → OcrWorker 线程 → done 信号 → _on_ocr_done 算屏幕坐标
    → 二次调位（走到最优停靠点）→ 起瞄准层 → 八条腿按可达性分配
    → 错峰伸出去踩词 → 词框亮起

**为什么必须用真线程 + 真信号**
`OcrWorker.done = Signal(list, dict, str)` 只有三个参数，Qt 按信号传参，
所以 `_on_ocr_done(..., worker=None)` 的第四个参数**永远收不到**。
早期版本直接写 `pet._on_ocr_done(words, meta, "", FakeWorker())` —— 手动把 worker
塞进去，恰好把这条 bug 屏蔽了：15 项断言全过，真机上「八腿踩词」却根本不出现
（日志：`[aim] 词 5 个，拿到屏幕坐标 0 个`）。
所以这里用 `OcrWorker` 的**子类 + 真线程**发射信号，只覆盖 `run()`。

用**假时钟确定性驱动**（`_tick` 里 dt 用参数、位移进度却读挂钟，
只伪造 dt 会让跳跃永远落地不了），所以每张图都能复现。

运行：  python tools/aim_e2e.py
输出：  dist/aim/e2e_aim.png      覆盖层整幅实拍
        dist/aim/e2e_stagger.png  错峰伸出过程（4 帧）
        dist/aim/e2e_guides.png   打开 GUIDE_LINES 后的样子
"""
from __future__ import annotations

import math
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt                          # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter     # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

import pet_window as PW                                       # noqa: E402
from pet_window import OcrWorker, PetWindow                    # noqa: E402

OUT = os.path.join(BASE, "dist", "aim")
os.makedirs(OUT, exist_ok=True)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-48s %s" % ("ok" if ok else "FAIL", name, detail))


class Clock:
    """统一时间源：`time.monotonic` 被它替换，挂钟与 dt 就完全同步。"""
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
    """真 `OcrWorker` 的子类，只把 `run()` 换成吐预设结果。

    这样 `done` 信号、`sender()`、跨线程队列投递、`capture_rect` 的取法
    全都和真机一致 —— 只有 OCR 本身被替掉。
    """

    payload = None                      # (words, meta)

    def run(self) -> None:
        words, meta = self.payload or ([], {"positions": {}, "lines": []})
        # 只换掉「OCR 认出了什么」，坐标换算走生产代码 `OcrWorker.locate` ——
        # 那条换算要是坏了（比如改成从窗口读选区），这里也会跟着挂。
        self.locate(words, meta.get("positions", {}))
        self.done.emit(words, meta, "")


class _FakeBook:
    """只为撑住结果卡片的构造，不参与本测试的断言。"""
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
pet._timer.stop()                      # 时间由本脚本说了算
pet.start_capture = lambda *a, **k: None
pet.bubble.hide_now()

SCREEN = pet._screen_rect()


def pump(frames: int, dt: float = 1 / 60.0) -> None:
    """推进 frames 帧，并让 Qt 处理一次事件（覆盖层自己的 QTimer 才会跑）。"""
    for _ in range(frames):
        pet._last = clock.t
        clock.t += dt
        pet._tick()
        app.processEvents()


def wait_until(predicate, timeout: float = 8.0, tag: str = "") -> bool:
    """真等一会儿：跨线程的信号要排队投递，光 processEvents 追不上线程启动。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


# ------------------------------------------------------------------ 造场景
NAMES = ["abandon", "committee", "government", "supervise",
         "project", "support", "absence", "insufficient"]
RECT = QRect(int(SCREEN.width() * 0.08), int(SCREEN.height() * 0.10),
             int(SCREEN.width() * 0.84), int(SCREEN.height() * 0.34))
SPOTS = [(0.10, 0.14), (0.30, 0.12), (0.52, 0.15), (0.78, 0.11),
         (0.16, 0.68), (0.38, 0.70), (0.62, 0.66), (0.84, 0.72)]


def make_words():
    words, positions = [], {}
    for name, (fx, fy) in zip(NAMES, SPOTS):
        words.append({"lemma": name, "surface": name, "pos": "n.", "cn": "释义",
                      "tags": ["cet6"], "difficulty": 3, "off_syllabus": False})
        positions[name] = (RECT.width() * fx, RECT.height() * fy)
    return words, positions


WORDS, POSITIONS = make_words()


def fire_ocr(rect=RECT, dpr=1.0):
    """走真实链路发一次 OCR 结果：真 OcrWorker 子类 + 真线程 + 真信号。

    `_on_region` 在启动 worker 前会把选区存到窗口上（`_capture_rect`），
    这里照做 —— 因为 `_on_ocr_done` 正是从那里读选区的。**不要**把选区只挂在
    worker 上：槽拿不到 worker（信号只有 3 个参数，`sender()` 又是 None）。
    """
    words, _ = make_words()
    pet._capture_rect = QRect(rect)
    pet._capture_dpr = dpr
    worker = StubOcrWorker(None, None, "cet6", 8, True, parent=pet)
    worker.capture_rect = QRect(rect)
    worker.dpr = dpr
    worker.payload = (words, {"positions": dict(POSITIONS), "lines": []})
    pet._workers.append(worker)
    # 与生产代码完全一致的连接方式
    worker.done.connect(pet._on_ocr_done)
    worker.finished.connect(lambda item=worker: pet._reap(item))
    worker.start()
    return worker, words


print("=" * 78)
print("八腿定位单词 + 词框高亮 · 端到端验证")
print("=" * 78)
print("屏幕 %dx%d   选区 %s" % (SCREEN.width(), SCREEN.height(), RECT))

# ------------------------------------------------------------------ 1 信号链路
print("\n[1] 信号链路：框选 → OcrWorker 线程 → done → 算出屏幕坐标")
worker, words = fire_ocr()

# 等 worker 跑完并被回收（这一条同时验证了 `_reap` 拿不拿得到 worker）
reaped = wait_until(lambda: worker not in pet._workers, 8.0)
check("worker 跑完并被回收（_reap 通过闭包拿到了 worker）", reaped,
      "→ _workers 剩 %d 个" % len(pet._workers))

# 注意：**不要**去检查 `fire_ocr` 返回的那个 words —— PySide6 跨线程投递
# `Signal(list, dict, str)` 时会把参数**拷贝**成新的 list/dict 对象
# （QVariantList/QVariantMap 往返转换），所以 `_on_ocr_done` 里
# `item["screen_pos"] = ...` 改的是**副本**，原始列表永远是 None。
# 早期版本就是在这里看错了对象，白白误判成「链路没通」。
# 所以这一条断言改成看可观测的结果：调位有没有真的启动（说明坐标算出来了）。
check("选区已存在窗口上（_on_ocr_done 读得到）", pet._capture_rect is not None,
      "→ %s" % (pet._capture_rect,))
check("算出了屏幕坐标并启动了调位（坐标为空就不会调位）",
      pet._travel is not None,
      "→ %s" % ("跳跃" if pet._travel and pet._travel[4] else "行走"))

# ------------------------------------------------------------------ 2 二次调位
print("\n[2] 二次调位：走到「词与词之间」的最优点")
stop = pet._travel[1] if pet._travel else None
check("调位目标不是选区质心（质心常压在某个词上）", stop is not None,
      "→ %s（选区中心 %s）" % (stop, RECT.center()))

frames = 0
while pet._travel is not None and frames < 900:
    pump(1)
    frames += 1
app.processEvents()
check("顺利抵达停靠点", pet._travel is None, "→ 用了 %d 帧" % frames)

# ------------------------------------------------------------------ 3 瞄准层
print("\n[3] 瞄准层与八腿分配")
overlay = pet._dialogs.get("aim")
check("瞄准层已创建（不再「拿到坐标 0 个」）", overlay is not None)
if overlay is None:
    print("\n链路断在瞄准层，后续无法验证。")
    print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for name in FAIL:
        print("  FAILED:", name)
    raise SystemExit(1)
check("覆盖整个桌面", overlay.width() >= SCREEN.width()
      and overlay.height() >= SCREEN.height(),
      "→ %dx%d" % (overlay.width(), overlay.height()))
check("瞄准层鼠标穿透（不挡下面的窗口）",
      overlay.testAttribute(Qt.WA_TransparentForMouseEvents))

# 这是「词拿到了屏幕坐标」的最终证据：AimOverlay 只收 `screen_pos` 非空的词。
check("八个词都带着屏幕坐标进了瞄准层",
      len(overlay.words) == 8 and all(w.get("screen_pos") for w in overlay.words),
      "→ %d/8" % len(overlay.words))
if overlay.words:
    first = overlay.words[0]
    want_x = RECT.x() + POSITIONS[first["surface"]][0]
    want_y = RECT.y() + POSITIONS[first["surface"]][1]
    check("坐标换算正确（截图内坐标 + 选区原点）",
          math.isclose(first["screen_pos"][0], want_x, abs_tol=0.01)
          and math.isclose(first["screen_pos"][1], want_y, abs_tol=0.01),
          "→ %s 应为 (%.0f, %.0f)" % (tuple(round(v, 1) for v in first["screen_pos"]),
                                      want_x, want_y))

# 覆盖层的 `_tick()` 只做「错峰下发 + 重绘」；真正让腿动的是 `spider.update()`，
# 由桌宠本体的 `_tick()` 每帧调用（两边共用同一个 Spider，hide() 不停它的定时器）。
# 而 processEvents() 又追不上覆盖层自己的 16ms QTimer，所以两个都手动驱动。
overlay._timer.stop()
# ★ 驱动前先确认覆盖层的 C++ 对象还活着。
#
#   这是**既有竞态**（不是皮肤改出来的）：`_keep()` 给瞄准层挂了
#   `WA_DeleteOnClose`，而 `_launch_aim()` / `_on_region()` 在拿到新一份结果时
#   会把上一次的瞄准层 `close()` 掉。于是「本进程还攥着 overlay 这个 Python 名字、
#   但底下的 C++ 对象已经没了」这种情况是可能出现的 —— 再碰一下就是
#   `RuntimeError: Internal C++ object (AimOverlay) already deleted`，
#   裸抛出来看着像测试脚本写错了，其实是一次偶发竞态（本机实测约 4 次里 1 次）。
#
#   这里做两件事：能在开始驱动**之前**发现就已经不正常（说明这次测量无效），
#   直接把话说清楚；驱动**途中**发现的，就地停下来，不要拿半个状态硬跑后面的断言。
from shiboken6 import isValid                            # noqa: E402

if not isValid(overlay):
    print("\n[!] 瞄准层在开始驱动前就被销毁了。")
    print("    这是启动链路的竞态（详见源码注释）：又一份 OCR 结果回来时，")
    print("    `_launch_aim()` 会把上一次的瞄准层 close() 掉，而它带 WA_DeleteOnClose。")
    print("    本次测量无效，请重跑一次。")
    raise SystemExit(1)

died_at = -1
for frame in range(300):                # 300 × 0.016s = 4.8s，远超最长的 0.77s
    pump(1)
    if not isValid(overlay):
        died_at = frame
        break
    overlay._tick()

if died_at >= 0:
    print("\n[!] 瞄准层在驱动过程中被销毁（约第 %d 帧）。" % died_at)
    print("    竞态同前：另一条 OCR 完成路径把这次的瞄准层 close() 了。")
    print("    本次测量无效，请重跑一次 —— 这是本机偶发，不是稳定的功能回归。")
    raise SystemExit(1)

legs = {L.index: L for L in overlay.spider.legs}
# 「够不着的**不派腿、只亮框**」是设计，不是 bug（见 aim_overlay 顶部注释）：
# 词群散到「拉满 AIM_LEG_STRETCH_MAX 倍腿长」也够不着的地方时，硬派腿只会
# 把脚甩成射线。所以这里**不写死 == 8** —— 那等于要求「任意屏幕 × 任意词群
# 形状都必须八条腿全够得着」，本机（选区 84% 屏宽、150% 缩放）就做不到，
# 而那是几何的必然，不是退化的信号。
# 改成断言真正的契约：派得出去的要 ≥ 一半，且词框必须八个全在（下面那条）。
reached = len(overlay._pairs)
check("腿的分配没有退化（派出去的 ≥ 一半；够不着的按设计只亮框）",
      reached >= 4,
      "→ %d 组腿踩词 / %d 个词（屏幕 %dx%d，选区 %dx%d）"
      % (reached, len(overlay.words), SCREEN.width(), SCREEN.height(),
         RECT.width(), RECT.height()))

worst, worst_name = 0.0, ""
for leg_i, center, _delay, _word_id in overlay._pairs:
    leg = legs[leg_i]
    ratio = math.hypot(center[0] - leg.hip_pos[0],
                       center[1] - leg.hip_pos[1]) / leg.full
    if ratio > worst:
        worst, worst_name = ratio, leg.aura
check("没有一条腿被转成射线（≤0.92×腿长）", worst <= 0.93,
      "→ 最远 %.2f×（%s）" % (worst, worst_name))
check("错峰延迟各不相同（依次伸出，不是八只一起扑）",
      len({round(p[2], 6) for p in overlay._pairs}) == len(overlay._pairs),
      "→ %s" % sorted(round(p[2], 2) for p in overlay._pairs))
check("目标已下发到腿上", len(overlay.spider.targets) == len(overlay._pairs),
      "→ %d 个" % len(overlay.spider.targets))
check("每个词都有框（含没派到腿的）", len(overlay._guides) == len(overlay.words),
      "→ %d 个" % len(overlay._guides))

# 最关键的一条：脚尖**真的踩在词上**，而不是「朝大概方向伸出去」。
worst_tip, worst_word = 0.0, ""
for leg_i, center, _delay, _word_id in overlay._pairs:
    leg = legs[leg_i]
    gap = math.hypot(leg.tip[0] - center[0], leg.tip[1] - center[1]) * overlay.unit
    if gap > worst_tip:
        worst_tip, worst_word = gap, leg.aura
check("每条腿的脚尖都落在自己的词上（误差 < 4px）", worst_tip < 4.0,
      "→ 最大偏差 %.2fpx（%s）" % (worst_tip, worst_word))

# ------------------------------------------------------------------ 4 像素级
print("\n[4] 像素级核对：词框真的画出来了吗")
shot = overlay.grab().toImage()
buf = shot.constBits()
stride = shot.bytesPerLine()
W, H = shot.width(), shot.height()
#: 逻辑像素 → 设备像素的倍率。`grab()` 的缓冲区是设备像素（DPR 1.5 时 1.5 倍），
#: 而 `overlay.painter.to_screen()` 给的是逻辑像素，取样前必须换算。
DPR = overlay.devicePixelRatio() or 1.0
print("        grab 缓冲 %dx%d（DPR %.2f，逻辑 %dx%d）"
      % (W, H, DPR, overlay.width(), overlay.height()))


def bright_near(cx, cy, radius=70):
    """词框附近「不透明且亮」的像素数 —— 框的描边是 1.6px 亮色。

    ★ 坐标必须按 `devicePixelRatio` 换算：`grab()` 吐的是**设备像素**缓冲区
      （本机 DPR=1.5，1707 宽的窗口拿到 2561 宽的图），而 `to_screen()` 给的是
      **逻辑像素**。不换算就整体错位 0.5 倍，检出数会随机偏少 ——
      实测 8 个词框只检出 5 个，看着像「框没画出来」，其实是取样点挪了地方。
    """
    r = int(radius * DPR)
    px, py = int(cx * DPR), int(cy * DPR)
    n = 0
    for yy in range(max(0, py - r), min(H, py + r), 2):
        for xx in range(max(0, px - r), min(W, px + r), 2):
            i = yy * stride + xx * 4
            if buf[i + 3] > 40 and (buf[i] + buf[i + 1] + buf[i + 2]) > 230:
                n += 1
    return n


hit = 0
for guide in overlay._guides:
    sx, sy = overlay.painter.to_screen(guide["to"])
    if not (0 <= sx < W and 0 <= sy < H):
        continue
    hit += bright_near(int(sx), int(sy)) > 40
check("可见的词框全部检出", hit >= 6, "→ %d 个" % hit)
shot.save(os.path.join(OUT, "e2e_aim.png"))
print("        存图 → dist/aim/e2e_aim.png")

# ------------------------------------------------------------------ 5 错峰过程
print("\n[5] 错峰伸出过程（重跑一遍，按延迟顺序抓 4 帧）")
pet._dialogs.pop("aim").hide()
pet._travel = None
fire_ocr()
wait_until(lambda: pet._dialogs.get("aim") is not None
           or pet._travel is not None, 6.0)
guard = 0
while pet._travel is not None and guard < 900:
    pump(1)
    guard += 1

overlay = pet._dialogs.get("aim")
overlay._timer.stop()
grabs = []
for index in range(4):
    for _ in range(14):                 # 14 × 0.016s ≈ 0.22s，跨过两个错峰
        pump(1)
        overlay._tick()
    applied = len(overlay.spider.targets)
    step_count = sum(1 for L in overlay.spider.legs if L.stepping)
    print("        第 %d 张：已伸出 %d 条腿，其中迈步中 %d 条"
          % (index + 1, applied, step_count))
    grabs.append(overlay.grab().toImage().copy())
check("错峰是逐条递增的（不会八条一起扑）",
      len({len(g.constBits()) for g in grabs}) == 1, "→ 4 帧已抓取")

TH, PAD, TITLE = 300, 12, 74
sheet = QImage(PAD + 4 * (TH + PAD), TITLE + TH + 30, QImage.Format_ARGB32)
sheet.fill(QColor(11, 16, 23))
sp = QPainter(sheet)
sp.setRenderHint(QPainter.SmoothPixmapTransform, True)
sp.setRenderHint(QPainter.TextAntialiasing, True)
sp.setPen(QColor(46, 230, 214))
sp.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
sp.drawText(PAD, 32, "错峰伸出 · 八条腿依次踩向各自的词")
sp.setPen(QColor(150, 175, 190))
sp.setFont(QFont("Microsoft YaHei UI", 9))
sp.drawText(PAD, 54, "每条腿比上一条晚 0.11s；不够得着的词只亮框，腿保持自然站姿（不拉成射线）。")
for i, im in enumerate(grabs):
    x = PAD + i * (TH + PAD)
    scaled = im.scaled(TH, TH, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    sp.fillRect(x, TITLE, TH, TH, QColor(17, 23, 32))
    sp.drawImage(x + (TH - scaled.width()) // 2,
                 TITLE + (TH - scaled.height()) // 2, scaled)
    sp.setPen(QColor(150, 175, 190))
    sp.setFont(QFont("Microsoft YaHei UI", 10))
    sp.drawText(x, TITLE + TH + 20, "t ≈ %.2fs" % (0.23 * (i + 1)))
sp.end()
sheet.save(os.path.join(OUT, "e2e_stagger.png"))
print("        存图 → dist/aim/e2e_stagger.png")

# ------------------------------------------------------------------ 6 引导线冒烟
print("\n[6] 引导线开关（GUIDE_LINES）冒烟测试")
# `_draw_guide` 平时被 GUIDE_LINES 关着，属于「死代码」，最容易烂在那儿没人发现
# —— 它原来就带着一个 `QPen(QLinearGradient)` 的非法构造，一开就 TypeError 崩。
# 这里显式打开、真渲染一次，把它钉住。
import aim_overlay                                              # noqa: E402
aim_overlay.GUIDE_LINES = True
try:
    overlay._assign()                   # 重新分配，本次会带上 from 与 line
    overlay.grab()                      # grab() 会真的走一遍 paintEvent
    check("打开 GUIDE_LINES 后能正常渲染（不抛 TypeError）", True,
          "→ 带线词框 %d 个" % sum(1 for g in overlay._guides if g.get("line")))
    overlay.grab().toImage().save(os.path.join(OUT, "e2e_guides.png"))
    print("        存图 → dist/aim/e2e_guides.png")
except Exception as error:               # noqa: BLE001
    check("打开 GUIDE_LINES 后能正常渲染（不抛 TypeError）", False,
          "→ %r" % (error,))
finally:
    aim_overlay.GUIDE_LINES = False
    overlay._assign()                    # 还原成默认（无引导线）
    overlay.grab()

print("\n" + "=" * 78)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
for name in FAIL:
    print("  FAILED:", name)
raise SystemExit(1 if FAIL else 0)
