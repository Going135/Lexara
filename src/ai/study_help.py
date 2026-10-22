# -*- coding: utf-8 -*-
"""背单词卡片的 AI 辅助：造句 / 同义词。

为什么单独一个服务，而不是复用 `ChatService`
--------------------------------------------
`ChatService` 的语义是「一条连续的会话」：它会把历史消息一起发出去、把回复
追加进 `messages` 列表、并在 QML 的对话页里渲染。背单词要的是**一次性的
旁路查询**：

- **互不污染**：用户点「造句」不该让对话页多出两条消息，也不该被上一轮对话
  的上下文影响（那会让同一张卡片两次点击得到不同难度的句子）；
- **可缓存**：翻回上一张卡片时，刚才那句例句应该立刻回来，而不是再花一次
  网络请求和两秒等待；
- **可作废**：卡片一换（自评 / 上一个 / 退出），在途请求的结果必须丢弃，
  否则「上一张的例句」会盖到下一张上。

所以这里只有三件事：拼提示词、跑后台线程、按 (单词, 模式) 缓存结果。

输出是**纯文本**，QML 侧用只读 `TextArea` 展示（不渲染 Markdown）——
和 `chat.py` 同一条红线：模型输出当不可信输入处理。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

#: `_Worker` 是 chat.py 里的线程实现。这里直接复用而不是再写一个 QThread：
#: 请求体、超时、错误翻译三条逻辑只该有一份（`classify_error` 的文案都在
#: 那里，重写一份必然漂）。下划线前缀表示「包内共用」，跨包引用才是红线。
from .chat import _Worker, classify_error
from .config import validate_endpoint
from . import persona

#: 两种辅助能力的 id。QML 传的就是这两个字符串。
MODE_SENTENCE = "sentence"
MODE_SYNONYM = "synonym"

MODE_LABELS = {MODE_SENTENCE: "造句", MODE_SYNONYM: "同义词"}

#: 结果最长字符数。示例句 / 同义词都是短输出，截断只会发生在模型跑题时。
MAX_HELP_CHARS = 1200
#: 请求超时（秒）。比对话的 20s 略宽：有些服务在 max_tokens 小时反而更慢。
HELP_TIMEOUT = 25.0
#: 单次最多生成多少 token。给足两句例句 + 中文翻译，又不至于让模型写小作文。
HELP_MAX_TOKENS = 520
#: 缓存条数上限（按「最近最少用」淘汰）。一局 20 张卡片 × 2 种模式 = 40 条，
#: 120 够翻上好几十张还不淘汰，同时不会无限涨。
MAX_CACHE = 120

_NO_MEANING = "（本地词典没有这个词的中文释义）"

#: 每种模式的**输出格式**要求。放在后端而不是 QML：改口径不用碰界面，
#: 也方便单测直接断言「提示词里有没有写清只要结果、不要寒暄」。
MODE_TASKS = {
    MODE_SENTENCE: (
        "用英文单词「{word}」造 2 个句子。要求：\n"
        "1. 每句单独一行，行首写「1. 」「2. 」；句子下一行紧跟中文翻译，行首写「译：」。\n"
        "2. 句子要体现这个词最常用的搭配与用法，不要挑生僻义项。\n"
        "3. 难度对标{difficulty}，每句不超过 20 个词。\n"
        "4. 只输出句子和翻译，不要标题、不要解释、不要总结，也不要说「好的」「当然」。"
    ),
    MODE_SYNONYM: (
        "给出英文单词「{word}」的 3 个同义词或近义词。要求：\n"
        "1. 每个词一行，格式为「word（词性）— 一句中文，说明它和 {word} 的细微差别」。\n"
        "2. 只列多数语境下真的能替换的词；不要反义词，不要同一词根的其他词形。\n"
        "3. 难度不超过{difficulty}。\n"
        "4. 只输出这三行词条，不要标题、不要总结段落。"
    ),
}


def _difficulty(level: str) -> str:
    """把档位翻成提示词里能直接读的中文。"""
    label = persona.LEVEL_LABELS.get(persona.normalize_level(level))
    return label or "大学英语四级"


def build_messages(word: str, meaning: str = "", mode: str = MODE_SENTENCE,
                   level: str = persona.CET) -> list:
    """拼出请求体。**纯函数**，单测直接断言内容。

    只发三样东西：单词、本地词典释义、格式要求。**不带截屏、不带历史对话**。
    释义在这里很关键 —— ``bank`` 这类多义词，没有释义时模型会随机挑一个义项，
    而卡片上显示的是另一个，用户会觉得 AI 答非所问。
    """
    mode = str(mode or "").strip().lower()
    task = MODE_TASKS.get(mode)
    if task is None:
        raise ValueError("未知的辅助模式：%r" % (mode,))
    word = (word or "").strip()
    if not word:
        raise ValueError("单词为空")
    difficulty = _difficulty(level)
    system = persona.system_prompt(
        task_note="【本次任务】你在给单词卡片做辅助说明。只要结果本身，"
                  "不要寒暄、不要复述用户的要求、不要额外建议怎么背。",
        level=level, style="chat")
    body = ["单词：%s" % word]
    body.append("词典释义：%s" % ((meaning or "").strip() or _NO_MEANING))
    body.append("")
    body.append(task.format(word=word, difficulty=difficulty))
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n".join(body)}]


def _idle_state() -> dict:
    return {"state": "idle", "word": "", "mode": "", "modeLabel": "",
            "text": "", "error": "", "code": "", "elapsed": 0.0}


class StudyHelpService(QObject):
    """一次一张卡片的 AI 辅助。生命周期 = 启动台窗口。

    状态机（QML 只读 `state`）：

        idle ──request()──▶ loading ──ok──▶ done
                              │
                              ├──error──▶ error      （含未配置 / 网络 / 401 …）
                              └──reset()──▶ idle     （换卡片时调用）
    """

    #: 任何一次状态变化都发（QML 通过 `bridge.reviewHelp` 整体重绑）
    changed = Signal()

    def __init__(self, config, parent=None, worker_factory=None):
        super().__init__(parent)
        self.config = config
        self._factory = worker_factory
        self._state = _idle_state()
        self._cache: dict = {}
        self._cache_order: list = []
        self._worker = None
        #: 递增请求号：换卡片后旧线程的结果一律丢弃（同 `ChatService`)
        self._generation = 0

    # ---- QML 读
    @property
    def state(self) -> dict:
        return dict(self._state)

    @property
    def loading(self) -> bool:
        return self._state.get("state") == "loading"

    # ---- 对外动作
    def request(self, word: str, meaning: str = "", mode: str = MODE_SENTENCE) -> bool:
        """发起一次辅助查询。返回 True 表示**已经开始/已命中缓存**。

        失败原因不抛异常，全部落到 `state["error"]` —— QML 没有地方接异常，
        抛出去只会变成一条控制台 traceback，用户看到的是「点了没反应」。
        """
        word = (word or "").strip()
        mode = str(mode or "").strip().lower()
        if not word or mode not in MODE_TASKS:
            return False
        if (self._state.get("state") == "loading"
                and self._state.get("word") == word
                and self._state.get("mode") == mode):
            return False                      # 同一张卡片同一种问法：正在跑，别叠请求

        cached = self._cache.get((word.lower(), mode))
        if cached:
            self._touch(word.lower(), mode)
            self._set({"state": "done", "word": word, "mode": mode,
                       "modeLabel": MODE_LABELS[mode], "text": cached,
                       "error": "", "code": "", "elapsed": 0.0})
            return True

        try:
            key = self.config.api_key()
            base = self.config.base_url()
            model = self.config.model()
        except Exception as error:            # noqa: BLE001 配置层异常 → 展示，不崩
            code, message = classify_error(error)
            self._fail(word, mode, code, message)
            return False
        missing = [name for name, value in (("API Key", key), ("Base URL", base),
                                            ("模型名", model)) if not value]
        if missing:
            self._fail(word, mode, "not_configured",
                       "还没有配置模型（缺 %s）。到「AI 对话」页填好就能用。"
                       % "、".join(missing))
            return False
        # 端点校验交给 config 的公开实现：**不在这里抄一遍 URL 规则**。
        try:
            _, endpoint = validate_endpoint(base)
        except Exception as error:            # noqa: BLE001 AIConfigError
            code, message = classify_error(error)
            self._fail(word, mode, code, message)
            return False

        try:
            messages = build_messages(
                word, meaning, mode,
                persona.level_from_settings(getattr(self.config, "settings", None)))
        except ValueError as error:
            self._fail(word, mode, "bad_request", str(error))
            return False

        self._discard_worker()
        generation = self._generation
        worker = self._make_worker(endpoint, key, model, messages)
        worker.finished_with.connect(
            lambda ok, payload, g=generation: self._on_done(g, ok, payload))
        self._worker = worker
        self._set({"state": "loading", "word": word, "mode": mode,
                   "modeLabel": MODE_LABELS[mode], "text": "", "error": "",
                   "code": "", "elapsed": 0.0})
        worker.start()
        return True

    def reset(self) -> None:
        """换卡片 / 关面板时调用：丢弃在途请求，回到 idle。**缓存保留**。"""
        self._discard_worker()
        if self._state.get("state") != "idle":
            self._state = _idle_state()
            self.changed.emit()

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_order.clear()

    # ---- 内部
    def _make_worker(self, endpoint: str, key: str, model: str, messages: list):
        if self._factory is not None:
            return self._factory(endpoint, key, model, messages)
        return _Worker(endpoint, key, model, messages,
                       timeout=HELP_TIMEOUT, max_tokens=HELP_MAX_TOKENS,
                       parent=self)

    def _discard_worker(self) -> None:
        worker, self._worker = self._worker, None
        self._generation += 1                 # 在途结果作废
        if worker is None:
            return
        cancel = getattr(worker, "cancel", None)
        running = getattr(worker, "isRunning", None)
        try:
            if callable(running) and running():
                cancel and cancel()
        except RuntimeError:                  # 线程对象已析构
            pass

    def _on_done(self, generation: int, ok: bool, payload: dict) -> None:
        if generation != self._generation:
            return                            # 旧卡片的结果，丢弃
        self._worker = None
        word = self._state.get("word", "")
        mode = self._state.get("mode", "")
        if payload.get("cancelled"):
            self._state = _idle_state()
            self.changed.emit()
            return
        if not ok:
            self._fail(word, mode, payload.get("code", "unexpected"),
                       payload.get("message", "请求失败。"),
                       elapsed=payload.get("elapsed", 0.0))
            return
        text = (payload.get("text") or "").strip()
        if not text:
            self._fail(word, mode, "empty_reply",
                       "模型这次什么都没回。再点一次试试，或换个模型。",
                       elapsed=payload.get("elapsed", 0.0))
            return
        if len(text) > MAX_HELP_CHARS:
            text = text[:MAX_HELP_CHARS].rstrip() + "…"
        self._remember(word.lower(), mode, text)
        self._set({"state": "done", "word": word, "mode": mode,
                   "modeLabel": MODE_LABELS.get(mode, ""), "text": text,
                   "error": "", "code": "",
                   "elapsed": payload.get("elapsed", 0.0)})

    def _fail(self, word: str, mode: str, code: str, message: str,
              elapsed: float = 0.0) -> None:
        self._set({"state": "error", "word": word, "mode": mode,
                   "modeLabel": MODE_LABELS.get(mode, ""), "text": "",
                   "error": message, "code": code, "elapsed": elapsed})

    def _remember(self, word: str, mode: str, text: str) -> None:
        key = (word, mode)
        self._cache[key] = text
        self._touch(word, mode)
        while len(self._cache_order) > MAX_CACHE:
            old = self._cache_order.pop(0)
            self._cache.pop(old, None)

    def _touch(self, word: str, mode: str) -> None:
        key = (word, mode)
        if key in self._cache_order:
            self._cache_order.remove(key)
        self._cache_order.append(key)

    def _set(self, state: dict) -> None:
        self._state = dict(state)
        self.changed.emit()
