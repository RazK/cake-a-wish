@echo off
:: One-time setup for Cake A Wish on Windows.
:: Run this once; after that, double-click run.bat or the Desktop shortcut.

cd /d "%~dp0"
set SCRIPT_DIR=%~dp0

echo === Cake A Wish Setup ===

:: 1. Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to tick "Add python.exe to PATH" during install.
    echo Then run this script again.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VERSION=%%v
echo Python %PY_VERSION% found

:: 2. Create virtual environment
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate
echo Virtual environment ready

:: 3. Install dependencies
echo Installing dependencies (this may take a minute)...
pip install -r requirements.txt -q
echo Dependencies installed

:: 4. Create Desktop shortcut
set SHORTCUT=%USERPROFILE%\Desktop\Cake A Wish.bat
(
  echo @echo off
  echo cd /d "%SCRIPT_DIR%"
  echo call .venv\Scripts\activate
  echo python launcher.py
) > "%SHORTCUT%"
echo Desktop shortcut created: %SHORTCUT%

echo.
echo === Setup complete ===
echo Double-click "Cake A Wish" on your Desktop to start.
echo Or run: run.bat
pause
