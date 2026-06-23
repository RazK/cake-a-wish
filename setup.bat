@echo off
:: One-time setup for Cake A Wish on Windows.
:: Run this once; after that, double-click run.bat or the Desktop shortcut.
:: Pass --force as first argument to redo all steps.

cd /d "%~dp0"
set SCRIPT_DIR=%~dp0
set FORCE=0
if "%1"=="--force" set FORCE=1

echo === Cake A Wish Setup ===

:: 1. Check Python 3.11+
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
for /f "tokens=1,2 delims=." %%a in ("%PY_VERSION%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if %PY_MAJOR% LSS 3 (
    echo Error: Python 3.11+ required ^(found %PY_VERSION%^).
    echo Install it from https://www.python.org/downloads/ then run this script again.
    pause
    exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 11 (
    echo Error: Python 3.11+ required ^(found %PY_VERSION%^).
    echo Install it from https://www.python.org/downloads/ then run this script again.
    pause
    exit /b 1
)
echo Python %PY_VERSION%

:: 2. Create virtual environment (skip if exists)
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
) else if "%FORCE%"=="1" (
    echo Recreating virtual environment...
    rmdir /s /q .venv
    python -m venv .venv
)
call .venv\Scripts\activate
echo Virtual environment ready

:: 3. Install dependencies (skip if already installed)
if "%FORCE%"=="1" goto install_deps
python -c "import uvicorn, fastapi, PIL, brother_ql, serial" >nul 2>&1
if errorlevel 1 goto install_deps
echo Dependencies already installed
goto deps_done
:install_deps
echo Installing dependencies (this may take a minute)...
pip install -r requirements.txt -q
echo Dependencies installed
:deps_done

:: 4. Download face_landmarker.task if missing
set TASK_FILE=blow_detection\face_landmarker.task
set TASK_URL=https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
if exist "%TASK_FILE%" if not "%FORCE%"=="1" (
    echo face_landmarker.task already present
    goto task_done
)
echo Downloading face_landmarker.task (~3.6 MB)...
curl -L -o "%TASK_FILE%" "%TASK_URL%"
if errorlevel 1 (
    del /f "%TASK_FILE%" >nul 2>&1
    echo Warning: download failed -- camera blow detection will be unavailable
) else (
    echo face_landmarker.task downloaded
)
:task_done

:: 5. Create Desktop shortcut (skip if exists)
set SHORTCUT=%USERPROFILE%\Desktop\Cake A Wish.bat
if exist "%SHORTCUT%" if not "%FORCE%"=="1" (
    echo Desktop shortcut already exists
    goto shortcut_done
)
(
  echo @echo off
  echo cd /d "%SCRIPT_DIR%"
  echo call .venv\Scripts\activate
  echo python launcher.py
) > "%SHORTCUT%"
echo Desktop shortcut created: %SHORTCUT%
:shortcut_done

echo.
echo === Setup complete ===
echo Double-click "Cake A Wish" on your Desktop to start.
echo Or run: run.bat
pause
