@echo off
setlocal

REM Ensure venv exists (create if needed, same as install.bat)
if not exist "venv\" (
    echo Virtual environment not found. Creating...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to create virtual environment.
        echo Make sure Python 3.10+ is installed.
        pause
        exit /b 1
    )
    echo Installing base dependencies...
    venv\Scripts\pip install -r requirements.txt
    echo.
)

venv\Scripts\python tools\install_modules.py %*

echo.
pause
endlocal
exit /b 0
