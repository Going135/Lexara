# -*- coding: utf-8 -*-
"""启动台主题的外部调参命令行。

启动器**开着**的时候用，改完立刻生效（ThemeStore 监听 theme.json，约 140ms
后重绘），不用重启、不用改源码：

    python tools/theme_tool.py list                      # 看全部 81 个令牌
    python tools/theme_tool.py list --group btn          # 只看按钮
    python tools/theme_tool.py set base.accent=#E04B3A   # 改强调色
    python tools/theme_tool.py set btn.primaryBg=#E04B3A btn.primaryHoverBg=#C43A2B
    python tools/theme_tool.py get btn.primaryBg
    python tools/theme_tool.py diff                      # 我到底改过什么
    python tools/theme_tool.py preset ink                # 整套换（含文字色）
    python tools/theme_tool.py reset --all               # 回到默认
    python tools/theme_tool.py path                      # theme.json 在哪
    python tools/theme_tool.py watch                     # 盯着文件，打印每次变化

约定
----
* 键名是 `组.名字`（`base.accent` / `btn.primaryBg` / `shadow.margin`），
  和 QML 里 `tv["base.accent"]` 完全一致 —— 看到代码就能猜出键。
* 颜色写 `#RGB` / `#RRGGBB` / `#AARRGGBB`（Qt 的 8 位是 alpha 在前）。
* 值可以写成 `@base.accent`，表示「跟随另一个令牌」。改强调色时按钮默认跟着
  走，但单独覆盖 `btn.primaryBg` 又能只改按钮。
* `set` 是**先全量校验再落盘**：一条不合法就一条都不写，不会留下半个状态。

这个脚本**不需要 Qt 事件循环**（只 import 纯函数层），所以能在任何终端里跑，
也不会因为启动器没开而失败 —— 写文件本来就是启动器不在时也该能做的事。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import ui_theme                                              # noqa: E402

# ANSI：只在真终端里上色，重定向到文件时不掺转义符
_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_DIM = "\033[2m" if _COLOR else ""
_BOLD = "\033[1m" if _COLOR else ""
_RESET = "\033[0m" if _COLOR else ""
_RED = "\033[31m" if _COLOR else ""
_GREEN = "\033[32m" if _COLOR else ""
_YELLOW = "\033[33m" if _COLOR else ""


# --------------------------------------------------------------------- 小工具
def _swatch(color: str) -> str:
    """真色块（终端支持 24bit 时）。半透明色不画色块 —— 画出来会骗人。"""
    if not _COLOR:
        return ""
    text = str(color).lstrip("#")
    if len(text) == 8:                   # #AARRGGBB：透明度不是 255，画色块会误导
        return "   "
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return "   "
    try:
        red, green, blue = (int(text[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return "   "
    return "\033[48;2;%d;%d;%dm   %s" % (red, green, blue, _RESET)


def _describe(token: dict) -> str:
    return "%s（%s）" % (token["label"], token["desc"])


def _print_problems(problems) -> None:
    for message in problems:
        print("%s! %s%s" % (_YELLOW, message, _RESET))


def _load_raw(path: str):
    raw, problems = ui_theme.read_raw(path)
    _print_problems(problems)
    return raw


def _resolve(raw):
    return ui_theme.resolve_refs(raw)


# --------------------------------------------------------------------- 命令
def cmd_list(args, path: str) -> int:
    raw = _load_raw(path)
    values = _resolve(raw)
    changed = ui_theme.diff(values)
    rows = []
    for key, token in ui_theme.SPEC.items():
        if args.group and token["group"] != args.group:
            continue
        if args.changed and key not in changed:
            continue
        if args.search:
            needle = args.search.lower()
            if needle not in key.lower() and needle not in token["label"].lower():
                continue
        rows.append((key, token, raw.get(key), values.get(key)))

    if args.json:
        payload = [{"key": key, "value": value, "raw": raw_value,
                    "label": token["label"], "desc": token["desc"],
                    "group": token["group"], "kind": token["kind"],
                    "default": token["default"]}
                   for key, token, raw_value, value in rows]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print("没有匹配的令牌。`%s list` 看全部。" % os.path.basename(sys.argv[0]))
        return 0

    current_group = None
    for key, token, raw_value, value in rows:
        if token["group"] != current_group:
            current_group = token["group"]
            print("\n%s%s%s" % (_BOLD, token["groupLabel"], _RESET))
        mark = "*" if key in changed else " "
        # 引用写法的键：显示解析后的颜色，后面标 `= @引用`
        ref = ""
        if isinstance(raw_value, str) and raw_value.startswith("@"):
            ref = "%s= %s%s" % (_DIM, raw_value, _RESET)
        if token["kind"] == "color":
            print(" %s %-22s %-12s %s  %s" % (
                mark, key, value, _swatch(value), ref or token["label"]))
        else:
            print(" %s %-22s %-12s      %s%s" % (
                mark, key, value, token["label"], ref and "  " + ref or ""))
    total = len(rows)
    print("\n%d 个令牌%s   %s" % (
        total,
        "（* = 改过 %d 个）" % len(changed) if changed else "",
        _DIM + path + _RESET))
    return 0


def cmd_get(args, path: str) -> int:
    raw = _load_raw(path)
    values = _resolve(raw)
    missing = [key for key in args.keys if key not in ui_theme.SPEC]
    for key in missing:
        print("%s! 没有这个键：%s%s" % (_RED, key, _RESET))
    for key in args.keys:
        if key in ui_theme.SPEC:
            token = ui_theme.SPEC[key]
            raw_value = raw.get(key)
            suffix = ""
            if isinstance(raw_value, str) and raw_value.startswith("@"):
                suffix = "  %s(= %s)%s" % (_DIM, raw_value, _RESET)
            print("%-22s %s%s" % (key, values.get(key), suffix))
            print("%s%s%s" % (_DIM, _describe(token), _RESET))
    return 2 if missing else 0


def _apply_set(raw, pairs, strict=True):
    """返回 (新 raw, 错误列表, 变化列表)。先全部校验，有一条不行就整体不动。"""
    errors = []
    changes = []
    updated = dict(raw)
    for key, value in pairs:
        if key not in ui_theme.SPEC:
            errors.append("没有这个键：%s（用 `list` 查）" % key)
            continue
        coerced, error = ui_theme.coerce(key, value, strict=strict)
        if error:
            errors.append(error)
            continue
        before = ui_theme.resolve_refs(updated).get(key)
        updated[key] = coerced
        after = ui_theme.resolve_refs(updated).get(key)
        if before != after:
            changes.append((key, before, after))
    return updated, errors, changes


def cmd_set(args, path: str) -> int:
    pairs = []
    for item in args.assignments:
        if "=" not in item:
            print("%s! 要写成 KEY=VALUE，收到 %r%s" % (_RED, item, _RESET))
            return 2
        key, value = item.split("=", 1)
        pairs.append((key.strip(), value.strip()))

    raw = _load_raw(path)
    updated, errors, changes = _apply_set(raw, pairs)
    if errors:
        _print_problems(errors)
        print("%s没有写入任何一个键%s（set 是全有或全无）" % (_RED, _RESET))
        return 2

    if not changes:
        print("值没有变化。")
        return 0

    for key, before, after in changes:
        print("%s%-22s %s → %s%s" % (_GREEN, key, before, after, _RESET))
    if args.dry_run:
        print("%s--dry-run：没有落盘%s" % (_DIM, _RESET))
        return 0

    ui_theme.write_file(path, updated)
    print("\n已写入 %s" % path)
    print(_DIM + "运行中的启动器会在 0.2 秒内自己重绘（不用重启）。" + _RESET)
    return 0


def cmd_reset(args, path: str) -> int:
    raw = _load_raw(path)
    if args.all or not args.keys:
        if not args.all and not args.yes:
            print("这会清空**所有**自定义值。确认请加 --all（或 --yes）。")
            return 0
        updated = dict(ui_theme.DEFAULT_VALUES)
        count = len(ui_theme.diff(_resolve(raw)))
        ui_theme.write_file(path, updated)
        print("%s已恢复默认（清掉 %d 处自定义）%s" % (_GREEN, count, _RESET))
        return 0

    unknown = [key for key in args.keys if key not in ui_theme.SPEC]
    for key in unknown:
        print("%s! 没有这个键：%s%s" % (_RED, key, _RESET))
    if unknown:
        return 2

    updated = dict(raw)
    for key in args.keys:
        updated[key] = ui_theme.SPEC[key]["default"]
    ui_theme.write_file(path, updated)
    print("%s已恢复默认：%s%s" % (_GREEN, "、".join(args.keys), _RESET))
    return 0


def cmd_diff(args, path: str) -> int:
    raw = _load_raw(path)
    values = _resolve(raw)
    changed = ui_theme.diff(values)
    if not changed:
        print("和默认配色一致。")
        return 0
    for key in changed:
        token = ui_theme.SPEC.get(key, {})
        print("%-22s %s → %s  %s%s%s" % (
            key, ui_theme.DEFAULT_RESOLVED.get(key), changed[key],
            _DIM, token.get("label", ""), _RESET))
    print("\n%d 处自定义。`reset --all` 全部恢复。" % len(changed))
    return 0


def cmd_presets(args, path: str) -> int:
    values = _resolve(_load_raw(path))
    print("%s预设%s" % (_BOLD, _RESET))
    for name, (label, overrides) in ui_theme.PRESETS.items():
        target = ui_theme.resolve_refs({**ui_theme.DEFAULT_VALUES, **overrides})
        current = "  ← 当前" if values == target else ""
        print("  %-8s %-18s %s%d 处覆盖%s%s" % (
            name, label, _DIM, len(overrides), _RESET, current))
    print("\n套用：python tools/theme_tool.py preset ink")
    return 0


def cmd_preset(args, path: str) -> int:
    if args.name not in ui_theme.PRESETS:
        print("%s! 没有预设 %s。可选：%s%s" % (
            _RED, args.name, "、".join(ui_theme.PRESETS), _RESET))
        return 2
    label, overrides = ui_theme.PRESETS[args.name]
    # 预设 = 默认 + 覆盖（不是「在现状上叠加」），否则两套预设会互相污染
    updated = dict(ui_theme.DEFAULT_VALUES)
    updated.update(overrides)
    if args.dry_run:
        print("%s--dry-run：会写入 %d 个键%s" % (_DIM, len(updated), _RESET))
        return 0
    ui_theme.write_file(path, updated)
    print("%s已套用预设「%s」→ %s%s" % (_GREEN, label, path, _RESET))
    return 0


def cmd_path(args, path: str) -> int:
    exists = os.path.exists(path)
    print(path)
    print("%s%s%s" % (_DIM, "已存在" if exists else "还不存在（启动一次启动器会自动生成）", _RESET))
    return 0


def cmd_open(args, path: str) -> int:
    ui_theme.ensure_file(path)
    print(path)
    try:
        os.startfile(path)                        # noqa: S606 —— Windows 默认程序
    except AttributeError:
        print("这个平台没有 os.startfile，自己打开上面的路径吧。")
    except OSError as error:
        print("%s打开失败：%s%s" % (_RED, error, _RESET))
        return 1
    return 0


def cmd_watch(args, path: str) -> int:
    """轮询打印主题文件的变化（不需要启动器）。Ctrl+C 退出。"""
    print("盯着 %s（每 %.1fs 查一次，Ctrl+C 退出）" % (path, args.interval))
    last = None
    try:
        while True:
            try:
                stamp = os.path.getmtime(path)
            except OSError:
                stamp = None
            if stamp is not None and stamp != last:
                values = _resolve(_load_raw(path))
                changed = ui_theme.diff(values)
                last = stamp
                now = time.strftime("%H:%M:%S")
                print("[%s] %s  自定义 %d 处" % (now, _DIM + path + _RESET, len(changed)))
                for key, value in list(changed.items())[:12]:
                    print("    %-22s %s" % (key, value))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n停止。")
    return 0


# --------------------------------------------------------------------- 入口
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="theme_tool.py",
        description="LEXARA 启动台主题的外部调参工具（改完启动器自动重绘）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="键表用 `list` 查；颜色支持 #RGB/#RRGGBB/#AARRGGBB，值可写 @其它键 表示跟随。")
    parser.add_argument("--theme", metavar="PATH",
                        help="指定主题文件（默认 %%APPDATA%%/Lexara/theme.json，"
                             "也认 LEXARA_THEME 环境变量）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出令牌")
    p_list.add_argument("--group", help="只看某一组：base/shell/shadow/btn/heat")
    p_list.add_argument("--changed", action="store_true", help="只看改过的")
    p_list.add_argument("--search", help="按键名或中文名过滤")
    p_list.add_argument("--json", action="store_true", help="输出 JSON（给别的程序吃）")
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="查某个键")
    p_get.add_argument("keys", nargs="+")
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser("set", help="改值（KEY=VALUE，可多条）")
    p_set.add_argument("assignments", nargs="+", metavar="KEY=VALUE")
    p_set.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    p_set.set_defaults(func=cmd_set)

    p_reset = sub.add_parser("reset", help="恢复默认")
    p_reset.add_argument("keys", nargs="*")
    p_reset.add_argument("--all", action="store_true", help="清空所有自定义值")
    p_reset.add_argument("--yes", action="store_true", help="不给提示直接做")
    p_reset.set_defaults(func=cmd_reset)

    p_diff = sub.add_parser("diff", help="看改过哪些")
    p_diff.set_defaults(func=cmd_diff)

    p_presets = sub.add_parser("presets", help="看可用预设")
    p_presets.set_defaults(func=cmd_presets)

    p_preset = sub.add_parser("preset", help="套用预设")
    p_preset.add_argument("name")
    p_preset.add_argument("--dry-run", action="store_true")
    p_preset.set_defaults(func=cmd_preset)

    p_path = sub.add_parser("path", help="打印主题文件路径")
    p_path.set_defaults(func=cmd_path)

    p_open = sub.add_parser("open", help="用系统默认程序打开主题文件")
    p_open.set_defaults(func=cmd_open)

    p_watch = sub.add_parser("watch", help="盯着文件变化并打印")
    p_watch.add_argument("--interval", type=float, default=0.4)
    p_watch.set_defaults(func=cmd_watch)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = args.theme or ui_theme.default_path()
    return args.func(args, path)


if __name__ == "__main__":
    sys.exit(main())
