# -*- coding: utf-8 -*-
"""运动可视化对照图 + 像素级朝向断言（任务书 §3 / §10）。

`test/test_locomotion.py` 守的是**模型几何**（脚钉住、骨长恒定、头前导）。
这里守的是**画面上真的如此**：走的是生产 `PetWindow` 的 `paintEvent`
（`pet.render()`），所以皮肤、形变矩阵、朝向、侧摆全都和真机同一条路径 ——
万一渲染层把身体翻了个面（`Tf.flip` / 负缩放 / 头腹画反位），模型断言看不出来，
这一层能看出来。

两张图：

    ① 行走 8 方向：每个方向真走一段，掐 4 帧。断言「本体真的平移了」
       和「实测朝向跟得上前进方向」（头领路，不是屁股领路）。
    ② 收腿剪影 8 朝向：把腿收到全折叠再渲染，只剩头+胸腹+腹部。
       沿**前向轴**做墨迹投影，质心必须落在体心**后方**（腹部是最大的一块，
       它应当在后面拖着）。如果渲染层把前后画反，这个符号就会翻。
    ③ 跳跃四段（§9.2C / §9.3）：起点 → 蓄力 → 空中 → 落地 → 恢复，
       五张帧 + 一张把腾空各帧按位移叠在一起的抛物线合成图。
    ④ 待机 / 慢走 / 快走 / 原地转向（§9.3 要求的四种基本状态）：
       慢走与快走用固定速度平移本体来驱动，断言步频与步幅随速度放大。

运行：  python tools/locomotion_sheet.py
输出：  dist/shape/locomotion_walk.png
        dist/shape/locomotion_orient.png
        dist/shape/locomotion_jump.png
        dist/shape/locomotion_speed.png
"""

from __future__ import annotations

import math
import os
import random
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

# 故意不设 offscreen：那个平台枚举不到中文字族，标签会变豆腐块，
# 而且渲染出来的像素不可信（见 test_word_box_fit.py 同段说明）。
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt          # noqa: E402
from PySide6.QtGui import (QColor, QPolygonF, QFont, QImage,     # noqa: E402
                           QPainter, QPen)
from PySide6.QtWidgets import QApplication                      # noqa: E402

import anim                                                     # noqa: E402
import crawler_spider as CS                                     # noqa: E402
import pet_window as PW                                         # noqa: E402
import locomotion                                               # noqa: E402
from pet_window import PetWindow                                # noqa: E402

OUT = os.path.join(BASE, "dist", "shape")
os.makedirs(OUT, exist_ok=True)

#: 迈步时长是随机的（`crawler_spider` 在 `STEP_DUR` 区间里 `random.random()`），
#: 所以不夹种子的话每次跑出来的步相位都不同：④ 的步频/步幅会漂半拍到一拍，
#: 断言余量就得按最差情况留。任务书 §9.3 要的是「确定性时间步」，这里把随机源
#: 也一起定死 —— 图可比、数可比，改坏了才会真的红。
random.seed(20261018)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %-58s %s" % ("ok" if ok else "FAIL", name, detail))


class Clock:
    """假时钟：主循环读挂钟，要能把动画冻在任意进度。"""

    def __init__(self):
        self.t = 1_000_000.0

    def monotonic(self):
        return self.t

    def strftime(self, fmt):
        import time as real
        return real.strftime(fmt)


clock = Clock()
PW.time = clock

app = QApplication.instance() or QApplication(sys.argv)

BG = QColor(11, 16, 23)
INK = QColor(150, 175, 190)
TITLE = QColor(46, 230, 214)
MARK = QColor(232, 92, 92)

ARROW = {0: "→", 45: "↘", 90: "↓", 135: "↙", 180: "←",
         225: "↖", 270: "↑", 315: "↗"}


def font(px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSize(px)
    f.setBold(bold)
    return f


pet = PetWindow(None, None, sprite_w=360.0)
pet.effect = None
pet.resize(*pet._window_size())
pet._timer.stop()
pet.bubble.hide_now()


def run(frames: int) -> None:
    for _ in range(frames):
        clock.t += 1.0 / 60.0
        pet._tick()
    app.processEvents()


def settle(frames: int = 150) -> None:
    """空跑到站姿稳定（新建的腿还缩在体心，不跑够帧数会挤成一团）。"""
    pet.effect = None
    run(frames)
    pet.spider.lean = 0.0
    pet.spider.body_sway = 0.0
    pet.spider.clear_targets()


screen = pet._screen_rect()
home = QPoint(int(screen.center().x()), int(screen.center().y()))


def park() -> None:
    """把本体停回原位，并**结束上一段没跑完的位移**。

    上一段 `_travel` 不清的话，下一帧它会把 `center` 直接写成自己那一段的终点
    （`u>=1` 分支），于是本体的落点根本不是我设的那个 home —— 第一次跑对照图
    就被这个坑骗了：八个方向量出来的朝向整齐地偏 66°，看着像「头不领路」，
    其实是每一行的起点被上一段的终点劫持了。清掉再摆 home，才是干净的独行。
    """
    pet._travel = None
    pet._travel_done = None
    pet.effect = None
    pet.center = QPoint(home)
    settle(40)


def render_window() -> QImage:
    """按生产 paintEvent 渲一张窗口图。

    第一张会命中「尺寸没变 → 复用缓存层」的旧图，所以连渲两次取后者 ——
    否则改完朝向/收腿后的第一帧可能还是上一状态的样子（探针踩过）。
    """
    image = QImage(pet.width(), pet.height(), QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    pet.render(image)
    pet.render(image)
    return image


def forward_projection(image: QImage) -> float:
    """剪影墨迹在**前向轴**上的质心（窗口像素；正 = 头那一侧）。

    只在收腿状态下用：那时画面里只剩头 + 胸腹 + 腹部，腹部是最大的一块，
    正常应该把质心拖到体心后方（负值）。腿伸着的时候八条腿的墨迹占大头，
    而且腿是围绕体心分布的，投影几乎没有信息量（实测正负只差 4px）。
    """
    fx, fy = pet.spider.forward()
    ox, oy = pet._canvas_origin()
    transform = pet._scene_transform()
    num = den = 0.0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            alpha = image.pixelColor(x, y).alpha()
            if alpha <= 40:
                continue
            px, py = (transform.map(QPointF(x, y)).toTuple()
                      if transform is not None else (float(x), float(y)))
            t = (px - ox) * fx + (py - oy) * fy
            num += alpha * t
            den += alpha
    return num / den if den else 0.0


# ------------------------------------------------------------------ ① 行走
pet.center = QPoint(home)
settle()

CELL_W, CELL_H = 300, 230
SLICES = (0.15, 0.35, 0.55, 0.85)
walk_rows = []          # (标签, [QImage...], 实测朝向, 位移像素, 偏差)

print("\n[①] 八个方向各走一段：本体平移 + 头领路")
for deg in (0, 45, 90, 135, 180, 225, 270, 315):
    park()
    pet._movement_choice = None
    rad = math.radians(deg)
    target = QPoint(int(home.x() + 210 * math.cos(rad)),
                    int(home.y() + 210 * math.sin(rad)))
    start_center = QPoint(pet.center)
    pet.travel_to(target, force_jump=False)
    duration = pet._travel[3] if pet._travel else 0.0
    frames_needed = [int(duration * 60 * s) for s in SLICES]
    frames = []
    previous = 0
    for need in frames_needed:
        run(max(1, need - previous))
        previous = need
        frames.append(render_window())
    moved = math.hypot(pet.center.x() - start_center.x(),
                       pet.center.y() - start_center.y())
    heading = math.degrees(pet.spider.heading) % 360.0
    # 朝向与前进方向的夹角（取劣角）
    dev = abs((heading - deg + 180.0) % 360.0 - 180.0)
    walk_rows.append(("%.0f° %s" % (deg, ARROW[deg]), frames, heading, moved, dev))
    check("方向 %.0f°%s：本体真的平移了（>=20px）" % (deg, ARROW[deg]),
          moved >= 20.0, "→ %.0fpx / 目标 210px" % moved)
    check("方向 %.0f°%s：头朝着前进方向（偏差 <=35°）" % (deg, ARROW[deg]),
          dev <= 35.0, "→ 实测朝向 %.1f°，偏差 %.1f°" % (heading, dev))

sheet = QImage(CELL_W * 4 + 90, (CELL_H + 34) * len(walk_rows) + 70,
               QImage.Format_ARGB32)
sheet.fill(BG)
painter = QPainter(sheet)
painter.setPen(QPen(TITLE))
painter.setFont(font(12, True))
painter.drawText(QRectF(24, 16, sheet.width() - 48, 30), Qt.AlignLeft,
                 "① 行走八方向（生产 paintEvent · 每行四个进度：%s）"
                 % " / ".join("%.0f%%" % (s * 100) for s in SLICES))
y = 64
for label, frames, heading, moved, dev in walk_rows:
    painter.setPen(QPen(INK))
    painter.setFont(font(9, True))
    painter.drawText(QRectF(8, y + CELL_H / 2 - 24, 84, 60), Qt.AlignLeft,
                     "%s\nheading %.0f°\nmove %.0fpx" % (label, heading, moved))
    x = 90
    for image in frames:
        painter.fillRect(QRectF(x, y, CELL_W, CELL_H), BG)
        scale = min(CELL_W / image.width(), CELL_H / image.height())
        w, h = image.width() * scale, image.height() * scale
        painter.drawImage(QRectF(x + (CELL_W - w) / 2, y + (CELL_H - h) / 2, w, h),
                          image)
        painter.setPen(QPen(MARK, 1.0, Qt.DashLine))
        painter.drawLine(QPointF(x + CELL_W / 2, y),
                         QPointF(x + CELL_W / 2, y + CELL_H))
        x += CELL_W
    y += CELL_H + 34
painter.end()
walk_path = os.path.join(OUT, "locomotion_walk.png")
sheet.save(walk_path)

# ------------------------------------------------------------------ ② 剪影
print("\n[②] 收腿剪影：墨迹质心必须在体心后方（腹部拖着，头在前）")

park()
pet.folded = True
pet._leg_from = 1.0
pet.effect = None
run(40)                                  # 让 retract 插值真的到位

# ★ 比剪影之前必须真的「站定」：走路起伏/压低下沉是**屏幕竖直**方向的偏移，
#   它沿各朝向的前向轴投影分量不同（0°/180° 投到 0，90°/270° 投满），
#   于是「八朝向质心一致」量的就不再是图形本身，而是采样那一刻还剩多少起伏。
#   折叠只影响绘制，模型仍在收尾步 → 等到没有腿在迈、bob 归零再采。
for _ in range(600):
    if (not any(L.stepping for L in pet.spider.legs)
            and abs(pet.spider.body_bob) < 0.02):
        break
    run(1)
pet.spider.lean = 0.0
pet.spider.body_sway = 0.0

centroids = []
orient_rows = []
for deg in (0, 45, 90, 135, 180, 225, 270, 315):
    pet.spider.heading = math.radians(deg)
    image = render_window()
    value = forward_projection(image)
    centroids.append(value)
    orient_rows.append(("%d°" % deg, image, value))
    check("朝向 %.0f°：质心在体心后方" % deg, value < 0.0,
          "→ %.1fpx" % value)

check("八朝向质心一致（体坐标系里图形没被翻面）",
      max(centroids) - min(centroids) <= 4.0,
      "→ 极差 %.2fpx" % (max(centroids) - min(centroids)))
check("质心离体心够远（>=3px，不然符号没有意义）",
      min(abs(v) for v in centroids) >= 3.0,
      "→ 最小 %.1fpx" % min(abs(v) for v in centroids))

sheet = QImage(300 * 4 + 40, 250 * 2 + 90, QImage.Format_ARGB32)
sheet.fill(BG)
painter = QPainter(sheet)
painter.setPen(QPen(TITLE))
painter.setFont(font(12, True))
painter.drawText(QRectF(24, 16, sheet.width() - 48, 30), Qt.AlignLeft,
                 "② 收腿剪影 · 红竖线 = 体心 · 质心应在右侧= 头的对侧")
index = 0
for label, image, value in orient_rows:
    x = 40 + (index % 4) * 300
    y = 74 + (index // 4) * 250
    painter.setPen(QPen(INK))
    painter.setFont(font(9, True))
    painter.drawText(QRectF(x, y - 18, 290, 16), Qt.AlignLeft,
                     "%s  centroid %.1fpx" % (label, value))
    scale = min(300.0 / image.width(), 250.0 / image.height())
    w, h = image.width() * scale, image.height() * scale
    painter.drawImage(QRectF(x + (300 - w) / 2, y, w, h), image)
    painter.setPen(QPen(MARK, 1.0, Qt.DashLine))
    painter.drawLine(QPointF(x + 150, y), QPointF(x + 150, y + 250))
    index += 1
painter.end()
orient_path = os.path.join(OUT, "locomotion_orient.png")
sheet.save(orient_path)

pet.folded = False
pet._leg_from = 0.0
pet.effect = None

# --------------------------------------------------------------- 排版小工具
CAP_H, GAP, LABEL_W = 22, 10, 124        # 每格下面那行小字 / 格间距 / 行标签宽
GHOST_BODY = 0.13                        # 合成图里每一帧的缩放比


def build_sheet(path, title, rows, cell_w=300, cell_h=215):
    """rows = [(行标签, [(QImage, 小字, 占几格), ...]), ...] → 一张对照图。

    ①② 那两段是各自手写的网格（先有的它们），③④ 起用这个公共排版。
    `span>1` 的格子给合成图用，宽度按 `span*cell_w + (span-1)*GAP` 算。
    """
    widest = max((sum(cell_w * span + GAP * (span - 1)
                      for _, _, span in cells) for _, cells in rows), default=0)
    sheet = QImage(LABEL_W + widest + GAP,
                   58 + len(rows) * (cell_h + CAP_H + 26) + 14,
                   QImage.Format_ARGB32)
    sheet.fill(BG)
    painter = QPainter(sheet)
    painter.setPen(QPen(TITLE))
    painter.setFont(font(12, True))
    painter.drawText(QRectF(24, 14, sheet.width() - 48, 30), Qt.AlignLeft, title)
    y = 58
    for row_label, cells in rows:
        painter.setPen(QPen(INK))
        painter.setFont(font(9, True))
        painter.drawText(QRectF(8, y + 6, LABEL_W - 16, cell_h),
                         Qt.AlignLeft | Qt.TextWordWrap, row_label)
        x = LABEL_W
        for image, caption, span in cells:
            box_w = cell_w * span + GAP * (span - 1)
            scale = min(box_w / image.width(), cell_h / image.height())
            w, h = image.width() * scale, image.height() * scale
            painter.drawImage(QRectF(x + (box_w - w) / 2, y + (cell_h - h) / 2,
                                     w, h), image)
            painter.setPen(QPen(INK))
            painter.setFont(font(8))
            painter.drawText(QRectF(x, y + cell_h + 3, box_w, CAP_H),
                             Qt.AlignLeft, caption)
            x += box_w + GAP
        y += cell_h + CAP_H + 26
    painter.end()
    sheet.save(path)
    return path


def ghost_cell(width, height, start, curve, shots, body=GHOST_BODY,
               opacity=0.34, pad=24.0):
    """把腾空各帧按「相对起点的位移」叠进一张图 —— 抛物线肉眼可读。

    每张窗口图的身体都在**图心**（`_canvas_origin` = 窗口中心），所以把图心
    平移到轨迹点上就行。位移比例不再写死：先量出整条轨迹的包围盒，再夹到
    「盒子 + 一帧身子」刚好落在格子里 —— 第一版把起点钉在图心，结果 609px
    的跳距有三分之二被推出画面，看上去只剩「一小撮蜘蛛加一条直线」。
    """
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(BG)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    if not curve:
        painter.end()
        return image
    rel = [(float(p.x() - start.x()), float(p.y() - start.y())) for p in curve]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    body_px = max(shot.height() for _, shot in shots) * body if shots else 0.0
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    k = min((width - 2.0 * pad - body_px) / max(span_x, 1.0),
            (height - 2.0 * pad - body_px) / max(span_y, 1.0))
    mid_x = (max(xs) + min(xs)) / 2.0
    mid_y = (max(ys) + min(ys)) / 2.0
    cx, cy = width / 2.0, height / 2.0

    def place(point):
        return QPointF(cx + (point[0] - mid_x) * k, cy + (point[1] - mid_y) * k)

    if len(rel) > 1:
        painter.setPen(QPen(MARK, 1.0, Qt.DashLine))
        painter.drawPolyline(QPolygonF([place(p) for p in rel]))
    for root, shot in shots:
        center = place((float(root.x() - start.x()), float(root.y() - start.y())))
        w, h = shot.width() * body, shot.height() * body
        painter.setOpacity(opacity)
        painter.drawImage(QRectF(center.x() - w / 2, center.y() - h / 2, w, h),
                          shot)
    painter.setOpacity(1.0)
    painter.end()
    return image, k


def ink_fingerprint(image):
    """墨迹总量 + 质心（窗口像素）。待机那三帧用它判断「画面到底动没动」。"""
    total = num_x = num_y = 0.0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            alpha = image.pixelColor(x, y).alpha()
            if alpha > 40:
                total += alpha
                num_x += alpha * x
                num_y += alpha * y
    if total <= 0:
        return (0.0, 0.0, 0.0)
    return (total, num_x / total, num_y / total)


def worst_tip_ratio(spider) -> float:
    """最 stretched 的一条腿：脚尖到髋部 ÷（骨长 × 上限系数），>1 就是腿被拉长。"""
    return max(math.hypot(leg.tip[0] - leg.hip_pos[0], leg.tip[1] - leg.hip_pos[1])
               / (leg.full * CS.REACH_LIMIT_FRAC)
               for leg in spider.legs if not leg.palp)


def step() -> None:
    """推一帧，不过 `processEvents`。

    `play()` 里的 `wake()` 会把真定时器重新起来；事件循环一转它就按挂钟补一堆
    dt≈0 的空帧。那些空帧改不了状态（阻尼量是 dt 的一次函数），但会把「这一帧
    身体动没动」的账搅浑，所以新加的几段自己推、自己停表。
    """
    clock.t += 1.0 / 60.0
    pet._timer.stop()
    pet._tick()


legs_by_index = {leg.index: leg for leg in pet.spider.legs}
SLICE4 = (0.15, 0.40, 0.65, 0.90)

# ------------------------------------------------------------------ ③ 跳跃
print("\n[③] 远距离跳：起点 → 蓄力 → 空中 → 落地 → 恢复（§9.2C）")

park()
bone_before = {index: (leg.l1, leg.l2) for index, leg in legs_by_index.items()}
threshold = locomotion.walk_jump_threshold(pet.spider, pet.unit)
rad = math.radians(190.0)
jump_target = QPoint(int(round(home.x() + 2.35 * threshold * math.cos(rad))),
                     int(round(home.y() + 2.35 * threshold * math.sin(rad))))
jump_start = QPoint(pet.center)
pet.travel_to(jump_target)              # 不指定 force：让阈值自己判走还是跳
snap = pet._travel
goal = QPoint(snap[1]) if snap else QPoint(jump_start)
chord_x = float(goal.x() - jump_start.x())
jump_distance = math.hypot(chord_x, goal.y() - jump_start.y())
check("远距离 %.0fpx（阈值 %.0fpx）自动判成跳" % (jump_distance, threshold),
      bool(snap) and snap[4],
      "→ 时长 %.2fs（基准 %.2fs）" % (snap[3] if snap else 0.0,
                                    locomotion.JUMP_BASE_SECONDS))
check("跳跃时长可测且随距离放大（1.0×~1.6× 基准）",
      snap is not None and locomotion.JUMP_BASE_SECONDS - 1e-6 <= snap[3]
      <= 1.6 * locomotion.JUMP_BASE_SECONDS + 1e-6,
      "→ %.3fs" % (snap[3] if snap else 0.0))

shot_start = render_window()
mode_seq = [pet.mover.movement_mode]
air_curve, air_shots = [], []
prepare_last = land_shot = None
crouch_max = land_impulse = 0.0
prepare_root_moved = peak_lift = progress_regress = 0.0
air_step_onsets = 0
last_progress = 0.0
next_sample = 0.15
frames = 0
guard = int((snap[3] if snap else 1.0) * 60) + 400
while frames < guard and pet.mover.moving:
    frames += 1
    was_stepping = {i for i, leg in legs_by_index.items()
                    if leg.stepping and not leg.palp}
    step()
    mode = pet.mover.movement_mode
    if mode != mode_seq[-1]:
        mode_seq.append(mode)
    root = QPoint(pet.center)
    now_stepping = {i for i, leg in legs_by_index.items()
                    if leg.stepping and not leg.palp}
    if mode == locomotion.JUMP_PREPARE:
        prepare_root_moved = max(prepare_root_moved,
                                 math.hypot(root.x() - jump_start.x(),
                                            root.y() - jump_start.y()))
        if pet.spider.crouch > crouch_max + 0.03:
            crouch_max = pet.spider.crouch
            prepare_last = render_window()
    elif mode == locomotion.JUMP_AIRBORNE:
        air_step_onsets += len(now_stepping - was_stepping)
        air_curve.append(root)
        t = (root.x() - jump_start.x()) / chord_x if abs(chord_x) > 1 else 0.0
        progress_regress = max(progress_regress, last_progress - t)
        last_progress = max(last_progress, t)
        lift = (jump_start.y() + t * (goal.y() - jump_start.y())) - root.y()
        if t >= next_sample and len(air_shots) < 5:
            next_sample += 0.20
            air_shots.append((QPoint(root), render_window(), lift,
                              worst_tip_ratio(pet.spider)))
        peak_lift = max(peak_lift, lift)
    elif mode == locomotion.LAND and land_shot is None:
        land_impulse = pet.spider.landing_compression
        land_shot = render_window()

land_root = QPoint(pet.center)
worst_ratio = max((item[3] for item in air_shots), default=0.0)
run(60)                                    # 落地后 1 秒：回弹、重新撑开、播完 squash
shot_recover = render_window()
recover_compression = pet.spider.landing_compression
recover_spread = pet.spider.spread()

check("跳跃是状态机（准备→腾空→落地→停稳，顺序不乱）",
      [m for m in mode_seq if m in (locomotion.JUMP_PREPARE,
                                    locomotion.JUMP_AIRBORNE, locomotion.LAND,
                                    locomotion.IDLE)]
      == [locomotion.JUMP_PREPARE, locomotion.JUMP_AIRBORNE, locomotion.LAND,
          locomotion.IDLE],
      "→ %s" % " → ".join(mode_seq))
check("蓄力段身体不许漂（root 位移 <=1.5px）",
      prepare_root_moved <= 1.5, "→ %.2fpx" % prepare_root_moved)
check("蓄力真的压到底（crouch >=0.8）", crouch_max >= 0.8,
      "→ 峰值 %.2f" % crouch_max)
check("空中沿抛物线抬起（>=60px，弧高 %d）" % int(locomotion.JUMP_ARC_PX),
      peak_lift >= 60.0, "→ 实测峰值 %.1fpx" % peak_lift)
check("前进进度单调（不许倒退着跳）", progress_regress <= 0.02,
      "→ 最大回退 %.3f" % progress_regress)
check("腾空不迈步（§9.2C.3）", air_step_onsets == 0,
      "→ 腾空 %d 帧里新起步 %d 次" % (len(air_curve), air_step_onsets))
check("落地那一下压缩接近满值（>=0.8，冲量已衰减 1 帧）",
      land_impulse >= 0.8, "→ %.3f" % land_impulse)
check("落点精确到目标（<=1.5px）",
      math.hypot(land_root.x() - goal.x(), land_root.y() - goal.y()) <= 1.5,
      "→ %.2fpx" % math.hypot(land_root.x() - goal.x(), land_root.y() - goal.y()))
check("恢复 1s 后回弹结束、腿重新撑开",
      recover_compression < 0.05 and recover_spread > 0.9
      and not pet.spider.folding(),
      "→ 压缩 %.3f / 张开度 %.2f" % (recover_compression, recover_spread))
check("骨长一根没变（跳跃不改目标坐标系）",
      all(abs(legs_by_index[i].l1 - l1) < 1e-9
          and abs(legs_by_index[i].l2 - l2) < 1e-9
          for i, (l1, l2) in bone_before.items())
      and pet.spider.leg_stretch == 1.0,
      "→ 10 条腿 l1/l2 全等 · leg_stretch %.2f" % pet.spider.leg_stretch)
check("空中脚尖从不越过最大可达（<=0.995）",
      worst_ratio <= 0.995, "→ 峰值帧最坏 %.4f" % worst_ratio)
dev = abs((math.degrees(pet.spider.heading) - math.degrees(
            math.atan2(goal.y() - jump_start.y(), chord_x)) + 270.0) % 360.0 - 180.0)
check("跳完头还朝着跳跃方向（坐标系没翻）", dev <= 35.0,
      "→ 偏差 %.1f°" % dev)

peak_shot = max(air_shots, key=lambda item: item[2]) if air_shots else (
    land_root, land_shot or shot_start, 0.0, 0.0)
ghost, ghost_k = ghost_cell(1200, 300, jump_start, air_curve,
                            [(r, img) for r, img, _lift, _ratio in air_shots])
jump_rows = [
    ("跳跃四段\n%s px 起跳" % int(jump_distance), [
        (shot_start, "起点 %.0f,%.0f" % (jump_start.x(), jump_start.y()), 1),
        (prepare_last or shot_start, "蓄力 crouch %.2f" % crouch_max, 1),
        (peak_shot[1], "空中 抬起 %.0fpx" % peak_shot[2], 1),
        (land_shot or shot_recover, "落地 压缩 %.2f" % land_impulse, 1),
        (shot_recover, "恢复 压缩 %.2f" % recover_compression, 1),
    ]),
    ("腾空轨迹\n叠加 %d 帧" % len(air_shots), [
        (ghost, "虚线 = 身体 root（位移 1:%.2f）· 每帧缩到 %.0f%% · "
                "跳距 %.0fpx / 弧高 %.0fpx"
         % (ghost_k, GHOST_BODY * 100.0, jump_distance, peak_lift), 3),
    ]),
]
jump_path = build_sheet(os.path.join(OUT, "locomotion_jump.png"),
                        "③ 远距离跳跃 · 起点/蓄力/空中/落地/恢复（生产 paintEvent）",
                        jump_rows)

# ------------------------------------------------------------------ ④ 步态
print("\n[④] 待机 / 慢走 / 快走 / 原地转向（§9.3 的四种基本状态）")

WALK_SECONDS, WARMUP_SECONDS = 2.4, 0.9


def walk_row(px_per_second):
    """按固定速度平移本体，数步频与步幅。

    走的是 `dragging` 那条路（`_tick` 见 `dragging` 就喂 crawl 步态）：
    控制器里走路速度写死 165px/s，测不出「慢走」这一档，而拖动正是真机上
    唯一能连续控制身体速度的入口 —— 步态引擎拿到的位移和拖它时一模一样。
    """
    park()
    pet.dragging = True
    start = QPoint(pet.center)
    screen = pet._screen_rect()
    margin = int(pet.sprite_w * 0.45) + 40
    sign = 1.0 if (screen.right() - margin - start.x()) >= \
        (start.x() - screen.left() - margin) else -1.0
    total = int(WALK_SECONDS * 60)
    warm = int(WARMUP_SECONDS * 60)
    shot_frames = sorted(warm + int(round((total - warm) * f)) for f in SLICE4)
    shot_times = [(frame - warm) / 60.0 for frame in shot_frames]
    x = float(start.x())
    onsets, strides, bobs, shots = 0, [], [], []
    was = {i for i, leg in legs_by_index.items()
           if leg.stepping and not leg.palp}
    for frame in range(1, total + 1):
        x += sign * px_per_second / 60.0
        pet.center = QPoint(int(round(x)), start.y())
        step()
        now = {i for i, leg in legs_by_index.items()
               if leg.stepping and not leg.palp}
        if frame > warm:
            for index in now - was:
                leg = legs_by_index[index]
                if leg.frm and leg.nxt:
                    onsets += 1
                    strides.append(math.hypot(leg.nxt[0] - leg.frm[0],
                                              leg.nxt[1] - leg.frm[1]))
            bobs.append(abs(pet.spider.body_bob))
            if frame in shot_frames:
                shots.append(render_window())
        was = now
    pet.dragging = False
    seconds = (total - warm) / 60.0
    return {"shots": shots, "shot_times": shot_times,
            "onsets": onsets, "cadence": onsets / seconds,
            "stride": sum(strides) / len(strides) if strides else 0.0,
            "bob_max": max(bobs) if bobs else 0.0,
            "moved": math.hypot(pet.center.x() - start.x(),
                                pet.center.y() - start.y()),
            # 期望位移按**整段**算：`moved` 量的是全程，`cadence` 才只量预热之后
            "want": px_per_second * total / 60.0,
            "room": (screen.right() - margin - start.x()) if sign > 0
            else (start.x() - screen.left() - margin),
            "sign": sign,
            "heading": math.degrees(pet.spider.heading) % 360.0}


slow = walk_row(45.0)
fast = walk_row(240.0)

check("慢走 45px/s：本体按指令平移（±3px）",
      abs(slow["moved"] - slow["want"]) <= 3.0,
      "→ %.0fpx / 指令 %.0fpx" % (slow["moved"], slow["want"]))
check("快走 240px/s：本体按指令平移（±3px）",
      abs(fast["moved"] - fast["want"]) <= 3.0,
      "→ %.0fpx / 指令 %.0fpx" % (fast["moved"], fast["want"]))
check("两档都留在屏幕安全区内（截图不会被边缘裁掉）",
      slow["want"] <= min(slow["room"], fast["room"])
      and fast["want"] <= min(slow["room"], fast["room"]),
      "→ 需要 %.0f/%.0fpx，可用 %.0fpx"
      % (slow["want"], fast["want"], min(slow["room"], fast["room"])))
check("快走步频高于慢走（>=1.15×，§9.2B 频率随速度）",
      fast["cadence"] >= slow["cadence"] * 1.15,
      "→ %.1f vs %.1f 步/秒" % (fast["cadence"], slow["cadence"]))
check("快走步幅大于慢走（>=1.05×，§9.2B 步长随速度）",
      fast["stride"] >= slow["stride"] * 1.05,
      "→ %.1f vs %.1f 局部单位（≈%.0f vs %.0fpx）"
      % (fast["stride"], slow["stride"], fast["stride"] * pet.unit,
         slow["stride"] * pet.unit))
check("两种速度都在持续倒换腿（慢 >=3 次 / 快 >=12 次）",
      slow["onsets"] >= 3 and fast["onsets"] >= 12,
      "→ %d / %d 次（慢走 2.4s 只挪 %.0fpx，本来就没几步）"
      % (slow["onsets"], fast["onsets"], slow["moved"]))
check("走路起伏在限内且不随速度失控（<=BOB_MAX×体型）",
      0.05 <= slow["bob_max"] <= CS.BOB_MAX * pet.spider.scale + 1e-6
      and fast["bob_max"] <= CS.BOB_MAX * pet.spider.scale + 1e-6,
      "→ 峰值 %.2f / %.2f，上限 %.2f"
      % (slow["bob_max"], fast["bob_max"], CS.BOB_MAX * pet.spider.scale))
want_deg = 0.0 if slow["sign"] > 0 else 180.0
slow_dev = abs((slow["heading"] - want_deg + 180.0) % 360.0 - 180.0)
fast_dev = abs((fast["heading"] - want_deg + 180.0) % 360.0 - 180.0)
check("慢走/快走时头都领路（偏差 <=25°）",
      slow_dev <= 25.0 and fast_dev <= 25.0,
      "→ %.1f° / %.1f°（前进方向 %.0f°）" % (slow_dev, fast_dev, want_deg))

# 待机：把降频关掉，逐帧推满 6 秒，再取三帧（间隔各 1 秒）比墨迹。
# 关降频是因为 `_tick` 在降频态直接 return —— 那样「画面没动」是空转出来的，
# 不是静止出来的，断言就白做了。
park()
for _ in range(360):
    pet._idle_frames = 0
    pet._downshifted = False
    step()
idle_center = QPoint(pet.center)
idle_shots = []
for frame in range(1, 121):
    pet._idle_frames = 0
    pet._downshifted = False
    step()
    if frame in (1, 60, 120):
        idle_shots.append(render_window())
idle_still = (not any(leg.stepping for leg in pet.spider.legs)
              and not pet.spider.folding()
              and abs(pet.spider.body_bob) < 0.02)
prints = [ink_fingerprint(image) for image in idle_shots]
drift = max(max(abs(p[1] - prints[0][1]), abs(p[2] - prints[0][2])) for p in prints)
mass = max(abs(p[0] - prints[0][0]) / max(prints[0][0], 1.0) for p in prints)
moved_idle = math.hypot(pet.center.x() - idle_center.x(),
                        pet.center.y() - idle_center.y())
check("（前提）待机 = 没有腿在迈、腿全伸着、起伏归零", idle_still,
      "→ bob %.4f" % pet.spider.body_bob)
check("待机三帧（相隔各 1s）墨迹完全一致 —— 不许抽搐",
      drift <= 0.6 and mass <= 0.002,
      "→ 质心漂 %.2fpx / 墨迹差 %.3f%%" % (drift, mass * 100.0))
check("待机本体不动", moved_idle < 0.5, "→ %.1fpx" % moved_idle)

# 原地转向：生产彩蛋 `spin_once`（转的是模型朝向，脚钉住）
park()
spin_start = QPoint(pet.center)
spin_frames = int(anim.EFFECT_DURATION["spin"] * 60)
spin_shot = sorted(int(spin_frames * f) for f in SLICE4)
spin_times = [frame / 60.0 for frame in spin_shot]
spin_onsets = 0
spin_shots = []
spin_turn = 0.0            # 累计转角：一圈转完时首尾朝向差会绕回 0，只能逐帧累加
was = {i for i, leg in legs_by_index.items() if leg.stepping and not leg.palp}
previous_heading = pet.spider.heading
pet.spin_once()
for frame in range(1, spin_frames + 1):
    step()
    spin_turn += pet.spider.heading - previous_heading
    previous_heading = pet.spider.heading
    now = {i for i, leg in legs_by_index.items()
           if leg.stepping and not leg.palp}
    spin_onsets += len(now - was)
    was = now
    if frame in spin_shot:
        spin_shots.append(render_window())
spin_moved = math.hypot(pet.center.x() - spin_start.x(),
                        pet.center.y() - spin_start.y())
spin_deg = math.degrees(spin_turn)
check("原地转向：本体不漂移（<=10px）", spin_moved <= 10.0,
      "→ %.1fpx" % spin_moved)
check("原地转向：腿逐条倒换（不是整张图打转）", spin_onsets >= 4,
      "→ %d 次迈步" % spin_onsets)
check("原地转向：真的转了近一圈（>=300°）", spin_deg >= 300.0,
      "→ %.0f°" % spin_deg)

speed_rows = [
    ("待机\n各隔 1s", [(image, "质心 %.1f,%.1f" % (p[1], p[2]), 1)
                       for image, p in zip(idle_shots, prints)]),
    ("慢走 45px/s\n步频 %.1f/s · 步幅 %.0fpx" % (slow["cadence"], slow["stride"] * pet.unit),
     [(image, "t=%.2fs" % t, 1)
      for image, t in zip(slow["shots"], slow["shot_times"])]),
    ("快走 240px/s\n步频 %.1f/s · 步幅 %.0fpx" % (fast["cadence"], fast["stride"] * pet.unit),
     [(image, "t=%.2fs" % t, 1)
      for image, t in zip(fast["shots"], fast["shot_times"])]),
    ("原地转向 spin 0.9s\n转过 %.0f° / %d 次迈步" % (spin_deg, spin_onsets),
     [(image, "t=%.2fs" % t, 1)
      for image, t in zip(spin_shots, spin_times)]),
]
speed_path = build_sheet(os.path.join(OUT, "locomotion_speed.png"),
                         "④ 待机 / 慢走 / 快走 / 原地转向（生产 paintEvent）",
                         speed_rows)

print("\n  图：%s" % walk_path)
print("  图：%s" % orient_path)
print("  图：%s" % jump_path)
print("  图：%s" % speed_path)
print("\n" + "=" * 78)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
for name in FAIL:
    print("  FAILED:", name)
raise SystemExit(1 if FAIL else 0)
