# communite/ · WorkBuddy ⇄ Qoder 异步协作区

两个 AI 在同一个项目目录（LEXARA）里工作，所有跨代理沟通走这里。

## 规则（来自任务书第 8 节）

- `messages/` 下**每条消息一个独立文件**，命名 `YYYYMMDD-HHMMSS_<from>_to_<to>_<topic>.md`。写入后不再修改。
- 每个代理只编辑自己的 `status/<agent>.md`（WorkBuddy 只写 `workbuddy.md`）。
- 禁止写入 API Key、用户隐私数据、原始桌面截图。
- 先提接口草案 → 确认 → 再实现；不要一边改同一接口一边假设对方实现。
- 代码冲突时先检查工作区差异，保留对方改动，协商拆分，不得盲目覆盖。

## 目录

```
communite/
  README.md              本文件
  messages/              一次性消息，append-only
  contracts/             接口约定（双方确认后成为事实标准）
    ocr-result-contract.md
    ai-provider-contract.md
  status/
    workbuddy.md         WorkBuddy 的进度报告（第 10 节格式）
    qoder.md             Qoder 的进度报告（WorkBuddy 只读）
```

## 职责边界（双方确认过就不再重复讨论）

| 能力 | 归属 | 说明 |
| --- | --- | --- |
| OCR / 词框坐标 / 八腿路径 / 蜘蛛感应 | **Qoder** | UI 不创建 OCR 实例，不复制取词与路径规划业务 |
| 启动台 UI / 背单词 / 对话框 / API 配置面板 / 帮助 | **WorkBuddy** | 不发明第二套 OCR 切换逻辑或第二份密钥存储 |
| 单词本 JSON 与 1/3/7/14 复习调度 | **既有实现** | 双方都不得更改 schema 或间隔规则 |
