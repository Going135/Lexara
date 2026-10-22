# -*- coding: utf-8 -*-
"""启动台的设置存储（JSON，落在 %APPDATA%/Lexara/settings.json）。

为什么是 JSON 而不是 SQLite：本项目已经有一个同样位置的同款存储
（`wordbook.py` 的 `wordbook.json`，原子写 `.tmp` + `os.replace`），
沿用同一套做法比重引一个 SQLite 文件更省，也不改词典那三个只读连接。

键名和 `ui-preview/启动台.html` 里 `localStorage["eightlegs.launcher"]` 一一对应，
真机与原型可以互相核对：

    selected_mode / ocr_engine / max_words / min_conf /
    pet_scale / always_on_top / show_meaning_card

其中两项在源程序里**原本没有对应的落盘**，是这次移植新增的：
`min_conf`（OCR 行置信度下限）、`show_meaning_card`（识别完要不要弹释义卡）。
其余都能接到既有的真实开关上：
`selected_mode`→`pet.capture_mode`、`max_words`→`pet.capture_limit`、
`pet_scale`→`pet.set_scale()`、`always_on_top`→`pet.on_top`。

`skin`（蜘蛛皮肤）是**启动台与桌宠共用**的一项：启动台改它要立刻反映到
罐子里的预览和已部署的桌宠，桌宠右键改它也要回写，两边都读这一个键。

读到不认识的值一律退回默认（宁可少读，不要让一个脏字段把启动台卡死）。
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Callable, Dict

#: 项目 2026-10-16 正式改名：词蛛LEXARA（旧名 EightLegsGlow）。
APP_NAME = "Lexara"
APP_DISPLAY_NAME = "词蛛LEXARA"
#: 旧数据目录名 —— 只用于**一次性迁移**（见 `migrate_app_dir`）。
LEGACY_APP_DIR_NAME = "EightLegsGlow"


def migrate_app_dir() -> None:
    """把旧目录 `%APPDATA%/EightLegsGlow` 的数据搬到 `%APPDATA%/Lexara`。

    只在新目录**不存在**而旧目录存在时执行一次（复制，不删旧的 ——
    万一要回滚旧版 exe，词库和设置还在原位）。幂等：目录已在新就直接返回。
    """
    base = os.environ.get("APPDATA")
    if not base:
        return
    new = os.path.join(base, APP_NAME)
    old = os.path.join(base, LEGACY_APP_DIR_NAME)
    if os.path.isdir(new) or not os.path.isdir(old):
        return
    try:
        shutil.copytree(old, new)
        print("[migrate] 数据目录 %s -> %s" % (old, new))
    except OSError as exc:                       # noqa: BLE001
        print("[migrate] 数据目录迁移失败（不影响启动）：%s" % exc)

#: 默认值**逐项对齐原型** `ui-preview/启动台.html` 的 `DEFAULTS`
#: （`selected_mode:"cet4"`）。
#: ★ `min_conf` 刻意**不对齐**原型的 0.80（2026-10-17）：RapidOCR 对英文短词、
#:   斜体/浅灰/彩色混排普遍只给 0.68~0.85，0.8 的默认阈值实测能把一半以上的
#:   真词整行砍掉（用户截图：五行被砍四行）。默认降到 0.6 —— 纯噪声行的
#:   分数通常在 0.5 以下，仍然挡得住；想收紧的用户可以自己拖滑杆。
#: 这里刻意不跟 `PetWindow.__init__` 里的 `capture_mode="cet6"` 走：
#: 启动台是用户看到的第一屏，默认高亮哪一档是**设计决定**，
#: 而 `PetWindow` 那一行只是「没有启动台时」的兜底初值。
#: 两边不一致没关系，因为部署时 `apply_settings()` 一定把这里的值覆盖上去。
DEFAULTS: Dict[str, Any] = {
    "selected_mode": "cet4",
    "ocr_engine": "rapid",
    # ★ 「最大识词」从 1~8 提到 1~48（任务书 §6，2026-10-18）；
    #   2026-10-19 再收成四档 `MAX_WORDS_CHOICES = (8, 16, 32, 48)`。
    #   这个数字以前等于「八条腿一次能踩几个」，所以顺手也把它当成**丢弃阈值** ——
    #   框到 12 个词时第 9 个之后是静默消失的。现在它是「本次最多处理多少个词」，
    #   八条腿只是**同时**踩八个，剩下的排队分批往前踩。
    #   上限 48 和 `OcrWorker.run` 里 `scan_text(limit=48)` 是同一个数：
    #   候选池就这么大，再往上也只是把同一个池子标成「还要更多」。
    #   默认给 8（用户口径 2026-10-19）：八条腿一次正好踩满、一批就走完，
    #   不再排队开第二批。再大结果卡会长得看不完。
    "max_words": 8,
    "min_conf": 0.6,
    "pet_scale": 1.0,
    "always_on_top": True,
    "show_meaning_card": True,
    #: 蜘蛛皮肤。用户口径：**默认白跳蛛**（`skin_manifest.json` 里写的是
    #: original，以用户要求为准）。合法值从 `spider_painter.SKIN_SPECS` 现取，
    #: 所以新增皮肤时这里不用改 —— 但**必须**保持和 `spider_painter.DEFAULT_SKIN`
    #: 一致，否则「启动台还没写入过设置」时会和桌宠首屏不一致。
    "skin": "white_jump_spider",
    #: ---- AI 配置（2026-10-17 新增，任务书第 5 节）------------------------
    #: 只放**非密**字段。API Key 本身走 Windows DPAPI 加密文件
    #: （见 `ai/config.py`），**绝不**落到这里，也不进日志。
    #: 留空表示「未配置」，此时 UI 与 provider 会退回环境变量，再退回禁用。
    "ai_base_url": "",
    "ai_model": "",
    #: ---- 蜘蛛感应（2026-10-18 新增，任务书第 7 节）------------------------
    #: **默认关**：这是一直看屏幕的模式，用户不主动开就绝不自己开
    #: （隐私边界，见 `sense_session.py` 模块注释与任务书 §7.3）。
    "sense_enabled": False,
    #: 扫描频率初值 1 次/秒 —— 任务书明说「每秒约 1~2 次是**待测初始值**，
    #: 不是性能承诺」。下限 0.4、上限 2.0：再高就变成「每帧全屏 OCR」，
    #: 实测单轮 OCR 本身就要 1s+（`tools/sense_bench.py`），高频率只会堆延迟。
    "sense_hz": 1.0,
    #: ---- 启动行为（2026-10-18 新增，任务书 §6）--------------------------
    #: `auto_deploy_on_start`：**应用进程启动后**是否自动播放部署动画让蜘蛛上桌面。
    #: 默认开（用户要「打开就能用」），关掉之后必须尊重 —— 只影响进程启动，
    #: 托盆恢复 / 收回 / 再次显示窗口都不许触发（由 `app_lifecycle` 保证）。
    #: ★ 它与「开机时启动词蛛」是**两个独立设置**：后者是 Windows 启动项，
    #:   真实状态存在系统 Startup 文件夹里（`autostart.py`），这里不存副本。
    "auto_deploy_on_start": True,
    #: ---- 界面主题（2026-10-22 新增）--------------------------------------
    #: 启动台「白天/夜晚」切换选中的 `ui_theme.PRESETS` 预设 id。
    #: **真源是 theme.json 里的 `_preset`**，这里存的是副本 —— 给 Widgets
    #: 老路径和 theme.json 被外部手改时兜底，也保证「恢复默认」能切回 forest。
    "theme_preset": "forest",
    #: 「跟随系统」开关：开 = 按 Windows 深浅色自动在 forest/midnight 间切换，
    #: 此时 `theme_preset` 存的是用户上一次**手动**选的预设（切回手动时还原）。
    "theme_auto": False,
}


def _ai_text(value: Any) -> str:
    """AI 字段只做字符串裁剪，不在这里校验 URL —— URL 校验带有安全语义，
    统一由 `ai/config.py::validate_endpoint` 负责（拒绝公网 HTTP）。"""
    return str(value).strip()

#: 每个键的取值范围/类型。**区间和启动台里的滑杆一格不差**，
#: 否则「滑杆调不出但 JSON 手改能得到」的状态会让两边行为分叉。
def _skin_id(value: Any) -> str:
    """皮肤 ID 白名单校验。惰性导入画笔模块，避免设置层拖进 Qt。"""
    from spider_painter import SKIN_SPECS
    key = str(value).strip().lower()
    return key if key in SKIN_SPECS else DEFAULTS["skin"]


def _theme_preset_id(value: Any) -> str:
    """主题预设 ID 白名单校验（同 `_skin_id`，惰性导入避免设置层拖进 Qt）。"""
    from ui_theme import PRESETS
    key = str(value).strip().lower()
    return key if key in PRESETS else DEFAULTS["theme_preset"]


#: 「最大识词」的**可选档位**（2026-10-19 从「连续 1~48 滑杆」改成四档）。
#:
#: 为什么收成档位：滑杆能停在 7 / 23 / 37 这种数上，而实际步进只可能是
#: 「八条腿一批、一批批往上加」，中间值既记不住也没有对应效果。四档
#: 8/16/32/48 正好是「一批 / 两批 / 四批 / 六批」，用户按节奏挑就行。
#:
#: 启动台的两个界面（Widgets 的 `launcher_window` 和 QML 的 `launcher_qml` +
#: `qml/Main.qml`）以及右键菜单的「识词设置」**都从这里取**，免得三处各写
#: 一个数字、改一处漏一处。
MAX_WORDS_CHOICES = (8, 16, 32, 48)
#: 兼容旧调用方：`MAX_WORDS_RANGE` 仍是 (最小值, 最大值) 的形态。
MAX_WORDS_RANGE = (MAX_WORDS_CHOICES[0], MAX_WORDS_CHOICES[-1])


def normalize_max_words(value: Any) -> int:
    """把任意历史值收敛到四档之一。

    老配置里存过 4 / 6 / 12 / 24：直接 clamp 只会把 4 变成 8、把 24 留在 24，
    而 UI 上四个档位一个都不高亮（看起来像「没选中」）。所以统一取**最近档**，
    等距时取大的一档（24 → 32、40 → 48），存下来的值永远能点亮一个档位。
    """
    try:
        want = int(value)
    except (TypeError, ValueError):
        want = DEFAULTS["max_words"]
    return min(MAX_WORDS_CHOICES, key=lambda n: (abs(n - want), -n))

#: 「感应频率」的取值区间（任务书 §7.3：1~2 次/秒是**待测初始值**，不是承诺）。
#: 上限压在 2.0 是实测决定的：本机单轮 ROI OCR 约 0.3~1.4s，
#: 再往上就只会丢帧（`tools/sense_bench.py`）。
#: 启动台那两个界面（`launcher_window` / `launcher_qml` + `qml/Main.qml`）
#: 和 `sense_session` 的兜底初值都从这一处取。
SENSE_HZ_RANGE = (0.4, 2.0)

BOUNDS: Dict[str, Callable[[Any], Any]] = {
    "selected_mode": lambda v: str(v),
    "ocr_engine": lambda v: str(v),
    "max_words": normalize_max_words,
    "min_conf": lambda v: float(min(0.99, max(0.5, float(v)))),  # 原型 0.5~0.99
    "pet_scale": lambda v: float(min(2.0, max(0.6, float(v)))),  # 原型 0.6~2.0
    "always_on_top": bool,
    "show_meaning_card": bool,
    "skin": _skin_id,
    "ai_base_url": _ai_text,
    "ai_model": _ai_text,
    "sense_enabled": bool,
    "sense_hz": lambda v: float(min(SENSE_HZ_RANGE[1],
                                    max(SENSE_HZ_RANGE[0], float(v)))),
    "auto_deploy_on_start": bool,
    "theme_preset": _theme_preset_id,
    "theme_auto": bool,
}


def _coerce(key: str, value: Any, log: Callable[[str], None] | None) -> Any:
    """按 `BOUNDS` 校验单个键；失败就退回默认值并记一笔。"""
    try:
        return BOUNDS[key](value)
    except Exception:                          # noqa: BLE001
        if log is not None:
            log("[settings] %s 的值 %r 不合法，退回默认 %r"
                % (key, value, DEFAULTS[key]))
        return DEFAULTS[key]


class Settings:
    """一个内存 dict + 惰性落盘。改动立刻写文件（原子替换），和 wordbook 一样。"""

    def __init__(self, path: str | None = None,
                 log: Callable[[str], None] | None = None):
        self.log = log or (lambda message: None)
        if path is None:
            from wordbook import app_data_dir
            path = os.path.join(app_data_dir(), "settings.json")
        self.path = path
        self.values: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------ 读写
    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception as error:             # noqa: BLE001
            # 文件坏了不能把程序带崩：记一笔，用默认值继续，下一次 save 会覆盖掉。
            self.log("[settings] 读取失败（%r），用默认值" % (error,))
            return
        if not isinstance(raw, dict):
            return
        # 一次性迁移：旧默认 0.8 是当时写进 settings.json 的（不是用户调的），
        # 新默认 0.6 上线后，存档里恰好等于旧默认的值跟着迁走；
        # 用户真调过的其它值一律不动。
        if raw.get("min_conf") == 0.8:
            raw["min_conf"] = DEFAULTS["min_conf"]
        for key in DEFAULTS:
            if key in raw:
                self.values[key] = _coerce(key, raw[key], self.log)

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.values, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as error:             # noqa: BLE001
            # 写不进去只是下次要重设，不该影响本次运行。
            self.log("[settings] 写入失败: %r" % (error,))

    # ------------------------------------------------ 访问
    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, save: bool = True) -> Any:
        if key not in DEFAULTS:
            self.log("[settings] 忽略未知键 %s" % key)
            return None
        self.values[key] = _coerce(key, value, self.log)
        if save:
            self.save()
        return self.values[key]

    def update(self, mapping: Dict[str, Any]) -> None:
        """批量写入，只落盘一次（滑杆拖动时用它，别每格都写一遍磁盘）。"""
        for key, value in mapping.items():
            self.set(key, value, save=False)
        self.save()

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.values)
