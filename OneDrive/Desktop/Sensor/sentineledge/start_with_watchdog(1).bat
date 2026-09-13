@echo off
title SentinelEdge Watchdog
echo ============================================
echo  SentinelEdge Watchdog Starting...
echo ============================================

:: Step 1 — Ensure PostgreSQL is running before starting backend
echo [1/3] Checking PostgreSQL...
net start postgresql-x64-16 2>nul
if %errorlevel%==0 (
    echo       PostgreSQL started.
) else (
    echo       PostgreSQL already running.
)

:: Wait 3 seconds for PostgreSQL to be fully ready
timeout /t 3 /nobreak >nul

:: Step 2 — Kill anything on port 5000 (stale process from previous crash)
echo [2/3] Clearing port 5000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000 "') do (
    taskkill /PID %%a /F 2>nul
)
timeout /t 1 /nobreak >nul

:: Step 3 — Start SentinelEdge with crash recovery loop
echo [3/3] Starting SentinelEdge server with watchdog...
echo       Server will auto-restart on crash.
echo       Close this window to stop the server.
echo.

:loop
echo [%date% %time%] Starting SentinelEdge...
SET PYTHONPATH=%~dp0backend
cd /d %~dp0
call venv\Scripts\uvicorn backend.main:app --host 0.0.0.0 --port 5000

echo.
echo [%date% %time%] Server stopped or crashed. Restarting in 5 seconds...
echo       (Close this window to stop restart loop)
timeout /t 5 /nobreak >nul
goto loop
