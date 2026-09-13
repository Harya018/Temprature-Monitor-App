@echo off
:: ============================================================
::  SentinelEdge — Remove Auto-Start
::
::  Removes the Task Scheduler entry so the server will
::  no longer start automatically on boot.
::
::  Right-click → Run as Administrator
:: ============================================================

setlocal

set "TASK_NAME=SentinelEdge Server"

echo.
echo  =====================================================
echo   SentinelEdge Auto-Start Removal
echo  =====================================================
echo.

:: ── Check for Administrator privileges ──────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] This script must be run as Administrator.
    echo.
    echo  Right-click uninstall_autostart.bat and select
    echo  "Run as administrator", then try again.
    echo.
    pause
    exit /b 1
)

:: ── Check if task exists ─────────────────────────────────────────────────────
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [INFO] No auto-start task found. Nothing to remove.
    echo.
    pause
    exit /b 0
)

:: ── Delete the task ──────────────────────────────────────────────────────────
echo  Removing scheduled task: %TASK_NAME%
echo.
schtasks /delete /tn "%TASK_NAME%" /f

if %errorlevel% neq 0 (
    echo  [ERROR] Failed to remove the task.
    echo  Make sure you are running as Administrator.
    echo.
    pause
    exit /b 1
)

echo.
echo  =====================================================
echo   SUCCESS!
echo  =====================================================
echo.
echo   SentinelEdge Server auto-start has been removed.
echo   The server will NO LONGER start automatically on boot.
echo.
echo   To re-enable auto-start, double-click:
echo   install_autostart.bat
echo.
echo   To start the server manually, double-click:
echo   start_server.bat
echo.
echo  =====================================================
echo.
pause
