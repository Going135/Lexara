"""Keep Qt's MSVC libraries and Windows' system ICU during PyInstaller builds.

A tool's PATH may contain an older libheif MSVC runtime. PyInstaller can pick
that for the archive root, which is loaded before Qt's private directory and
can shadow Qt's runtime. Poppler's unversioned icuuc.dll is also incompatible
with Windows ICU used by Qt: it exports suffixed instead of Windows entry points.
"""
from pathlib import Path


def pin_qt_runtime(binaries, qt_dir=None):
    if qt_dir is None:
        from PyInstaller.utils.hooks import get_package_paths
        qt_dir = get_package_paths("PySide6")[1]
    qt_dir = Path(qt_dir)
    names = {"msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
             "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll",
             "concrt140.dll"}
    available = {p.name.lower(): p for p in qt_dir.iterdir()
                 if p.is_file() and p.name.lower() in names}
    required = {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"}
    if not required <= available.keys():
        raise RuntimeError("Qt's bundled MSVC runtime is incomplete")
    # Qt on Windows uses the OS ICU API. Do not ship a same-name Poppler/Conda
    # ICU DLL (or its now-unused data DLL) ahead of System32 in the loader path.
    system_icu = {"icuuc.dll", "icuin.dll", "icu.dll", "icudt78.dll"}
    result = [entry for entry in binaries
              if entry[0].lower() not in available.keys() | system_icu]
    result.extend((name, str(path), "BINARY") for name, path in sorted(available.items()))
    return result
