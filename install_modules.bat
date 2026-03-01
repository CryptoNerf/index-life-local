@echo off
setlocal EnableDelayedExpansion

REM Detect context: EXE distribution or source checkout
REM Bat may be at root (next to exe) or inside _internal/
set "EXE_DIR="
if exist "%~dp0index-life.exe" set "EXE_DIR=%~dp0"
if exist "%~dp0..\index-life.exe" set "EXE_DIR=%~dp0..\"

if defined EXE_DIR (
    REM === EXE CONTEXT ===
    echo ========================================
    echo   index.life - Module Installer
    echo ========================================
    echo.

    REM Find Python 3.10 specifically
    call :find_python310
    if not defined PY310 (
        echo Python 3.10 not found. Installing automatically...
        call :install_python310
        if errorlevel 1 (
            echo.
            echo ERROR: Failed to install Python 3.10.
            echo Please install manually from https://www.python.org/downloads/release/python-31013/
            pause
            exit /b 1
        )
        call :find_python310
    )

    if not defined PY310 (
        echo ERROR: Python 3.10 still not found after installation.
        echo Please restart this script or install Python 3.10 manually.
        pause
        exit /b 1
    )

    echo Using Python: !PY310!
    "!PY310!" --version
    echo.

    REM Create modules_venv next to exe if needed
    if not exist "%EXE_DIR%modules_venv\" (
        echo Creating modules environment...
        "!PY310!" -m venv "%EXE_DIR%modules_venv"
        if errorlevel 1 (
            echo.
            echo ERROR: Failed to create virtual environment.
            pause
            exit /b 1
        )
        echo.
    )

    REM Find install_modules.py
    set "SCRIPT=%EXE_DIR%_internal\tools\install_modules.py"
    if not exist "!SCRIPT!" set "SCRIPT=%EXE_DIR%tools\install_modules.py"
    if not exist "!SCRIPT!" (
        echo ERROR: install_modules.py not found.
        pause
        exit /b 1
    )

    "%EXE_DIR%modules_venv\Scripts\python" "!SCRIPT!" %*
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

REM ========================================
REM Function: Find Python 3.10 executable
REM Sets PY310 variable if found
REM ========================================
:find_python310
    set "PY310="
    set "_tmppy=%TEMP%\indexlife_py310.txt"

    REM Try py launcher first (most reliable on Windows)
    py -3.10 -c "import sys;print(sys.executable)" >"%_tmppy%" 2>nul
    if not errorlevel 1 (
        set /p PY310=<"%_tmppy%"
        del "%_tmppy%" 2>nul
        if defined PY310 exit /b 0
    )
    del "%_tmppy%" 2>nul

    REM Try common install paths
    if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
        set "PY310=%LocalAppData%\Programs\Python\Python310\python.exe"
        exit /b 0
    )
    if exist "C:\Python310\python.exe" (
        set "PY310=C:\Python310\python.exe"
        exit /b 0
    )
    if exist "C:\Program Files\Python310\python.exe" (
        set "PY310=C:\Program Files\Python310\python.exe"
        exit /b 0
    )

    REM Try python in PATH and check if it's 3.10
    python -c "import sys;exit(0 if sys.version_info[:2]==(3,10) else 1)" >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys;print(sys.executable)" >"%_tmppy%" 2>nul
        set /p PY310=<"%_tmppy%"
        del "%_tmppy%" 2>nul
        if defined PY310 exit /b 0
    )
    del "%_tmppy%" 2>nul

    exit /b 1

REM ========================================
REM Function: Download and install Python 3.10
REM ========================================
:install_python310
    echo.
    echo Downloading Python 3.10.13...

    set "ARCH=x86"
    if "%PROCESSOR_ARCHITECTURE%"=="AMD64" set "ARCH=x64"
    if "%PROCESSOR_ARCHITEW6432%"=="AMD64" set "ARCH=x64"

    if "%ARCH%"=="x64" (
        set "PY_URL=https://www.python.org/ftp/python/3.10.13/python-3.10.13-amd64.exe"
        set "PY_INSTALLER=python-3.10.13-amd64.exe"
    ) else (
        set "PY_URL=https://www.python.org/ftp/python/3.10.13/python-3.10.13.exe"
        set "PY_INSTALLER=python-3.10.13.exe"
    )

    powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '!PY_URL!' -OutFile '!PY_INSTALLER!'}"

    if not exist "!PY_INSTALLER!" (
        echo ERROR: Failed to download Python installer.
        exit /b 1
    )

    echo Installing Python 3.10 (this may take a minute)...
    "!PY_INSTALLER!" /quiet PrependPath=1 Include_test=0 InstallAllUsers=0 Include_pip=1 Include_launcher=1

    if errorlevel 1 (
        del "!PY_INSTALLER!" 2>nul
        echo ERROR: Python installation failed.
        exit /b 1
    )

    del "!PY_INSTALLER!" 2>nul
    echo Python 3.10 installed successfully!
    echo.

    REM Refresh PATH so we can find the new Python
    for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "PATH=%%B;%PATH%"

    exit /b 0
