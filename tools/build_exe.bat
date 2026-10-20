@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

rem ==================================================================
rem  Lexara - build script (tests -> QML smoke -> PyInstaller onefile)
rem  IMPORTANT: keep this file 100 percent ASCII. Non-ASCII bytes make
rem  cmd mis-parse the script and abort with bogus "path not found".
rem  The Python env is auto-detected (see below), so renaming folders
rem  does not break the build.
rem ==================================================================

set "PY="
if exist "%~dp0..\.venv\Scripts\python.exe" set "PY=%~dp0..\.venv\Scripts\python.exe"
if not defined PY (
    for /d %%d in ("%~dp0..\..\*") do (
        if not defined PY if exist "%%d\.venv\Scripts\python.exe" set "PY=%%d\.venv\Scripts\python.exe"
    )
)

if not defined PY (
    echo [X] No Python venv found next to this project.
    echo     Create one and install deps:
    echo         python -m venv .venv
    echo         .venv\Scripts\pip install -r requirements.txt
    pause & endlocal & exit /b 1
)

echo ============================================
echo  Lexara - rebuild
echo  env: %PY%
echo ============================================

echo [1/9] icon ...
"%PY%" tools\make_icon.py

echo [2/9] unit tests ...
"%PY%" test\test_spider.py        || (echo FAILED: spider geometry & pause & endlocal & exit /b 1)
"%PY%" test\test_leg_stretch.py   || (echo FAILED: leg stretch & pause & endlocal & exit /b 1)
"%PY%" test\test_click_through.py || (echo FAILED: hit / crop & pause & endlocal & exit /b 1)
"%PY%" test\test_ocr_coords.py    || (echo FAILED: OCR coords & pause & endlocal & exit /b 1)
"%PY%" test\test_industry.py      || (echo FAILED: industry lexicon & pause & endlocal & exit /b 1)
"%PY%" test\test_fold.py          || (echo FAILED: fold / no-leg mode & pause & endlocal & exit /b 1)
"%PY%" test\test_aim_hold.py      || (echo FAILED: aim hold & pause & endlocal & exit /b 1)
"%PY%" test\test_spin.py          || (echo FAILED: spin anim & pause & endlocal & exit /b 1)
"%PY%" test\test_skin.py          || (echo FAILED: skins & pause & endlocal & exit /b 1)

echo [3/9] shape / render smoke ...
"%PY%" tools\shape_sheet.py       || (echo FAILED: shape render & pause & endlocal & exit /b 1)

echo [4/9] e2e aim (legs on words + box highlight) ...
"%PY%" tools\aim_e2e.py           || (echo FAILED: aim e2e & pause & endlocal & exit /b 1)

echo [5/9] aim trigger matrix ...
"%PY%" tools\aim_trigger_probe.py || (echo FAILED: aim trigger & pause & endlocal & exit /b 1)

echo [6/9] fold sheet ...
"%PY%" tools\fold_sheet.py        || (echo FAILED: fold sheet & pause & endlocal & exit /b 1)

rem QML side: settings / skin writes must reach settings.json + the jar renderer.
rem This probe temporarily edits settings.json and restores it in a finally block.
echo [7/9] QML bridge writes ...
"%PY%" tools\qml_bridge_probe.py  || (echo FAILED: QML bridge writes & pause & endlocal & exit /b 1)

echo [8/9] QML launcher smoke ...
"%PY%" tools\qml_smoke.py         || (echo FAILED: QML launcher & pause & endlocal & exit /b 1)

echo [9/9] PyInstaller (takes a few minutes) ...
rem 2026-10-18: build via Lexara.spec instead of a long CLI list.
rem Why: only a spec can filter Analysis().binaries, and we drop cv2's
rem FFmpeg video plugin (opencv_videoio_ffmpeg500_64.dll, 29MB) there.
rem The spec mirrors the old CLI exactly: onefile / windowed / noupx,
rem same --add-data set, same Qt module excludes.
"%PY%" -m PyInstaller Lexara.spec --noconfirm || (echo BUILD FAILED & pause & endlocal & exit /b 1)

echo.
echo ============================================
echo  done: dist\Lexara.exe
echo ============================================
pause
endlocal
