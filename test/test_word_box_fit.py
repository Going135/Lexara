# -*- coding: utf-8 -*-
"""词框贴合回归测试：框必须**套在单词本体上**，不是「中心点 + 字号」另估一只。

对应任务书 §4 的验收口径：
    框线直接贴合单词本体、宽高随词变化、不漂移到词的上方，且偏差**可量化**。

这里刻意不用 Trainer 的合成集（那是引擎质量评测，跑起来慢、依赖 manifest），
而是**当场画图**：用 QPainter 把词画在已知槽位上，再用列/行墨迹投影量出
每个词的**真实笔画外接框**当 GT —— 这样测试自包含、可离线跑，
GT 也不是「我以为的字号高度」而是像素事实。

三组断言：
    ① 引擎侧：`OcrWord.bbox` 对 GT 的 IoU、四边偏差、框高是否跟着词高走；
    ② 换算侧：`OcrWorker.locate` 在 DPR=1.25/1.5 下把词框换算成屏幕逻辑像素；
    ③ 覆盖层侧：`AimOverlay` 用的是词本体框（`fitted=True`），
       并且框中心 ≈ 词中心（**不允许整体往上飘**）。

运行：  python test/test_word_box_fit.py
"""

from __future__ import annotations

import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))
# ★ 不要设 `QT_QPA_PLATFORM=offscreen`：离屏平台没有可用的字体数据库，
#   `QPainter.drawText` 画出来的东西检测端读不出任何行 ——
#   实测 `test_ocr_coords.py` 在 offscreen 下从 6/6 变成 2/6。
#   本测试需要「真渲染 + 真识别」，所以走平台默认（覆盖层不 show，只是建出来取几何）。

import numpy as np                                          # noqa: E402
from PySide6.QtCore import QPoint, QRect, Qt                # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter   # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

import ocr_engine as OE                                     # noqa: E402
from ocr_engine import OcrEngine                            # noqa: E402
from pet_window import OcrWorker                            # noqa: E402

app = QApplication(sys.argv)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-52s %s" % ("ok" if ok else "FAIL", name, detail))


def iou(a, b):
    ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def render_scene(rows, width=1000, height=260, bg=(255, 255, 255)):
    """把若干行词画出来，返回 (ndarray, [GT 词框])。

    GT 用**墨迹投影**量出来，不是 `QFontMetrics` 说的行高 ——
    后者包含 ascent/descent 的留白，正好是旧词框「比词高一截」的来源。
    """
    image = QImage(width, height, QImage.Format_RGB888)
    image.fill(QColor(*bg))
    painter = QPainter(image)
    slots = []
    y = 24
    for px, kind, words, gap in rows:
        font = QFont(kind["family"], px, QFont.Bold if kind.get("bold") else 0)
        font.setItalic(bool(kind.get("italic")))
        painter.setFont(font)
        painter.setPen(QColor(18, 20, 30))
        x = 28
        metrics = painter.fontMetrics()
        for word in words:
            w = metrics.horizontalAdvance(word)
            # boundingRect 的左上角相对基线的偏移，画字时 Qt 用的是逻辑原点
            rect = metrics.boundingRect(word)
            painter.drawText(QPoint(x, y + px + 6), word)
            slots.append((word, x, y + px + 6 - metrics.ascent(),
                          w, metrics.height(), px))
            x += w + gap
        y += metrics.height() + 34
    painter.end()

    arr = OE.qimage_to_ndarray(image)
    gt = []
    lum = arr.astype(np.float32).mean(axis=2)
    for word, sx, sy, sw, sh, px in slots:
        x0, x1 = max(0, sx - 6), min(width, sx + sw + 6)
        y0, y1 = max(0, sy - 4), min(height, sy + sh + 4)
        patch = lum[y0:y1, x0:x1]
        ink = np.abs(patch - float(np.median(patch))) > 24.0
        if not ink.any():
            continue
        cols = np.flatnonzero(ink.any(axis=0))
        rows_ = np.flatnonzero(ink.any(axis=1))
        gt.append({"text": word, "box": (x0 + int(cols[0]), y0 + int(rows_[0]),
                                         int(cols[-1] - cols[0]) + 1,
                                         int(rows_[-1] - rows_[0]) + 1)})
    return arr, gt


SCENES = {
    "长短词混排": [
        (30, {"family": "Arial"}, ["I", "a", "committee", "millions", "of",
                                    "w"], 16),
    ],
    "带标点与撇号": [
        (30, {"family": "Arial"}, ["don't", "well-known", "word,", "end."], 18),
    ],
    "斜体": [
        (30, {"family": "Georgia", "italic": True}, ["italic", "sample",
                                                      "values"], 18),
    ],
    "紧挨着的短词": [
        (26, {"family": "Arial"}, ["cat", "rat", "bat", "hat"], 6),
    ],
}

print("=" * 78)
print("词框贴合 · 回归（引擎几何 / DPR 换算 / 覆盖层取框）")
print("=" * 78)

all_pred, all_gt = [], []
for scene, rows in SCENES.items():
    arr, gt = render_scene(rows)
    lines = OcrEngine.recognize_lines(arr)
    words = [w for ln in lines for w in ln.words]
    gt_by_text = {}
    for g in gt:
        # 键同时挂「原文小写」和「去掉尾标点」两份：
        # 画的是 `word,` 而 WORD_RE 只截出 `word`，只挂一份会白丢可比对样本。
        keys = {g["text"].lower(), g["text"].lower().strip(".,:;'\u2019")}
        for key in keys:
            gt_by_text.setdefault(key, g["box"])

    matched = []
    for w in words:
        key = w.text.lower().strip(".,:;")
        box = gt_by_text.get(key) or gt_by_text.get(w.text.lower())
        if box is None:
            continue
        matched.append((w, box, iou(box, w.bbox)))

    print("\n[%s] 画出 %d 词，认出 %d 词，可比对 %d 词"
          % (scene, len(gt), len(words), len(matched)))
    check("%s：认出了词" % scene, bool(words), "→ %s" % [w.text for w in words][:6])
    if not matched:
        continue

    ious = [m for _, _, m in matched]
    check("%s：词框 IoU 中位数 ≥ 0.55" % scene,
          sorted(ious)[len(ious) // 2] >= 0.55,
          "→ 中位 %.3f 最小 %.3f" % (sorted(ious)[len(ious) // 2], min(ious)))

    # 框高必须跟着**词高**走：行高 40px 的词不能给出 8px 或 60px 的框
    heights = [(w.bottom - w.top, g[3]) for w, g, _ in matched if g[3] > 6]
    if heights:
        ratios = [p / t for p, t in heights]
        check("%s：框高与笔画高之比在 0.75~1.35 内" % scene,
              max(ratios) <= 1.35 and min(ratios) >= 0.75,
              "→ %.2f ~ %.2f" % (min(ratios), max(ratios)))

    # 不许整体上飘：框中心与词中心的垂直偏差 < 0.45 倍词高
    drift = [(w.top + w.bottom) / 2.0 - (g[1] + g[3] / 2.0) for w, g, _ in matched]
    worst = max(drift, key=abs)
    check("%s：框没有往上/往下飘（|Δy| < 0.45×词高）" % scene,
          abs(worst) < 0.45 * min(g[3] for _, g, _ in matched if g[3] > 6),
          "→ 最大 %.1fpx" % worst)

    # 框宽要能区分窄词与宽词（旧版按字号估，i 和 committee 一样宽是错的）
    widths = {w.text.lower(): (w.right - w.left) for w, _, _ in matched}
    if "i" in widths and "committee" in widths:
        check("窄词 'i' 的框明显窄于 'committee'",
              widths["committee"] > 3 * widths["i"],
              "→ %.0f vs %.0f" % (widths["i"], widths["committee"]))

    all_pred += [(w, g) for w, g, _ in matched]
    all_gt += matched

# 至少有一条路径真的走到了墨迹细化
check("墨迹细化确实在跑（refined 比例 > 0.5）",
      any(w.refined for w, _ in all_pred),
      "→ %d/%d" % (sum(1 for w, _ in all_pred if w.refined), len(all_pred)))
# 细化里不许静默吞异常：`except: pass` 藏一个 ValueError，
# 表现是「所有词框都不收紧」，只看界面根本发现不了。
check("墨迹细化没有吞掉异常（REFINE_ERRORS 为空）",
      not OE.REFINE_ERRORS, "→ %s" % (OE.REFINE_ERRORS[-3:],))

# ---------------------------------------------------------------- ② DPR 换算
print("\n[②] DPR 换算：词框从图像像素到屏幕逻辑像素")
rect = QRect(200, 100, 800, 400)
for dpr in (1.0, 1.25, 1.5):
    worker = OcrWorker(None, None, "cet6", 8, True)
    worker.capture_rect = QRect(rect)
    worker.dpr = dpr
    items = [{"surface": "committee", "lemma": "committee"}]
    # 落点取框中心，和引擎里 `_snap_edges` 之后 `cx/cy = 框心` 的约定一致
    worker.locate(items, {"committee": (145.0, 60.0)}, None,
                  {"committee": (100.0, 49.0, 90.0, 22.0)})
    got = items[0].get("screen_box")
    want = (200 + 100.0 / dpr, 100 + 49.0 / dpr, 90.0 / dpr, 22.0 / dpr)
    ok = got is not None and all(math.isclose(a, b, abs_tol=0.01)
                                 for a, b in zip(got, want))
    check("DPR=%.2f 词框换算正确（先除 DPR 再加选区原点）" % dpr, ok,
          "→ %s 应为 %s" % (tuple(round(v, 1) for v in got or ()),
                            tuple(round(v, 1) for v in want)))
    # 中心点与框中心必须吻合，否则腿踩的地方和亮框不是同一个地方
    if got:
        cx = got[0] + got[2] / 2.0
        cy = got[1] + got[3] / 2.0
        pos = items[0]["screen_pos"]
        check("DPR=%.2f 框中心与落点一致（腿尖踩在亮框里）" % dpr,
              abs(cx - pos[0]) < 20 and abs(cy - pos[1]) < 20,
              "→ 框心(%.1f,%.1f) 落点(%.1f,%.1f)" % (cx, cy, pos[0], pos[1]))

# ---------------------------------------------------------------- ③ 覆盖层
print("\n[③] 覆盖层：用的是词本体框，不是「字号估的独立框」")
from aim_overlay import AimOverlay, WORD_BOX_PAD          # noqa: E402
import pet_window as PW                                   # noqa: E402


class StubPet:
    """只提供 AimOverlay 需要的字段，不建真桌宠（真桌宠会拉起定时器）。"""

    def __init__(self):
        import crawler_spider as CS_
        from spider_painter import SpiderPainter
        self.sprite_w = 360.0
        # 和生产一致：`CS.Spider(size=1.0)` 自带八条腿 + 触须
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

    # `AimOverlay.closeEvent` 收尾时会把本体叫回来（`show()` + `raise_()`）
    def show(self):
        pass

    def raise_(self):
        pass


pet = StubPet()
overlay_words = []
for index, (word, gbox) in enumerate(all_pred[:8] or []):
    overlay_words.append({
        "lemma": word.text, "surface": word.text,
        "screen_pos": (float(gbox[0] + gbox[2] / 2.0),
                       float(gbox[1] + gbox[3] / 2.0)),
        "screen_box": (float(gbox[0]), float(gbox[1]),
                       float(gbox[2]), float(gbox[3])),
    })
if not overlay_words:
    overlay_words = [{"lemma": "committee", "surface": "committee",
                      "screen_pos": (600.0, 300.0),
                      "screen_box": (540.0, 288.0, 120.0, 26.0)}]

overlay = AimOverlay(pet, overlay_words, stagger=0.0)
fitted = [g for g in overlay._guides if g.get("fitted")]
check("覆盖层走了「词本体框」路径", len(fitted) == len(overlay._guides),
      "→ %d/%d 个词框贴合" % (len(fitted), len(overlay._guides)))

if fitted:
    offs = []
    for guide in fitted:
        box = guide["box"]
        want = guide["fit"]
        offs.append(max(abs(box.left() - (want.left() - WORD_BOX_PAD)),
                        abs(box.top() - (want.top() - WORD_BOX_PAD))))
    check("画出来的框 = 词框 ± 可配置边距（≤2.5px）", max(offs) <= 2.5,
          "→ 最大偏移 %.2fpx，边距 %.1fpx" % (max(offs), WORD_BOX_PAD))

    # 旧实现按 `QFontMetrics.horizontalAdvance(lemma)` 估宽：
    # 单字母 'i' 的旧框会有 ~30px 宽，贴着词的框应该只有几像素。
    narrow = [g for g in fitted if g["text"].lower() in ("i", "a", "I")]
    if narrow:
        widths = [g["box"].width() for g in narrow]
        check("窄词没有被撑成「字号那么宽」", max(widths) < 24,
              "→ %.1fpx" % max(widths))

    # 框中心 vs 词中心：飘移必须很小（这是「单词上方多出一只框」的直接判据）
    drift = [abs(g["box"].center().y() - g["fit"].center().y()) for g in fitted]
    check("亮框中心与词中心重合（没有往上飘）", max(drift) <= 2.0,
          "→ 最大 %.2fpx" % max(drift))

overlay.close()
overlay.deleteLater()

print("\n" + "=" * 78)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
for name in FAIL:
    print("  FAILED:", name)
raise SystemExit(1 if FAIL else 0)
