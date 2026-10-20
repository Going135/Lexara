# -*- coding: utf-8 -*-
"""内存探针：量「谁在吃 RAM」。

两种用法：
    python tools/mem_probe.py --imports          # 单个依赖的常驻基线
    python tools/mem_probe.py --app [秒数]        # 拉起 src/main.py 采整机曲线

为什么要单独量 import 基线：应用总内存 = 解释器 + 各 C 扩展的私有页 + 渲染缓冲，
只看总数永远不知道该砍谁。这里把每一块单独拉起来量，数字可以直接相减。

采样口径：
    WorkingSet   任务管理器「内存」那一列（含共享页）
    Private      「提交大小」里私有的部分，进程退出才真正还给系统
    Peak         生命周期峰值（--app 结束时打印）
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

_MB = 1024 * 1024


class _PMC_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.OpenProcess.restype = wt.HANDLE
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_kernel32.CloseHandle.restype = wt.BOOL
_psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC_EX), wt.DWORD]
_psapi.GetProcessMemoryInfo.restype = wt.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def sample(pid: int):
    """返回 (working_set, private, peak) 字节；进程没了返回 None。"""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        info = _PMC_EX()
        info.cb = ctypes.sizeof(_PMC_EX)
        if not _psapi.GetProcessMemoryInfo(handle, ctypes.byref(info), info.cb):
            return None
        return (info.WorkingSetSize, info.PrivateUsage, info.PeakWorkingSetSize)
    finally:
        _kernel32.CloseHandle(handle)


def _mb(value: float) -> str:
    return "%7.1f MB" % (value / _MB)


# ---------------------------------------------------------------- import 基线

#: 每一项都在**独立子进程**里 import，避免互相污染。
IMPORT_CASES = [
    ("空解释器", []),
    ("PySide6.QtCore", ["PySide6.QtCore"]),
    ("QtWidgets", ["PySide6.QtCore", "PySide6.QtWidgets"]),
    ("QtQuick (QML 引擎)", ["PySide6.QtCore", "PySide6.QtQuick", "PySide6.QtQml"]),
    ("numpy", ["numpy"]),
    ("opencv (cv2)", ["cv2"]),
    ("onnxruntime", ["onnxruntime"]),
    ("rapidocr", ["rapidocr_onnxruntime"]),
]


def probe_imports() -> None:
    """量单个依赖的常驻基线。

    ★ 不按 pid 采外部内存：`.venv/Scripts/python.exe` 是 py.exe 的转发壳，
      真正跑 import 的是它的子进程。这里让子进程自己报（_mem_self.py）。
    """
    import json

    print("== import 基线（独立进程，工作集 / 私有）==")
    base = None
    for name, mods in IMPORT_CASES:
        cmd = [sys.executable, os.path.join("tools", "_mem_self.py")] + mods
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        payload = None
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                payload = json.loads(line)
        if not payload:
            print("  %-22s  测量失败: %s" % (name, (proc.stderr or "").strip()[:80]))
            continue
        ws, private = payload["ws"], payload["private"]
        if base is None:
            base = (ws, private)
            print("  %-22s %s / %s" % (name, _mb(ws), _mb(private)))
        else:
            print("  %-22s %s / %s   (+%s 工作集 / +%s 私有)"
                  % (name, _mb(ws), _mb(private),
                     _mb(ws - base[0]), _mb(private - base[1])))


# ---------------------------------------------------------------- 进程树

_TH32CS_SNAPPROCESS = 0x00000002


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _children_map() -> dict:
    """pid -> [子进程 pid, ...]。一次快照，几十毫秒。"""
    kernel32 = _kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wt.BOOL
    kernel32.Process32NextW.restype = wt.BOOL

    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wt.HANDLE(-1).value:
        return {}
    out = {}
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    return out


def _tree_pids(root: int) -> list:
    """root 及其全部后代。"""
    children = _children_map()
    seen, stack, out = {root}, [root], []
    while stack:
        pid = stack.pop()
        out.append(pid)
        for kid in children.get(pid, ()):
            if kid not in seen:
                seen.add(kid)
                stack.append(kid)
    return out


def _heaviest(root: int):
    """进程树里工作集最大的那个 —— 真正干活的是它，不是 py.exe 转发壳。"""
    best = None
    for pid in _tree_pids(root):
        got = sample(pid)
        if got and (best is None or got[0] > best[1][0]):
            best = (pid, got)
    return best


# ---------------------------------------------------------------- 整机曲线

def probe_app(seconds: int = 26, step: float = 2.0) -> None:
    env = dict(os.environ)
    env.setdefault("LEXARA_SFX_MUTE", "1")
    print("== src/main.py 运行曲线（每 %.0fs 一次）==" % step)
    proc = subprocess.Popen([sys.executable, "src/main.py"], env=env)
    rows, started = [], time.time()
    peak = 0
    try:
        while time.time() - started < seconds:
            time.sleep(step)
            best = _heaviest(proc.pid)
            if not best:
                print("  进程已退出")
                break
            _pid, (ws, private, peak_ws) = best
            elapsed = time.time() - started
            rows.append((elapsed, ws, private))
            peak = max(peak, peak_ws)
            print("  %5.1fs  工作集 %s   私有 %s   (pid %d)"
                  % (elapsed, _mb(ws), _mb(private), _pid))
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True)
        proc.wait()
    if rows:
        steady = sorted(r[1] for r in rows)[len(rows) // 2]
        tail = rows[-1][1]
        print("-- 中位工作集 %s   收尾 %s   峰值 %s"
              % (_mb(steady), _mb(tail), _mb(peak)))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--imports" in argv:
        probe_imports()
    elif "--app" in argv:
        idx = argv.index("--app")
        secs = int(argv[idx + 1]) if len(argv) > idx + 1 and argv[idx + 1].isdigit() else 26
        probe_app(secs)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
