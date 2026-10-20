# -*- coding: utf-8 -*-
"""奶蛛美术换新：把用户给的两张白底 JPG（身子 / 头）铺进标准皮肤框。

皮肤契约见 `assets/skins/skin_manifest.json`：身体画布 256×156（可见区 252×152，
+x = 朝头方向），头部画布 160×170（可见区 156×166），运行时 Qt 用
IgnoreAspectRatio 严格铺满局部坐标框 —— 所以源图必须**先裁到有效区、再非等比
拉伸**，不能自己留白。

两张源图都是 1254×1254 纯白底 JPG，处理链：
  1. 四角 flood fill 取背景（cv2，容差 18）→ 只保留与边框相连的白，
     物体内部的亮部（高光、眼白）不会被抠穿；
  2. 边沿去白边（un-matte）：C = (C_obs - 255*(1-a)) / a，不然贴到浅色卡片上
     会有一圈灰白毛边 —— 素材本身是高亮黄色，白边比别的颜色更明显；
  3. 按 alpha 取紧包围盒（阈值 10，JPEG 在纯白区有 alpha 噪声）；
  4. 身子：小圆帽（腰球）在上 → 顺时针 90° 让小圆帽朝 +x（朝头），
     大头（后宽前窄的腹部）落到后面；
  5. 头：保持正立（和旧奶蛛头素材同向，渲染层会再逆时针转 90°）。

用法：
    python tools/apply_milk_art.py <身子图> <头图>
"""
from __future__ import annotations

import os
import shutil
import sys

import cv2
import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKINS = os.path.join(BASE, "assets", "skins")
BACKUP = os.path.join(BASE, "backup")

BODY_CANVAS = (256, 156)
BODY_VIS = (252, 152)
HEAD_CANVAS = (160, 170)
HEAD_VIS = (156, 166)

#: 背景容差：JPG 在纯白边上有 3~10 的振铃，18 够吃掉。
TOL = 18


def cutout(path: str) -> Image.Image:
    """白底 JPG → 带 alpha 的 RGBA（只抠与边框连通的白色）。"""
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit("读不了 %s" % path)
    h, w = bgr.shape[:2]

    mask = np.zeros((h + 2, w + 2), np.uint8)
    # ★ 必须带 FLOODFILL_FIXED_RANGE：不带它时 floodFill 比较的是**邻居像素**，
    #   物体边缘那圈抗锯齿渐变会把填充一路「渗」进整个物体（实测 alpha 99.9%
    #   变 0，黄色身子变成一片透明，只剩眼珠）。带上的话只对比种子值（纯白），
    #   容差 18 之外一律不填。
    flags = 8 | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    diff = (TOL, TOL, TOL)
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        cv2.floodFill(bgr.copy(), mask, seed, 255, diff, diff, flags)

    bg = mask[1:-1, 1:-1].astype(bool)
    alpha = np.where(bg, 0.0, 1.0)

    # 1px 羽化 + 去白边。羽化只在边界上做，内部像素 a=1 保持原样。
    soft = cv2.GaussianBlur(alpha.astype(np.float32), (3, 3), 0.7)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)

    a = np.clip(soft, 0.0, 1.0)[..., None]
    # un-matte：观测值 = 真色*a + 白*(1-a)  →  真色 = (obs - 255*(1-a)) / a
    safe = np.maximum(a, 0.06)
    unmatte = (rgb - 255.0 * (1.0 - a)) / safe
    unmatte = np.clip(unmatte, 0.0, 255.0)
    # a 很小时 un-matte 会放大噪声，直接沿用未处理色（反正不可见）
    out_rgb = np.where(a < 0.06, rgb, unmatte)

    rgba = np.dstack([out_rgb, a * 255.0]).round().astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def tight_bbox(im: Image.Image, threshold: int = 10) -> Image.Image:
    alpha = im.split()[3].point(lambda v: 255 if v >= threshold else 0)
    box = alpha.getbbox()
    if not box:
        raise SystemExit("源图全透明？")
    return im.crop(box)


def fit(im: Image.Image, vis: tuple[int, int], canvas: tuple[int, int]) -> Image.Image:
    """非等比铺满可见区，居中放进标准画布（四周留 2px）。"""
    resized = im.resize(vis, Image.LANCZOS)
    out = Image.new("RGBA", canvas, (0, 0, 0, 0))
    out.paste(resized, ((canvas[0] - vis[0]) // 2, (canvas[1] - vis[1]) // 2), resized)
    return out


def backup(name: str) -> None:
    dst = os.path.join(SKINS, name)
    if not os.path.exists(dst):
        return
    os.makedirs(BACKUP, exist_ok=True)
    keep = os.path.join(BACKUP, "milk_art_prev_20261017", name)
    if os.path.exists(keep):
        return
    os.makedirs(os.path.dirname(keep), exist_ok=True)
    shutil.copy2(dst, keep)
    print("  旧素材备份 →", keep)


def main(body_src: str, head_src: str) -> int:
    # ---- 身子 ----
    body = tight_bbox(cutout(body_src))
    print("身子 源可见区", body.size, "比例 %.3f" % (body.size[0] / body.size[1]))
    # 小圆帽在**上**（源图竖构图），要让它朝 +x（右=朝头）→ 顺时针 90°。
    # PIL 的 ROTATE_270 = 逆时针 270° = 顺时针 90°，顶边→右边。
    body = body.transpose(Image.Transpose.ROTATE_270)
    print("身子 旋转后", body.size)
    body_canvas = fit(body, BODY_VIS, BODY_CANVAS)
    backup("milk_spider_body.png")
    body_canvas.save(os.path.join(SKINS, "milk_spider_body.png"))
    print("  已写入 milk_spider_body.png", body_canvas.size)

    # ---- 头 ----
    head = tight_bbox(cutout(head_src))
    print("头   源可见区", head.size, "比例 %.3f" % (head.size[0] / head.size[1]))
    head_canvas = fit(head, HEAD_VIS, HEAD_CANVAS)
    backup("milk_spider_head.png")
    head_canvas.save(os.path.join(SKINS, "milk_spider_head.png"))
    print("  已写入 milk_spider_head.png", head_canvas.size)

    # 预览图：贴在浅色背景上，检查有没有白边/漏抠
    sheet = Image.new("RGB", (720, 360), (250, 250, 247))
    b = body_canvas.resize((BODY_VIS[0], BODY_VIS[1]), Image.LANCZOS)
    hd = head_canvas.resize((HEAD_VIS[0], HEAD_VIS[1]), Image.LANCZOS)
    sheet.paste(b, (40, 60), b)
    sheet.paste(hd, (400, 40), hd)
    out = os.path.join(BACKUP, "milk_art_check.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out)
    print("  预览 →", out)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("用法: apply_milk_art.py <身子图> <头图>")
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
