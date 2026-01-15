@echo off
setlocal EnableExtensions

REM -------------------------------------------------
REM Overlord install script (Windows)
REM -------------------------------------------------

set "VENV_DIR=.venv"
set "PYTHON_EXE=python"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

echo.
echo [Overlord] Installation started
echo.

REM --- Check Python ---
%PYTHON_EXE% --version >nul 2>&1 || (
  echo ERROR: Python not found in PATH
  exit /b 1
)

REM --- Create venv ---
if not exist "%VENV_PY%" (
  echo Creating virtual environment...
  %PYTHON_EXE% -m venv "%VENV_DIR%" || exit /b 1
) else (
  echo Virtual environment already exists
)

REM --- Upgrade pip ---
echo Upgrading pip (venv)...
"%VENV_PY%" -m pip install --upgrade pip || exit /b 1

REM --- Install dependencies ---
echo Installing dependencies (venv)...
"%VENV_PY%" -m pip install rich || exit /b 1

REM --- tomli only if Python < 3.11 ---
"%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info < (3,11) else 1)" >nul 2>&1
if not errorlevel 1 (
  echo Installing tomli (Python ^< 3.11)...
  "%VENV_PY%" -m pip install tomli || exit /b 1
)

echo.
echo [Overlord] Installation complete
echo.

REM -------------------------------------------------
REM Open activated shell
REM -------------------------------------------------
echo Opening activated shell...
start "Overlord venv" cmd /k call ".venv\Scripts\activate.bat"

REM -------------------------------------------------
REM Minimize installer window
REM -------------------------------------------------
powershell -NoProfile -Command ^
  "(New-Object -ComObject Shell.Application).MinimizeAll()" >nul 2>&1

exit /b 0
