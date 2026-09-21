@echo off
title SentinelEdge Watchdog
color 0A
cls

echo ============================================
echo  SentinelEdge Watchdog Starting...
echo ============================================
echo.

cd /d "%~dp0"

:: Step 1 — Ensure PostgreSQL is running
echo [1/3] Checking PostgreSQL...
sc query postgresql-x64-16 | findstr /i "RUNNING" >nul
if errorlevel 1 (
    echo       Starting PostgreSQL...
    net start postgresql-x64-16
    timeout /t 3 /nobreak >nul
) else (
    echo       PostgreSQL already running.
)
echo.

:: Step 2 — Kill anything on port 5000
echo [2/3] Clearing port 5000...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-NetTCPConnection -LocalPort 5000 -EA SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 4 } | ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }"
timeout /t 2 /nobreak >nul
echo       Done.
echo.

:: Step 3 — Start with auto-restart watchdog loop
echo [3/3] Starting SentinelEdge with watchdog (auto-restarts on crash)...
echo       Close this window to stop.
echo.

set PYTHONPATH=%~dp0;%~dp0backend
call venv\Scripts\activate

:loop
echo [%date% %time%] Starting SentinelEdge...
uvicorn backend.main:app --host 0.0.0.0 --port 5000
echo.
echo [%date% %time%] Server stopped or crashed. Restarting in 5 seconds...
echo       (Close this window to stop the restart loop)
timeout /t 5 /nobreak >nul
goto loop
