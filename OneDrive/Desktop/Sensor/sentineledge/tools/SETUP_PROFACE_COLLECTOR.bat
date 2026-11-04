@echo off
title SentinelEdge - set up the Pro-face live collector
:: For a PC where Pro-Server EX was installed after SentinelEdge (FIRST_TIME_SETUP does this by itself).
net session >nul 2>&1
if errorlevel 1 (
    echo Asking Windows for Administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo Setting up the Pro-face live collector (32-bit Python + libraries)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\setup_collector32.ps1"
if errorlevel 1 (echo. & echo  Setup failed - check the internet connection and run this file again.) else (echo. & echo  Done. Run STOP.bat and START.bat: the collector window starts with SentinelEdge.)
echo.
pause
