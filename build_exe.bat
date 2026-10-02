@echo off
setlocal
title Build BookPulse executable

rem ============================================================
rem  Build the Windows executable.
rem
rem  Usage:
rem     build_exe.bat            -> single-file exe  (dist\WeReadHotmarks.exe)
rem     build_exe.bat fast       -> onedir folder    (dist_fast\BookPulse\)
rem     build_exe.bat both       -> build both
rem
rem  Takes a few minutes. Requires .venv (run setup_env.bat first).
rem  NOTE: keep this file ASCII-only (cmd reads .bat as ANSI).
rem ============================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   [ERROR] .venv not found. Run setup_env.bat first.
  echo.
  pause
  exit /b 1
)

if "%1"=="" (
  ".venv\Scripts\python.exe" src\build_exe.py onefile
) else (
  ".venv\Scripts\python.exe" src\build_exe.py %1
)

echo.
pause
