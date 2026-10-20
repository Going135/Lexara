# -*- coding: utf-8 -*-
"""让被测进程**自报**内存。

为什么需要它：`.venv/Scripts/python.exe` 是 `py.exe` 的转发壳（文件描述就是
"Python Launcher"），真正跑代码的是它 spawn 的子进程。外部按 `Popen.pid` 采
WorkingSet 永远只能量到那个 4 MB 的空壳 —— 所以样板代码在进程内部读自己。

用法：
    python tools/_mem_self.py cv2 numpy          # 逐个 import 后报一次
输出一行 JSON：{"modules": [...], "ws": 字节, "private": 字节}
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import importlib
import json
import sys

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


def self_memory():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC_EX), wt.DWORD]
    psapi.GetProcessMemoryInfo.restype = wt.BOOL
    info = _PMC_EX()
    info.cb = ctypes.sizeof(_PMC_EX)
    psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(info), info.cb)
    return int(info.WorkingSetSize), int(info.PrivateUsage)


def main(argv=None) -> int:
    names = list(sys.argv[1:] if argv is None else argv)
    done = []
    for name in names:
        try:
            importlib.import_module(name)
            done.append(name)
        except Exception as error:                # noqa: BLE001
            print("import %s failed: %r" % (name, error), file=sys.stderr)
    ws, private = self_memory()
    print(json.dumps({"modules": done, "ws": ws, "private": private}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
