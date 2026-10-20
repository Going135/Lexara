@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ==================================================================
rem  One-time setup: create a local .venv and install runtime deps.
rem  Keep this file 100 percent ASCII (see note in run.bat).
rem ==================================================================

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo [X] No Python interpreter found.
    echo     Install Python 3.13 from https://www.python.org/downloads/
    echo     Remember to tick "Add python.exe to PATH".
    pause
    endlocal
    exit /b 1
)

echo [1/3] interpreter: %PY%
"%PY%" --version

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [2/3] creating .venv ...
    "%PY%" -m venv .venv
    if errorlevel 1 goto fail
) else (
    echo [2/3] .venv already exists, reusing it
)

echo [3/3] installing dependencies ^(this can take a few minutes^) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-runtime.txt
if errorlevel 1 goto fail

echo.
echo [OK] Done. Now double-click run.bat to start.
echo      If pip was slow or failed, see README.md, Route B, "Slow downloads".
pause
endlocal
exit /b 0

:fail
echo.
echo [X] Installation failed. Common causes:
echo     - no network / proxy required
echo     - Python too old ^(3.13 recommended^)
echo     See README.md, Route B, for a PyPI mirror and troubleshooting.
pause
endlocal
exit /b 1
