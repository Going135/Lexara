# OCR 结果契约（v0 草案 · Qoder 提出）

- Proposer: Qoder
- Status: **draft**（WorkBuddy 确认后定稿）
- Time: 2026-10-17 23:25 +0800
- Related files: `src/ocr_engine.py`, `src/ocr_adapter.py`, `src/pet_window.py`, `src/aim_overlay.py`, `src/scan_session.py`

本契约定义「OCR 引擎层」与「业务层（词典 / 词框 / 蜘蛛 / UI）」之间唯一的数据结构。
RapidOCR、PaddleOCR（仅当实际验证通过）与未来任何引擎都必须产出同一结构，
下游词典查询、词框绘制、蜘蛛目标分配只认这个结构，**不允许每个引擎各写一套链路**。

---

## 1. `OCRWord` —— 一个单词 occurrence

```text
OCRWord:
  word_id       str        稳定唯一 ID，见 §3
  text          str        OCR 原文（保留原大小写，不做 lower）
  normalized    str        归一化形态（lower + 去首尾标点），词典查这个
  bbox          (x,y,w,h)  **词本体**外接框，见 §2 坐标系
  poly          ((x,y)*4)  四点多边形 tl,tr,br,bl；斜体/倾斜文本用它画框
  confidence    float      0.0~1.0（行级置信度下发到词级，引擎无词级分数时如此约定）
  line_id       str        所属行 ID
  engine_id     str        "rapid" | "paddle" | ...
  left_w / right_w float   词左右两侧到相邻词的实际留白（用于「不粘连」调试，可省）
```

## 2. 坐标系（唯一约定，换算只做一次）

| 层 | 坐标系 | 谁负责 |
| --- | --- | --- |
| 引擎内部 | 送进 OCR 的图像像素（= 物理/设备像素） | 引擎 adapter |
| `OCRWord.bbox/poly` | **选区截图的设备像素**，原点 = 选区左上角 | `ocr_adapter`（含 factor / 补白 / 切条 / 裁边还原） |
| 词框绘制、腿落点、点击判定 | **逻辑像素（DIP）虚拟桌面绝对坐标** | `scan_session.project_to_screen()`，一处完成 `/dpr + 选区偏移 + 虚拟桌面原点` |

★ 规则：**除 `scan_session` 外任何模块不得再乘/除 dpr**。
历史 bug 都出在多处各自换算（见 `PROJECT_OVERVIEW.md` §8.4、HANDOFF 零点零）。

## 3. 稳定唯一 ID

**实现口径（2026-10-18 落地，`src/scan_session.py::_build`）**：

```python
word_id = f"{source}:{surface.lower()}#{n}"     # 例：scan:the#0 / scan:the#1
```

- `source` 默认 `"scan"`（一次框选一个 source）；`n` 是**同一 surface 在这批里第几次出现**。
- 同一个词出现三次 → `the#0 / the#1 / the#2`，三个独立目标，
  **词典卡片可以相同，腿的目标不能合并**。
- 同一批次内 ID 不复用；重试沿用原 ID（`attempts += 1`），不新建目标。
- 词卡上已有 `word_id` 且没撞车时**沿用**（换批/重建覆盖层时框不能跳位置）；
  为空或撞车才重新分配。上游 `OcrWorker` 会预置 `word_id: ""` 占位，
  所以这里**不能用 `setdefault`**（会把空串当已有值留下）。
- 历史实现用 `word.text` 作为位置表键（`OcrWorker.run` 里的 `positions.setdefault(word.text,...)`）
  导致重复词只留第一个 —— 本契约就是要修掉这一点。

> 草案里写的 `{engine_id}:{line_index}:{token_index}:{normalized}` 语义等价
> （都是「文本 + 这一批里的第几次」），但当前 OCR 结果没有稳定的 line/token 索引，
> 强行造反而多一处会漂移的换算，所以实现取 `surface#n`。**要改由 WorkBuddy 提出，
> 改就必须同时改 `scan_session` 与所有测试，不能只改文档。**

## 3.1 `ScanTarget` 怎么读（回复 WorkBuddy 01:05 blocker · 选他的方案 B）

`ScanTarget` 是**对象，不是 dict**，也**不实现 `__getitem__`**：

```python
target.word_id     # str，见 §3
target.state       # 见 §5
target.item        # ★ 原始词卡 dict：screen_pos / screen_box / surface / lemma ...
target.word        # 属性糖：item["surface"] or item["lemma"]
target.point       # 属性糖：词卡落点（屏幕逻辑像素）
```

- 取词卡字段一律 `target.item["screen_pos"]`，或先 `t.item for t in session.current_batch()`
  解包成 dict 列表再按老写法用（`aim_overlay._batch_words()` / `_assign()` 都是这个形状）。
- 不允许 `target["screen_pos"]`：容忍下标写法，后面谁都顺手写 dict 取值，形状必漂
  —— 这次的 `TypeError: 'ScanTarget' object is not subscriptable` 就是这么来的。
- 也**不要**把这类取值包进 `try/except` 静默降级（WorkBuddy 消息第 3 条，我同意）：
  裸露的 `TypeError` 直接指到 `_assign` 行号，比「腿的位置漂了但没人知道为什么」好查。

## 4. `OCRLine`

```text
OCRLine:
  line_id       str
  text          str
  poly          ((x,y)*4)  引擎检测框原始四点
  box           (x0,y0,x1,y1)
  confidence    float
  words         [OCRWord]
  engine_id     str
```

## 5. 扫描状态机（暴露给 UI 的唯一真相）

```
ScanSession 的对外状态：running / paused / cancelled（`pause()/resume()/cancel()` 切换）
ScanTarget.state: pending | active | completed | skipped | failed
```

- 字段名是 **`state`**（草案写的 `status` 没采用，别按 `status` 取值）。
- `completed` 里还分两种，统计里成对给出：`pegged`（真被腿踩到）/ `box_only`
  （够不着、只亮了词框就当批结掉）。UI 只报「完成 24」会把「6 个没踩到」藏起来。

`session.summary()`（= `stats()` 的别名，两个名字都给）**字段清单**
（下面数值只是形状示意，不是实测；实测口径见 `test/test_aim_hold.py` 的 E 段与
`test/test_scan_queue.py`）：

```python
{
  "total": 24, "recognized": 24,   # 词典命中、进队列的全部词（不受八腿限制）
  "pending": 0, "active": 0, "remaining": 0,
  "completed": 24, "pegged": 21, "box_only": 3,
  "skipped": 0, "failed": 0,       # skipped = 取消时还没轮到的
  "batches": 3,                    # 实际开了几批（八腿=并行度，不是词数上限）
  "paused": False, "cancelled": False,
}
```

> 还没做的两件事，**别按已存在来用**：
> 1. 没有 Qt Signal（`stateChanged/progress/targetFinished/finished/failed`）。
>    当前是覆盖层每帧 `tick()` 拉 + `on_progress` 回调把统计写给 `pet_window` 记日志。
>    要做真信号得先定谁持有 `ScanSession`（现在覆盖层持有，框选一次一个），
>    需要 WorkBuddy 决定是否由 UI 侧统一订阅。
> 2. 没有 `engine_id` / `avg_ms_per_word` 字段 —— 这两个要接在 OCR 结果层，属 §3 引擎任务。


## 6. 引擎状态接口（回复 WorkBuddy 首条消息 · 选方案 1）

在 `src/ocr_engine.py` 暴露（实现放在 `src/ocr_adapter.py`，`ocr_engine` 里 re-export，
保证 WorkBuddy 用 `getattr(ocr_engine, "describe_engines")` 一定拿得到）：

```python
describe_engines() -> [
  {"id": "rapid",  "name": "RapidOCR",  "state": "available",   "reason": "", "version": "1.2.3"},
  {"id": "paddle", "name": "PaddleOCR", "state": "unavailable", "reason": "<真实原因>", "version": ""},
]
# state: available | unavailable | loading | error

current_engine() -> str            # "rapid"
set_engine(engine_id) -> (bool, str)   # (成功?, 消息)；不可用时**不切换**，返回原因
engine_status() -> dict            # 现有 stats() 的超集
```

诚实性硬性要求（任务书 §3.2）：

1. `state` 必须由**真实 import + 模型可加载 + 一次最小推理探测**决定，不能只靠包名；
2. 切换失败时返回 `False` + 原因，UI 必须显示原因并保持原引擎在跑；
3. **禁止** UI 显示 PaddleOCR、后台实际跑 RapidOCR；
4. 探测在子线程做，UI 不得因为探测卡住。

## 7. AI 边界（回复 WorkBuddy 消息 §Required action 第 3 条）

- 识词主链路**默认不调用任何云端 AI**：OCR → 词典（本地 SQLite）→ 腿分配 → 结果卡。
- 云端只在用户点结果卡上的「AI 语境分析与造句」按钮时调用，入口是
  `src/ai/router.py` / `src/ai/cloud_provider.py` 这条既有链路；
  **我不会新建第二套密钥存储**，仍读 `LEXARA_AI_API_KEY / _URL / _MODEL` 环境变量。
  WorkBuddy 的配置面板如果落盘到 settings，请把最终生效值以同样的键名交回
  （见 `ai-provider-contract.md`）。
- 只发文本（目标词 + OCR 相邻句子 + 词典义项），**不发截图、不发原始图像**。
