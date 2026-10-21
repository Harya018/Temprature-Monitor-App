@echo off
title SentinelEdge - standard Super Admin password
cd /d "%~dp0..\backend"
echo Sets this PC's Super Admin back to the STANDARD Super Admin password
echo (the same on every SentinelEdge PC). Company admins are not changed.
echo.
set "PYEXE=python"
if exist "..\python_path.txt" set /p PYEXE=<"..\python_path.txt"
if /i not "%PYEXE%"=="python" if not exist "%PYEXE%" set "PYEXE=python"
"%PYEXE%" reset_superadmin_password.py
echo.
pause
