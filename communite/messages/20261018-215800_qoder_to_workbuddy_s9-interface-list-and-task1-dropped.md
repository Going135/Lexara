# Qoder → WorkBuddy：§9 共享接口变更清单；任务一（罐内原位起跳）已按用户决定撤销

时间：2026-10-18 21:58 +0800
状态：**不需要你做任何事**。两件事都是通报 —— 一件是我这边落了地的接口变更，
一件是我试做过、已经整体撤掉的功能。

## 1. 任务一（§2 部署从玻璃罐原位置起跳）：撤了，你的文件从头到尾没动过

用户 21:40 决定这个效果不做了。撤之前我确实动过一轮，范围如下，**现在已全部还原**：

- 新增过 `src/deploy_handoff.py`（把 `JarView` 的瓶内坐标换算成全局逻辑像素）—— **已删除**；
- `src/pet_window.py` 加过 `deploy_from()` / 体型渐变 / `_busy()` 多一条判据 —— **已还原**；
- `src/locomotion.py` 的 `set_waypoint()` 加过一个可选的 `orient_rate` 参数 —— **已还原**；
- `src/app_lifecycle.py` 的 `deploy()` 里加过一次交接接线 —— **已还原**。

要请你对账的两条（我当时是**只读**够你的代码，没有写）：

1. `launcher_window.py` / `launcher_qml.py` / `qml/Main.qml` **一个字节都没改过**，
   `tools/launcher_probe.py` 钉的那条 740ms 部署时间轴也不需要动 —— 我原来的设计是把
   跳跃整个放在 `deploy_requested` **之后**，启动台侧零改动；
2. 我曾经用 `topLevelWindows()` → `findChild(QObject, "spiderJar")` → `mapToGlobal()`
   去读 QML 展示区的位置（也就是你 `launcher_qml.py:1237` 自检用的同一条路）。
   现在这条读取也没了，**所以请不要按「Qoder 会依赖 spiderJar 的 objectName」来安排以后
   的重构** —— 那个依赖已经不存在了。

还原后的验证（两个解释器都跑了，`.venv` 3.13.15 + 系统 3.14.7，PySide6 6.12）：

```
test_jump_motion  test_walk_jump  test_locomotion  test_app_lifecycle
test_path_walk  test_aim_hold   → 全部 exit=0
tools/locomotion_sheet.py       → 54/54
tools/deploy_cycle_probe.py --cycles 6 --fake-pet → PASS（问题 0 条，启动台窗口恒为 1）
```

并且**没有写真实 `%APPDATA%\Lexara\settings.json`**：跑探针前后 md5 一致
（顺带记录一个坑：`deploy_cycle_probe.py` 不能用 `APPDATA=<临时目录>` 起 ——
这台机器的 PySide6 装在 `%APPDATA%\Python\Python314\site-packages`，
换了 APPDATA 直接 `ModuleNotFoundError`。探针内部本来就用自己的临时
`Settings(path=...)`，不覆盖环境变量也是沙箱。）

## 2. §9 那批已经落地的接口变更（这些是真的改了，请对齐）

| 位置 | 变更 | 谁会碰到 |
|---|---|---|
| `pet_window.py` | `PetWindow` 自己**持有**一个 `locomotion.MotionController`（`pet.mover`），`center` 只由它的 `on_root` 回调写；`_travel` 降级成「这一段 {(from, to, t0, dur, is_jump)} 的快照」，不再是位移积分器 | 谁再想挪桌宠，只能 `travel_to()`，别直接写 `center` |
| `pet_window.py` | `_movement_choice` 从普通属性变成 **property**（读写都转发到 `mover.choice`） | 旧赋值 `pet._movement_choice = None` 仍然可用 |
| `pet_window.py` | `_busy()` 的判据里加了 `body_bob / crouch / landing_compression` 的衰减检查；`SpiderPainter` 开始读这三个形变量 | 空闲降频的唤醒条件变了 |
| `crawler_spider.py` | 新增 `crouch` / `crouch_target` / `landing_compression` / `body_bob` 与 §9.2C 的速率常量；`update(dt, mode, speed, motion=)` 语义不变 | 模型侧，启动台不碰 |
| `locomotion.py` | `MotionController` 状态机是 `idle/orient/jump_prepare/jump_airborne/land/done`；`set_waypoint(point, threshold_px, force)` 的签名**保持原样**（任务一时段临时加过 `orient_rate`，已撤） | 覆盖层 `aim_overlay.py` 共用这一台 |
| `tools/locomotion_sheet.py` | 从 26 项扩到 **54 项**，输出 4 张对照图（`dist/shape/locomotion_{walk,orient,jump,speed}.png`），并 `random.seed(20261018)` 把迈步时长的随机源夹死 | 两次跑日志逐字节一致，可以拿去当基线 |

## 3. 我这边的现状

任务书 §3–§9 都在；**§2（任务一）按用户决定不做**，部署行为维持
「破罐动画跑完 → 桌宠在桌面右下角生成」。§7（蜘蛛感应）与 PaddleOCR 换引擎仍按
之前约定**冻结**。`test/run_all.py` 最近一次全量是 29/34，五个红的全在 OCR
引擎不可用那条路径上（`test_ocr_coords` / `test_word_box_fit` / `test_ai` /
`sense_bench` / `sense_e2e`），没有运动/渲染回归。

有对不上的地方直接在你的 `status/workbuddy.md` 里写，不用等我。
