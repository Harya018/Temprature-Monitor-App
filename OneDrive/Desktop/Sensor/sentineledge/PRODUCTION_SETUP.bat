@echo off
setlocal EnableDelayedExpansion
title SentinelEdge — Production Setup
color 0A
cls

:: ============================================================
::  SentinelEdge — Production Service Installer
::  Run ONCE as Administrator on the target machine.
::  Do NOT hardcode any path — %~dp0 detects install location.
:: ============================================================

:: Auto-detect install directory (always ends with \)
SET INSTALL_DIR=%~dp0

echo ============================================================
echo   SentinelEdge — Production Service Installer
echo   Install directory: %INSTALL_DIR%
echo ============================================================
echo.

:: ── Admin check ──────────────────────────────────────────────
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This script must be run as Administrator.
    echo         Right-click PRODUCTION_SETUP.bat and choose
    echo         "Run as administrator", then try again.
    echo.
    pause
    exit /b 1
)
echo [OK] Running as Administrator.
echo.

:: ── Check nssm.exe ───────────────────────────────────────────
if not exist "%INSTALL_DIR%nssm.exe" (
    echo [ERROR] nssm.exe not found in %INSTALL_DIR%
    echo         nssm.exe must be placed in the sentineledge folder.
    echo         Download from: https://nssm.cc/release/nssm-2.24.zip
    echo         Extract: nssm-2.24\win64\nssm.exe
    echo.
    pause
    exit /b 1
)
echo [OK] nssm.exe found.
echo.

:: ── Check venv ───────────────────────────────────────────────
if not exist "%INSTALL_DIR%venv\Scripts\uvicorn.exe" (
    echo [ERROR] Python venv not found at %INSTALL_DIR%venv\
    echo         Please set up the Python virtual environment first:
    echo           cd %INSTALL_DIR%
    echo           python -m venv venv
    echo           venv\Scripts\pip install -r backend\requirements.txt
    echo.
    pause
    exit /b 1
)
echo [OK] Python venv found.
echo.

:: ── Check Node / npm ─────────────────────────────────────────
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found. Install Node.js from https://nodejs.org
    echo.
    pause
    exit /b 1
)
echo [OK] npm found.
echo.

:: ── Check .env.production ────────────────────────────────────
if not exist "%INSTALL_DIR%.env.production" (
    echo [WARNING] .env.production not found.
    echo           Copying .env.development as starting point...
    copy "%INSTALL_DIR%.env.development" "%INSTALL_DIR%.env.production" >nul
    echo           IMPORTANT: Edit .env.production before going live:
    echo             - Set ADMIN_PASSWORD to a strong hashed password
    echo             - Set SMTP_USER / SMTP_PASSWORD for email alerts
    echo             - Set DEMO_MODE=true if no USB sensor is connected
    echo             - Set DATABASE_URL for your PostgreSQL instance
    echo.
) else (
    echo [OK] .env.production found.
    :: Warn if ADMIN_PASSWORD is blank
    findstr /i "ADMIN_PASSWORD=$" "%INSTALL_DIR%.env.production" >nul 2>&1
    if not errorlevel 1 (
        echo [WARNING] ADMIN_PASSWORD is empty in .env.production.
        echo           Set it before exposing to a network.
    )
    echo.
)

:: ── Create logs directory ─────────────────────────────────────
if not exist "%INSTALL_DIR%logs" (
    mkdir "%INSTALL_DIR%logs"
    echo [OK] Created logs\ directory.
) else (
    echo [OK] logs\ directory already exists.
)
echo.

:: ── Step 1: Build frontend ────────────────────────────────────
echo [1/4] Building frontend for production...
echo       (This may take 30-60 seconds)
echo.
cd /d "%INSTALL_DIR%frontend-web"
call npm install --silent
if errorlevel 1 (
    echo [ERROR] npm install failed. Check Node.js installation.
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo [ERROR] npm run build failed. Check frontend-web\ for errors.
    pause
    exit /b 1
)
cd /d "%INSTALL_DIR%"
echo.
echo [OK] Frontend built — output in backend\static\
echo.

:: ── Step 2: Remove existing service if present ───────────────
echo [2/4] Checking for existing SentinelEdge-Backend service...
sc query SentinelEdge-Backend >nul 2>&1
if not errorlevel 1 (
    echo       Existing service found — removing it first...
    "%INSTALL_DIR%nssm.exe" stop SentinelEdge-Backend >nul 2>&1
    "%INSTALL_DIR%nssm.exe" remove SentinelEdge-Backend confirm >nul 2>&1
    echo       Old service removed.
) else (
    echo       No existing service found.
)
echo.

:: ── Step 3: Install Windows service ──────────────────────────
echo [3/4] Installing SentinelEdge-Backend Windows service...

SET UVICORN_EXE=%INSTALL_DIR%venv\Scripts\uvicorn.exe
SET PYTHONPATH_VAL=%INSTALL_DIR%;%INSTALL_DIR%backend
SET LOG_FILE=%INSTALL_DIR%logs\backend_service.log

"%INSTALL_DIR%nssm.exe" install SentinelEdge-Backend "%UVICORN_EXE%"
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend AppParameters "backend.main:app --host 0.0.0.0 --port 5000"
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend AppDirectory "%INSTALL_DIR%"
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend AppEnvironmentExtra "APP_ENV=production" "PYTHONPATH=%PYTHONPATH_VAL%"
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend Start SERVICE_AUTO_START
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend AppRestartDelay 5000
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend AppStdout "%LOG_FILE%"
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend AppStderr "%LOG_FILE%"
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend AppStdoutCreationDisposition 4
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend AppStderrCreationDisposition 4
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend DependOnService postgresql-x64-16
"%INSTALL_DIR%nssm.exe" set SentinelEdge-Backend Description "SentinelEdge IoT temperature monitoring backend (FastAPI/uvicorn)"

echo [OK] Service installed.
echo.

:: ── Step 4: Start the service ─────────────────────────────────
echo [4/4] Starting SentinelEdge-Backend service...
"%INSTALL_DIR%nssm.exe" start SentinelEdge-Backend
timeout /t 5 /nobreak >nul

sc query SentinelEdge-Backend | findstr /i "RUNNING" >nul
if errorlevel 1 (
    echo [WARNING] Service may still be starting up.
    echo           Check status with: PRODUCTION_STATUS.bat
    echo           Check logs at: %LOG_FILE%
) else (
    echo [OK] Service is RUNNING.
)
echo.

:: ── Open browser ──────────────────────────────────────────────
start http://localhost:5000
echo.

echo ============================================================
echo   SentinelEdge is now installed as a Windows Service.
echo.
echo   It will start automatically every time Windows boots.
echo   Access the dashboard at: http://localhost:5000
echo.
echo   Service name : SentinelEdge-Backend
echo   Log file     : %INSTALL_DIR%logs\backend_service.log
echo.
echo   To check status : run PRODUCTION_STATUS.bat
echo   To uninstall    : run PRODUCTION_REMOVE.bat as Administrator
echo ============================================================
echo.
pause
endlocal
