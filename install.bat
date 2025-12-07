@echo off
REM Installation script for index.life local application (Windows)
REM Now with automatic Python installation!

echo ========================================
echo   index.life - Installation
echo ========================================
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed. Starting automatic installation...
    echo.
    echo This will download and install Python 3.12 automatically.
    echo Installation will take a few minutes.
    echo.
    set /p CONFIRM="Continue with automatic Python installation? (Y/N): "
    if /i not "%CONFIRM%"=="Y" (
        echo.
        echo Installation cancelled. Please install Python manually from:
        echo https://www.python.org/downloads/
        pause
        exit /b 1
    )

    call :install_python
    if errorlevel 1 (
        echo.
        echo ERROR: Python installation failed
        echo Please install Python manually from:
        echo https://www.python.org/downloads/
        pause
        exit /b 1
    )
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
exit /b 0

REM ========================================
REM Function: Install Python automatically
REM ========================================
:install_python
    echo.
    echo [1/4] Detecting system architecture...

    REM Detect architecture (64-bit or 32-bit)
    set ARCH=x86
    if "%PROCESSOR_ARCHITECTURE%"=="AMD64" set ARCH=x64
    if "%PROCESSOR_ARCHITEW6432%"=="AMD64" set ARCH=x64

    echo System architecture: %ARCH%
    echo.

    REM Set Python download URL (Python 3.12.0 - latest stable)
    if "%ARCH%"=="x64" (
        set PYTHON_URL=https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe
        set INSTALLER_NAME=python-3.12.0-amd64.exe
    ) else (
        set PYTHON_URL=https://www.python.org/ftp/python/3.12.0/python-3.12.0.exe
        set INSTALLER_NAME=python-3.12.0.exe
    )

    echo [2/4] Downloading Python 3.12...
    echo URL: %PYTHON_URL%
    echo.
    echo Please wait, this may take a few minutes...

    REM Download using PowerShell
    powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%INSTALLER_NAME%'}"

    if not exist "%INSTALLER_NAME%" (
        echo ERROR: Failed to download Python installer
        exit /b 1
    )

    echo Download completed successfully!
    echo.

    echo [3/4] Installing Python...
    echo This will install Python to your user directory.
    echo.

    REM Install Python silently with options:
    REM - PrependPath=1: Add to PATH
    REM - Include_test=0: Don't install tests
    REM - SimpleInstall=1: Simple installation
    REM - InstallAllUsers=0: Install for current user only (no admin rights needed)
    REM - Include_pip=1: Install pip
    REM - Include_launcher=1: Install py launcher

    "%INSTALLER_NAME%" /quiet PrependPath=1 Include_test=0 SimpleInstall=1 InstallAllUsers=0 Include_pip=1 Include_launcher=1

    if errorlevel 1 (
        echo ERROR: Python installation failed
        del "%INSTALLER_NAME%"
        exit /b 1
    )

    echo Installation completed!
    echo.

    echo [4/4] Cleaning up...
    del "%INSTALLER_NAME%"
    echo.

    echo Python has been installed successfully!
    echo.
    echo IMPORTANT: Please close this window and run install.bat again
    echo to continue with the installation.
    echo.
    pause
    exit /b 0

goto :eof
