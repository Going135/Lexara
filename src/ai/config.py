# -*- coding: utf-8 -*-
"""AI 配置：**非密**部分走 settings.json，**密钥**走 Windows DPAPI 加密文件。

为什么分成两处
--------------
任务书 5.2 明确禁止把 API Key 明文写进 `settings.json`、日志、测试快照。
但 Base URL / 模型名本身不算机密，放在 `settings_store.Settings` 里可以让
「启动台 QML → 隐藏 LauncherWindow → ai/cloud_provider.py」三方读到同一份值，
不出现两套互相覆盖的设置。

密钥存放在 `%APPDATA%/Lexara/ai_secret.bin`，内容是 Windows **DPAPI**
（`CryptProtectData`）保护后的密文：

- 加密密钥由 **当前 Windows 用户账户** 派生，同一台机器换个用户登录就解不开；
- 换个工具自己写个 reader 也解不开（不走 DPAPI 拿不到明文）；
- 不需要新增 pip 依赖（ctypes 直接调 `crypt32.dll`），PyInstaller 打包天然兼容。

**DPAPI 不可用时绝不假装加密**：会抛 `SecretStoreError` 并如实告诉调用方，
由 UI 把「无法安全保存」这件事显示出来（任务书：不得假装密钥已加密）。

这里**不缓存**明文密钥到任何模块级变量，读取即解密、用完即丢。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import time
from urllib.parse import urlparse

from wordbook import app_data_dir

SECRET_FILE = "ai_secret.bin"
_MAGIC = b"LEXD1"
_SYSTEM_AVAILABLE = os.name == "nt"

#: 请求 endpoint 的后缀。用户既可以填 Base URL（`https://api.openai.com/v1`），
#: 也可以直接填完整 URL（`https://api.openai.com/v1/chat/completions`）——
#: 现有的 `cloud_provider.py` 默认值就是后者，必须向后兼容。
_CHAT_SUFFIX = "/chat/completions"


class AIConfigError(Exception):
    """配置 / 密钥操作失败。``code`` 用于 UI 显示可执行的下一步。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.user_message = message


# ---------------------------------------------------------------- DPAPI
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt_protect(raw: bytes) -> bytes:
    source = ctypes.create_string_buffer(raw, len(raw))
    inbound = _Blob(len(raw), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
    outbound = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(inbound), "LEXARA_AI_API_KEY", None, None, None, 0,
        ctypes.byref(outbound))
    if not ok:
        raise AIConfigError("dpapi", "Windows 数据保护接口加密失败（错误码 %d）"
                            % ctypes.get_last_error())
    try:
        return ctypes.string_at(outbound.pbData, outbound.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outbound.pbData)


def _crypt_unprotect(blob: bytes) -> bytes:
    source = ctypes.create_string_buffer(blob, len(blob))
    inbound = _Blob(len(blob), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
    outbound = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(inbound), None, None, None, None, 0, ctypes.byref(outbound))
    if not ok:
        raise AIConfigError("dpapi", "密钥解密失败：这台机器或这个 Windows "
                                     "账户下无法解开（错误码 %d）。请重新填写密钥。"
                            % ctypes.get_last_error())
    try:
        return ctypes.string_at(outbound.pbData, outbound.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outbound.pbData)


class SecretStore:
    """单个 API Key 的加密落盘读写。"""

    def __init__(self, directory: str | None = None):
        self.directory = directory or app_data_dir()
        self.path = os.path.join(self.directory, SECRET_FILE)

    @property
    def available(self) -> bool:
        return _SYSTEM_AVAILABLE

    def has_secret(self) -> bool:
        return os.path.isfile(self.path) and os.path.getsize(self.path) > len(_MAGIC)

    def read(self) -> str:
        if not self.has_secret():
            return ""
        with open(self.path, "rb") as handle:
            raw = handle.read()
        if not raw.startswith(_MAGIC):
            raise AIConfigError("format", "密钥文件格式不正确，请重新填写并保存。")
        plain = _crypt_unprotect(raw[len(_MAGIC):])
        try:
            return plain.decode("utf-8")
        except UnicodeDecodeError:
            raise AIConfigError("format", "密钥文件内容损坏，请重新填写并保存。")

    def write(self, secret: str) -> None:
        if not _SYSTEM_AVAILABLE:
            raise AIConfigError("dpapi",
                                "当前系统不支持 Windows 加密存储，为保证安全"
                                "未保存密钥。请改用环境变量 LEXARA_AI_API_KEY。")
        if not secret:
            self.clear()
            return
        blob = _MAGIC + _crypt_protect(secret.encode("utf-8"))
        tmp = self.path + ".tmp"
        os.makedirs(self.directory, exist_ok=True)
        with open(tmp, "wb") as handle:
            handle.write(blob)
        os.replace(tmp, self.path)

    def clear(self) -> bool:
        existed = self.has_secret()
        for path in (self.path, self.path + ".tmp"):
            try:
                os.remove(path)
            except OSError:
                pass
        return existed


# ---------------------------------------------------------------- URL 校验
_LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}


def validate_endpoint(url: str) -> tuple[str, str]:
    """校验用户填的地址，返回 ``(normalized_url, resolved_endpoint)``。

    - 公网地址必须是 HTTPS（任务书 5.2：不要对任意公网 HTTP 端点发密钥）；
    - 只有 loopback（localhost / 127.0.0.1 / ::1）允许明文 HTTP，用于本机模型。
    """
    text = (url or "").strip()
    if not text:
        raise AIConfigError("invalid_url", "请填写 Base URL，例如 https://api.openai.com/v1")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        raise AIConfigError("invalid_url", "地址必须以 https:// 开头（本机模型可用 http://localhost）。")
    host = (parsed.hostname or "").lower()
    if not host:
        raise AIConfigError("invalid_url", "地址里缺少主机名。")
    if parsed.scheme == "http" and host not in _LOOPBACK:
        raise AIConfigError("insecure_url",
                            "为安全起见，只有 localhost / 127.0.0.1 允许 http；"
                            "公网地址请改用 https。")
    normalized = "%s://%s" % (parsed.scheme, parsed.netloc) + (
        parsed.path.rstrip("/") if parsed.path not in ("", "/") else "")
    return normalized, resolve_endpoint(normalized)


def resolve_endpoint(url: str) -> str:
    """把用户填的地址补成真正的 chat-completions 请求地址。

    ``.../chat/completions`` 结尾（含旧环境变量默认值）原样使用；
    否则当作 Base URL，补上后缀。
    """
    text = (url or "").strip().rstrip("/")
    if not text:
        return ""
    return text if text.lower().endswith(_CHAT_SUFFIX) else text + _CHAT_SUFFIX


# ---------------------------------------------------------------- 配置门面
class AIConfig:
    """唯一的 AI 配置入口。QML / 控制器 / provider 都读它。

    优先级：**UI 已保存的配置 > 环境变量**。环境变量保留给 CI 和不用 UI 的
    用户（既有 `LEXARA_AI_API_KEY` / `LEXARA_AI_URL` / `LEXARA_AI_MODEL` 行为不变）。
    """

    def __init__(self, settings, secrets: SecretStore | None = None):
        self.settings = settings
        self.secrets = secrets or SecretStore()
        self._last_test: dict = {}

    # ---- 读
    def api_key(self) -> str:
        try:
            stored = self.secrets.read()
        except AIConfigError:
            # 解不开就当作没配：宁可让用户重填，也不要把异常抛到 UI 上崩掉。
            stored = ""
        if stored:
            return stored
        return os.environ.get("LEXARA_AI_API_KEY", "").strip()

    def base_url(self) -> str:
        value = str(self.settings.get("ai_base_url", "") or "").strip()
        return value or os.environ.get("LEXARA_AI_URL", "").strip()

    def model(self) -> str:
        value = str(self.settings.get("ai_model", "") or "").strip()
        return value or os.environ.get("LEXARA_AI_MODEL", "").strip()

    def endpoint(self) -> str:
        return resolve_endpoint(self.base_url() or
                                os.environ.get("LEXARA_AI_URL", "").strip())

    def source_of_key(self) -> str:
        try:
            if self.secrets.read():
                return "store"
        except AIConfigError:
            return "broken"
        return "env" if os.environ.get("LEXARA_AI_API_KEY", "").strip() else "none"

    def configured(self) -> bool:
        return bool(self.api_key() and self.base_url())

    def masked_key(self) -> str:
        key = self.api_key()
        if not key:
            return ""
        tail = key[-4:] if len(key) > 4 else ""
        return ("●" * max(0, len(key) - 4)) + tail

    def key_source_label(self) -> str:
        return {"store": "本机加密存储", "env": "环境变量",
                "broken": "密钥无法解密", "none": "未配置"}.get(
                    self.source_of_key(), "未配置")

    # ---- 写
    def update(self, base_url: str, model: str, api_key: str | None) -> dict:
        """保存配置。``api_key`` 为空表示**不改动**已存的密钥。"""
        normalized, endpoint = validate_endpoint(base_url)
        self.settings.set("ai_base_url", normalized)
        self.settings.set("ai_model", (model or "").strip())
        saved_key = False
        if api_key:
            self.secrets.write(api_key.strip())
            saved_key = True
        return {"baseUrl": normalized, "endpoint": endpoint, "model": self.model(),
                "keySaved": saved_key, "configured": self.configured()}

    def clear_key(self) -> dict:
        existed = self.secrets.clear()
        return {"cleared": existed, "configured": self.configured()}

    # ---- 最后一次测试结果的记忆（只存摘要，不存任何密钥/响应体）
    def remember_test(self, ok: bool, message: str, elapsed: float,
                      model: str = "") -> None:
        self._last_test = {"ok": bool(ok), "message": message,
                           "elapsed": round(float(elapsed), 2), "model": model,
                           "at": time.strftime("%H:%M:%S")}

    def last_test(self) -> dict:
        return dict(self._last_test)

    def snapshot(self, include_key: bool = False) -> dict:
        """给 UI 的状态快照。**默认不含密钥**。"""
        data = {
            "baseUrl": self.base_url(),
            "endpoint": self.endpoint(),
            "model": self.model(),
            "configured": self.configured(),
            "hasKey": bool(self.api_key()),
            "keyHint": self.masked_key(),
            "keySource": self.source_of_key(),
            "keySourceLabel": self.key_source_label(),
            "lastTest": self.last_test(),
        }
        if include_key:
            data["key"] = self.api_key()
        return data


def mask(text: str) -> str:
    """把任意可能含密钥的文本里的 key 抹掉（写日志 / 抛异常前用）。"""
    key = (text or "").strip()
    if len(key) <= 4:
        return "***"
    return key[:2] + "***" + key[-2:]
