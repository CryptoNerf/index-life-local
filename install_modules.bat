@echo off
setlocal

REM Detect context: EXE distribution or source checkout
if exist "%~dp0index-life.exe" (
    REM === EXE CONTEXT ===
    echo ========================================
    echo   index.life - Module Installer (EXE)
    echo ========================================
    echo.

    REM Check if system Python is available
    python --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python is not installed.
        echo.
        echo Please install Python 3.10 from:
        echo   https://www.python.org/downloads/
        echo.
        echo After installing Python, run this script again.
        pause
        exit /b 1
    )

    echo Python found:
    python --version
    echo.

    REM Create modules_venv next to exe if needed
    if not exist "%~dp0modules_venv\" (
        echo Creating modules environment...
        python -m venv "%~dp0modules_venv"
        if errorlevel 1 (
            echo.
            echo ERROR: Failed to create virtual environment.
            pause
            exit /b 1
        )
        echo Upgrading pip...
        "%~dp0modules_venv\Scripts\python" -m pip install --upgrade pip
        echo.
    )

    REM Find install_modules.py (PyInstaller puts it in _internal/tools/)
    set "SCRIPT=%~dp0_internal\tools\install_modules.py"
    if not exist "%SCRIPT%" set "SCRIPT=%~dp0tools\install_modules.py"
    if not exist "%SCRIPT%" (
        echo ERROR: install_modules.py not found.
        pause
        exit /b 1
    )

    "%~dp0modules_venv\Scripts\python" "%SCRIPT%" %*
) else (
    REM === SOURCE CONTEXT ===
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
)

echo.
pause
endlocal
exit /b 0
