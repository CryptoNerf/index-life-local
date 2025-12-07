@echo off
REM Installation script for index.life local application (Windows)

echo ========================================
echo   index.life - Installation
echo ========================================
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo.
    echo Please install Python 3.8 or higher from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM Create virtual environment
if exist "venv\" (
    echo Virtual environment already exists.
    set /p RECREATE="Recreate virtual environment? (Y/N): "
    if /i "%RECREATE%"=="Y" (
        echo Removing old virtual environment...
        rmdir /s /q venv
    )
)

if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip
echo.

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
echo.

echo ========================================
echo Installation completed successfully!
echo ========================================
echo.
echo To start the application, run:
echo   start.bat
echo.
echo Or simply double-click start.bat
echo.

pause
