@echo off
title SentinelEdge Server
color 0A
cls

echo ================================================
echo   SentinelEdge IoT Server  (port 5000)
echo ================================================
echo.

cd /d "%~dp0"

:: Kill any stale process on port 5000
echo [*] Freeing port 5000...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-NetTCPConnection -LocalPort 5000 -EA SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 4 } | ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }"
timeout /t 1 /nobreak >nul

echo [*] Starting server...
echo [*] Dashboard: http://localhost:5000
echo [*] Press Ctrl+C to stop.
echo.

set PYTHONPATH=%CD%;%CD%\backend
call venv\Scripts\activate
uvicorn backend.main:app --host 0.0.0.0 --port 5000 --app-dir .

echo.
echo [!] Server stopped.
pause
