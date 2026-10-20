@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ==================================================================
rem  Dev launcher: runs the source tree, no exe needed.
rem  IMPORTANT: keep this file 100 percent ASCII. Any non-ASCII byte
rem  makes cmd mis-parse the whole script (it decodes with the OEM
rem  codepage), which silently breaks every line and falls back to a
rem  bare system python without PySide6.
rem ==================================================================

set "PY="

rem 1) a venv inside this project
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"

rem 2) any sibling project that has a venv
if not defined PY (
    for /d %%d in ("%~dp0..\*") do (
        if not defined PY if exist "%%d\.venv\Scripts\python.exe" set "PY=%%d\.venv\Scripts\python.exe"
    )
)

rem 3) fall back to a system interpreter
if not defined PY (
    where py >nul 2>nul
    if not errorlevel 1 set "PY=py"
)
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo [X] No Python interpreter found.
    echo     Install the deps first:  pip install -r requirements.txt
    pause
    endlocal
    exit /b 1
)

echo [run] %PY%  src\main.py
"%PY%" src\main.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [X] exited with code %RC%
    pause
)
endlocal
