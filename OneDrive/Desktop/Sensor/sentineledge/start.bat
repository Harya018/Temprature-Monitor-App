@echo off
title SentinelEdge — Starting...
color 0A
cls

echo ==========================================
echo        SENTINELEDGE - STARTING UP
echo ==========================================
echo.

:: Must run from sentineledge\ directory
cd /d "%~dp0"

:: Step 1 — Check PostgreSQL
echo [1/3] Checking PostgreSQL...
sc query postgresql-x64-16 | findstr /i "RUNNING" >nul
if errorlevel 1 (
    echo       PostgreSQL not running — starting it...
    net start postgresql-x64-16
    timeout /t 3 /nobreak >nul
) else (
    echo       PostgreSQL is already running.
)
echo.

:: Step 1b — Kill any old backend on port 5000
echo [1b] Stopping any running backend on port 5000...

:: Kill 0: use PID file written by the server itself (most reliable)
if exist backend\server.pid (
    set /p OLD_PID=<backend\server.pid
    echo       Killing previous server PID %OLD_PID%...
    taskkill /f /t /pid %OLD_PID% >nul 2>&1
    del backend\server.pid >nul 2>&1
) else (
    echo       No server.pid file found — scanning for other servers...
)

:: Kill 1: by window title (catches cmd.exe + its uvicorn child)
taskkill /f /t /fi "WINDOWTITLE eq SentinelEdge Backend" >nul 2>&1

:: Kill 2: uvicorn.exe directly (in case it was installed as a standalone exe)
taskkill /f /im uvicorn.exe >nul 2>&1

:: Kill 3: python.exe processes whose command line mentions uvicorn
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -match 'uvicorn' } | ForEach-Object { Write-Host ('  Killing python.exe PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue } } catch {}"

timeout /t 3 /nobreak >nul

:: Kill 4: anything still on port 5000 regardless of process name or TCP state
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Get-NetTCPConnection -LocalPort 5000 -EA SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 4 } | ForEach-Object { Write-Host ('  Force-killing PID ' + $_); Stop-Process -Id $_ -Force -EA SilentlyContinue } } catch {}"

:: Wait for OS to release the socket
timeout /t 8 /nobreak >nul

:: Confirm port is free
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c = Get-NetTCPConnection -LocalPort 5000 -EA SilentlyContinue; if ($c) { $p = Get-Process -Id $c[0].OwningProcess -EA SilentlyContinue; Write-Host ('  WARNING: port 5000 still held by ' + $p.Name + ' PID ' + $c[0].OwningProcess) } else { Write-Host '  Port 5000 is free — starting server.' }"
echo.

:: Step 2 — Start Backend
echo [2/3] Starting Backend (FastAPI on port 5000)...
set APP_ENV=development
set PYTHONPATH=%CD%;%CD%\backend
call venv\Scripts\activate
start "SentinelEdge Backend" cmd /k "title SentinelEdge Backend && uvicorn backend.main:app --host 0.0.0.0 --port 5000"
echo       Backend starting...
timeout /t 4 /nobreak >nul
echo.

:: Step 3 — Open Browser
:: Built frontend is served by FastAPI at port 5000 (backend/static/)
echo [3/3] Opening dashboard...
start http://localhost:5000
echo.

echo ==========================================
echo     SENTINELEDGE IS RUNNING
echo.
echo     Dashboard  : http://localhost:5000
echo     API Docs   : http://localhost:5000/docs
echo.
echo     To STOP, close the "SentinelEdge Backend" terminal window.
echo ==========================================
echo.
pause
