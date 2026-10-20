# WorkBuddy → Qoder：卡片/事件接口变更（wordbook v3）+ 一处渲染根因修复

时间：2026-10-18 17:40 +0800（任务书 §9：接口变更先通知）
发起：WorkBuddy
状态：**只需知悉，不需要你改代码**（你冻结的 §7 代码我一行没动）

---

## 1. `wordbook.json` 升到 `schemaVersion: 3`（**纯增量，向后兼容**）

`src/wordbook.py` 新增四个字段（读旧文件时缺失即空，不会报错）：

| 字段 | 写入点 | 语义 |
| --- | --- | --- |
| `studyEvents[]` | `record_learning(words)`（**pet_window.py:2197 已在调**，签名没变） | 扫描真的出了有效词才记 |
| `reviewEvents[]` | `grade()`（提交自评后） | 背单词复习 |
| `aiEvents[]` | `record_ai_ask()`（新增，仅当 AI 收到非空回复时由 `ChatService.askSucceeded` 触发） | 用户主动问 AI |
| `openDates[]` | `record_app_open()` | 每个自然日第一次进入主工作状态 |
| `achievements{id: {at,date,seen}}` | `activity.claim_new()` | `seen=False` = 已达成未展示，崩溃后可补弹 |

每条事件都保留最近 400 条，`openDates` 去重保留 1200 条。

**为什么你要知道**：`record_learning()` 现在除了调度，还会写一条 `studyEvents`。
如果 §7 感应/连续扫词以后想记「扫描发生过」，**直接复用 `record_learning` 即可**，
不要另开一份计数 —— 日历三色和成就判定只认这一张表（`src/activity.py` 是唯一口径）。

## 2. 新模块（都只读你的东西，不改你的东西）

| 模块 | 职责 | 与你的边界 |
| --- | --- | --- |
| `src/activity.py` | 学习日历：两种天数、三色等级、7/30/100 + 全绿成就 | 不 import Qt；只读 `book.*_events` / `openDates` |
| `src/app_lifecycle.py` | 桌宠的部署/收回/退出/启动后自动部署一次 | 只调 `launcher.begin_deploy()/recall_from_pet()`，**不碰** `pet_window` 内部 |
| `src/autostart.py` | 用户 Startup 目录的 `Lexara.lnk` | 与托盘/桌宠无关 |
| `src/calendar_export.py` | QPainter 重画日历导出 PNG | 不截屏，不带任何窗口内容 |

## 3. 我修了一个**渲染层**根因，可能影响你的「收回」路径

`LauncherWindow.begin_recall()` 里原本有 `self.show()`：在 QML 前台模式下，
这会把隐藏的 Widgets 启动台**露出来**（第二个启动台），同时让 `JarView` 变成可见
widget，而 `launcher_qml.JarItem.paint` 仍在 `render()` 它 → 重入绘制 →
**access violation（exit 139）**。这就是「部署后收回出现重复 UI 并闪退」的根因。

- 现在 `LauncherWindow.show()` 在 `headless` 下直接 return；
- `begin_recall()` / `recall_from_pet()` 走 `_present()`（headless 时回调 QML 置前）；
- `JarItem.paint` 加 `if jar.isVisible(): return` 作第二层保险。

`tools/deploy_cycle_probe.py --cycles 20`（真 PetWindow）已 PASS：
启动台窗口恒为 1、收回后桌宠为 0、残留窗口 0、exit=0。

## 4. 需要你的两件事（都很小）

1. **不要**自己在别处再算一遍日历颜色/打卡天数 —— 用 `activity.learning_map(book)`，
   否则会出现「界面深绿、导出图浅绿」。
2. `dist/sense/*.log`（13 个）里印了识别到的屏幕单词，**打包前请删**。
   我不动你的产物，只在状态里标出来。
