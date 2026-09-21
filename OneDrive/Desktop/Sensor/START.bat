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

:: Step 1 — Check/Start PostgreSQL (try both service names)
echo [1/3] Checking PostgreSQL...
sc query postgresql-x64-16 | findstr /i "RUNNING" >nul 2>&1
if not errorlevel 1 (
    echo       PostgreSQL is already running.
    goto kill_old
)
sc query postgresql-16 | findstr /i "RUNNING" >nul 2>&1
if not errorlevel 1 (
    echo       PostgreSQL is already running.
    goto kill_old
)

echo       PostgreSQL not running - starting it...
net start postgresql-x64-16 >nul 2>&1
if errorlevel 1 (
    net start postgresql-16 >nul 2>&1
)
timeout /t 3 /nobreak >nul
echo       PostgreSQL started.

:kill_old
echo.

:: Step 1b — Kill any old backend on port 5000
echo [1b] Stopping any old backend on port 5000...
if exist backend\server.pid (
    set /p OLD_PID=<backend\server.pid
    taskkill /f /t /pid %OLD_PID% >nul 2>&1
    del backend\server.pid >nul 2>&1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-NetTCPConnection -LocalPort 5000 -EA SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 4 } | ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }"
timeout /t 2 /nobreak >nul
echo       Done.
echo.

:: Step 2 — Start Backend
echo [2/3] Starting Backend (FastAPI on port 5000)...
start "SentinelEdge Backend" cmd /k "title SentinelEdge Backend && cd /d "%~dp0sentineledge\backend" && python -m uvicorn main:app --host 0.0.0.0 --port 5000"
echo       Waiting for server to be ready...

:: Poll /api/health every second until ready (max 45s), then open browser
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$max=45; $i=0; do { Start-Sleep -Seconds 1; $i++; try { $r=(Invoke-WebRequest -Uri 'http://localhost:5000/api/health' -TimeoutSec 1 -UseBasicParsing -EA Stop).StatusCode } catch { $r=0 }; if ($r -eq 200) { Write-Host ('      Ready in ' + $i + 's'); break } else { Write-Host -NoNewline '.' } } while ($i -lt $max); if ($i -ge $max) { Write-Host ''; Write-Host '      Timed out — opening anyway.' }"
echo.

:: Step 3 — Open Browser
echo [3/3] Opening dashboard in browser...
start http://localhost:5000
echo.

echo ==========================================
echo     SENTINELEDGE IS RUNNING
echo.
echo     Dashboard  : http://localhost:5000
echo     API Docs   : http://localhost:5000/docs
echo.
echo     To STOP everything run STOP.bat
echo ==========================================
echo.
pause
