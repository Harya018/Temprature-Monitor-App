@echo off
:: Runs the collector using the isolated 32-bit venv.
:: Usage:
::   run_collector_32.bat --test     (one-shot test)
::   run_collector_32.bat --inspect  (print DLL public methods)
::   run_collector_32.bat            (continuous mode)

setlocal

set SCRIPT_DIR=%~dp0

if not exist "%SCRIPT_DIR%venv32\Scripts\python.exe" (
    echo ERROR: 32-bit venv not found at %SCRIPT_DIR%venv32\
    echo.
    echo The venv32 environment must be created once on this machine.
    echo It is intentionally excluded from project sync (never copied via robocopy).
    echo.
    echo Run:  setup_32bit_env.bat
    echo Then retry this command.
    pause
    exit /b 1
)

:: Tell pythonnet 3.x to use .NET Framework (required for ProEasyDotNet)
set PYTHONNET_RUNTIME=netfx

"%SCRIPT_DIR%venv32\Scripts\python.exe" "%SCRIPT_DIR%proserver_collector.py" %*
