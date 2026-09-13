@echo off
title SentinelEdge Server
color 0A

echo ================================================
echo   SentinelEdge IoT Server  (HTTPS port 5000)
echo ================================================
echo.

:: Move to the project root
cd /d "%~dp0"

:: Kill any stale process on port 5000
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    echo [*] Freeing port 5000 (PID %%a)...
    taskkill /PID %%a /F >nul 2>&1
)

echo [*] Starting server...
echo [*] Dashboard: http://localhost:5000
echo [*] Press Ctrl+C to stop.
echo.

uvicorn main:app ^
  --host 0.0.0.0 ^
  --port 5000 ^
  --app-dir backend ^
  
echo.
echo [!] Server stopped.
pause
