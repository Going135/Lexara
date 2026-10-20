# -*- coding: utf-8 -*-
"""皮肤回归测试：四套皮肤能切、能画、**不改几何**，且设置能落盘。

这个套件盯的是三件最容易悄悄坏掉的事：

1. **换皮不能改形状**。皮肤只该替换「身体与头部的画法」和腿的颜色。
   一旦有人顺手在皮肤分支里动了 `leg.reach` / `THORAX` / `HEAD_*`，
   腿根、命中区、窗口尺寸会跟着变 —— 桌宠点不着、走位错乱，而且只在
   某一套皮肤下出现，极难定位。所以这里逐项对拍四套皮肤的几何。
2. **素材必须真的在**。打包漏了 `assets/skins` 的话，本地跑没事、
   发出去的 exe 里桌宠会集体「没身体」。所以按 manifest 契约校验尺寸。
3. **默认皮肤是白跳蛛**（用户口径）。这条写死，改回 original 会红。

运行：  python test/test_skin.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtCore import Qt                                        # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter                   # noqa: E402
from PySide6.QtWidgets import QApplication                           # noqa: E402

app = QApplication(sys.argv)

import crawler_spider as CS                                          # noqa: E402
import spider_painter as SP                                          # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if condition else "[FAIL]", name, detail))


def rendered(skin_id: str, unit: float = 1.6, heading: float = 0.0) -> QImage:
    """把某套皮肤画到一张图里。

    ★ 必须先把腿摆到静止位：新构造的 `Spider` 每条腿的 `knee`/`tip` 都是
      `(0, 0)`，要等第一次 `update()` 才解算。直接画的话八条腿全塌在体心上，
      「有没有画出腿」这类断言会全部失真。
    """
    spider = CS.Spider(size=1.0)
    spider.origin_px = (0.0, 0.0)
    for leg in spider.legs:
        foot = spider.rest_pos(leg)
        leg.tip = foot
        leg.knee = spider.solve_ik(leg.hip_pos, foot, leg.l1, leg.l2, leg.bend)

    image = QImage(420, 360, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    layer = SP.SpiderPainter()
    layer.set_skin(skin_id)
    layer.paint(painter, spider, SP.SpiderState(heading=heading, dim=1.0),
                unit=unit, origin_px=(210, 180))
    painter.end()
    return image


def ink(image: QImage) -> int:
    return sum(1 for y in range(image.height()) for x in range(image.width())
               if image.pixelColor(x, y).alpha() > 8)


def diff(a: QImage, b: QImage) -> int:
    n = 0
    for y in range(a.height()):
        for x in range(a.width()):
            if a.pixelColor(x, y) != b.pixelColor(x, y):
                n += 1
    return n


def geometry_of(skin_id: str) -> tuple:
    """取一只蜘蛛在指定皮肤下的**全部几何指纹**（与渲染无关）。"""
    layer = SP.SpiderPainter()
    layer.set_skin(skin_id)
    spider = CS.Spider(size=1.0)
    spider.origin_px = (0.0, 0.0)
    layer.setup((0.0, 0.0), 1.0, 0.0)
    legs = tuple((round(L.reach, 6), round(L.l1, 6), round(L.l2, 6),
                  round(L.hip, 6), round(L.hip_y, 6), round(L.ang, 6))
                 for L in spider.legs)
    before = layer.hit_test_px(20.0, 0.0, spider, 1.0)
    return (legs, before, round(CS.THORAX[0], 6), round(CS.THORAX[2], 6),
            round(CS.HEAD_TRI_LEN, 6), round(CS.BASE_SCALE, 6),
            round(SP.SpiderPainter.unit_for_width(360.0), 9))


print("=" * 68)
print("蜘蛛皮肤 · 回归验证")
print("=" * 68)

# ------------------------------------------------------------------ A 注册表
print("\n[A] 皮肤注册表")
ids = [sid for sid, _ in SP.skin_options()]
check("四套皮肤都注册了", len(ids) == 4, "→ %s" % (ids,))
check("★ 默认皮肤是白跳蛛（用户口径）",
      SP.DEFAULT_SKIN == "white_jump_spider" and SP.DEFAULT_SKIN in SP.SKIN_SPECS,
      "→ %s" % SP.DEFAULT_SKIN)
check("原皮仍在（不然没法退回去）", "original" in SP.SKIN_SPECS)
check("每套皮肤都有中文名",
      all(SP.SKIN_SPECS[sid].name.strip() for sid in ids))
bad_hex = [sid for sid in ids
           for field in ("leg", "leg_hi", "leg_outline", "joint")
           if not QColor(getattr(SP.SKIN_SPECS[sid], field)).isValid()]
check("所有腿色都是合法颜色", not bad_hex, "→ %s" % (bad_hex or "全部合法"))
check("skin_options 与 SKIN_ORDER 一致",
      tuple(ids) == tuple(SP.SKIN_ORDER), "→ %s" % (SP.SKIN_ORDER,))

# ------------------------------------------------------------------ B 素材
print("\n[B] 素材与契约（打包漏素材是这里唯一能挡住的地方）")
CONTRACT = {"body": (256, 156), "head": (160, 170)}
missing = []
for sid in ids:
    spec = SP.SKIN_SPECS[sid]
    if spec.skin_id == "original":
        continue
    for kind, expect in CONTRACT.items():
        name = spec.body_file if kind == "body" else spec.head_file
        path = os.path.join(SP._skin_dir(), name)
        if not os.path.exists(path):
            missing.append("%s/%s 文件不存在" % (sid, kind))
            continue
        image = QImage(path)
        if (image.width(), image.height()) != expect:
            missing.append("%s/%s 尺寸 %dx%d ≠ %dx%d"
                           % (sid, kind, image.width(), image.height(), *expect))
        if not image.hasAlphaChannel():
            missing.append("%s/%s 没有 alpha 通道" % (sid, kind))
check("三套图皮的素材都在且符合标准框", not missing,
      "→ %s" % ("、".join(missing) if missing else "3 套 × 2 件，全部合规"))
check("皮肤目录能从 resource_path 解析到", os.path.isdir(SP._skin_dir()),
      "→ %s" % SP._skin_dir())

# ------------------------------------------------------------------ C 渲染
print("\n[C] 四套皮肤都画得出来，且互相看得出区别")
images = {sid: rendered(sid) for sid in ids}
for sid in ids:
    count = ink(images[sid])
    check("%s 画出了东西" % SP.SKIN_SPECS[sid].name, count > 400,
          "→ 墨迹 %d 像素" % count)

pairs_differ = True
worst = None
for i, a in enumerate(ids):
    for b in ids[i + 1:]:
        d = diff(images[a], images[b])
        if d < 300:
            pairs_differ = False
            worst = (a, b, d)
check("任意两套皮肤的画面对得上不上（没有「换了等于没换」）", pairs_differ,
      "→ %s" % (worst or "6 组两两都有明显差异"))

# 四套皮肤在同一姿态下，腿的像素应该落在大致同一片区域 —— 这是
# 「严格复用同一局部坐标框」的直接体现（换皮不改大小、不改位置）。
boxes = {}
for sid in ids:
    image = images[sid]
    xs, ys = [], []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 8:
                xs.append(x)
                ys.append(y)
    boxes[sid] = (min(xs), min(ys), max(xs), max(ys))
spread_w = max(b[2] - b[0] for b in boxes.values())
spread_h = max(b[3] - b[1] for b in boxes.values())
narrow_w = min(b[2] - b[0] for b in boxes.values())
narrow_h = min(b[3] - b[1] for b in boxes.values())
# 图皮不铺柔光，包围盒本来就比原皮小一圈；这里只卡「不许差出一个量级」
check("四套皮肤的占位尺寸在同一档（没有某套明显偏大/偏小）",
      narrow_w > spread_w * 0.55 and narrow_h > spread_h * 0.55,
      "→ 宽 %d~%d，高 %d~%d" % (narrow_w, spread_w, narrow_h, spread_h))

# ------------------------------------------------------------------ D 几何不变
print("\n[D] ★ 换皮不许改几何（腿长/腿根/命中区/缩放基准）")
base = geometry_of("original")
for sid in ids[1:]:
    check("%s 的几何与原皮逐项一致" % SP.SKIN_SPECS[sid].name,
          geometry_of(sid) == base,
          "→ 腿长/髋位/命中判定/THORAX/HEAD_TRI/unit 全同")

# ------------------------------------------------------------------ E 切换
print("\n[E] 切换行为")
layer = SP.SpiderPainter()
check("画笔初始就是默认皮肤", layer.skin_id == SP.DEFAULT_SKIN,
      "→ %s" % layer.skin_id)
try:
    layer.set_skin("nope_spider")
    check("未知皮肤会报错", False, "→ 居然没报错")
except ValueError:
    check("未知皮肤会报错", True, "→ ValueError")
layer.set_skin("MILK_SPIDER")           # 大小写与空格要能容错
check("皮肤 ID 大小写不敏感", layer.skin_id == "milk_spider",
      "→ 输入 'MILK_SPIDER' 得到 %s" % layer.skin_id)
layer.set_skin("original")
check("切回原皮能生效", layer.skin_id == "original" and layer.skin_name.startswith("原皮"),
      "→ %s" % layer.skin_name)

# 素材缺失必须回退原皮身体，而不是留一只没身体的蜘蛛
saved = SP.SKIN_SPECS["white_jump_spider"]
SP.SKIN_SPECS["white_jump_spider"] = SP.SkinSpec(
    "white_jump_spider", "白跳蛛", "不存在的_身体.png", "不存在的_头.png",
    "#F2F4F7", "#FFFFFF", "#7F8790", "#8C959E")
try:
    broken = rendered("white_jump_spider")
    check("素材缺失时回退成几何身体（不会只剩腿）", ink(broken) > 400,
          "→ 墨迹 %d 像素" % ink(broken))
finally:
    SP.SKIN_SPECS["white_jump_spider"] = saved

# ------------------------------------------------------------------ F 持久化
print("\n[F] 设置落盘（启动台与桌宠共用这一个键）")
from settings_store import DEFAULTS, Settings                        # noqa: E402

check("settings 默认皮肤与画笔默认一致",
      DEFAULTS["skin"] == SP.DEFAULT_SKIN,
      "→ settings=%s / painter=%s" % (DEFAULTS["skin"], SP.DEFAULT_SKIN))

tmp = tempfile.mkdtemp(prefix="skin_settings_")
store = Settings(path=os.path.join(tmp, "settings.json"))
store.set("skin", "milk_spider")
again = Settings(path=os.path.join(tmp, "settings.json"))
check("皮肤能存进 JSON 并读回来", again.get("skin") == "milk_spider",
      "→ %s" % again.get("skin"))
store.set("skin", "皮卡丘")
check("非法皮肤被挡回默认", store.get("skin") == SP.DEFAULT_SKIN,
      "→ 输入 '皮卡丘' 得到 %s" % store.get("skin"))

# ------------------------------------------------------------------ G 缩略图缓存
# 2026-10-18 的真实 bug：用户换了蜘蛛的头/身体贴图，设置里「选皮肤」的预览
# 还是旧蜘蛛 —— 因为缩略图文件名写死成 `v5_<skin>.png`，文件在就一直复用。
# 现在文件名带素材指纹，这里守住三件事：指纹对内容敏感、旧图会被清掉、
# 真画出来的四个文件都存在。
print("\n[G] 换皮肤预览图（缩略图）跟着素材一起失效")
import launcher_qml as LQ                                            # noqa: E402

thumb_tmp = tempfile.mkdtemp(prefix="skin_thumbs_")
fake_body = os.path.join(thumb_tmp, "fake_body.png")

with open(fake_body, "wb") as handle:
    handle.write(b"A" * 100)

real_asset_path = SP.skin_asset_path


def _fake_asset_path(filename):
    """把白跳蛛的身体素材指到临时文件，用来模拟「用户换了图」。"""
    if filename == "white_jump_spider_body.png":
        return fake_body
    return real_asset_path(filename)


SP.skin_asset_path = _fake_asset_path
sig_first = LQ._skin_thumb_signature("white_jump_spider")
sig_again = LQ._skin_thumb_signature("white_jump_spider")
with open(fake_body, "wb") as handle:                # 换一张（字节数也不同）
    handle.write(b"B" * 260)
sig_after = LQ._skin_thumb_signature("white_jump_spider")
SP.skin_asset_path = real_asset_path

check("同一素材的指纹稳定", sig_first == sig_again, "→ %s" % sig_first)
check("素材一换指纹就变", sig_first != sig_after,
      "→ 换图前 %s / 换图后 %s" % (sig_first, sig_after))
check("四套皮肤指纹互不相同",
      len({LQ._skin_thumb_signature(sid) for sid in SP.SKIN_ORDER}) == len(SP.SKIN_ORDER))

# 旧命名（v5_xxx.png / xxx.png）要被清掉，别人的文件不碰
keep_name = "t1234abcd_white_jump_spider.png"
for name in (keep_name, "v5_white_jump_spider.png", "white_jump_spider.png",
             "v5_milk_spider.png", "笔记.txt"):
    with open(os.path.join(thumb_tmp, name), "wb") as handle:
        handle.write(b"x")
LQ._drop_stale_thumbs(thumb_tmp, "white_jump_spider", keep=keep_name)
left = set(os.listdir(thumb_tmp))
check("旧版缩略图被清理",
      "v5_white_jump_spider.png" not in left and "white_jump_spider.png" not in left,
      "→ 目录 %s" % sorted(left))
check("当前这一版保留", keep_name in left)
check("别的皮肤与无关文件不碰",
      "v5_milk_spider.png" in left and "笔记.txt" in left)

# 真画一遍：四个文件都要落盘，且文件名带指纹
render_tmp = tempfile.mkdtemp(prefix="skin_render_")
original_thumb_dir = LQ._thumb_dir
LQ._thumb_dir = lambda: render_tmp


class _NoBridge:
    """`_skin_options` 只用到 `self._skins`，不需要真的把启动台拉起来。"""
    _skins = None


thumbs = LQ.LauncherBridge._skin_options(_NoBridge())
LQ._thumb_dir = original_thumb_dir

from PySide6.QtCore import QUrl                                      # noqa: E402

paths = [QUrl(item["thumb"]).toLocalFile() for item in thumbs]
check("四套皮肤都给了预览图", len(thumbs) == len(SP.SKIN_ORDER), "→ %d" % len(thumbs))
check("预览图文件真的存在", all(os.path.isfile(p) for p in paths),
      "→ %s" % [os.path.basename(p) for p in paths])
check("文件名带素材指纹（不会撞旧图）",
      all(os.path.basename(p).startswith("t") and "_" in os.path.basename(p)
          for p in paths),
      "→ %s" % os.path.basename(paths[0]) if paths else "")
check("预览图不是空白",
      all(QImage(p).width() == 170 and ink(QImage(p)) > 0 for p in paths)
      if paths else False)

print("\n" + "=" * 68)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
for name in FAIL:
    print("  FAILED:", name)
raise SystemExit(1 if FAIL else 0)
