@echo off
:: ============================================================
::  SentinelEdge — Install Auto-Start (Task Scheduler)
::
::  Run this as Administrator to register the server
::  to start automatically at every Windows boot.
::
::  Right-click → Run as Administrator
:: ============================================================

setlocal

set "ROOT=C:\Users\harya\OneDrive\Desktop\Sensor\sentineledge"
set "SCRIPT=%ROOT%\start_server.bat"
set "TASK_NAME=SentinelEdge Server"

echo.
echo  =====================================================
echo   SentinelEdge Auto-Start Installer
echo  =====================================================
echo.

:: ── Check for Administrator privileges ──────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] This script must be run as Administrator.
    echo.
    echo  Right-click install_autostart.bat and select
    echo  "Run as administrator", then try again.
    echo.
    pause
    exit /b 1
)

:: ── Verify start_server.bat exists ──────────────────────────────────────────
if not exist "%SCRIPT%" (
    echo  [ERROR] start_server.bat not found at:
    echo  %SCRIPT%
    echo.
    echo  Make sure all SentinelEdge files are in:
    echo  %ROOT%
    echo.
    pause
    exit /b 1
)

echo  Installing Task Scheduler entry...
echo  Task name : %TASK_NAME%
echo  Script    : %SCRIPT%
echo  Trigger   : At system startup
echo  User      : SYSTEM
echo.

:: ── Delete old task if it exists (ignore error if not found) ─────────────────
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: ── Create new task ──────────────────────────────────────────────────────────
schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%SCRIPT%\"" ^
    /sc onstart ^
    /ru SYSTEM ^
    /rl HIGHEST ^
    /delay 0000:30 ^
    /f

if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Failed to create scheduled task.
    echo  Make sure you are running as Administrator.
    echo.
    pause
    exit /b 1
)

:: ── Set working directory for the task via XML update ────────────────────────
:: schtasks /create doesn't support /sd directly for SYSTEM tasks,
:: so we patch the working directory with PowerShell after creation.
powershell -NoProfile -Command ^
    "$t = Get-ScheduledTask -TaskName '%TASK_NAME%'; ^
     $t.Actions[0].WorkingDirectory = '%ROOT%'; ^
     Set-ScheduledTask -TaskName '%TASK_NAME%' -Action $t.Actions" >nul 2>&1

echo.
echo  =====================================================
echo   SUCCESS!
echo  =====================================================
echo.
echo   SentinelEdge Server has been registered to start
echo   on boot automatically.
echo.
echo   To verify: Restart your PC, then open:
echo   http://localhost:5000/api/health
echo.
echo   To remove auto-start at any time, double-click:
echo   uninstall_autostart.bat
echo.
echo  =====================================================
echo.
pause
