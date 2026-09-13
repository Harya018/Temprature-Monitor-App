@echo off
setlocal
title SentinelEdge — Production Uninstaller
color 0C
cls

:: ============================================================
::  SentinelEdge — Production Service Uninstaller
::  Run as Administrator to stop and remove the service.
:: ============================================================

SET INSTALL_DIR=%~dp0

echo ============================================================
echo   SentinelEdge — Production Service Uninstaller
echo ============================================================
echo.

:: ── Admin check ──────────────────────────────────────────────
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This script must be run as Administrator.
    echo.
    pause
    exit /b 1
)

:: ── Check nssm.exe ───────────────────────────────────────────
if not exist "%INSTALL_DIR%nssm.exe" (
    echo [ERROR] nssm.exe not found in %INSTALL_DIR%
    echo         Cannot remove service without nssm.exe.
    echo.
    pause
    exit /b 1
)

:: ── Confirm ───────────────────────────────────────────────────
echo   This will STOP and REMOVE the SentinelEdge-Backend service.
echo   Log files and application data will NOT be deleted.
echo.
set /p CONFIRM="   Type YES to confirm: "
if /i not "%CONFIRM%"=="YES" (
    echo   Cancelled — no changes made.
    echo.
    pause
    exit /b 0
)
echo.

:: ── Stop service ──────────────────────────────────────────────
echo [1/2] Stopping SentinelEdge-Backend service...
sc query SentinelEdge-Backend >nul 2>&1
if errorlevel 1 (
    echo       Service not found — nothing to stop.
) else (
    "%INSTALL_DIR%nssm.exe" stop SentinelEdge-Backend
    timeout /t 3 /nobreak >nul
    echo [OK] Service stopped.
)
echo.

:: ── Remove service ────────────────────────────────────────────
echo [2/2] Removing SentinelEdge-Backend service...
sc query SentinelEdge-Backend >nul 2>&1
if errorlevel 1 (
    echo       Service already removed.
) else (
    "%INSTALL_DIR%nssm.exe" remove SentinelEdge-Backend confirm
    echo [OK] Service removed.
)
echo.

echo ============================================================
echo   SentinelEdge-Backend service has been removed.
echo.
echo   To reinstall, run PRODUCTION_SETUP.bat as Administrator.
echo ============================================================
echo.
pause
endlocal
