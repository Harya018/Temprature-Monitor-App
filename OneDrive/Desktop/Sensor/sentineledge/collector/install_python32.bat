@echo off
echo ============================================================
echo  Install Python 3.12 32-bit to C:\Python312-32
echo ============================================================
echo.
echo  This script installs the official Python x86 installer silently.
echo  It does NOT touch the existing 64-bit Python.
echo  It does NOT modify the system PATH.
echo.

set INSTALLER=%~dp0python-3.12.10.exe
set INSTALL_DIR=C:\Python312-32

if not exist "%INSTALLER%" (
    echo ERROR: Installer not found at: %INSTALLER%
    echo.
    echo Please download the 32-bit installer first:
    echo   URL: https://www.python.org/downloads/release/python-31210/
    echo   File: "Windows installer (32-bit)" — filename: python-3.12.10.exe
    echo   Save to: %~dp0python-3.12.10.exe
    echo.
    pause
    exit /b 1
)

echo Installer found: %INSTALLER%
echo Install target : %INSTALL_DIR%
echo.

:: Verify installer is actually 32-bit by checking its size (rough sanity check)
for %%F in ("%INSTALLER%") do set SIZE=%%~zF
echo Installer size : %SIZE% bytes
echo.

echo Installing Python 3.12 32-bit...
echo (This may take 30-60 seconds)
echo.

"%INSTALLER%" /quiet ^
    InstallAllUsers=0 ^
    TargetDir=%INSTALL_DIR% ^
    PrependPath=0 ^
    Include_launcher=0 ^
    Include_test=0 ^
    Include_doc=0 ^
    Include_dev=1 ^
    Include_pip=1 ^
    SimpleInstall=1

if errorlevel 1 (
    echo.
    echo ERROR: Installation failed with exit code %errorlevel%
    echo Try running this script as Administrator.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Verifying installation...
echo ============================================================
echo.

if not exist "%INSTALL_DIR%\python.exe" (
    echo ERROR: python.exe not found at %INSTALL_DIR%\python.exe
    echo Installation may have failed or used a different path.
    pause
    exit /b 1
)

echo Python executable:
%INSTALL_DIR%\python.exe -c "import sys; print(' ', sys.executable)"

echo.
echo Architecture:
%INSTALL_DIR%\python.exe -c "import platform, struct; print('  platform.architecture():', platform.architecture()); print('  pointer size (bits):', struct.calcsize('P')*8)"

echo.
echo Version:
%INSTALL_DIR%\python.exe --version

echo.
echo ============================================================
if exist "%INSTALL_DIR%\python.exe" (
    %INSTALL_DIR%\python.exe -c "import struct; exit(0 if struct.calcsize('P')*8 == 32 else 1)" 2>nul
    if errorlevel 1 (
        echo  WARNING: Installed Python does NOT appear to be 32-bit.
        echo  You may have downloaded the AMD64 installer by mistake.
        echo  Please download the "Windows installer (32-bit^)" from python.org.
    ) else (
        echo  32-bit Python confirmed at %INSTALL_DIR%\python.exe
        echo.
        echo  Next step: run setup_32bit_env.bat to create the collector venv.
    )
)
echo ============================================================
echo.
pause
