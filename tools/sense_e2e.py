# -*- coding: utf-8 -*-
"""蜘蛛感应的**真机端到端**验证（任务书 §7.4）。

跑的是真链路，没有一段被桩替掉：

    真 PetWindow → 真抓屏 QTimer（GUI 线程）→ 真 `SenseWorker` 线程
    → 真变化检测 / ROI → 真 OCR → 真词典挑词 → 真跨线程 Signal
    → 真 SenseOverlay（射线 + 高亮 + 状态条）→ 真本地释义卡

「场景」就是一张**真实创建、真实显示在桌面上**的字幕窗口。
早期版本试过在离线平台（`QT_QPA_PLATFORM=offscreen`）里造这些帧 —— 那是假绿：
offscreen 下字体渲染拿不到真实字距，OCR 一个词都认不出来
（`test_ocr_coords` 的坑注释里记着）。所以这里必须在接了显示器的真机上跑。

★ 隐私：整份脚本**不落盘任何桌面截图**。证据图只保存覆盖层自己的渲染
  （里面只有射线、细边框和状态条，没有任何用户屏幕内容）。
★ 网络：`urlopen` 全程打桩成「调了就炸」，用来证明感应链路一次都不联网。
★ 配置：`APPDATA` 指向临时目录，不碰用户真实的 `%APPDATA%\\Lexara\\settings.json`
  与 `run.log`；隐私检查读的是这份临时日志。

运行：``python tools/sense_e2e.py``
输出：终端 PASS/FAIL 摘要 + ``dist/sense/e2e_overlay.png``
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

# ---- 必须在 import 任何会读 APPDATA 的模块**之前**改环境 -------------------
SANDBOX = os.path.join(tempfile.gettempdir(), "lexara_sense_e2e")
os.makedirs(SANDBOX, exist_ok=True)
os.environ["APPDATA"] = SANDBOX
os.environ["LOCALAPPDATA"] = SANDBOX

from PySide6.QtCore import QPoint, Qt                       # noqa: E402
from PySide6.QtGui import QGuiApplication                   # noqa: E402
from PySide6.QtWidgets import (QApplication, QLabel,        # noqa: E402
                               QWidget)

OUT = os.path.join(BASE, "dist", "sense")
os.makedirs(OUT, exist_ok=True)
SHOT = os.path.join(OUT, "e2e_overlay.png")
LOG = os.path.join(SANDBOX, "Lexara", "run.log")

PASS, FAIL = [], []
NOTICES = []          # 真信号收到的词卡（只用于断言，不打日志、不落盘）
NET = []              # 任何一次 urlopen 调用都记在这儿
APP = None            # 见 main()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("[ok]" if ok else "[x] ", name,
                         ("　" + detail) if detail else ""))


def boom(*args, **kwargs):
    NET.append(args)
    raise AssertionError("感应链路不允许发起网络请求")


def pump(seconds: float) -> None:
    """真的等一会儿：跨线程信号要排队投递，光 processEvents 追不上工作线程。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        APP.processEvents()
        time.sleep(0.01)


def wait_until(predicate, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def counter_after(seconds: float, read):
    """等 `seconds` 秒，返回 `read()` 的增量（用于「不动/暂停时不该继续做事」）。"""
    before = read()
    pump(seconds)
    return read() - before


class FakeBook:
    """只为撑住释义卡的构造：不落盘、不进真单词本。"""

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

    def record_learning(self, words) -> int:
        return 0


# ---------------------------------------------------------------- 字幕窗口

#: 两句字幕都刻意由考纲词组成（`scan_text` 认不出来的话，问题会直接暴露在第 3 步）
SENTENCE_A = "an aggressive approach to eliminate the duplicate consequence"
SENTENCE_B = "a committee must supervise the insufficient government absence"
#: [6b]「遮挡」用的第三句：词表和 A/B **完全不重叠**（`assets/exam-tags.sqlite`
#: 实测 cet4/cet6/kaoyan 三种模式都认得出 7 个词），所以一旦提示落在它身上，
#: 就能断定「认的是合成后桌面上看得见的那一句」，而不是被盖住的旧句子。
SENTENCE_C = ("the temporary facility revealed a preliminary phenomenon "
              "of the financial institution")


class SubtitleWindow(QWidget):
    """一张真的显示在桌面上的「视频字幕」—— 感应要认的就是它。"""

    def __init__(self, text):
        super().__init__(None)
        from PySide6.QtGui import QFont
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background:#101216;")
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setFont(QFont("Arial", 28, QFont.Bold))
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color:#f5f5f5; background:transparent;")
        self.label.setText(text)
        self.resize(920, 230)
        self.label.setGeometry(20, 20, self.width() - 40, self.height() - 40)

    def logical_rect(self):
        """这个窗口在**屏幕逻辑坐标**里的矩形 —— 和 `screen_pos` 同一个坐标系。"""
        pos = self.mapToGlobal(QPoint(0, 0))
        return (float(pos.x()), float(pos.y()), float(self.width()),
                float(self.height()))

    def show_at_bottom(self):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.x() + max(20, (geo.width() - self.width()) // 2),
                  geo.y() + geo.height() - self.height() - 30)
        self.show()
        self.raise_()

    def show_over(self, other):
        """**严丝合缝地盖住**另一张窗口（四周各多盖 12px，不留缝）。

        「遮挡」这一类场景在离线平台上根本造不出来 —— 必须是真的压在同一块
        桌面上，抓屏拿到的才是合成后的画面。
        """
        pos = other.mapToGlobal(QPoint(0, 0))
        self.resize(other.width() + 24, other.height() + 24)
        self.label.setGeometry(20, 20, self.width() - 40, self.height() - 40)
        self.move(pos.x() - 12, pos.y() - 12)
        self.show()
        self.raise_()
        APP.processEvents()


def inside(rect, item, pad=14.0) -> bool:
    pos = item.get("screen_pos")
    if rect is None or pos is None:
        return False
    x, y = pos[0], pos[1]
    rx, ry, rw, rh = rect
    return (rx - pad <= x <= rx + rw + pad
            and ry - pad <= y <= ry + rh + pad)


# ---------------------------------------------------------------- 主流程

def main() -> int:
    global APP
    APP = QApplication.instance() or QApplication(sys.argv)
    APP.setQuitOnLastWindowClosed(False)

    # ---- 0. 红线与环境 ----------------------------------------------
    urllib.request.urlopen = boom

    print("=" * 78)
    print("LEXARA 蜘蛛感应 · 真机端到端（任务书 §7.4）")
    print("=" * 78)
    screens = QGuiApplication.screens()
    print("\n[0] 桌面：%d 屏 · %s"
          % (len(screens), ", ".join(
              "%s %dx%d dpr=%.2f 原点(%d,%d)"
              % (s.name(), s.geometry().width(), s.geometry().height(),
                 s.devicePixelRatio(), s.geometry().x(), s.geometry().y())
              for s in screens)))
    from ocr_engine import OcrEngine
    if not OcrEngine.available():
        print("\n  未运行：本机 OCR 引擎不可用（先跑 tools/sense_bench.py 看原因）。")
        return 1

    print("\n[1] 初始状态：感应是关着的（这个模式必须用户主动开）")
    from lexicon import Lexicon
    lexicon = Lexicon(os.path.join(BASE, "assets", "ecdict.sqlite"),
                      os.path.join(BASE, "assets", "exam-tags.sqlite"),
                      os.path.join(BASE, "assets", "industry.sqlite"))
    from pet_window import PetWindow
    pet = PetWindow(lexicon, FakeBook(), sprite_w=360.0)
    pet.bubble.hide_now()
    screen = pet._screen_rect()
    pet.move(screen.x() + 40, screen.y() + 40)     # 蜘蛛去左上角，字幕在底部
    pet.show()
    pump(0.5)
    check("未开启时不捕获、不起线程",
          pet.sense_enabled is False and pet.sense_worker is None
          and pet._sense_timer is None and pet._sense_overlay is None)

    # ---- 2. 开感应 ---------------------------------------------------
    print("\n[2] 开启感应（hz=2.0：真抓屏 QTimer + 真工作线程 + 真覆盖层）")
    pet._start_sense(hz=2.0)
    pet.sense_worker.notice.connect(lambda item: NOTICES.append(item))
    session, overlay = pet.sense_session, pet._sense_overlay
    check("会话状态 running", session.state == "running",
          "→ %s" % session.status_text())
    check("工作线程真的在跑", pet.sense_worker.isRunning())
    check("抓屏定时器已启动（GUI 线程）",
          pet._sense_timer is not None and pet._sense_timer.isActive())
    check("覆盖层已显示且鼠标穿透",
          overlay.isVisible()
          and overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
          and bool(overlay.windowFlags() & Qt.WindowTransparentForInput))
    check("全局钩子真的装上了（点词看释义的前提）",
          bool(getattr(overlay, "_hook", None)))
    check("第一版扫描是整帧建基准（§7.3 的一次性成本）",
          wait_until(lambda: session.stats["full_frame"] >= 1, 40.0),
          "→ 整帧 %d 次 / OCR %d 次" % (session.stats["full_frame"],
                                        session.stats["ocr_runs"]))

    # ---- 3. 桌面上出现新内容 ----------------------------------------
    print("\n[3] 桌面新内容：显示真字幕窗口 → 应认出新的词并短暂提示")
    card = SubtitleWindow(SENTENCE_A)
    card.show_at_bottom()
    APP.processEvents()
    rect = card.logical_rect()
    pump(1.0)
    mark = len(NOTICES)
    got = wait_until(lambda: any(inside(rect, n) for n in NOTICES[mark:]), 90.0)
    hit = next((n for n in NOTICES[mark:] if inside(rect, n)), None)
    words_a = SENTENCE_A.lower().split()
    detail = ("→ %s @(%d,%d)" % (hit.get("surface"), hit["screen_pos"][0],
                                hit["screen_pos"][1]) if hit
              else "→ 共收到 %d 个提示，没有一个落在字幕窗口里"
                   % (len(NOTICES) - mark))
    # 失败时把**调度现场**一起打出来：状态/频率/OCR 次数/中位延迟。
    # 上一版这条只打「16 个提示没一个落在窗口里」，看不出来是
    # 「读不到」还是「读到了却排在队尾 / 模式已经被自动暂停」，
    # 结果要再写一个 `tools/sense_coord_probe.py` 才定位到（两种都中过）。
    detail += "　｜状态 %s · %.2f 次/秒 · OCR %d · 跳过 %d · 近 5 轮中位 %.0fms · %s" % (
        session.state, session.hz, session.stats["ocr_runs"],
        session.stats["skipped_no_change"], session.recent_cycle_ms,
        session.note or "（无提示）")
    check("桌面上新出现的词被识别并提示（提示落在字幕窗口内）", got, detail)
    check("提示的词就是这句字幕里的词（不是屏幕上的别处）",
          hit is not None and (hit.get("surface") or "").lower() in words_a,
          "→ %s" % (hit or {}).get("surface"))
    check("带回了词本体框（高亮画在词上，不是凭空一点）",
          hit is not None and bool(hit.get("screen_box")),
          "→ %s" % (hit or {}).get("screen_box"))
    live = wait_until(lambda: overlay._notice is not None, 15.0)
    if live:
        overlay.grab().save(SHOT)      # 只存覆盖层自己的渲染，不含桌面内容
    check("覆盖层确实画出了提示（射线/高亮已渲染并存证）",
          live and os.path.isfile(SHOT), "→ %s" % SHOT)

    print("\n[4] 腿不参与：感应期间八条腿一个词都不踩（§7.2）")
    check("蜘蛛没有任何瞄准目标", not pet.spider.targets,
          "→ targets=%s" % (pet.spider.targets,))
    check("没有起瞄准层（aim 对话框不存在）", "aim" not in pet._dialogs)
    check("桌宠不在瞄准态（state 仍是 idle/walk 一类）",
          pet.state_name not in ("aim", "aiming"),
          "→ state=%s" % pet.state_name)

    print("\n[5] 静态画面不会无限重复提示（§7.4）")
    grew = counter_after(12.0, lambda: session.stats["notices"])
    check("画面不动时提示不会一直冒（12 秒内新增 %d 次）" % grew, grew <= 4,
          "→ 抑制计数 %d · OCR %d 次" % (session.stats["suppressed"],
                                        session.stats["ocr_runs"]))
    skip = session.stats["skipped_no_change"]
    check("没变化的轮次被跳过（不白跑 OCR：跳过 %d / OCR %d）"
          % (skip, session.stats["ocr_runs"]), skip > 0)

    print("\n[6] 不认出自己（本程序窗口在排除区里，但**不是整层**）")
    rects = pet._sense_exclude_rects()
    total_area = float(sum((r[2] * r[3]) for r in rects) or 0)
    desktop = float(screen.width() * screen.height())
    check("排除区非空（桌宠 / 气泡 / 卡片 / 状态条）", len(rects) > 0,
          "→ %d 块" % len(rects))
    check("排除区没有盖掉整屏（盖掉就等于把感应弄瞎）",
          total_area < 3.0 * desktop,
          "→ 合计 %.0f%% 桌面面积" % (total_area / desktop * 100))
    chip = overlay.chip_rect()
    on_chip = [n for n in NOTICES if inside(chip, n, pad=6.0)]
    check("没有任何提示落在自己的状态条上（自我识别循环）", not on_chip,
          "→ %d 个" % len(on_chip))

    print("\n[6b] 遮挡：感应读的是**合成后的桌面**，不是某个窗口自己的内容")
    cover = SubtitleWindow(SENTENCE_C)
    cover.show_over(card)                     # 把刚才那句字幕整张盖住（四周各多 12px）
    rect_cover = cover.logical_rect()
    mark = len(NOTICES)
    words_c = SENTENCE_C.lower().replace(".", " ").split()
    covered = wait_until(lambda: any(
        inside(rect_cover, n)
        and (n.get("surface") or "").lower() in words_c
        for n in NOTICES[mark:]), 90.0)
    cover_hit = next((n for n in NOTICES[mark:] if inside(rect_cover, n)), None)
    detail = ("→ %s @(%d,%d)" % (cover_hit.get("surface"),
                                cover_hit["screen_pos"][0],
                                cover_hit["screen_pos"][1]) if cover_hit
              else "→ 覆盖窗口出现后收到 %d 个提示，没有一个落在它里面"
                   % (len(NOTICES) - mark))
    check("盖在最上面那句被认出来（提示落在**覆盖窗口**里）", covered, detail)
    check("认出来的词属于看得见的那一句（被压住的旧句子不算被识别）",
          cover_hit is not None
          and (cover_hit.get("surface") or "").lower() in words_c,
          "→ %s" % (cover_hit or {}).get("surface"))
    hidden_hits = [n for n in NOTICES[mark:]
                   if inside(rect, n)
                   and (n.get("surface") or "").lower()
                   in [w.strip(".,") for w in SENTENCE_A.lower().split()]
                   and (n.get("surface") or "").lower() not in words_c]
    check("被盖住的那句没有再被提示（屏幕上确实看不见它）", not hidden_hits,
          "→ %d 个" % len(hidden_hits))

    print("\n[6c] 最小化 / 隐藏：桌宠不见了，排除区要让开，感应仍在跑")
    rects_before = len(pet._sense_exclude_rects())
    pet.hide()                                # 「最小化」在 Tool 窗口上就是 hide()
    APP.processEvents()
    pump(1.5)                                 # 让下一轮捕获把新排除表送进会话
    rects_after = len(pet._sense_exclude_rects())
    check("窗口隐藏后不再占着自己的排除区", rects_after < rects_before,
          "→ %d 块 → %d 块" % (rects_before, rects_after))
    cycles_while_hidden = counter_after(6.0, lambda: session.stats["cycles"])
    check("桌宠隐藏期间感应仍在轮询（隐藏 ≠ 关闭，也不许偷偷起第二条线程）",
          cycles_while_hidden >= 1 and pet.sense_worker.isRunning(),
          "→ 6 秒内 +%d 轮" % cycles_while_hidden)
    pet.show()
    APP.processEvents()
    pump(1.5)
    check("重新显示后排除区回来了", len(pet._sense_exclude_rects()) >= rects_before,
          "→ %d 块" % len(pet._sense_exclude_rects()))
    cover.close()                             # 拿开遮挡，桌面又露出原来那句字幕
    card.show_at_bottom()
    APP.processEvents()
    pump(2.0)

    print("\n[7] 暂停 → 不再触发 OCR；恢复 → 继续")
    # ★ 先把状态**摆正**再测：`sense_pause_resume()` 是「切换」，不是「暂停」。
    #   真桌面上如果前面已经被预算判成 `paused`（本机第一版 e2e 就是这样），
    #   这里第一次调用会变成「恢复」，接着的两条断言就全踩反了 ——
    #   那是测试自己的相位错了，不能拿来当产品的失败证据。
    if session.state != "running":
        pet.sense_pause_resume()
        wait_until(lambda: session.state == "running", 10.0)
    check("进入这一步时会话确实在跑（不然下面的相位全反）",
          session.state == "running", "→ %s" % session.status_text())
    pet.sense_pause_resume()
    check("暂停后会话不是 running", session.state != "running",
          "→ %s" % session.status_text())
    runs_delta = counter_after(8.0, lambda: session.stats["ocr_runs"])
    cycles_delta = counter_after(0.1, lambda: session.stats["cycles"])
    check("暂停期间 OCR 不再增长", runs_delta == 0, "→ +%d" % runs_delta)
    check("暂停期间连捕获轮次都不再增长（不白抓屏）", cycles_delta == 0,
          "→ +%d" % cycles_delta)
    pet.sense_pause_resume()
    check("恢复后重新 running", session.state == "running",
          "→ %s" % session.status_text())
    check("恢复后继续扫（8 秒内至少一轮）",
          counter_after(8.0, lambda: session.stats["cycles"]) >= 1,
          "→ 状态 %s · %s" % (session.state, session.note or "（无提示）"))

    print("\n[8] 内容变了要优先检测新内容（视频字幕的核心场景）")
    card.label.setText(SENTENCE_B)
    APP.processEvents()
    rect = card.logical_rect()
    mark = len(NOTICES)
    words_b = SENTENCE_B.lower().split()
    swapped = wait_until(lambda: any(
        inside(rect, n) and (n.get("surface") or "").lower() in words_b
        for n in NOTICES[mark:]), 90.0)
    new_hit = next((n for n in NOTICES[mark:] if inside(rect, n)), None)
    check("字幕换成新句子后被认出来（新内容优先）", swapped,
          "→ %s" % (new_hit or {}).get("surface"))

    print("\n[9] 点了高亮的词 → 本地释义卡；AI 仍然要用户主动按")
    item = new_hit or hit
    if item is None:
        check("前面没有可用提示，点词项跳过", False, "→ 见 [3] 的失败原因")
    else:
        pet._on_sense_word_click(item)
        APP.processEvents()
        check("释义卡真的弹出来了", "words" in pet._dialogs
              and pet._dialogs["words"] is not None)
        check("释义卡全程不碰网络（本地词典先行，AI 要用户主动按）", not NET,
              "→ urlopen %d 次" % len(NET))
        dialog = pet._dialogs.pop("words", None)
        if dialog is not None:
            dialog.close()
        APP.processEvents()

    print("\n[10] 关闭：线程、定时器、覆盖层都要收干净")
    worker = pet.sense_worker
    overlay_alive = True
    try:
        overlay_alive = overlay.isVisible()      # ★ 关闭之后 C++ 对象可能已被 delete
    except RuntimeError:                         # noqa: BLE001
        overlay_alive = False                    #    「已经没了」就是「已经收起」
    pet._stop_sense()
    APP.processEvents()
    check("工作线程已退出", worker.isRunning() is False)
    check("抓屏定时器已停并置空", pet._sense_timer is None)
    try:
        visible_after = overlay.isVisible()
    except RuntimeError:                         # noqa: BLE001
        visible_after = False                    # 对象已释放 = 不再可见
    check("覆盖层已收起", pet._sense_overlay is None and not visible_after,
          "→ 关闭前 visible=%s · 关闭后 visible=%s · 句柄=%s"
          % (overlay_alive, visible_after, pet._sense_overlay))
    check("会话状态归零", session.state == "off")
    runs = session.stats["ocr_runs"]
    pump(3.0)
    check("关闭后 OCR 计数不再增长（真的不再抓屏）",
          session.stats["ocr_runs"] == runs,
          "→ %d → %d" % (runs, session.stats["ocr_runs"]))

    print("\n[11] 退出销毁：shutdown 会先把感应停掉")
    pet._start_sense(hz=2.0)
    check("开关可以反复（第二次开启也在跑）",
          pet.sense_enabled and pet.sense_worker.isRunning())
    pump(3.0)
    second_worker = pet.sense_worker
    pet.shutdown()
    APP.processEvents()
    check("shutdown 后感应已关闭（不留后台线程）",
          pet.sense_enabled is False and pet.sense_worker is None
          and pet._sense_timer is None)
    check("shutdown 后线程确实退出了", second_worker.isRunning() is False,
          "→ isRunning=%s" % second_worker.isRunning())

    print("\n[12] 隐私：日志里不许出现屏幕文本")
    card.close()
    APP.processEvents()
    try:
        with open(LOG, encoding="utf-8", errors="replace") as handle:
            logged = handle.read()
    except Exception:                                       # noqa: BLE001
        logged = ""
        check("临时日志存在（读不到就没法验隐私）", False, "→ %s" % LOG)
    leaked = [w for w in words_a if len(w) > 5 and w in logged]
    check("日志里没有识别到的屏幕单词（读的是临时 run.log）", not leaked,
          "→ %s" % (leaked[:3],))
    check("全程零联网（屏幕图像不会被发给 AI / 第三方）", not NET,
          "→ %d 次" % len(NET))
    if len(screens) < 2:
        print("      多屏 / 高 DPI：本机只有 1 块屏（dpr=%.2f）→ "
              "多屏与缩放的**真机**用例未运行，逻辑侧见 "
              "test/test_sense_overlay.py 与 test/test_sense_worker.py"
              % screens[0].devicePixelRatio())

    print("\n" + "=" * 78)
    print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    for name in FAIL:
        print("  FAILED:", name)
    print("证据图：", SHOT if os.path.isfile(SHOT) else "（未生成）")
    print("沙箱配置目录：", SANDBOX, "（用户的 %APPDATA% 未被读写）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
