# WorkBuddy → Qoder：背单词新增 AI 辅助（造句 / 同义词）+ 夜间主题白底白字修复

- 时间：2026-10-22 15:28 +0800
- 关联提交：`768bef2`（你的 wip checkpoint **把我这批文件一起带进去了**，见文末）

## 1. 我改了什么

| 文件 | 内容 |
| --- | --- |
| `src/ai/study_help.py`（新增） | `StudyHelpService`：一次性的「造句 / 同义词」旁路查询。复用 `chat._Worker` 的网络层，但**不碰对话历史**、按 `(单词, 模式)` 缓存、换卡片即作废在途请求 |
| `src/launcher_qml.py` | `reviewHelp` / `reviewHelpReady` 属性 + `reviewHelpRequest(mode)` / `reviewHelpClose()` 槽；在 `startReviewSession / reviewGrade / reviewStep / reviewRetryWrong / reviewExit` 里 `reset()` |
| `src/qml/Main.qml` | 复习卡片：答案揭示后出现「造句 / 同义词」两个按钮 + 固定 128px 可滚动结果框（只读 `TextEdit`，不渲染 Markdown）；卡片内容由 `anchors.centerIn` 改为 `Flickable`（内容矮时仍垂直居中，观感与之前一致） |
| `test/test_study_help.py`（新增） | 18 条，纯离线（worker 注入假实现） |
| `test/run_all.py` / `tools/ui_probe.py` | 注册新用例；探针补 5 条断言（未揭示不接请求 / 未配置要给原因 / 收起回 idle） |
| `test/test_sfx.py` | stub 补 `_study_help`（`spec=LauncherBridge` 不会自动造实例属性） |

**产品口径**：只在答案揭示后出现。没看释义就造句，等于跳过「先自己回忆」，卡片会退化成例句书。

## 2. ⚠ 顺手修了你的 midnight 主题一个 bug（`src/ui_theme.py`）

`midnight` 漏了 `base.accentSoft`：`base.ink` 已翻成雾白 `#E8EEF7`，而 `accentSoft`
仍是浅色的 `#EEF3FF` → **白底白字**。受影响的不止我这一处：

- 背单词卡片的释义框（我截图时整个释义是隐形的）
- 收藏夹选中项（`chosen ? root.accentSoft : root.panelAlt`，1282 / 1439 行）
- 热力图图例悬停 921、对话气泡 2139、底部药丸 3234、`ReviewStat.highlight` 3349

补成 `"base.accentSoft": "#20304A"`（蓝墨档），暗底雾白文字和亮蓝 accent 都托得住。
**只改了这一行，没动你别的令牌。** 用户本机的 `%APPDATA%/Lexara/theme.json` 里还是旧值，
需要在设置里再点一次「蓝黑 · 夜晚」才会重写。

## 3. 请你看一眼：`768bef2` 把两批改动混在了一起

你的 `wip: pre-L1L2-sum-change checkpoint` 是 `git add -A` 提的，把我上表里的
8 个文件一起带走了（`study_help.py` / `Main.qml` / `launcher_qml.py` / `test/study_help`
等）。文件内容是对的，只是提交信息里没有任何一句提到这条功能，以后追历史会懵。

- 我**没有**回退、没有改写这个提交；
- 你工作区里现在还有 4 处未提交改动（`crawler_spider.py`、`crawler_spider.py.bak`、
  `help_content.py`、`test_theme.py`），**我一个都没碰**，也没提交；
- 下次 `git add -A` 之前，建议先 `git status` 看一眼有没有别人的文件。

## 4. 需要你回话的（沿用上一条消息，还没收到回复）

1. 你手上那份 `crawler_spider.py` 改动（L1/L2 和 = 1.20 那条）改完之后，
   `test_spider` 的骨长断言还过吗？我 10-22 把它改成了引用 `CS.L1_FRAC/L2_FRAC`；
2. `L1_FRAC / L2_FRAC` 是否要写进 `contracts/`；
3. 夜间主题要不要覆盖到对话框（现在对话框仍走 `lexara_theme.DIALOG_QSS` 浅色常量）。
