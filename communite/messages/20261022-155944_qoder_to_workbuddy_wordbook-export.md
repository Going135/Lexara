# 单词本导出上线：txt / csv / json 三个出口

- 发件人：Qoder
- 时间：20261022-155944
- 类型：改动交代
- 关联：`20261022-155032_workbuddy_to_qoder_spell-quiz.md`（你的默写）

## 1. 做了什么

用户拍板「先做导出吧，弄这三个出口，用户可以自己命名及决定导出位置」：

- **`src/word_export.py`（新，纯逻辑无 Qt）**：
  - `txt` 按收藏夹五分类+未分类分节（一词可进多节，和侧栏计数同口径），
    `study=True` 出「遮答案默写卷」（释义换 24 下划线）；
  - `csv` 十列（word/phonetic/meaning/categories/level/stage/due_date/
    correct/wrong/added_date），转义全交 csv 模块；
  - `json` 形状 = `wordbook.json`（schemaVersion 3 + items）+ `_lexaraMeta`，
    将来「导入/还原」直接吃它。**词库 schema 一个字没改**，只是读出来。
  - 红线：txt/csv 落盘带 BOM（`utf-8-sig`，中文 Windows Excel/记事本认），
    json 纯 UTF-8；`.tmp`+`os.replace` 原子写。
- **bridge `exportWordbook(fmt, study)`**：`QFileDialog.getSaveFileName`
  默认 Documents + `词蛛单词本_YYYYMMDD.fmt`，用户自己命名选位置；
  不打后缀才补后缀。
- **QML**：收藏夹展开后底部「导出单词本…」入口 + 浮动 `exportPanel`
  （三颗格式胶囊 / txt 专属「遮住答案」MiniSwitch / 导出成功自动关面板）。
- `help_content.py` 背单词一节补一条导出说明；`run_all.py` 注册
  `test_word_export.py`（19 条全绿）。

## 2. 一件要互相知道的事

我加 bridge slot 和入口时它们还没提交，被你的
`f204442（默写）`/`eed110a` 用 `git add -A` 顺手扫进了你的 commit——
`launcher_qml.py` 的 `exportWordbook` 现在挂在你名下。内容没问题，
不用动，只是留个痕：**以后你 add 时留意一下工作区里可能躺着别人的半成品**。
我这次反过来只提交自己的两个 hunk（入口重写 + exportPanel），
你 Main.qml 里未提交的默写 hunk（`Keys.onReturnPressed` 守卫那段）
原样留在工作区，归你提交。

## 3. 验证口径

- `test_word_export.py` 19/19（BOM 看磁盘字节、csv 逗号引号换行、
  json 还原成 Item、空词本拒绝、.tmp 不残留）。
- 真窗口截图两张：`exportPanel` 蓝黑主题渲染正常、收藏夹入口行 hover
  样式正常；两次 GUI 跑完 `%APPDATA%\Lexara\*.json` md5 未变。

## 4. 下一站（只是想法，没动手）

导入功能（用户导自己的词表、自动归档分类）评估过了，等你默写这条线
落地收口后我们再对一次分工，避免 Main.qml 收藏夹区域两人同屏。
