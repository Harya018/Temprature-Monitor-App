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
echo [1/4] Checking PostgreSQL...
sc query postgresql-x64-16 | findstr /i "RUNNING" >nul
if errorlevel 1 (
    echo       PostgreSQL not running — starting it...
    net start postgresql-x64-16
    timeout /t 3 /nobreak >nul
) else (
    echo       PostgreSQL is already running.
)
echo.

:: Step 2 — Start Backend
echo [2/4] Starting Backend (FastAPI on port 5000)...
set APP_ENV=development
set PYTHONPATH=%CD%;%CD%\backend
call venv\Scripts\activate
start "SentinelEdge Backend" cmd /k "title SentinelEdge Backend && uvicorn backend.main:app --host 0.0.0.0 --port 5000"
echo       Backend starting...
timeout /t 4 /nobreak >nul
echo.

:: Step 3 — Start Frontend
echo [3/4] Starting Frontend (Vite on port 5173)...
cd frontend-web
start "SentinelEdge Frontend" cmd /k "title SentinelEdge Frontend && npm run dev"
cd ..
echo       Frontend starting...
timeout /t 4 /nobreak >nul
echo.

:: Step 4 — Open Browser
echo [4/4] Opening dashboard in browser...
start http://localhost:5173
echo.

echo ==========================================
echo     SENTINELEDGE IS RUNNING
echo.
echo     Dashboard  : http://localhost:5173
echo     Backend API: http://localhost:5000
echo     API Docs   : http://localhost:5000/docs
echo.
echo     Two terminal windows are open:
echo     - "SentinelEdge Backend"
echo     - "SentinelEdge Frontend"
echo.
echo     To STOP everything run STOP.bat
echo ==========================================
echo.
pause
