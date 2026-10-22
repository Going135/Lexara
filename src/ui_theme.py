# -*- coding: utf-8 -*-
"""启动台主题令牌表 + 热重载存储（外部调参入口）。

为什么单独做一份，而不是继续在 `Main.qml` 里写 `readonly property string ink`：

- 调色是**设计动作**，不该每次都改源码 + 重启进程。这里把 QML 里所有会变的
  颜色/尺寸抽成一张扁平令牌表，落在 `theme.json` 里，外部工具（命令行、
  浏览器调参页、脚本、别的 AI）改文件即可，启动器监听到写入后 100~200ms 内
  重绘，不用重启。
- 令牌表同时是**唯一真源**：QML 只读令牌，Python 画笔（罐子展示区、学习
  日志点阵）也只读令牌。以前同一颗「墨绿」在两个文件里各写一遍，改一处忘
  另一处，是这套 UI 反复出问题的地方。

三条设计约束
------------
1. **缺省即安全**：文件缺失/写坏/键名拼错，一律退回内置默认值并在 `problems`
   里报出来，绝不让启动台因为主题文件挂了打不开。
2. **允许继承**：值可以写成 `"@base.accent"`，表示「跟随另一个令牌」。这样
   改强调色时按钮默认也跟着走，但单独覆盖 `btn.primaryBg` 又能只改按钮。
   解析是逐键递归的，最多 8 层，成环/指向不存在的键就地退回该键默认值。
3. **原子写**：`主题.json.tmp` + `os.replace`，和 `settings_store` 同一条
   路子 —— 启动器正在监听这个文件，半截写入会读到半个 JSON。

键名用点分两层（`组.名字`），JSON 文件里按组嵌套（人读者友好），内部扁平化
（QML 里 `theme.v["btn.primaryBg"]` 一句话取到）。查看所有键：

    python tools/theme_tool.py list
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, Signal

#: 主题文件环境变量覆盖（换整套皮肤 / 做 A/B 对比时用）。
ENV_THEME = "LEXARA_THEME"
APP_NAME = "Lexara"

_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_REF_RE = re.compile(r"^@([A-Za-z0-9_.]+)$")

# ---------------------------------------------------------------------------
# 令牌表
# ---------------------------------------------------------------------------
# 每个令牌：key / kind / default / label / desc（+ 数值型的 ui 范围）
#   kind: "color"（#RGB/#RRGGBB/#AARRGGBB 或 @引用）、"number"（浮点）、
#         "int"（整数像素/层数）
#   ui:   给浏览器调参页用的滑杆范围，命令行不吃这个值
# 顺序 = 调参页与 `--list` 的展示顺序，也是「从上到下就是界面从上到下」的
# 直觉顺序：底色 → 外壳 → 展示区 → 投影 → 按钮 → 热力图。

GROUPS: Tuple[Tuple[str, str, Tuple[dict, ...]], ...] = (
    ("base", "基础色", (
        {"key": "base.ink", "kind": "color", "default": "#1F1F1F",
         "label": "主文字", "desc": "最深的文字色：标题、数字、侧栏大项"},
        {"key": "base.text", "kind": "color", "default": "#2B2B2B",
         "label": "正文", "desc": "正文与次级按钮文字"},
        {"key": "base.muted", "kind": "color", "default": "#747474",
         "label": "次要文字", "desc": "说明、单位、状态行"},
        {"key": "base.subtle", "kind": "color", "default": "#9A9A96",
         "label": "禁用文字", "desc": "按钮不可用时的文字"},
        {"key": "base.line", "kind": "color", "default": "#E7E6E0",
         "label": "描边", "desc": "卡片/按钮的 1px 边框与分隔线"},
        {"key": "base.card", "kind": "color", "default": "#FFFDF6",
         "label": "卡片底", "desc": "象牙白：主卡片、Logo 白卡、次级按钮常态底"},
        {"key": "base.panel", "kind": "color", "default": "#FBFBF9",
         "label": "条目底", "desc": "设置/复习面板里的小条目、统计块底色"},
        {"key": "base.panelAlt", "kind": "color", "default": "#FCFCFA",
         "label": "条目底（亮）", "desc": "比条目底再白一档，用于并排的次级条目"},
        {"key": "base.hover", "kind": "color", "default": "#F1F0EA",
         "label": "悬停底", "desc": "按钮/条目鼠标悬停时的背景"},
        {"key": "base.white", "kind": "color", "default": "#FFFFFF",
         "label": "纯白", "desc": "开关滑块、主按钮文字、深色底上的字"},
        {"key": "base.accent", "kind": "color", "default": "#2F6BFF",
         "label": "强调色", "desc": "选中、焦点、进度、勾选"},
        {"key": "base.accentSoft", "kind": "color", "default": "#EEF3FF",
         "label": "强调浅底", "desc": "选中项的浅色背景"},
        {"key": "base.success", "kind": "color", "default": "#4F765F",
         "label": "成功", "desc": "连接测试通过、已就绪"},
        {"key": "base.warn", "kind": "color", "default": "#7A5C22",
         "label": "警示文字", "desc": "未配置 API 等需要被看见的提示"},
        {"key": "base.warnSoft", "kind": "color", "default": "#FBF6EA",
         "label": "警示底", "desc": "警示条背景"},
        {"key": "base.warnLine", "kind": "color", "default": "#E8DCC2",
         "label": "警示描边", "desc": "警示条边框"},
        {"key": "base.warnChip", "kind": "color", "default": "#E0CFA8",
         "label": "警示胶囊边", "desc": "警告态胶囊按钮的边框"},
        {"key": "base.danger", "kind": "color", "default": "#A3524C",
         "label": "危险", "desc": "删除、重置等破坏性操作"},
        {"key": "base.dangerSoft", "kind": "color", "default": "#FBF3EE",
         "label": "危险底", "desc": "破坏性统计块/提示条背景"},
        {"key": "base.dangerLine", "kind": "color", "default": "#E3C9C7",
         "label": "危险描边", "desc": "危险按钮与提示的边框"},
        {"key": "base.onDark", "kind": "color", "default": "#F7F3E6",
         "label": "深底文字", "desc": "压在墨绿外壳上的标题（象牙白）"},
        {"key": "base.onDarkMuted", "kind": "color", "default": "#B9C7BC",
         "label": "深底次文字", "desc": "压在墨绿上的状态文字/窗口按钮"},
        {"key": "base.scrim", "kind": "color", "default": "#1A1A1455",
         "label": "模态遮罩", "desc": "成就弹窗后面压暗整屏的那层（#AARRGGBB）"},
        {"key": "base.scrimSoft", "kind": "color", "default": "#1A1A1422",
         "label": "轻遮罩", "desc": "换皮肤/设置面板后面那层很淡的压暗"},
    )),

    ("shell", "外壳与渐变", (
        {"key": "shell.top", "kind": "color", "default": "#1D3D31",
         "label": "渐变顶", "desc": "窗口最上沿的墨绿"},
        {"key": "shell.upper", "kind": "color", "default": "#24473A",
         "label": "渐变上段", "desc": "标题带下沿"},
        {"key": "shell.mid", "kind": "color", "default": "#61795F",
         "label": "渐变中段", "desc": "过渡带；这一段最容易和深色文字打架"},
        {"key": "shell.low", "kind": "color", "default": "#D9D3BF",
         "label": "渐变下段", "desc": "接近象牙白前的米灰"},
        {"key": "shell.bottom", "kind": "color", "default": "#FBF7EA",
         "label": "渐变底", "desc": "下半屏的象牙白"},
        {"key": "shell.stop1", "kind": "number", "default": 0.15,
         "label": "停靠点 2", "desc": "渐变上段位置（0~1）",
         "ui": {"min": 0.0, "max": 1.0, "step": 0.01}},
        {"key": "shell.stop2", "kind": "number", "default": 0.26,
         "label": "停靠点 3", "desc": "过渡带开始位置",
         "ui": {"min": 0.0, "max": 1.0, "step": 0.01}},
        {"key": "shell.stop3", "kind": "number", "default": 0.34,
         "label": "停靠点 4", "desc": "准象牙白位置",
         "ui": {"min": 0.0, "max": 1.0, "step": 0.01}},
        {"key": "shell.stop4", "kind": "number", "default": 0.42,
         "label": "停靠点 5", "desc": "完全落到象牙白的位置；再往前提会撞到深色导航文字",
         "ui": {"min": 0.0, "max": 1.0, "step": 0.01}},
        {"key": "shell.radius", "kind": "int", "default": 14,
         "label": "外壳圆角", "desc": "整窗圆角（像素）",
         "ui": {"min": 0, "max": 32, "step": 1}},
        {"key": "hero.top", "kind": "color", "default": "#F6F2E4",
         "label": "展示区卡顶", "desc": "主卡片渐变顶端"},
        {"key": "hero.bottom", "kind": "color", "default": "#FDFBF2",
         "label": "展示区卡底", "desc": "主卡片渐变底端"},
        {"key": "hero.radius", "kind": "int", "default": 14,
         "label": "主卡片圆角", "desc": "展示区外层圆角（像素）",
         "ui": {"min": 0, "max": 36, "step": 1}},
        {"key": "stage.holeRadiusRatio", "kind": "number", "default": 0.08,
         "label": "镂空圆角比例", "desc": "洞的圆角 = 高度 × 这个比例（有上限）",
         "ui": {"min": 0.0, "max": 0.3, "step": 0.01}},
        {"key": "stage.holeRadiusMax", "kind": "int", "default": 18,
         "label": "镂空圆角上限", "desc": "上一条算出来的圆角不会超过这个像素值",
         "ui": {"min": 0, "max": 48, "step": 1}},
        {"key": "stage.overlayAlpha", "kind": "int", "default": 128,
         "label": "展示区白纱", "desc": "挖透的洞里盖的那层白，0=全透 255=全白",
         "ui": {"min": 0, "max": 255, "step": 1}},
        {"key": "stage.border", "kind": "color", "default": "#AAE2E1DA",
         "label": "展示区描边", "desc": "白纱圆角边框（#AARRGGBB）"},
    )),

    ("shadow", "窗口投影", (
        {"key": "shadow.margin", "kind": "int", "default": 28,
         "label": "投影边距", "desc": "卡片四周留出的透明宽度；0=不要投影",
         "ui": {"min": 0, "max": 60, "step": 1}},
        {"key": "shadow.steps", "kind": "int", "default": 18,
         "label": "叠加层数", "desc": "层数越多越平滑，代价是重绘更慢",
         "ui": {"min": 1, "max": 40, "step": 1}},
        {"key": "shadow.color", "kind": "color", "default": "#0C1E16",
         "label": "投影颜色", "desc": "建议带一点底色（墨绿），纯黑会发脏"},
        {"key": "shadow.strength", "kind": "number", "default": 0.045,
         "label": "投影浓度", "desc": "每层基础不透明度；调大更厚重",
         "ui": {"min": 0.0, "max": 0.2, "step": 0.005}},
        {"key": "shadow.power", "kind": "number", "default": 1.35,
         "label": "衰减曲线", "desc": "越大边缘越淡、越贴边越集中",
         "ui": {"min": 0.5, "max": 3.0, "step": 0.05}},
        {"key": "shadow.offsetY", "kind": "number", "default": 7.0,
         "label": "纵向下沉", "desc": "阴影整体下移的像素，正数像有顶光",
         "ui": {"min": -20.0, "max": 30.0, "step": 1}},
        {"key": "shadow.radius", "kind": "int", "default": 14,
         "label": "投影圆角", "desc": "跟外壳圆角保持一致才不露边",
         "ui": {"min": 0, "max": 36, "step": 1}},
    )),

    ("btn", "按钮", (
        {"key": "btn.winFg", "kind": "color", "default": "@base.onDarkMuted",
         "label": "窗口钮·文字", "desc": "最小化/最大化/关闭的常态字色"},
        {"key": "btn.winHoverBg", "kind": "color", "default": "#33FFFFFF",
         "label": "窗口钮·悬停底", "desc": "标题栏三个按钮的悬停背景（半透白）"},
        {"key": "btn.winHoverFg", "kind": "color", "default": "@base.onDark",
         "label": "窗口钮·悬停字", "desc": "悬停时的字色"},
        {"key": "btn.closeHoverBg", "kind": "color", "default": "#4DF3D6D3",
         "label": "关闭钮·悬停底", "desc": "关闭按钮单独一个暖红灰"},
        {"key": "btn.closeHoverFg", "kind": "color", "default": "#FFECE9",
         "label": "关闭钮·悬停字", "desc": "关闭按钮悬停时的字色"},
        {"key": "btn.navHoverBg", "kind": "color", "default": "#E6E4DC",
         "label": "导航项·悬停底", "desc": "侧栏「背单词/收藏夹」悬停底色"},
        {"key": "btn.pillFg", "kind": "color", "default": "@base.muted",
         "label": "胶囊·文字", "desc": "未选中胶囊按钮的字色"},
        {"key": "btn.pillHoverBg", "kind": "color", "default": "@base.hover",
         "label": "胶囊·悬停底", "desc": "未选中胶囊的悬停背景"},
        {"key": "btn.pillActiveBg", "kind": "color", "default": "@base.accentSoft",
         "label": "胶囊·选中底", "desc": "选中态背景"},
        {"key": "btn.pillActiveFg", "kind": "color", "default": "@base.accent",
         "label": "胶囊·选中字", "desc": "选中态文字"},
        {"key": "btn.pillBorder", "kind": "color", "default": "@base.line",
         "label": "胶囊·边框", "desc": "未选中时的描边"},
        {"key": "btn.pillWarnFg", "kind": "color", "default": "#8A6A2B",
         "label": "胶囊·警示字", "desc": "tone=warning 的胶囊文字"},
        {"key": "btn.pillWarnBorder", "kind": "color", "default": "#E0CFA8",
         "label": "胶囊·警示边", "desc": "tone=warning 的胶囊边框"},
        {"key": "btn.primaryBg", "kind": "color", "default": "@base.accent",
         "label": "主按钮·底", "desc": "部署按钮、MiniButton(primary)"},
        {"key": "btn.primaryHoverBg", "kind": "color", "default": "#1F55D6",
         "label": "主按钮·悬停底", "desc": "主按钮悬停"},
        {"key": "btn.primaryDisabledBg", "kind": "color", "default": "#A9C4FF",
         "label": "主按钮·禁用底", "desc": "主按钮不可用"},
        {"key": "btn.primaryFg", "kind": "color", "default": "@base.white",
         "label": "主按钮·文字", "desc": "主按钮上的字"},
        {"key": "btn.darkBg", "kind": "color", "default": "#262624",
         "label": "发送钮·底", "desc": "输入栏发送箭头的深色块"},
        {"key": "btn.darkHoverBg", "kind": "color", "default": "#3A3A38",
         "label": "发送钮·悬停底", "desc": "发送箭头悬停"},
        {"key": "btn.darkDisabledBg", "kind": "color", "default": "#C9C7C0",
         "label": "发送钮·禁用底", "desc": "没内容可发时的灰"},
        {"key": "btn.darkFg", "kind": "color", "default": "@base.white",
         "label": "发送钮·图案", "desc": "箭头图形颜色"},
        {"key": "btn.ghostBg", "kind": "color", "default": "@base.card",
         "label": "次按钮·底", "desc": "MiniButton 常态背景"},
        {"key": "btn.ghostHoverBg", "kind": "color", "default": "@base.hover",
         "label": "次按钮·悬停底", "desc": "MiniButton 悬停"},
        {"key": "btn.ghostFg", "kind": "color", "default": "@base.text",
         "label": "次按钮·文字", "desc": "MiniButton 文字"},
        {"key": "btn.dangerFg", "kind": "color", "default": "@base.danger",
         "label": "危险钮·文字", "desc": "MiniButton(danger)"},
        {"key": "btn.dangerBorder", "kind": "color", "default": "@base.dangerLine",
         "label": "危险钮·边框", "desc": "MiniButton(danger) 描边"},
        {"key": "btn.inputBg", "kind": "color", "default": "@base.white",
         "label": "输入框·底", "desc": "AI 输入栏与设置项底"},
        {"key": "btn.inputBorder", "kind": "color", "default": "@base.line",
         "label": "输入框·边框", "desc": "输入栏描边"},
        {"key": "btn.sliderFill", "kind": "color", "default": "@base.accent",
         "label": "滑杆·已选段", "desc": "设置面板滑杆左侧"},
        {"key": "btn.sliderGroove", "kind": "color", "default": "@base.line",
         "label": "滑杆·轨道", "desc": "滑杆未选段"},
        {"key": "btn.sliderHandle", "kind": "color", "default": "@base.white",
         "label": "滑杆·滑块", "desc": "拖动的圆点"},
        {"key": "btn.switchOn", "kind": "color", "default": "@base.accent",
         "label": "开关·开", "desc": "MiniSwitch 打开时的轨道色"},
        {"key": "btn.switchOff", "kind": "color", "default": "#E0DFD8",
         "label": "开关·关", "desc": "关闭时的轨道色"},
        {"key": "btn.switchKnob", "kind": "color", "default": "@base.white",
         "label": "开关·滑钮", "desc": "开关上的圆点"},
    )),

    ("heat", "学习日志点亮色", (
        {"key": "heat.empty", "kind": "color", "default": "#EEF0EE",
         "label": "无活动", "desc": "当天没有任何学习活动"},
        {"key": "heat.light", "kind": "color", "default": "#B9DCC1",
         "label": "扫描过", "desc": "当天至少完成一次蜘蛛扫描"},
        {"key": "heat.deep", "kind": "color", "default": "#4F765F",
         "label": "复习过", "desc": "当天背过单词或主动问过 AI"},
    )),
)

#: 扁平令牌表：key -> 规格（含 group，方便命令行按组过滤）
SPEC: Dict[str, dict] = {}
for _group, _label, _tokens in GROUPS:
    for _token in _tokens:
        _item = dict(_token)
        _item["group"] = _group
        _item["groupLabel"] = _label
        SPEC[_item["key"]] = _item
del _group, _label, _tokens, _token, _item

DEFAULT_VALUES: Dict[str, Any] = {k: v["default"] for k, v in SPEC.items()}


# ---------------------------------------------------------------------------
# 纯函数层（命令行/测试不依赖 Qt 事件循环，只用这一层）
# ---------------------------------------------------------------------------
def default_path() -> str:
    """主题文件位置：`%APPDATA%/Lexara/theme.json`（与 settings.json 同目录）。

    环境变量 `LEXARA_THEME` 优先 —— 想同时摆两套配色对比、或把主题跟着仓库
    走的时候，指到任意路径即可。
    """
    custom = os.environ.get(ENV_THEME)
    if custom:
        return os.path.abspath(os.path.expanduser(custom))
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".lexara")
    return os.path.join(base, APP_NAME, "theme.json")


def flatten(data: Any, prefix: str = "") -> Dict[str, Any]:
    """嵌套 JSON → 扁平点分键。也接受**本来就是扁平**的写法（`"btn.primaryBg"`）。

    两种写法都认，是因为越早的版本手写过扁平文件，而嵌套对人读更友好；
    没必要为了统一而让人重写一遍。
    """
    out: Dict[str, Any] = {}
    if not isinstance(data, dict):
        return out
    for key, value in data.items():
        if not isinstance(key, str) or key.startswith("_"):
            # `_help` 这类说明键跳过：不是令牌，也不该被当成脏数据报错。
            continue
        name = "%s.%s" % (prefix, key) if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, name))
        else:
            out[name] = value
    return out


def unflatten(values: Dict[str, Any]) -> Dict[str, Any]:
    """扁平点分键 → 按组嵌套；不带点的键留在根上。"""
    out: Dict[str, Any] = {}
    for key in sorted(values):
        node = out
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):       # 键前缀撞车（a=1 又有 a.b）
                break
        else:
            node[parts[-1]] = values[key]
    return out


def _default_of(key: str, depth: int = 0) -> Any:
    """某键的默认**本值**（默认表里可能又是一个 `@` 引用，顺着跟到底）。"""
    value = DEFAULT_VALUES.get(key)
    if isinstance(value, str) and depth < 8:
        match = _REF_RE.match(value.strip())
        if match:
            return _default_of(match.group(1), depth + 1)
    return value


def resolve_refs(values: Dict[str, Any]) -> Dict[str, Any]:
    """把 `"@base.accent"` 这类引用换成本值。

    逐键递归，最多 8 层；成环或指向不存在的键 → 退回该键的默认值（不做静默
    跳过，否则 QML 会拿到 `"@base.accent"` 这种字符串当颜色，界面直接透明）。
    """
    resolved = dict(values)

    def _follow(key: str, depth: int = 0) -> Any:
        value = resolved.get(key, _default_of(key))
        if not isinstance(value, str):
            return value
        match = _REF_RE.match(value.strip())
        if not match:
            return value
        if depth >= 8:
            return _default_of(key)
        target = match.group(1)
        if target not in resolved and target not in DEFAULT_VALUES:
            return _default_of(key)
        return _follow(target, depth + 1)

    for key in list(resolved):
        resolved[key] = _follow(key)
    return resolved


#: 解析后的默认值 —— 比较「用户改了什么」要用它，不能拿带 `@` 的原始表比。
DEFAULT_RESOLVED: Dict[str, Any] = resolve_refs(DEFAULT_VALUES)

#: 预设配色。每套都是「默认值 + 这组覆盖」，所以套用预设 = 一次批量 set，
#: 不会漏掉某个键（漏掉的键会留着上一套的值，那才是最难查的问题）。
#: 换深色/浅色时**必须连文字色一起换**：标题带上的字是浅色，外壳一浅就瞎了。
PRESETS: Dict[str, Tuple[str, Dict[str, Any]]] = {
    "forest": ("墨绿 · 象牙白（默认）", {}),
    "ocean": ("深海蓝 · 雾白", {
        "shell.top": "#12324A",
        "shell.upper": "#16405E",
        "shell.mid": "#4E7A93",
        "shell.low": "#C9D9E0",
        "shell.bottom": "#F3F7F9",
        "hero.top": "#EEF4F8",
        "hero.bottom": "#F9FCFE",
        "base.card": "#F8FBFD",
        "base.accent": "#1F6FB2",
        "base.accentSoft": "#E8F2F9",
        "shadow.color": "#0A1A24",
        "heat.light": "#A9CBE0",
        "heat.deep": "#3F6F8C",
    }),
    "paper": ("象牙纸白 · 无深色带", {
        # 外壳整体是浅的，所以压在深色带上的字要改回墨色，窗口按钮的悬停底
        # 也要从「半透白」换成「半透黑」，否则悬停时白底白字。
        "shell.top": "#EFEDE3",
        "shell.upper": "#F4F2E9",
        "shell.mid": "#F8F6EE",
        "shell.low": "#FBF9F2",
        "shell.bottom": "#FDFBF4",
        "base.onDark": "#2B2B2B",
        "base.onDarkMuted": "#747474",
        "btn.winHoverBg": "#14000000",
        "btn.winHoverFg": "#1F1F1F",
        "btn.closeHoverBg": "#33D9C2BE",
        "btn.closeHoverFg": "#8C3A33",
        "hero.top": "#F7F3E7",
        "hero.bottom": "#FEFCF5",
        "shadow.strength": 0.035,
    }),
    "ink": ("墨黑 · 夜间", {
        "base.ink": "#F2F2F0",
        "base.text": "#DCDCD8",
        "base.muted": "#9C9C98",
        "base.subtle": "#6E6E6A",
        "base.line": "#33383B",
        "base.card": "#1E2225",
        "base.panel": "#23282B",
        "base.panelAlt": "#202528",
        "base.hover": "#2A3033",
        "base.warn": "#D8B87A",
        "base.warnSoft": "#2A2519",
        "base.warnLine": "#4A3F26",
        "base.danger": "#D98C86",
        "base.dangerSoft": "#2B2020",
        "base.dangerLine": "#4A3331",
        "base.scrim": "#66000000",
        "base.scrimSoft": "#33000000",
        "shell.top": "#0E1315",
        "shell.upper": "#121A1D",
        "shell.mid": "#182326",
        "shell.low": "#1C282B",
        "shell.bottom": "#1A2326",
        "hero.top": "#1B2427",
        "hero.bottom": "#1F292C",
        "shadow.color": "#000000",
        "shadow.strength": 0.06,
        "btn.winHoverBg": "#22FFFFFF",
        "btn.navHoverBg": "#2A3033",
        "btn.inputBg": "#262C2F",
        "btn.pillHoverBg": "#2A3033",
        "heat.empty": "#2A3134",
    }),
    "midnight": ("蓝黑 · 夜晚", {
        # 蓝黑版夜间：外壳压成深夜蓝，卡片留在「蓝墨」档，正文用偏冷的雾白。
        # 和 ink 一样必须连文字/悬停/输入框一起覆盖，漏一项就是白底白字。
        "base.ink": "#E8EEF7",
        "base.text": "#D2DAE6",
        "base.muted": "#8F9BAD",
        "base.subtle": "#68727F",
        "base.line": "#2A3B52",
        "base.card": "#16222F",
        "base.panel": "#1B2836",
        "base.panelAlt": "#18242F",
        # ★ 2026-10-22：这一项之前漏了。`accentSoft` 是「选中 / 高亮」的底色，
        # 上面坐的文字是 `base.ink`（夜间已翻成雾白）—— 不覆盖它就变成
        # **白底白字**：背单词卡片的释义框、收藏夹选中项、热力图图例全都读不出来。
        # 取蓝墨档，既能托住雾白文字，也托得住 `base.accent` 的亮蓝。
        "base.accentSoft": "#20304A",
        "base.hover": "#233446",
        "base.warn": "#D8B87A",
        "base.warnSoft": "#2A2517",
        "base.warnLine": "#4A3F26",
        "base.warnChip": "#6A5A34",
        "base.danger": "#D98C86",
        "base.dangerSoft": "#2B1F1E",
        "base.dangerLine": "#4A3331",
        "base.onDark": "#EAF1FA",
        "base.onDarkMuted": "#93A6BE",
        "base.scrim": "#66000000",
        "base.scrimSoft": "#33000000",
        "shell.top": "#0A101C",
        "shell.upper": "#0E1726",
        "shell.mid": "#16233A",
        "shell.low": "#182742",
        "shell.bottom": "#121D31",
        "hero.top": "#141F33",
        "hero.bottom": "#182541",
        "shadow.color": "#02040A",
        "shadow.strength": 0.06,
        "btn.winHoverBg": "#22FFFFFF",
        "btn.navHoverBg": "#1E2D42",
        "btn.pillHoverBg": "#233446",
        "btn.inputBg": "#1E2E44",
        "btn.darkBg": "#24344A",
        "btn.darkDisabledBg": "#3A4A5E",
        "btn.primaryDisabledBg": "#3E5A85",
        "btn.switchOff": "#33455C",
        # 白纱不归零：JarView 的蜘蛛画在透明底板上，全透会和窗口外沿的桌面
        # 直接混在一起；128 的白纱在深蓝外壳上像块白板，压到约十分之一。
        "stage.overlayAlpha": 26,
        "stage.border": "#3A547088",
        "heat.empty": "#1E2C3D",
        "heat.light": "#3E6B96",
        "heat.deep": "#6FA0D2",
    }),
}



def coerce(key: str, raw: Any, strict: bool = False) -> Tuple[Any, Optional[str]]:
    """把一个外部输入转成合法令牌值。

    返回 `(值, 错误说明)`；`strict=False`（读文件）时非法值退回默认值并带回
    说明，`strict=True`（命令行/调参页写入）时原样带回输入让调用方拒绝。

    为什么要限制范围而不是照单全收：`shadow.strength=45`（少写小数点）会让
    窗口四周糊成一块黑板，用户只会看到「启动器坏了」，不会想到是主题文件。
    """
    token = SPEC.get(key)
    if token is None:
        return raw, "未知令牌 %s" % key
    kind = token["kind"]
    if kind == "color":
        if isinstance(raw, str) and _REF_RE.match(raw.strip()):
            target = _REF_RE.match(raw.strip()).group(1)
            if target not in SPEC:
                return (raw, "引用不存在的令牌 @%s" % target) if strict \
                    else (token["default"], "引用不存在的令牌 @%s" % target)
            return raw.strip(), None
        if not isinstance(raw, str) or not _COLOR_RE.match(raw.strip()):
            return (raw, "颜色要写成 #RGB / #RRGGBB / #AARRGGBB，收到 %r" % (raw,)) \
                if strict else (token["default"], "颜色格式不对：%r" % (raw,))
        return raw.strip(), None
    if kind in ("int", "number"):
        try:
            number = float(str(raw).strip())
        except (TypeError, ValueError):
            return (raw, "%s 需要一个数字，收到 %r" % (key, raw)) if strict \
                else (token["default"], "%s 不是数字：%r" % (key, raw))
        ui = token.get("ui") or {}
        low, high = ui.get("min"), ui.get("max")
        if low is not None and high is not None and not (low <= number <= high):
            message = "%s 超出范围 %s~%s（收到 %s）" % (key, low, high, number)
            return (raw, message) if strict else (token["default"], message)
        return (int(round(number)) if kind == "int" else number), None
    return raw, "不认识的令牌类型 %s" % kind


def merge(loaded: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """默认值 + 文件内容 → （已解析引用的）最终值 + 问题清单。"""
    values = dict(DEFAULT_VALUES)
    problems: List[str] = []
    for key, raw in loaded.items():
        if key not in SPEC:
            problems.append("忽略未知键 %s（拼错了？用 --list 查）" % key)
            continue
        value, error = coerce(key, raw, strict=False)
        if error:
            problems.append(error)
        values[key] = value
    return resolve_refs(values), problems


def read_raw(path: Optional[str] = None) -> Tuple[Dict[str, Any], List[str]]:
    """读文件 → **未解析引用**的原始值 + 问题清单。

    写回时必须用这一份：解析过的值里 `@base.accent` 已经变成 `#2F6BFF`，
    再存回去就把「跟随」这件事写死了 —— 以后改强调色，按钮不跟了。
    """
    path = path or default_path()
    if not os.path.exists(path):
        return dict(DEFAULT_VALUES), []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        return dict(DEFAULT_VALUES), ["读取 %s 失败：%s（先用默认配色）" % (path, error)]
    if not isinstance(data, dict):
        return dict(DEFAULT_VALUES), ["%s 顶层应该是一个对象" % path]
    raw = dict(DEFAULT_VALUES)
    raw.update(flatten(data))
    return raw, []


def read_file(path: Optional[str] = None) -> Tuple[Dict[str, Any], List[str]]:
    """读文件 → 最终值（引用已解析）+ 问题清单。文件不存在不是错误（等于全默认）。"""
    path = path or default_path()
    if not os.path.exists(path):
        # 注意要**解析完引用**再返回：`DEFAULT_VALUES` 里存的是 `@base.accent`
        # 这种写法，直接交给 QML 会变成「把字符串当颜色」，面板整片透明。
        return dict(DEFAULT_RESOLVED), []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        return dict(DEFAULT_RESOLVED), ["读取 %s 失败：%s（先用默认配色）" % (path, error)]
    if not isinstance(data, dict):
        return dict(DEFAULT_RESOLVED), ["%s 顶层应该是一个对象" % path]
    return merge(flatten(data))


def read_preset_id(path: Optional[str] = None) -> Optional[str]:
    """读主题文件里的 `_preset` 元数据（设置面板的高亮依据）。

    只认已注册的预设 id；没有、写坏或指向不存在的预设都返回 None，
    由调用方自己决定兜底（外部手改 theme.json 的人不该被假装成某个预设）。
    """
    path = path or default_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("_preset")
    return value if isinstance(value, str) and value in PRESETS else None


def apply_preset_to_raw(raw: Dict[str, Any], preset: str) -> Dict[str, Any]:
    """把预设盖到一份原始令牌表上：先回默认再套覆盖，不留旧预设的残色。"""
    overrides = PRESETS[preset][1]
    values = dict(DEFAULT_VALUES)
    values.update(overrides)
    for key, value in raw.items():
        if key.startswith("_") and key not in SPEC:
            values[key] = value       # 元数据（_preset 等）原样带走
    values["_preset"] = preset
    return values


#: 「跟随系统」昼夜映射的两个预设（`theme_tool` 之外的其余预设不参与自动切换）。
DAY_PRESET = "forest"
NIGHT_PRESET = "midnight"


def system_preset() -> str:
    """现在该摆哪套：Windows 浅色 → 白天、深色 → 夜晚。

    读 `Apps\\Settings` 的 `AppsUseLightTheme`（注册表不可读/键缺失时按本地
    时间近似，7:00~19:00 算白天）—— 自动模式总得给个结果，不许返回 None
    让调用方各自兜底，那才是三处三个口径。
    """
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return DAY_PRESET if int(value) else NIGHT_PRESET
    except Exception:                   # noqa: BLE001 —— 非 Windows/精简系统/键被删
        import time
        return DAY_PRESET if 7 <= time.localtime().tm_hour < 19 else NIGHT_PRESET


def write_file(path: Optional[str], values: Dict[str, Any], header: Optional[str] = None) -> str:
    """原子写。只写令牌（引用原样保留），外加一段 `_help` 说明。

    `values` 里下划线开头的键（如 `_preset`）当作元数据原样带走 —— 设置面板
    靠它记住「用户选的是哪套预设」，读文件时 `flatten` 会跳过这类键，
    不会污染令牌表。
    """
    path = path or default_path()
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload: Dict[str, Any] = {
        "_help": header or "LEXARA 启动台主题。改完保存即可，运行中的启动器会自动重载。"
                          "键的说明见 python tools/theme_tool.py list",
    }
    for key, value in values.items():
        if key.startswith("_") and key not in SPEC:
            payload[key] = value
    payload.update(unflatten({k: v for k, v in values.items() if k in SPEC}))
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(temp, path)
    return path


def ensure_file(path: Optional[str] = None) -> str:
    """文件不存在就落一份默认值 —— 用户得有个能改的东西。"""
    path = path or default_path()
    if not os.path.exists(path):
        write_file(path, dict(DEFAULT_VALUES))
    return path


def diff(values: Dict[str, Any], base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """返回「和默认值不一样」的键（命令行 `diff` 与调参页高亮用）。"""
    base = base if base is not None else DEFAULT_RESOLVED
    return {k: v for k, v in values.items() if base.get(k) != v}


# ---------------------------------------------------------------------------
# Qt 侧：给 QML 的只读映射 + 文件监听
# ---------------------------------------------------------------------------
_ACTIVE: Optional["ThemeStore"] = None


class ThemeStore(QObject):
    """把主题值暴露给 QML，并在文件变化时自动重载。

    QML 取值的唯一姿势是 `theme.v["btn.primaryBg"]`：`v` 是一个带
    `notify` 的 `QVariantMap` 属性，重载时**整个换掉**并 emit 一次，所有绑定
    因为依赖 `v` 而自动重算 —— 不需要为每个令牌写一个 Property，也不会出现
    「改了但界面没动」。
    """

    valuesChanged = Signal()
    reloaded = Signal(int)      # 第几次重载（调试/测试用）
    problem = Signal(str)       # 文件写坏了之类，交给启动日志

    def __init__(self, path: Optional[str] = None, watch: bool = True, parent=None):
        super().__init__(parent)
        self._path = path or default_path()
        self._values: Dict[str, Any] = dict(DEFAULT_VALUES)
        #: 未解析引用的原始值（写回用；`_values` 是给 QML 的成品）
        self._raw: Dict[str, Any] = dict(DEFAULT_VALUES)
        self._problems: List[str] = []
        self._reloads = 0
        self._signature = None
        self._watcher: Optional[QFileSystemWatcher] = None
        self._debounce: Optional[QTimer] = None
        ensure_file(self._path)
        self._load(initial=True)
        if watch:
            self._install_watch()

    # ---- 对外属性 -------------------------------------------------------
    @Property("QVariantMap", notify=valuesChanged)
    def v(self) -> Dict[str, Any]:
        return dict(self._values)

    @Property(str, constant=True)
    def path(self) -> str:
        return self._path

    @Property(int, notify=reloaded)
    def reloads(self) -> int:
        return self._reloads

    # ---- 读写 -----------------------------------------------------------
    def _load(self, initial: bool = False) -> bool:
        try:
            signature = (os.path.getmtime(self._path), os.path.getsize(self._path))
        except OSError:
            signature = None
        if not initial and signature is not None and signature == self._signature:
            return False                    # 目录事件但内容没动，别白折腾 QML
        self._signature = signature
        values, problems = read_file(self._path)
        self._values = values
        self._raw, _ = read_raw(self._path)
        # `flatten` 会跳下划线键，所以 `_preset` 元数据要单独接住带进 `_raw`：
        # 之后任何一次 `save()`（含外部调参的热重载回写）都不该把它洗掉。
        preset = read_preset_id(self._path)
        if preset:
            self._raw["_preset"] = preset
        self._problems = problems
        for message in problems:
            self.problem.emit(message)
        if not initial:
            self._reloads += 1
            self.reloaded.emit(self._reloads)
        self.valuesChanged.emit()
        return True

    def reload(self) -> None:
        self._load()
        self._rewatch()

    def save(self) -> None:
        write_file(self._path, self._raw)
        try:
            self._signature = (os.path.getmtime(self._path), os.path.getsize(self._path))
        except OSError:
            self._signature = None

    def set_values(self, patch: Dict[str, Any], strict: bool = False) -> List[str]:
        """批量改值。返回问题清单（空 = 全成功）。strict 下非法值不写入。"""
        errors: List[str] = []
        raw = dict(self._raw)
        for key, raw_value in patch.items():
            value, error = coerce(key, raw_value, strict=strict)
            if error:
                errors.append(error)
                if strict:
                    continue
            raw[key] = value
        self._raw = raw
        self._values = resolve_refs(raw)
        if not errors or not strict:
            self.save()
        self.valuesChanged.emit()
        return errors

    def reset(self, keys: Optional[List[str]] = None) -> None:
        raw = dict(self._raw)
        if keys is None:
            raw = dict(DEFAULT_VALUES)
        else:
            for key in keys:
                if key in SPEC:
                    raw[key] = SPEC[key]["default"]
        self._raw = raw
        self._values = resolve_refs(raw)
        self.save()
        self.valuesChanged.emit()

    # ---- 预设 -------------------------------------------------------------
    def current_preset(self) -> Optional[str]:
        """主题文件里记录的预设 id（`_preset` 元数据）。"""
        return read_preset_id(self._path)

    def apply_preset(self, preset: str) -> bool:
        """整套切换到某个预设并落盘；QML 绑定和 Python 画笔跟着热重载。

        刻意**先回默认再套覆盖**：预设之间的差集最容易留残色（比如从 ink 切
        回 forest，忘记清 `base.card` 会得到一张深色卡片）。返回 False 表示
        预设 id 不认识，什么都不写。
        """
        if preset not in PRESETS:
            return False
        self._raw = apply_preset_to_raw(self._raw, preset)
        self._values = resolve_refs(self._raw)
        self.save()
        self.valuesChanged.emit()
        return True

    # ---- 监听 -----------------------------------------------------------
    def _install_watch(self) -> None:
        self._watcher = QFileSystemWatcher(self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(140)     # 编辑器保存常常连续写几次
        self._debounce.timeout.connect(self.reload)
        self._watcher.fileChanged.connect(self._on_path_changed)
        self._watcher.directoryChanged.connect(self._on_path_changed)
        self._rewatch()

    def _rewatch(self) -> None:
        """重新挂载监听。

        `os.replace` 会把旧 inode 换掉，文件监听也随之失效（Windows 上表现为
        「只热重载了一次，之后再也不动」）。所以每次重载后都重挂一遍，并且
        **同时监目录** —— 文件被原子替换的瞬间，只有目录事件能拿到通知。
        """
        if self._watcher is None:
            return
        for paths in (self._watcher.files(), self._watcher.directories()):
            if paths:
                self._watcher.removePaths(paths)
        directory = os.path.dirname(os.path.abspath(self._path))
        for target in (self._path, directory):
            if target and os.path.exists(target) and target not in self._watcher.files():
                self._watcher.addPath(target)

    def _on_path_changed(self, _path: str = "") -> None:
        if self._debounce is not None:
            self._debounce.start()


def set_active(store: Optional[ThemeStore]) -> None:
    global _ACTIVE
    _ACTIVE = store


def active_store() -> Optional[ThemeStore]:
    return _ACTIVE


def current() -> Dict[str, Any]:
    """给 Python 画笔用的当前值（没建 store 时就是默认值）。"""
    if _ACTIVE is not None:
        return dict(_ACTIVE._values)         # noqa: SLF001 —— 同模块，取快照
    return dict(DEFAULT_VALUES)


def color(key: str, fallback: str = "#000000"):
    """取一个 QColor；键写错也返回可用的颜色，不让画笔崩掉。"""
    from PySide6.QtGui import QColor

    value = current().get(key, fallback)
    candidate = QColor(str(value))
    return candidate if candidate.isValid() else QColor(fallback)


def stage_overlay():
    """展示区那层「白纱」：纯白 + 可调 alpha（令牌 stage.overlayAlpha）。

    分开写是因为它不是一个纯色令牌 —— 透明度是 0~255 的整数，直接塞进
    `QColor("#...")` 会变成无效色，展示区会退回不透明白板（用户报过的那次）。
    """
    from PySide6.QtGui import QColor

    alpha = int(current().get("stage.overlayAlpha", 128))
    overlay = QColor(255, 255, 255)
    overlay.setAlpha(max(0, min(255, alpha)))
    return overlay
