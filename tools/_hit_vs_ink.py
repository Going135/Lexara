"""量「命中几何框」与「素材可见墨迹」差多少（两个方向 + 面积）。

目的：判断 `_in_thorax` 的判定框是否明显大于白蛛素材真正画出来的肚子，
     即「点到空白却判成点身体」有多宽。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import crawler_spider as CS  # noqa: E402
from pet_window import PetWindow  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def main() -> None:
    pet = PetWindow(None, None, sprite_w=360.0)
    pet.effect = None
    pet.resize(*pet._window_size())
    pet._timer.stop()
    pet.bubble.hide_now()
    scr = pet._screen_rect()
    pet.center = scr.center()
    pet.show()
    for _ in range(40):
        pet._tick()
        pet.repaint()

    sp = pet.spider
    sp.clear_targets()
    sp.leg_retract = 0.0
    sp.retract_fold = 0.0
    sp.body_fold = 0.0
    sp.lean = 0.0
    sp.body_sway = 0.0
    for _ in range(60):
        pet._tick()

    unit = pet.unit
    print("unit        = %.4f px/单位" % unit)
    print("body_scale  = %.3f" % sp.body_scale)
    print("THORAX      = %s" % (CS.THORAX,))
    print("THORAX_SCALE= %.3f" % CS.THORAX_SCALE)
    print("HIT_PAD     = %s" % (sp.HIT_PAD,))

    # ---- 几何：沿体轴的判定后缘（局部单位） ----
    ox, oy = pet._canvas_origin()
    fx, fy = sp.forward()
    print("forward     = (%.3f, %.3f)" % (fx, fy))

    def axis_pt(t_px):
        return QPointF(ox + fx * t_px, oy + fy * t_px)

    def hit_at(t_px):
        return sp.hit_test(pet._to_local(axis_pt(t_px).x(), axis_pt(t_px).y()))

    back_hit = 0
    t = 0
    while t > -400:
        t -= 1
        if hit_at(t) not in ("head", "body"):
            break
        back_hit = t
    front_hit = 0
    t = 0
    while t < 400:
        t += 1
        if hit_at(t) not in ("head", "body"):
            break
        front_hit = t

    # ---- 像素：素材真正画出来的墨迹 ----
    img = QImage(pet.width(), pet.height(), QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    pet.render(img)
    pet.render(img)

    def ink(t_px):
        x, y = ox + fx * t_px, oy + fy * t_px
        if not (0 <= int(x) < img.width() and 0 <= int(y) < img.height()):
            return False
        return img.pixelColor(int(x), int(y)).alpha() > 60

    back_ink = 0
    t = 0
    while t > -400:
        t -= 1
        if not ink(t):
            break
        back_ink = t
    front_ink = 0
    t = 0
    while t < 400:
        t += 1
        if not ink(t):
            break
        front_ink = t

    print()
    print("沿体轴（窗口像素，以身体中心为 0，+ 朝头）：")
    print("  可点前缘 %+5d   |> 前段差 %+d px" % (front_hit, front_hit - front_ink))
    print("  墨迹前缘 %+5d   |" % front_ink)
    print("  墨迹后缘 %+5d   |  后段差 %+d px" % (back_ink, back_hit - back_ink))
    print("  可点后缘 %+5d   <|" % back_hit)
    print("  可点体长 %d px · 可见体长 %d px · 外扩 %.0f%%"
          % (front_hit - back_hit, front_ink - back_ink,
             100.0 * ((front_hit - back_hit) / max(1.0, front_ink - back_ink) - 1.0)))

    # ---- 面积：整个命中框 vs 整个不透明墨迹 ----
    from PySide6.QtCore import QRectF

    rect = QRectF(CS.THORAX[0] * unit * CS.THORAX_SCALE,
                  CS.THORAX[1] * unit * CS.THORAX_SCALE,
                  CS.THORAX[2] * unit * CS.THORAX_SCALE,
                  CS.THORAX[3] * unit * CS.THORAX_SCALE)
    draw = pet.painter._body_draw_rect(rect)
    print()
    print("body 贴图绘制框（窗口像素）= (%.1f, %.1f, %.1f x %.1f)"
          % (draw.x(), draw.y(), draw.width(), draw.height()))

    # 贴图自身 alpha 的 bbox 占整图的比例
    pm = None
    for name in ("body_pixmap", "body", "_body_pm"):
        cand = getattr(pet.painter, name, None)
        if cand is not None and hasattr(cand, "toImage"):
            pm = cand
            break
    if pm is None:
        skin = pet.painter.__dict__.get("skin") or {}
        print("  （找不到 body 贴图，跳过 padding 测量；painter 字段：%s）"
              % ", ".join(sorted(pet.painter.__dict__)))
    else:
        bimg = pm.toImage()
        xs, ys = [], []
        for y in range(bimg.height()):
            for x in range(bimg.width()):
                if bimg.pixelColor(x, y).alpha() > 60:
                    xs.append(x)
                    ys.append(y)
        if xs:
            bw, bh = bimg.width(), bimg.height()
            print("  body 贴图 %dx%d · 不透明 bbox x[%d..%d] y[%d..%d] → 占宽 %.0f%% 占高 %.0f%%"
                  % (bw, bh, min(xs), max(xs), min(ys), max(ys),
                     100.0 * (max(xs) - min(xs)) / bw,
                     100.0 * (max(ys) - min(ys)) / bh))

    pet.close()


if __name__ == "__main__":
    main()
