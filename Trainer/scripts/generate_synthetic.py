# -*- coding: utf-8 -*-
"""生成可控的英文单词识别合成样本 + ground truth（JSONL）。

为什么先做合成数据：真实截图的词框要人肉标注，标注本身不可信；
合成图里每个词的框是**画出来时就知道的**，所以「识别对不对」和「框贴不贴」
第一次有了可复现的量化口径。真实截图（`datasets/real_world/`）只用于
词集召回率，不参与 IoU 统计（见 README 的标注分级）。

用法：
    python Trainer/scripts/generate_synthetic.py                      # 全量
    python Trainer/scripts/generate_synthetic.py --profile quick      # 回归用小样本
    python Trainer/scripts/generate_synthetic.py --out ... --manifest ... --seed 7

输出：
    datasets/generated/<case_id>.png
    datasets/manifests/generated.jsonl     每行一个 image_id（含 words[]）
    datasets/manifests/generated_index.json 汇总（字体/尺寸/参数，供报告引用）

标注字段（`Trainer/README.md` 里是权威定义）：
    image_id, text, bbox=[x,y,w,h]（**图像像素**，原点左上，y 向下）,
    poly=[[x,y]*4]（旋转后的四点；未旋转时是 bbox 的四角）,
    line_id, case_sensitive=false, source="synthetic", difficulty_tags=[...]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
TRAINER = HERE.parent
ROOT = TRAINER.parent

# ---------------------------------------------------------------- 词表
#: 全部是真实英文词（能在 ECDICT 里查到），这样同一批图也能喂给词典链路做回归。
WORDS = """
release revenue spider window market bright digital forest laptop rocket station
thunder whisper mountain machine village family island object vision engine paper
silver shadow garden pencil camera bottle yellow future signal memory planet river
light orange energy bridge pocket candle marble angle motion winter summer circle
travel cotton dream nature desert ocean phone tree system smooth calm vector flower
""".split()

#: 带标点/数字/连字符的干扰样本（任务书 §2.2「干扰」一栏）
DISTRACTORS = [
    ("well-known", "hyphen"),
    ("don't", "apostrophe"),
    ("v2.4", "version"),
    ("error: 404", "digits"),
    ("https://lexara.dev/docs", "url"),
    ("SPIDER", "allcaps"),
    ("Spider", "titlecase"),
    ("spiders", "plural"),
    ("(release)", "parens"),
    ("release,", "trailing-comma"),
    ("数据release同步", "cjk-adjacent"),
    ("café naïve", "non-latin"),
]

FONTS = {
    "sans": ("segoeui", "C:/Windows/Fonts/segoeui.ttf"),
    "sans_bold": ("segoeui-bold", "C:/Windows/Fonts/segoeuib.ttf"),
    "sans_italic": ("segoeui-italic", "C:/Windows/Fonts/segoeuii.ttf"),
    "arial": ("arial", "C:/Windows/Fonts/arial.ttf"),
    "arial_bold": ("arial-bold", "C:/Windows/Fonts/arialbd.ttf"),
    "arial_italic": ("arial-italic", "C:/Windows/Fonts/ariali.ttf"),
    "serif": ("times", "C:/Windows/Fonts/times.ttf"),
    "serif_italic": ("times-italic", "C:/Windows/Fonts/timesi.ttf"),
    "mono": ("consolas", "C:/Windows/Fonts/consola.ttf"),
    "cjk": ("msyh", "C:/Windows/Fonts/msyh.ttc"),
}


def font_for(kind: str, px: int) -> ImageFont.FreeTypeFont:
    name, path = FONTS[kind]
    if not os.path.isfile(path):               # 精简系统可能缺某个字族
        path = FONTS["sans"][1]
    return ImageFont.truetype(path, px)


def tight_box(draw: ImageDraw.ImageDraw, x: int, y: int, text: str,
              font) -> tuple:
    """把 (left, top-ascender) 落点换算成**贴合字形**的 [x, y, w, h]。

    PIL 的 textbbox 返回的是字形实际边界（含 descender），
    这正是我们要的「词本体框」，不是行高框。
    """
    b = draw.textbbox((x, y), text, font=font)
    return [b[0], b[1], b[2] - b[0], b[3] - b[1]]


def aabb(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [round(min(xs), 2), round(min(ys), 2),
            round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)]


# ---------------------------------------------------------------- 画布构造

class Canvas:
    """先画到「逻辑画布」，再按 dpi 倍率放大/旋转，得到最终图与变换后的标注。"""

    def __init__(self, w: int, h: int, bg=(255, 255, 255), gradient=False,
                 noise=0, photo_like=False, rng=None):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (w, h), bg)
        self.rng = rng or random.Random(0)
        #: 背景噪声/色块要的是「数组」随机数，`random.Random` 没有 `integers/size=`，
        #: 这里另开一个 numpy Generator，并用 `self.rng` 播种，保证整体仍可复现。
        self.np_rng = np.random.default_rng(self.rng.randrange(2 ** 32))
        if gradient:
            top = np.array(bg, dtype=np.float32)
            bottom = np.clip(top * 0.82, 0, 255)
            ramp = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
            arr = top[None, None, :] * (1 - ramp) + bottom[None, None, :] * ramp
            self.img = Image.fromarray(np.repeat(arr, w, axis=1).astype(np.uint8))
        if photo_like:
            # 模拟「文字压在图片上」：低频彩色块 + 高斯模糊，不需要外部素材
            arr = self.np_rng.integers(0, 255, size=(max(2, h // 12),
                                                     max(2, w // 12), 3),
                                       dtype=np.uint8)
            small = Image.fromarray(arr).resize((w, h), Image.BICUBIC)
            self.img = Image.blend(self.img, small, 0.55)
        if noise:
            arr = np.asarray(self.img).astype(np.int16)
            arr += self.np_rng.integers(-noise, noise + 1, size=arr.shape,
                                        dtype=np.int16)
            self.img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        self.draw = ImageDraw.Draw(self.img, "RGBA")
        self.words = []      # [{text, box, line_id, tags}]

    # ---- 文本 ----
    def text(self, x, y, text, px=20, kind="sans", fill=(20, 20, 20, 255),
             line_id="L0", tags=(), letter_spacing=0):
        font = font_for(kind, px)
        if letter_spacing:
            cx = x
            for ch in text:
                self.draw.text((cx, y), ch, font=font, fill=fill)
                cx += self.draw.textlength(ch, font=font) + letter_spacing
        else:
            self.draw.text((x, y), text, font=font, fill=fill)
        box = tight_box(self.draw, x, y, text, font)
        self.words.append({"text": text, "box": box, "line_id": line_id,
                           "tags": list(tags)})
        return box[0] + box[2]

    def line(self, x, y, words, px=20, kind="sans", fill=(20, 20, 20, 255),
             line_id="L0", gap=None, tags=()):
        font = font_for(kind, px)
        gap = gap if gap is not None else int(px * 0.45)
        cx = x
        for wd in words:
            cx = self.text(cx, y, wd, px=px, kind=kind, fill=fill,
                           line_id=line_id, tags=tags) + gap
        return cx

    # ---- 输出 ----
    def render(self, scale=1.0, angle=0.0):
        """放大 + 旋转，返回 (PIL.Image, [标注…])。标注同步做几何变换。"""
        w, h = int(self.w * scale), int(self.h * scale)
        img = self.img.resize((w, h), Image.LANCZOS) if scale != 1.0 else self.img
        raw = [(wd["text"], [v * scale for v in wd["box"]], wd["line_id"],
                wd["tags"]) for wd in self.words]
        if abs(angle) < 1e-6:
            out = img
            entries = [{"text": t, "bbox": [round(v, 2) for v in b],
                        "poly": [[b[0], b[1]], [b[0] + b[2], b[1]],
                                 [b[0] + b[2], b[1] + b[3]], [b[0], b[1] + b[3]]],
                        "line_id": lid, "tags": tg} for t, b, lid, tg in raw]
        else:
            a = math.radians(angle)
            ca, sa = math.cos(a), math.sin(a)
            # 旋转后画布要撑大，否则四角被裁
            nw = int(abs(w * ca) + abs(h * sa)) + 2
            nh = int(abs(w * sa) + abs(h * ca)) + 2
            out = Image.new("RGB", (nw, nh), (255, 255, 255))
            out.paste(img, (0, 0))
            cx0, cy0 = w / 2.0, h / 2.0
            ox, oy = nw / 2.0, nh / 2.0
            arr = np.asarray(img).astype(np.float32)
            import cv2
            m = cv2.getRotationMatrix2D((cx0, cy0), angle, 1.0)
            m[0, 2] += ox - cx0
            m[1, 2] += oy - cy0
            rotated = cv2.warpAffine(arr, m, (nw, nh), flags=cv2.INTER_CUBIC,
                                     borderValue=(255, 255, 255))
            out = Image.fromarray(np.clip(rotated, 0, 255).astype(np.uint8))

            def map_pt(px, py):
                return [round(m[0, 0] * px + m[0, 1] * py + m[0, 2], 2),
                        round(m[1, 0] * px + m[1, 1] * py + m[1, 2], 2)]

            entries = []
            for t, b, lid, tg in raw:
                poly = [map_pt(b[0], b[1]), map_pt(b[0] + b[2], b[1]),
                        map_pt(b[0] + b[2], b[1] + b[3]), map_pt(b[0], b[1] + b[3])]
                entries.append({"text": t, "bbox": aabb(poly), "poly": poly,
                                "line_id": lid, "tags": tg})
        return out, entries


# ---------------------------------------------------------------- 用例
#: profile=quick 时只跑这些（回归用，控制在十几张、几秒内）
QUICK_CASES = {"size_small", "size_medium", "size_large", "style_italic",
               "contrast_light_gray", "rotate_tilt_5", "layout_paragraph",
               "aspect_wide_flat", "distract_mixed", "dpi_150"}


def build_cases(rng_factory):
    """返回 [(case_id, builder)]；builder(rng) -> (Canvas, meta) 或直接 (img, entries, tags)。"""
    cases = []

    def add(cid, fn):
        cases.append((cid, fn))

    # —— 1. 字号 ——
    for cid, px in (("size_small", 13), ("size_medium", 20), ("size_large", 34)):
        def mk(px=px, cid=cid):
            def f(rng):
                words = rng.sample(WORDS, 6)
                c = Canvas(1100, 120)
                c.line(30, 40, words, px=px, tags=[cid])
                return c, {"difficulty_tags": [cid, "font_px=%d" % px]}
            return f
        add(cid, mk())

    # —— 2. 字体样式 ——
    for cid, kind, mutate in (
            ("style_regular", "sans", lambda w: w),
            ("style_bold", "sans_bold", lambda w: w),
            ("style_italic", "arial_italic", lambda w: w),
            ("style_mixed_case", "arial",
             lambda w: w.capitalize() if len(w) % 3 else w.upper())):
        def mk(kind=kind, mutate=mutate, cid=cid):
            def f(rng):
                base = rng.sample(WORDS, 6)
                words = [mutate(w) for w in base]
                c = Canvas(1100, 120)
                c.line(30, 40, words, px=22, kind=kind, tags=[cid])
                return c, {"difficulty_tags": [cid, "case=%s" % kind]}
            return f
        add(cid, mk())

    # —— 3. 颜色 / 透明度 / 低对比 ——
    for cid, fill, bg, tags in (
            ("contrast_light_gray", (170, 170, 170, 255), (255, 255, 255, 255), "light-gray"),
            ("contrast_semi_transparent", (30, 30, 30, 110), (255, 255, 255, 255), "alpha-43pct"),
            ("contrast_low", (205, 205, 205, 255), (232, 232, 232, 255), "bg-also-light"),
            ("contrast_on_gradient", (240, 240, 240, 255), (60, 60, 60, 255), "inverted"),
    ):
        def mk(fill=fill, bg=bg, tags=tags, cid=cid):
            def f(rng):
                c = Canvas(1100, 120, bg=bg[:3])
                c.line(30, 40, rng.sample(WORDS, 6), px=18, fill=fill,
                       tags=[cid, tags])
                return c, {"difficulty_tags": [cid, "contrast=" + tags]}
            return f
        add(cid, mk())

    # —— 4. 方向：水平 / 轻微倾斜 / 斜体角度 ——
    for cid, angle in (("rotate_0", 0.0), ("rotate_tilt_3", 3.0),
                       ("rotate_tilt_5", -5.0), ("rotate_tilt_12", 12.0)):
        def mk(angle=angle, cid=cid):
            def f(rng):
                c = Canvas(1000, 110)
                c.line(30, 35, rng.sample(WORDS, 5), px=22, tags=[cid])
                return c, {"difficulty_tags": [cid, "angle=%g" % angle],
                           "angle": angle}
            return f
        add(cid, mk())

    # —— 5. 排版 ——
    def layout_phrase(rng):
        c = Canvas(1200, 130)
        c.line(30, 45, ["the", "quarterly", "release", "report", "shows",
                        "revenue", "growth"], px=24, tags=["layout_phrase"])
        return c, {"difficulty_tags": ["phrase"]}

    def layout_paragraph(rng):
        c = Canvas(1200, 300)
        for i in range(4):
            c.line(30, 28 + i * 62, rng.sample(WORDS, 7), px=19,
                   line_id="L%d" % i, tags=["layout_paragraph"])
        return c, {"difficulty_tags": ["paragraph", "lines=4"]}

    def layout_two_column(rng):
        c = Canvas(1200, 320)
        for i in range(4):
            c.line(30, 28 + i * 70, rng.sample(WORDS, 3), px=18,
                   line_id="A%d" % i, tags=["two_column"])
            c.line(620, 28 + i * 70, rng.sample(WORDS, 3), px=18,
                   line_id="B%d" % i, tags=["two_column"])
        return c, {"difficulty_tags": ["two_column"]}

    def layout_web_ui(rng):
        c = Canvas(1280, 360, bg=(246, 247, 250))
        c.text(28, 18, "Dashboard", px=26, kind="sans_bold", tags=["web_ui"])
        for i, label in enumerate(["Overview", "Reports", "Settings", "Logout"]):
            c.text(28, 78 + i * 34, label, px=16, fill=(90, 96, 110, 255),
                   line_id="nav", tags=["web_ui"])
        c.line(240, 78, rng.sample(WORDS, 5), px=17, line_id="body",
               tags=["web_ui"])
        c.line(240, 130, rng.sample(WORDS, 6), px=17, line_id="body",
               tags=["web_ui"])
        c.text(240, 300, "© 2026 Lexara Labs", px=13, fill=(150, 150, 150, 255),
               line_id="footer", tags=["web_ui"])
        return c, {"difficulty_tags": ["web_ui", "mixed_sizes"]}

    def layout_code_subtitle(rng):
        c = Canvas(1280, 260, bg=(24, 26, 31))
        for i, ln in enumerate([
                "def scan_region(rect, dpr):",
                "    words = ocr.recognize(rect)",
                "    return assign_targets(words[:8])"]):
            c.text(28, 24 + i * 30, ln, px=17, kind="mono",
                   fill=(220, 224, 232, 255), line_id="code", tags=["code"])
        c.text(360, 200, "[ SPIDER ] scanning subtitle line now", px=20,
               fill=(255, 255, 255, 255), line_id="subtitle", tags=["subtitle"])
        return c, {"difficulty_tags": ["code", "subtitle", "dark_bg"]}

    for cid, fn in (("layout_phrase", layout_phrase),
                    ("layout_paragraph", layout_paragraph),
                    ("layout_two_column", layout_two_column),
                    ("layout_web_ui", layout_web_ui),
                    ("layout_code_subtitle", layout_code_subtitle)):
        add(cid, fn)

    # —— 6. 背景 ——
    for cid, kw in (("bg_solid", {}),
                    ("bg_gradient", {"gradient": True}),
                    ("bg_photo_like", {"photo_like": True}),
                    ("bg_video_frame", {"photo_like": True, "noise": 18}),
                    ("bg_noisy", {"noise": 40})):
        def mk(kw=kw, cid=cid):
            def f(rng):
                c = Canvas(1100, 140, bg=(250, 250, 250) if cid != "bg_gradient"
                           else (40, 40, 40), **kw)
                c.line(30, 45, rng.sample(WORDS, 6), px=22,
                       fill=(20, 20, 20, 255) if cid != "bg_gradient"
                       else (245, 245, 245, 255), tags=[cid])
                return c, {"difficulty_tags": ["background=" + cid]}
            return f
        add(cid, mk())

    # —— 7. 图像尺寸 / 选区形状 ——
    # 这三档对应真实框选最常见的三种形状：窄长条（一列菜单）、宽扁条（一行字幕）、
    # 整页高分辨率。宽扁条是 RapidOCR 检测端的历史死穴（见 ocr_engine 文档字符串）。
    for cid, (w, h, per_line, px) in (
            ("aspect_narrow_tall", (260, 900, 1, 22)),
            ("aspect_wide_flat", (1920, 150, 8, 24)),
            ("hires_page", (2200, 1400, 12, 20))):
        def mk(w=w, h=h, per_line=per_line, px=px, cid=cid):
            def f(rng):
                c = Canvas(w, h)
                rows = max(1, (h - 30) // int(px * 2.6))
                if cid == "aspect_wide_flat":
                    rows = 1
                for i in range(rows):
                    c.line(24, 16 + i * int(px * 2.6),
                           rng.sample(WORDS, per_line), px=px,
                           line_id="L%d" % i, tags=[cid])
                return c, {"difficulty_tags": ["shape=" + cid,
                                               "canvas=%dx%d" % (w, h)]}
            return f
        add(cid, mk())

    # —— 8. 干扰 ——
    def distract(rng):
        c = Canvas(1300, 320)
        for i in range(0, len(DISTRACTORS), 2):
            pair = DISTRACTORS[i:i + 2]
            y = 24 + (i // 2) * 62
            cx = 24
            for text, tag in pair:
                cx = c.text(cx, y, text, px=21, kind="arial",
                            line_id="D%d" % (i // 2),
                            tags=["distract", tag]) + 46
        return c, {"difficulty_tags": ["distractors", "punct", "digits", "cjk"]}

    add("distract_mixed", distract)

    # —— 9. DPI / 缩放（同一版式在 100/125/150% 下渲染）——
    for cid, scale in (("dpi_100", 1.0), ("dpi_125", 1.25), ("dpi_150", 1.5)):
        def mk(scale=scale, cid=cid):
            def f(rng):
                c = Canvas(900, 120)
                c.line(26, 40, rng.sample(WORDS, 5), px=20, tags=[cid])
                return c, {"difficulty_tags": ["dpi=%g" % scale], "scale": scale}
            return f
        add(cid, mk())

    # —— 10. 动态内容：字幕三帧（新词出现 / 旧词消失）——
    def subtitle_seq(rng):
        frames = []
        texts = ["the spider is climbing", "a new subtitle appears here",
                 "final caption with revenue"]
        for i, t in enumerate(texts):
            c = Canvas(1280, 200, bg=(12, 12, 14))
            c.text(120, 130, t, px=26, fill=(255, 255, 255, 255),
                   line_id="sub", tags=["subtitle_seq", "frame=%d" % i])
            frames.append((c, {"difficulty_tags": ["dynamic_subtitle",
                                                   "frame=%d" % i],
                               "seq": "subtitle", "frame": i}))
        return frames

    add("dynamic_subtitle_seq", subtitle_seq)
    return cases


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(TRAINER / "datasets" / "generated"))
    ap.add_argument("--manifest", default=str(TRAINER / "datasets" / "manifests" /
                                              "generated.jsonl"))
    ap.add_argument("--profile", choices=("full", "quick"), default="full")
    ap.add_argument("--seed", type=int, default=20261017)
    ap.add_argument("--cases", default="", help="逗号分隔的 case_id 过滤")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)

    wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
    records = []
    for cid, builder in build_cases(lambda: random.Random(args.seed)):
        if args.profile == "quick" and cid not in QUICK_CASES:
            continue
        if wanted and cid not in wanted:
            continue
        rng = random.Random("%s:%d" % (cid, args.seed))
        produced = builder(rng)
        if isinstance(produced, list):
            produced = produced
        else:
            produced = [produced]
        for idx, (canvas, meta) in enumerate(produced):
            scale = float(meta.get("scale", 1.0))
            angle = float(meta.get("angle", 0.0))
            img, entries = canvas.render(scale=scale, angle=angle)
            suffix = "" if len(produced) == 1 else "_%02d" % idx
            image_id = "%s%s" % (cid, suffix)
            path = out_dir / ("%s.png" % image_id)
            img.save(path)
            records.append({
                "image_id": image_id,
                "path": os.path.relpath(path, ROOT).replace("\\", "/"),
                "width": img.width, "height": img.height,
                "source": "synthetic",
                "seed": args.seed,
                "render": {"scale": scale, "angle": angle,
                           "canvas": [canvas.w, canvas.h]},
                "case": cid,
                "difficulty_tags": sorted(set(meta.get("difficulty_tags", []))),
                "words": [{"text": e["text"], "bbox": e["bbox"], "poly": e["poly"],
                           "line_id": e["line_id"], "case_sensitive": False,
                           "source": "synthetic",
                           "difficulty_tags": e["tags"]} for e in entries],
            })
            print("[gen] %-28s %5dx%-5d words=%d" % (image_id, img.width,
                                                     img.height, len(entries)))
    with open(args.manifest, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    index = {"profile": args.profile, "seed": args.seed,
             "images": len(records),
             "words": sum(len(r["words"]) for r in records),
             "cases": sorted({r["case"] for r in records}),
             "fonts": {k: v[1] for k, v in FONTS.items()}}
    with open(Path(args.manifest).with_name("generated_index.json"), "w",
              encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
    print("\n[done] %d 张图 / %d 个词标注 -> %s"
          % (index["images"], index["words"], args.manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
