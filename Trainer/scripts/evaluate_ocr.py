# -*- coding: utf-8 -*-
"""OCR 评测：同一批样本、同一套归一化规则、同一个脚本，比较不同引擎。

用法：
    python Trainer/scripts/evaluate_ocr.py --engine rapid --profile quick
    python Trainer/scripts/evaluate_ocr.py --engine rapid,paddle --profile full
    python Trainer/scripts/evaluate_ocr.py --engine rapid --ci      # 回归门限模式

输出（`Trainer/reports/`）：
    eval_<engine>_<stamp>.json   全量逐图明细（visualize_misses.py 吃它）
    eval_<engine>_<stamp>.md     人看的汇总
    compare_<stamp>.md           多引擎并排对照

指标口径（任务书 §2.3）：
    词识别准确率 = 归一化（lower + 去首尾标点）后 exact match；
    词级召回率   = 正确找回的真实词 / 全部真实词；
    词框质量     = 匹配上的框 IoU、四边偏差（像素 + 相对词高）；
    失败形态     = 漏词 / 重复词 / 错误切词 / 粘连词，分开计数，不混成一个「失败」；
    性能         = 单张耗时中位数 / P95 / 最大值、空结果率、异常率。

★ 匹配规则：一个真实词最多配一个预测词（一对一贪心），
  所以「同一个词被踩两遍」会体现在 duplicate 而不是 recall 上升 —— 这正是
  连续扫词队列要保证的东西（任务书 §6.1「每个目标最多完成一次」）。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TRAINER = HERE.parent
ROOT = TRAINER.parent
sys.path.insert(0, str(ROOT / "src"))

PUNCT_RE = re.compile(r"^[-'.,:;!?\(\)\[\]{}\"“”‘’、。，]+|[-'.,:;!?\(\)\[\]{}\"“”‘’、。，]+$")


def norm(text: str) -> str:
    return PUNCT_RE.sub("", (text or "").strip()).lower()


# ---------------------------------------------------------------- 几何

def box_iou(a, b) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ax1, ay1, bx1, by1 = ax0 + aw, ay0 + ah, bx0 + bw, by0 + bh
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def center(a):
    return (a[0] + a[2] / 2.0, a[1] + a[3] / 2.0)


def edge_delta(gt, pred):
    gx, gy, gw, gh = gt
    px, py, pw, ph = pred
    return {"dx": px - gx, "dy": py - gy, "dw": pw - gw, "dh": ph - gh,
            "rel_dx": abs(px - gx) / max(1.0, gw),
            "rel_dy": abs(py - gy) / max(1.0, gh),
            "rel_w": abs(pw - gw) / max(1.0, gw),
            "rel_h": abs(ph - gh) / max(1.0, gh)}


# ---------------------------------------------------------------- 匹配

def match_image(gt_words, pred_words):
    """一对一贪心匹配。返回统计字典 + 逐词明细（可视化要用）。"""
    pairs = []
    for gi, g in enumerate(gt_words):
        gbox = g["bbox"]
        gcx, gcy = center(gbox)
        tol = max(14.0, 0.8 * max(6.0, gbox[3]))
        for pi, p in enumerate(pred_words):
            pbox = list(p.bbox)
            pcx, pcy = center(pbox)
            iou = box_iou(gbox, pbox)
            dist = ((gcx - pcx) ** 2 + (gcy - pcy) ** 2) ** 0.5
            inside = (gbox[0] - tol <= pcx <= gbox[0] + gbox[2] + tol and
                      gbox[1] - tol <= pcy <= gbox[1] + gbox[3] + tol)
            if iou < 0.12 and not (inside and dist <= tol * 2.2):
                continue
            text_hit = 0.45 if norm(g["text"]) == norm(p.text) else 0.0
            score = iou + text_hit + max(0.0, 0.3 - dist / max(1.0, tol * 6))
            pairs.append((score, gi, pi, iou, dist))
    pairs.sort(reverse=True)
    used_g, used_p, matched = set(), set(), []
    for score, gi, pi, iou, dist in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        g, p = gt_words[gi], pred_words[pi]
        ok = norm(g["text"]) == norm(p.text)
        matched.append({"gt": g["text"], "pred": p.text, "ok": ok,
                        "iou": round(iou, 4), "dist": round(dist, 2),
                        "gt_box": g["bbox"], "pred_box": list(p.bbox),
                        "refined": bool(p.refined),
                        "delta": {k: round(v, 3) for k, v in
                                  edge_delta(g["bbox"], list(p.bbox)).items()}})
    misses = [gt_words[i]["text"] for i in range(len(gt_words)) if i not in used_g]
    extras = [pred_words[i].text for i in range(len(pred_words)) if i not in used_p]

    # 重复词：多余预测的文本等于某个**已命中**的真实词，且中心落在它附近
    duplicate = 0
    for i in range(len(pred_words)):
        if i in used_p:
            continue
        p = pred_words[i]
        for m in matched:
            if norm(p.text) != norm(m["gt"]):
                continue
            pcx, pcy = center(list(p.bbox))
            gcx, gcy = center(m["gt_box"])
            if ((pcx - gcx) ** 2 + (pcy - gcy) ** 2) ** 0.5 <= max(
                    18.0, 1.2 * max(6.0, m["gt_box"][3])):
                duplicate += 1
                break

    # 粘连词：一个预测框覆盖 ≥2 个真实词（各 IoU ≥ 0.2）
    merged = 0
    for i in range(len(pred_words)):
        cover = [gi for gi, g in enumerate(gt_words)
                 if box_iou(g["bbox"], list(pred_words[i].bbox)) >= 0.2]
        if len(cover) >= 2:
            merged += 1
    # 错误切词：一个真实词被 ≥2 个预测框覆盖
    split = 0
    for g in gt_words:
        cover = [pi for pi, p in enumerate(pred_words)
                 if box_iou(g["bbox"], list(p.bbox)) >= 0.2]
        if len(cover) >= 2:
            split += 1

    correct = sum(1 for m in matched if m["ok"])
    return {"gt": len(gt_words), "pred": len(pred_words), "correct": correct,
            "wrong_text": len(matched) - correct, "miss": len(misses),
            "extra": len(extras), "duplicate": duplicate, "merged": merged,
            "split": split, "misses": misses, "extras": extras,
            "matched": matched}


# ---------------------------------------------------------------- 汇总

def pct(a, b):
    return round(100.0 * a / b, 2) if b else 0.0


def summarize(records, engine_id, env):
    gt = sum(r["gt"] for r in records)
    pred = sum(r["pred"] for r in records)
    correct = sum(r["correct"] for r in records)
    ious = [m["iou"] for r in records for m in r["matched"] if m["ok"]]
    times = [r["elapsed_ms"] for r in records]
    refined = sum(1 for r in records for m in r["matched"] if m["refined"])
    matched_n = sum(len(r["matched"]) for r in records) or 1
    deltas = [m["delta"] for r in records for m in r["matched"] if m["ok"]]

    def mean(key):
        return round(statistics.fmean([d[key] for d in deltas]), 3) if deltas else 0.0

    def rel(key):
        return pct(sum(1 for d in deltas if d[key] > 0.15), len(deltas)) if deltas else 0.0

    return {
        "engine": engine_id,
        "images": len(records),
        "gt_words": gt,
        "pred_words": pred,
        "word_recall_pct": pct(correct, gt),
        "word_precision_pct": pct(correct, pred),
        "word_f1_pct": round(2 * pct(correct, gt) * pct(correct, pred) /
                             max(1e-9, pct(correct, gt) + pct(correct, pred)), 2),
        "correct": correct,
        "wrong_text": sum(r["wrong_text"] for r in records),
        "miss": sum(r["miss"] for r in records),
        "extra": sum(r["extra"] for r in records),
        "duplicate": sum(r["duplicate"] for r in records),
        "merged": sum(r["merged"] for r in records),
        "split": sum(r["split"] for r in records),
        "box_iou_mean": round(statistics.fmean(ious), 4) if ious else 0.0,
        "box_iou_median": round(statistics.median(ious), 4) if ious else 0.0,
        "box_iou_p95": (round(sorted(ious)[int(0.95 * (len(ious) - 1))], 4)
                        if len(ious) > 1 else (round(ious[0], 4) if ious else 0.0)),
        "box_iou_ge_05_pct": pct(sum(1 for i in ious if i >= 0.5), len(ious)),
        "edge_mean": {k: mean(k) for k in ("dx", "dy", "dw", "dh")},
        "edge_over_15pct_pct": {k: rel(k) for k in ("rel_dx", "rel_dy",
                                                    "rel_w", "rel_h")},
        "refined_ratio_pct": pct(refined, matched_n),
        "latency_ms_median": round(statistics.median(times), 1) if times else 0.0,
        "latency_ms_p95": (round(sorted(times)[int(0.95 * (len(times) - 1))], 1)
                           if len(times) > 1 else round(times[0], 1) if times else 0.0),
        "latency_ms_max": round(max(times), 1) if times else 0.0,
        "empty_result_pct": pct(sum(1 for r in records if r["pred"] == 0),
                                len(records)),
        "error_pct": pct(sum(1 for r in records if r.get("error")), len(records)),
        "environment": env,
    }


def by_case(records):
    buckets = {}
    for r in records:
        key = r["case"]
        b = buckets.setdefault(key, {"images": 0, "gt": 0, "correct": 0,
                                     "iou": [], "ms": []})
        b["images"] += 1
        b["gt"] += r["gt"]
        b["correct"] += r["correct"]
        b["ms"].append(r["elapsed_ms"])
        b["iou"] += [m["iou"] for m in r["matched"] if m["ok"]]
    out = {}
    for key, b in buckets.items():
        out[key] = {"images": b["images"], "gt_words": b["gt"],
                    "recall_pct": pct(b["correct"], b["gt"]),
                    "iou_mean": round(statistics.fmean(b["iou"]), 3) if b["iou"] else 0.0,
                    "ms_median": round(statistics.median(b["ms"]), 1)}
    return out


def dpi_offset(records):
    """同一版式在不同 DPI 下的坐标偏移（任务书 §2.3 最后一项）。

    合成集里 `dpi_100/125/150` 是**同一批词**按 1/1.25/1.5 渲染的，
    所以把归一化坐标（除以画布宽）对齐后，同一词的相对位置差就是 DPI 换算误差。
    """
    groups = {}
    for r in records:
        if not r["case"].startswith("dpi_"):
            continue
        for m in r["matched"]:
            if not m["ok"]:
                continue
            word = norm(m["gt"])
            groups.setdefault(word, {})[r["case"]] = (
                m["pred_box"][0] / max(1.0, r["width"]),
                m["pred_box"][1] / max(1.0, r["height"]))
    rows = []
    for word, per in sorted(groups.items()):
        if len(per) < 2:
            continue
        xs = [v[0] for v in per.values()]
        ys = [v[1] for v in per.values()]
        rows.append({"word": word, "spread_x_pct": round(100 * (max(xs) - min(xs)), 3),
                     "spread_y_pct": round(100 * (max(ys) - min(ys)), 3),
                     "engines": sorted(per)})
    return {"words_compared": len(rows),
            "max_spread_x_pct": round(max([r["spread_x_pct"] for r in rows], default=0.0), 3),
            "max_spread_y_pct": round(max([r["spread_y_pct"] for r in rows], default=0.0), 3),
            "detail": rows[:40]}


# ---------------------------------------------------------------- 环境

def environment(engine_id: str) -> dict:
    env = {"python": sys.version.split()[0], "platform": platform.platform(),
           "numpy": np.__version__, "opencv": cv2.__version__,
           "engine": engine_id, "engine_version": "", "engine_state": "",
           "engine_reason": "", "model": "", "preprocess": {},
           "cpu": platform.processor(), "timestamp": time.strftime("%F %T %z")}
    try:
        import importlib.metadata as md
        if engine_id == "rapid":
            env["engine_version"] = md.version("rapidocr_onnxruntime")
            env["model"] = ("PP-OCRv4 det/rec (ONNX, 随 rapidocr_onnxruntime 分发)")
        else:
            env["engine_version"] = md.version("paddleocr")
    except Exception:                                 # noqa: BLE001
        pass
    try:
        import ocr_adapter
        snap = ocr_adapter.describe_engines()
        me = next((s for s in snap if s["id"] == engine_id), {})
        env.update({"engine_state": me.get("state", "unknown"),
                    "engine_reason": me.get("reason", "")})
    except Exception as error:                        # noqa: BLE001
        env["engine_state"] = "error"
        env["engine_reason"] = repr(error)
    try:
        import ocr_engine
        env["preprocess"] = {"DET_LIMIT": ocr_engine.DET_LIMIT,
                             "EFF_CAP": ocr_engine.EFF_CAP,
                             "MAX_FACTOR": ocr_engine.MAX_FACTOR,
                             "TILE_OVERLAP": ocr_engine.TILE_OVERLAP,
                             "GOOD_SCORE": ocr_engine.GOOD_SCORE,
                             "MERGE_IOU": ocr_engine.MERGE_IOU}
    except Exception:                                 # noqa: BLE001
        pass
    return env


# ---------------------------------------------------------------- main

def load_manifest(path: Path):
    recs = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def evaluate(engine_id: str, manifest: Path, out_dir: Path, limit=0,
             cases=None) -> dict:
    import ocr_adapter

    # ★ 引擎不可用时报**明确错误**，不静默跳过（任务书 §2.4）
    snap = ocr_adapter.probe(engine_id)[0]
    if snap["state"] != "available":
        raise SystemExit("[eval] 引擎 %s 状态=%s，无法评测。原因：%s\n"
                         "        （这不是跳过：请先在独立环境装好并验证，"
                         "或改用 --engine rapid）"
                         % (engine_id, snap["state"], snap["reason"]))

    records = []
    items = load_manifest(manifest)
    if cases:
        items = [r for r in items if r["case"] in cases]
    if limit:
        items = items[:limit]
    for rec in items:
        path = ROOT / rec["path"]
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise SystemExit("[eval] 样本读不到：%s（先跑 generate_synthetic.py）" % path)
        arr = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = ocr_adapter.recognize(arr, engine_id=engine_id)
        m = match_image(rec["words"], res.words)
        m.update({"image_id": rec["image_id"], "path": rec["path"], "case": rec["case"],
                  "width": rec["width"], "height": rec["height"],
                  "difficulty_tags": rec.get("difficulty_tags", []),
                  "elapsed_ms": res.elapsed_ms, "error": res.error,
                  "degraded": res.degraded, "note": res.note})
        records.append(m)
        print("[eval] %-28s recall=%3d/%-3d iou=%.3f %6.0fms%s"
              % (rec["image_id"], m["correct"], m["gt"],
                 statistics.fmean([x["iou"] for x in m["matched"]] or [0.0]),
                 res.elapsed_ms,
                 "  ERR:" + res.error if res.error else ""))
    summary = {"engine": engine_id, "overall": summarize(records, engine_id,
                                                         environment(engine_id)),
               "by_case": by_case(records), "dpi": dpi_offset(records),
               "images": records}
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / ("eval_%s_%s.json" % (engine_id, stamp))).write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / ("eval_%s_latest.json" % engine_id)).write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def render_md(summaries: dict, out_dir: Path, stamp: str) -> Path:
    path = out_dir / ("compare_%s.md" % stamp)
    keys = [("images", "样本数"), ("gt_words", "真实词"), ("pred_words", "预测词"),
            ("correct", "正确"), ("word_recall_pct", "召回率%"),
            ("word_precision_pct", "精确率%"), ("word_f1_pct", "F1%"),
            ("wrong_text", "错字"), ("miss", "漏词"), ("extra", "多余词"),
            ("duplicate", "重复词"), ("merged", "粘连词"), ("split", "错误切词"),
            ("box_iou_mean", "IoU均值"), ("box_iou_median", "IoU中位"),
            ("box_iou_ge_05_pct", "IoU≥0.5 %"), ("refined_ratio_pct", "墨迹细化%"),
            ("latency_ms_median", "耗时中位ms"), ("latency_ms_p95", "耗时P95ms"),
            ("empty_result_pct", "空结果%"), ("error_pct", "异常%")]
    lines = ["# OCR 评测对照（%s）" % stamp, ""]
    lines.append("| 指标 | " + " | ".join(summaries) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in summaries) + " |")
    for k, label in keys:
        lines.append("| %s | %s |" % (label,
                                       " | ".join(str(summaries[e]["overall"].get(k))
                                                  for e in summaries)))
    lines += ["", "## 四边偏差（匹配正确的词，像素均值）", ""]
    for e, s in summaries.items():
        d = s["overall"]["edge_mean"]
        r = s["overall"]["edge_over_15pct_pct"]
        lines.append("- `%s` dx=%s dy=%s dw=%s dh=%s；偏差>15%%词宽/高的比例 "
                     "x=%s%% y=%s%% w=%s%% h=%s%%"
                     % (e, d["dx"], d["dy"], d["dw"], d["dh"],
                        r["rel_dx"], r["rel_dy"], r["rel_w"], r["rel_h"]))
    lines += ["", "## 环境", ""]
    for e, s in summaries.items():
        env = s["overall"]["environment"]
        lines.append("- `%s`: python=%s platform=%s engine_version=%s state=%s "
                     "reason=%s model=%s" %
                     (e, env["python"], env["platform"], env["engine_version"],
                      env["engine_state"], env["engine_reason"] or "-",
                      env["model"] or "-"))
    lines += ["", "## 分场景召回率", ""]
    cases = sorted({c for s in summaries.values() for c in s["by_case"]})
    lines.append("| case | " + " | ".join(summaries) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in summaries) + " |")
    for c in cases:
        lines.append("| %s | %s |" % (c, " | ".join(
            str(s["by_case"].get(c, {}).get("recall_pct", "-"))
            for s in summaries.values())))
    lines += ["", "## DPI 坐标偏移（归一化后同一词的散布）", ""]
    for e, s in summaries.items():
        # 注意：`dpi` 挂在 summary 顶层（它是**跨图**对齐结果，不属于单引擎的
        # 逐词统计），别写成 `s["overall"]["dpi"]` —— 那是 KeyError。
        d = s.get("dpi") or {"words_compared": 0, "max_spread_x_pct": "-",
                             "max_spread_y_pct": "-"}
        lines.append("- `%s`: 可比词 %d，x 最大散布 %s%%，y 最大散布 %s%%"
                     % (e, d["words_compared"], d["max_spread_x_pct"],
                        d["max_spread_y_pct"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--engine", default="rapid",
                    help="rapid | paddle | rapid,paddle（逗号分隔即并排对照）")
    ap.add_argument("--manifest", default=str(TRAINER / "datasets" / "manifests" /
                                              "generated.jsonl"))
    ap.add_argument("--out", default=str(TRAINER / "reports"))
    ap.add_argument("--profile", choices=("full", "quick"), default="full")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cases", default="", help="逗号分隔的 case_id 过滤")
    ap.add_argument("--ci", action="store_true",
                    help="回归门限模式：召回率/IoU 低于门限即 exit 1")
    ap.add_argument("--min-recall", type=float, default=70.0)
    ap.add_argument("--min-iou", type=float, default=0.45)
    ap.add_argument("--report-only", action="store_true",
                    help="不重跑 OCR，直接读 reports/eval_<engine>_latest.json 渲染对照表")
    args = ap.parse_args(argv)

    manifest = Path(args.manifest)
    if not manifest.is_file() and not args.report_only:
        raise SystemExit("[eval] 标注不存在：%s\n"
                         "        先跑：python Trainer/scripts/generate_synthetic.py"
                         % manifest)
    if args.profile == "quick":
        from generate_synthetic import QUICK_CASES
        cases = set(QUICK_CASES)
    else:
        cases = {c.strip() for c in args.cases.split(",") if c.strip()} or None

    engines = [e.strip() for e in args.engine.split(",") if e.strip()]
    summaries = {}
    for e in engines:
        if args.report_only:
            latest = Path(args.out) / ("eval_%s_latest.json" % e)
            if not latest.is_file():
                raise SystemExit("[eval] 没有可直接渲染的结果：%s（先完整跑一次）"
                                 % latest)
            summaries[e] = json.loads(latest.read_text(encoding="utf-8"))
        else:
            summaries[e] = evaluate(e, manifest, Path(args.out), args.limit, cases)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    md = render_md(summaries, Path(args.out), stamp)
    print("\n[report] %s" % md)
    for e, s in summaries.items():
        o = s["overall"]
        print("[summary] %-7s 图=%d 词=%d 召回=%.1f%% 精确=%.1f%% IoU均值=%.3f "
              "细化=%.0f%% 耗时中位=%.0fms P95=%.0fms 空结果=%.0f%%"
              % (e, o["images"], o["gt_words"], o["word_recall_pct"],
                 o["word_precision_pct"], o["box_iou_mean"],
                 o["refined_ratio_pct"], o["latency_ms_median"],
                 o["latency_ms_p95"], o["empty_result_pct"]))
    if args.ci:
        bad = []
        for e, s in summaries.items():
            o = s["overall"]
            if o["word_recall_pct"] < args.min_recall:
                bad.append("%s 召回 %.1f%% < %.1f%%" % (e, o["word_recall_pct"],
                                                        args.min_recall))
            if o["box_iou_mean"] < args.min_iou:
                bad.append("%s IoU %.3f < %.3f" % (e, o["box_iou_mean"], args.min_iou))
        if bad:
            print("\n[CI FAIL] " + "；".join(bad))
            return 1
        print("\n[CI OK] 门限通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
