@echo off
title SentinelEdge — Starting...
color 0A
cls

echo ==========================================
echo        SENTINELEDGE - STARTING UP
echo ==========================================
echo.

:: Move into the sentineledge folder
cd /d "%~dp0sentineledge"

:: Not set up yet on this PC? (no settings file) -> FIRST_TIME_SETUP.bat first
if not exist ".env.development" if not exist ".env" if not exist ".env.production" (
    echo  This PC is not set up yet. Double-click FIRST_TIME_SETUP.bat ^(next to START.bat^) first.
    echo.
    pause
    exit /b 1
)

:: The Python that FIRST_TIME_SETUP installed the libraries into (falls back to "python" on the PATH)
set "PYEXE=python"
if exist "python_path.txt" set /p PYEXE=<"python_path.txt"
if /i not "%PYEXE%"=="python" if not exist "%PYEXE%" set "PYEXE=python"
"%PYEXE%" -c "import fastapi, uvicorn, psycopg2" >nul 2>&1
if errorlevel 1 (
    echo  Python or its libraries were not found ^(%PYEXE%^).
    echo  Run FIRST_TIME_SETUP.bat ^(next to START.bat^) again, then START.bat.
    echo.
    pause
    exit /b 1
)

:: Step 1 — Check/Start PostgreSQL (any installed version: postgresql-x64-16, postgresql-x64-17, ...)
echo [1/4] Checking PostgreSQL...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = @(Get-Service 'postgresql*' -EA SilentlyContinue); if (-not $s) { exit 2 }; if ($s | Where-Object Status -eq 'Running') { exit 0 }; $s | ForEach-Object { try { Start-Service $_.Name -EA Stop } catch {} }; Start-Sleep 3; if (@(Get-Service 'postgresql*' | Where-Object Status -eq 'Running')) { exit 0 } else { exit 1 }"
set "PGSTATE=%errorlevel%"
if "%PGSTATE%"=="0" echo       PostgreSQL is running.
if "%PGSTATE%"=="2" (
    echo       PostgreSQL is not installed on this PC - run FIRST_TIME_SETUP.bat first.
    pause
    exit /b 1
)
if "%PGSTATE%"=="1" (
    echo       PostgreSQL is not running and could not be started from here.
    echo       Restart the PC ^(it starts with Windows^), or right-click START.bat and choose Run as administrator.
)

:kill_old
echo.

:: Step 1b — Kill any old backend on port 5000
echo [1b] Stopping any old backend on port 5000...
:: Read the PID outside an ( ) block — inside one, %OLD_PID% expands before set /p runs
set "OLD_PID="
if exist backend\server.pid set /p OLD_PID=<backend\server.pid
if defined OLD_PID taskkill /f /t /pid %OLD_PID% >nul 2>&1
if exist backend\server.pid del backend\server.pid >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-NetTCPConnection -LocalPort 5000 -EA SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 4 } | ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }"
timeout /t 2 /nobreak >nul
echo       Done.
echo.

:: Step 2 — Start Backend
echo [2/4] Starting Backend (FastAPI on port 5000)...
start "SentinelEdge Backend" cmd /k "title SentinelEdge Backend && cd /d "%~dp0sentineledge\backend" && "%PYEXE%" -m uvicorn main:app --host 0.0.0.0 --port 5000"
echo       Waiting for server to be ready...

:: Poll /api/health every second until ready (max 45s).
:: Single-line command — no ^ continuation. Uses exit 0 (not break) so PowerShell
:: actually terminates when 200 is received. [int] cast avoids StatusCode type mismatch.
powershell -NoProfile -ExecutionPolicy Bypass -Command "for ($i=1; $i -le 45; $i++) { Start-Sleep 1; try { if (([int](Invoke-WebRequest 'http://localhost:5000/api/health' -UseBasicParsing -TimeoutSec 3 -EA Stop).StatusCode) -eq 200) { Write-Host ('      [Backend] Ready in ' + $i + 's'); exit 0 } } catch {}; Write-Host -NoNewline '.' }; Write-Host ''; Write-Host '      Timed out — opening anyway.'"
echo.

:: Step 3 — Start ProEasy Collector
echo [3/4] ProEasy Collector...
echo.
set "COLL_DIR=%~dp0sentineledge\collector"
if not exist "%COLL_DIR%\venv32\Scripts\python.exe" (
    echo       Not installed on this PC - live data comes from the Excel live reader.
    echo.
    goto collector_done
)
echo       [Collector] Checking collector directory...

set "COLL_PY=%COLL_DIR%\venv32\Scripts\python.exe"
set "COLL_SCRIPT=%COLL_DIR%\proserver_collector.py"

echo       [Collector] Working directory: %COLL_DIR%
echo       [Collector] Python: %COLL_PY%
echo       [Collector] Script: %COLL_SCRIPT%
echo.

if not exist "%COLL_DIR%\" (
    echo       [Collector] ERROR: Collector directory not found.
    goto collector_done
)

if not exist "%COLL_PY%" (
    echo       [Collector] ERROR: Python executable not found.
    goto collector_done
)

if not exist "%COLL_SCRIPT%" (
    echo       [Collector] ERROR: Collector script not found.
    goto collector_done
)

echo       [Collector] Python: FOUND
echo       [Collector] Script: FOUND
echo.
echo       [Collector] Starting ProEasy collector...
echo       [Collector] Expected backend endpoint: http://localhost:5000/api/collector/reading
echo.

start "SentinelEdge ProEasy Collector" /D "%COLL_DIR%" cmd /k "set PYTHONNET_RUNTIME=netfx&&echo PYTHONNET_RUNTIME=[%%PYTHONNET_RUNTIME%%]&&venv32\Scripts\python.exe proserver_collector.py --run"

echo       [Collector] Collector CMD window launched.
echo.

:collector_done
:open_browser
:: Step 4 — Open Browser
echo [4/4] Opening dashboard in browser...
start http://localhost:5000
echo.

echo ==========================================
echo     SENTINELEDGE IS RUNNING
echo.
echo     Dashboard  : http://localhost:5000
if exist "%~dp0sentineledge\collector\venv32\Scripts\python.exe" (echo     Collector  : ProEasy live collector) else (echo     Live data  : Excel live reader - set it up in Settings)
echo.
echo     To STOP everything run STOP.bat
echo ==========================================
echo.
pause
