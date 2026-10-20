# -*- coding: utf-8 -*-
"""音效：用 WinMM 的 MCI 播 mp3，不引任何第三方库。

为什么不用 QtMultimedia：这个环境里 PySide6 根本没装 `QtMultimedia` 模块
（`tools/build_exe.bat` 还显式 `--exclude-module PySide6.QtMultimedia`），
而 MCI 是 Windows 自带的，mp3 直接能放，一行依赖都不用加。

## 为什么要后台线程（2026-10-18 卡顿修复）

MCI 的 `play` **不是**异步的。实测这台机器上（`type mpegvideo` 走
DirectShow 滤镜图）：

| 命令 | 实测耗时 |
| --- | --- |
| `open`（冷启动） | 160 ~ 750 ms |
| `play` | **310 ~ 560 ms**（文件总长才 984 ms） |
| `stop` + `seek` | 25 + 60 ms |

这些 `mciSendStringW` 全是**同步阻塞**调用，以前直接写在 QML 槽里（UI 线程），
于是每次点「记住了」界面就冻 0.3~0.6 秒——动画掉帧、按钮按下去没反应，
这就是「卡一下」的真凶。

关键实测（`status position`）：`play` 返回时 position 已经 302 ms，
说明**声音在命令发出约 35 ms 就响了**，剩下的时间纯粹是它在等播放进度。
所以把命令搬到后台线程，延迟听不出来，UI 却一点都不冻。

## 约定（音效是锦上添花，绝不能因为放不出来让背单词点不动）

- `play()` 只把请求塞进邮箱就返回，**永不阻塞调用方**；
- 任何失败都静默（返回 False，不抛异常、不弹窗、不写日志刷屏）；
- 非 Windows 静默返回 False；
- `LEXARA_SFX_MUTE=1` 全局静音（跑测试/批量脚本时用）；
- `LEXARA_SFX` 可以换一个音频文件（调试用）。

## 连点行为

邮箱只有一格、**后来居上**：连点五次只会在播完当前这声后再补一声，
不会排五声长队。后台线程正忙时新请求直接覆盖旧的待办。
"""
from __future__ import annotations

import ctypes
import os
import threading

_ALIAS = "lexara_sfx"

_WINMM = None
_WINMM_TRIED = False


def _winmm():
    """惰性拿 winmm.dll；非 Windows 返回 None（缓存结果，别每次都试）。"""
    global _WINMM, _WINMM_TRIED
    if not _WINMM_TRIED:
        _WINMM_TRIED = True
        try:
            _WINMM = ctypes.windll.winmm if os.name == "nt" else None
        except (AttributeError, OSError):
            _WINMM = None
    return _WINMM


def _send(command: str, size: int = 0) -> tuple[int, str]:
    winmm = _winmm()
    if winmm is None:
        return -1, ""
    buf = ctypes.create_unicode_buffer(max(256, size))
    code = winmm.mciSendStringW(command, buf, len(buf), 0)
    return code, buf.value


def default_path() -> str:
    """音效文件位置：`assets/sfx/ding.mp3`（走 resource_path，兼容 PyInstaller）。"""
    override = os.environ.get("LEXARA_SFX")
    if override:
        return override
    try:
        from wordbook import resource_path
        return resource_path("assets", "sfx", "ding.mp3")
    except Exception:                       # noqa: BLE001
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "assets", "sfx", "ding.mp3")


def muted() -> bool:
    return os.environ.get("LEXARA_SFX_MUTE", "").strip() not in ("", "0", "false", "False")


class _Player:
    """一条后台线程 + 一格邮箱。MCI 的句柄（alias）只在这个线程里碰。"""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._request: tuple[str, str] | None = None
        self._thread: threading.Thread | None = None
        self._opened: str | None = None
        self._busy = False

    # ---- 对外：只是投递 ------------------------------------------------
    def submit(self, kind: str, path: str) -> None:
        with self._cv:
            self._request = (kind, path)          # 后来居上，不排队
            self._cv.notify()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="lexara-sfx", daemon=True)
                self._thread.start()

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """等到没有待办也没有正在播（测试用，UI 里别调——会阻塞）。"""
        with self._cv:
            return self._cv.wait_for(
                lambda: self._request is None and not self._busy, timeout)

    # ---- 内部：真正干活 ------------------------------------------------
    def _run(self) -> None:
        while True:
            with self._cv:
                while self._request is None:
                    self._cv.wait()
                kind, path = self._request
                self._request = None
                self._busy = True
            try:
                self._handle(kind, path)
            except Exception:                 # noqa: BLE001 音效绝不外抛
                pass
            finally:
                with self._cv:
                    self._busy = False
                    self._cv.notify_all()     # 叫醒 wait_idle

    def _handle(self, kind: str, path: str) -> None:
        if self._opened != path:
            if self._opened:
                _send("close %s" % _ALIAS)
                self._opened = None
            # type mpegvideo 是 DirectShow 的 MCI 设备名，mp3 靠它才认
            code, _ = _send('open "%s" type mpegvideo alias %s' % (path, _ALIAS))
            if code != 0:
                return
            self._opened = path
            _send("set %s time format milliseconds" % _ALIAS)
        if kind != "play":
            return                            # "warm"：只把设备打开，不出声
        # 一条 `play ... from 0` 顶掉 stop+seek+play 三条往返，且天然从头重播
        _send("play %s from 0" % _ALIAS)


_PLAYER = _Player()


def play(path: str | None = None) -> bool:
    """播一次。返回「是否已交给后台」（不代表你听见了，也不代表播完了）。"""
    if muted():
        return False
    target = os.path.abspath(path or default_path())
    if _winmm() is None or not os.path.isfile(target):
        return False
    _PLAYER.submit("play", target)
    return True


def prewarm(path: str | None = None) -> bool:
    """启动时先 `open`，把那 160~750 ms 的冷启动开销挪到用户点按钮之前。"""
    if muted():
        return False
    target = os.path.abspath(path or default_path())
    if _winmm() is None or not os.path.isfile(target):
        return False
    _PLAYER.submit("warm", target)
    return True


def play_ding() -> bool:
    """背单词「记住了」的提示音（名字直白，调用处读起来就是意图）。"""
    return play()
