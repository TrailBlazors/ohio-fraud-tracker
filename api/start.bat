@echo off
REM ============================================
REM Ohio Fraud Tracker - Quick Start
REM Double-click to start the API server
REM ============================================

cd /d "%~dp0"

echo.
echo ============================================
echo   Ohio Fraud Tracker API
echo ============================================
echo.

REM Check if venv exists
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found!
    echo.
    echo Please run setup first:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM Activate and run
echo Starting API server...
echo.
".venv\Scripts\python.exe" run.py

pause
