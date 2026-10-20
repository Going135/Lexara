# -*- coding: utf-8 -*-
"""新美术素材铺进标准皮肤/裂纹框（2026-10-18 第三次换皮）。

三条链路，规则不同，所以不并成一个函数：

1. **身子**（白底 JPG → 256×156）：源图是横构图、小圆帽在**左**；
   原素材约定小圆帽朝 +x（右 = 朝头），所以先水平镜像再非等比铺满可见区。
   白跳蛛的圆顶身子例外：它 1.20:1，身体框 1.64:1，非等比铺满会拉成胶囊，
   所以走 `fit_body()` 保比例、靠前缘对齐（用户 2026-10-18 明确要求）。
2. **头**（白底或黑底 JPG → 160×170）：素材要**预先顺时针转 90°**。
   渲染层 `_paint_image_body` 对所有图皮的头统一 `rotate(-90)`（逆时针），
   所以正着存进去的头，屏幕上会变成「眼睛竖着排、嘴在右边」。
   旧奶蛛头是六眼放射对称的，转了看不出来，一直没人发现；新头是方形笑脸，
   一测就露馅（`.workbuddy/shots/zoom_milk_head.png` 就是证据）。
   预转 90° 顺时针，渲染层的逆时针正好抵回正立。
   黑底图（白跳蛛）不能沿用白底那套：flood fill 的种子色是黑，容差要放大到
   把柔和投影一起吃掉，否则浅色卡片上会挂一圈灰边。
3. **玻璃损毁**（白底 JPG → 1152×736）：裂纹是**按整块展示区**铺的，
   非等比拉伸会把放射状裂纹压扁，所以这里**保比例**缩放后居中（留白透明）。

用法：
    python tools/apply_skin_art.py spiders --milk-body B.jpg --milk-head H.jpg \\
                                          --white-head W.jpg
    python tools/apply_skin_art.py cracks C1.jpg C2.jpg C3.jpg      # → jar_crack_01..03
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

import cv2
import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKINS = os.path.join(BASE, "assets", "skins")
ASSETS = os.path.join(BASE, "assets")
BACKUP = os.path.join(BASE, "backup", "art_prev_20261018")

#: 皮肤契约见 assets/skins/skin_manifest.json（与 apply_milk_art.py 一致）
BODY_CANVAS = (256, 156)
BODY_VIS = (252, 152)
HEAD_CANVAS = (160, 170)
HEAD_VIS = (156, 166)
#: 裂纹画布（launcher_window 用它整块铺展示区）
CRACK_CANVAS = (1152, 736)
#: 裂纹四周留一点透明，避免边角硬切在卡片描边上
CRACK_MARGIN = 0.012
#: 必须与 launcher_window.IMPACT 一致（图会被整块拉伸铺满展示区）
IMPACT = (0.500, 0.440)


def _flood(bgr: np.ndarray, seed_value: int, tol: int) -> np.ndarray:
    """四角 flood fill：只填与边框连通、且接近 `seed_value` 的区域。

    ★ 必须 `FLOODFILL_FIXED_RANGE`：不带它时比较的是**邻居像素**，物体边缘
      那圈抗锯齿会把填充一路渗进物体内部（实测整块变透明）。
    """
    h, w = bgr.shape[:2]
    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 8 | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    diff = (tol, tol, tol)
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        cv2.floodFill(bgr.copy(), mask, seed, seed_value, diff, diff, flags)
    return mask[1:-1, 1:-1].astype(bool)


def cutout_white(path: str, tol: int = 18) -> Image.Image:
    """白底 → RGBA。边沿做 un-matte，否则贴到浅色卡片上会有一圈灰白毛边。"""
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit("读不了 %s" % path)
    bg = _flood(bgr, 255, tol)
    alpha = np.where(bg, 0.0, 1.0)

    soft = cv2.GaussianBlur(alpha.astype(np.float32), (3, 3), 0.7)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
    a = np.clip(soft, 0.0, 1.0)[..., None]

    safe = np.maximum(a, 0.06)
    unmatte = np.clip((rgb - 255.0 * (1.0 - a)) / safe, 0.0, 255.0)
    out_rgb = np.where(a < 0.06, rgb, unmatte)
    return Image.fromarray(np.dstack([out_rgb, a * 255.0]).round().astype(np.uint8), "RGBA")


def cutout_black(path: str, tol: int = 92) -> Image.Image:
    """黑底 → RGBA（白跳蛛头）。

    容差比白底大得多：这张图的主体后面有一层柔和投影（0→60 的灰），
    容差 18 只能啃掉最外圈，剩下的灰会在浅色卡片上挂成一圈脏边。
    92 能把投影和抗锯齿的内半圈一起吃进背景；接缝处再 un-matte 一次
    （观测值 = 真色 × a + 黑 × (1-a)，所以真色 = obs / a），白色主体回到纯白。
    """
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit("读不了 %s" % path)
    bg = _flood(bgr, 0, tol)
    alpha = np.where(bg, 0.0, 1.0)
    soft = cv2.GaussianBlur(alpha.astype(np.float32), (3, 3), 0.9)

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
    a = np.clip(soft, 0.0, 1.0)[..., None]
    safe = np.maximum(a, 0.12)
    unmatte = np.clip(rgb / safe, 0.0, 255.0)
    out_rgb = np.where(a < 0.10, rgb, unmatte)
    return Image.fromarray(np.dstack([out_rgb, a * 255.0]).round().astype(np.uint8), "RGBA")


def cutout_glass(path: str, white: int = 250) -> Image.Image:
    """玻璃裂纹 → RGBA：**所有**纯白都算透明，不只是和边框相连的白。

    这一条和 `cutout_white` 的差别很关键：裂纹是「放射状星芒」，星芒之间的
    大块白底被玻璃片围在中间，不跟画布边框相连，四角 flood fill 根本填不到。
    实测直接 flood fill 会在展示区里留下几块死白补丁（
    `.workbuddy/shots/cracks_preview.png` 第一版就是），像贴了白纸。
    这里的判据是「三通道都 ≥ 250」：源图里真正是玻璃的位置都带蓝灰调
    （实测 235,247,255 / 193,209,224），不会误伤。
    """
    rgb_img = Image.open(path).convert("RGB")
    arr = np.array(rgb_img).astype(np.float32)
    alpha = np.where(arr.min(axis=2) >= white, 0.0, 1.0)
    soft = cv2.GaussianBlur(alpha.astype(np.float32), (3, 3), 0.6)

    a = np.clip(soft, 0.0, 1.0)[..., None]
    safe = np.maximum(a, 0.08)
    unmatte = np.clip((arr - 255.0 * (1.0 - a)) / safe, 0.0, 255.0)
    out_rgb = np.where(a < 0.08, arr, unmatte)
    return Image.fromarray(np.dstack([out_rgb, a * 255.0]).round().astype(np.uint8), "RGBA")


def tight(im: Image.Image, threshold: int = 10) -> Image.Image:
    alpha = im.split()[3].point(lambda v: 255 if v >= threshold else 0)
    box = alpha.getbbox()
    if not box:
        raise SystemExit("源图全透明？")
    return im.crop(box)


def upright_for_renderer(im: Image.Image) -> Image.Image:
    """顺时针 90° —— 抵消渲染层 `rotate(-90)`，屏幕上才是正立的头。"""
    return im.transpose(Image.Transpose.ROTATE_270)


def fit_stretch(im: Image.Image, vis: tuple[int, int], canvas: tuple[int, int]) -> Image.Image:
    """非等比铺满可见区，居中放进标准画布（皮肤贴图契约要求铺满，不能留白）。"""
    resized = im.resize(vis, Image.LANCZOS)
    out = Image.new("RGBA", canvas, (0, 0, 0, 0))
    out.paste(resized, ((canvas[0] - vis[0]) // 2,
                        (canvas[1] - vis[1]) // 2), resized)
    return out


def fit_contain(im: Image.Image, canvas: tuple[int, int], margin: float,
                align: tuple[float, float] | None = None) -> Image.Image:
    """保比例缩放后居中：玻璃裂纹是放射状的，压扁一眼就能看出来。

    `align` 给出裂纹中心应落在画布的哪个比例位置。必须给：`JarView` 是把整张
    图直接拉伸铺满展示区的，撞击点写在 `launcher_window.IMPACT=(0.5, 0.44)`，
    图里的爆点在 0.5,0.5 的话，裂纹会从肚子底下而不是撞击点散开。
    """
    cw, ch = canvas
    box_w, box_h = cw * (1 - margin * 2), ch * (1 - margin * 2)
    scale = min(box_w / im.width, box_h / im.height)
    size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    resized = im.resize(size, Image.LANCZOS)

    out = Image.new("RGBA", canvas, (0, 0, 0, 0))
    if align is None:
        pos = ((cw - size[0]) // 2, (ch - size[1]) // 2)
    else:
        # 爆点 = alpha 加权重心（裂纹是绕撞击点放射的，重心够近似）
        alpha = np.array(resized)[:, :, 3].astype(np.float32)
        ys_idx, xs_idx = np.nonzero(alpha >= 20)
        if len(xs_idx):
            weights = alpha[ys_idx, xs_idx]
            cx = float((xs_idx * weights).sum() / weights.sum())
            cy = float((ys_idx * weights).sum() / weights.sum())
        else:
            cx, cy = size[0] / 2, size[1] / 2
        pos = (round(cw * align[0] - cx), round(ch * align[1] - cy))
        pos = (min(max(0, pos[0]), cw - size[0]), min(max(0, pos[1]), ch - size[1]))
    out.paste(resized, pos, resized)
    return out


def fit_body(im: Image.Image, canvas: tuple[int, int] = BODY_CANVAS,
             vis: tuple[int, int] = BODY_VIS) -> Image.Image:
    """身体按**原比例**缩放进可见区，靠前缘（朝头那侧）对齐。

    渲染层 `_skin_pixmap` 用 `IgnoreAspectRatio` 把整张画布铺满身体框
    （76.5×46.75 → 1.64:1），所以只要画布本身是 256×156（1.64:1）、里面
    的内容保比例，屏幕上就不会变形 —— 拉伸发生在画布内部时才有意义。

    为什么从前缘对齐：身体前缘要和头接住，靠后留白只是「肚子短一点」，
    居中或靠后都会在脖子处露出一道缝。
    """
    cw, ch = canvas
    vw, vh = vis
    scale = min(vw / im.width, vh / im.height)
    size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    resized = im.resize(size, Image.LANCZOS)
    out = Image.new("RGBA", canvas, (0, 0, 0, 0))
    out.paste(resized, (cw - (cw - vw) // 2 - size[0], (ch - size[1]) // 2),
              resized)
    return out


def save(im: Image.Image, path: str, note: str) -> None:
    os.makedirs(BACKUP, exist_ok=True)
    if os.path.exists(path):
        keep = os.path.join(BACKUP, os.path.basename(path))
        if not os.path.exists(keep):
            shutil.copy2(path, keep)
    im.save(path)
    print("  %-34s %-10s %s" % (note, "%dx%d" % im.size, os.path.basename(path)))


def do_spiders(args) -> int:
    if not any((args.milk_body, args.milk_head, args.white_head, args.white_body)):
        raise SystemExit("至少要给一个 --milk-body / --milk-head / --white-head / --white-body")

    if args.white_body:
        print("白跳蛛身子 ←", os.path.basename(args.white_body))
        wbody = tight(cutout_white(args.white_body))
        print("    源可见区 %dx%d  比例 %.3f" % (wbody.size[0], wbody.size[1],
                                                wbody.size[0] / wbody.size[1]))
        # 源图是「圆顶朝上、平底朝下」的竖构图。局部坐标里 +x 是朝头方向，
        # 所以把平底转到**右**边（= 头那一侧）：逆时针 90° 后底边落到右侧。
        # 反过来转（平底朝左）就成了「屁股被切平」，一眼出戏。
        wbody = wbody.transpose(Image.Transpose.ROTATE_90)
        # ★ 2026-10-18 22:2x：改成**保比例**缩放进 252×152（用户反馈「程序里被
        #   拉长了」）。源图 1.20:1，身体框 1.64:1，非等比铺满会把厚度压掉一半，
        #   圆顶变成一根胶囊。保比例后靠前缘对齐，脖子处不会露缝。
        save(fit_body(wbody),
             os.path.join(SKINS, "white_jump_spider_body.png"), "白跳蛛身子")

    if args.milk_body:
        print("奶蛛身子 ←", os.path.basename(args.milk_body))
        body = tight(cutout_white(args.milk_body))
        print("    源可见区 %dx%d  比例 %.3f" % (body.size[0], body.size[1],
                                                body.size[0] / body.size[1]))
        # 小圆帽在左 → 镜像到右（+x 是朝头方向）
        body = body.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        save(fit_stretch(body, BODY_VIS, BODY_CANVAS),
             os.path.join(SKINS, "milk_spider_body.png"), "奶蛛身子")

    if args.milk_head:
        print("奶蛛头 ←", os.path.basename(args.milk_head))
        head = upright_for_renderer(tight(cutout_white(args.milk_head)))
        print("    源可见区 %dx%d  比例 %.3f" % (head.size[0], head.size[1],
                                                head.size[0] / head.size[1]))
        save(fit_stretch(head, HEAD_VIS, HEAD_CANVAS),
             os.path.join(SKINS, "milk_spider_head.png"), "奶蛛头")

    if args.white_head:
        print("白跳蛛头 ←", os.path.basename(args.white_head))
        whead = upright_for_renderer(tight(cutout_black(args.white_head)))
        print("    源可见区 %dx%d  比例 %.3f" % (whead.size[0], whead.size[1],
                                                whead.size[0] / whead.size[1]))
        save(fit_stretch(whead, HEAD_VIS, HEAD_CANVAS),
             os.path.join(SKINS, "white_jump_spider_head.png"), "白跳蛛头")
    return 0


def do_cracks(args) -> int:
    for index, src in enumerate(args.sources, start=1):
        print("裂纹 %d ← %s" % (index, os.path.basename(src)))
        crack = tight(cutout_glass(src))
        print("    源可见区 %dx%d  比例 %.3f" % (crack.size[0], crack.size[1],
                                                crack.size[0] / crack.size[1]))
        save(fit_contain(crack, CRACK_CANVAS, CRACK_MARGIN, IMPACT),
             os.path.join(ASSETS, "jar_crack_%02d.png" % index), "玻璃损毁 %02d" % index)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="新美术素材 → 标准皮肤/裂纹框")
    sub = parser.add_subparsers(dest="cmd", required=True)

    spiders = sub.add_parser("spiders", help="换奶蛛头身 / 白跳蛛头身（按需给）")
    spiders.add_argument("--milk-body")
    spiders.add_argument("--milk-head")
    spiders.add_argument("--white-head")
    spiders.add_argument("--white-body")
    spiders.set_defaults(func=do_spiders)

    cracks = sub.add_parser("cracks", help="换三张玻璃损毁贴图")
    cracks.add_argument("sources", nargs=3, metavar="IMG")
    cracks.set_defaults(func=do_cracks)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
