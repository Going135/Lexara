# -*- coding: utf-8 -*-
"""感应覆盖层（§7.2）：穿透不吞点击、射线从身体出发、提示会自己淡掉。

这一层最要命的两条是「不劫持输入」和「腿不参与」，都在真鼠标的钩子里，
所以这里用**伪造钩子参数**（ctypes 造一个 `MSLLHOOKSTRUCT`）来验，
不需要真的动鼠标；绘制用 `grab()` 走一遍 `paintEvent`，把三样东西都画出来。

`pet` 用一个只有 `center` 的桩：覆盖层对桌宠的全部要求就是体心坐标
（射线起点、状态条位置）和可选的 `_sense_log`。

★ 运行方式：直接 `python test/test_sense_overlay.py`，**不要**在外面设
  `QT_QPA_PLATFORM=windows`（下面第 17 行是 `setdefault`，外部值会盖掉它）。
  [3] 的命中判定和 [9] 的状态条取样是按 offscreen 那块 DPR=1 的虚拟屏写的，
  换成真屏（本机 1.5 倍缩放）这两条会红 —— 那是测试口径，不是产品缺陷，
  2026-10-18 就这么误判过一次。真 OCR 的测试才需要禁 offscreen。
"""
import ctypes
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt                       # noqa: E402
from PySide6.QtGui import QImage                            # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

import sense_overlay as SO                                  # noqa: E402
from sense_overlay import SenseOverlay                      # noqa: E402
from sense_session import SenseSession                      # noqa: E402

APP = QApplication(sys.argv)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-52s %s" % ("ok" if ok else "FAIL", name, detail))


class Clock:
    """伪造 `time.monotonic`：淡出与过期不该靠挂钟才能测。"""

    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def advance(self, ms):
        self.t += ms / 1000.0


class LegStub:
    """一条腿的「目标表」。感应层要是碰了它，就说明腿被拉去踩词了（§7.2 禁止）。"""

    def __init__(self, index):
        self.index = index
        self.target = None
        self.aimed = False


class SpiderStub:
    def __init__(self):
        self.legs = [LegStub(i) for i in range(8)]
        self.touches = []

    def set_target(self, *args, **kwargs):
        self.touches.append(("set_target", args, kwargs))

    def snapshot(self):
        return [(leg.target, leg.aimed) for leg in self.legs]


class FakePet:
    """覆盖层对桌宠的全部要求：体心坐标（射线起点、状态条位置）+ 可选的 `_sense_log`。

    `spider` 只是**放在那儿让它能误碰**的诱饵：真的被碰了就会被记下来。
    """

    def __init__(self):
        self.center = QPoint(1200, 700)
        self.spider = SpiderStub()
        self.logs = []

    def _sense_log(self, message):
        self.logs.append(message)


def _leg_writes_in_source():
    """源码级兜底：覆盖层里出现「给腿设目标」的写法就直接判失败。

    只查**写入形式**，不查 `spider` 这个词 —— 模块注释里就写着
    「不碰 `pet.spider` 的任何目标」，按整词匹配会把说明当成违规。
    """
    path = os.path.join(BASE, "src", "sense_overlay.py")
    with open(path, encoding="utf-8") as handle:
        src = handle.read()
    return [tok for tok in ("set_target", ".target =", ".aimed =", "spider.legs")
            if tok in src]


def notice(box=(900.0, 500.0, 70.0, 20.0), point=(935.0, 510.0)):
    item = {"surface": "lexara", "lemma": "lexara", "meaning": "假释义"}
    if box is not None:
        item["screen_box"] = box
    if point is not None:
        item["screen_pos"] = point
    return item


def make_overlay(session=None):
    pet = FakePet()
    session = session or SenseSession()
    session.start()
    clicked = []
    overlay = SenseOverlay(pet, session, on_word_click=lambda item: clicked.append(item))
    overlay.setGeometry(0, 0, 1920, 1080)
    overlay._offset = QPoint(0, 0)
    return overlay, pet, session, clicked


def fake_l_param(x, y):
    """造一个真的 `MSLLHOOKSTRUCT*`（钩子回调拿到的就是这个）。"""
    info = SO.MSLLHOOKSTRUCT()
    info.pt.x = int(x)
    info.pt.y = int(y)
    return ctypes.cast(ctypes.byref(info), ctypes.c_void_p).value, info


def main():
    print("[1] 窗口属性：全屏穿透、不抢焦点、不吞点击")
    overlay, pet, session, clicked = make_overlay()
    flags = overlay.windowFlags()
    check("WA_TransparentForMouseEvents",
          overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
    check("Qt.WindowTransparentForInput",
          bool(flags & Qt.WindowTransparentForInput))
    check("WA_ShowWithoutActivating（不抢视频/游戏的焦点）",
          overlay.testAttribute(Qt.WA_ShowWithoutActivating))
    check("WA_TranslucentBackground（不遮住底下内容）",
          overlay.testAttribute(Qt.WA_TranslucentBackground))
    check("不置顶之外的窗口类型里仍是无边框 Tool 窗",
          bool(flags & Qt.Tool) and bool(flags & Qt.FramelessWindowHint))
    # 「不遮挡视频控制」的可验形式：这一层没有任何不透明的实心块盖住屏幕，
    # 只有状态条与细边框 —— 用 grab 的 alpha 通道量一下覆盖率。
    overlay.show_notice(notice())
    image = overlay.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    w, h = image.width(), image.height()
    opaque = 0
    step = 7
    for yy in range(0, h, step):
        for xx in range(0, w, step):
            if (image.pixel(xx, yy) >> 24) > 200:
                opaque += 1
    total = len(range(0, h, step)) * len(range(0, w, step))
    ratio = opaque / float(total or 1)
    check("实心不透明覆盖率 < 8%%（实测 %.2f%%）" % (ratio * 100), ratio < 0.08,
          "→ 状态条 + 细边框以外的地方都能看见底下的视频")

    print("\n[2] 提示的生命周期：会自己淡掉，不留残影")
    clock = Clock()
    real_time = SO.time
    SO.time = clock
    try:
        overlay.show_notice(notice())
        check("show_notice 后有待画提示", overlay._notice is not None)
        clock.advance(SO.RAY_MS - 60)
        overlay._tick()
        check("射线时长内仍在（%.0fms）" % SO.RAY_MS, overlay._notice is not None)
        clock.advance(SO.FLASH_MS)
        overlay._tick()
        check("超过 max(RAY_MS, FLASH_MS) 后自动清空", overlay._notice is None)
        # 没有落点的词不画（宁可不闪，也不闪到一个不存在的位置）
        overlay.show_notice(notice(point=None))
        check("没有 screen_pos 的词不提示", overlay._notice is None)
        # 没有词本体框 → 退化成落点附近的小框，而不是不提示
        overlay.show_notice(notice(box=None))
        box = overlay._notice["box"]
        check("缺 screen_box 时退化成落点小框（仍有视觉回执）",
              box is not None and box[2] > 0 and box[3] > 0, "→ %s" % (box,))
        SO.time = real_time
    finally:
        SO.time = real_time

    print("\n[3] 全局钩子：只观察，一次都不吞")
    overlay, pet, session, clicked = make_overlay()
    overlay._notice = None
    # 钩子跑在系统消息泵里，测试不能真的装钩子（会拦住真鼠标），
    # 所以直接调回调：`_hook` 为 0 时 CallNextHookEx 只是返回 0，无副作用。
    l_param, _keep = fake_l_param(935, 510)
    ret = overlay._hook_proc(SO.HC_ACTION, SO.WM_LBUTTONDOWN, l_param)
    check("没有提示时不记点击", overlay._clicked is False)
    overlay.show_notice(notice())
    ret = overlay._hook_proc(SO.HC_ACTION, SO.WM_LBUTTONDOWN, l_param)
    check("点中高亮的词 → 记下这一笔", overlay._clicked is True)
    check("回调返回值不是 1（返回 1 = 吞掉这一次点击）", ret != 1, "→ ret=%s" % (ret,))
    overlay._clicked = False
    _l2, _keep2 = fake_l_param(100, 100)
    overlay._hook_proc(SO.HC_ACTION, SO.WM_LBUTTONDOWN, _l2)
    check("点在高亮框外面 → 不算点词", overlay._clicked is False)
    # 移动事件一律不管（只认左键按下）
    overlay._clicked = False
    overlay._hook_proc(SO.HC_ACTION, SO.WM_LBUTTONDOWN + 1, l_param)
    check("鼠标移动 / 其他消息不改状态", overlay._clicked is False)

    print("\n[4] DPR：钩子给物理像素，词框是逻辑像素")
    overlay, pet, session, clicked = make_overlay()
    overlay.show_notice(notice())
    original = overlay.devicePixelRatioF
    try:
        overlay.devicePixelRatioF = lambda: 1.5            # 150% 缩放
        check("150% 下物理点被换算回逻辑坐标",
              overlay._logical_point(type("P", (), {"x": 1350, "y": 750})())
              == (900.0, 500.0),
              "→ (1350,750)/1.5 = (900,500) 正好是词框左上角")
        overlay._clicked = False
        l_param, _k = fake_l_param(1350 + 20, 750 + 10)     # 框内（物理）
        overlay._hook_proc(SO.HC_ACTION, SO.WM_LBUTTONDOWN, l_param)
        check("150% 缩放下点词仍然命中（不除 DPR 就会点空）",
              overlay._clicked is True)
    finally:
        overlay.devicePixelRatioF = original

    print("\n[5] 点了词 → 交回桌宠弹本地释义，提示立刻让位")
    overlay, pet, session, clicked = make_overlay()
    item = notice()
    overlay.show_notice(item)
    overlay._clicked = True
    overlay._tick()
    check("回调收到那个词本身", len(clicked) == 1 and clicked[0] is item)
    check("开卡后提示清空（不会重复触发）", overlay._notice is None)
    overlay._tick()
    check("再 tick 一次不会重复开卡", len(clicked) == 1)

    print("\n[6] 射线从**身体**出发，不从脚；腿的目标表一次都不碰（§7.2）")
    overlay, pet, session, clicked = make_overlay()
    pet.center = QPoint(1200, 700)
    legs_before = pet.spider.snapshot()
    item = notice(point=(1500.0, 700.0))
    overlay.show_notice(item)
    fills, rects = [], []

    class Recorder:
        def fillPath(self, *args):
            fills.append(args)

        def setPen(self, *a): pass
        def setBrush(self, *a): pass
        def drawRoundedRect(self, *a): rects.append(a)

    clock = Clock()
    real_time = SO.time
    SO.time = clock
    try:
        rec = Recorder()
        overlay._notice["t0"] = clock.t
        overlay._draw_ray(rec)
        check("射线被画出来了（一次 fillPath）", len(fills) == 1)
        box = fills[0][0].boundingRect() if fills else None
        check("射线起点在体心之后（前半段不画，避免糊在身体上）",
              box is not None and box.left() > 1200 + 20,
              "→ 最左端 x≈%.0f，体心 x=1200" % (box.left() if box else -1))
        check("射线末端到达词的位置",
              box is not None and abs(box.right() - 1500.0) < 2.0,
              "→ 右端 x≈%.0f，词在 1500" % (box.right() if box else -1))

        # 高亮框画在**词本体**上（§7.2「词本体上闪一下细边框」）
        overlay._draw_flash(rec)
        check("高亮框贴着词框画（含外扩）",
              bool(rects) and abs(rects[-1][0] - (900.0 - SO.BOX_PAD)) < 0.5
              and abs(rects[-1][2] - (70.0 + SO.BOX_PAD * 2)) < 0.5,
              "→ %s" % (rects[-1][:4] if rects else None,))

        check("提示全程没有调用 spider.set_target", pet.spider.touches == [])
        check("提示前后腿的目标表没有变化", pet.spider.snapshot() == legs_before)
        bad = _leg_writes_in_source()
        check("覆盖层源码里没有任何「给腿设目标」的写法", bad == [], "→ %s" % (bad,))

        # 距离很近时（<120px）不该跳过前半段，否则射线会看不见
        fills.clear()
        overlay.show_notice(notice(point=(1240.0, 700.0)))
        overlay._notice["t0"] = clock.t
        overlay._draw_ray(Recorder())
        check("近距离词也画射线（不从 0.32 处起笔）",
              bool(fills) and fills[0][0].boundingRect().left() <= 1200 + 1,
              "→ 左端 x≈%.0f" % (fills[0][0].boundingRect().left() if fills else -1))
    finally:
        SO.time = real_time

    print("\n[7] 状态条文案（§7.3）+ 装不上钩子不关掉模式")
    overlay, pet, session, clicked = make_overlay()
    session.note_words("r0c0", [notice()], 300.0)
    text = session.status_text()
    check("状态条含「感应中 / 本地识别 / 最近扫描」",
          all(k in text for k in ("感应中", "本地识别", "最近扫描")), "→ %s" % text)
    # 模拟 SetWindowsHookEx 失败：`start()` 只记一笔，模式继续
    overlay._hook_cb = None
    real_set = SO._USER32.SetWindowsHookExW
    SO._USER32.SetWindowsHookExW = lambda *a: 0
    try:
        overlay.start()
        check("钩子装不上 → 只记说明，不报错、不关模式",
              "钩子" in (session.note or "") or "钩子" in "".join(pet.logs))
    finally:
        SO._USER32.SetWindowsHookExW = real_set
    overlay.close()

    print("\n[8] 关闭即清理：定时器停、钩子卸、回调断开")
    check("closeEvent 后 timer 已停", overlay._timer.isActive() is False)
    check("closeEvent 后钩子句柄已清", overlay._hook is None
          and overlay._hook_cb is None)
    check("closeEvent 后不再持有释义回调（防悬挂引用）",
          overlay.on_word_click is None)

    print("\n[9] 状态条几何同源：`chip_rect()` 要真罩得住画出来的那一块")
    overlay, pet, session, clicked = make_overlay()
    pet.center = QPoint(1200, 700)
    check("_local 同时吃 QPoint 与 tuple（桌宠的 center 是 QPoint）",
          overlay._local(QPoint(100, 200)) == (100.0, 200.0)
          and overlay._local((100, 200)) == (100.0, 200.0),
          "→ 只写下标的话 QPoint 每帧在 paintEvent 里抛 TypeError，提示全瞎")
    rect = overlay.chip_rect()
    image = overlay.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    x0, y0 = int(rect[0]), int(rect[1])
    x1, y1 = x0 + int(rect[2]), y0 + int(rect[3])
    ink = 0
    for yy in range(y0, min(image.height(), y1), 3):
        for xx in range(x0, min(image.width(), x1), 3):
            if (image.pixel(xx, yy) >> 24) > 200:
                ink += 1
    check("chip_rect 里确实画着状态条（排除区挡得住自己那行字）", ink > 20,
          "→ %d 个采样点 · 框=%s" % (ink, tuple(int(v) for v in rect)))
    check("状态条贴在蜘蛛旁边（不在屏幕角上压着任务栏/视频控件）",
          abs((rect[0] + rect[2] / 2) - 1200) < rect[2] / 2 + 1
          and rect[1] > 700, "→ 中心 x=%.0f，y=%.0f，蜘蛛在 (1200,700)"
          % (rect[0] + rect[2] / 2, rect[1]))
    overlay.close()

    print("\n" + "=" * 78)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for name in FAIL:
        print("  FAILED:", name)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
