# Qoder · 状态

> 本文件只有 Qoder 编辑。WorkBuddy 只读。格式按任务书 §10。

## 2026-10-17 23:28 +0800

- 阶段：开工调查 + 环境重建 + 基线测试（任务书 §1）→ 准备进入任务 A（trainer）
- 已完成：
  - 读 `PROJECT_OVERVIEW.md` / `HANDOFF.md`（目录级）/ 两份任务书 / WorkBuddy 首条消息；
  - 定位真实实现：`src/ocr_engine.py`(602行) `src/capture.py` `src/pet_window.py::OcrWorker`
    `src/aim_overlay.py` `src/crawler_spider.py::assign_reachable` `src/lexicon.py::scan_text`
    `src/settings_store.py` `src/launcher_qml.py::LauncherBridge` `src/ai/*`；
  - **项目原本没有可用 Python 环境**：无 `.venv`，系统 Python 3.14（miniconda）缺
    `rapidocr_onnxruntime` / `onnxruntime`；`py -3.13`、`py -3.12` 是裸解释器。
    已按 `requirements.txt` 建 `.venv`（Python 3.13.15 + PySide6-Essentials 6.12.0 +
    rapidocr_onnxruntime 1.2.3 + onnxruntime 1.31.0 + opencv-python 5.0.0.93 +
    numpy 2.5.4 + pyinstaller 6.22.3）；
  - 建立 `communite/`（README 由 WorkBuddy 先建，我补 contracts + status + 回复消息）；
  - 发布两份契约草案：`contracts/ocr-result-contract.md`、`contracts/ai-provider-contract.md`。
- 修改文件：`communite/contracts/*`、`communite/messages/20261017-232700_*`、`communite/status/qoder.md`、
  新增 `.venv/`（未跟踪）
- 测试命令：
  ```
  APPDATA=<临时沙箱> PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv\Scripts\python.exe test\<t>.py
  ... tools\{shape_sheet,aim_e2e,aim_trigger_probe,fold_sheet,qml_smoke,qml_bridge_probe,ocr_regress}.py
  ```
- 测试结果：
  - `test/` 11 项：**全部通过**（基线）
    - 注意：`test_spider.py`、`test_thread_ocr.py` 在 GBK 控制台 **exit 1**，
      原因是 print 里 `↔`/`✓` 无法用 gbk 编码（`UnicodeEncodeError`），**非功能回归**；
      UTF-8 环境通过。打包脚本因为 `chcp 65001` 不受影响。
  - `tools/shape_sheet` PASS、`tools/fold_sheet` PASS、`tools/qml_smoke` PASS、
    `tools/aim_trigger_probe` PASS(13/13)
  - `tools/aim_e2e`：**首跑 exit 127 空输出**（HANDOFF §8.6 已知瞬时崩溃），单跑 PASS —— 记为既有不稳定项
  - `tools/qml_bridge_probe`：**FAIL 1 项 `pet_scale`（既有缺陷，非本次引入）**
    根因已定位：`LauncherBridge.setPetScalePct()` → `scale_slider.setValue()` →
    `_on_scale_changed()` 有 **300ms 去抖** 才写盘；probe 立刻读 `settings` 拿到旧值。
    真实风险：用户拖完滑杆 300ms 内退出会丢设置。已在消息里认领修复。
  - `tools/ocr_regress`：**FAIL（既有）**——硬编码 `C:\Users\35388\Desktop\2af1acd1….png`
    / `2ffaf0ed….png`，而这两张图现在在项目 `Trainer/` 下 → `cv2.imread` 返回 None →
    `cvtColor` 断言崩。将由 `trainer/scripts/evaluate_ocr.py` 取代。
- 性能数据（如适用）：RapidOCR 在合成小图上可用（`test_thread_ocr`：2 行识别，主线程/子线程结果一致）；
  引擎冷启动秒数将在 trainer 报告里给中位数/P95。
- 未解决问题：
  - 本会话**只有一块普通 DPI 显示器**，125%/150% DPI、多屏偏移、真机视频字幕场景无法实测，
    到时会标注「未验证」而不是「通过」；
  - PaddleOCR 尚未在独立环境验证（任务书 §3.1 要求），保持 `unavailable`；
  - `git` 仓库不存在（`fatal: not a git repository`），无法用 diff 区分并发改动 ——
    已改为「按文件所有权协商」（见发给 WorkBuddy 的消息 §5）。
- 下一步：任务 A —— 建 `trainer/`（沿用/收纳既有 `Trainer/` 素材），
  合成样本生成器 + JSONL ground truth + 双引擎评测脚本 + 漏识别可视化。
- 是否需要 WorkBuddy 决策：是 —— 见 `messages/20261017-232700_qoder_to_workbuddy_engine-status-and-scan-contract.md`
  的 Required action 四条（引擎接口形状 / 扫描状态字段 / AI 从默认链路移除 / `pet_scale` 归我修）。

## 2026-10-18 00:40 +0800

- 阶段：任务书 §2（trainer）+ §4（词框贴合）+ §5（本地先行 / AI 按需）已完成并跑过回归；
  下一步进 §6 连续扫词队列。§3（PaddleOCR）**未开始验证**，见「未解决问题」。
- 已完成：
  - **§2 trainer**：`Trainer/scripts/generate_synthetic.py`（修 `np.random.default_rng` 用法）
    产出 35 张合成样本 / 561 个标注词 → `datasets/manifests/generated.jsonl`；
    `evaluate_ocr.py` 统一归一化 + 词级 P/R/F1 + 四边偏差 + IoU + 分场景召回 + DPI 偏移，
    新增 `--report-only`（不重跑 OCR 只重出报告）；
    `visualize_misses.py` **只可视化出问题的那些**：漏字（橙虚线）/错字（黄）/多余（蓝）/
    粘连（紫）/IoU<0.5（洋红），输出 `Trainer/reports/misses/*.png` + `_overview.png` + `index.md`
    （本轮 19/35 张被标记）。
  - **§4 词框贴合**：`ocr_engine._snap_edges` 重写为「按词自适应吸收墨迹游程」
    （`_ink_runs` / `_grow_run`）+ 空白列中心吸附 + 退化框保护 + 逐词行投影收紧高度；
    `OcrWorker` 把词本体框（图像像素）经 `locate()` 换算成 `screen_box`（逻辑像素，与 `screen_pos`
    同一套 DPR 换算，单一换算点）；`AimOverlay._cache_boxes()` 优先用 `guide["fit"]`，
    画的是词本体 + 1.5px 内边距 + 四角刻度 + 词性小标签，**不再另估一只飘在词上方的框**；
    回退开关 `LEXARA_OCR_REFINE=0`；细化异常不再静默吞掉，记进 `REFINE_ERRORS` 并由测试断言为空。
    新增 `test/test_word_box_fit.py`（29 项：长短词混排/带标点撇号/斜体/紧挨短词 的 IoU、
    高宽比、Δy、DPR 1.0/1.25/1.5 换算、覆盖层用 fit 框、框中心==腿落点）。
  - **§5 本地先行 + AI 按需**：`LearningRouter.prepare_local()`（零网络、不夹 8 词）接管默认链路，
    `select()` 保留原行为给显式调用；新增 `ai/context_request.py`
    （`build_request` 只含文本、`parse_context` 强校验、`ContextRequest` QThread + 可取消、
    `request_word_context(transport=…)` 供离线单测）；`dialogs.WordResultDialog` 每卡加
    「AI 语境分析与造句」按钮，覆盖 未配置 / 请求中(可取消) / 成功 / 失败(可重试) / 取消 五态，
    整卡限流 1 个在途请求，`closeEvent` 回收线程；桌宠气泡文案改为如实的「本地词典认出 N 个词…」。
    新增 `test/test_ai.py` 11 项 + `tools/result_card_probe.py` 26 项（含「全程零网络」红线探针）。
  - **回归基建**：`test/run_all.py` —— 每个测试文件**独立子进程**跑。
    原因：`test_fold/click_through/aim_hold/leg_stretch` 在 import 期就设
    `QT_QPA_PLATFORM=offscreen`，`unittest discover` 先 import 全部再执行，
    会把 `test_ai` 的真 OCR 图渲染成不可读（假失败），并且 `QApplication` 单例会互相炸。
  - 修掉一个被记成「偶发竞态」的**真崩溃**：`aim_e2e` exit 127 空日志 =
    `AimOverlay.paintEvent` 里 `KeyError('box')`（`_assign()` 没跑 `_cache_boxes()`），
    Qt 把 paintEvent 的 Python 异常直接带走进程。现在 `_assign()` 末尾会缓存框。
- 修改文件：
  - 源码：`src/ocr_engine.py`、`src/pet_window.py`、`src/aim_overlay.py`、`src/ai/router.py`、
    `src/dialogs.py`
  - 新增：`src/ai/context_request.py`、`test/test_word_box_fit.py`、`test/run_all.py`、
    `tools/result_card_probe.py`、`Trainer/scripts/visualize_misses.py`
  - 修改：`Trainer/scripts/generate_synthetic.py`、`Trainer/scripts/evaluate_ocr.py`、
    `test/test_ai.py`、`PROJECT_OVERVIEW.md`（§2.5 段落改写为「本地词典先行 + AI 按需」）
  - 文档/通信：`communite/contracts/ai-provider-contract.md`（v0 草案，签名以本文件为准）、
    `communite/messages/20261018-003500_qoder_to_workbuddy_ai-on-demand-and-box-fit.md`
  - **没有**动 `launcher_qml/*`、隐藏 `LauncherWindow` 控制器、`ai/config.py`（WorkBuddy 所有权）
- 测试命令：
  ```
  PYTHONIOENCODING=utf-8 .venv\Scripts\python.exe test\run_all.py
  PYTHONIOENCODING=utf-8 .venv\Scripts\python.exe Trainer\scripts\generate_synthetic.py --profile full
  PYTHONIOENCODING=utf-8 .venv\Scripts\python.exe Trainer\scripts\evaluate_ocr.py --engine rapid --profile full
  PYTHONIOENCODING=utf-8 .venv\Scripts\python.exe Trainer\scripts\visualize_misses.py --engine rapid
  LEXARA_OCR_REFINE=0 ... evaluate_ocr.py            # A/B 回退对照（见「未解决问题」第 4 条）
  ```
- 测试结果：
  - `test/run_all.py`：**15 个文件全通过 / 累计 383 项检查，exit 0**
    （spider 59、leg_stretch 15、fold 30、spin 13、skin 25、click_through 45、aim_hold 32、
    ocr_coords 6、word_box_fit 29、industry 52、review_session 15、thread_ocr exit0、
    ai 17、result_card_probe 26、aim_e2e 19）。日志：`dist/logs/regression_task6.log`。
  - 与基线对比：**无回归**。上一轮的 `aim_e2e exit 127`、`test_ai` 里
    「默认识词等云端」的隐式行为，本轮分别转为「19/19 通过」与「零网络断言通过」。
  - trainer 全量评测（35 图 / 561 真值词，rapid 引擎）：
    召回 82.0%、精确 83.5%、F1 82.7%、**IoU 均值 0.853**、墨迹细化 100%、
    空结果 0%、异常 0%。报告 `Trainer/reports/compare_20261018-001125.md`。
- 性能数据：
  - 词框细化**没有拖慢识别**：耗时中位 1425.8ms → **1372ms**，P95 6605.1ms → **6169ms**
    （细化本身是投影运算，量级 µs；P95 变化来自 tiling 路径）。
  - 召回代价：82.53% → 82.0%（-0.53pt，在 IoU/框收紧改造里属噪声级；漏词大头是
    `bg_noisy` / `distract_mixed` / `dynamic_subtitle_seq` 这类场景与数据集标注粒度问题）。
  - 默认链路网络耗时：**0**（改造前配了 key 时最坏 12s 同步等待）。
  - `test/run_all.py` 全程 15 个进程串行 ≈ 70s。
- 未解决问题：
  1. **PaddleOCR 完全未验证**（§3）：独立 venv 还没试装，`ocr_engine` 的
     `settings.ocr_engine → ocr_adapter.configure()` 接线也没做。
     当前 UI 里它必须是 `unavailable`，我不会先改成 available。
  2. **§6 连续扫词未开始**：`aim_overlay` 里 `[:8]` 截断、`settings_store.BOUNDS["max_words"]`
     夹 8 仍在，>8 词目前仍会丢第 9 个之后的词 —— 这是下一步的主任务。
  3. **§7 蜘蛛感应未开始**；**§8 的 `communite/` 只有我的部分**。
  4. `LEXARA_OCR_REFINE=0` 的 A/B 对照**只跑过一次口头对比**（IoU 0.730→0.853 的那组数字来自
     两次全量评测），还没在报告里做成正式的双列表格。
  5. trainer 的 `real_world/` 子集与 `Trainer/README.md`（标注字段权威定义）**还没写**；
     `layout_code_subtitle` 的 ground truth 是行级、`distract_mixed` 含 URL/数字/CJK，
     属数据集缺陷，需按 §2 修正后重测。
  6. 125%/150% DPI、多屏负坐标、真机视频字幕场景：本机只有一块普通 DPI 屏，
     **只做了数学换算层面的验证**（`test_word_box_fit` 的 DPR 段落），
     真机多屏/高 DPI **未验证**，不写成通过。
  7. 双列跨栏粘连（`docsspider` / `machinethunder`）是引擎真实弱点，
     没有用「伪造文本切分」掩盖，保留为已知限制。
- 下一步：§6 —— 新建 `src/scan_session.py`（词级 `word_id` 状态机 + 阅读顺序/最近邻路径 +
  八腿分批再分配 + 暂停/继续/取消 + 完成统计），并拆掉三处 8 夹。
- 是否需要 WorkBuddy 决策：是 —— 见
  `messages/20261018-003500_qoder_to_workbuddy_ai-on-demand-and-box-fit.md`
  第 3 节两件事（QML 文案对齐「本地词典 / 按需 AI」；是否能提供「打开 AI 设置面板」的入口信号），
  以及第 1 节末尾：`prepare_local` 实际签名多了首位 `text`，`max_words` 的 8 夹要和队列一起放。

## 2026-10-18 01:15 +0800

- 阶段：**任务书 §6（连续扫词 / 八腿=并行度）已完成并跑过回归**；
  上一条列的「§6 未开始、>8 词会丢第 9 个之后的词」已作废。下一步 §7 蜘蛛感应。
- 已完成：
  - **`src/scan_session.py`（新）**：词级状态机 `pending/active/completed/skipped/failed`；
    稳定 `word_id = "<source>:<surface>#<n>"`（同词出现三次是三个独立目标，
    文本单独作键的老毛病从根上去掉）；行优先 + 同行最近邻路径；
    八腿分批再分配（`LEG_COUNT=8` 只是并行度）；`start/pause/resume/cancel`；
    `stats()`/`summary()` 给出 `total/pending/active/completed/pegged/box_only/
    skipped/failed/batches/remaining`。纯 Python、不 import Qt、时钟可注入。
  - **两处死锁/幂等修复**（都是先失败再定位的）：
    ① `start()` 改幂等 —— 非幂等版本对已在途的批次再调一次会重开一批、把在途丢掉
    （症状：`test_one_word` 完成数 0、腿收回来不再伸出）；
    ② 加 `DEFAULT_STALL=0.9` 的「卡住的批次先重派、三次仍不落位才记 failed」——
    原来的 `attempts > MAX_ATTEMPTS` 对从没落过位的词永远不涨 attempts，
    **等于队列死锁**（第 9 个之后的词会一直卡在 active）。
  - **`src/aim_overlay.py` 重构为「腿 / 框 分离」**：腿只踩 `current_batch()`；
    框画队列里**每一个**词，还没轮到的 `lit=0.42` 淡一档（不是消失）；
    配对与落位回执全程用 `word_id` + `id(cs_target)`；腿长倍率改按**当前批**最远词算，
    且 `_on_batch` 里立刻取值（可达判断必须看到真实腿长），缩短走 `_ease_stretch` 缓动；
    点蜘蛛身体=暂停/继续、点词=释义、点别处=收起；`closeEvent` 里先 `session.cancel()`
    再清腿目标并把 `on_progress` 摘掉。
  - **拆掉六处 8 夹**（>8 词不再丢词）：`settings_store.MAX_WORDS_RANGE=(1,48)` +
    `DEFAULTS["max_words"]=24` + `BOUNDS` 由区间推、`qml/Main.qml` 滑杆 1~48、
    `launcher_qml.py` 与 `launcher_window.py` 改引用共享常量、`dialogs.ModeDialog`
    选项 4/8/16/24/48（并修掉 `findData` 失败时 `else 2` 静默改写存储值）、
    `pet_window` 默认取 `DEFAULTS`、`OcrWorker` 候选池 `max(48, limit)`。
  - **WorkBuddy 的 blocker（01:05）已修**：`_assign()` 漏了 `.item` 解包导致
    `TypeError: 'ScanTarget' object is not subscriptable`。按他提的**方案 B**
    走属性/`.item`，**没有**加 `__getitem__`、**没有** try/except 静默降级；
    契约新增 §3.1 写死「词卡字段只能读 `target.item[...]`」+ 属性清单。
  - 契约 `contracts/ocr-result-contract.md` 按实现口径更正：`word_id` 实际格式、
    字段名是 `state` 不是 `status`、`summary()` 字段清单，
    并**明确标注还没做的**：Qt Signal（`stateChanged/progress/...`）与
    `engine_id`/`avg_ms_per_word`（属 §3 引擎任务）。
- 修改文件：
  - 我的：`src/scan_session.py`(新) `src/aim_overlay.py` `src/pet_window.py`
    `src/settings_store.py` `test/test_scan_queue.py`(新) `test/test_aim_hold.py`
    （新增 E1–E19）`test/run_all.py`（把队列用例加进 CASES）`tools/aim_e2e.py`
    （`_pairs` 三元组→四元组）`communite/contracts/ocr-result-contract.md`
  - **动了 WorkBuddy 的文件（已发消息告知，请他复核）**：`src/qml/Main.qml`
    `src/launcher_qml.py` `src/launcher_window.py` `src/dialogs.py` —— 四处都只是
    把写死的 8 换成 `settings_store.MAX_WORDS_RANGE`/`DEFAULTS`。
  - 通信：`communite/messages/20261018-011200_qoder_to_workbuddy_scantarget-fix-and-scan-queue-done.md`、
    本文件。
- 测试命令：
  ```
  APPDATA=<临时沙箱> PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv\Scripts\python.exe test\run_all.py
  单项：test\test_scan_queue.py / test\test_aim_hold.py / test\test_word_box_fit.py
  ```
  ⚠️ **不要**给子进程设 `QT_QPA_PLATFORM=offscreen`：会做出「画出词框但 OCR 认出 0 词」的
  假失败（我踩过一次，`test_word_box_fit` 10/5 → 正常环境 29/0）。
- 测试结果：
  - **全量回归 `test/run_all.py`：16 个文件、累计 432 项检查，全部通过，exit 0**
    （含新增的「连续扫词队列（§6）30 项」）。
  - `test/test_scan_queue.py`：**30/30 OK**（0.009s，纯逻辑：阅读顺序、跨行、双列、
    同词重复、暂停/继续/取消、0/1/8/9/16 词、卡住重派、守恒式、`word_id` 写回词卡）。
  - `test/test_aim_hold.py`：**51/51**，其中新 **E1–E19**（24 词 6×4 网格、假时钟真跑 Qt 覆盖层）：
    E1 24 词全进队列、E2 首批 8 条腿、E3 24 只框、E5 全部踩完（完成 24/待办 0/在途 0/失败 0）、
    E6 3 批、E7 不重复计数、E8 完成+失败+跳过==24、E9 框不被抹掉、E10 提示条「已全部踩完」、
    E11–E13 暂停冻住→继续走到完、E14/E15 身体点击判成暂停而非收起、E16 状态翻转、
    E17 中途关闭无在途残留、E18 未轮到的计 skipped（8+16+0）、E19 腿长归位。
  - `test/test_word_box_fit.py`：**29/0**（blocker 复现路径 ③ 覆盖层 8/8 贴合）。
  - `tools/aim_e2e.py`：19 项通过（这次**没有**复现历史 exit 127，但那是偶发项，不写成「已根治」）。
- 性能数据：
  - 队列调度开销可忽略：30 个用例 0.009s（≈0.3ms/用例），每帧 `tick()` 是 O(批大小)。
  - 24 词整队列在假时钟下 3 批走完、2400 帧内收敛（E5/E6），该文件含全部 E 段 wall time 2.3s。
  - 识别侧耗时未被本阶段改动：中位 1372ms / P95 6169ms（上一条的数字，仍有效）。
  - 默认链路网络耗时仍为 **0**。
- 未解决问题：
  1. **§7 蜘蛛感应未开始**。
  2. **§3 PaddleOCR 仍未验证**（上一条第 1 点仍有效）：独立 venv 试装、
     `settings.ocr_engine → ocr_adapter.configure()` 接线、UI 真状态暴露都没做，
     引擎在 UI 里保持 `unavailable`，不会假切换。
  3. **`summary()` 没有 Qt Signal**，进度靠覆盖层每帧拉 + `on_progress` 回调记日志；
     UI 侧要做真进度条需先定 `ScanSession` 的持有者（已在消息 §4.2 请 WorkBuddy 决策）。
  4. **同词多次出现只出一张释义卡**：`lexicon.scan_text` 按 lemma 去重，队列层 `word_id`
     独立但卡片共用 —— 已知限制，未掩盖（改它要动 WorkBuddy 的结果卡形状）。
  5. **够不着的词**按 `box_only` 当场结掉（只亮框不踩）—— 不然队列换不到下一批；
     UI 文案不能把它说成「全部踩到」。
  6. >8 词的**真实人工目测**（真鼠标框选一大段文字看它一批批走完）仍未做，
     E 段是假时钟 + offscreen-free 的 Qt 层验证，不等价于真人观感；125%/150% DPI、
     多屏负坐标同样**未验证**。
  7. trainer 遗留（上一条 5–7 点）：`Trainer/README.md` 标注规范、`real_world/` 子集、
     `LEXARA_OCR_REFINE=0` 正式 A/B 表、`layout_code_subtitle` 行级 GT 修正。
- 下一步：§7 蜘蛛感应（截屏 → 变化检测/ROI → OCR 子线程 → 去重缓存 → 短线提示 + 高亮 →
  本地释义；独立开关与状态；节流约 1~2 次/秒作为**实测起点**；排除自己的窗口；退出清理；
  文案不出现「无限扫描 / 零成本」）。
- 是否需要 WorkBuddy 决策：是 —— 见新消息 §4 三条（同词多次出现的卡片形状、
  `ScanSession` 持有者与是否要 Qt Signal、`box_only` 的 UI 文案口径），
  以及 §3 请他复核我动的那四个 launcher/dialogs 文件。

> **给明天的自己**：§6 已闭环，无未跑项。开工顺序 = ①`git` 仍无，先看
> `communite/status/workbuddy.md` 有没有新留言/是否复跑绿了 ②直接进 §7 ③
> PaddleOCR 那条别再往后拖。命令模板见上面「测试命令」。


## 2026-10-18 15:40 +0800

- 阶段：**用户下午明确指令 ——「先不做蜘蛛感应，也不换 PaddleOCR，暂停任务写文档」**。
  所以下面是**冻结点存档**，不是完成存档。§7 的真实状态必须这样读：
  **代码已实现、逻辑单测全绿、真桌面端到端没跑绿（而且中途崩）** —— 不能当已完成，
  任何 UI 文案都不许把它写成可用能力。§3 按指令**停在 `unavailable`**（不假切换）。

- 已完成（本轮 = §7 的性能治理，每一条都是实测驱动）：
  1. **整条 §7 流水线在位**：GUI 线程抓屏 → `SenseWorker(QThread)` → 缩略图 4×3
     格均值差变化检测 → 变化格并成 ROI → 行段切分 → 纯色闸门 → OCR → 词典挑词 →
     队列调度（新内容优先）→ 覆盖层短线/射线 → 点词出本地释义卡（AI 仍由用户触发）。
     开关独立、状态可见、出错自动暂停**不自动重启**、退出清理线程与捕获。
  2. **行段切分 `_tighten_bands`**（`src/sense_worker.py`）：按「哪几行有墨」把 ROI
     横切成 ≤`TIGHT_MAX_ROWS=160` 的条带，一轮最多喂 `MAX_BANDS_PER_ROI=4` 段。
     依据：本机 OCR 成本正比于**一段里有几行字**，不是像素面积
     （`dist/sense/shape_probe.log`：同一句字幕整块 505×1970 = 4657ms，
     收成一条行段 = 1254ms）。
  3. **轮预算 `round_budget_ms`**（默认 `min(1200ms, session.budget_ms)`）：一轮里累计
     OCR 时间超预算就不再开新块，整块顺延。**这条治的是「感应开十几秒自己停」的真因**：
     旧代码把一轮最多 6 块 / 整帧全跑完，真桌面上「一轮」= 9~19 秒 →
     被 §7.4 的降频/暂停判据读成「这台机器跟不上」。
  4. **顺延表 `defer_roi/take_deferred/pending_deferred`**（`src/sense_session.py`，
     `DEFER_MAX=8`）：没读完的块带**行段游标**存下来，下一轮即使画面没变也补读，
     挤爆了才丢并计数 `roi_dropped` —— 「读不完」不等于「静默丢词」。
  5. **段级去重键**：ROI 缓存键从 `r2c0,r2c1` 变成 `r2c0,r2c1#2`（块 + 第几段），
     否则同块换段会被上一段的结果判成「没变」而压掉。
  6. **退出收尾**（`src/pet_window.py`）：`_stop_sense()` 只等 3 秒（再多就是把界面冻住），
     没退出的线程记进 `_sense_lingering`，`shutdown()` 用 `_drain_sense_workers()` +
     `SENSE_EXIT_GRACE_MS=12000` 收尾，等不到就写日志「仍有 N 个未退出」——
     **不假装等到了**。
  7. **OCR 限核（用户可感知的行为变化，WorkBuddy 必读）**：`src/ocr_engine.py` 新增
     `DEFAULT_THREAD_LIMIT = 2` + `set_thread_limit()` / `thread_limit()`，
     `OcrEngine.stats()` 多一个 `threads` 键。
     原因：`rapidocr_onnxruntime` 的 `OrtInferSession` 把 `SessionOptions` 写死了，
     `intra_op_num_threads` 留默认 0 = 「onnxruntime 按机器核数自己开线程池」，
     本机 32 逻辑核 → **一次识别把 27 个核点着**，这就是「一开感应风扇就狂转」的机制。
     实现是在建会话那一刻把值按进 `SessionOptions`（补的是 rapidocr 模块里绑好的那个
     `InferenceSession` 名字，改 `onnxruntime.InferenceSession` 对它无效），建完还原。
     **用户 2026-10-18 选的是「2 核 + 全局一起」**，所以 ①八腿扫描 ②连续扫词 ③感应
     和启动预热**都**受影响。
     实测（`tools/sense_threads_probe.py`，同一批清晰单行合成文字，各 4 轮）：

     | 线程上限 | 单次中位 | 满载核数中位（= 一次识别的 `process_time/wall`） | 最大 | 读出总行数 |
     |---|---|---|---|---|
     | 不夹（原行为） | 160.7ms | **26.99** | 32.95 | 16 |
     | 夹到 4 | 59.1ms | 9.09 | 15.61 | 16 |
     | 夹到 2（现默认） | 71.7ms | **3.14** | 9.34 | 16 |

     感应 ROI 的常见小形状（200×40、13px 小字）另测：不夹 墙钟 1677ms / CPU 25.27s /
     15.1 核 → 夹 2 核 墙钟 2414ms / CPU 4.8s / 2.0 核，**行数没掉**。
     诚实口径：**单次识别慢约 44%** 是物理账（同样算力摊到更少核上）；而
     「满载核数 15.1」比 bench 报的「平均 1.2 个核」更能解释体感 —— 后者是含 93%
     空闲的整段大平均，两回事。
  8. 新增 3 个取证脚本（只用本地画的图，不联网、不落用户内容）：
     `tools/sense_shape_probe.py`（形状-成本表 → `dist/sense/shape_probe.log`）、
     `tools/sense_smallroi_probe.py`（小 ROI 整块 vs 切段）、
     `tools/sense_threads_probe.py`（限核前后的满载核数）。

- 修改文件（本轮，全是我这边的）：
  - `src/sense_worker.py` `src/sense_session.py` `src/pet_window.py` `src/ocr_engine.py`
  - `test/test_sense_worker.py`（25 项；新增「高 ROI 分几轮读完」「轮预算整块顺延」
    「整帧那轮也收紧」三条用例）
  - `test/test_sense_session.py`（50 项；只加了 `DEFER_MAX` 的 import）
  - `tools/sense_e2e.py`（[11] 的线程退出判据改成有界轮询）
  - `tools/sense_shape_probe.py` / `tools/sense_smallroi_probe.py` /
    `tools/sense_threads_probe.py`（新）
  - 证据：`dist/sense/shape_probe.log`、`dist/sense/bench_report.md`（15:07 版）、
    `dist/sense/run_all_threads2.log`
  - **没有动 WorkBuddy 的文件**：`src/qml/Main.qml`、`src/launcher_qml.py`、
    `src/launcher_window.py`、`src/dialogs.py`、`src/help_content.py` 一个都没碰。
    感应的设置读的是既有 `sense_hz` / `sense_enabled` 两键，**没有新建第二份配置存储**。

- 测试命令（沙箱 + 禁 offscreen，这两条违反过一次就记一次）：
  ```
  APPDATA=<临时沙箱> PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv\Scripts\python.exe test\run_all.py
  单项：test\test_sense_session.py / test\test_sense_worker.py / test\test_sense_overlay.py
  实测：tools\sense_bench.py（约 160s）/ tools\sense_e2e.py（约 120s，要真桌面）
  取证：tools\sense_threads_probe.py / tools\sense_smallroi_probe.py
  ```
  长 GUI 用例**不要**管到 `head`（SIGPIPE 会中途杀进程，数字变垃圾）；
  不要给子进程设 `QT_QPA_PLATFORM=offscreen`（OCR 认 0 词的假失败）。
  `sense_e2e.py` 会在真桌面上抓你当前屏幕（只在本机内存里过一遍，不落盘、不发网络），
  跑之前确认桌面上没有不想被认出来的东西。

- 测试结果（逐条：通过 / 失败 / 未运行）：
  - **全量回归 `test/run_all.py`：19 个文件通过 / 21，累计检查项 597，exit≠0**
    （`dist/sense/run_all_threads2.log`，15:07，限核后的引擎）。
  - `test/test_sense_session.py`：**50/50 通过**。
  - `test/test_sense_worker.py`：**25/25 通过**。
  - `test/test_sense_overlay.py`：**37 项通过**（坐标/DPI/穿透/自身窗口排除，逻辑侧）。
  - `tools/sense_bench.py`：**失败 33/35**（161.9s，exit=1）。挂的两条**不是产品退化，
    是判据口径过期**：`静态画面没有反复唤醒 OCR（跳过占多数）` 与
    `变化检测的判定和剧本对得上` 都写成「一轮 ≤ 一次 OCR」，而现在一轮可以是
    ≤4 个行段、静态轮还会补读顺延表（实测 10 跳过 / 10 次 OCR / 7 个变化轮）。
    **没有为了让它绿而放宽阈值**，改法记在「未解决问题 2」。
  - `tools/sense_e2e.py`（真桌面端到端）：**失败 —— 崩在第 [5] 步，18 项后
    exit=3221226505（0xC0000409）**，不是断言失败。崩点
    `src/sense_overlay.py:264 chip_rect` → `RuntimeError: libshiboken:
    Internal C++ object (SenseOverlay) already deleted`（调用方 `tools/sense_e2e.py:315`）。
  - 真桌面端到端**从未在新 build 上跑绿过**。`dist/sense/e2e_run3.log` 的
    33 通过 / 10 失败是**上一版 build**（行段切分与轮预算之前）的数字，
    不能引用成现在的状态。
  - §7.4 的**多屏 / 125%·150% 缩放**：真机用例**未运行**（本机只有 1 块屏，
    NE160QDM-NYM 1707x1067、dpr=1.50）；**遮挡 / 最小化**那两条在 e2e 的 [6]/[6b]，
    本次因崩溃**未执行到**（上一版跑过，不算现在的证据）。
  - §3 PaddleOCR：**按用户指令停**。UI 保持 `unavailable` + 真实原因，不出现假切换。
    已量的成本数据仍有效：依赖 +378MB、模型 +177MB，打包与否**未决**（现在也不用决）。
  - §2 `Trainer/`：标注规范 `README.md`、`real_world/` 真实现场照片集、
    `LEXARA_OCR_REFINE=0` 的正式 A/B 表、`layout_code_subtitle` 行级 GT 修正 ——
    **全部未运行 / 未产出**，只有已有的评测脚本与子集。

- 性能数据（本机 2026-10-18 实测，换机器要重量；口径写在括号里）：
  - 捕获（GUI 线程，2560×1600 物理像素）：`grabWindow` 中位 **84.2ms** +
    `QImage→ndarray` 中位 14.2ms = 单次中位 **99.6ms**；1 次/秒时占 GUI 线程 **10.1%**。
  - 变化检测（12 格绝对差）：均 **7.1ms** —— 比 OCR 便宜两个数量级，这就是
    「屏幕静止时基本不烧钱」的根据。
  - 单轮 OCR（`bench_report.md` 15:07，限核后）：整帧 1920×1080 均 1797ms /
    中位 1292ms；单格 ROI 518×432 均 3087ms；**并集不收紧 1920×432 均 5278ms**（最贵）；
    线上路径收紧后 1621×65 均 **251ms**（省时 86%）；整屏都在换（滚动页）均 4533ms。
  - 流水线（17 轮剧本）：OCR 10 次（整帧 3 次、无变化跳过 10 次、纯色闸门挡 1 次）、
    收紧 7 次剪掉 3664 行 / 3154 列、单轮延迟 均 188ms · 近 5 轮中位 **145ms** ·
    P95 415ms、提示 16 次、缓存 ROI 5 条 / 词 25 条（上限 64 / 512）、降频 **0 次**、
    自动暂停 0 次。
  - 资源：**墙钟 56.55s · 进程 CPU 8.34s → 平均 0.1 个核满载**（限核前 1.2 个核）、
    OCR 占空 **3%**（限核前 7%）、工作集 204.8MB → 210.8MB（**+6.0MB**）。
  - 默认链路网络耗时 **0**（感应全程零联网，e2e 里 `NET` 守卫在跑）。

- 未解决问题（编号，接续者按这个顺序读）：
  1. **e2e 崩溃 = 覆盖层生命周期**（它阻塞一切验证，先修这个）。`sense_overlay.py:264
     ` 的 `chip_rect()` 在外部还持句柄时 C++ 侧已析构。要么产品路径里
     「自动暂停/出错」不该把覆盖层 `close()`（留着显示「已暂停」），要么调用方必须
     重新取 `pet._sense_overlay` 而不是缓存旧对象。**这条牵扯 UI 口径，见
     「需要 WorkBuddy 决策」(b)**。
  2. **bench 两条判据要改成段级口径**（是改口径，不是放宽阈值）：把「一轮 ≤ 一次 OCR」
     改成「静态轮不新开端到 `roi_deferred` 的段；变化轮的 OCR 次数 ≤ `MAX_BANDS_PER_ROI`」，
     报表从「每轮一次调用」改报「一轮几段 + 轮预算花了多少」。**改完必须重跑**，
     现在的 33/35 是混合口径，不能引用。
  3. **给接续者的方向修正（重要）**：`_tighten_bands` 的收益**只在大形状上成立**。
     `tools/sense_smallroi_probe.py` 实测真桌面那种 80×84 两格 ROI：整块一次送
     **1207ms**，切成两段送 790 + 405 = **1195ms**（等于没省；而两格各自单独送是
     448ms / 377ms）。对比 `shape_probe.log` 的大形状（4657ms → 1254ms）才看得清边界。
     真桌面被点亮的常常就是 1~2 格小 ROI，所以切段这层**实际收益有限**；
     真正救回来的是 `_is_blank` 纯色闸门 + 轮预算 + 顺延 + 降频。
  4. **限核到 2 之后「贵形状」的实测数据未运行**（只有便宜形状表 + 一次 15:07 bench）。
     贵形状 = 低对比小字、回退阶梯全跑那种（旧实测单段最长 14620ms）。
     夹核后单轮更慢 → 更容易触发 §7.4 的降频/自动暂停，要重跑 bench/e2e 才敢定值。
  5. `_is_blank` 只挡**纯色**块；「有色但低对比」的桌面块仍会进 OCR 并跑满回退阶梯。
  6. 感应的「新内容优先」目前只是队列语义（新词插队头、队尾挤掉，`QUEUE_MAX=16`），
     **真实忙桌面上的召回没有被量化过** —— 因为 e2e 还没跑绿。
  7. §2 / §3 的尾巴照旧（见上面「测试结果」）。
  8. **隐私自查结果**：`communite/` 里**没有**任何屏幕文本（已 grep 验证 0 命中），
     也没写过截图或 key；`sense_e2e.py` 的 `[12]` 那条守卫测的就是临时 `run.log`
     里不许出现识别到的单词，这条在旧 build 上是绿的。
     **但**本机取证日志 `dist/sense/shape_probe.log`、`card_probe.log/2/3`
     这 4 个文件**印出了识别到的屏幕单词**（探针为了对比「这段读到了什么」写的）。
     它们只在本地、从未外传，可按 §7.5「日志不记录用户内容」的严格口径它们不该留 ——
     恢复任务时把探针的这行输出删掉并清一次这几个 log。

- 下一步：**按用户指令 = 暂停，不做**。若恢复，顺序是
  ①修问题 1 的覆盖层生命周期 → ②按问题 2 改 bench 口径并重跑 →
  ③真桌面 e2e 迭代到绿**或如实标红**（不许放宽判据凑绿）→ ④再谈 §3 打包与 §2 trainer。
  任务书 §0 的 ①八腿扫描 ②连续扫词 仍是**已闭环**（上一条 16 文件 / 432 项全绿），
  本轮没动它们的逻辑，但**限核会改变识别延迟**，所以本次 `run_all` 里
  `test_scan_queue` 30/30、`test_aim_hold` 51/51、`tools/aim_e2e.py` 19/19、
  `test_word_box_fit` 29/0 这几条绿灯是新默认下重跑过的，可以引用。

- 是否需要 WorkBuddy 决策：**是，四条**
  (a) **不要**把 `src/help_content.py` 里感应的状态翻成 ready —— §7 未验证、
      e2e 还崩着，文案口径见随附消息。
  (b) **自动暂停/出错时覆盖层该不该收**？现在产品会 `close()`，结果外部旧句柄炸
      `RuntimeError`。我倾向「留着但灰掉并写『已暂停 · 原因』」（既是修 bug，也更符合
      §7.2「状态清楚可读」），但显示层归你，等你口径再动。
  (c) 你上次要的 `aim_overlay._hint_text` 的 `box_only` 文案，我没动，等你改或明确指令。
  (d) **OCR 限核要不要进启动台**？现在是代码里的 `DEFAULT_THREAD_LIMIT = 2`。
      要做成滑杆就得动 `qml/Main.qml` + `launcher_*`（你的文件）+ `settings_store`
      加一键，请你决定并认领，我不擅自改你的文件。现状提醒：用户已经感知到
      「一开感应风扇就转」，滑杆不做的就只能改代码。


## 2026-10-18 19:38 +0800

- 阶段：任务书 §8（任务七）—— 超过八词时蜘蛛根节点/头/身体必须沿路径**真实平移**

- 已完成：
  1. **路径一次性规划**：`locomotion.plan_route()` 吃 `ScanSession.order`（阅读顺序 + 行内最近邻），
     一个词一个停靠点，开层时算完就不再逐帧重排（中途改道就是「蜘蛛乱跑」）。
     `approach_point()` 现在只认一个口径 —— 传进去的 `reach_px` 是「腿拉到**上限**的可达半径」：
     词在半径内 → 站着让腿够（停靠点 = 当前位置）；在半径外 → 走过去，站到 `reach × 0.62`
     且不小于 `身体半径 + 12px`（不压住词框）。
  2. **身体真的在走**：`AimOverlay` 持有 `locomotion.MotionController`，落点写回**唯一权威**
     `PetWindow.center`（`_apply_root`），步态引擎从中心点的逐帧差自己拿到位移（`motion=`）；
     开层时把 `pet._travel` 置空，避免两处同写一个 `center`。
  3. **§8.2.6 落脚/扫描确认**：`_on_arrive()` → `session.note_progress()` → 按这一站重算腿长 →
     重派腿 → `_contact_stop` 原地等到这一站的词结清（`_release_contact`）才起程。
     为什么非等不可：脚尖盯的是词在**体坐标系**里的投影，身体一动投影就漂，落位判据
     （`leg.target_now == center`）一直不成立 —— 实测 8 词长条只有 2 个真被踩到。
  4. **队列时钟口径统一**：`_queue_now` 只在身体停着时推进，`session.tick(self._queue_now)`；
     `ScanSession.note_progress()`（新增）落一站续一次「这批没卡住」的命。
  5. **零长度的一站不算任务**：`_next_stop()` 跳过「身体已经站在上面」的停靠点
     （`STOP_ALREADY_THERE_PX = 2 × ARRIVE_PX`），否则一片密集词会被拆成 8 次原地确认，
     1 秒能踩完的框选拖成 3 秒；这些词仍由腿并行踩。
  6. **§8.4 暂停/继续/关闭**：暂停连 `mover.cancel()`（身体立刻停，不是只冻换批），
     继续把**同一个**停靠点交回去，关闭时 `cancel()` + 腿长/派腿复位。
  7. **§8.5 视觉边界**：腿长只为「停靠点就在脚下」的那些词算（`_needed_stretch` 改成按停靠点
     归属筛，不再按距离筛）；`Spider.set_leg_stretch()` 补上「改完长度立刻夹一次脚尖」，
     堵掉腿长缓动那一帧的超尺例外（实测 1.0022×full → 界从 1.001 收回 0.995）。

- 修掉的用户可见回归：**「已全部踩完 0 个词 · 3 批 · 8 个失败」**（本轮截图）。
  根因是**一张表两处读**：`session.tick(now)` 喂的是 `time.monotonic()`，而 session 的 `clock`
  已换成恒为 0 的 `_queue_now` → `now - _batch_started` 一上来就是「开机至今的秒数」→
  第一批立刻被判卡住 → 重试 3 轮后 8 个词全 failed。

- 修改文件：`src/locomotion.py`（`approach_point` / `plan_route` / `MotionController.step` /
  `APPROACH_STANDOFF_FRAC` `APPROACH_BODY_CLEARANCE_PX`）、`src/aim_overlay.py`（路由与控制器接线、
  `_next_stop`/`_set_waypoint`/`_on_arrive`/`_release_contact`/`_advance_body`/`_apply_stretch`/
  `_needed_stretch`/`_max_reach_px`/`_tick`/`_toggle_pause`/`closeEvent` + 模块头改写）、
  `src/scan_session.py`（`note_progress`）、`src/crawler_spider.py`（`set_leg_stretch` 夹脚尖）、
  `test/test_path_walk.py`（新增 43 项）、`test/run_all.py`、`tools/run_tests.py`（登记）。

- 测试命令：
  ```
  APPDATA="$PWD/.tmpappdata" .venv/Scripts/python.exe test/run_all.py --only test_path_walk,test_aim_hold,test_scan_queue,test_leg_fold_assignment,test_spider,test_locomotion,test_leg_stretch
  APPDATA="$PWD/.tmpappdata" .venv/Scripts/python.exe test/run_all.py
  ```
- 测试结果：
  - 运动子集 **7 个文件全绿**：`test_path_walk` 43/43（新）、`test_aim_hold` 51/51、
    `test_spider` 59/59、`test_leg_fold_assignment` 35/35、`test_locomotion` 31/31、
    `test_scan_queue` 30/30、`test_leg_stretch` 15/15。
  - 全量 `test/run_all.py`：**31 个文件通过 / 33，累计 842 项**（含 `aim_e2e` 19/19、
    `locomotion_sheet` 26/26、`word_box_fit` 29/29、`overlay_box_only` 8/8）。
  - 两个红：`tools/sense_bench.py` 33/35（挂的是「静态画面没有反复唤醒 OCR」「变化检测判定和剧本对得上」）、
    `tools/sense_e2e.py` 真桌面端到端整段挂。**都是 §7 冻结态的既有失败**（15:28 基线起就在，
    WorkBuddy 在 `communite/status/workbuddy.md` 里也这么认定），且 §8 改动不在那条路径上
    （`src/sense_*.py` 不调 `set_leg_stretch`/`limit_to_reach`；`sense_session/worker/overlay` 三个测试本轮全绿）。
  - §9.3 要求的 1/4/8/9/16 目标**截图册**：**未运行**（还没做，见下一步）。

- 视觉验证：**未验证**。本轮只有几何/状态断言与 `tools/locomotion_sheet.py` 的像素朝向检查，
  没有在真桌面上肉眼复核「16 个词一路踩过去」的连续观感；也没有过多屏 / 非 100% DPI / 打包冷启动。

- 根因/算法说明：见上面第 1～7 条。核心是把「距离」这件事分成两口 ——
  **身体**负责超过最大可达半径的词（走过去，站到 0.62 处），**腿**只负责脚下这一站的词；
  两口共用同一个 `_max_reach_px()` 数字，任何一处改口径都会出现
  「身体没挪（判定够得着）但腿也不拉（判定该走）」或反过来的死角 —— 本轮 D4b 挂过一次就是这个味。

- 未解决问题：
  1. §9（任务八）A：`PetWindow._travel` 还是自己那套位移，没并到 `MotionController`；
     跳跃的**蓄力压低 / 落地压缩回弹**（`body_bob`、`landing_compression`）在渲染层还没做。
  2. §9.3 评测册（1/4/8/9/16 目标 + 四方向四对角 + 不同皮肤的截图与几何断言）未建。
  3. §2（任务一：罐子原位出现 → 跳到桌面右下角）按指令仍卡在 WorkBuddy 提案：
     `tools/launcher_probe.py:142-187` 钉着 740ms 部署时间线，动它之前要先发协作消息。
  4. 仓库根目录还散着我本轮的 `.tmp_*.txt/.log/.view` 与 `.tmpappdata/` 沙箱，收尾时清掉。

- 下一步：任务书 §9（任务八）—— 统一运动状态 + 走/跳质感（蓄力→腾空→落地压缩→恢复），
  然后 §9.3 的截图册与几何断言，最后把 §10 全量回归与交付清单一次跑齐。

- PaddleOCR 与蜘蛛感应状态：**暂停**（未动 `src/sense_*`、`src/ocr_*`，也没换引擎）。

## 2026-10-18 21:58 +0800

- 阶段：§9（任务八）运动质感 → §9.3 评测册 → §10 全量回归 → §2（任务一）试做后按用户决定**撤销**

- 已完成：
  - **§9.2A 唯一权威**：`PetWindow` 持有自己的 `locomotion.MotionController`（`pet.mover`），
    根节点只由 `on_root` → `_apply_travel_root` 写；`_travel` 降级成这一段 {(from,to,t0,dur,is_jump)}
    的**快照**（给旧调用方/测试/探针读），不再是第二个积分器。谁置 `_travel=None`（拖动、
    覆盖层接手、取消），下一帧 `_tick` 就 `mover.cancel()`。
  - **§9.2B/C 走与跳的质感**：身体起伏按「此刻几条腿抬着」给（`body_bob`，夹在
    `BOB_MAX`）、跳跃四段 `jump_prepare → jump_airborne → land → 恢复`（蓄力 `crouch` 压到底、
    起跳撤目标、落地满冲量、自己回弹）、走停给一次轻冲量；`spider_painter` 消费这三个量，
    且**脚尖像素一个都不动**（只下沉 + 屏幕竖直压扁）。
  - **§9.3 评测册**：`tools/locomotion_sheet.py` 从 26 项扩到 **54 项**，4 张对照图
    `dist/shape/locomotion_{walk,orient,jump,speed}.png`；新增「跳跃起点/蓄力/腾空 5 帧＋
    抛物线合成图」「待机 / 慢走 45px·s⁻¹ / 快走 240px·s⁻¹ / 原地转向」两组帧序列与步频步幅
    数字。随机源夹死（`random.seed(20261018)`，因为 `crawler_spider.py:795` 的迈步时长是
    `random.random()`），两次跑日志逐字节一致。
  - **§2（任务一）试做与撤销**：实现过 `src/deploy_handoff.py`（瓶内坐标 → 全局逻辑像素，
    三条路线：启动台钩子 / 可见 Widgets 瓶身 `mapToGlobal` / QML `findChild("spiderJar")`
    → `QQuickItem.mapToGlobal`）＋ `PetWindow.deploy_from()`（起点=罐内蜘蛛位、比例=罐内等效
    比例、姿态=继承 `heading`，腾空里把体型长成设置值，然后 `force_jump` 落到右下角），
    并接到 `PetLifecycle.deploy()`。用户 21:40 决定不做，**已整体还原**（4 个文件回到原样、
    新模块删除、`__pycache__` 里的残留也清了）。启动台那三个文件（`launcher_window.py` /
    `launcher_qml.py` / `qml/Main.qml`）**全程只读、零修改**，`launcher_probe.py` 的 740ms
    时间轴也不需要动。

- 修改文件（本轮净残留，撤销之后）：
  - `src/locomotion.py`、`src/crawler_spider.py`、`src/spider_painter.py`、`src/pet_window.py`（§9.2）
  - `test/test_jump_motion.py`（新增 37 项）、`test/run_all.py`、`tools/locomotion_sheet.py`（§9.3）
  - `communite/messages/20261018-215800_qoder_to_workbuddy_s9-interface-list-and-task1-dropped.md`、
    本文件
  - `src/deploy_handoff.py`：**已创建又已删除**，现在仓库里没有这个文件

- 测试命令：
  ```
  .venv/Scripts/python.exe test/run_all.py                       # 全量（34 个文件）
  for f in test/test_jump_motion.py test/test_walk_jump.py test/test_locomotion.py \
           test/test_app_lifecycle.py test/test_path_walk.py test/test_aim_hold.py; do
      .venv/Scripts/python.exe $f; done                          # 撤销后的对账
  .venv/Scripts/python.exe tools/locomotion_sheet.py
  python tools/deploy_cycle_probe.py --cycles 6 --fake-pet        # 部署/收回状态机
  ```

- 测试结果：
  - §9.3 册：**54/54 通过**（`locomotion_sheet.py` exit=0）。
  - 全量 `test/run_all.py`（撤销前跑的那一轮，仍然有效，因为撤销只动了 §2 那条路）：
    **29 / 34 个文件通过，累计 815 项**。5 个红全部是「本机 OCR 引擎不可用」这一条路径：
    `test_ocr_coords`（0 行识别）、`test_word_box_fit`（5 项「认出了词」＋refined 比例）、
    `test_ai`（`AssertionError: [] is not true`）、`tools/sense_bench` 与 `tools/sense_e2e`
    都是打印「未运行：本机 OCR 引擎不可用」。**无运动 / 渲染回归。**
  - §2 撤销后的对账：上列 6 个测试 + `locomotion_sheet` **两个解释器都绿**
    （`.venv` 3.13.15 与系统 3.14.7，PySide6 6.12.0），全部 exit=0；
    `deploy_cycle_probe --cycles 6 --fake-pet` → **PASS，问题 0 条**，启动台窗口恒为 1。
    真实 `%APPDATA%\Lexara\settings.json` 跑前跑后 **md5 一致**（未被写入）。
  - §9.3 里 **未运行** 的两项（如实记）：「1、4、8、9、16 个目标的定位」截图册、
    「不同皮肤下头身朝向与腿部一致性」截图册。前者只在 `test_path_walk.py`（43 项）与
    `aim_e2e`（19 项）里有几何断言、没有出图；后者沿用 `tools/skin_sheet.py` 的旧断面，
    没有按 §9.3 的口径重做。

- 视觉验证：**部分已验证**。4 张对照图我逐张看过 —— 就是因为看了 `locomotion_jump.png`
  才发现抛物线合成图第一版把起点钉在图心、609px 的跳距有三分之二被推出画面（改成量包围盒
  自适应缩放后重出图）。**未验证**：真桌面上肉眼看部署/收回的连续动画（本轮 §2 撤掉了，
  没再跑真机部署）、多屏 / 非 100% DPI（本机恒 150%）、打包后冷启动。

- 根因/算法说明：
  - §9.2A 的病根是「两个积分器各写一半 `center`」——桌宠自己那套 `_travel` 逐帧插值，
    控制器也在写，取消时机一错身体就被两边来回拽。修法是让控制器独占，`_travel` 只当快照。
  - 评测不可比的原因是**随机**而不是时间：`crawler_spider` 每步时长在 `STEP_DUR` 区间里
    `random.random()`，不夹种子时步相位每次漂半拍到一拍，断言余量只能按最差情况留。
  - §2 撤销的代价记在这里，将来要重做不用重新查：起点可以在**不改启动台**的前提下拿到
    （`JarItem.draw_jar` 是 `jar.resize(w,h)` 后 1:1 `render()`，所以瓶身局部像素 ==
    `spiderJar` item 局部像素；`QQuickItem.mapToGlobal` 出来的就是 `PetWindow.center`
    那套逻辑像素）；破罐 `burst_out()` 之后 `jar.x/jar.y` 冻结在最后可见位，正是交接点；
    跳跃段放在 `deploy_requested` **之后**，740ms 时间轴零改动；唯一别扭的是原地转身最坏
    0.75s（`ORIENT_RATE=4.2`），当时是按段加了倍速解决的。

- 未解决问题：
  1. §12 交付清单里「1/4/8/9/16 目标」与「不同皮肤一致性」两本截图册（见上面「未运行」）；
  2. 5 个 OCR 相关的红：本机没有可用 OCR 引擎（rapid/paddle 都探不到），
     不是代码回归，但也不会自己变绿；
  3. §2（任务一）按用户决定**不做**，部署仍是「右下角直接生成」—— 如果哪天重启，
     上面「根因/算法说明」最后一段是完整的接续点。

- 下一步：等你（用户）指方向。可选的三件按性价比排：① 补 §9.3 那两本截图册（把 §12 清单收干净）；
  ② 查 OCR 引擎为什么在这台机器上探不到（会同时影响 5 个红）；③ 收尾清理仓库根的
  `.tmp_*` 草稿与 `.tmpappdata/`。

- PaddleOCR 与蜘蛛感应状态：**暂停**（没换引擎、没动 `src/sense_*`；§7 维持冻结约定）。

## 2026-10-22 15:14 +0800

**任务：启动台「白天/夜晚」UI 主题切换（用户直接下令，非任务书）** — commit `dcc37d2`

- 新预设 `midnight`（蓝黑·夜晚）进 `ui_theme.PRESETS`；设置面板一行两颗胶囊
  （白天=forest 墨绿·象牙白 / 夜晚=midnight），数据走 bridge，QML 零硬编码。
- 新契约：theme.json 根上的 `_preset` 元数据 = 当前预设真源；
  `settings.theme_preset` 只是副本/兜底；`theme_tool set` 手改单键会摘掉
  `_preset`（文件不再等于任何预设，不许假高亮）。完整交代见
  `messages/20261022-151159_qoder_to_workbuddy_theme-switch-and-preset-metadata.md`。
- 动了 WorkBuddy 的 `launcher_qml.py` / `qml/Main.qml`：**用户当面授权**，
  事后留了消息；Widgets 老面板没加选择器。
- 验证：`test_theme.py` 32/32；两套主题真窗口截图（含设置面板/罐子/热力图）
  人工看过，无残色无白底白字；全量回归 46/54，新增红 0 ——
  `test_leg_fold_assignment`/`test_skin` 两条红是 WorkBuddy 15:04 信里自报的
  步态参数改动所致，归他处理，我没碰。
- 用户口径更新：**和 WorkBuddy 并行开发中**，协作走 communite；少跑长冒烟、
  直接做（本轮全量回归跑了 8 分钟，被点名）。

## 2026-10-22 15:32 +0800

**任务：自动昼夜（「跟随系统」主题档）** — 主体散在 `768bef2`（被 WorkBuddy 的
add -A 卷走），收尾在 `e9d1f8d`

- `ui_theme.system_preset()`：Windows 注册表深浅色 → forest/midnight，
  读不到按 7~19 点时间兜底；settings 新键 `theme_auto`；
  bridge 第三颗虚拟胶囊 `auto` + 60s 轮询（只在系统真翻转时写盘，
  手动模式不抢方向盘）；QML 胶囊文案全走 bridge label。
- 验证：`test_theme.py` 35/35（新 `SystemPresetTest` 4 条）+ 无头链路断言
  全过 + 真窗口截图。**注意**：无头断言里 `sys.modules` 替换 winreg/time
  是瞬时的，不碰注册表、不碰真 `%APPDATA%`。
- WorkBuddy 修了我 midnight 预设漏 `base.accentSoft` 的白底白字 bug
  （`#20304A`），收下；**用户本机 theme.json 还是旧值，要在设置里重点一次
  「夜晚」才生效**（已口头转告）。待办：给 PresetSwitchTest 补一条
  「暗色预设 Soft 底 × ink 对比度」机械断言。
- 工作区遗留：`crawler_spider.py` 未提交 diff + `.bak` **不是我的**，
  已在消息里让 WorkBuddy 自己认领。

## 2026-10-22 15:59 · 单词本导出（txt/csv/json 三个出口）

- `src/word_export.py`（新，纯逻辑）：txt 按收藏夹分节 + 遮答案默写卷、
  csv 十列走模块转义、json = wordbook 形状 + `_lexaraMeta`（schema 没动）；
  txt/csv 落盘 `utf-8-sig` 带 BOM，`.tmp`+`os.replace` 原子写。
- bridge `exportWordbook(fmt, study)`：系统「另存为」定名定位，默认
  Documents/`词蛛单词本_YYYYMMDD.fmt`，不打后缀才补。
- QML：收藏夹底部「导出单词本…」入口 + `exportPanel` 浮动面板。
- 验证：`test_word_export.py` 19/19；两张真窗口截图；GUI 跑完
  `%APPDATA%\Lexara\*.json` 未变。
- 留痕：我的 bridge slot / 旧版入口被 WorkBuddy `f204442` 的 `git add -A`
  扫进他名下（内容没问题，不动）；他 Main.qml 未提交的默写 hunk 我这次
  **没有**带走，原样留工作区归他提交。详见 `20261022-155944` 消息。
