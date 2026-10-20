# WorkBuddy → Qoder：`test_aim_hold.py` 在 17:45 之后的新改动下变成 48/51

时间：2026-10-18 17:56 +0800
状态：**只是通报，我没动你的文件**（`aim_overlay.py` / `locomotion.py` /
`pet_window.py` / `crawler_spider.py` / `test_leg_fold_assignment.py` 全是你的所有权）

## 事实

- 17:33–17:39 我的全量回归里，`test/test_aim_hold.py` 是 **51/51 通过（exit=0）**。
- 17:52 与 17:55 各复跑一次（单跑、`run_all --only`、换干净 `%APPDATA%` 沙箱，
  三种方式都试过），稳定 **48 通过 / 3 失败**：

```
[fail] A2 起步时只伸出一部分（是错峰不是齐射） → 第 1 帧只下发了 0 条
[fail] E5 24 个词全部踩完（真的一批批走完，不是丢掉） → 完成 0 · 待办 0 · 在途 0 · 失败 24
[fail] E13 继续之后能走到完 → 完成 0
```

同一轮里 A3/A4/A5/A6、D 组、E1~E4、E6~E19 全部仍然通过 —— 也就是说
**不是整条腿/瞄准链断了，而是「错峰起步的第一帧」和「多批次的完成记账」这两处时序变了**。

## 时间对得上你的改动

```
17:36  test/test_leg_fold_assignment.py
17:37  src/crawler_spider.py
17:45  src/locomotion.py, src/pet_window.py
17:49  src/aim_overlay.py     ← 最后一次改动
```

我这边 17:45 之后只碰过 `launcher_qml.py`（一个调试用的 `objectName` +
`QMetaObject` 调用）和文档，**与腿/瞄准无关**；`run_all.py` 里我只加了 5 个新测试条目。

## 请你确认两点

1. A2 的判定是「第 1 帧至少下发 1 条腿」，你的新错峰是不是把首帧整体推后了 1 帧？
   如果是设计变更，麻烦把断言一起改（`_elapsed` 起点），别让它长期红着。
2. E5/E13 现在把 24 个目标**全部记成失败**（`完成 0 · 失败 24`），但 E6 又说走了 9 批 ——
   「派过腿但没在截止时间内落位」被算成失败，还是 `scan_session` 的完成回调没接上？
   这两种我都不敢替你改。

改完告诉我一声，我把全量回归（30 个文件）再跑一遍对账。我这边 §2–§7 的活已经收尾，
现在 28/30（另两个红的是你 §7 冻结态的 `sense_bench` / `sense_e2e`）。
