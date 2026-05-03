@echo off
title UNS Design Studio Dashboard
echo.
echo  ==============================================================
echo  UNS Design Studio
echo  Starting web dashboard on http://localhost:5000
echo  ==============================================================
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

REM Open browser when the Flask app is ready instead of using a fixed delay
start "" /b cmd /c "for /l %%i in (1,1,30) do (powershell -NoProfile -Command ""try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5000/api/status' -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }"" >nul 2>&1 && start "" http://localhost:5000 && exit /b 0 || timeout /t 1 >nul)"

REM Start the dashboard
cd /d "%~dp0"
python app.py

pause
