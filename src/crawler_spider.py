# -*- coding: utf-8 -*-
"""程序化蜘蛛几何 + 步态状态机 —— 源自 web-crawlers `js/crawler.js` 的移植。

★ 授权状态（2026-10-22）：上游 `cyohei9907/web-crawlers` **没有 LICENSE**，
  按默认版权 = 保留所有权利。本文件是它的衍生作品，**在拿到作者书面许可
  之前不能对外宣称「独立实现 / 原创」**，也不该把 MIT 许可证覆盖到这部分。
  见 `THIRD_PARTY_NOTICES.md` 第三节。

沿用的骨架（结构性，不是调个数字就能脱开的）：
    · 8 条步足 + 2 条触须（pedipalp），两骨 IK，每条腿**固定弯曲侧**
      （唯一例外：待机徽章站姿会把膝盖缓慢翻向另一侧，见 `Leg.arch`）
    · 阈值驱动步态：脚偏离静止位到一定比例才迈步，同时最多 4~6 条腿在动，
      同侧相邻腿不许同时迈；迈步时脚沿 `smoothstep` 插值并**向髋部收**（真抬腿）
    · 配色语汇：天蓝腿、高光小腿、红关节红脚尖

2026-10-22 重调过的数值（目的是拉开与原版参数表的距离，**不等于换了一套实现**）：
    · `LEG_DEF` 四对步足的静止角（非等距）与中段腿长（原 0.55/1.15/1.95/2.55）
    · 分骨比 `L1:L2` 由 0.56:0.64 改为 0.54:0.66（膝盖略往髋收；和值仍 1.20）
    · `STEP_FRAC` 0.30→0.34、`URGENT_FRAC` 0.50→0.55、迈步时长整体略快
    · 速度前瞻 0.3→0.26、`VELOCITY_DAMP` 5→6、腹部跟随 12/14→10/11
    · `HIP_SIDE` 3.0→3.2；渲染线宽 1.25→1.42、点径指数 0.6→0.52
      （见 `spider_painter.paint`）
  仍与原版逐项相同的：`OVER_FRAC` 0.92、`PLACE_FRAC` 0.85、同侧协调规则、
  IK 公式本身、reach 极值 118/126、腿数（8 步足 + 2 触须）。

在此之上的自有扩展（上游完全没有）：
    · 异步行波相位排班、待机徽章站姿、模式系统、身体起伏/蓄力/落地压缩、
      转弯倾斜与侧摆、逐腿折叠、八足分派瞄准（`place_targets` / `assign_legs`）、
      可点头部三角与命中判定、皮肤系统
    · `limit_to_reach()`：上游的脚锚在真实 DOM 元素上，天然受网页布局约束；
      这里脚是数学点，必须自己夹住，否则会画出越过膝盖的"射线腿"

坐标系：局部坐标，原点 = 体心 `p`，**朝向恒为 +x**（屏幕上的旋转由渲染层负责）。
`update(motion=...)` 的入参是**世界（屏幕）位移**（单位=局部单位，即像素/unit），
内部用 `Spider.to_body()` 旋进体坐标系后才喂步态；朝向追世界运动方向，
所以头（+x）永远领路。换算的唯一真相见 `Spider.forward/to_body/to_world`。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 调参（对齐 crawler.js）

#: 两段骨长相对 `reach` 的比例。**L1_FRAC + L2_FRAC 必须恒为 1.20** ——
#: `leg.full = l1 + l2 = 1.20 × reach` 是所有「占腿长比例」阈值（OVER/PLACE/
#: 抬腿夹取）的分母，和值一变，这些阈值的实际像素含义就跟着漂。
#: 上游是 0.56 / 0.64。这里取 0.54 / 0.66：膝盖略往髋部收，折角比原版尖一点。
#: ★ 试过 0.50 / 0.70，膝更靠髋、小腿更长 —— 出图后 240 px/s 那几帧腿交叉成一团，
#:   比原版还乱，回退到 0.54 / 0.66。小腿超过 0.66 就不该再放大。
L1_FRAC = 0.54
L2_FRAC = 0.66

#: 基准尺寸。crawler.js 里 SCALE=1.45，这里让 1.0 就是它。
BASE_SCALE = 1.45

#: 腿部定义 [静止角(rad), 腿长, 髋部前后偏移]，左右各一套 = 8 腿 + 2 触须
#: 触须那一项的「髋部前后偏移」**已不生效**：它改由 `PALP_HIP_FWD/SIDE`
#: 按头部三角定位（见下面的常量说明），这里保留 10.0 只为对齐表结构。
#: ★ 2026-10-22：角度与中段腿长已重调，不再沿用上游数值。上游是
#:   (0.55,118) (1.15,106) (1.95,106) (2.55,126) (0.22,38)，本项目此前
#:   只挪过两项（1.95→2.08 / 2.55→2.72），仍是"逐项对得上"的状态。
#:   现在改成**非等距**分布：四对步足的角间距是 0.64 / 0.86 / 0.56（上游 0.60 /
#:   0.80 / 0.60），中段两对腿长一长一短（108 / 104）。剪影与原版不再逐项对应。
#: ★ 试过更激进的外扩（0.66/1.32/2.24/2.90 + reach 102/110），出图后 240 px/s
#:   的帧里腿交叉成 X 形线团，待机也散成"竹节虫"，已回退到这一档。
#: ★ 前后足的极值（118 / 126）**故意保留**：`max_reach()` 取的就是 126，
#:   它决定 `unit_for_width()` 的基准和桌宠窗口尺寸，动它等于动窗口。
LEG_DEF = (
    (0.62, 118.0, 7.0),     # 前足
    (1.26, 108.0, 3.0),
    (2.12, 104.0, -1.0),
    (2.68, 126.0, -5.0),    # 后足
    (0.26, 38.0, 10.0),     # 触须 pedipalp
)

#: 步态阈值
#: ★ 2026-10-22：上游是 .30 / .50 / .92 / .85。步幅与紧急阈值重调（.30→.34、
#:   .50→.55）；后两项**保持原值** —— `OVER_FRAC` 与 `assign_reachable()` 的
#:   `max_frac=0.92` 是同一个口径，`PLACE_FRAC` 又和 `IDLE_POSE` 前足的伸展
#:   系数卡在一起（`REST_K×1.26 = 0.8×1.26×reach = 0.84×full`，离 0.85 只剩
#:   0.01 的余量）：收紧到 0.82 会让待机站姿的静止位超出落脚上限，脚永远够不到
#:   → 每帧重复迈步，观感就是"站定时抽筋"。
STEP_FRAC = 0.34          # 偏离静止位超过这个比例（×腿长）就迈步
URGENT_FRAC = 0.55        # 超过就无视协调直接迈
OVER_FRAC = 0.92          # 硬上限，超过立即回缩（与 assign_reachable 的 0.92 同源，别单独动）
PLACE_FRAC = 0.85         # 新落脚点最远到腿长的这个比例
STEP_DUR = (0.09, 0.15)   # 常规迈步时长
STEP_DUR_QUICK = (0.065, 0.10)
MAX_STEPPING_SLOW = 4
MAX_STEPPING_FAST = 6
STEP_SPEED_FAST = 70.0

#: 落脚点的速度前瞻（秒）与前瞻幅度上限（×腿长）
#: 上游是 0.3 / 0.3；这里收到 0.26 / 0.27，脚落在身体"将要去"而不是"更远处"，
#: 步幅看着更收，配合 STEP_FRAC 0.34 才不至于一条腿跨过去半屏。
LEAD_SECONDS = 0.26
LEAD_MAX_FRAC = 0.27

#: 速度平滑系数（1 秒内衰减到约 1/e）。上游 5.0；调大一点，
#: 起步/刹车跟得更紧，落脚点前瞻不会拖着上一段运动的惯性走。
VELOCITY_DAMP = 6.0

#: 模式切换时 spread 的平滑系数（越大切得越快）
SPREAD_DAMP = 8.0

#: 腹部拖尾跟随系数（上游 12 / 14）。放慢一档，转弯时腹部滞后更明显 ——
#: 尾巴那条点链已经不在画面上，这个量只影响 `body["abd"/"spin"]` 的跟随，
#: 所以纯粹是给以后把尾巴加回来时留的手感。
ABD_DAMP = 10.0
SPIN_DAMP = 11.0

#: 身体侧摆幅度（局部单位），按左右两侧正在迈步的腿数差
SWAY_PER_LEG = 1.6

# ------------------------------------------------ 身体反馈（任务书 §9.2B / §9.2C）
#
# 三个标量都**只影响画出来的身体和髋部**，不参与 IK 的落脚解算，也不改 `foot`：
# 脚始终钉在屏幕上，身体往上抬 / 往下压时腿自动变长变短 —— 这就是
# 「身体从脚上方通过」的反向表达。所以 `test_locomotion` 的「脚钉住」不变量
# 不会因为加了起伏而松，`hit_test` 的判定框也不跟着抖（判定用模型点，不用绘制偏移）。

#: 起伏幅度：每条**正在抬起**的腿贡献 `sin(πt)`（0→1→0），乘这个系数再累加。
#: 为什么不另开一个 `sin(gait_phase)` 振荡器：那种起伏和真实迈步对不上拍，
#: 身体会「自己抖」而脚没动 —— 一眼就是假动画。挂在上腿数量上，起伏天然合拍。
BOB_PER_LEG = 0.62
#: 起伏上限（局部单位，再乘体型 `scale`）。≈2 单位在 360px 档位是 2~5px，
#: 「轻轻起伏」而不是踩高跷。
BOB_MAX = 2.0
#: 起伏/蓄力/压缩各自的缓动系数（`damp(k, dt)`，越大跟得越快）。
#: 蓄力必须快（准备段只有 0.16s），恢复要慢（落地后回弹 0.1~0.2s 才像有重量）。
BOB_RATE = 16.0
CROUCH_RATE = 30.0
COMPRESSION_RATE = 8.5

#: 蓄力时身体下沉多少局部单位、落地压缩时下沉多少。
#: 压缩比蓄力沉得多一点：跳下来那一下比蹲下去重。
#: ★ 这两个是**无量纲 0..1 的系数**（`crouch` / `landing_compression`）乘的幅度，
#:   绘制层自己乘 `unit` 换成像素；和 `body_bob` 不同 —— 那个在模型里已经乘过
#:   体型 `scale` 了，别再乘第二遍。
CROUCH_SINK = 2.6
LAND_SINK = 3.4

#: 压缩/蓄力时身体的**压扁比例**：`sy = 1 − k×s`、`sx = 1 + k×0.6×s`。
#: 身体素材是图不是矢量形状，所以压扁只作用在头胸矩形那块绘制变换上（见 painter）。
SQUASH_SY = 0.16
SQUASH_SX = 0.10

#: 髋部随身体下沉走 100%，膝盖只走这一档，脚尖 0%（钉子）。
#: 为什么不是 0 也不是 1：完全不跟的话身体压下去、膝盖还停在原处，大腿会被
#: 硬拉成一条直线；全跟的话整条腿一起平移，脚就像被身体拖着走 = 滑步。
KNEE_FOLLOW = 0.45

#: 转弯倾斜系数：角速度 × 这个值 = lean（弧度），再钳到 ±LEAN_MAX
TURN_LEAN_K = 0.28
LEAN_MAX = 0.16

#: 闲置抽动概率（每秒）—— crawler.js 里是 dt*0.3，这里**默认关掉**。
#: 真蜘蛛站着确实会偶尔挪一下脚，但那 0.3/s 乘 8 条腿 ≈ 每秒 2.4 次抬脚，
#: 在桌宠这种「被人盯着看」的场景里就是持续的小抽搐，用户明确要求
#: 「待机时身体不动，不要抽搐」。机制保留在这里，想要的话改成正数即可
#: （`test/test_spider.py` 里有一条「静止时不迈步」的断言守着它，改之前先想清楚）。
IDLE_TWITCH_RATE = 0.0

#: 步态相位推进：身体每移动 1 个局部单位，相位前进这么多。
#: 真机 unit≈1.232（sprite_w=360），WALK_SPEED=165 px/s → 134 局部单位/秒，
#: 于是相位周期 ≈ 1.66 秒。注意这个值**只在真机 unit 下才有意义** ——
#: 局部单位/秒 = 像素速度 / unit，拿小尺寸探针的 unit 调出来的值搬到真机
#: 会整体慢一倍（踩过，见 tools/gait_probe.py 的说明）。
GAIT_PHASE_PER_UNIT = 0.0045
#: 每条步足的理想相位（0..1），右侧基准；左侧整体偏移半周期，形成异步行波
LEG_PHASE = (0.0, 0.5, 0.25, 0.75)   # slot 0..3
#: 每条腿的相位窗口占周期的比例（两侧各 GAIT_WINDOW，实际占空比 2×）。
#: 0.30 → 占空比 60%：既能看出「波浪式依次迈步」，又不会把腿饿到被拖长。
GAIT_WINDOW = 0.30

#: 原地转身也要推相位：每转 1 弧度前进这么多。转满一圈（2π）≈ 一个完整周期。
#: 少了这条，转身时 `gait_phase` 一动不动（它只按平移距离推进），
#: 窗口外的腿只能靠 `PHASE_RELIEF` 兜底先迈，行波就散了。
GAIT_PHASE_PER_RAD = 1.0 / (2.0 * math.pi)

#: 相位窗口外的兜底倍数：偏离静止位超过 `thresh × 这个值` 就允许无视相位先迈。
#: 异步行波是**排班偏好**，不能当硬闸门 —— 一旦变成闸门，错过窗口的腿要等
#: 一个整周期（真机 165 px/s 下约 1.66 秒），期间会被身体拖到腿长边缘。
PHASE_RELIEF = 1.5

#: 单条腿折叠/伸回的缓动速率（1/秒）。5.0 → 走完 90% 约 0.46 秒：
#: 再快就像被拽一下，再慢则跟不上「换批」（一批停留默认 0.45 秒）。
FOLD_DAMP = 5.0
#: 身体随折叠量的缓动速率。比腿慢一档：腿先收、身子再轻轻收拢，
#: 读起来是「缩成一团」而不是「整只蜘蛛一起缩水」。
BODY_FOLD_DAMP = 3.2
#: 全折叠时身体**朝头部等比缩小**的比例（锚点 = 前缘中心，头与头三角纹丝不动）。
#:
#: 以前这里是 0.12 的「只把后缘往前挪」：宽度缩 12%、高度一点不变，
#: 观感上只是肚子短了一截，像是被压扁而不是「缩回壳里」。现在改成**等比缩**：
#: 后缘往前、上下也往中轴收，整块身子朝着头那侧缩进去，读起来才是
#: 「蜘蛛把身子收拢到脑袋后面」。
#:
#: 0.22 是「看得出来、又不失真」的一档：全折叠时身体长宽各小两成，
#: 还稳稳包住头部三角的底边（头部素材本身不缩，缩太多会露出脖子缝）。
BODY_FOLD_SHRINK = 0.22

#: 瞄准时脚尖靠近目标的速率（指数平滑的 k）。越大越「一下子扑过去」，
#: 越小越「缓缓伸过去」。
#: 16 ≈ 0.28s 走完 95% 的距离（e^{-16×0.19}≈0.05）：踩词是「指一下」而不是
#: 「慢慢摸过去」，慢了就跟整个 OCR 流程对不上节奏。再往上调就接近瞬移，
#: 腿会显得没有重量。
TARGET_APPROACH_K = 16.0

#: 脚尖距离目标这么近（局部单位）就算到位。
#: 指数平滑的尾巴很长，0.8 个单位 ≈ 1px，再小就要多花上百毫秒去补最后一点
#: 肉眼根本看不出的距离。
TARGET_EPS = 0.8

#: 脚相对髋部的最大距离（×腿长）。脚是「钉在世界上」的，身体走快了、或者迈步
#: 过程中身体继续前移，局部距离就会被一路拉大；而 `solve_ik` 只把**膝盖**伸直，
#: 并不约束脚尖，于是脚尖会飞到腿长之外 —— 画出来就是一条被拉长的腿。
#: 物理上脚不可能比腿长更远，所以在这里硬夹住。夹住的瞬间脚会轻微「滑」一下，
#: 那正是真蜘蛛跟不上身体时被拖着走的样子；紧接着 `OVER_FRAC` 会触发一次回缩步。
REACH_LIMIT_FRAC = 0.99

#: 朝向跟随速度的最小速度（局部单位/秒）。低于它不改朝向，站定时才不会自己乱转。
HEADING_MIN_SPEED = 6.0

#: 身体各节点沿朝向的偏移（×SCALE）
#: HEAD_OFF 同时是头部三角的**底边位置**：头胸放大 2.5 倍后，底边也要
#: 按比例前移（原：前沿 17 − 底边 12 = 5；现：前沿 42.5 − 底边 30 = 12.5），
#: 否则头会「陷」进放大后的身体里，看着像头比身体小了。
HEAD_OFF = 30.0
ABD_OFF = -17.0
SPIN_OFF = -13.0
#: 髋部横向偏移（×SCALE）。上游 3.0；这里 3.2 —— 只放一点点。
#: 试过 3.6，髋点离体轴太远，腿根张开后整体像"伞骨"，慢走时同侧腿会互相穿插。
HIP_SIDE = 3.2

#: 触须（pedipalp）髋部：挂在**头部三角底边两侧**，而不是身子前缘正中。
#:
#: 以前两根触须和八条步足共用 `HIP_SIDE`（x = 10×SCALE ≈ 14.5、y = ±3×SCALE
#: ≈ ±4.4），几乎压在体轴中线上 —— 远看就是「从肚子前面伸出两根短刺」，
#: 跟「长在头上的感觉器」不是一回事。蜘蛛的触须本来长在头前方两侧，
#: 所以按头部三角（底边在 `HEAD_OFF`、半宽 `HEAD_TRI_HALF`）定位：
#: 纵向从底边再往前 `PALP_HIP_FWD` × 三角长，横向取半宽的 `PALP_HIP_SIDE`。
#:
#: ★ 这两个比例乘出来的是**局部单位**，**不乘 `BASE_SCALE`**：触须是挂在
#:   头上的，而头部三角的常量（`HEAD_OFF` / `HEAD_TRI_LEN` / `HEAD_TRI_HALF`）
#:   本来就是局部单位（见 `_in_head_tri` 与 `spider_painter` 的 `head_rect`）。
#:   乘了 `BASE_SCALE` 的话，髋部会跑出头顶之外。
PALP_HIP_FWD = 0.15
PALP_HIP_SIDE = 0.75
#: 静止时脚尖的伸展系数
REST_K = 0.8

#: 待机姿势（徽章站姿）：静止不动时腿摆成参考图那样 ——
#: 八条腿全部收拢到体轴两侧、沿身体纵轴方向拱起：前足两对向前上方举起
#: （外拱 ~24°、内拱 ~9°，脚尖钩回头顶上方汇拢），后足两对向后下方垂拖
#: （外拱 ~148°、内拱 ~170°，脚尖贴着腹部两侧收尾）。
#: 参考图实测腿尖相对体轴角：±8° / ±24° / ±148° / ±170°。
#: 每项 = (静止角 rad，未乘 side；伸展系数，乘在 REST_K 之外)。
#: 注意 slot2/slot3 的角度是**倒序**的：最长后足（slot3）摆外侧大拱，
#: slot2 贴着体轴拖到几乎正后方 —— 与参考图的外长内短一致。
#: 只作**混合目标**：rest_pos 按 `_idle_pose_t` 在「走路站姿」和它之间插值，
#: 脚钉在原地不动，静止位慢慢移过去，腿被阈值步态一条条「挪」进姿势 ——
#: 看着就是蜘蛛站定后自己调整落脚，而不是八条腿瞬移。
#: 伸展系数：前足 1.26（REST_K×1.26×reach = 0.84×腿长，刚好卡在落脚点上限
#: PLACE_FRAC(0.85) 之内，拱形张到最开）；后足 0.87/0.88（膝弯得更深，
#: 脚尖收在腹侧，对应参考图后足明显短一截的剪影）。
IDLE_POSE = (
    (0.42, 1.26),   # 前足：外拱，向前上举 ~24°
    (0.16, 1.26),   # 第二对：内拱，~9°，脚尖汇拢到头顶轴线
    (2.88, 0.87),   # 第三对：后内拱，贴腹垂拖
    (2.66, 0.88),   # 后足：后外拱
    (0.22, 1.00),   # 触须不变
)
#: 拱形换边速率（1 秒衰减到约 1/e）。腿尖不动，膝盖从「朝体轴」扫到
#: 「朝体外」，中途经过完全伸直的一瞬 —— 像真蜘蛛重新架腿。
ARCH_DAMP = 5.0
#: 徽章站姿里哪几对步足需要把膝盖翻向体外（按 slot）。
#: 前足/第二对/后足走路时都是「肘朝内」的折线，摊到 ±10°/±25° 与 ±148°
#: 这种沿轴方向后，必须翻成「膝朝外」的拱才和参考图一致；
#: **唯独第三对不翻** —— 它的 bend 本来就与前三对相反（LEG_DEF 里
#: `slot in (3, 4)` 那一项），脚尖拖到 ~166° 时不翻正好外凸，
#: 翻了反而跨过体轴画出一个 X。
IDLE_POSE_ARCH = (1, 1, 0, 1)
#: 姿势淡入/淡出速度（1 秒衰减到 1/e）。要慢：淡入期间静止位移动得比
#: 迈步快，腿才能一步接一步跟上；太快了静止位瞬间跳变 = 八腿集体抽筋。
IDLE_POSE_DAMP = 2.2
#: 进入姿势的静止判定：速度低于它且几乎不自转才算「站定」。
#: 自转时必须排除 —— 转身时脚要忙着蹬地，没空摆姿势。
IDLE_POSE_SPEED = 6.0
IDLE_POSE_TURN = 0.5

#: 头胸矩形（局部坐标，随朝向旋转）
THORAX = (-8.0, -5.5, 18.0, 11.0)

#: 头胸额外放大系数。原版 18×11 是配 SCALE=1.45 调的；桌宠整体缩得比原版小，
#: 原尺寸下头胸只有 17px 宽，在浅色桌面上只剩一圈亮边，像个白方块。
#: 曾放大到 1.7；2026-10-16 用户要求头+身体**等比例放大到原来的 2.5 倍**：
#: 1.7 × 2.5 = 4.25。头三角、圆角半径、HEAD_OFF（三角底边）同步 ×2.5，
#: 渲染（spider_painter）与命中判定（hit_test / covers）都读这些常量，
#: 改这里一处，画出来的和点得中的还是同一块形状。
THORAX_SCALE = 4.25
#: 头胸矩形圆角半径（×unit），让方块更像肚子而不是硬边框
THORAX_RADIUS = 7.5

#: 头部三角形（局部坐标，朝向 +x）。底边落在头胸矩形**里面一点**（这样两块
#: 连成一个整体），顶点伸出矩形前沿 `HEAD_OFF + HEAD_TRI_LEN - 前沿`。
#: 前沿在 `(THORAX[0]+THORAX[2]) * THORAX_SCALE = 42.5`，所以三角露在外面
#: 30 个局部单位 —— 要够显眼，用户要「一眼看出哪里是头、点了会识词」。
HEAD_TRI_LEN = 42.5
HEAD_TRI_HALF = 22.5

# ---------------------------------------------------------------- 配色

COLORS = {
    "leg": "#5cc8ff",
    "leg_hi": "#9be0ff",
    "joint": "#ff4a6e",
    "body": "#cfe8ff",
    "body_fill": "#142878",        # 原 rgba(20,40,130,.65)，这里按不透明处理
    "web_line": (92, 200, 255),    # 腹部到髋部的半透明连接线
}

#: 「八足微光」八色：瞄准时每条步足一色（腿的辉光 + 词框 + 引导线共用）
LEG_AURA = (
    "#2ee6d6", "#4d8bff", "#b06bff", "#ff5cb8",
    "#ff4d5e", "#ff8a3d", "#ffd93d", "#3ddc84",
)

#: 触须沿用原版的高光色，不参与八色轮换
CS_HI = COLORS["leg_hi"]

# ---------------------------------------------------------------- 状态

MODES = ("idle", "crawl", "think", "rest", "jump")

#: 各模式下静止姿态的伸展系数与亮度
# jump 收到 0.4：跳蛛腾空时腿是贴身的，收到 0.62 还看得出「海星」
MODE_SPREAD = {"idle": 1.0, "crawl": 1.0, "think": 1.06, "rest": 0.55, "jump": 0.40}
MODE_DIM = {"idle": 1.0, "crawl": 1.0, "think": 1.0, "rest": 0.8, "jump": 1.0}


def clamp(v: float, a: float, b: float) -> float:
    return a if v < a else (b if v > b else v)


def damp(k: float, dt: float) -> float:
    """指数平滑系数：1 秒内衰减到约 e^{-k}。对齐 crawler.js 的 damp。"""
    return 1.0 - math.exp(-k * dt)


def damp_pt(a, b, k: float, dt: float):
    """二维点的指数平滑。"""
    f = damp(k, dt)
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def smoothstep(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def limit_to_reach(leg, point) -> tuple:
    """把 ``point`` 夹到「离髋部不超过 `REACH_LIMIT_FRAC × 腿长`」的圆内。

    腿不可能比自己的长度更长。脚「钉在世界上」，身体一走快，脚在局部坐标里
    就被越拉越远 —— `solve_ik` 只会把膝盖伸直，不会把脚尖拉回来，
    于是画面上出现一条越过膝盖笔直拖出去的腿。这里统一兜住。

    只夹**脚尖**，不夹膝盖：膝盖是解算出来的，本来就在腿长之内。
    """
    hx, hy = leg.hip_pos
    dx, dy = point[0] - hx, point[1] - hy
    d = math.hypot(dx, dy)
    limit = leg.full * REACH_LIMIT_FRAC
    if d <= limit or d < 1e-9:
        return (point[0], point[1])
    k = limit / d
    return (hx + dx * k, hy + dy * k)


def point_segment_distance(point, a, b) -> float:
    """点到线段的最短距离（都当二维点处理）。"""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    if span <= 1e-9:
        return math.hypot(point[0] - ax, point[1] - ay)
    t = ((point[0] - ax) * dx + (point[1] - ay) * dy) / span
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(point[0] - (ax + dx * t), point[1] - (ay + dy * t))


@dataclass
class Leg:
    """一条腿（步足或触须）的运行时状态。"""

    index: int          # 全局序号 0..9
    side: int           # +1 右侧 / -1 左侧
    slot: int           # LEG_DEF 里的下标 0..4
    ang: float          # 静止角（相对 +x，已乘 side）
    reach: float
    hip: float          # 髋部前后偏移（×SCALE）
    hip_y: float        # 髋部横向偏移（side × 3 × SCALE）
    l1: float
    l2: float
    bend: int
    palp: bool
    #: 拱形换边系数 0..1（仅待机姿势用）：0 = 走路时的弯曲侧（膝朝体轴），
    #: 1 = 徽章站姿的**反向**弯曲（膝朝体外、脚尖钩回轴线）—— 参考图的
    #: 腿是向外凸的拱，而走路站姿的腿是向内折的肘。IK 里等效弯曲量 =
    #: `bend × (1 − 2×arch)`，arch 扫过 0.5 的瞬间腿正好完全伸直，
    #: 所以换边是「伸直→反向弯」的连续过程，不会瞬移抽筋。
    arch: float = 0.0
    aura: str = ""
    #: 这一批有没有派到词（任务书 §9 的 per-leg ``assigned``）。
    #: 默认 True：没有覆盖层在管腿的时候，八条腿都算「在用」。
    assigned: bool = True
    #: 折叠进度 0..1（1 = 整条腿收到髋部）与它的缓动目标。
    #: 目标是**瞬时**设定的意图，`fold` 才是逐帧插出来的实际值 ——
    #: 分派批次时不会看到腿「啪」地弹进弹出。
    fold: float = 0.0
    fold_target: float = 0.0
    #: 构造时算出的**原始**腿根半径（reach × scale）。`set_leg_stretch()`
    #: 靠它做可逆缩放 —— 不存这一份就只能连乘，反复调用会越拉越长。
    rest_r: float = 0.0

    foot: tuple = None       # 已落地的落脚点（局部坐标）
    nxt: tuple = None        # 正在迈向的点
    frm: tuple = None        # 迈步起点
    #: 瞄准时的目标（局部坐标）与当前脚尖（用于平滑靠近）
    target_goal: tuple = None
    target_now: tuple = None
    t: float = 0.0
    dur: float = 0.15
    stepping: bool = False
    #: 本次迈步是否「紧急」（紧急时按原版一样无视同时迈步数与同侧协调限制）
    quick: bool = False

    knee: tuple = (0.0, 0.0)
    tip: tuple = (0.0, 0.0)

    @property
    def full(self) -> float:
        return self.l1 + self.l2

    @property
    def hip_pos(self) -> tuple:
        return (self.hip, self.hip_y)


@dataclass
class Target:
    """瞄准目标（局部坐标由渲染层换算好）。"""

    text: str
    center: tuple
    color: str = ""


@dataclass
class Spider:
    """程序化蜘蛛。"""

    size: float = 1.0
    mode: str = "idle"
    #: 朝向（弧度）。**默认 PI/2，即面朝屏幕下方** —— 这点和 crawler.js 一致，
    #: 而且很关键：腿的角度是相对朝向定义的，朝向一变，整圈腿的分布就跟着转。
    #: heading=0（面朝右）时 8 条腿会摊成「上四下四」，那正是螃蟹的站法；
    #: heading=PI/2 时才是「左上二 / 左下二 / 右上二 / 右下二」的蜘蛛俯视。
    heading: float = math.pi / 2
    speed: float = 0.0
    targets: dict = field(default_factory=dict)   # leg.index -> 局部坐标
    legs: list = field(default_factory=list)
    #: 身体贴图的放大倍数（由渲染层按当前皮肤写入，见 `SkinSpec.body_scale`）。
    #: 模型自己不关心皮肤，但**命中判定必须跟着画出来的大小走** ——
    #: 否则 2 倍身子只有前半截能点中，后半截大半个肚子点在空气上，
    #: 而且 `covers()` 会放行鼠标，点击直接穿到下面的窗口。
    body_scale: float = 1.0
    #: 身体「收拢」进度 0..1：多少比例的腿已经折回髋部（见 `fold_amount`）。
    #: 渲染层按它把头胸**朝头部等比缩小**（见 `BODY_FOLD_SHRINK`），
    #: 命中判定读同一个值，于是「看不见的地方点得中」这种老毛病不会再犯
    #: （头部不受影响）。
    body_fold: float = 0.0
    #: **外部**折叠深度 0..1（右键菜单的「折叠 / 无腿模式」）。
    #:
    #: 为什么单开一个字段：那条路径走的是 `SpiderState.leg_retract`（渲染层把
    #: 膝/脚往髋部 lerp），压根不碰 `leg.fold` —— 只看 `fold_amount` 的话，
    #: 用户右键折叠八条腿，身体一个像素都不缩。覆盖层的「没派到词的腿收回去」
    #: 走的是 `leg.fold`，两条路互不干扰，取较大者即可。
    retract_fold: float = 0.0

    @property
    def fold_depth(self) -> float:
        """身体这一刻该缩多少：逐腿折叠与外部折叠取较大者。"""
        return max(self.body_fold, self.retract_fold)

    def __post_init__(self):
        scale = BASE_SCALE * self.size
        self.scale = scale
        #: 身体速度（局部单位/秒），用于落脚点前瞻
        self.velocity = (0.0, 0.0)
        self.legs = []
        stepper_no = 0
        for side in (1, -1):
            for slot, (ang, reach, hip) in enumerate(LEG_DEF):
                r = reach * scale
                aura = CS_HI if slot == 4 else LEG_AURA[stepper_no % 8]
                if slot < 4:
                    stepper_no += 1
                palp = (slot == 4)
                if palp:
                    # 触须：髋部搭在头部三角底边两侧（局部单位，不乘 scale，
                    # 理由见 `PALP_HIP_FWD` 的注释）。步足的 `hip` 字段照旧生效。
                    hip_x = HEAD_OFF + HEAD_TRI_LEN * PALP_HIP_FWD
                    hip_y = side * HEAD_TRI_HALF * PALP_HIP_SIDE
                else:
                    hip_x = hip * scale
                    hip_y = side * HIP_SIDE * scale
                self.legs.append(Leg(
                    index=len(self.legs),
                    side=side,
                    slot=slot,
                    ang=ang * side,
                    reach=r,
                    rest_r=r,
                    hip=hip_x,
                    hip_y=hip_y,
                    l1=r * L1_FRAC,
                    l2=r * L2_FRAC,
                    bend=(1 if slot in (3, 4) else -1) * side,
                    palp=palp,
                    aura=aura,
                ))
        # 身体点链用可变 list：head/abd/spin 不再是固定偏移，
        # update() 里做阻尼跟随，转弯时腹部会甩一下。
        #
        # **单位/坐标系**：这里是**随朝向旋转的体坐标系**（+x 就是「朝前」），
        # `SpiderPainter.to_screen()` 会再乘一次朝向矩阵，`hit_test()` 的
        # 「前段是头」也是按这个系的 +x 判的。所以三个点恒在 x 轴上，
        # 千万别在这里乘 cos/sin(heading) —— 那是二次旋转，身体胶囊会横过来。
        self.body = {
            "head": [HEAD_OFF * scale, 0.0],
            "p": [0.0, 0.0],
            "abd": [ABD_OFF * scale, 0.0],
            "spin": [(ABD_OFF + SPIN_OFF) * scale, 0.0],
        }
        # 模式切换时 spread 平滑过渡，避免八条腿集体抽筋
        self._spread_now = MODE_SPREAD.get(self.mode, 1.0)
        #: 待机姿势混合系数 0..1：0 = 走路站姿，1 = 徽章站姿（IDLE_POSE）
        self._idle_pose_t = 0.0
        # 角速度与倾斜：身体转弯时向内侧微倾
        self._prev_heading = self.heading
        self.heading_vel = 0.0
        self.lean = 0.0
        # 身体侧摆（垂直于朝向的偏移，局部单位）
        self.body_sway = 0.0
        # 身体反馈三件套（任务书 §9.2B/C，单位与含义见文件顶部那组常量）：
        #   · `body_bob`            走路时的轻微抬升（局部单位，>0 = 抬起）
        #   · `crouch` / `crouch_target`  起跳前的压低 0..1（目标由控制器给，这里缓动）
        #   · `landing_compression` 落地那一下的压缩冲量 0..1（无人再给就自己衰减）
        self.body_bob = 0.0
        self.crouch = 0.0
        self.crouch_target = 0.0
        self.landing_compression = 0.0
        # 步态相位：按身体移动距离推进，驱动异步行波
        self.gait_phase = 0.0
        self._move_dist = 0.0   # 本帧累计移动距离
        #: 腿长倍率。1.0 = 原始比例；瞄准时由 `AimOverlay` 临时调大（见
        #: `set_leg_stretch`），**退场必须调回 1.0**。
        self.leg_stretch = 1.0
        # 每条腿先在自己的静止位上落一只脚。
        # 少了这一步，初始偏离恒为 0，阈值步态永远不会启动
        # （crawler.js 里 L.foot 同样一开始就指向静止位）。
        for leg in self.legs:
            k = 1.0 if leg.palp else REST_K
            r = leg.reach * k
            leg.foot = (leg.hip + math.cos(leg.ang) * r,
                        leg.hip_y + math.sin(leg.ang) * r)
        # 迈步计数的**增量记账**起点（update() 里每帧维护，见 `_unstep`）。
        self._stepping_count = 0
        self._left_step = 0
        self._right_step = 0

    # ------------------------------------------------ 步态计数（增量）
    def _unstep(self, leg: Leg) -> None:
        """把一条**刚刚结束迈步**的腿从计数里扣掉。

        调用方必须保证 ``leg.stepping`` 这一刻是 True 且紧接着就置 False
        （迈步→落地/被瞄准接管/腾空收腿）。以前 `update()` 在每个会置
        stepping 的位置后全量重扫一遍 10 条腿（每帧最多 10 次 O(n) 扫描），
        现在改为：帧首扫一次拿基线，循环内只记增量。
        """
        self._stepping_count -= 1
        if not leg.palp:
            if leg.side == -1:
                self._left_step -= 1
            else:
                self._right_step -= 1

    # ------------------------------------------------ 几何
    def set_leg_stretch(self, factor: float) -> None:
        """整体缩放八条**步足**的腿长（触须不动），1.0 = 原始比例。

        为什么要有这个东西：识词时蜘蛛要踩的词散在一大片屏幕上，而腿的可达
        半径 = ``leg.full × unit``，只有 ~330px —— 再远的词就只亮框、不派腿，
        观感上是「蜘蛛够不着远一点的词」。

        为什么不是「放大整个蜘蛛」：把绘制用的 ``unit`` 调大是把**身子一起**
        等比放大，像素可达半径确实变大，可腿相对身体的比例没变，看着只是
        「一只更大的蜘蛛」。要的是**腿更长**（够得更远、也更像蛛形纲），
        只能动几何本身。

        为什么不在运行时直接改 ``LEG_DEF``：那是本体和瞄准层共用的常量，
        改了桌面小宠物也一起变长腿。而瞄准层偏偏**直接用 ``pet.spider``**
        （这样从桌面爬到词上这一路位置是连续的），所以只能做成**可逆**倍率：
        进场 ``×k``、退场 ``set_leg_stretch(1.0)``。

        ``rest_pos()`` 和 ``limit_to_reach()`` 每帧都读 ``leg.reach`` / ``leg.full``，
        所以改完立刻生效，不需要重建 ``Leg``、也不会打断迈步状态；
        脚仍钉在原地，会被新的静止圈「拽」着自然迈出去，看着就是腿在伸出去。
        """
        factor = max(0.1, min(5.0, float(factor)))
        if abs(factor - self.leg_stretch) < 1e-6:
            return
        for leg in self.legs:
            if leg.palp:
                continue                     # 触须保持原长，头部观感不变
            base = leg.rest_r if leg.rest_r > 0.0 else leg.reach
            leg.reach = base * factor
            leg.l1 = leg.reach * L1_FRAC
            leg.l2 = leg.reach * L2_FRAC
        self.leg_stretch = factor
        # ★ 腿一缩短，已经摆出去的脚尖要跟着夹回来。
        #   平时 `limit_to_reach` 是在 `update()` 里夹的，而覆盖层的腿长缓动
        #   （`AimOverlay._ease_stretch`）改 `full` 的时机在**模型推进之后**：
        #   那一帧画面上就有一条比自己的腿还长的腿（实测 1.0022×full）。
        #   0.2% 肉眼看不见，但「脚尖永不超过腿长」这条不变量不该有例外帧 ——
        #   一旦有例外，任何拿它做的检查都得先给误差让路。
        for leg in self.legs:
            if leg.palp:
                continue
            leg.tip = limit_to_reach(leg, leg.tip)

    def spread(self) -> float:
        return self._spread_now

    # ------------------------------------------------ 朝向/坐标系（唯一真相）
    def forward(self) -> tuple:
        """单位前向向量（**世界/屏幕坐标**）：局部 +x 在屏幕上指向哪儿。

        ★ 这是全项目**唯一**的「前方」定义。行走、跳跃、身体倾斜、腿部步态、
        目标接近点、命中区一律从这里取，不要在各自的动画里补零散的负号 ——
        历史上「屁股朝前」就是因为 heading 追的是 `-velocity`，而别处又按 +x 算。
        """
        return (math.cos(self.heading), math.sin(self.heading))

    def to_body(self, world_vec) -> tuple:
        """世界（屏幕）向量 → 体坐标系（乘 R(-heading)）。"""
        ch, sh = self.forward()
        return (world_vec[0] * ch + world_vec[1] * sh,
                -world_vec[0] * sh + world_vec[1] * ch)

    def to_world(self, body_vec) -> tuple:
        """体坐标向量 → 世界（屏幕）向量（乘 R(heading)）。

        与 `SpiderPainter.to_screen()` 的旋转部分完全一致（那个再多一个
        ×unit 与 +origin），所以「画出来的」和「算出来的」不会错位。
        """
        ch, sh = self.forward()
        return (body_vec[0] * ch - body_vec[1] * sh,
                body_vec[0] * sh + body_vec[1] * ch)

    def set_leg_assignment(self, assigned_indices=None, *, retract_unassigned: bool = False) -> None:
        """记录本批分配，不把未分配腿误当成用户折叠请求。

        `assigned_indices` 是 `Leg.index` 的集合；传 `None` 表示「没有覆盖层在
        管腿」，八条全部伸回。触须（palp）永远不参与：它们是探路的感觉器，
        收起来反而不像这只蜘蛛，而且现有折叠测试的判据都只针对步足。

        ``retract_unassigned`` 仅供需要旧式收腿效果的显式调用方使用；扫描默认
        保持未分配腿的自然待机/步态姿势。用户主动折叠由 PetWindow.set_folded()
        管理，不能通过分配状态间接触发。
        """
        want = None if assigned_indices is None else set(assigned_indices)
        for leg in self.legs:
            if leg.palp:
                continue
            if want is None:
                leg.assigned = True
                leg.fold_target = 0.0
            else:
                leg.assigned = leg.index in want
                leg.fold_target = (0.0 if leg.assigned or not retract_unassigned else 1.0)

    @property
    def fold_amount(self) -> float:
        """步足的平均折叠量 0..1：身体「收拢多少」跟着它走（见 §6 身体缩短）。"""
        steppers = [leg for leg in self.legs if not leg.palp]
        return sum(leg.fold for leg in steppers) / max(1, len(steppers))

    def folding(self) -> bool:
        """还有腿或身体正处在收/伸的过程中。

        给主循环的 `_busy()` 用：折叠动画是**没有事件源**的纯状态缓动，
        空闲降频态下如果把它当「静止」，`_tick()` 会一帧都不推进，
        用户看到的就是「腿收了但再也伸不回来」，要等鼠标碰一下才动。
        """
        if abs(self.body_fold - self.fold_amount) > 1e-3:
            return True
        return any(abs(leg.fold - leg.fold_target) > 1e-3 for leg in self.legs)

    def _advance_folds(self, dt: float) -> None:
        """把每条腿的 `fold` 朝 `fold_target` 缓动，再带动身体折叠量。"""
        k = damp(FOLD_DAMP, dt)
        for leg in self.legs:
            gap = leg.fold_target - leg.fold
            leg.fold = leg.fold_target if abs(gap) < 1e-4 else leg.fold + gap * k
        goal = self.fold_amount
        drift = goal - self.body_fold
        self.body_fold = goal if abs(drift) < 1e-4 else self.body_fold + drift * damp(
            BODY_FOLD_DAMP, dt)

    def rest_pos(self, leg: Leg) -> tuple:
        """脚在「静止站姿」下的位置（局部坐标，随身体一起走）。

        站定时（``_idle_pose_t`` → 1）按 ``IDLE_POSE`` 混合：八腿收拢到
        体轴两侧、沿纵轴拱起，摆成徽章站姿。走路时 ``_idle_pose_t`` = 0，
        这里和原来一模一样；所以行走/瞄准的落脚点计算完全不受姿势影响。
        """
        k = 1.0 if leg.palp else REST_K
        k *= self.spread()
        ang = leg.ang
        t = self._idle_pose_t
        if t > 1e-3 and not leg.palp:
            pose_ang, pose_k = IDLE_POSE[leg.slot]
            target = pose_ang * leg.side
            ang = leg.ang + (target - leg.ang) * t
            k *= 1.0 + (pose_k - 1.0) * t
        r = leg.reach * k
        return (leg.hip + math.cos(ang) * r,
                leg.hip_y + math.sin(ang) * r)

    def advance(self, dx: float, dy: float) -> None:
        """身体移动了 ``(dx, dy)`` —— **必须是体坐标系下的位移**（局部单位）。

        由 `update()` 负责先把世界位移乘 R(-heading) 旋进体坐标系再调这里。
        （它曾直接吃世界位移：朝向一转迈步方向就偏，配合当时反向的 heading
        插值，画面上就是整只蜘蛛倒着走。）

        脚是钉在原地的，所以局部坐标下脚必须反向平移 ——
        身体一动，脚相对静止位的偏移就增大，偏移够大才迈步
        （crawler.js 里脚的锚点是真实 DOM 元素，这里等价模拟）。

        注意这里**没有** crawler.js 那套「走远了就重定基」：
        原版要在世界坐标里累加，走远了浮点精度会掉；而这里脚只以
        局部坐标（世界 − 身体）存储，重定基在数学上是恒等变换。
        早先照搬过来的那一版会在阈值触发时把八只脚同时推成两倍偏移，
        脚被拖到腿长的两三倍外，画出来就是一条条「射线」。
        """
        if dx == 0.0 and dy == 0.0:
            return
        for leg in self.legs:
            for attr in ("foot", "nxt", "frm"):
                point = getattr(leg, attr)
                if point:
                    setattr(leg, attr, (point[0] - dx, point[1] - dy))

    def turn(self, delta: float) -> None:
        """身体在世界里**自转**了 ``delta`` 弧度（绕体心）。

        和 `advance()` 是同一件事的另一个分量：脚钉在世界坐标上，
        体坐标系跟着 `heading` 转，于是脚在体坐标系里要**反向**转 ``-delta``。
        少了这一步，原地转身时脚和静止位一起转、相对偏移恒为 0，
        阈值步态永远不触发 —— 整只蜘蛛就变成一张被刚体旋转的图片，
        腿一步都不迈（这正是「转身动画」原本难看的原因）。

        别写成 `+delta`：那是把脚再顺着转一次，偏差翻倍，
        腿会被甩到极限位置疯狂回缩。
        """
        if delta == 0.0:
            return
        c, s = math.cos(-delta), math.sin(-delta)
        for leg in self.legs:
            for attr in ("foot", "nxt", "frm"):
                point = getattr(leg, attr)
                if point:
                    setattr(leg, attr, (point[0] * c - point[1] * s,
                                        point[0] * s + point[1] * c))

    def foot_now(self, leg: Leg) -> tuple:
        """脚当前的位置：迈步中走插值，否则用已落地点或静止点。

        返回值一律夹到 `REACH_LIMIT_FRAC × 腿长` 之内。这一个夹子很关键：
        脚「钉在世界上」，身体走快了（或迈步途中身体继续前移）局部距离就被拉大，
        而 `solve_ik` 只管膝盖、不管脚尖 —— 不夹的话脚尖会飞出腿长之外，
        屏幕上就是一条越过膝盖、直直拖出去的腿。走步态时这甚至只是**偶发**的
        （大约一半的随机步长会超过 1.02×），肉眼很难定位。
        """
        if leg.stepping and leg.frm and leg.nxt:
            e = smoothstep(leg.t)
            fx = leg.frm[0] + (leg.nxt[0] - leg.frm[0]) * e
            fy = leg.frm[1] + (leg.nxt[1] - leg.frm[1]) * e
            # 抬起：往髋部收。幅度随速度与腿位变化 ——
            # 跑得快抬得高，前腿（slot 小）比后腿抬得稍高，
            # 触须几乎不抬（它本来就短，抬了也看不见）。
            sp = math.hypot(*self.velocity)
            speed_k = clamp(0.5 + sp / 160.0, 0.4, 1.7)
            leg_k = 1.0 if leg.palp else (1.0 + (3 - leg.slot) * 0.07)
            lift = math.sin(math.pi * leg.t) * 0.18 * speed_k * leg_k
            hx, hy = leg.hip_pos
            fx += (hx - fx) * lift
            fy += (hy - fy) * lift
            return limit_to_reach(leg, (fx, fy))
        return limit_to_reach(leg, leg.foot if leg.foot else self.rest_pos(leg))

    @staticmethod
    def solve_ik(hip, foot, l1: float, l2: float, bend: int) -> tuple:
        """两骨 IK（crawler.js `ik()`）。目标超出腿长时整条腿伸直。

        `bend` 允许传 ±1 之间的**连续值**（待机拱形的换边过渡用）：
        0 = 完全伸直，符号 = 膝盖凸向哪一侧。
        """
        dx, dy = foot[0] - hip[0], foot[1] - hip[1]
        d = math.hypot(dx, dy)
        base = math.atan2(dy, dx)
        if d >= l1 + l2 - 0.01:
            return (hip[0] + math.cos(base) * l1, hip[1] + math.sin(base) * l1)
        c = clamp((l1 * l1 + d * d - l2 * l2) / (2 * l1 * max(d, 1e-6)), -1.0, 1.0)
        b = base + bend * math.acos(c)
        return (hip[0] + math.cos(b) * l1, hip[1] + math.sin(b) * l1)

    @staticmethod
    def _bend_now(leg: Leg) -> float:
        """本帧的等效弯曲量：走路 = leg.bend；徽章站姿 = 反侧（arch=1）。"""
        return leg.bend * (1.0 - 2.0 * leg.arch)

    # ------------------------------------------------ 步态
    def _neighbour_stepping(self, leg: Leg) -> bool:
        return any(o.stepping and o.side == leg.side
                   and abs(o.slot - leg.slot) == 1 for o in self.legs)

    def _step_target(self, leg: Leg) -> tuple:
        """新落脚点：**静止位 + 速度前瞻**（对齐 crawler.js 的 stepTarget）。

        `self.velocity` 现在是**体坐标系**下的身体速度（见 `update()`：世界位移
        先乘 R(-heading)）。前瞻就是把脚放到「身体接下来要去的方向」上，
        所以这里是 **加**：`rest + velocity * lead`。

        摆腿结束的瞬间脚正好落在静止位上：身体继续往前，钉住的脚在局部坐标里
        逆着身体漂移，回到静止位附近。

        历史坑（别再翻回去）：
        · crawler.js 把脚存在**世界坐标**里，`restPos` 是世界点，所以它写
          `restPos + v * lead`；
        · 本项目的脚存**局部坐标**，早先为了对上原版把它写成 `rest - v * lead`，
          而那时 `v = -世界位移/dt` 又是世界方向 —— 两个负号抵消，在 heading=0
          时恰好正确；
        · 一旦朝向不是 0（走路时朝向会跟着目标转），那套写法就把前瞻留在了
          错误的一侧，而且 heading 本身也追反了。现在朝向、位移、前瞻用同一个
          体坐标系，符号就是上面这一种。
        """
        hx, hy = leg.hip_pos
        rx, ry = self.rest_pos(leg)

        # 速度前瞻，最多 reach 的 LEAD_MAX_FRAC
        vx, vy = self.velocity
        lx = rx + vx * LEAD_SECONDS
        ly = ry + vy * LEAD_SECONDS
        ahead = math.hypot(lx - rx, ly - ry)
        if ahead > leg.reach * LEAD_MAX_FRAC:
            k = (leg.reach * LEAD_MAX_FRAC) / ahead
            lx, ly = rx + (lx - rx) * k, ry + (ly - ry) * k

        # 落脚点永不超出腿长的 PLACE_FRAC
        tx, ty = hx + (lx - hx), hy + (ly - hy)
        d = math.hypot(tx - hx, ty - hy)
        limit = leg.full * PLACE_FRAC
        if d > limit and d > 1e-6:
            tx, ty = hx + (tx - hx) / d * limit, hy + (ty - hy) / d * limit
        return (tx, ty)

    def _start_step(self, leg: Leg, quick: bool) -> None:
        leg.frm = self.foot_now(leg)
        leg.nxt = self._step_target(leg)
        lo, hi = STEP_DUR_QUICK if quick else STEP_DUR
        base = lo + random.random() * (hi - lo)
        # 迈步距离越远花的时间越长，避免短腿"磨蹭"、长腿"甩飞"。
        # 距离因子幅度要压过随机基数（base 0.10~0.17 比值 1.7），
        # 否则远近步的时长差异会被随机性淹没。
        d = math.hypot(leg.nxt[0] - leg.frm[0], leg.nxt[1] - leg.frm[1])
        dist_k = 0.5 + 1.3 * (d / max(leg.reach, 1.0))
        leg.dur = clamp(base * dist_k, 0.06, 0.36)
        leg.t = 0.0
        leg.stepping = True
        leg.quick = quick

    def _plant(self, leg: Leg) -> None:
        leg.foot = leg.nxt
        leg.stepping = False
        leg.t = 0.0

    def update(self, dt: float, mode: str = None, speed: float = None,
               motion=(0.0, 0.0)) -> None:
        """推进一步。

        ``motion`` 是本帧身体在世界里的位移；``targets`` 里有值的腿
        不参与步态，直接踩住目标点。
        """
        if mode:
            self.mode = mode
        if motion != (0.0, 0.0):
            # ★ 两套坐标系必须在这里分清：调用方传进来的 `motion` 是**世界（屏幕）
            # 位移**（已经除过 unit，但方向还是屏幕方向），而脚、静止位、髋部全活在
            # **随 heading 旋转的体坐标系**里。所以先把它旋进体坐标系（乘 R(-heading)）
            # 再喂 `advance()`。
            #
            # 历史坑（2026-10-18 修）：这里曾直接把世界位移当体坐标位移减掉，
            # 同时 heading 又去追 `atan2(-motion)`（见下一段注释），两个错误各自
            # 「看起来自洽」，合起来的结果是**蜘蛛永远倒着走**——用户看到的
            # 「屁股在前、头在后」。现在朝向追世界运动方向，位移旋进体系，
            # `advance`/`turn`/`_step_target` 三处用的是同一个体坐标系。
            local = self.to_body(motion)
            self.advance(local[0], local[1])
            # 身体速度：**体坐标系**下的速度（局部单位/秒），用于落脚点前瞻与抬腿幅度。
            # 模长与世界速度相同（旋转保长度），所以 `speed` 的口径没有变。
            inv = 1.0 / max(dt, 1e-4)
            want = (local[0] * inv, local[1] * inv)
            vf = damp(VELOCITY_DAMP, dt)
            self.velocity = (self.velocity[0] + (want[0] - self.velocity[0]) * vf,
                             self.velocity[1] + (want[1] - self.velocity[1]) * vf)
            self._move_dist = math.hypot(local[0], local[1])
            # 朝向跟随**世界**运动方向：局部 +x 就是「朝前」= 头的方向，
            # 所以头部永远领路（任务三）。静止时保持上一次朝向，站定不会自己乱转。
            sp = math.hypot(*self.velocity)
            if sp > HEADING_MIN_SPEED:
                target = math.atan2(motion[1], motion[0])
                delta = target - self.heading
                while delta > math.pi:
                    delta -= 2 * math.pi
                while delta < -math.pi:
                    delta += 2 * math.pi
                turn = damp(4.0 + sp * 0.02, dt)
                self.heading += delta * turn
        else:
            self._move_dist = 0.0
            # 身体停下来了，速度**必须**跟着衰减到 0。
            # 不衰减的话 `self.speed = |velocity|` 会永远停在最后一帧的值：
            # `_step_target` 的前瞻 `rest - v * LEAD_SECONDS` 会一直把落脚点
            # 放在偏离静止位的位置，脚一落地就被判成「偏得远」→ 再迈一次
            # 却还是落在同一个点（步长为 0，时长只有 0.07s）→ 原地每秒抖
            # 十几次。表现就是「待机时脚一直在抽」，正是要避免的观感。
            vf = damp(VELOCITY_DAMP, dt)
            self.velocity = (self.velocity[0] * (1.0 - vf),
                             self.velocity[1] * (1.0 - vf))

        # 速度直接由 velocity 算出，不再依赖外部传入的 speed（拖动时那是写死的 140）
        self.speed = math.hypot(*self.velocity)

        # 逐腿折叠缓动（谁这一批没派到词，谁往髋部收）。放在迈步判定之前，
        # 这样「正在收回」和「正在迈步」两件事在同一帧里看到的是同一个 fold。
        self._advance_folds(dt)

        # 模式切换时 spread 平滑过渡：从 jump(0.4) 回 idle(1.0) 时腿慢慢张开，
        # 而不是一瞬间八条静止位全跳开、集体触发迈步。
        target_spread = MODE_SPREAD.get(self.mode, 1.0)
        self._spread_now += (target_spread - self._spread_now) * damp(SPREAD_DAMP, dt)

        # 角速度 + 转弯倾斜：身体向内侧微倾，模拟离心力
        hdelta = self.heading - self._prev_heading
        while hdelta > math.pi:
            hdelta -= 2 * math.pi
        while hdelta < -math.pi:
            hdelta += 2 * math.pi
        self.heading_vel = hdelta / max(dt, 1e-4)
        target_lean = clamp(self.heading_vel * TURN_LEAN_K, -LEAN_MAX, LEAN_MAX)
        self.lean += (target_lean - self.lean) * damp(10.0, dt)
        self._prev_heading = self.heading

        # 待机姿势混合：站定（慢且不自转）→ 淡入徽章站姿；一动/一转就淡出。
        # rest/jump 不参与 —— rest 有自己的收腿 spread，jump 腾空无站姿。
        pose_on = (self.mode in ("idle", "crawl", "think")
                   and self.speed < IDLE_POSE_SPEED
                   and abs(self.heading_vel) < IDLE_POSE_TURN)
        self._idle_pose_t += ((1.0 if pose_on else 0.0) - self._idle_pose_t) \
            * damp(IDLE_POSE_DAMP, dt)
        # 脚钉在世界上：身体转了多少，脚在体坐标系里就反向转多少。
        # 必须在迈步判定**之前**做，这一帧的偏差里才含得上刚才转过去的量。
        # `hdelta` 已经囊括了两种来源 —— 速度朝向插值（走位时）和
        # pet_window 直接改 heading（转身效果时）。
        self.turn(hdelta)

        # 身体点链（head / abd / spin）阻尼跟随。
        #
        # **坐标系**：这些点活在**随朝向旋转的体坐标系**里（+x = 朝前）——
        # `SpiderPainter.to_screen()` 会再乘一次朝向矩阵，`hit_test()` 的
        # 「前段是头」也是按 +x 判的。所以目标点恒为 `(偏移, 0)`，
        # **绝不能乘 cos/sin(heading)**：那是二次旋转，身体胶囊会横过来，
        # 头胸矩形的四个角立刻落到胶囊外 —— 表现就是「腿能点中、身体点不中」。
        #
        # 想要 crawler.js 那种「转弯时腹部甩一下」，靠的是把上一帧的点按
        # **朝向变化量反向旋转**（等价于「点在世界上不动、身体转过去」），
        # 再阻尼回目标。于是体坐标系里自然出现滞后甩尾 ≈ heading_vel / k。
        scale = self.scale
        if hdelta:
            _c, _s = math.cos(-hdelta), math.sin(-hdelta)
            for key in ("head", "abd", "spin"):
                _bx, _by = self.body[key]
                self.body[key] = [_bx * _c - _by * _s, _bx * _s + _by * _c]
        self.body["head"] = list(damp_pt(self.body["head"],
                                         (HEAD_OFF * scale, 0.0), 16.0, dt))
        self.body["abd"] = list(damp_pt(self.body["abd"],
                                        (ABD_OFF * scale, 0.0), ABD_DAMP, dt))
        self.body["spin"] = list(damp_pt(self.body["spin"],
                                         ((ABD_OFF + SPIN_OFF) * scale, 0.0),
                                         SPIN_DAMP, dt))

        # 步态相位：平移 + 自转都推，驱动异步行波。
        # 只算平移的话，原地转身时相位是冻结的，窗口外的腿全靠 PHASE_RELIEF
        # 兜底才迈得出去，行波就没了 —— 转身看着像八条腿各迈各的。
        self.gait_phase = (self.gait_phase
                           + self._move_dist * GAIT_PHASE_PER_UNIT
                           + abs(hdelta) * GAIT_PHASE_PER_RAD) % 1.0

        # 同时迈步上限的计数走**增量维护**（`self._stepping_count`，
        # 上一帧帧尾扫出的基线；循环里 `_start_step` / `_unstep` 负责增减），
        # 不再在每个能改 stepping 的位置后全量重扫。
        stepping_count = self._stepping_count
        max_stepping = (MAX_STEPPING_FAST if self.speed > STEP_SPEED_FAST
                        else MAX_STEPPING_SLOW)

        for leg in self.legs:
            # 迈步→停步的过渡检测（增量计数的扣减依据，见帧尾说明）
            was_stepping = leg.stepping
            # 拱形换边：站定且这只脚已落进徽章静止位 → 膝盖缓慢翻向体外；
            # 一旦迈步/瞄准/起跳/姿势淡出就翻回来。迈步中的腿不翻（落地后再翻），
            # 于是八条腿跟着各自的落步节奏逐条「重新架腿」，不会集体弹一下。
            goal = self.targets.get(leg.index)
            arch_want = (goal is None and not leg.palp and not leg.stepping
                         and IDLE_POSE_ARCH[leg.slot]
                         and self.mode != "jump" and self._idle_pose_t > 0.98)
            leg.arch += ((1.0 if arch_want else 0.0) - leg.arch) * damp(ARCH_DAMP, dt)

            # 瞄准：脚尖**平滑靠近**目标，而不是瞬间瞬移过去。
            if goal is not None:
                if leg.target_now is None:
                    leg.target_now = leg.tip
                rate = damp(TARGET_APPROACH_K, dt)
                leg.target_now = (leg.target_now[0] + (goal[0] - leg.target_now[0]) * rate,
                                  leg.target_now[1] + (goal[1] - leg.target_now[1]) * rate)
                if math.hypot(goal[0] - leg.target_now[0],
                              goal[1] - leg.target_now[1]) < TARGET_EPS:
                    leg.target_now = goal
                if was_stepping:
                    leg.stepping = False
                    self._unstep(leg)
                else:
                    leg.stepping = False
                # 目标点也要夹到腿长之内：分配阶段已经按可达性筛过，但
                # 「可达」判的是 `full * max_frac`，而这里还要留出膝盖弯曲的余量，
                # 不夹的话最远那条腿的膝盖会被解算成一条笔直的射线。
                leg.tip = limit_to_reach(leg, leg.target_now)
                leg.knee = self.solve_ik(leg.hip_pos, leg.tip, leg.l1, leg.l2,
                                         self._bend_now(leg))
                continue

            leg.target_now = None
            leg.target_goal = None

            if self.mode == "jump":
                # 腾空：腿收拢，跟着身体走，不做任何迈步判定。
                if was_stepping:
                    self._unstep(leg)
                leg.stepping = False
                leg.t = 0.0
                leg.nxt = None
                leg.frm = None
                foot = self.rest_pos(leg)
                leg.foot = foot
                leg.tip = foot
                leg.knee = self.solve_ik(leg.hip_pos, foot, leg.l1, leg.l2,
                                         self._bend_now(leg))
                continue

            if leg.stepping:
                leg.t += dt / max(leg.dur, 1e-6)
                if leg.t >= 1.0:
                    self._plant(leg)
                    if was_stepping:
                        # 本帧发生了「迈步→落地」，从增量计数里扣掉。
                        self._unstep(leg)
            else:
                rest = self.rest_pos(leg)
                current = leg.foot if leg.foot else rest
                off = math.hypot(current[0] - rest[0], current[1] - rest[1])
                hx, hy = leg.hip_pos
                reach_here = math.hypot(current[0] - hx, current[1] - hy)
                over = reach_here > leg.full * OVER_FRAC
                urgent = off > leg.reach * URGENT_FRAC
                thresh = leg.reach * (0.25 if leg.palp else STEP_FRAC)

                # 姿势落位：待机姿势淡入期间，静止位在缓慢移动，脚要跟着挪。
                # 这时 gait_phase 是冻结的（既不平移也不自转），相位窗口外的腿
                # 会被卡死 —— 前足要挪 ~50 个局部单位，恰好卡在 STEP_FRAC 阈值
                # 上下，不放宽的话姿势永远只能摆一半。所以落位期间：
                # 阈值降到 0.10×reach（小步快挪），且不卡相位窗口。
                # 脚步一旦落进新静止位阈值内就停，不会无休止抽（IDLE_TWITCH 仍关）。
                settling = (not leg.palp and self._idle_pose_t > 0.02
                            and self.speed < IDLE_POSE_SPEED
                            and abs(self.heading_vel) < IDLE_POSE_TURN)
                if settling:
                    thresh = leg.reach * 0.05

                # 异步行波：步足只在自己的相位窗口内才允许迈步（触须不受限）。
                # 右腿相位 = gait_phase + LEG_PHASE[slot]，左腿偏移半周期。
                in_phase = True
                if not leg.palp and not settling:
                    lp = (self.gait_phase + (0.5 if leg.side == -1 else 0.0)
                          + LEG_PHASE[leg.slot]) % 1.0
                    in_phase = lp < GAIT_WINDOW or lp > 1.0 - GAIT_WINDOW

                if over:
                    # 硬危险（脚已经被拖到腿长边缘）**必须立刻回缩，允许打断邻居**。
                    # 这里不能再加 `not self._neighbour_stepping(leg)`：加了以后
                    # 两条相邻腿会互相谦让，谁也迈不出去，脚贴在硬上限上被一路
                    # 拖着走 —— 实测 165 px/s 时 "over 帧占比" 从 2.8% 涨到 15.3%，
                    # 320 px/s 时从 7.2% 涨到 55%，画面上就是一块被拉长的腿。
                    # 步长最多 0.34s，抢一步不会把画面搅乱；被拖长才会。
                    self._start_step(leg, True)
                elif urgent and not self._neighbour_stepping(leg):
                    # 偏得远：仍守同侧协调，但放宽相位窗口（先迈再说）
                    self._start_step(leg, True)
                elif off > thresh and stepping_count < max_stepping \
                        and not self._neighbour_stepping(leg) and in_phase:
                    self._start_step(leg, False)
                elif off > thresh * PHASE_RELIEF and stepping_count < max_stepping \
                        and not self._neighbour_stepping(leg):
                    # 相位窗口外的兜底：异步行波只是**排班偏好**，不能变成硬闸门。
                    # 一条腿错过窗口后要么等一个整周期（1.66s，够被拖出腿长），
                    # 要么直接掉进 over —— 所以偏出常规阈值 1.5 倍就让它先迈。
                    self._start_step(leg, False)
                elif self.speed < 6.0 and random.random() < dt * IDLE_TWITCH_RATE \
                        and not self._neighbour_stepping(leg):
                    # 闲置抽动：站定时偶尔抬一下脚，对齐 crawler.js 的 idle twitch
                    self._start_step(leg, False)

            foot = self.foot_now(leg)
            leg.tip = foot
            leg.knee = self.solve_ik(leg.hip_pos, foot, leg.l1, leg.l2,
                                     self._bend_now(leg))

        # 帧内迈步/落地的过渡都用 `was_stepping` + `_unstep` 增量维护
        # （以前每个能改 stepping 的位置后都要全量重扫 10 条腿，每帧最多十来遍）。
        # 帧尾这里再**全量扫一次**：它既算出本帧的侧摆计数，也是下一帧
        # `stepping_count` 的起点 —— 增量若有任何对不上，这一扫就是自愈点。
        self._stepping_count = sum(1 for L in self.legs if L.stepping)
        self._left_step = sum(1 for L in self.legs
                              if L.stepping and L.side == -1 and not L.palp)
        self._right_step = sum(1 for L in self.legs
                               if L.stepping and L.side == 1 and not L.palp)
        target_sway = (self._right_step - self._left_step) * SWAY_PER_LEG * scale
        self.body_sway += (target_sway - self.body_sway) * damp(14.0, dt)

        # ── 身体反馈（§9.2B/C）：走路起伏 / 起跳蓄力 / 落地压缩 ──────────────
        # 起伏的来源是「此刻有几条腿正抬着、各抬到多少」，不是独立振荡器，
        # 所以身体抬起的最高点必然落在换脚的那一拍上。腾空时八条腿都收在静止位
        # （`mode == "jump"` 那一支不做迈步），抬升量自然归零，不需要特判。
        lift = 0.0
        for L in self.legs:
            if L.stepping and not L.palp:
                lift += math.sin(math.pi * clamp(L.t, 0.0, 1.0))
        target_bob = min(BOB_MAX, lift * BOB_PER_LEG) * scale
        self.body_bob += (target_bob - self.body_bob) * damp(BOB_RATE, dt)
        # 蓄力：往 `crouch_target` 缓动（控制器在准备段持续给 1，起跳瞬间撤 0，
        # 于是「压到底 → 弹开」；0.16s 的准备段配 30 的系数刚好压满）。
        self.crouch += (self.crouch_target - self.crouch) * damp(CROUCH_RATE, dt)
        # 落地压缩：无人再给冲量就自己回到 0（`damp` 是指数衰减 = 回弹）。
        self.landing_compression += (0.0 - self.landing_compression) \
            * damp(COMPRESSION_RATE, dt)

    def place_targets(self, points) -> None:
        """把局部坐标下的目标点绑到步足上（不绑触须）。"""
        self.targets = {}
        steppers = [L for L in self.legs if not L.palp]
        for leg, point in zip(steppers, list(points)[:8]):
            self.targets[leg.index] = point

    def clear_targets(self) -> None:
        self.targets = {}
        for leg in self.legs:
            leg.target_goal = None
            leg.target_now = None
            leg.stepping = False

    # ------------------------------------------------ 命中测试

    #: 命中判定的容差（局部单位）。矩形四角正好落在边界上，`lean` 一反旋
    #: 就会有 1e-16 级的浮点误差把它判到外面；顺手也给「手没那么准」留点余量
    #: —— 1 局部单位 ≈ 1.2px，远小于那圈柔光半径，不会把柔光也算成实体。
    HIT_PAD = 1.0

    def _leg_point(self, local_point) -> tuple:
        """腿用的点：只反平移一个侧摆。

        painter 给「身体 + 所有髋部」加了 `body_sway` 的侧摆平移，所以要减掉。
        **不能顺手把 `lean` 也反旋掉** —— 转弯倾斜只作用于头胸矩形和三角，
        腿是照 heading 画的（`_paint_legs` 里没有 lean）。反旋错了，
        转弯时（LEAN_MAX=0.16rad，腿上 130 单位处 ≈ 20 单位 ≈ 25px）腿就点不中了。

        髋部那端其实还差一个 `sway`（画家只给髋加了侧摆、膝/脚尖没有），
        但 sway 最多 `SWAY_PER_LEG*2 = 3.2` 局部单位，远小于判定用的
        `HIT_LEG_PAD_PX/unit ≈ 4.9`，容差能盖住。
        """
        return (local_point[0], local_point[1] - self.body_sway)

    def _body_point(self, local_point) -> tuple:
        """身体（矩形 + 三角）自坐标系：反平移侧摆，再反旋转一个 `lean`。

        这块是 painter 里唯一跟着 `lean` 一起转的东西。
        """
        lx, ly = self._leg_point(local_point)
        if self.lean:
            c, s = math.cos(-self.lean), math.sin(-self.lean)
            lx, ly = lx * c - ly * s, lx * s + ly * c
        return (lx, ly)

    def _in_thorax(self, point, pad: float = None) -> bool:
        """点是否落在头胸（身体）内。`body_scale > 1` 时包含放大出来的肚子。

        ★ 放大出来的那一段必须用**椭圆**判，不能拿矩形一直铺到底：
          素材是个圆肚子，矩形四角（比如后缘 x=-110、y=±23 那个角）是**全透明**的。
          用矩形的话，收腿后 leg2/leg7 的脚尖正好落在这个透明角里 ——
          `test_fold` 的「看不见却点得中」断言当场就抓到了（alpha=0 却吃点击）。
          椭圆与基础矩形在后缘**相切**，视觉上就是「圆角矩形的后半拉长」，不会突兀。

        ★ 2026-10-19：折叠改成**朝头部等比缩小**（`BODY_FOLD_SHRINK`）。
          渲染链是 `_folded_body_rect()` → `_body_draw_rect()`，两步都锚在
          前缘（朝头那侧），所以合成结果就是「以 x1 为不动点、整体缩
          `(1-BODY_FOLD_SHRINK×fold)×body_scale` 倍」。判定这里照同一个式子
          算一遍，宽、高都要缩 —— 只缩宽度的话，折起来那半截会变成
          「摸得到但看不见 / 看得见却摸不到」。
        """
        pad = self.HIT_PAD if pad is None else pad
        lx, ly = point
        ts = THORAX_SCALE
        scale = max(1.0, float(self.body_scale))
        fold = max(0.0, min(1.0, self.fold_depth))
        # 折叠倍率：1 = 原尺寸，1-0.22 = 全折叠时缩到 78%
        keep = 1.0 - BODY_FOLD_SHRINK * fold
        x1 = (THORAX[0] + THORAX[2]) * ts          # 前缘：头和它都不动
        base_w = THORAX[2] * ts * keep             # 折叠后的基础矩形宽度
        base_x0 = x1 - base_w
        # ★ 高度只跟**折叠**缩，不乘 `body_scale`：`body_scale` 那套放大是
        #   「图皮肚子看着太小、放大一圈」的观感修正，命中区一直是纯几何，
        #   乘进去会让白蛛的判定框凭空长高一截（不是本次要改的事）。
        h = THORAX[3] * ts * keep
        y0, y1 = -h / 2.0, h / 2.0
        grow = THORAX[2] * ts * keep * max(0.0, scale - 1.0)

        if lx >= base_x0 - pad:
            return (base_x0 - pad <= lx <= x1 + pad
                    and y0 - pad <= ly <= y1 + pad)

        # 放大段：从基础矩形后缘一直包到肚尾的椭圆（其最宽处正好与矩形后缘同宽）
        if grow <= 0.0:
            return False
        rear = base_x0 - grow
        a = (x1 - rear) / 2.0
        b = (y1 - y0) / 2.0
        cx = (rear + x1) / 2.0
        ny = (ly - 0.0) / (b + pad)
        nx = (lx - cx) / (a + pad)
        return nx * nx + ny * ny <= 1.0

    def _in_head_tri(self, point, pad: float = None) -> bool:
        """点是否落在头部三角形内（底边在 x = HEAD_OFF，顶点朝 +x）。

        **容差必须换算成真实距离**：叉积的大小是边长倍的面积量，
        直接拿 `pad` 去比（老写法）等于把 1 局部单位的容差缩成
        `1 / 边长 ≈ 0.05` 单位 ≈ **0.06px** —— 顶点、三条边上的点一取整就判到外面，
        表现就是「戳三角尖经常没反应」。所以每条边的叉积都除掉边长再比。
        """
        pad = self.HIT_PAD if pad is None else pad
        lx, ly = point
        tri = ((HEAD_OFF, -HEAD_TRI_HALF),
               (HEAD_OFF + HEAD_TRI_LEN, 0.0),
               (HEAD_OFF, HEAD_TRI_HALF))
        for i in range(3):
            ax, ay = tri[i]
            bx, by = tri[(i + 1) % 3]
            ex, ey = bx - ax, by - ay
            length = math.hypot(ex, ey) or 1.0
            # 叉积 / 边长 = 点到这条边所在直线的**带符号垂直距离**。
            # 三角形的绕向是固定的，所以「在里面」= 三个距离都 ≥ -pad。
            if (ex * (ly - ay) - ey * (lx - ax)) / length < -pad:
                return False
        return True

    def hit_test(self, local_point) -> str:
        """点的语义：``"head"`` = 三角头（识词），``"body"`` = 矩形身（拖动）。

        **判定框必须就是画出来的那两个形状本身**，不能再用拍脑袋的矩形：
        以前是「x > 4 且 |y| < 14 算头」，那既盖住了大半个头胸矩形
        （点肚子会误触发识词），又伸到三角形外面（戳空白也算头）。
        顺序也有讲究 —— 三角底边是压在矩形前沿上的，重叠区判给「头」。
        """
        point = self._body_point(local_point)
        if self._in_head_tri(point):
            return "head"
        if self._in_thorax(point):
            return "body"
        return None

    def covers(self, local_point, leg_pad: float = 0.0,
               body_pad: float = None) -> bool:
        """点是否落在**画出来的东西**上（头胸矩形 ∪ 头部三角 ∪ 十条腿的线段）。

        用途不是「点没点中头」，而是给窗口的鼠标命中测试用：
        窗口是逐像素透明的，Windows 会把 alpha=0 的像素当「不存在」自动穿透，
        但蜘蛛周围那圈柔光 alpha 只有 1~8，照样会吃掉点击。所以要在
        `WM_NCHITTEST` 里按真实轮廓回一个 HTTRANSPARENT
        —— 这样既不用每帧改窗口区域（那是拖动卡顿的根源），
        判定又是**事件发生时实时算**的，永远和画面一致。

        `leg_pad` 由调用方按屏幕像素折算成局部单位传进来。

        **身体后面不再有「胶囊」**：腹部/纺器那条尾巴已经从画面上删掉了，
        判定也必须跟着删 —— 否则会在空白处留下一块能点中、却看不见的方块。

        两条路径用的坐标系不一样，这是故意的：
        矩形/三角跟着 `heading + lean` 转（`_body_point`），腿只跟 `heading`
        （`_leg_point`）。混用会让转弯时的腿判定偏出二十几个单位。

        `leg_pad` / `body_pad` 都由调用方按**屏幕像素**折算成局部单位传进来
        （见 `PetWindow._on_spider`）：弹出/压扁这类一次性形变会把局部单位缩得
        很小，容差写死在局部坐标里的话，那时就只剩零点几像素，一取整就判不中。
        """
        body = self._body_point(local_point)
        if self._in_thorax(body, body_pad) or self._in_head_tri(body, body_pad):
            return True
        if leg_pad <= 0.0:
            return False
        point = self._leg_point(local_point)
        for leg in self.legs:
            if point_segment_distance(point, leg.hip_pos, leg.knee) <= leg_pad:
                return True
            if point_segment_distance(point, leg.knee, leg.tip) <= leg_pad:
                return True
        return False


# ---------------------------------------------------------------- 腿↔词分配

#: 代价权重：角度与交叉刻意压过距离，否则八个词挤在一起时
#: 所有腿会朝同一个方向扑过去、互相穿插成一团。
_W_ANGLE = 1.8
_W_UNREACHABLE = 2.0
_W_CROSS = 1.2

#: `assign_reachable()` 里「够不着」格子的哨兵成本。必须是**有限**的大数：
#: 匈牙利解法器内部用 `float("inf")` 做松弛，输入里混进 inf 会算出 nan。
#: 取 1e9 远大于任何真实成本（量级 ~10²），最优解不会去碰这些格子。
_UNREACHABLE_SENTINEL = 1e9


def _cross(a1, a2, b1, b2) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1, d2 = orient(a1, a2, b1), orient(a1, a2, b2)
    d3, d4 = orient(b1, b2, a1), orient(b1, b2, a2)
    return ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
           ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0))


def _segments_cross(a1, a2, b1, b2) -> bool:
    return _cross(a1, a2, b1, b2)


def _leg_cost(leg: Leg, target: Target, preferred: float, maximum: float) -> float:
    hx, hy = leg.hip_pos
    dx, dy = target.center[0] - hx, target.center[1] - hy
    dist = math.hypot(dx, dy)

    deviation = abs(math.atan2(dy, dx) - leg.ang)
    while deviation > math.pi:
        deviation = abs(deviation - 2 * math.pi)

    penalty = 0.0 if dist <= preferred else (
        (dist - preferred) / max(maximum - preferred, 1.0))
    return (dist
            + _W_ANGLE * deviation * preferred
            + _W_UNREACHABLE * ((1.0 if dist > maximum else 0.0) + penalty) * maximum)


def solve_hungarian(cost):
    """匈牙利算法（O(n³)）。输入方阵 cost[i][j]，返回 assignment[i] = j。"""
    n = len(cost)
    if n == 0:
        return []
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta, j1 = inf, 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignment = [-1] * n
    for j in range(1, n + 1):
        if p[j] > 0:
            assignment[p[j] - 1] = j - 1
    return assignment


def assign_legs(legs, targets, preferred: float, maximum: float):
    """腿 ↔ 词的最小成本分配，最多 8 对。返回 ``[{leg, target, cost}]``。"""
    n = min(len(legs), len(targets), 8)
    if n == 0:
        return []

    cost = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            value = _leg_cost(legs[i], targets[j], preferred, maximum)
            for k in range(n):
                if k == j:
                    continue
                if _segments_cross(legs[i].hip_pos, targets[j].center,
                                   legs[(i + 1) % n].hip_pos, targets[k].center):
                    value += _W_CROSS * preferred
            cost[i][j] = value

    mapping = solve_hungarian(cost)
    return [{"leg": i, "target": j, "cost": cost[i][j]}
            for i, j in enumerate(mapping) if j >= 0]


def assign_reachable(legs, targets, unit: float = 1.0, max_frac: float = 0.92):
    """**只给够得着的词**分配腿（可达性约束 + 贪心）。

    为什么不能用匈牙利硬分：桌面上被框出来的词往往离蜘蛛几百像素，
    而一条腿只有两百来像素。硬分的结果是腿被拉成直线、八条腿汇聚成一把射线，
    蜘蛛本体几乎看不见 —— 这正是之前「腿鬼畜」的成因。
    够不着的词只亮词框，腿保持自然站姿，画面才干净。

    规模只有 8×8，且有可达性硬约束，贪心足够（匈牙利在稀疏可行集上没优势）。

    **单位陷阱（踩过坑，别再犯）**：这里全部是**局部单位**。
    `leg.hip_pos` 是局部坐标，`Target.center` 也是调用方用
    `SpiderPainter.to_local()` 换算好的局部坐标，`leg.full` 同样是局部长度。
    三者同量纲，`reach` 绝不能再乘 `unit` —— 乘了就等于把约束放宽 `unit` 倍
    （瞄准层的 `unit ≈ 1.66`，腿就能伸到自身长度的 1.66 倍），
    于是又变回「八条腿拉成射线」。`unit` 参数只为兼容旧调用签名而保留，不参与计算。

    **为什么是匈牙利而不是贪心**（改过一次，别再改回去）：
    可达约束紧的时候候选图很稀疏，每个词基本只有一两条腿够得到，贪心（按成本从
    小到大先到先得）结果就等于最优解。但腿长能按需拉长之后候选图变**稠密** ——
    8 个词 × 8 条腿全在可达圈内，这时候贪心的短视就暴露了：它会把腿消耗在
    「角度最顺」的那几对上，轮到剩下的词时八条腿已经派完。实测一圈 400px 的词，
    贪心只派得出 **4 条腿**，匈牙利能派满 **8 条**。
    规模只有 8×8、O(n³) 可以忽略，没理由再省这一步。
    """
    n_leg, n_tgt = len(legs), len(targets)
    if not n_leg or not n_tgt:
        return []

    # 匈牙利要求方阵，补到 max(腿, 词) 阶；不可达的格子填一个大哨兵值。
    # 哨兵必须**有限**：解法器内部用 `float("inf")`，输入里再混一个 inf 会算出 nan。
    n = max(n_leg, n_tgt)
    cost = [[_UNREACHABLE_SENTINEL] * n for _ in range(n)]
    for i, leg in enumerate(legs):
        reach = leg.full * max_frac
        preferred = leg.full
        for j, target in enumerate(targets):
            distance = math.hypot(target.center[0] - leg.hip_pos[0],
                                  target.center[1] - leg.hip_pos[1])
            if distance <= reach:
                cost[i][j] = _leg_cost(leg, target, preferred, reach)

    pairs = []
    for i, j in enumerate(solve_hungarian(cost)):
        if i >= n_leg or j < 0 or j >= n_tgt:
            continue                                   # 落在补出来的行/列上
        if cost[i][j] >= _UNREACHABLE_SENTINEL:
            continue                                   # 这条腿够不着它被配到的词
        pairs.append({"leg": i, "target": j, "cost": cost[i][j]})

    # 按成本升序返回：调用方（瞄准层）拿这个顺序做错峰延迟，最贴合的脚先伸出去
    pairs.sort(key=lambda pair: pair["cost"])
    return pairs
