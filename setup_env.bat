@echo off
setlocal
title BookPulse - one time setup

rem ============================================================
rem  BookPulse - one-time environment setup
rem
rem  Creates a .venv folder next to this file and installs the
rem  project dependencies (PySide6 is the only one).
rem
rem  Run this ONCE. After that, use the GUI launcher .bat.
rem
rem  NOTE: keep this file ASCII-only (cmd reads .bat as ANSI).
rem ============================================================

cd /d "%~dp0"

echo.
echo   ============================================================
echo    BookPulse - environment setup
echo   ============================================================
echo.

rem ---------------------------------------------------------------- find Python
where python >nul 2>&1
if errorlevel 1 (
  echo   [ERROR] Python 3 not found.
  echo.
  echo   Please install Python 3.10 or newer from
  echo       https://www.python.org/downloads/
  echo   and make sure to tick "Add python.exe to PATH"
  echo   during installation.
  echo.
  pause
  exit /b 1
)
set "PY=python"

for /f "delims=" %%v in ('"%PY%" -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
echo   Using Python: %PY%  ^(version %PYVER%^)
echo.

rem ---------------------------------------------------------------- create venv
echo   [1/4] Creating virtual environment (.venv) ...
"%PY%" -m venv .venv
if errorlevel 1 (
  echo   [ERROR] Failed to create the virtual environment.
  pause
  exit /b 1
)
echo         done.
echo.

rem ---------------------------------------------------------------- upgrade pip
echo   [2/4] Upgrading pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
echo         done.
echo.

rem ---------------------------------------------------------------- install deps
echo   [3/4] Installing dependencies (this downloads about 200 MB) ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo   Default package index failed. Retrying with the Aliyun mirror ...
  echo.
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
)
if errorlevel 1 (
  echo.
  echo   [ERROR] Dependency installation failed.
  echo   Check your network connection and run this file again.
  echo.
  pause
  exit /b 1
)
echo         done.
echo.

rem ---------------------------------------------------------------- verify
echo   [4/4] Verifying ...
".venv\Scripts\python.exe" -c "import PySide6; print('        PySide6', PySide6.__version__, 'OK')"
if errorlevel 1 (
  echo   [WARN] PySide6 could not be imported. The app may not start.
  echo.
)

echo.
echo   ============================================================
echo    Setup complete.
echo.
echo    Next step: double-click the GUI launcher .bat in this folder.
echo   ============================================================
echo.
pause
exit /b 0
