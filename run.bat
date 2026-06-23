@echo off
:: Start Cake A Wish. Run this after setup.bat has been run once.

cd /d "%~dp0"

if not exist ".venv" (
    echo Error: .venv not found. Run setup.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\activate
python launcher.py
