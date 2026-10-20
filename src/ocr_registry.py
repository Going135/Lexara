# -*- coding: utf-8 -*-
"""OCR 引擎状态发现层（只读 + 受控切换，Qoder 拥有真实实现）。

为什么 UI 不能直接碰 OCR
------------------------
任务书 6.3：UI 不得创建自己的 OCR 实例，也不得复制 Qoder 的词框/扫描业务。
所以这个文件只做两件事：

1. **问**：向 `ocr_engine` 询问「有哪些引擎、各自什么状态」；
2. **转**：把结果翻译成 UI 能直接画的状态列表 `[{id,name,state,reason}]`。

Qoder 何时接进来都不影响 UI 代码：本模块优先调用 Qoder 提供的钩子
``ocr_engine.describe_engines()`` / ``ocr_engine.set_engine(id)``，
**没有钩子时就用 UI 自己能诚实确认的事实兜底**——不会为了让界面好看而编状态。

兜底事实（2026-10-17 实测代码，不是猜的）
-----------------------------------------
- `ocr_engine.OcrEngine` 只有一个 RapidOCR 单例，无切换分支；
- `OcrEngine.available()` 通过能否 import `rapidocr_onnxruntime` 判定，
  因此「依赖没装」会被如实报成 `unavailable` 而不是 `available`；
- PaddleOCR 既未实现也未打包（`ocr_engine.py` 文档字符串写明弃用原因：
  Paddle C++ 层不支持非 ASCII 路径）。2026-10-19 起它**已从清单中删除**，
  设置里不再出现这个永远点不动的选项。
"""
from __future__ import annotations

import logging
import threading

_STATE_ORDER = {"available": 0, "loading": 1, "error": 2, "unavailable": 3}

#: UI 侧展示用的中文状态名。
#: `unknown` 是 Qoder `ocr_adapter` 的**初始态**——引擎还没跑过可用性探测。
#: UI 必须如实显示「还没验证」，既不能画成可用，也不能画成失败。
STATE_LABELS = {
    "available": "可用",
    "loading": "加载中",
    "error": "出错",
    "unavailable": "暂不可用",
    "unknown": "未探测",
}

#: 取值出意外时（后端改字段、返回 None…）一律按「未知」处理，不猜。
_UNKNOWN = "unknown"


def _state_of(row: dict) -> str:
    state = str(row.get("state") or row.get("status") or "").strip().lower()
    if state in STATE_LABELS:
        return state
    # 后端换了字段名（例如只给 {"available": True}）时的降级判断
    if row.get("available") is True:
        return "available"
    if row.get("available") is False:
        return "unavailable"
    return _UNKNOWN


def _module():
    try:
        import ocr_engine
        return ocr_engine
    except Exception:                          # noqa: BLE001
        return None


def _normalize(rows) -> list:
    """把 Qoder 钩子返回的东西收敛成 UI 契约，缺字段就退化成未知。"""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        engine_id = str(row.get("id") or row.get("key") or "").strip()
        if not engine_id:
            continue
        state = _state_of(row)
        out.append({
            "id": engine_id,
            "name": str(row.get("name") or engine_id),
            "state": state,
            "stateLabel": STATE_LABELS.get(state, state),
            "reason": str(row.get("reason") or row.get("message") or ""),
            "version": str(row.get("version") or ""),
        })
    return out


def _fallback_engines() -> list:
    """没有后端钩子时，UI 只用自己能验证的事实说话。"""
    module = _module()
    if module is None:
        return [{"id": "rapid", "name": "RapidOCR", "state": "unavailable",
                 "stateLabel": STATE_LABELS["unavailable"],
                 "reason": "识词模块未能加载。", "version": ""}]
    available = False
    error = ""
    try:
        available = bool(module.OcrEngine.available())
        error = getattr(module.OcrEngine, "_error", "") or ""
    except Exception as exc:                   # noqa: BLE001
        available = False
        error = str(exc)
    # ★ 2026-10-19：不再列 PaddleOCR。它从来没被打包过，恒为 unavailable，
    #   留在设置里只是一张永远点不动的灰卡（实测还占掉半个面板的高度）。
    #   引擎清单 = 真正随包发货的东西，只有 RapidOCR 一个。
    return [
        {"id": "rapid", "name": "RapidOCR", "state": "available" if available else "unavailable",
         "stateLabel": STATE_LABELS["available" if available else "unavailable"],
         "reason": "" if available else ("依赖缺失：%s" % error if error
                                         else "运行时依赖 rapidocr_onnxruntime 未安装。"),
         "version": ""},
    ]


def list_engines() -> list:
    """引擎列表 + 真实状态。Qoder 接进来后这里自动改用他的实现。

    Qoder 的 `describe_engines()` **不主动探测**（契约见 `src/ocr_adapter.py`），
    首次返回一律 `unknown`。UI 若就此显示「未探测」会一直挂着，所以这里在
    后台请求一次后端自己提供的 `probe()` —— 探测仍由后端执行，UI 不碰 OCR 实例；
    等他那边在启动流程里接上探测，这段就是幂等的（probe 结果带缓存）。
    """
    rows = _from_backend()
    if rows and all(row["state"] == _UNKNOWN for row in rows):
        _request_probe()
    return rows or _fallback_engines()


def _from_backend() -> list:
    module = _module()
    describe = getattr(module, "describe_engines", None) if module else None
    if not callable(describe):
        return []
    try:
        rows = _normalize(describe())
    except Exception:                          # noqa: BLE001
        logging.getLogger("lexara.ocr").exception("describe_engines failed")
        return []                              # 钩子出错退回兜底事实，不让 UI 崩
    return rows


_probe_requested = False


def _request_probe() -> None:
    """请后端跑一次真实探测（后台线程）。

    用的是 Qoder 自己在 `ocr_adapter` 里提供的 `probe()`，过程是
    「import + 构造 + 一次最小推理」；**UI 不构造任何识别器**。
    """
    global _probe_requested
    if _probe_requested:
        return
    module = _module()
    probe = getattr(module, "probe", None) if module else None
    if not callable(probe):
        return
    _probe_requested = True

    def _run() -> None:
        try:
            probe()
        except Exception:                      # noqa: BLE001
            logging.getLogger("lexara.ocr").exception("engine probe failed")

    threading.Thread(target=_run, name="ocr-probe", daemon=True).start()


def current_engine_id(settings) -> str:
    """当前选中的引擎。**永远只允许取到真实存在的那一档**。"""
    engines = list_engines()
    ids = [e["id"] for e in engines]
    available = [e for e in engines if e["state"] == "available"]
    if available:
        chosen = str(settings.get("ocr_engine", "rapid") or "rapid")
        if chosen in ids and any(e["id"] == chosen for e in available):
            return chosen
        return available[0]["id"]
    # 一个都还没验证可用：以**设置里存的**为准（Qoder 的记录优先），
    # 兜底 rapid —— 这里不声称任何引擎可用，UI 侧另有真实的 state 可显示。
    return _recorded_engine(settings, ids)


def _recorded_engine(settings, ids: list) -> str:
    module = _module()
    getter = getattr(module, "current_engine", None) if module else None
    if callable(getter):
        try:
            value = str(getter() or "").strip()
        except Exception:                      # noqa: BLE001
            value = ""
        if value in ids:
            return value
    chosen = str(settings.get("ocr_engine", "rapid") or "rapid")
    return chosen if chosen in ids else (ids[0] if ids else "rapid")


def scanning() -> bool:
    """是否正在扫描（扫描中不允许切换引擎）。后端没暴露就当没在扫。"""
    module = _module()
    probe = getattr(module, "is_scanning", None) if module else None
    if callable(probe):
        try:
            return bool(probe())
        except Exception:                      # noqa: BLE001
            return False
    return False


def switch_engine(settings, engine_id: str) -> dict:
    """切换引擎。成功与否由**后端**说了算，UI 不假装成功。"""
    engine_id = str(engine_id or "").strip()
    engines = {e["id"]: e for e in list_engines()}
    target = engines.get(engine_id)
    if target is None:
        return {"ok": False, "engine": engine_id,
                "message": "未知的识别引擎：%s" % engine_id}
    if target["state"] != "available":
        if target["state"] in ("loading", _UNKNOWN):
            # 还没结论不等于坏：如实说「还在验证」，别把用户引到别处去。
            return {"ok": False, "engine": engine_id,
                    "message": "%s 还在验证可用性（%s），请稍候。"
                               % (target["name"], target["stateLabel"])}
        return {"ok": False, "engine": engine_id,
                "message": "%s 暂不可用：%s" % (target["name"],
                                             target["reason"] or "后端未提供可用实现")}
    if scanning():
        return {"ok": False, "engine": engine_id,
                "message": "正在一次识词过程中，结束后再切换。"}
    module = _module()
    setter = getattr(module, "set_engine", None) if module else None
    if not callable(setter):
        # 后端还没提供切换能力。当前只打包了一个引擎，所以「换不动」本身就是真相。
        if engine_id == current_engine_id(settings):
            return {"ok": True, "engine": engine_id, "already": True,
                    "message": "已经是 %s 了。" % target["name"]}
        return {"ok": False, "engine": engine_id,
                "message": "OCR 后端尚未提供引擎切换接口（UI 不会自己切换）。"}
    try:
        result = setter(engine_id)
    except Exception as error:                 # noqa: BLE001
        return {"ok": False, "engine": engine_id,
                "message": "切换失败：%s" % error}
    ok, message = _unpack_result(result, "%s。" % target["name"])
    if ok:
        settings.set("ocr_engine", engine_id)
        return {"ok": True, "engine": engine_id, "message": message}
    return {"ok": False, "engine": engine_id, "message": message}


def _unpack_result(result, fallback: str) -> tuple:
    """把后端各种返回形状收敛成 ``(成功?, 消息)``。

    Qoder 的 `set_engine` 返回 ``(bool, str)``；更早的草案是 dict / bool。
    三种都要认，认不出来就**按失败处理**（宁可让用户重来，也不假装切成功）。
    """
    if isinstance(result, tuple):
        ok = bool(result[0]) if result else False
        message = str(result[1]) if len(result) > 1 and result[1] else ""
        return ok, message or fallback
    if isinstance(result, dict):
        return bool(result.get("ok")), str(result.get("message") or fallback)
    if isinstance(result, bool):
        return result, fallback if result else "引擎后端拒绝了这次切换。"
    return False, "引擎后端返回了无法识别的结果，按未切换处理。"
