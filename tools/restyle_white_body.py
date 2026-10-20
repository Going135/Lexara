# -*- coding: utf-8 -*-
"""白跳蛛腹部贴图重制 —— 把用户新美术素材铺进标准皮肤框。

皮肤契约（skin_manifest.json asset_contract）：身体源图必须铺满
256×156 画布（可见区 2..254 × 2..154，比例 30.6:18.7），运行时 Qt
IgnoreAspectRatio 严格铺满局部坐标框，+x = 头部方向。

新素材是竖构图（大头朝上、腰球朝下）：
  · 90° 逆时针旋转 → 腰球朝右 = 朝头（真跳蛛腹部后宽前窄）；
  · LANCZOS 非等比铺满 252×152 可见区 —— 与旧素材同一占位，
    圆形肚子被拉成和旧版一样的横椭圆剪影，四套皮肤视觉大小不串。

用法：python tools/restyle_white_body.py <源图路径>
"""
import os
import sys

from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(BASE, "assets", "skins", "white_jump_spider_body.png")
BACKUP = os.path.join(BASE, "backup", "white_jump_spider_body_prev_20261017.png")

CANVAS = (256, 156)
VIS = (252, 152)          # 可见区（契约 visible_size_px，四周留 2px 边）


def main(src, ball_right=True):
    im = Image.open(src).convert("RGBA")
    # 用 alpha 阈值取紧包围盒：源图边缘有 alpha=1 的量化噪声，getbbox 会虚胖
    alpha = im.split()[3].point(lambda v: 255 if v >= 10 else 0)
    bbox = alpha.getbbox()
    if not bbox:
        raise SystemExit("源图全透明？")
    im = im.crop(bbox)
    print("源可见区", im.size, "比例 %.2f" % (im.size[0] / im.size[1]))

    # 竖构图 → 横框：ball（腰球）朝 +x（右=朝头）用 ROTATE_90（逆时针，底边→右）；
    # 朝后（左）用 ROTATE_270。
    im = im.transpose(Image.Transpose.ROTATE_90 if ball_right
                      else Image.Transpose.ROTATE_270)
    print("旋转后", im.size)

    im = im.resize(VIS, Image.LANCZOS)
    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    canvas.paste(im, (2, 2), im)

    if os.path.exists(DST) and not os.path.exists(BACKUP):
        os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
        canvas_old = Image.open(DST)
        canvas_old.save(BACKUP)
        print("旧素材已备份 →", BACKUP)

    # 渐变/高光素材用 RGBA 真彩保存（索引量化会在柔光上出色带）
    canvas.save(DST)
    print("已写入", DST)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\35388\Desktop\copy_副本.png"
    # 第二个参数：ball=朝头(+x，默认) / rear=朝后(-x)
    main(src, ball_right=(len(sys.argv) < 3 or sys.argv[2] != "rear"))
