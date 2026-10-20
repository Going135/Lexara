# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets/icon.ico', 'assets'), ('assets/ecdict.sqlite', 'assets'), ('assets/exam-tags.sqlite', 'assets'), ('assets/industry.sqlite', 'assets'), ('assets/skins', 'assets/skins'), ('assets/jar_crack_01.png', 'assets'), ('assets/jar_crack_02.png', 'assets'), ('assets/jar_crack_03.png', 'assets'), ('assets/sfx', 'assets/sfx')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['src/main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtMultimedia', 'PySide6.Qt3DCore', 'PySide6.QtCharts', 'PySide6.QtDesigner', 'PySide6.QtSql', 'PySide6.QtTest', 'tkinter', 'PyQt5'],
    noarchive=False,
    optimize=0,
)
# ★ 2026-10-18：OpenCV 自带的 FFmpeg 编解码器（opencv_videoio_ffmpeg500_64.dll，29MB）
# 本项目完全用不到 —— 我们只用 resize / cvtColor / copyMakeBorder / threshold /
# GaussianBlur / putText，从不碰 VideoCapture / VideoWriter（grep src/ 与 rapidocr
# 全仓无 VideoCapture）。实测删掉该 dll 后 cv2 导入、全部像素运算、RapidOCR 识别
# 链路均正常，故在打包阶段直接剔除，产物立减 29MB。
# ★ 2026-10-19 精简：下面这些在产物里没有一处在用，删掉纯赚体积
#   opencv_videoio_ffmpeg 29MB —— 只用 resize/cvtColor 等像素运算，不碰视频 IO
#   opengl32sw.dll 19.7MB —— Qt 的软件 OpenGL 兜底；本项目走 D3D11 RHI，
#     只有「无显卡驱动 + 强制 opengl 后端」才会加载
#   Qt6Pdf 4.4MB —— 只有 QtPdf/PDF 渲染用，本项目不 import
_DROP_BINARIES = ("opencv_videoio_ffmpeg", "opengl32sw", "Qt6Pdf")
a.binaries = [b for b in a.binaries
              if not any(key in b[0] for key in _DROP_BINARIES)]

# 翻译只留中英文：PySide6 的 hook 会把 198 个 .qm 全收进来，
# 其余语言本项目永远走不到，白占十几 MB。
a.datas = [d for d in a.datas
           if "/translations/" not in d[0].replace("\\", "/")
           or "zh_CN" in d[0] or d[0].replace("\\", "/").endswith("_en.qm")]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LexaraDebug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
)
