# Qoder → WorkBuddy：我动了你的三个文件（启动台主题切换），完整交代

时间：2026-10-22 15:11 +0800
发起：Qoder
状态：**知会 + 接口公布**（用户当面授权改启动台 UI，按约定事后留全量交代）

---

## 0. 边界说明

用户要求「设置里加一个 UI 切换：墨绿·象牙白『白天』/ 蓝黑『夜晚』」。
落点必须经过 `launcher_qml.py` / `qml/Main.qml`（你的所有权范围），
我当面问过用户，得到「直接改 + 留协作消息」的授权后才动手。
**没碰** `crawler_spider.py` / `spider_painter.py` / locomotion 侧任何文件，
也看到了你 15:04 那封关于步态参数的信——`test_leg_fold_assignment` /
`test_skin` 两条红我在全量回归里撞见了，确认与主题改动无关，按你信里的
口径处理，不代改。

## 1. 改了什么（commit `dcc37d2`）

| 文件 | 改动 |
| --- | --- |
| `src/ui_theme.py` | 新预设 `midnight`（蓝黑·夜晚）；`_preset` 元数据约定（见 §2）；`ThemeStore.apply_preset()` / `read_preset_id()` / `apply_preset_to_raw()` |
| `src/settings_store.py` | `DEFAULTS`/`BOUNDS` 新增 `theme_preset`（默认 `forest`，白名单校验，**副本**，真源是 theme.json 的 `_preset`） |
| `src/launcher_qml.py` | `LauncherBridge` 新增 `themePresets`（QVariantList，只摆 forest/midnight）、`currentThemePreset`（str）、`setThemePreset(str)→dict`（Slot）；`resetSettings` 保留用户主题 |
| `src/qml/Main.qml` | 设置面板「释义卡片」下方新增「界面主题」一行，两颗 `PillButton`，数据全走 bridge，QML 零硬编码色值 |
| `tools/theme_tool.py` | `preset` 命令改走 `apply_preset_to_raw`（同步写 `_preset`）；`set` 手改单键后**摘掉** `_preset` 标记（文件已不等于任何预设，别让面板高亮假胶囊） |
| `src/help_content.py` | 设置一节加一条主题说明 |
| `test/test_theme.py` | 新增 `PresetSwitchTest`（残色/往返/脏元数据）+ StoreTest 一条 apply 用例；32 项全绿 |

## 2. `_preset` 元数据约定（需要你知悉的契约）

- theme.json 根上多一个下划线键 `"_preset": "forest" | "midnight" | ...`。
  `flatten()` 本来就跳过 `_` 开头键，**不会**进令牌表；`write_file` 会把
  `_` 开头的非令牌键原样带走。
- 语义：`_preset` 存在且合法 = 面板高亮它；被 `theme_tool set` 手改过 =
  没有 `_preset` = 面板回退读 `settings.theme_preset` 副本。
- 预设套用 = 「默认值 + 覆盖」整体盖写，**不是**在现状上叠加（沿用
  theme_tool 原有语义，防残色）。

## 3. 对你已有的东西的影响

- `ThemeStore.save()` 之后不会再把 `_preset` 洗掉（`_load` 时单独接住）。
- 「恢复默认」按钮行为变了一点：以前会把 `theme_preset`（新键）重置，
  现在显式保留当前主题——用户选过的界面配色不该被「恢复识词参数」带走。
- Widgets 老路径（`launcher_window.Panel`）**没有**加主题选择器，只保证
  `theme_preset` 键能存能校验；QML 是唯一入口。
- 已验证：两套主题真窗口截图（含设置面板、罐子展示区、热力图）无白底
  白字/残色；`test_theme.py` 32/32；全量回归新增红为 0（除你信里那两条）。

有问题随时回，接口要挪位置（比如你想把「界面主题」挪去换皮肤面板）我这边
bridge 属性是现成的，QML 侧随你摆。
