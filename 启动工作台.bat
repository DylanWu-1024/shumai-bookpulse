@echo off
setlocal
title BookPulse - WeRead Highlights Studio

rem ============================================================
rem  BookPulse - desktop app launcher
rem  Double-click this file to open the GUI workbench.
rem
rem  Requires .venv (run setup_env.bat once first).
rem  NOTE: keep this file ASCII-only (cmd reads .bat as ANSI).
rem ============================================================

cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" goto run

echo.
echo   [ERROR] Virtual environment not found.
echo   Please run setup_env.bat first (one time only).
echo.
pause
exit /b 1

:run
rem  Source code lives in src\ ; this file is only the entry point.
start "" "%PY%" "%~dp0src\app_gui.py"
exit /b 0
