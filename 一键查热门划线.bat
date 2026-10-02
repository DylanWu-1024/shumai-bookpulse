@echo off
setlocal
title WeRead - Hot Highlights Exporter

rem ============================================================
rem  WeRead Hot Highlights - one click exporter
rem  Just double-click this file and follow the prompts.
rem  NOTE: keep this file ASCII-only (cmd reads .bat as ANSI).
rem ============================================================

rem  Prefer the project virtual environment (created by setup_env.bat).
set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" goto run

rem  Fall back to whatever Python 3 is on PATH.
where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [ERROR] Python not found on this machine.
  echo   Install Python 3.10+ from https://www.python.org/downloads/
  echo   (tick "Add python.exe to PATH" during installation)
  echo.
  echo   Or run setup_env.bat once to create a local environment.
  echo.
  pause
  exit /b 1
)
set "PY=python"

:run
"%PY%" "%~dp0src\weread_hotmarks.py" %*
echo.
pause
