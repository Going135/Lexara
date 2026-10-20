# -*- coding: utf-8 -*-
"""对话式 AI：给底部输入区一个**真的会发请求**的后端。

三条硬约束（任务书 4.4 / 5.2）
------------------------------
1. **不阻塞 GUI**：请求跑在 `QThread` 里，结果通过信号回主线程；
2. **不上传截图**：请求体只有用户输入的文字 + 一句系统提示词；
3. **不泄露密钥**：错误信息里出现的 key 一律 `mask()` 掉，且不记录响应头。

不可信输出处理（任务书 4.4）
----------------------------
模型回复当**不可信输入**处理：这里只做长度截断与纯文本化，
不做 HTML/Markdown 渲染；QML 侧用 `TextEdit` 的纯文本模式展示，
避免把模型输出当成富文本执行。

为什么先做非流式
----------------
当前 provider 抽象的调用是一次性返回完整 JSON。
不做流式就不能假装在流式 —— 所以 UI 用明确的「思考中」状态，
而不是一个假装一个字一个字往外吐的效果。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .config import AIConfig, AIConfigError, mask, validate_endpoint
from . import persona

#: 单条回复的最大字符数，防止模型一次性吐回超长内容。
MAX_REPLY_CHARS = 8000
#: 单次请求超时（秒）。沿用 `cloud_provider` 12 秒的量级，给对话留些余量。
DEFAULT_TIMEOUT = 20.0
#: 会话里保留的最大消息条数（含用户与助手），超出丢最早的。
MAX_HISTORY = 40

#: 对话人设。**唯一事实源在 `ai/persona.py`** —— 以前这里自己写了一份，
#: 和 `context_request` / `cloud_provider` 那两份互相不知道对方存在。
#: 现在只保留这个常量给「拿不到 settings 的场景」兜底，实际请求走
#: `_history_for_request()` 里按用户档位现拼。
SYSTEM_PROMPT = persona.system_prompt(style="chat")


#: 空状态时给用户看的示例。**只有在真的配好模型之后**才展示（UI 侧已按
#: `bridge.aiReady` 控制），避免出现「点了没反应」的装饰性文字。
EXAMPLE_PROMPTS = [
    "解释 abandon 在句末的含义，并给两个常用搭配",
    "用 accelerate 造三个难度递增的句子",
    "分辨 affect 和 effect，给一句容易记的口诀",
    "这段英文里哪些词值得背：The committee abandoned the project.",
    # 备考咨询也是人设的一部分（`ai/persona.py` 的备考口径），
    # 空状态里得有一条让用户看出「可以问规划」，不然这能力没人会发现。
    "还有 40 天考四级，听力总在 130 分上下，怎么提",
]


def classify_error(error: Exception, baseline_url: str = "") -> tuple[str, str]:
    """把异常翻译成 (code, 用户能看懂的下一步)。**绝不**回显密钥。"""
    if isinstance(error, AIConfigError):
        return error.code, str(error)
    if isinstance(error, urllib.error.HTTPError):
        status = getattr(error, "code", 0)
        table = {
            400: ("bad_request", "请求被服务商拒绝（400）。检查模型名是否支持 chat，以及是否要求特定参数。"),
            401: ("auth", "API Key 无效或未通过验证（401）。请重新填写密钥。"),
            403: ("auth", "没有权限访问这个模型（403）。检查账号额度与模型白名单。"),
            404: ("model_missing", "找不到这个模型（404）。请确认模型名称填写正确。"),
            408: ("timeout", "请求超时（408）。稍后重试，或换一个响应更快的服务。"),
            409: ("bad_request", "请求冲突（409）。检查模型与参数组合。"),
            422: ("bad_request", "请求参数不被接受（422）。"),
            429: ("rate_limit", "触发速率限制或额度不足（429）。稍后再试，或检查账户余额。"),
        }
        code, message = table.get(status, (None, None))
        if code is None:
            if 500 <= status < 600:
                return ("server_error",
                        "服务商内部错误（%d）。这是对方的问题，稍后重试即可。" % status)
            return ("http_error", "请求失败（HTTP %d）。请检查地址与模型名。" % status)
        return code, message
    if isinstance(error, urllib.error.URLError):
        reason = getattr(error, "reason", None)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return ("timeout", "连接超时。检查网络，或把超时时间放宽（本机模型可能首次加载较慢）。")
        return ("network", "连不上服务器。检查地址是否正确、网络是否可用，"
                           "以及本机模型的服务是否已启动。")
    if isinstance(error, TimeoutError):
        return ("timeout", "请求超时（%.0fs 内没有响应）。" % DEFAULT_TIMEOUT)
    if isinstance(error, json.JSONDecodeError):
        return ("bad_response", "服务商返回的不是合法 JSON —— 地址可能填错，"
                                "或填的不是一个 chat 接口。")
    if isinstance(error, KeyError):
        return ("bad_response", "响应里缺少内容字段，可能不是 OpenAI 兼容接口。")
    text = str(error) or error.__class__.__name__
    return ("unexpected", "请求失败：%s" % mask(text))


# ---------------------------------------------------------------- worker
class _Worker(QThread):
    """后台线程：一次 chat 请求。**不持有任何 Qt Widget**。"""

    finished_with = Signal(object, object)     # (ok: bool, payload: dict)

    def __init__(self, endpoint: str, api_key: str, model: str,
                 messages: list, timeout: float = DEFAULT_TIMEOUT,
                 max_tokens: int | None = None, parent=None):
        super().__init__(parent)
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.messages = messages
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _read_body(self, request: urllib.request.Request) -> bytes:
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            chunks = []
            while True:
                if self._cancelled:
                    raise TimeoutError("cancelled")
                chunk = response.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(len(c) for c in chunks) > 1024 * 1024 + 1:
                    raise ValueError("响应过大（>1MB）")
        return b"".join(chunks)

    def run(self) -> None:                     # noqa: D102
        started = time.time()
        try:
            body = json.dumps({
                "model": self.model,
                "messages": self.messages,
                "temperature": 0.4,
                **({"max_tokens": self.max_tokens} if self.max_tokens else {}),
            }).encode("utf-8")
            request = urllib.request.Request(
                self.endpoint, body, {
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                    "User-Agent": "Lexara/1.0",
                })
            raw = self._read_body(request)
            if self._cancelled:
                raise TimeoutError("cancelled")
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            choices = payload.get("choices")
            if not choices:
                raise KeyError("choices")
            content = choices[0].get("message", {}).get("content", "")
            if not isinstance(content, str):
                raise ValueError("回复内容不是字符串")
            elapsed = time.time() - started
            self.finished_with.emit(True, {
                "text": content[:MAX_REPLY_CHARS],
                "truncated": len(content) > MAX_REPLY_CHARS,
                "elapsed": round(elapsed, 2),
                "model": payload.get("model") or self.model,
            })
        except Exception as error:             # noqa: BLE001
            elapsed = time.time() - started
            if isinstance(error, TimeoutError) and str(error) == "cancelled":
                self.finished_with.emit(False, {"cancelled": True,
                                                "elapsed": round(elapsed, 2)})
                return
            code, message = classify_error(error)
            self.finished_with.emit(False, {"code": code, "message": message,
                                            "elapsed": round(elapsed, 2)})


# ---------------------------------------------------------------- service
class ChatService(QObject):
    """当前会话的消息列表 + 发送状态。生命周期 = 一个启动台窗口。

    刻意**不做持久化**：任务书 4.2 明确说「如果项目当前没有持久化聊天历史，
    不要假装有历史」。这里只保留内存里的当前会话，清空即消失。
    """

    #: 每次消息列表变化都发一次（QML ListView 直接整体重绑，够用且省心）
    messagesChanged = Signal()
    #: 请求中 busy 状态变化
    busyChanged = Signal()
    #: 最后一条结果的错误摘要变化
    statusChanged = Signal()
    #: 连接测试开始 / 结束（异步，不卡 GUI；结束时带一个 dict 结果）
    testStarted = Signal()
    testFinished = Signal(dict)
    #: 一次对话**真的收到回复**（`ok` 且文本非空）。启动台用它记学习活动日
    #: （任务书 §7.1 深绿口径），失败 / 取消 / 未配置都不会发这个信号。
    askSucceeded = Signal()
    #: 连接测试的进行中状态（True/False 两端都会发）
    testingChanged = Signal(bool)

    def __init__(self, config: AIConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._messages: list = []
        self._busy = False
        self._worker: _Worker | None = None
        self._status: dict = {}
        self._testing = False
        self._test_worker: _Worker | None = None
        #: 递增的请求号。用户点了「取消」之后旧线程可能还在跑，
        #: 用它保证**旧结果不会覆盖新会话**。
        self._generation = 0

    # ---- QML 读
    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def testing(self) -> bool:
        return self._testing

    @property
    def messages(self) -> list:
        return [dict(m) for m in self._messages]

    @property
    def status(self) -> dict:
        return dict(self._status)

    # ---- QML 写
    @Slot(str, result=bool)
    def send(self, text: str) -> bool:
        text = (text or "").strip()
        if self._busy:
            return False
        if not text:
            self._set_status({"code": "empty", "message": "请输入内容后再发送。"})
            return False
        try:
            key = self.config.api_key()
            base = self.config.base_url()
            model = self.config.model()
        except AIConfigError as error:
            self._set_status({"code": error.code, "message": str(error)})
            return False
        if not key or not base or not model:
            self._set_status({
                "code": "not_configured",
                "message": "还没有配置模型。打开设置填写 Base URL、模型名和 API Key。",
                "action": "open_settings"})
            return False
        try:
            _, endpoint = validate_endpoint(base)
        except AIConfigError as error:
            self._set_status({"code": error.code, "message": str(error)})
            return False

        self._append({"role": "user", "text": text, "state": "sent", "at": _now()})
        self._append({"role": "assistant", "text": "", "state": "pending",
                      "at": _now(), "elapsed": 0})
        self._generation += 1
        generation = self._generation
        history = self._history_for_request()
        worker = _Worker(endpoint, key, model, history,
                         timeout=DEFAULT_TIMEOUT, parent=self)
        worker.finished_with.connect(
            lambda ok, payload, g=generation: self._on_done(g, ok, payload))
        self._worker = worker
        self._busy = True
        self.busyChanged.emit()
        self._set_status({})
        worker.start()
        return True

    @Slot()
    def cancel(self) -> None:
        """取消当前请求 / 连接测试。已写盘的结果不受影响。"""
        test = self._test_worker
        if test is not None and test.isRunning():
            test.cancel()
            test.wait(2000)
            return
        worker = self._worker
        if worker is not None and worker.isRunning():
            self._generation += 1           # 让在途结果作废
            worker.cancel()
            worker.wait(3000)

    @Slot()
    def newSession(self) -> None:
        self.cancel()
        self._messages = []
        self.messagesChanged.emit()
        self._set_status({})

    @Slot(result=str)
    def copyLastReply(self) -> str:
        for message in reversed(self._messages):
            if message.get("role") == "assistant" and message.get("text"):
                return message["text"]
        return ""

    @Slot(str, result=str)
    def copyMessage(self, text: str) -> str:
        return text or ""

    # ---- 测试连接（只有用户点「测试连接」才会真的发出一个最小请求）
    #: 注意：**真的会向服务商发一个请求并可能产生费用**，UI 上必须写清楚。
    @Slot(result=bool)
    def testConnection(self) -> bool:
        if self._busy or self._testing:
            return False
        try:
            key = self.config.api_key()
            base = self.config.base_url()
            model = self.config.model()
        except AIConfigError as error:
            self.testFinished.emit({"ok": False, "code": error.code,
                                    "message": str(error)})
            return False
        missing = [name for name, value in (("API Key", key), ("Base URL", base),
                                            ("模型名", model)) if not value]
        if missing:
            self.testFinished.emit({"ok": False, "code": "not_configured",
                                    "message": "还缺：" + "、".join(missing)})
            return False
        try:
            _, endpoint = validate_endpoint(base)
        except AIConfigError as error:
            self.testFinished.emit({"ok": False, "code": error.code,
                                    "message": str(error)})
            return False
        worker = _Worker(endpoint, key, model,
                         [{"role": "user", "content": "ping"}],
                         timeout=15.0, max_tokens=8, parent=self)
        worker.finished_with.connect(self._on_test_done)
        self._test_worker = worker
        self._testing = True
        self.testStarted.emit()
        self.testingChanged.emit(True)
        worker.start()
        return True

    def _on_test_done(self, ok: bool, payload: dict) -> None:
        self._testing = False
        self._test_worker = None
        self.testingChanged.emit(False)
        elapsed = float(payload.get("elapsed", 0))
        if payload.get("cancelled"):
            result = {"ok": False, "code": "cancelled", "message": "测试已取消。"}
        elif ok:
            result = {"ok": True, "elapsed": elapsed,
                      "model": payload.get("model") or self.config.model(),
                      "message": "连接成功 · 用时 %.2fs" % elapsed}
        else:
            result = {"ok": False, "code": payload.get("code", "unexpected"),
                      "message": payload.get("message", "连接失败。")}
        self.config.remember_test(result["ok"], result["message"], elapsed,
                                  result.get("model", ""))
        self.testFinished.emit(result)

    # ---- 内部
    def _level(self) -> str:
        """用户当前备考档位（启动台上选的那一档）。"""
        return persona.level_from_settings(getattr(self.config, "settings", None))

    def _history_for_request(self) -> list:
        """给 provider 的消息数组。只取文本，**不附带任何截图或 OCR 结果**。

        人设在这里现拼：同一份 `ai/persona.py`，但档位跟着 `selected_mode` 走，
        所以用户从四级切到六级之后，同样的问题会拿到更难一点的例句。
        """
        out = [{"role": "system",
                "content": persona.system_prompt(level=self._level(), style="chat")}]
        recent = self._messages[-MAX_HISTORY:]
        for message in recent:
            role = message.get("role")
            if role not in ("user", "assistant") or not message.get("text"):
                continue
            if role == "assistant" and message.get("state") != "done":
                continue
            out.append({"role": role, "content": message["text"]})
        return out

    def _append(self, message: dict) -> None:
        self._messages.append(message)
        self.messagesChanged.emit()

    def _on_done(self, generation: int, ok: bool, payload: dict) -> None:
        if generation != self._generation:
            return                            # 旧请求的结果，丢弃
        self._busy = False
        self._worker = None
        if payload.get("cancelled"):
            self._messages = [m for m in self._messages
                              if m.get("state") != "pending"]
            self.messagesChanged.emit()
            self._set_status({"code": "cancelled", "message": "已取消本次请求。"})
            self.busyChanged.emit()
            return
        target = self._messages[-1] if self._messages else None
        if target is None or target.get("role") != "assistant":
            return
        if ok:
            target.update(state="done", text=payload.get("text", ""),
                          elapsed=payload.get("elapsed", 0),
                          model=payload.get("model", ""),
                          truncated=payload.get("truncated", False))
            self._set_status({})
            if (payload.get("text") or "").strip():
                self.askSucceeded.emit()
        else:
            target.update(state="error", code=payload.get("code", "unexpected"),
                          error=payload.get("message", "请求失败。"),
                          elapsed=payload.get("elapsed", 0))
            self._set_status({"code": payload.get("code", "unexpected"),
                              "message": payload.get("message", "请求失败。")})
        self.messagesChanged.emit()
        self.busyChanged.emit()

    def _set_status(self, status: dict) -> None:
        self._status = dict(status)
        self.statusChanged.emit()


def _now() -> str:
    return time.strftime("%H:%M")
