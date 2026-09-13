@echo off
:: ============================================================
::  SentinelEdge — Server Status Check
::
::  Checks if the server is running on port 5000.
::  Offers to start it if not running.
::
::  Double-click to use.
:: ============================================================

setlocal

set "ROOT=C:\Users\harya\OneDrive\Desktop\Sensor\sentineledge"
set "SCRIPT=%ROOT%\start_server.bat"
set "PORT=5000"

echo.
echo  =====================================================
echo   SentinelEdge — Server Status Check
echo  =====================================================
echo.

:: ── Check if port 5000 is in use ─────────────────────────────────────────────
echo  Checking port %PORT%...
echo.

netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1

if %errorlevel% equ 0 (
    :: ── Port is in use = server is running ──────────────────────────────────
    echo  [OK]  SentinelEdge Server is RUNNING on port %PORT%
    echo.

    :: Show which PID is using the port
    echo  Process details:
    netstat -ano | findstr ":%PORT% " | findstr "LISTENING"
    echo.

    :: Try to show the health endpoint
    echo  Testing API health endpoint...
    powershell -NoProfile -Command ^
        "try { $r = Invoke-WebRequest -Uri 'http://localhost:%PORT%/api/health' -UseBasicParsing -TimeoutSec 3; Write-Host ('  [OK]  API responded: ' + $r.StatusCode) } catch { Write-Host '  [WARN] Port in use but API not responding yet (still starting up)' }"

    echo.
    echo  Dashboard : http://localhost:%PORT%
    echo  Health    : http://localhost:%PORT%/api/health
    echo.
) else (
    :: ── Port is NOT in use = server is not running ───────────────────────────
    echo  [--]  SentinelEdge Server is NOT running on port %PORT%
    echo.
    echo  Also checking for any uvicorn processes...
    tasklist | findstr /i "uvicorn" >nul 2>&1
    if %errorlevel% equ 0 (
        echo  [INFO] uvicorn process found (may be starting up or using a different port):
        tasklist | findstr /i "uvicorn"
        echo.
    ) else (
        echo  [INFO] No uvicorn process found.
        echo.
    )

    set /p START_NOW="  Do you want to start the server now? (Y/N): "
    echo.

    if /i "!START_NOW!"=="Y" (
        if exist "%SCRIPT%" (
            echo  Starting SentinelEdge Server...
            echo  (A new window will open for the server)
            echo.
            start "SentinelEdge Server" "%SCRIPT%"
            echo  [OK]  Server starting in a new window.
            echo.
            echo  Wait ~5 seconds then check:
            echo  http://localhost:%PORT%/api/health
        ) else (
            echo  [ERROR] start_server.bat not found at:
            echo  %SCRIPT%
        )
    ) else (
        echo  OK. Server was not started.
        echo  To start manually, double-click: start_server.bat
    )
)

echo.
echo  =====================================================
echo.
pause
