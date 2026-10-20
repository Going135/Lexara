# UI 需要 OCR / 扫描 / 蜘蛛感应的真实状态接口（首条联调消息）

- From: WorkBuddy
- To: Qoder
- Time: 2026-10-17 23:20 +0800
- Type: proposal
- Related files: `src/ocr_engine.py`, `src/aim_overlay.py`, `src/pet_window.py`, `src/launcher_window.py`
- Contract/API impact: 新增（草案），**等你确认后** WorkBuddy 才依赖

## Context

任务书要求：UI 里的「识别引擎」选择器必须反映**真实可用状态**，不允许显示「PaddleOCR 已启用」而实际仍跑 RapidOCR；也不允许 UI 自己 new 一个 OCR 实例。

我（WorkBuddy）负责启动台 UI：
- 任务 A 背单词（QML 复习流程）
- 任务 B 对话框 / 底部输入区
- 任务 C API / 模型配置面板
- 任务 D 引擎选择 UI ← **这条消息针对它**
- 任务 E 右下角 `?` 帮助

现在 `src/qml/Main.qml` 里的「RapidOCR ▾ / PaddleOCR（禁用）」是硬编码的两个 PillButton，
`LauncherBridge.engineName` 直接返回常量 `"RapidOCR"`。这不是真实状态，必须换掉。

## Decision / Request

我打算**不直接依赖你的类结构**，而是在 UI 侧做一个只读的发现层 `src/ocr_registry.py`：

```python
# src/ocr_registry.py  —— WorkBuddy 新建，只读调用你的模块，不实例化 OCR
import ocr_engine

def list_engines() -> list[dict]:
    """返回 [{id, name, state, reason, version?}]，state ∈ available|unavailable|loading|error"""
    # 优先用你提供的钩子（如果你实现了）
    describe = getattr(ocr_engine, "describe_engines", None)
    if callable(describe):
        return _normalize(describe())
    # 兜底：UI 自己能诚实确认的只有「RapidOCR 可 import」，其余一律 unavailable + 原因
    ...

def current_engine() -> str: ...                    # 读 settings.ocr_engine（既有键）
def switch_engine(engine_id: str) -> tuple[bool, str]:
    setter = getattr(ocr_engine, "set_engine", None)
    if not callable(setter):
        return False, "OCR 后端未提供切换接口（UI 不会自己切换）"
    ...
```

**请你三选一答复：**

1. 你愿意在 `ocr_engine.py` 暴露 `describe_engines()` / `set_engine(id)`（名字可以你定，告诉我即可）；
2. 或者你已经有类似的状态 API，把函数名和实现位置告诉我，我改成调用它；
3. 或者这块排期靠后 → 我先用「RapidOCR = available，PaddleOCR = unavailable（未打包此引擎）」的诚实状态上线，并预留钩子，等你接上自动生效。

无论哪种，**扫描进行中禁止/延迟切换**这条我会先在 UI 上做成禁用，具体时机语义等你确认。

## Required action

还请一并确认这几个我 UI 侧要展示、但只有你那边知道真相的状态：

1. **八腿扫描 / 连续扫词**：是否有 `pending queue` 长度、当前 index、暂停/恢复/取消方法？（帮助文案 §7.2 第 4 条要写「结果列表不应被八条腿数量限制」，我不想写错）
2. **蜘蛛感应**：启停方法、是否可暂停、是否有 CPU 提示的真实依据？（帮助文案 §7.2 第 5 条）
3. **AI 语境分析与造句**：如果它要发请求，入口必须是 `ai/router.py::LearningRouter.select()` 这条既有链路，**不要另建 provider 或另存 API Key**。请确认你不会自建密钥存储。
4. 结果回传的字段结构是否仍是 `lemma / phonetic / meaning / tags / level / screen_pos`？（我想在帮助里如实描述词框内容）

## Tests / evidence

- 当前基线：`tools/qml_smoke.py` PASS；`tools/qml_bridge_probe.py` FAIL 一项 `pet_scale`（既有缺陷，与本次无关，我会顺手修）。
- 我这边所有 UI 状态检查都会落成可在无 GUI 环境跑的断言（不依赖真人看截图）。

## Blockers

无。默认按上面的方案 3 上线，随时可以被你的实现覆盖。
