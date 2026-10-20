# -*- coding: utf-8 -*-
"""打包产物体检：体积构成 + 运行时内存。

用法::

    python tools/package_size_audit.py                     # 默认量 dist/LexaraPortable
    python tools/package_size_audit.py dist/LexaraPortable
    python tools/package_size_audit.py --mem               # 顺手量一次启动后的内存
    python tools/package_size_audit.py --json              # 给 CI 吃

为什么要有这个工具：`du -sh dist/xxx` 只会给一个总数，看不出「112MB 是 OpenCV」
这种事实。体积问题的解法几乎全部来自**知道哪一块大、以及它是不是死重**，
所以这里把「按目录 / 按文件 / 已知死重」三层都列出来。

`--mem` 会真的把 exe 拉起来采样工作集（WorkingSet），
因为这个项目里「打包后占多少内存」一直只能靠猜。
注意：采样完会结束该进程，不会留在桌面上。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 已知的死重 / 可选项：名字片段 → (结论, 说明)。
#: 结论只有三种：`drop`（可删，已进 spec）、`opt`（可删但有代价）、`keep`（必须留）。
KNOWN = [
    ("opencv_videoio_ffmpeg", "drop",
     "OpenCV 的 FFmpeg 编解码器，只服务 VideoCapture/VideoWriter；"
     "本项目从不解码视频（全仓无 VideoCapture），已在 spec 里剔除"),
    ("opengl32sw.dll", "opt",
     "Qt 的软件 OpenGL 回退（Mesa）。有独显/正常驱动时永远不加载；"
     "删掉可省 20MB，但虚拟机/无驱动环境会起不来"),
    ("Qt6Pdf", "opt",
     "Qt PDF 模块。本项目不生成也不显示 PDF，可加进 excludes"),
    ("icudt78.dll", "keep",
     "Qt 的 ICU 语言数据。QLocale / 中文排序 / 大小写转换都依赖它，不能删"),
    ("numpy.libs", "keep",
     "NumPy 的 OpenBLAS。删掉 numpy 直接导入失败"),
    ("onnxruntime", "keep",
     "OCR 推理引擎，RapidOCR 的底座"),
    ("ecdict.sqlite", "keep",
     "离线词库主数据（65MB）。想瘦身只能裁剪词条/列，属于内容决策"),
]


def _dir_size(path: str) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _mb(n: int) -> str:
    return "%.1fMB" % (n / 2 ** 20)


# ---------------------------------------------------------------- 内存

class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


def _working_set_mb(pid: int) -> float | None:
    """读进程工作集（MB）。拿不到返回 None（进程已退出 / 无权限）。"""
    if os.name != "nt":
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p,
                                           ctypes.POINTER(_PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED
    if not handle:
        return None
    try:
        info = _PMC()
        info.cb = ctypes.sizeof(_PMC)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(info), info.cb):
            return None
        return info.WorkingSetSize / 2 ** 20
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))


def measure_memory(exe: str, seconds: int = 24, step: float = 3.0) -> dict:
    """拉起 exe 采样工作集。返回 {samples, steady, peak}。"""
    env = dict(os.environ)
    env.pop("LEXARA_QML_SHOT", None)
    proc = subprocess.Popen([exe], cwd=os.path.dirname(exe) or None, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    samples = []
    try:
        deadline = time.time() + seconds
        while time.time() < deadline:
            time.sleep(step)
            ws = _working_set_mb(proc.pid)
            if ws is None:
                break
            samples.append((round(time.time() - (deadline - seconds), 1), round(ws, 1)))
    finally:
        proc.terminate()
        try:
            proc.wait(6)
        except Exception:                                  # noqa: BLE001
            proc.kill()
    values = [v for _, v in samples]
    # 稳态取后 1/3 的中位数：启动期的峰值（QML 编译 / 首次渲染）不该算进常驻。
    tail = sorted(values[max(1, len(values) * 2 // 3):]) if values else []
    return {
        "samples": samples,
        "steady": tail[len(tail) // 2] if tail else None,
        "peak": max(values) if values else None,
    }


# ---------------------------------------------------------------- 报告

def audit(target: str) -> dict:
    target = os.path.abspath(target)
    report = {"target": target, "exists": os.path.isdir(target)}

    if os.path.isfile(target):                             # onefile 的 exe
        size = os.path.getsize(target)
        report.update(total=size, entries=[], files=[])
        return report

    if not report["exists"]:
        return report

    inner = os.path.join(target, "_internal")
    root = inner if os.path.isdir(inner) else target

    entries = []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        size = _dir_size(path) if os.path.isdir(path) else os.path.getsize(path)
        entries.append((size, name))
    entries.sort(reverse=True)

    files = []
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            try:
                files.append((os.path.getsize(path), os.path.relpath(path, root)))
            except OSError:
                pass
    files.sort(reverse=True)

    report.update(total=_dir_size(target), entries=entries[:12], files=files[:12],
                  all_files=files, root=root)
    return report


def known_hits(report: dict) -> list:
    """在产物里找已知条目，返回 [(结论, 命中名, 体积, 说明)]。

    体积一律按**文件**累加（`all_files`）—— 顶层条目与文件是同一批字节，
    两边相加会把同名文件算两遍（第一版就把 31.6MB 的 icudt 显示成 63.2MB）。
    """
    out = []
    for key, verdict, note in KNOWN:
        size = sum(s for s, n in report.get("all_files", []) if key in n)
        if size:
            out.append((verdict, key, size, note))
    return out


def print_report(report: dict, mem: dict | None = None) -> None:
    target = report["target"]
    if not report["exists"]:
        print("找不到产物：%s" % target)
        print("先打包：  .venv\\Scripts\\python.exe -m PyInstaller LexaraPortable.spec --noconfirm")
        return

    print("=" * 68)
    print("产物：%s" % target)
    print("总体积：%s" % _mb(report["total"]))
    print("=" * 68)

    if report.get("entries"):
        print("\n[按目录 / 顶层条目]")
        for size, name in report["entries"]:
            share = size / report["total"] * 100 if report["total"] else 0
            print("  %8s  %5.1f%%  %s" % (_mb(size), share, name))

        print("\n[最大的 12 个文件]")
        for size, name in report["files"]:
            print("  %8s  %s" % (_mb(size), name))

    hits = known_hits(report)
    if hits:
        print("\n[已知条目体检]")
        marks = {"drop": "[冗余]", "opt": "[可选]", "keep": "[保留]"}
        for verdict, key, size, note in hits:
            print("  %s %-28s %8s" % (marks[verdict], key, _mb(size)))
            print("        %s" % note)

    if mem:
        print("\n[运行时内存（工作集）]")
        if mem.get("samples"):
            for sec, ws in mem["samples"]:
                print("  t=%4.1fs  %7.1fMB" % (sec, ws))
            print("  稳态 %s   峰值 %s" % (_mb(int((mem["steady"] or 0) * 2 ** 20)),
                                           _mb(int((mem["peak"] or 0) * 2 ** 20))))
        else:
            print("  没能采到数据（进程起不来或立刻退出）")
    print()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="打包产物体积 / 内存体检")
    parser.add_argument("target", nargs="?", default=os.path.join(BASE, "dist", "LexaraPortable"),
                        help="产物目录或 exe（默认 dist/LexaraPortable）")
    parser.add_argument("--mem", action="store_true", help="拉起程序采样内存")
    parser.add_argument("--seconds", type=int, default=24, help="内存采样总时长")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    report = audit(args.target)
    mem = None
    if args.mem and report["exists"]:
        exe = args.target
        if os.path.isdir(exe):
            exe = os.path.join(exe, os.path.basename(exe.rstrip("\\/")) + ".exe")
        if os.path.isfile(exe):
            mem = measure_memory(exe, seconds=args.seconds)

    if args.json:
        payload = {
            "total_mb": round(report["total"] / 2 ** 20, 1) if report["exists"] else None,
            "entries": [{"name": n, "mb": round(s / 2 ** 20, 1)}
                        for s, n in report.get("entries", [])],
            "files": [{"name": n, "mb": round(s / 2 ** 20, 1)}
                      for s, n in report.get("files", [])],
            "known": [{"key": k, "verdict": v, "mb": round(s / 2 ** 20, 1)}
                      for v, k, s, _ in known_hits(report)],
            "memory": mem,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_report(report, mem)
    return 0 if report["exists"] else 2


if __name__ == "__main__":
    sys.exit(main())
