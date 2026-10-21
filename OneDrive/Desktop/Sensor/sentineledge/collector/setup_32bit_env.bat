@echo off
echo ============================================================
echo  SentinelEdge Collector — 32-bit venv Setup
echo ============================================================
echo.

set PY32=C:\Python312-32\python.exe
set VENV=%~dp0venv32

echo [1] Verifying 32-bit interpreter...
if not exist "%PY32%" (
    echo ERROR: %PY32% not found.
    echo Run install_python32.bat first.
    pause
    exit /b 1
)
"%PY32%" -c "import struct,sys; bits=struct.calcsize('P')*8; print('  executable:', sys.executable); print('  bits:', bits); exit(0 if bits==32 else 1)"
if errorlevel 1 (
    echo ERROR: %PY32% is not 32-bit. Aborting.
    pause
    exit /b 1
)
echo   OK — 32-bit confirmed.
echo.

echo [2] Creating virtual environment at: %VENV%
if exist "%VENV%" (
    echo   venv32 already exists — skipping creation.
) else (
    "%PY32%" -m venv "%VENV%"
    if errorlevel 1 (
        echo ERROR: venv creation failed.
        pause
        exit /b 1
    )
    echo   Created.
)
echo.

echo [3] Verifying venv architecture...
"%VENV%\Scripts\python.exe" -c "import platform,struct,sys; print('  executable:', sys.executable); print('  architecture:', platform.architecture()); print('  bits:', struct.calcsize('P')*8)"
echo.

echo [4] Upgrading pip...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip --quiet
echo   Done.
echo.

echo [5] Installing pythonnet==3.1.0 and requests...
"%VENV%\Scripts\python.exe" -m pip install pythonnet==3.1.0 requests
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)
echo.

echo [6] Verifying pythonnet import with PYTHONNET_RUNTIME=netfx...
set PYTHONNET_RUNTIME=netfx
"%VENV%\Scripts\python.exe" -c "import platform,struct; from importlib.metadata import version; print('  architecture:', platform.architecture()); print('  bits:', struct.calcsize('P')*8); print('  pythonnet:', version('pythonnet')); import clr, System; print('  clr OK — .NET runtime:', System.Environment.Version)"
if errorlevel 1 (
    echo ERROR: pythonnet verification failed. See above.
    pause
    exit /b 1
)
echo.

echo ============================================================
echo  Setup complete.
echo  Run the one-shot test with:
echo    run_collector_32.bat --test
echo ============================================================
pause
