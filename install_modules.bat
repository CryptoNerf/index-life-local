@echo off
setlocal

if exist "venv\Scripts\python.exe" (
  set "PY=venv\Scripts\python.exe"
) else (
  call :ensure_python
  if errorlevel 1 (
    echo.
    echo ERROR: Python is required to install modules.
    pause
    exit /b 1
  )
  set "PY=python"
  if "%INDEXLIFE_MODULES_VENV%"=="" (
    set "INDEXLIFE_MODULES_VENV=modules_venv"
  )
)

%PY% tools\install_modules.py %*

echo.
pause
endlocal
exit /b 0

REM ========================================
REM Function: Ensure Python is installed
REM ========================================
:ensure_python
python --version >nul 2>&1
if not errorlevel 1 (
  exit /b 0
)

echo Python is not installed. Starting automatic installation...
echo.
echo This will download and install Python 3.10 automatically.
echo Installation will take a few minutes.
echo.

call :install_python
if errorlevel 1 (
  echo.
  echo ERROR: Python installation failed
  exit /b 1
)

echo.
echo Python has been installed successfully!
echo Please close this window and run install_modules.bat again.
echo.
pause
exit /b 1

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

    REM Set Python download URL (Python 3.10.13 - stable)
    if "%ARCH%"=="x64" (
        set PYTHON_URL=https://www.python.org/ftp/python/3.10.13/python-3.10.13-amd64.exe
        set INSTALLER_NAME=python-3.10.13-amd64.exe
    ) else (
        set PYTHON_URL=https://www.python.org/ftp/python/3.10.13/python-3.10.13.exe
        set INSTALLER_NAME=python-3.10.13.exe
    )

    echo [2/4] Downloading Python 3.10...
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

    exit /b 0
