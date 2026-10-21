@echo off
title SentinelEdge — Stopping...
color 0C
cls

echo ==========================================
echo        SENTINELEDGE - SHUTTING DOWN
echo ==========================================
echo.

cd /d "%~dp0sentineledge"

:: Step 1 — ProEasy collector first, so it doesn't log errors once the backend is gone.
:: (If killed this way the runtime cache is not released, but the collector
::  discards a stale SentinelEdgeCache and recreates it on its next start.)
echo [1/2] Stopping ProEasy collector...
taskkill /FI "WINDOWTITLE eq SentinelEdge ProEasy Collector*" /F /T >nul 2>&1
echo       Collector stopped.
echo.

:: Step 2 — FastAPI backend on port 5000 (same methods START.bat uses to clear old instances)
echo [2/2] Stopping backend (FastAPI on port 5000)...
:: Read the PID outside an ( ) block — inside one, %OLD_PID% expands before set /p runs
set "OLD_PID="
if exist backend\server.pid set /p OLD_PID=<backend\server.pid
if defined OLD_PID taskkill /f /t /pid %OLD_PID% >nul 2>&1
if exist backend\server.pid del backend\server.pid >nul 2>&1
taskkill /FI "WINDOWTITLE eq SentinelEdge Backend*" /F /T >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 5000 -State Listen -EA SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 4 } | ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }"
echo       Backend stopped.
echo.

:: PostgreSQL is left running on purpose — it is a system service shared with other tools.

echo ==========================================
echo     SENTINELEDGE STOPPED SUCCESSFULLY
echo ==========================================
echo.
pause
