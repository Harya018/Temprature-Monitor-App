@echo off
setlocal
title SentinelEdge — Service Status
cls

:: ============================================================
::  SentinelEdge — Production Service Status
::  No Administrator rights required.
:: ============================================================

SET INSTALL_DIR=%~dp0
SET LOG_FILE=%INSTALL_DIR%logs\backend_service.log

echo ============================================================
echo   SentinelEdge — Service Status
echo ============================================================
echo.

:: ── Service status ────────────────────────────────────────────
echo [Service: SentinelEdge-Backend]
sc query SentinelEdge-Backend >nul 2>&1
if errorlevel 1 (
    echo   Status : NOT INSTALLED
    echo   Run PRODUCTION_SETUP.bat as Administrator to install.
) else (
    sc query SentinelEdge-Backend | findstr /i "STATE"
    echo.

    :: Check if it's actually running
    sc query SentinelEdge-Backend | findstr /i "RUNNING" >nul
    if errorlevel 1 (
        echo   [WARNING] Service is not in RUNNING state.
        echo   To start:   sc start SentinelEdge-Backend
        echo   To diagnose: check the log below.
    ) else (
        echo   [OK] Service is running normally.
        echo   Dashboard: http://localhost:5000
    )
)
echo.

:: ── API health check ──────────────────────────────────────────
echo [API Health: http://localhost:5000/api/health]
powershell -NoProfile -Command ^
    "try { $r = Invoke-WebRequest -Uri 'http://localhost:5000/api/health' -UseBasicParsing -TimeoutSec 4; $r.Content } catch { '[WARN] API not responding — service may still be starting up' }"
echo.

:: ── Last 30 lines of log ──────────────────────────────────────
echo [Last 30 lines of log: %LOG_FILE%]
echo ────────────────────────────────────────────────────────────
if exist "%LOG_FILE%" (
    powershell -NoProfile -Command "Get-Content '%LOG_FILE%' -Tail 30"
) else (
    echo   Log file not found. Service may not have started yet.
    echo   Expected at: %LOG_FILE%
)
echo ────────────────────────────────────────────────────────────
echo.
pause
endlocal
