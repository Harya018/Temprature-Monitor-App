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
    goto backend
)
sc query postgresql-16 | findstr /i "RUNNING" >nul 2>&1
if not errorlevel 1 (
    echo       PostgreSQL is already running.
    goto backend
)

echo       PostgreSQL not running - starting it...
net start postgresql-x64-16 >nul 2>&1
if errorlevel 1 (
    net start postgresql-16 >nul 2>&1
)
timeout /t 3 /nobreak >nul
echo       PostgreSQL started.

:backend
echo.

:: Step 2 — Start Backend
echo [2/3] Starting Backend (FastAPI on port 5000)...
start "SentinelEdge Backend" cmd /k "title SentinelEdge Backend && cd /d "%~dp0sentineledge\backend" && python -m uvicorn main:app --host 0.0.0.0 --port 5000"
echo       Backend starting...
timeout /t 4 /nobreak >nul
echo.

:: Step 3 — Open Browser
echo [3/3] Opening dashboard in browser...
start http://localhost:5000
echo.

echo ==========================================
echo     SENTINELEDGE IS RUNNING
echo.
echo     Dashboard  : http://localhost:5000
echo     Backend API: http://localhost:5000
echo     API Docs   : http://localhost:5000/docs
echo.
echo     One terminal window is open:
echo     - "SentinelEdge Backend"
echo.
echo     To STOP everything run STOP.bat
echo ==========================================
echo.
pause
