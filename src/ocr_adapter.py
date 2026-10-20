# -*- coding: utf-8 -*-
"""OCR 统一层：一个数据结构、一条链路、多引擎可插拔。

为什么要有这一层（任务书 §3.2）：
    以前「用哪个引擎」这件事散落在三处 —— UI 上写死 "RapidOCR" 常量、
    `settings_store` 里有个没人读的 `ocr_engine` 键、真正干活的
    `ocr_engine.OcrEngine` 只认 RapidOCR。三者可以各说各话，
    于是「界面显示 PaddleOCR、后台其实跑 RapidOCR」这种不诚实状态是可能出现的。
    这一层把决定权收成一个函数（`current_engine()`）、一个出口（`recognize()`），
    **引擎选择只决定推理实现，不复制词典 / 词框 / 蜘蛛业务**。

契约见 `communite/contracts/ocr-result-contract.md`。

诚实性硬性要求：
    · `describe_engines()` 的 `state` 来自**真实探测**（import + 构造 + 一次最小推理），
      不是包名猜测，也不是 UI 的期望；
    · 探测失败 → 保持 RapidOCR 在跑，把真实原因交给 UI 显示，**绝不静默假装切换成功**；
    · 探测在子线程做，UI 不阻塞。
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

import numpy as np

ENGINE_RAPID = "rapid"
ENGINE_PADDLE = "paddle"

#: 探测用的文本。cv2.putText 画的是 Hershey 字体，和真实 UI 字体不一样，
#: 所以这里只要求「认回来的字符数够多」，不要求逐字精确 —— 探测证明的是
#: 「模型能加载 + 能推理 + 能返回框」，识别质量由 `Trainer/` 评测集负责。
PROBE_TEXT = "LEXARA"
PROBE_STATE_AVAILABLE = "available"
PROBE_STATE_UNAVAILABLE = "unavailable"
PROBE_STATE_LOADING = "loading"
PROBE_STATE_ERROR = "error"


# ---------------------------------------------------------------- 统一数据结构

@dataclass
class OCRWord:
    """一个单词 occurrence（契约 §1）。`bbox` 是**图像像素**，原点 = 送 OCR 的选区左上角。"""

    word_id: str
    text: str
    normalized: str
    bbox: tuple                 # (x, y, w, h)
    poly: tuple = ()            # tl,tr,br,bl（跟随行倾斜）
    confidence: float = 0.0
    line_id: str = ""
    engine_id: str = ENGINE_RAPID
    refined: bool = False       # 框边是否被墨迹投影细化过
    center: tuple = (0.0, 0.0)

    @property
    def area(self) -> float:
        return max(0.0, self.bbox[2]) * max(0.0, self.bbox[3])


@dataclass
class OCRLine:
    line_id: str
    text: str
    box: tuple                  # (x0, y0, x1, y1)
    confidence: float = 0.0
    poly: tuple = ()
    words: list = field(default_factory=list)
    engine_id: str = ENGINE_RAPID


@dataclass
class OCRResult:
    lines: list
    engine_id: str = ENGINE_RAPID
    elapsed_ms: float = 0.0
    error: str = ""
    degraded: bool = False      # True = 请求的引擎不可用，实际用了别的
    note: str = ""

    @property
    def words(self):
        return [w for ln in self.lines for w in ln.words]

    @property
    def ok(self) -> bool:
        return bool(self.lines) and not self.error


def _normalize(text: str) -> str:
    return (text or "").strip().strip("-'.,:;!?()[]{}\u201c\u201d\u3001\u3002").lower()


def make_word_id(engine_id: str, line_id: str, index: int, normalized: str) -> str:
    return "%s:%s:%d:%s" % (engine_id, line_id or "L?", index, normalized or "?")


def from_engine_lines(lines, engine_id: str = ENGINE_RAPID) -> list:
    """`ocr_engine.OcrLine` 列表 → 契约结构。

    ★ 这是**唯一**的转换点：任何新引擎要么产出同形状的行对象，
      要么在这里加一个分支，绝不允许下游出现「if engine == ...」。
    """
    out = []
    for i, ln in enumerate(lines or []):
        line_id = getattr(ln, "line_id", "") or "L%d" % i
        words = []
        for j, w in enumerate(getattr(ln, "words", None) or []):
            normalized = _normalize(getattr(w, "text", ""))
            left = float(getattr(w, "left", 0.0))
            right = float(getattr(w, "right", left))
            top = float(getattr(w, "top", getattr(ln, "box", (0, 0, 0, 0))[1]))
            bottom = float(getattr(w, "bottom", getattr(ln, "box", (0, 0, 0, 0))[3]))
            words.append(OCRWord(
                word_id=make_word_id(engine_id, line_id, j, normalized),
                text=str(getattr(w, "text", "")),
                normalized=normalized,
                bbox=(left, top, right - left, bottom - top),
                poly=tuple(getattr(w, "poly", ()) or ()),
                confidence=float(getattr(w, "confidence",
                                         getattr(ln, "score", 0.0)) or 0.0),
                line_id=line_id,
                engine_id=engine_id,
                refined=bool(getattr(w, "refined", False)),
                center=((left + right) / 2.0, (top + bottom) / 2.0),
            ))
        out.append(OCRLine(line_id=line_id, text=str(getattr(ln, "text", "")),
                           box=tuple(getattr(ln, "box", (0, 0, 0, 0))),
                           confidence=float(getattr(ln, "score", 0.0) or 0.0),
                           poly=tuple(getattr(ln, "poly", ()) or ()),
                           words=words, engine_id=engine_id))
    return out


# ---------------------------------------------------------------- 引擎探测

def probe_image() -> np.ndarray:
    """画一张「一定能被认出来」的小图（不依赖 Qt / 字体文件 / 网络）。"""
    import cv2
    canvas = np.full((96, 520, 3), 255, np.uint8)
    cv2.putText(canvas, PROBE_TEXT, (14, 62), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                (10, 10, 10), 3, cv2.LINE_AA)
    return cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)


def _text_overlap(text: str) -> int:
    target = set(PROBE_TEXT)
    return len(target & set((text or "").upper()))


class EngineProbe:
    """单个引擎的真实可用性缓存。

    状态机：unknown → loading → available | unavailable | error。
    `unavailable` 是「环境里根本没有 / 明确装不上」，`error` 是「装了但跑不通」，
    UI 上两者文案不同（前者提示安装，后者提示看日志并回退），别合并成一类。
    """

    def __init__(self, engine_id: str, label: str):
        self.engine_id = engine_id
        self.label = label
        self.state = "unknown"
        self.reason = ""
        self.version = ""
        self.seconds = None
        self._lock = threading.Lock()
        self._started = 0.0

    def snapshot(self) -> dict:
        return {"id": self.engine_id, "name": self.label, "state": self.state,
                "reason": self.reason, "version": self.version,
                "probe_seconds": self.seconds}

    def run(self, force: bool = False) -> dict:
        with self._lock:
            if self.state in (PROBE_STATE_AVAILABLE, PROBE_STATE_UNAVAILABLE) \
                    and not force:
                return self.snapshot()
            self.state = PROBE_STATE_LOADING
            self.reason = ""
            self._started = time.time()
        try:
            ok, reason, version, hits = _ENGINES[self.engine_id]()
            self.version = version
            self.seconds = round(time.time() - self._started, 2)
            if ok and hits >= 4:
                self.state = PROBE_STATE_AVAILABLE
                self.reason = ""
            elif ok:
                self.state = PROBE_STATE_ERROR
                self.reason = ("引擎能加载但探测图未认出足够字符（命中 %d/%d）："
                               "%s" % (hits, len(PROBE_TEXT), reason or "无附加信息"))
            else:
                self.state = PROBE_STATE_UNAVAILABLE
                self.reason = reason or "引擎不可用"
        except Exception as error:                # noqa: BLE001
            self.seconds = round(time.time() - self._started, 2)
            self.state = PROBE_STATE_ERROR
            self.reason = "%s: %s" % (type(error).__name__, error)
        return self.snapshot()


def _probe_rapid():
    """RapidOCR：import → 构造（模型加载）→ 一次最小推理。"""
    import importlib.metadata as md
    t0 = time.time()
    try:
        from rapidocr_onnxruntime import RapidOCR      # noqa: WPS433
    except Exception as error:                        # noqa: BLE001
        return False, "未安装 rapidocr_onnxruntime（%s）" % error, "", 0
    version = ""
    try:
        version = md.version("rapidocr_onnxruntime")
    except Exception:                                 # noqa: BLE001
        pass
    try:
        engine = RapidOCR()
    except Exception as error:                        # noqa: BLE001
        return False, "模型加载失败：%s" % error, version, 0
    if time.time() - t0 > 60:
        return False, "模型加载超时（>60s）", version, 0
    try:
        result, _ = engine(np.ascontiguousarray(probe_image()))
    except Exception as error:                        # noqa: BLE001
        return False, "CPU 推理失败：%s" % error, version, 0
    text = "".join(str(item[1]) for item in (result or []))
    return True, "", version, _text_overlap(text)


def _paddle_cache():
    """PaddleOCR 实例缓存（构造很贵：模型下载 + predictor 建立）。"""
    return getattr(_paddle_cache, "_obj", None)


#: PaddleOCR 3.x 在 Windows CPU 上**必须**关 oneDNN，否则推理直接抛
#: `NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute
#:  not support [pir::ArrayAttribute<pir::DoubleAttribute>]`
#: （`.../onednn/onednn_instruction.cc:118`）。
#: 2026-10-18 在 `.venv_paddle` 实测：默认参数三种调用全崩，
#: 加 `enable_mkldnn=False` 之后构造 6.2s / 推理 2.9s 跑通。
#: 这不是「我们传错了参数」—— 是 Paddle 3.x 新执行器（PIR）+ oneDNN 的实现缺口，
#: 所以绕法写死在这里，并在 `reason` 里如实告诉用户。
PADDLE_KWARGS = {"lang": "en", "enable_mkldnn": False}


def _paddle_ctor():
    """按 3.x → 2.x 的顺序构造 PaddleOCR，返回 ``(engine, 用的参数, 报错)``。

    顺序不能反：2.x 不认识 `enable_mkldnn`，3.x 不认识 `show_log/use_angle_cls`。
    """
    from paddleocr import PaddleOCR
    errors = []
    try:
        return PaddleOCR(**PADDLE_KWARGS), PADDLE_KWARGS, ""
    except TypeError as error:
        errors.append("3.x 参数被拒：%s" % error)
    except Exception as error:                            # noqa: BLE001
        return None, {}, "%s: %s" % (type(error).__name__, error)
    try:
        return (PaddleOCR(use_angle_cls=False, lang="en", show_log=False),
                {"use_angle_cls": False, "lang": "en", "show_log": False}, "")
    except Exception as error:                            # noqa: BLE001
        errors.append("2.x 参数也被拒：%s" % error)
    return None, {}, " | ".join(errors)


def _paddle_texts(result):
    """把 PaddleOCR 的返回统一成 ``[(poly, text, score)]``。

    3.x（paddleocr 3.7.0 实测）`predict()` 给的是**一list of dict-like 对象**：
        keys = rec_texts / rec_scores / rec_polys / rec_boxes / dt_polys / ...
    2.x 给的是 ``[[[poly, (text, score)], ...], ...]`` 嵌套 list。
    两种都得吃，因为「装到哪个版本」不是我们能决定的。
    """
    out = []
    for page in (result or []):
        # 3.x：一行一个结果对象，字段是数组
        keys = getattr(page, "keys", None)
        if callable(keys):
            data = page if isinstance(page, dict) else dict(page)
            texts = data.get("rec_texts") or []
            scores = data.get("rec_scores") or []
            polys = data.get("rec_polys") or data.get("dt_polys") or []
            for index, text in enumerate(texts):
                poly = polys[index] if index < len(polys) else None
                score = scores[index] if index < len(scores) else 0.0
                if poly is None or not len(poly):
                    continue
                out.append(([[float(p[0]), float(p[1])] for p in poly],
                            str(text), float(score)))
            continue
        # 2.x：[[poly, (text, score)], ...]
        for item in (page or []):
            try:
                poly, rec = item[0], item[1]
                out.append(([[float(p[0]), float(p[1])] for p in poly],
                            str(rec[0]), float(rec[1])))
            except Exception:                             # noqa: BLE001
                continue
    return out


def _paddle_infer(engine, arr):
    """推理：3.x 的 `predict()` 优先（`ocr()` 在 3.7.0 只是会打 DeprecationWarning
    的兼容壳），失败再退回 2.x 的 `ocr()`。"""
    try:
        return engine.predict(arr)
    except AttributeError:
        return engine.ocr(arr, cls=False)


def _probe_paddle():
    """PaddleOCR：真实验证，不猜。

    2026-10-18 独立环境实测结论（`.venv_paddle`：paddlepaddle 3.3.1 +
    paddleocr 3.7.0 + paddlex 3.7.2 + Python 3.13.15，全过程见
    `tools/paddle_isolated_probe.py` / `tools/paddle_api_probe.py` /
    `tools/paddle_workaround_probe.py` 的输出）：

      · **能跑通**，但必须 `enable_mkldnn=False`（见 `PADDLE_KWARGS` 注释）；
      · 首次构造会往 `~/.paddlex/official_models` 下 5 个模型（实测 177MB、
        76.5MB 那个是 `inference.pdiparams`），**模型不在应用目录里** ——
        打包要额外处理；
      · 依赖体积增量实测 **+378MB**（`.venv` 506MB → `.venv_paddle` 884MB）；
      · 缓存命中时构造 2.2~6.2s，探针图（96×520 合成 `LEXARA`）推理 2.9~3.2s，
        比 RapidOCR 的**真实选区**中位 1372ms 慢 —— 这是引擎事实，不是我们的实现；
      · 主环境 `.venv` **没有装** paddle，所以打包版探测结果就是
        「未安装 + 原因」，UI 上必须显示为不可用（不许假切换）。
    """
    import importlib.metadata as md
    try:
        from paddleocr import PaddleOCR               # noqa: F401,WPS433
    except Exception as error:                        # noqa: BLE001
        return False, ("主环境未安装 paddleocr/paddlepaddle（%s）。"
                       "已在独立环境 .venv_paddle 验证可跑通（需 enable_mkldnn=False，"
                       "模型另占 177MB、依赖 +378MB），但未打包 → 界面保持不可用。"
                       % type(error).__name__), "", 0
    version = ""
    try:
        version = md.version("paddleocr")
    except Exception:                                 # noqa: BLE001
        pass
    cwd = os.getcwd()
    try:
        cwd.encode("ascii")
        path_note = ""
    except UnicodeEncodeError:
        path_note = "当前工作目录含非 ASCII 字符（%s），Paddle 的 C++ 层可能直接失败" % cwd
    engine, used_kwargs, error = _paddle_ctor()
    if engine is None:
        return False, "PaddleOCR 构造失败：%s %s（试过的参数：%s）" % (
            error, path_note, used_kwargs or "3.x/2.x 两轮都被拒"), version, 0
    _paddle_cache._obj = engine
    try:
        res = _paddle_infer(engine, probe_image())
    except Exception as error:                        # noqa: BLE001
        return False, ("PaddleOCR 推理失败：%s: %s %s"
                       % (type(error).__name__, str(error)[:200],
                          path_note)), version, 0
    rows = _paddle_texts(res)
    text = "".join(row[1] for row in rows)
    ok = bool(text)
    return ok, ("" if ok else "推理返回空结果（调用参数 %s）" % used_kwargs), \
        version, _text_overlap(text)



_ENGINES = {ENGINE_RAPID: _probe_rapid, ENGINE_PADDLE: _probe_paddle}

#: ★ 2026-10-19：PaddleOCR 已从引擎清单里摘掉（v1 只随包分发 RapidOCR）。
#: 只从 `_PROBES` 移除，不删 `_probe_paddle` / `_recognize_paddle` 的实现——
#: 那段能在 `.venv_paddle` 里跑通，留着当「以后真要接第二个引擎」的现成参考；
#: 但**它不会再出现在任何 UI 列表里**，也不会被 `probe()` 顺手探出来。
_PROBES = {eid: EngineProbe(eid, label) for eid, label in
           ((ENGINE_RAPID, "RapidOCR"),)}

#: 运行期真正生效的引擎。初值一律是 rapid —— 「默认可用」这件事不需要证明，
#: 证明过的才允许变成别的。
_current = ENGINE_RAPID
_current_lock = threading.Lock()


def describe_engines() -> list:
    """给 UI 的引擎清单（**不触发**探测；探测用 `probe()`，在子线程调）。"""
    return [p.snapshot() for p in _PROBES.values()]


def probe(engine_id: str = None, force: bool = False) -> list:
    """真实探测（阻塞数秒）。**必须在子线程调用**。"""
    ids = [engine_id] if engine_id else list(_PROBES)
    out = []
    for eid in ids:
        if eid not in _PROBES:
            out.append({"id": eid, "name": eid, "state": PROBE_STATE_ERROR,
                        "reason": "未知引擎 id"})
            continue
        out.append(_PROBES[eid].run(force=force))
    return out


def probe_state(engine_id: str) -> str:
    p = _PROBES.get(engine_id)
    return p.state if p else "unknown"


def current_engine() -> str:
    with _current_lock:
        return _current


def set_engine(engine_id: str) -> tuple:
    """切换引擎。返回 ``(成功?, 给 UI 显示的原因)``。

    ★ 不可用时**不切换**，并且把原因原样交回 —— 由调用方决定怎么显示。
      这里刻意不做「静默回退到 rapid 并返回 True」，那正是任务书禁止的假切换。
    """
    global _current
    if engine_id not in _PROBES:
        return False, "未知 OCR 引擎：%s" % engine_id
    snap = _PROBES[engine_id].snapshot()
    if snap["state"] == "unknown":
        return False, ("%s 尚未完成可用性探测，请稍后再试（探测在后台进行中）"
                       % snap["name"])
    if snap["state"] == PROBE_STATE_LOADING:
        return False, ("%s 正在探测可用性（加载模型需要几秒），请等待完成"
                       % snap["name"])
    if snap["state"] != PROBE_STATE_AVAILABLE:
        return False, "%s 当前不可用：%s" % (snap["name"], snap["reason"])
    with _current_lock:
        _current = engine_id
    return True, "已切换到 %s" % snap["name"]


def engine_lines(arr):
    """按**当前生效引擎**跑一遍，返回 ``(lines, engine_id, note)``。

    这是给 `OcrWorker` / `SenseWorker` 用的「旧形状」出口：
    它们下游（词典 / 词框 / 八腿 / 队列）吃的都是 `ocr_engine.OcrLine`，
    换引擎**不应该**牵动那些业务，所以这里只换推理实现，不换数据结构
    （任务书 §3.2：引擎选择只决定推理实现）。

    `note` 非空 = 发生了**明确记录**的回退。返回 ``(bool, str)`` 而不是悄悄换：
    「界面显示 PaddleOCR、后台其实跑 RapidOCR」正是这一层要消灭的状态。
    """
    from ocr_engine import OcrEngine

    wanted = current_engine()
    if wanted == ENGINE_PADDLE:
        lines, error = _recognize_paddle(arr)
        if error:
            return (OcrEngine.recognize_lines(arr), ENGINE_RAPID,
                    "PaddleOCR 失败，本轮已回退 RapidOCR：%s" % error)
        return lines, ENGINE_PADDLE, ""
    return OcrEngine.recognize_lines(arr), ENGINE_RAPID, ""


def configure(engine_id: str) -> tuple:
    """启动时按持久化设置选引擎；失败则保持 rapid 并回传原因（供 UI 提示）。"""
    if not engine_id or engine_id == _current:
        return True, ""
    return set_engine(engine_id)


# ---------------------------------------------------------------- 统一识别入口

def recognize(arr, engine_id: str = None, min_conf: float = 0.0) -> OCRResult:
    """图像（RGB ndarray 或 QImage）→ 契约结构。

    线程约定同 `OcrEngine.recognize_lines`：**子线程必须传 ndarray**，
    传 QImage 属于 GUI 线程操作，实测会把进程崩成 exit 127。
    """
    from ocr_engine import OcrEngine, qimage_to_ndarray

    wanted = engine_id or current_engine()
    t0 = time.time()
    if arr is None:
        return OCRResult([], engine_id=wanted, error="空图像",
                         elapsed_ms=0.0)
    if not isinstance(arr, np.ndarray):
        arr = qimage_to_ndarray(arr)
    if arr is None or getattr(arr, "size", 0) == 0:
        return OCRResult([], engine_id=wanted, error="图像转换失败")

    degraded, note, used = False, "", wanted
    if wanted == ENGINE_PADDLE:
        lines, err = _recognize_paddle(arr)
        if err:
            # 请求的引擎跑不通 → 明确回退 + 记录，**不静默**
            used, degraded, note = ENGINE_RAPID, True, ("PaddleOCR 失败，已回退 "
                                                        "RapidOCR：%s" % err)
            lines = OcrEngine.recognize_lines(arr)
        else:
            lines = lines
    else:
        used = ENGINE_RAPID
        lines = OcrEngine.recognize_lines(arr)

    contract = from_engine_lines(lines, used)
    if min_conf > 0:
        contract = [ln for ln in contract if ln.confidence <= 0
                    or ln.confidence >= min_conf]
    error = "" if used == ENGINE_RAPID and wanted == ENGINE_RAPID else ""
    return OCRResult(lines=contract, engine_id=used,
                     elapsed_ms=round((time.time() - t0) * 1000.0, 1),
                     error=error, degraded=degraded, note=note)


def _recognize_paddle(arr):
    """PaddleOCR → 与 RapidOCR 同形状的**旧**行对象（复用同一套下游转换）。

    只有 `probe_state("paddle") == available` 时才可能被调到。
    返回 ``(lines, error)``；lines 是 `ocr_engine.OcrLine`，
    因此词典 / 词框 / 蜘蛛链路完全不需要知道引擎换过。

    ★ 3.x / 2.x 的返回形状不同（3.x 是 `rec_texts/rec_scores/rec_polys` 的 dict-like，
      2.x 是嵌套 list），统一先过 `_paddle_texts()`，下面这段只认一种形状。
    """
    engine = _paddle_cache()
    if engine is None:
        return [], "PaddleOCR 未初始化（先跑 probe）"
    try:
        res = _paddle_infer(engine, arr)
    except Exception as error:                        # noqa: BLE001
        return [], "%s: %s" % (type(error).__name__, str(error)[:200])
    from ocr_engine import OcrLine, _split_line_words
    lines = []
    for index, (poly, text, score) in enumerate(_paddle_texts(res)):
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        box = (min(xs), min(ys), max(xs), max(ys))
        ordered = OcrEngine_ordered(xs, ys)
        lines.append(OcrLine(text=text, box=box, score=score, poly=ordered,
                             line_id="P%d" % index,
                             words=_split_line_words(text, box, arr=arr,
                                                     poly=ordered,
                                                     line_id="P%d" % index,
                                                     score=score)))
    return lines, ""


def OcrEngine_ordered(xs, ys):
    from ocr_engine import OcrEngine
    return OcrEngine._ordered_poly(xs, ys)


def word_context(line: OCRLine, word: OCRWord, radius: int = 1) -> str:
    """给 AI 的上下文：同一行的整句（任务书 §5.2「只发必要文本」）。"""
    return (line.text or "")[:4000]


def stats() -> dict:
    return {"current": current_engine(),
            "engines": describe_engines(),
            "probe_done": {eid: (p.state != "unknown")
                           for eid, p in _PROBES.items()}}


def engine_status() -> dict:
    """契约 §6 的状态快照：现有 `OcrEngine.stats()` 的超集。"""
    from ocr_engine import OcrEngine
    data = stats()
    data["rapid"] = OcrEngine.stats()
    data["effective"] = next((e for e in data["engines"]
                              if e["id"] == data["current"]), {})
    return data
