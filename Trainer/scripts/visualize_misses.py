# -*- coding: utf-8 -*-
"""漏识别与错误框可视化：把「没认出来的词」画出来存成图，而不是只留识别成功的样例。

任务书 §2.4 明确要求：**不要只展示识别成功的样例，必须保存漏识别与错误框的可视化报告**。
本脚本不重跑 OCR —— 它读 `evaluate_ocr.py` 落盘的 `eval_<engine>_latest.json`
（里面有逐词的 GT 框 / 预测框 / IoU / 是否细化），配上 manifest 的真实标注，
把每张图叠成一张对照图。

用法：
    python Trainer/scripts/visualize_misses.py                    # 全部低分图
    python Trainer/scripts/visualize_misses.py --cases bg_noisy   # 指定场景
    python Trainer/scripts/visualize_misses.py --all              # 每张都出图
    python Trainer/scripts/visualize_misses.py --zoom 3           # 放大倍数

输出：
    Trainer/reports/misses/<image_id>.png     单图叠加（放大后看细节）
    Trainer/reports/misses/_overview.png      总览拼贴（每格一张缩略图）
    Trainer/reports/misses/index.md           文字索引：谁漏了、谁框歪了

图例：
    绿实线 = 真实标注且被正确命中     蓝实线 = 预测框
    橙虚线 = 漏词（GT 有、预测没匹配上） 红实线 = 多余词（预测有、GT 没有）
    黄实线 = 认出了但文本错            品红点线 = IoU < 0.5 的「框歪了」
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TRAINER = HERE.parent
ROOT = TRAINER.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from evaluate_ocr import box_iou, center, load_manifest, norm   # noqa: E402

# BGR
C_HIT = (0, 200, 0)
C_PRED = (255, 160, 0)
C_MISS = (0, 140, 255)
C_EXTRA = (0, 0, 255)
C_WRONG = (0, 215, 255)
C_LOOSE = (255, 0, 255)
C_TEXT = (255, 255, 255)


def draw_box(img, box, color, thickness=2, label="", dashed=False, scale=0.5):
    x, y, w, h = [int(round(v)) for v in box]
    x2, y2 = x + w, y + h
    if dashed:
        step, on = 6, 4
        for x0 in range(x, x2, step + on):
            for xx in (x0, min(x2, x0 + on)):
                cv2.rectangle(img, (xx, y), (min(xx + on, x2), y + 1), color, -1)
                cv2.rectangle(img, (xx, y2 - 1), (min(xx + on, x2), y2), color, -1)
        for y0 in range(y, y2, step + on):
            for yy in (y0, min(y2, y0 + on)):
                cv2.rectangle(img, (x, yy), (x + 1, min(yy + on, y2)), color, -1)
                cv2.rectangle(img, (x2 - 1, yy), (x2, min(yy + on, y2)), color, -1)
    else:
        cv2.rectangle(img, (x, y), (x2, y2), color, thickness)
    if label:
        cv2.putText(img, label, (x, max(12, y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def annotate(image, record, gt_by_image, zoom=1):
    """返回叠好框的图（BGR）。`record` 是 eval JSON 里的一条 image 记录。"""
    img = image.copy()
    if zoom != 1:
        img = cv2.resize(img, None, fx=zoom, fy=zoom,
                         interpolation=cv2.INTER_NEAREST)

    def z(box):
        return [v * zoom for v in box]

    matched = record["matched"]
    hit_gt = {tuple(m["gt_box"]) for m in matched if m["ok"]}
    for miss_text in record["misses"]:
        # manifest 里按文本找框：同词多次出现时取第一个未用掉的
        pool = [g for g in gt_by_image if norm(g["text"]) == norm(miss_text)
                and tuple(g["bbox"]) not in hit_gt]
        if not pool:
            continue
        gt = pool[0]
        hit_gt.add(tuple(gt["bbox"]))
        draw_box(img, z(gt["bbox"]), C_MISS, 2, "MISS " + gt["text"],
                 dashed=True, scale=0.45 * zoom)

    for m in matched:
        loose = m["iou"] < 0.5
        color = C_WRONG if not m["ok"] else (C_LOOSE if loose else C_HIT)
        label = "%s%s" % (m["gt"], "" if m["ok"] else "→" + m["pred"])
        if loose and m["ok"]:
            label += " iou%.2f" % m["iou"]
        draw_box(img, z(m["gt_box"]), color, 2, label, scale=0.42 * zoom)
        # 预测框画在真实框右侧一点，避免两线完全重合看不出偏差
        pb = list(m["pred_box"])
        pb[0] += 3
        draw_box(img, z(pb), C_PRED, 1, "", scale=0.4 * zoom)

    for ex in record["extras"]:
        # 多余词没有 GT 框可对，只统计数量（`index.md` 里的「多余」列）；
        # 要看具体是哪些词，读 eval JSON 的 `extras` 字段。
        pass
    return img


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--engine", default="rapid")
    ap.add_argument("--eval-json", default=str(TRAINER / "reports" /
                                               "eval_%s_latest.json"))
    ap.add_argument("--manifest", default=str(TRAINER / "datasets" /
                                              "manifests" / "generated.jsonl"))
    ap.add_argument("--out", default=str(TRAINER / "reports" / "misses"))
    ap.add_argument("--cases", default="", help="逗号分隔的 case_id")
    ap.add_argument("--all", action="store_true",
                    help="连满分的图也出（默认只出 recall<100%% 或 IoU<0.5 的）")
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--max-tiles", type=int, default=12, help="总览拼贴最多几格")
    args = ap.parse_args(argv)

    eval_path = Path(args.eval_json % args.engine if "%s" in args.eval_json
                     else args.eval_json)
    if not eval_path.is_file():
        raise SystemExit("[miss] 找不到评测结果：%s\n"
                         "       先跑：python Trainer/scripts/evaluate_ocr.py "
                         "--engine %s" % (eval_path, args.engine))
    data = json.loads(eval_path.read_text(encoding="utf-8"))
    gt = {rec["image_id"]: rec["words"] for rec in load_manifest(Path(args.manifest))}
    manifest_paths = {rec["image_id"]: rec["path"]
                      for rec in load_manifest(Path(args.manifest))}

    want_cases = {c.strip() for c in args.cases.split(",") if c.strip()}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, tiles = [], []
    for rec in data["images"]:
        if want_cases and rec["case"] not in want_cases:
            continue
        loose = [m for m in rec["matched"] if m["ok"] and m["iou"] < 0.5]
        interesting = (rec["correct"] < rec["gt"] or loose
                       or rec["extra"] or rec["error"])
        if not (args.all or interesting):
            continue
        path = ROOT / manifest_paths.get(rec["image_id"], rec["path"])
        image = cv2.imread(str(path))
        if image is None:
            print("[miss] 读不到图：%s" % path)
            continue
        zoom = args.zoom if args.zoom != 1 else (
            2.0 if max(image.shape[1], image.shape[0]) < 1400 else 1.0)
        ann = annotate(image, rec, gt.get(rec["image_id"], []), zoom)
        name = "%s.png" % rec["image_id"]
        cv2.imwrite(str(out_dir / name), ann)
        rows.append({
            "image": rec["image_id"], "case": rec["case"], "file": "misses/" + name,
            "gt": rec["gt"], "correct": rec["correct"], "miss": rec["miss"],
            "wrong_text": rec["wrong_text"], "extra": rec["extra"],
            "merged": rec["merged"], "split": rec["split"],
            "loose_box": len(loose),
            "worst_loose": (sorted(loose, key=lambda m: m["iou"])[0] if loose else None),
            "misses": rec["misses"][:12], "error": rec["error"],
        })
        thumb = cv2.resize(ann, (640, int(640 * ann.shape[0] / ann.shape[1])),
                           interpolation=cv2.INTER_AREA)
        tiles.append((rec["image_id"], thumb))
        print("[miss] %-30s → misses/%s  (漏%d 错%d 多%d 歪框%d)"
              % (rec["image_id"], name, rec["miss"], rec["wrong_text"],
                 rec["extra"], len(loose)))

    index = out_dir / "index.md"
    lines = ["# 漏识别与错误框报告（engine=%s）" % data["engine"], "",
             "> 生成方式：`python Trainer/scripts/visualize_misses.py`；"
             "底层数据来自 `Trainer/reports/%s`。" % eval_path.name,
             "> 默认只列出「没全对」的图（`--all` 可全出）。绿=命中，蓝=预测框，"
             "橙虚线=漏词，黄=文本识别错，品红=IoU<0.5 的歪框。", "",
             "| 图片 | 场景 | 真实/正确 | 漏 | 错字 | 多余 | 粘连 | 错切 | IoU<0.5 | 漏掉的词 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append("| [%s](%s) | %s | %d/%d | %d | %d | %d | %d | %d | %d | %s |"
                     % (r["image"], r["file"], r["case"], r["correct"], r["gt"],
                        r["miss"], r["wrong_text"], r["extra"], r["merged"],
                        r["split"], r["loose_box"],
                        ", ".join("`%s`" % w for w in r["misses"]) or "-"))
    bad = [r for r in rows if r["error"]]
    if bad:
        lines += ["", "## 异常样本", ""]
        for r in bad:
            lines.append("- `%s`: %s" % (r["image"], r["error"]))
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if tiles:
        cols = 2 if len(tiles) > 1 else 1
        tiles = tiles[:args.max_tiles]
        rows_n = (len(tiles) + cols - 1) // cols
        pad, cap = 8, 22
        h_max = max(t.shape[0] for _, t in tiles)
        sheet = np.zeros((rows_n * (h_max + pad + cap) + pad,
                          cols * (640 + pad) + pad, 3), np.uint8)
        sheet[:] = 24
        for i, (name, tile) in enumerate(tiles):
            r, c = divmod(i, cols)
            y = pad + r * (h_max + pad + cap)
            sheet[y:y + tile.shape[0], pad + c * (640 + pad):
                  pad + c * (640 + pad) + 640] = tile
            cv2.putText(sheet, "%s  (%d/%d shown of %d)" %
                        (name, len(tiles), len(tiles), len(rows)),
                        (pad + c * (640 + pad), y + h_max + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1,
                        cv2.LINE_AA)
        overview = out_dir / "_overview.png"
        cv2.imwrite(str(overview), sheet)
        print("\n[miss] 总览 → %s" % overview)

    print("[miss] 索引 → %s  （%d 张图）" % (index, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
