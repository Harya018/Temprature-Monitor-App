@echo off
title SentinelEdge — Stopping...
color 0C
cls

echo ==========================================
echo        SENTINELEDGE - SHUTTING DOWN
echo ==========================================
echo.

echo [1/2] Stopping Backend (uvicorn)...
taskkill /F /IM uvicorn.exe /T >nul 2>&1
echo       Backend stopped.
echo.

echo [2/2] Stopping Frontend (vite/node)...
taskkill /FI "WINDOWTITLE eq SentinelEdge Frontend" /F /T >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173"') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo       Frontend stopped.
echo.

echo ==========================================
echo     SENTINELEDGE STOPPED SUCCESSFULLY
echo ==========================================
echo.
pause
