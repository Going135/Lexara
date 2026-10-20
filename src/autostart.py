# -*- coding: utf-8 -*-
"""Windows 开机自启动（任务书 §5）。

实现选型
--------
用**当前用户的 Startup 文件夹快捷方式**，不改注册表 `Run` 键、不需要管理员权限：

    %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Lexara.lnk

为什么不写 `HKCU\\…\\Run`：Startup 文件夹是 Windows 官方给普通应用的口子，
用户可以在「任务管理器 → 启动」里看到并禁用，出问题时手工删掉也一目了然；
而且我们只创建/删除**自己那一个 .lnk**，客户机上别的启动项一个都不碰。

开发环境 vs 打包版
------------------
- 打包（`sys.frozen`）：Target = 本 exe，无参数；
- 开发：Target = 当前 Python 解释器，参数 = `"<项目>\\src\\main.py"`，工作目录 = 项目根。

失败时**如实返回 False + 原因**，由 UI 回滚开关，绝不假装成功。
"""

from __future__ import annotations

import os
import subprocess
import sys

#: 快捷方式文件名。刻意用 ASCII：避免某些系统区域设置下 cmd/PowerShell
#: 对中文文件名的编码抖动（项目已知坑：`.bat` 必须纯 ASCII）。
SHORTCUT_NAME = "Lexara.lnk"
#: 快捷方式描述（会显示在任务管理器「启动」页）
SHORTCUT_DESC = "词蛛 LEXARA"


def startup_dir() -> str:
    """当前用户的 Startup 目录（不保证存在）。"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup")


def shortcut_path(directory: str | None = None) -> str:
    return os.path.join(directory or startup_dir(), SHORTCUT_NAME)


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def launch_target() -> tuple:
    """(target, arguments, working_dir, icon)。打包态与开发态唯一的分叉点。"""
    root = _project_root()
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return exe, "", os.path.dirname(exe), exe
    script = os.path.join(root, "src", "main.py")
    icon = os.path.join(root, "assets", "icon.ico")
    return sys.executable, '"%s"' % script, root, icon


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_powershell(script: str) -> tuple:
    """跑一段 PowerShell。返回 (ok, output)。不弹窗（NoProfile / 非交互）。"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=25,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return False, "系统里找不到 PowerShell，无法创建启动快捷方式。"
    except subprocess.TimeoutExpired:
        return False, "创建启动快捷方式超时（PowerShell 25 秒未返回）。"
    except Exception as error:                  # noqa: BLE001
        return False, "创建启动快捷方式失败：%r" % (error,)
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, output


def is_enabled(directory: str | None = None) -> bool:
    """启动项是否存在（真实状态以文件为准，不依赖任何缓存/设置位）。"""
    return os.path.isfile(shortcut_path(directory))


def state(directory: str | None = None) -> dict:
    target, arguments, workdir, icon = launch_target()
    return {"enabled": is_enabled(directory),
            "path": shortcut_path(directory),
            "target": target,
            "arguments": arguments,
            "workingDirectory": workdir,
            "supported": os.name == "nt"}


def enable(directory: str | None = None) -> dict:
    """启用开机自启动。**幂等**：先删后建，重复调用只会有 1 个快捷方式。"""
    if os.name != "nt":
        return {"ok": False, "enabled": False,
                "message": "当前系统不是 Windows，开机自启动不可用。"}
    folder = directory or startup_dir()
    if not os.path.isdir(folder):
        return {"ok": False, "enabled": False,
                "message": "找不到系统启动目录：%s" % folder}
    path = shortcut_path(folder)
    # 先把旧的删掉（可能是上一版 exe 的路径），避免出现两个启动项
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as error:
        return {"ok": False, "enabled": is_enabled(folder),
                "message": "旧的启动项删不掉（%s）。" % error}

    target, arguments, workdir, icon = launch_target()
    script = ("$shell = New-Object -ComObject WScript.Shell; "
              "$link = $shell.CreateShortcut(%s); "
              "$link.TargetPath = %s; $link.Arguments = %s; "
              "$link.WorkingDirectory = %s; $link.Description = %s; "
              "$link.IconLocation = %s; $link.Save()"
              % (_ps_quote(path), _ps_quote(target), _ps_quote(arguments),
                 _ps_quote(workdir), _ps_quote(SHORTCUT_DESC),
                 _ps_quote(icon)))
    ok, output = _run_powershell(script)
    if not ok:
        return {"ok": False, "enabled": is_enabled(folder),
                "message": "系统拒绝了这次操作：%s" % (output or "没有返回原因")}
    if not os.path.isfile(path):
        return {"ok": False, "enabled": False,
                "message": "命令执行完了，但启动项没有生成。"}
    return {"ok": True, "enabled": True, "path": path,
            "message": "已加入开机启动（%s）" % SHORTCUT_NAME}


def disable(directory: str | None = None) -> dict:
    """关闭开机自启动：只删本产品那一个 .lnk。"""
    folder = directory or startup_dir()
    path = shortcut_path(folder)
    if not os.path.isfile(path):
        return {"ok": True, "enabled": False,
                "message": "开机启动原本就是关闭的"}
    try:
        os.remove(path)
    except OSError as error:
        return {"ok": False, "enabled": is_enabled(folder),
                "message": "启动项删不掉（%s），可能被其他程序占用。" % error}
    return {"ok": not is_enabled(folder), "enabled": is_enabled(folder),
            "message": "已取消开机启动" if not is_enabled(folder)
            else "删除后启动项仍然存在"}


def help_text() -> str:
    """给设置面板用的说明（写清怎么关）。"""
    return ("开启后，登录 Windows 时会自动运行词蛛（只写入当前用户的启动文件夹，"
            "不需要管理员权限）。关闭方式：把这里的开关关掉，或删除\n"
            "%s\n里的 %s。" % (startup_dir(), SHORTCUT_NAME))
