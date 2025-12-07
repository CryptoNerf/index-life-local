@echo off
REM Startup script for index.life local application (Windows)

echo ========================================
echo   Starting index.life Local Diary
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate

REM Check if dependencies are installed
pip show Flask >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
    echo.
)

REM Run the application
echo Starting application...
echo.
python run.py

REM Keep window open if error occurs
if errorlevel 1 (
    echo.
    echo ERROR: Application failed to start
    pause
)
