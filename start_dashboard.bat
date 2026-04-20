@echo off
title GlobalFoodCo – UNS Simulator Dashboard
echo.
echo  ╔══════════════════════════════════════════════════════════════╗
echo  ║   UNS Design Studio       ║
echo  ║   Starting web dashboard on http://localhost:5000            ║
echo  ╚══════════════════════════════════════════════════════════════╝
echo.

REM Check Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  ERROR: Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

REM Check Flask
python -c "import flask" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  Installing Flask...
    pip install flask
)

REM Open browser after 2 seconds
start /b cmd /c "timeout /t 2 >nul && start http://localhost:5000"

REM Start the dashboard
cd /d "%~dp0"
python app.py

pause
