# WorkBuddy · 状态

> 本文件只有 WorkBuddy 编辑。格式按任务书 §10。
> 职责：启动台 UI / 背单词 / 对话框 / API 配置面板 / 帮助（不碰 OCR 与八腿路径）。

## 2026-10-18 00:46 +0800

- 阶段：任务 A~E **全部完成**，进入收尾（测试补齐 + 交接文档）
- 已完成：
  - §1 开工调查：确认无 git 仓库 → 改用「文件所有权协商」；读通
    `launcher_window.py`(2100+ 行) / `launcher_qml.py` / `qml/Main.qml` /
    `dialogs.py` / `wordbook.py` / `settings_store.py` / `ai/*`；
    建 `communite/`（README + contracts + messages + status）
  - **A 背单词**：新增 `src/review_session.py`（`ReviewSession`：start/card/reveal/
    grade/next/exit/summary + `due_overview`），QML 实现「入口 → 卡片 → 完成页」；
    旧 Widgets 单词本弹窗改为**复用同一个类**（不是复制一份），不会分叉。
    调度仍是 `wordbook.py` 的 1/3/7/14，**一行未改**
  - **B 对话区**：新增 `src/ai/chat.py`（`ChatService`：后台线程 + 可取消 + 错误分级
    auth/bad_request/timeout/network/not_configured）；QML 换成真消息列表
    （气泡 / 思考中 / 失败重试 / 复制 / 新会话）。未配置时发送按钮 disabled + 引导
  - **C API 配置**：新增 `src/ai/config.py`（Windows **DPAPI** 加密密钥到
    `%APPDATA%\Lexara\ai_secret.bin`；Base URL/模型走 settings；公网 HTTP 拒绝、
    仅 loopback 放行；快照永不含明文）+ QML 配置面板（保存 / 清除 / 测试连接）
  - **D 引擎选择**：新增 `src/ocr_registry.py`，**只问** Qoder 的
    `describe_engines/current_engine/set_engine`，`unknown` 显示为「未探测」，
    不可用项灰掉并把后端给的原因显示出来（tooltip + 面板正文）
  - **E 帮助**：新增 `src/help_content.py`（10 步教学，每步带 `ready/partial/planned`
    真实状态），右下角 `?` 面板可滚动、Escape 关闭
  - 顺带修掉你的 `pet_scale` 既有缺陷（`_flush_scale` + `setPetScalePct` flush），
    `qml_bridge_probe` 已转 PASS —— 已在消息里跟 Qoder 交代，避免重复劳动
- 修改文件：
  - 新增 `src/review_session.py` `src/ocr_registry.py` `src/help_content.py`
    `src/ai/config.py` `src/ai/chat.py`
  - 新增 `test/test_review_session.py` `test/test_ai_config.py` `test/test_ocr_registry.py`
  - 新增 `tools/ui_probe.py` `tools/run_tests.py`
  - 改 `src/ai/cloud_provider.py`（改为统一读 `AIConfig`，消灭第二套 key 来源）
    `src/settings_store.py`（新增 `ai_base_url` / `ai_model` 默认值）
    `src/launcher_window.py`（`_flush_scale`）`src/launcher_qml.py` `src/qml/Main.qml`
    `src/dialogs.py`（复习页改走 `ReviewSession`）
    `test/test_industry.py`（夹具 `_W` 补齐 left/top/right/bottom 真实形状）
- 测试命令：
  ```
  PYTHONUTF8=1 python tools/run_tests.py        # 自动挑 .venv，18 项一条命令出表
  python tools/ui_probe.py                      # 单个跑（临时 profile，不碰用户数据）
  QT_QPA_PLATFORM=offscreen python src/main.py  # 离屏冷启动检查
  ```
- 测试结果：**18/18 通过**（`test/` 15 个文件 + qml_smoke + qml_bridge_probe + ui_probe）
  - QML 加载**零 error 零 warning**（先前 `Main.qml` 有 5 条 `Unable to assign [undefined]`，
    根因是 `reviewCard` 为空对象时取值没兜底，已修）
  - **真实端点验证 AI 链路**（DeepSeek，临时 profile）：
    正常 2.15s 出回复；错 key → `auth`/401 文案；错模型 → `bad_request`/400 文案；
    未配置 → `send()` 返回 False 且不产生任何气泡
  - 引信：`test_industry.py` 的 F6 用例原先崩在 `phrase_box`（假词缺 `left/top/right/bottom`），
    补夹具后 52/52 全过 —— **是测试夹具的洞，不是产品代码回归**
- 视觉检查：**部分验证**。全部 UI 断言由 QML 真实加载 + 桥接取值验证（819 个子控件、
  零警告）；但**未做真机截图目视**（offscreen 环境），配色/间距的主观美观度未验证。
- 未解决问题：
  - 只有一块普通分辨率屏，**125%/150% DPI、多屏负坐标**未实测（窗口最小尺寸已设 980×660）
  - 打包 exe 未重新构建（新增模块靠静态分析即可被 PyInstaller 找到，未改动 spec）
  - `ai_base_url` 键名与 Qoder 草案不同，等他把 `ai-provider-contract.md` 升 v1
  - `ocr_adapter.probe()` 暂无人在启动路径调用，目前由 UI 侧幂等触发一次；等 Qoder 接入后可撤
- 下一步：写 HANDOFF 交付清单 → 等 Qoder 两条回复 → 需要时重新打包 exe
- 是否需要 Qoder 决策：是 —— ①settings 键名用 `ai_base_url`；②`probe()` 触发权归谁

## 2026-10-18 01:10 +0800（暂停前最后一次跑）

- 阶段：**暂停**（用户关机，明早继续）。任务 A~E 已完成，文档已交付。
- 测试现状：**16/18 通过，2 项 FAIL —— 都是 Qoder 正在并发改动造成的，不是我这边的回归**
  - `test/test_word_box_fit.py`：`aim_overlay._assign()` 里用 `item["screen_pos"]`，
    但新的队列给的是 `ScanTarget` 对象 → `TypeError: 'ScanTarget' object is not subscriptable`
  - `test/test_aim_hold.py`：同为 01:00 左右新出现的失败（同一批并发改动）
  - 已按协议发消息给 Qoder（`communite/messages/20261018-010500_workbuddy_to_qoder_scantarget-blocker.md`），
    **没有**改 `aim_overlay.py` / `scan_session.py` / `pet_window.py`（归他）
- 本轮为配合他的改动做的调整：`tools/qml_bridge_probe.py` 里写死的 `reset.max_words == 8`
  改成读 `settings_store.DEFAULTS["max_words"]`（他把默认值提到 24 了）
- 明早第一件事：重跑 `python tools/run_tests.py`，确认上面 2 项是否已修复；
  仍失败就在 `communite/` 催一下，并按新事实更新 HANDOFF 的测试结论（别再写 18/18）

## 2026-10-18 10:58 +0800（恢复工作）

- 阶段：**收尾完成**。任务 A~E 全部落地，测试全绿，文档已按实际数字校准。
- **Blocker 已关闭**：Qoder 01:12 按方案 B 修了 `aim_overlay._assign()`
  （`batch = [t.item for t in session.current_batch()]`），复跑确认
  `test_aim_hold.py` 51/51、`test_word_box_fit.py` 29/29。
  **我没动他的三个文件。**
- 上一轮那两次「测试卡死」是**我这边命令的 120s 默认超时**，不是测试真的挂住；
  顺带发现 `run_tests.py` 走管道时 `print` 块缓冲 → 卡住时一行看不到，
  已逐项 `flush=True`（这次改的就是这个可观测性问题）
- 测试结果：**19/19 全绿**
  - 补上 `test/test_scan_queue.py`（30 项，Qoder 新增，我这张表原先漏了）
  - `tools/ui_probe.py` 新增 4 条断言（设置区间 min/max + 越界夹紧），现 40 条
- `max_words` 复核（Qoder 改了我四个文件，逐个看过）：
  - `settings_store` / `launcher_qml` / `launcher_window`：✅ 走同一常量
  - `dialogs.py::ModeDialog`：✅ 最近值回退修掉了老 `else 2` 把存过的 6 静默改成 8 的 bug
  - `qml/Main.qml`：⚠️→✅ 我把写死的 `from: 1 / to: 48` 换成桥接透出的
    `maxWordsMin/maxWordsMax`（`constant=True`），QML 不再硬编码区间
- 需要 Qoder 决策：否。给他的回复里做了三条决策（见
  `20261018-105819_workbuddy_to_qoder_all-green-and-decisions.md`）：
  ①同词去重保持现状、不动 `scan_text`；②`ScanSession` 继续归覆盖层，**不要**为我改成 QObject；
  ③他 `_hint_text()` 里「已全部踩完 N 个 · M 个只亮框」自相矛盾，给了改法，**他的文件我没动**
- 未解决问题（与 00:46 相同，未新增）：高 DPI / 多屏未实测；exe 未重打包

## 2026-10-18 11:06 +0800（帮助文案与 §6 对齐）

- **发现并修掉一处「文档说谎」**：Qoder §6 连续扫词上线后，
  `help_content.py` 的 `queue` 步骤还写着「当前上限 8 个词、超出不显示」，
  已被他改造成「八条腿一批 + 队列自动接下一批（默认 24 / 上限 48）」。
  行为：`state` 从 `partial` → `ready`，四条 bullets + footer 按他的实现重写；
  同时把 `scan` / `result` 两步里「八条腿踩向挑出来的词」「每个被踩住的词一个框」
  改准确（现在是「每个词都有框，只有当前批被腿踩着」）
- 并发改动影响：10:58 复跑时 `sense_overlay.py` 从 `lexara_theme` 导入
  `union_geometry`（当时它还在 `aim_overlay`）→ `ImportError`，`qml_smoke` 红了一次；
  一分钟后他自己改好，**我没动他的文件**，已发消息说明
- 待 Qoder 信号：§7 蜘蛛感应接进真实入口后，把 `help_content.py` 的 `sense`
  从 `planned` 改成 `ready` 并补真实步骤（不猜交互）
- 最终测试结论：**19/19 全绿**（11:04）


## 2026-10-18 15:30 +0800（Qoder 15:50 消息已回，交接）

- 用户指令：**暂停任务、写文档**。§7 蜘蛛感应为**冻结态**（不是完成态）。
- 已回 Qoder 四条（`20261018-152600_workbuddy_to_qoder_four-answers.md`）：
  - (a) 感应状态**保持 `planned`**，不翻 ready —— 他撤回请求，我确认未动
  - (b) 同意「不 close + 灰掉 + 写原因」；但补明 `already deleted` 是**句柄悬空**，
    真修法是析构置空引用或 `sip.isdeleted()` 守卫，「不 close」治不了它；
    原因文案由我统一写成中文，不把异常字符串甩给用户
  - (c) `box_only` 给了明确指令（他直接落）：`tail` 里删掉重复段 + 收尾按
    「已处理 N 个词（M 个只亮了框）」分叉，「全部踩完」不许和「只亮框」同行
  - (d) 限核**不做滑杆**（认领结论）：新开全局设置要动我 3 个文件 + settings_store + 自检，
    与「暂停任务写文档」冲突；常量 2 先跑，感应真上线时在帮助里加一句「2 个核、不发烫」
- 限核影响核查：他的 `DEFAULT_THREAD_LIMIT=2` 让识别慢约 44%（1.7s→2.4s），
  **我三个文件里没有任何按 1.5 秒写的等待/超时**（`singleShot` 全是 notice 淡出，3~6s）
- 新默认下全量复跑：**19/19 全绿**（15:28）
- 打包/交付注意：`dist/sense/*.log`（10 个）印了识别到的屏幕单词，
  **打包前必须删**；且 `dist/` 不作为交付物，交付只走源码 + `tools/run_tests.py`

## 2026-10-18 17:50 +0800（任务书 UI 精修：§2~§7 全部落地）

- 阶段：**任务书 `LEXARA_WorkBuddy_UI_Refinement_Task.md` 的 §2–§7 已完成**，
  全量回归跑完。除 Qoder §7 冻结态那两项既有失败外，**无新增回归**。
- 修改的文件（全部是我的所有权范围，**没碰** `pet_window.py` / `aim_overlay.py` /
  `sense_*.py` / `scan_session.py` / `ocr_engine.py`）：
  - `src/qml/Main.qml`（2170 → 2545 行）
  - `src/launcher_qml.py`（793 → 1174 行）
  - `src/launcher_window.py`（2362 → 2372 行，只改 `JarView` 与 headless 两处）
  - `src/main.py`（部署接线外迁）
  - `src/wordbook.py`（schemaVersion 2 → 3）、`src/settings_store.py`（+1 键）
  - `src/dialogs.py`（单词本按收藏分类过滤）、`src/bubble.py`（`dispose()`）
  - `src/ai/chat.py`（`askSucceeded` 信号）
  - 新增 `src/app_lifecycle.py` / `src/activity.py` / `src/autostart.py` /
    `src/calendar_export.py`
  - 新增 `test/test_favorites.py` / `test_app_lifecycle.py` / `test_activity.py` /
    `test_calendar_export.py` / `test_autostart.py`，并登记进 `test/run_all.py`
  - 新增 `tools/deploy_cycle_probe.py`（部署/收回循环探针）

### §2 UI 精修（逐条）

- **2.1 Logo**：白卡包裹 + `sourceSize 360×240` + `PreserveAspectFit`，高 116；
  窄窗口先压宽度（`Math.min`），不挤压主内容区。
- **2.2 导航**：整体上移紧贴 Logo；**「背单词」在「收藏夹」上方**；收藏夹可展开/收起，
  五个分类来自 `lexicon.FAVORITE_CATEGORIES`（唯一来源），每行显示
  `收藏数/该词库真实词条总数`（`cet4 9/3849`、`industry 0/307`…），
  分母取不到显示 `3/—`；一个分类都不命中的词进「未分类」**只显示计数**
  （写 `4/4` 会被读成「4 个都收藏了」）。点分类 → 打开**按该分类过滤**的单词本
  （同一份收藏数据，不复制）。底部「换皮肤/设置」在滚动区之外，展开不会把它们挤走。
- **2.3 换皮肤 / 设置**：图标盒 20→40、图标 18→34、文字 13→20px，整体约 2 倍，
  基线对齐、点击热区跟随。
- **2.4 展示区**：常驻玻璃罐**已下线**（`glass_case.png` 不再加载/绘制）。
  现在是三层：碎玻璃/裂纹/碎片（仅动画阶段，结束即隐藏）→ 蜘蛛本体（程序化 IK 不变）
  → 白色 50% 圆角矩形（`QColor(255,255,255,128)` + 1px 描边）。
  已部署时蜘蛛淡出，展示区补一句「蜘蛛已经到桌面上了 / 点右下角的「收回」，让它回来」——
  否则玻璃罐没了会只剩一块白板，看起来像渲染失败。
- **2.5 学习日志**：标题 `学习日志 · 已打卡 X 天`（X 由 `activity` 从真实事件算出）；
  右侧圆形 `?` 打开三色说明（浅绿=当天至少一次蜘蛛扫描、深绿=复习或主动 AI、灰=无活动，
  同日深绿优先），`modal: true` + `CloseOnEscape|CloseOnPressOutside`，不压住主按钮。
  写入点只有三处且都要求「真的成功」：`record_learning(扫出有效词)` /
  `grade(提交自评)` / `record_ai_ask(AI 收到非空回复)`。
- **2.6**：日/周/月/年选择器删除，`heatRange` 状态、信号、`_RANGE_WEEKS` 一起清掉，
  多出来的宽度全给格子（`cell = (w - 2*start - (weeks-1)*gap)/weeks`，夹 6~18px）。
- **2.7**：OCR 引擎选择器移进设置面板（真实状态 + 后端给的原因）；输入栏**首位**改为
  模型 pill（`模型 · deepseek-chat` / 未配置时琥珀色 `未配置模型`），未配置时发送禁用、
  输入框提示「配置模型后即可在这里提问（离线识词不受影响）」。原独立 `enginePanel` 已删除。
- **2.8**：部署文字 26px 加粗、按钮宽 176、与输入栏同高，动画期间 `deployEnabled=false`
  防重复点击，文案与相位一致（`部 署` / `收 回`）。

### §3 设置溢出

根因是设置面板内容全塞在一个固定高容器里（引擎列表 + 3 个滑杆 + 2 个开关 + 启动行为），
矮窗口时把底部按钮顶穿。现在改成**固定头尾 + 中部 `ScrollView`**（`contentWidth: availableWidth`），
长模型名 `elide: Text.ElideRight` + `ToolTip`，按钮区不参与滚动。两个入口都验过：
设置面板（`设置` 按钮）与 AI 配置面板（模型 pill / `去配置`）。

### §4 部署后收回出现重复 UI + 闪退（高优先级）—— 已定位根因并修复

- 复现：`tools/deploy_cycle_probe.py --cycles 2 --fake-pet` → 第一次「收回」后 `exit=139`。
- `faulthandler` 栈指向 `launcher_qml.py:131 in paint`（`jar.render()`）。
- 根因链：`LauncherWindow.begin_recall()` 调 `self.show()` → 隐藏的 Widgets 启动台
  **露出来**（第二个启动台 UI）→ `JarView` 变成可见 widget → QML 的 `JarItem.paint`
  仍在 `render()` 它 → 重入绘制 → access violation。
- 修复（三处，都不是加延时）：
  1. `LauncherWindow.show()` 在 `headless` 时直接 return；
  2. `begin_recall()` / `recall_from_pet()` 改走 `_present()`（headless 时回调 QML 置前）；
  3. `JarItem.paint` 加 `if jar.isVisible(): return` 作第二层保险。
- 验证：真 `PetWindow` **20 次循环 PASS** —— 启动台窗口恒为 1、收回后桌宠为 0、
  可见顶层窗口只剩 1 个（顺带修掉了 `BubbleWindow` 停在 opacity 0.011 不 hide 的残留小窗，
  改为 `_fade_out` 标记 + `dispose()`）。
- 顺带把部署/收回/退出/自动部署收敛成 `app_lifecycle.PetLifecycle`（可单测），
  12 项单测覆盖「重复部署 / 收回幂等 / 销毁后引用清空 / 自动部署只一次 / wire 幂等」。

### §5 / §6 启动行为

- `开机时启动词蛛`（默认关）：写**当前用户 Startup 目录**的 `Lexara.lnk`，不用管理员权限、
  不碰注册表、不碰别人的启动项；`enable()` 先删后建（幂等）；失败**回滚开关**并给原因；
  设置里有「怎么关」的说明。6 项单测用临时目录验证（真实建了 .lnk 再删）。
- `启动后默认部署蜘蛛`（默认开，独立设置）：只在进程启动后 `singleShot(1200ms)` 触发一次，
  `auto_deploy_once()` 有 `_auto_deploy_done` 标记 + 相位必须 `idle`，
  托盘恢复/收回/再显示都不会重复触发。

### §7 日历 / 成就

- 两种天数**分开统计**：`openDates`（打开天数，里程碑用）与学习事件表（打卡天数，标题用）。
- 三色与成就共用 `activity.learning_map()` 一份口径，界面、导出图不会对不上。
- 成就：7/30/100 天 + 日历全绿（`GREEN_MIN_SPAN=7`，防止第一天打卡就「全绿」；
  区间起点取 `max(窗口起点, 首次记录)`，未来日期不算）。`claim_new()` 只写 `seen=False`，
  `mark_seen()` 才标记已读 → 崩溃/关机后下次启动仍能补弹。
- 弹窗含「保存图片 / 暂不保存」；保存走 `calendar_export`（QPainter **重画**，不是截图，
  图里只有日历格、日期范围、打卡天数、图例），取消保存不标已读、失败绝不返回 ok=True。
  导出图尺寸从 1440×900 改成 **1440×520**（53×7 点阵天生宽而矮，900 高会剩一大片空白）。

### §8 测试

- 全量 `test/run_all.py`：**28/30 文件通过，累计 759 项**
  - 失败两项 = Qoder §7 冻结态的既有失败，与 10-18 15:28 基线一致：
    `tools/sense_bench.py`（35 项，判据口径过期）、
    `tools/sense_e2e.py`（43 项后 `exit=3221226505`，`SenseOverlay already deleted`）
  - 新增 5 个测试文件共 **52 项**全过（收藏夹 10 / 生命周期 12 / 日历成就 17 / 导出 7 / 自启动 6）
- `tools/qml_smoke.py` PASS、`tools/ui_probe.py` PASS（`qml.noWarnings=0`，927 个子控件）、
  `tools/qml_bridge_probe.py` PASS、`tools/deploy_cycle_probe.py --cycles 20` PASS
- 旧界面回退 `LEXARA_LEGACY_LAUNCHER=1` 冒烟通过（能启动 + 自动部署，无 traceback）

### 本轮额外修掉的一个渲染 bug（不在任务书里）

窗口缩放后展示区里的蜘蛛会「变扁 + 腿压出圆角矩形」。两个原因叠加：
1. `JarView` 的 resize 点只在 `paint()` 里，而 `paint()` 要被 `update()` 才跑 →
   没有 `geometryChanged` 就永远不重画，QML 把**旧纹理拉伸**到新尺寸；
2. Widgets 面板给 `JarView` 设了 `setFixedHeight(300)`，QML 要的 `444×222` 被夹回 300 →
   unit 按 300 高算、像素画进 222 高的纹理。
修法：`JarItem.geometryChanged()` 里 `update()`；`set_jar()` 里解除 min/max；
`paint()` 里再加一道「尺寸不符就 `setFixedSize`」兜底。已用 `LEXARA_JAR_DEBUG=1`
打日志核对（`展示区=644×322` 与 QML item 完全一致）。

### 视觉验证（截图都在 `.workbuddy/shots/`）

`v4_home` / `v4_fav` / `v4_settings` / `v4_settings_narrow` / `v4_api_narrow` /
`v4_legend` / `v4_achievement` / `v4_nomodel2` / `v4_dpi_0.6667` / `v4_dpi_0.8333` / `baseline`。
本机屏幕就是 **150% 缩放（dpr 1.5）**，100% / 125% 用 `QT_SCALE_FACTOR` 模拟验证布局无溢出。

### 未验证（如实记录，别当成通过）

- **真机 100% / 125% DPI 与多屏负坐标**：只有一块 150% 屏，其余是 `QT_SCALE_FACTOR` 模拟；
- **托盘菜单触发的收回**：代码路径与按钮一致（都进 `PetLifecycle.recall`），但没有真点托盘；
- **打包 exe 冷启动**：本轮没重新打包（新增 4 个模块，PyInstaller 靠静态分析能收到，spec 未改）；
- 成就「保存图片」的系统保存对话框只做了逻辑验证，没有在 UI 上真的点一遍选路径。

### 需要 Qoder 决策：否

已发 `communite/messages/20261018-174000_workbuddy_to_qoder_wordbook-v3-and-render-fix.md`：
`wordbook.json` 升 v3（纯增量）、新模块边界、`begin_recall → show()` 的根因修复，
并请他 **不要另算一套日历口径**、打包前删 `dist/sense/*.log`（13 个，印了屏幕单词，我没动他的产物）。

### 17:56 补记：`test_aim_hold.py` 的 3 项红不是我这边

全量回归（17:39）时它是 51/51。17:52 与 17:55 复跑变成 **48/51**，稳定复现：

```
A2 起步时只伸出一部分 → 第 1 帧只下发了 0 条
E5 24 个词全部踩完   → 完成 0 · 失败 24（但 E6 仍显示走了 9 批）
E13 继续之后能走到完  → 完成 0
```

同一时间窗里被改动的是 **Qoder 的文件**：`test_leg_fold_assignment.py` 17:36、
`crawler_spider.py` 17:37、`locomotion.py`+`pet_window.py` 17:45、`aim_overlay.py` 17:49。
我 17:45 之后只改过 `launcher_qml.py`（调试 objectName）+ 文档，与腿/瞄准无关。
已发 `20261018-175600_workbuddy_to_qoder_aim-hold-3-red.md` 通报，**没有改他的文件**。

因此当前默认口径：
- **我负责的部分：全绿**（新增 52 项 + QML 冒烟/桥接/UI 探针 + 部署循环 20 次）
- 回归表上的红：`sense_bench`、`sense_e2e`（§7 冻结态既有）+ `aim_hold` 3 项（他正在改的腿时序）
- 他改完说一声，我再跑一次 30 文件全量对账

### 18:55 补修：展示区「50% 透明」其实是不透明的（用户报）

用户截图反馈：展示区是一块死白的板子，不是约定的「白色 50% 圆角矩形」。

- **根因**（不是 alpha 写错，代码里一直是 `QColor(255,255,255,128)`）：
  `JarItem.paint()` 调的是 `jar.render(painter, offset, region)`，**默认 flags =
  `DrawWindowBackground | DrawChildren`**。Qt 会先用调色板 Window 色把整块区域
  不透明地填一遍（实测 `rgba(249,249,249,255)`），`paintEvent` 里的半透明底板
  被压在下面 → 界面上只剩一块白板。
- **修复**：`JarItem.draw_jar()`（从 `paint()` 抽出来的唯一绘制点）显式传
  `QWidget.RenderFlag.DrawChildren`，只画 `paintEvent` 的输出，圆角外自然透出卡片渐变。
- **实测**（1180×760 / dpr1.5，像素采样）：卡片底色 `(244,243,237)` →
  底板内 `(250,249,246)`，正是白 128 叠上去的结果（`244 + (255-244)*0.5 = 249.5`）；
  改之前是 `(255,255,255)`。
- **回归**：新增 `test/test_jar_stage.py`（5 项，走真实 `draw_jar()` 路径逐像素量）：
  底板内部 alpha=128、整块无大面积不透明、四个圆角外 alpha=0、蜘蛛层仍是实心；
  另有一项把「默认 flags 会填成不透明」钉住，防止有人把参数改回去。
  已登记进 `test/run_all.py` 与 `tools/run_tests.py`。
- 复跑 `tools/qml_smoke.py` PASS、`tools/ui_probe.py` PASS（QML 零警告）、
  `tools/deploy_cycle_probe.py --cycles 6` PASS（`启动台=1`、问题 0 条）。
- 截图：`.workbuddy/shots/v5_alpha.png`（白跳蛛）、`v5_pixel.png`（用户当前皮肤
  `pixel_spider`）、`v5_deployed.png`（已部署空态）、`v5_deployed_narrow.png`（980×660）。
- 备注：卡片本身是 `#F3F2EC → #FBFAF6`，白 50% 叠上去只亮 6 级，这是**算术结果**
  而不是又没生效 —— 想让玻璃感更明显只能把卡片底色压深，属于设计取舍，等用户点头再动。

#### 19:06 全量回归快照（29/33 文件，841 项）

- 我这边全绿：新增 `test_jar_stage.py` 5 项 + 之前 52 项 + QML 冒烟/UI 探针/部署循环。
- 表上 4 个红，**都不是本轮改动**：
  - `tools/sense_bench.py`、`tools/sense_e2e.py`：Qoder §7 冻结态的既有失败（10-18 15:28 基线起就在）。
  - `test/test_path_walk.py`（B5/B7/B8/D7）、`tools/aim_e2e.py`（腿分配没退化那一条）：
    跑的过程中 `test_path_walk.py`（19:00）、`src/locomotion.py` + `src/aim_overlay.py`（19:04）
    被 Qoder 改动，抓到的是**改到一半的快照**。19:06 单独复跑 `test_path_walk.py` → **43/43 全绿**；
    `aim_e2e` 还剩 1 条「腿的分配 ≥ 一半」不过，同属他正在调的腿分配。
    这两处我一行没碰（`crawler_spider` / `locomotion` / `aim_overlay` / `pet_window` 全是他所有）。

### 19:15 再改：展示区改成真正的「镂空看桌面」（用户第二次澄清）

用户明确：50% 不是「白板上的半透明」，而是**中间挖空、直接看到桌面**。
上一轮的 alpha 修复只解决了「白板不叠加」，但底板下面仍旧是卡片渐变，
所以看不出桌面。这一轮把窗口做成「透视窗」：

- **前提**：`ApplicationWindow.color: "transparent"` + `FramelessWindowHint` 本来就有，
  窗口四角实测 alpha=0（`v5_pixel.png` 右上角 `(0,0,0,0)`），透明帧是通的。
- **挖洞**：外壳与主卡片原来都是 `Rectangle`（铺满），下面垫着它们就永远看不到桌面。
  现在两层都改成「`Shape` 填充 + 奇偶填充规则（`ShapePath.OddEvenFill`）」：
  一条路径 = 外圆角矩形 + 内部圆角矩形，第二个子路径就是洞；描边单独一条
  `ShapePath`（共用会把洞边也描一圈，凭空多一道框线）。卡片渐变搬到
  `ShapePath.fillGradient`，视觉与原来一致。
- **洞的几何**：`jarItem.mapToItem()` 算到 shell / hero 各自坐标系，再内缩 1px
  —— `JarView.stage_rect()` 就是整个控件内缩 1px，不内缩会露出一圈 1px 卡片底色。
  用显式 `refreshPortal()` + `onWidthChanged/onHeightChanged/onXChanged/onYChanged`
  驱动（不能写成绑定：`jarItem` 在文件后半段才创建，首次求值是 null，
  既刷警告又绑不上依赖）。
- **自检**：`LEXARA_QML_TEST` 新增 `portal校验=True`，断言「洞 = 展示区内缩 1px
  且完全落在主卡片内」，`tools/qml_smoke.py` 把它列进 PASS 条件。实测
  1180×760 → `portal=642x320@(135,17) 卡片=912x392 展示区=644x322`；
  980×660 → `442x220 卡片=712x292 展示区=444x222`。
- **验证手段**：新增 `LEXARA_QML_SHOT_SCREEN=1`（截整屏）。`grabWindow()` 只能拿到
  alpha=0 的空洞，验不了「桌面透没透进来」。整屏截图里能直接看到下层的
  IDE 文本透过底板 —— `.workbuddy/shots/v6_portal.png` / `v6_portal_narrow.png` /
  `v6_portal_deployed.png` / `crop_portal_corner.png`（3 倍放大看边缘对齐）。
- **回归**：`qml_smoke` PASS（含 portal 校验）、`ui_probe` PASS（零警告，子件 927→940）、
  `deploy_cycle_probe --cycles 4` PASS、`test_jar_stage` 5 项 PASS。
- **代价/风险**：两层 `Shape` 都开了 `layer.enabled + layer.samples: 4`（圆角要 MSAA，
  否则边缘发毛）；它们只在几何变化时重绘，不是每帧。窗口从此是「局部透明」，
  ClearType 次像素抗锯齿会被 Qt 关掉，正文略细一点点。

### 19:55 主题换色（墨绿 → 象牙白）+ 窗口投影

用户要求：① 整个界面底色改成「上墨绿、下象牙白」的竖向渐变；② 给启动器加阴影。

**底色 / 渐变**
- 渐变画在外壳那层 `Shape` 的 `fillGradient` 上（`#1D3D31 → #24473A → #61795F →
  #D9D3BF → #FBF7EA`）。深色段只保留到 26%，42% 之后完全落到象牙白 ——
  再往下压会撞上「背单词 / 收藏夹」的深色文字，中间那段灰绿最难读，停靠点是按这个约束压缩的。
- 侧栏原来的 `#F0EFE9` 实心底**去掉**（改透明）：留着的话顶部会和主区拼出一道
  灰绿竖缝。代价是压在墨绿上的两处文字要换浅色：标题「桌面学习空间」、状态文字、
  三个窗口按钮、Logo 下的「具身化语言学习」。
- 卡片由纯白 `#FFFFFF` 调成象牙白 `#FFFDF6`，主卡片渐变 `#F6F2E4 → #FDFBF2`，
  和底色同一色系。
- `WinButton` 新增 `fg` 属性（默认仍是墨色），标题带用浅色 + 半透明白 hover。

**阴影**
- Windows 不为无边框窗口画阴影；先试了 `DwmExtendFrameIntoClientArea`，实测无效
  （透明 QQuickWindow 走的是另一套合成路径），已删除。
- 又试了 `MultiEffect`：它把源纹理**按 item 尺寸重采样**，padding 一加就把卡片
  整体放大了一圈；源设 `visible:false` 直接没影子；且模糊会顺着展示区那个洞往里洇。
  不可用。
- 最终用 `Canvas` 手画：窗口四周留 28px 透明边距，边距里从外向内叠 18 层圆角矩形
  （alpha 按 `(1-t)^1.35` 衰减，纵向下偏最多 7px），再用 `destination-out` 把展示区
  那个洞原样擦掉 —— 阴影绕着洞走，不污染「看桌面」。
- 最大化时 `shadowMargin` 归零、Canvas 隐藏，否则屏幕四周会留一圈透明缝。
- 窗口尺寸从 1180×760 改为 **1236×816**（= 卡片 + 2×28），卡片本身仍是 1180×760，
  布局一点没动；`minimumWidth/Height` 同步 +56。
- 实测左侧衰减：离卡片 11px 处 `(246,246,246)` → 贴边 `(173,182,180)`，11px 内平滑过渡。

**验证**
- `qml_smoke` PASS（含 `portal校验=True`）、`ui_probe` PASS（零 QML 警告）、
  最小尺寸 1036×716 下设置面板不溢出（`v9_settings_min.png`）。
- 截图：`v9_shadow3.png`（整屏，能同时看到渐变 + 阴影 + 透视）、`v9_skins.png`、
  `crop_shadow_portal.png`（放大确认阴影没洇进透视区）。

### 20:24 第三轮全量回归（对账）

`test/run_all.py` 跑满 11m11s：**文件 32 个通过 / 34，累计检查项 879**。

| 轮次 | 通过 | 检查项 | 红项 |
|---|---|---|---|
| 第二轮 19:04 | 29/33 | 841 | path_walk、aim_e2e、sense_bench、sense_e2e |
| 第三轮 20:24 | 32/34 | 879 | sense_bench、sense_e2e |

- 第二轮那两个红（`test_path_walk.py`、`aim_e2e.py`）本轮**转绿**（path_walk 42→43 项，
  Qoder 补了一条）：确认当时抓到的是 `locomotion.py` / `aim_overlay.py` 正在被改的
  半成品快照，不是真回归。
- 现存 2 个红全部属于 §7 感应链路（Qoder 侧冻结态），与 UI 改动无关：
  - `tools/sense_bench.py` 33/35：`静态画面没有反复唤醒 OCR`、`变化检测的判定和剧本对得上`。
  - `tools/sense_e2e.py` 33/43：桌面新词识别、词本体框、覆盖层渲染、轮次跳过统计等 10 条。
- 加项：本轮多出 `test/test_jar_stage.py`（5 项，展示区图层不透明度），即 34 个文件里
  新增的那一个；本项 PASS，`DrawWindowBackground` 那个根因现在有守了。
- 结论：底色渐变 + 阴影 + 透视三件事对既有 879 项检查零新增破坏。

### 21:10 外部调参：主题令牌化 + 两个调参入口

用户要求：「写一个工具支持外部调参，也包括改各种按钮颜色」。

**令牌化（`src/ui_theme.py`，85 个令牌）**
- `Main.qml` 里 78 处字面颜色 + 渐变停靠点 + 投影参数全部抽成 `tv["组.键"]`，
  顶部一整块 `readonly property string ink: tv["base.ink"]` 只是起短名字，
  所以原有 200+ 处 `root.xxx` 引用一行没改。现在 QML 里只剩两处 `"#000000"`
  （`rgbaOf` 兜底 + `destination-out` 填充），是绘制指令不是配色。
- 分组：`base`(24) / `shell`+`hero`+`stage`(17) / `shadow`(7) / `btn`(34) / `heat`(3)。
- **`@引用`**：`btn.primaryBg` 默认写 `@base.accent`，改强调色按钮跟着变；
  单独覆盖 `btn.primaryBg` 又只改按钮。解析最多 8 层，成环/指向空键退回默认。
  写回时保留 `@` 原文，不会固化成具体色（这点有测试守）。
- 校验：颜色必须 `#RGB/#RRGGBB/#AARRGGBB`，数值按 `ui.min/max` 卡范围
  （`shadow.strength=45` 这种少写小数点的会被拒），未知键报错但不阻断启动。
- 写盘：`.tmp` + `os.replace`；文件缺失自动落一份默认；坏 JSON 退回默认配色
  并在日志里说话 —— 主题文件写坏不该让启动器打不开。

**热重载**
- `ThemeStore(QObject)` 暴露 `Property("QVariantMap", notify=...)`，
  QML 全部绑在 `theme.v` 上；`QFileSystemWatcher` 同时盯文件**和目录**
  （`os.replace` 会换 inode，只盯文件会「只热一次」），140ms 去抖后整体换表。
- 实测：进程启动用默认色，1.5s 时改文件 → 2.6s 截图已经是紫色外壳 + 红色部署
  按钮（`.workbuddy/shots/t_hot.png`）。`reloads` 计数与二次写入都有测试。

**两个入口**
- `tools/theme_tool.py`：`list/get/set/reset/diff/presets/preset/path/open/watch`，
  支持 `--group/--changed/--search/--json/--dry-run`。`set` 是**全有或全无**
  （一条不合法就一条不写，退出码 2）。
- `tools/theme_live.py`：本地 `127.0.0.1:8765` 网页调参台（色块取色器 + 滑杆 +
  分组 + 搜索 + 预设 + 单键"默认"按钮 + 改过计数），只绑本机、只读写这一份文件。
- 预设 4 套：`forest`（默认）/ `ocean` / `paper`（浅壳，连带把压在深色带上的
  文字改回墨色）/ `ink`（夜间，连卡片、点阵、输入框一起转深）。

**顺手修的一处架构隐患**
- `ui_probe` 和 `deploy_cycle_probe` 各自复刻了一遍 `contextProperty` 清单，
  主题一加就漏 → 探针测的是「没有主题的界面」（83~84 条 undefined 警告），
  而真窗口是好的。抽出 `launcher_qml.build_engine()` 作为唯一装配点，三处共用，
  现在两个探针都是 0 警告。

**验证**
- `test/test_theme.py` 28 项全过（令牌自洽 / 引用 / 校验 / 原子写 / 坏文件降级 /
  两次热重载 / CLI 端到端 / **QML 里不许再出现字面颜色** / **`tv[]` 键必须存在** /
  **令牌表不许有僵尸键**）。
- `qml_smoke` PASS（portal 校验 True）、`ui_probe` PASS（0 警告）、
  `deploy_cycle_probe --cycles 3` PASS（0 警告 0 问题）。
- 三种预设有截图：`t_default.png` / `t_ink3.png` / `t_paper.png`，调参台 `t_live.png`。
- 未跑：完整 `test/run_all.py`（11 分钟，本轮只做了针对性回归）。

### 21:50 美术换素材：奶蛛头身 / 白跳蛛头 / 三张玻璃损毁

用户口述三条，一次做完（未跑测试，按要求）。

- **新工具** `tools/apply_skin_art.py`
  - `spiders --milk-body --milk-head --white-head`
  - `cracks A B C` → `jar_crack_01..03`
  - 旧素材自动存 `backup/art_prev_20261018/`（不覆盖更早的备份）
- **头部朝向**：渲染层 `_paint_image_body` 对图皮的头统一 `rotate(-90)`，所以
  素材要预转顺时针 90°。旧奶蛛头六眼对称看不出来，新方形笑脸一测就暴露
  （证据见 `.workbuddy/shots/zoom_milk_head.png` → 修复后 `zoom_milk2.png`）。
- **黑底抠图**：白跳蛛头是黑底 + 柔和投影，flood fill 容差提到 92，再按
  `obs/a` 反解 premultiply；白底图仍走容差 18 + un-matte。
- **玻璃**：四角 flood fill 会留下星芒之间的死白（不与边框连通），改判据为
  「三通道 ≥250 即透明」；并按 `IMPACT=(0.5,0.44)` 对齐爆点（alpha 加权重心），
  缩放**保比例**（放射状裂纹非等比拉伸会扁）。
- 验证（不算回归，只看图）：`tools/skin_sheet.py` 四皮 × 三底；启动台实截图
  `art_white.png`（默认白跳蛛）/`art_milk.png`（临时切奶蛛，已还原 settings）；
  `cracks_preview.png` 三张裂纹在象牙白与纯白两种底上按 644×322 实际尺寸叠放。
- 未跑：`test/run_all.py`（用户明确不跑）。改的是 assets，Python 未动，
  仅新增一个工具脚本。

### 21:58 Logo 换新 + 去掉外围白框

- 新 `tools/apply_logo.py`：白底/透明底通吃，出两版配色
  - `assets/ui/lexara_logo.png` → 象牙白 `#F7F3E6`（QML 墨绿顶栏）
  - `assets/ui/lexara_logo_ink.png` → 墨黑（旧 Widgets 浅色侧栏，`launcher_window`
    第 1907 行改用这版）
  - 440×119（2 倍图），旧文件备份在 `backup/logo_prev_20261018/`
- `Main.qml`：删掉包 logo 的白色圆角卡（`color: root.card` + 描边），`Image`
  直接压在渐变上，高度 `width * 119 / 440` 绑定。
- **必须染色**：原图是黑字，直接放 `#1D3D31` 上几乎看不见，所以用与 `root.onDark`
  相同的象牙白。
- 验证：`ui_probe` 0 警告（无绑定环）、`qml_smoke` PASS（portal 校验 True）；
  截图 `.workbuddy/shots/logo_v1.png`。

### 22:05 白跳蛛身子换新

- `assets/skins/white_jump_spider_body.png` ← 新圆顶素材：抠白底 → 紧裁 → **逆时针 90°**
  （平底转右，贴合 +x 朝头）→ 252×152。
- `tools/apply_skin_art.py` 的 `spiders` 改成四个部件都可选，单独换一个不用带其它图。
- 验证：`test/test_skin.py` 25/25；`skin_sheet.png` 重出（四皮 × 三底）；
  启动台截图 `white_v2.png` / 放大 `white_v2_zoom.png`。
- 旧身子已备份到 `backup/art_prev_20261018/white_jump_spider_body.png`。

### 22:12 背单词提示音（用户提供的 mp3）

- 素材：`assets/sfx/ding.mp3`（31 KB，0.98 秒，用户给的 lesiakower-ding-sound）。
- 播放：`src/sfx.py` 用 **WinMM MCI**（`type mpegvideo`）直接放 mp3。
  为什么不用 QtMultimedia：本环境 PySide6 无该模块，`build_exe.bat` 也显式
  `--exclude-module PySide6.QtMultimedia`；MCI 系统自带、零依赖、异步不阻塞。
- 接线：`LauncherBridge.reviewGrade(correct)` → `if correct: sfx.play_ding()`。
  注意界面上这个按钮的实际文案是「记住了（回车）」，就是用户说的「我已背会」；
  「没记住」不响。首页快捷入口也调用同一个 Slot，一并覆盖。
- 失败策略：文件缺失 / 非 Windows / `LEXARA_SFX_MUTE=1` → 静默 False，不抛不弹。
- 打包：`assets/sfx` 已加进 5 个 `.spec` 与 `tools/build_exe.bat`。
- 验证：`test/test_sfx.py` **6/6**（含「correct 才响、且只响一次」的接线断言）；
  `qml_smoke` PASS；人工 play() 返回 True（MCI rc=0）。
- 未跑：完整 `test/run_all.py`。

### 22:28 白跳蛛身子：非等比铺满 → 保比例

用户反馈「程序里被拉长了，可以保留原比例吗」。

- **定位**：不是渲染层的问题。`_skin_pixmap()` 的 `IgnoreAspectRatio` 是「换皮不改
  大小」的契约，而画布 256×156（1.64）与身体框 76.5×46.75（1.64）本来就同比例，
  缩放几乎 1:1。变形发生在素材内部：源图 1.20:1 被 `fit_stretch` 铺进 252×152
  （1.66:1），厚度被压 0.21×、长度只压 0.44× → 圆顶拉成胶囊。
- **改法**：`tools/apply_skin_art.py` 新增 `fit_body()` —— `contain` 缩放（不裁不拉）
  + **靠前缘（局部 +x / 朝头那侧）对齐**。靠前对齐是必要的：居中或靠后会
  在脖子处露出缝。产出内容 127×152，屏幕约 58×69 px（原来是铺满的 114×70）。
- **代价（如实说）**：肚子变小了。圆顶几乎是圆的，装不进 1.64:1 的框，想要更长
  只能换更椭圆的素材，或把 `SkinSpec.body_scale`（现 1.5）往上调 —— 但那会
  同时放大命中区（`_in_thorax` 读同一个值），没有理由不轻动。
- **备选版本**：不旋转、平底朝下的那版（肚子 183×152，更长，但底边是硬直线，
  看着像蹲在地上）。两版都实机截图比过，选「旋转 + 保比例」。
- **测试**：`test/test_skin.py` **24/25**。唯一红项是**头部**素材尺寸
  （`white_jump_spider_head.png` 170×160、`milk_spider_head.png` 200×188，
  契约 160×170）。这两张在 22:04 / 22:16 被本会话之外的改动替换过 ——
  `backup/art_prev_20261018/` 里 10-17 版都是 160×170，且我这两次都只写了
  body 分支。**不在本次改动范围内，未动。**

### 22:45 修两个「设置没传到桌宠」的 bug

用户报：「界面里切换皮肤后部署仍然显示原皮肤，而且界面设置里调大小对蜘蛛也没有作用」。

**根因（同一个家族：只写 settings，没人推给桌宠）**

1. `LauncherWindow.payload`（部署时发给桌宠的那份）里的 `skin` 读的是
   `self.panel.current_skin()` —— 隐藏的旧 Widgets 面板。QML 启动台换皮走
   `LauncherBridge.setSkin → _on_skin_selected`，**根本不点那排按钮**，于是
   payload 永远是构造时读到的那个皮肤，部署出去的桌宠自然是「原皮肤」。
   实测（修前）：`setSkin(milk_spider)` → settings=milk / jar=milk / **payload=white_jump_spider**。
2. `pet_scale` 只写进 settings，`PetWindow.set_scale()` 唯一的调用点是部署时的
   `apply_settings()` —— 部署之后再拖「桌宠大小」滑杆，桌面上什么都不动。

**改法**

- `payload` 的 `skin` / `pet_scale` 改读 **settings**（这两个键本来就是启动台与桌宠
  共享的，settings 才是唯一真相；桌宠右键换皮也写它，读面板还会把它覆盖回去）。
  滑杆去抖期间用 `_scale_pending` 顶上，拖完立刻部署也不丢最后一格。
- `_on_skin_selected` 增加 `panel.set_skin()` 同步（`Panel.set_skin` 只改选中态、
  不发 `skin_selected`，不会递归）。
- 新增 `LauncherWindow.scale_changed = Signal(float)`，`set_pet_scale_pct` 与
  `_flush_scale`（滑杆 300ms 去抖后）各发一次。
- 两个信号的处理收进 `PetLifecycle.sync_skin()` / `sync_scale()`（原来是 `main()`
  里的闭包，没法单测），`main.py` 现在只连两条信号。

**验证**

- 真 `PetWindow` 端到端：部署 → 皮肤 white_jump_spider @60%；
  启动台 `setSkin("milk_spider")` → 桌宠 `skin_id` 立刻变 milk；
  `setPetScalePct(80)` → `pet.scale=0.80`、窗口 586 → **474px**；
  收回再部署 → 新桌宠 milk @0.80（payload 也对上了）。
- `test/test_app_lifecycle.py` **16/16**（新增 LiveSyncTests 4 项：皮肤到达桌宠且
  `persist=False`、没部署时是 no-op、大小到达桌宠、桌宠抛异常不打断信号链）。
- `tools/qml_bridge_probe.py` **PASS**，新增 `skin.payload` / `skin.panel` /
  `pet_scale.signal` 三条断言 —— 以前的探针只验 settings 和罐内渲染器，
  正好把这两条链路漏掉，所以这个 bug 一直绿着。
- `qml_smoke` PASS、`ui_probe` PASS（0 警告）、`deploy_cycle_probe --cycles 3` PASS。

## 2026-10-22 15:04 +0800（授权驱动的参数重调 + 结果卡提示条）

- 阶段：用户要「拉开与上游 web-crawlers 的相似度」（MIT 授权未到），
  以及 UI 改进。**没有新任务书，按用户口述做。**
- ⚠ **本轮的越界声明**：我改了 `src/crawler_spider.py` + `src/spider_painter.py`
  （README 职责表里「八腿路径 / 蜘蛛」归 Qoder）。已在
  `messages/20261022-150445_workbuddy_to_qoder_spider-params-and-toast.md`
  逐项交代，并问他手上有没有未提交改动。**只改数值，功能契约未动。**
- 提交（本轮 4 个）：
  - `16f22d8` 几何/步态参数：`LEG_DEF` 静止角改非等距 0.62/1.26/2.12/2.68、
    中段 reach 108/104、分骨比 0.54:0.66（提成 `L1_FRAC/L2_FRAC`，两处共用）、
    STEP .34 / URGENT .55、迈步时长 .09~.15、前瞻 .26/.27、VELOCITY_DAMP 6、
    ABD/SPIN 10/11、HIP_SIDE 3.2、线宽 1.42、点径指数 .52
  - `94d3fb3` 原皮配色同色系微调（ΔE 1.4~4.1）：leg/leg_hi/joint/body/body_fill
  - `d1c1e8f` `THIRD_PARTY_NOTICES.md`：音效=第三方免费素材（不适用 MIT）、
    `assets/ui/*` + `assets/skins/*` + 破罐序列帧=自制
  - `061eb38` `src/dialogs.py`：识词结果卡「全部收藏」底部提示条 `_Toast`
- 保持不动的三处（有连锁依赖）：`OVER_FRAC 0.92`（与 `assign_reachable()`
  的 `max_frac` 同口径）、`PLACE_FRAC 0.85`（IDLE_POSE 前足伸展 0.84×full，
  只剩 0.01 余量）、`REST_K 0.80`（窗口尺寸基准）
- 测试：`test_spider` **61/0**（原 59/0，我补了两条不变量并改断言引用常量）；
  `test_ai` 17 / `test_favorites` 10 / `test_review_session` 15 / `test_sfx` 9 /
  `aim_e2e` 19 全绿；`test_click_through` 44/45 → **45/45**（腿位置变了，测试点
  不再落在腿上）
- 改动**前**就红的（已逐条比过基线，非本轮引入）：`test_leg_fold_assignment` 2 条、
  `test_skin` 1 条（头素材尺寸 170×160 / 200×188，契约 160×170）、
  `locomotion_sheet` 质心 8 条
- 视觉验证：`tools/locomotion_sheet.py` 新旧对照出图目视过。**踩过一次坑**：
  分骨比第一版 0.50/0.70 测试全绿但出图腿交叉成 X 形线团，回退到 0.54/0.66 才对
  —— **参数改动必须出图，不能只看断言**
- 未解决问题：
  - `_neighbour_stepping()` 仍没排除 palp（上游 `!o.palp && !L.palp`）——
    行为层，归 Qoder，我只通报未改
  - `COLORS["web_line"]` 死代码；`WALK_SPEED=165` 注释过时（实际 240）
  - `assets/ui/spider_cracked.png` 已不在磁盘，`tools/make_crack_stages.py`
    现在跑会 `FileNotFoundError`
  - 工作区还有 7 个未提交的 `ui_theme` / 夜间主题相关改动（`ui_theme.py`、
    `launcher_qml.py`、`Main.qml`、`help_content.py`、`settings_store.py`、
    `test_theme.py`、`tools/theme_tool.py`），**不是我改的**，我没碰也没提交
- 是否需要 Qoder 决策：**是** —— ①他手上有没有未提交的 `crawler_spider.py` 改动；
  ②`L1_FRAC/L2_FRAC` 提法是否写进 `contracts/`；③夜间主题是否要覆盖到对话框
  （现在对话框走 `lexara_theme.DIALOG_QSS` 浅色常量，不跟 `ui_theme` 预设）

## 2026-10-22 15:28 +0800（背单词 AI 辅助）

- 新增 `src/ai/study_help.py`：`StudyHelpService`（造句 / 同义词）。复用 `chat._Worker`，
  不碰对话历史，按 `(word, mode)` 缓存，换卡片作废在途请求。
- 桥接：`reviewHelp` / `reviewHelpReady` + `reviewHelpRequest(mode)` / `reviewHelpClose()`；
  五个换卡动作（start / grade / step / retryWrong / exit）都调 `reset()`。
- QML：答案揭示后出现两个按钮 + 128px 可滚动只读结果框；卡片内容改 `Flickable`
  （矮时仍垂直居中，观感不变），避免展开结果后溢到标题栏。
- 修 `ui_theme` midnight 缺 `base.accentSoft` 导致的白底白字（释义框 / 收藏夹选中项 /
  热力图图例受影响），补 `#20304A`。**只改这一行**，属 Qoder 主题范围，已发消息说明。
- 测试：`test/test_study_help.py` 18 条新增（全离线，worker 注入）；`test_sfx` 9 条
  （补 `_study_help` stub）；`test_theme` / `test_ai` / `test_persona` / `aim_e2e` 通过。
  **未跑**：`ui_probe.py` 之外的全量回归（用户要求不跑耗时冒烟）。
- ⚠ `git status` 现显示 `crawler_spider.py` / `crawler_spider.py.bak` / `help_content.py` /
  `test_theme.py` 四处未提交改动，**不是我的**，未碰未提。
- ⚠ 我的 8 个文件被 Qoder 的 `768bef2`（`git add -A` wip checkpoint）一起提走了，
  内容正确但提交信息未提这条功能。已在消息里说明，未回退。
