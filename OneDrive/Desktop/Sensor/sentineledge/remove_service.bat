@echo off
setlocal

set SERVICE_NAME=SentinelEdge

where nssm >nul 2>&1
if %errorlevel%==0 (
    set NSSM=nssm
) else if exist "%~dp0nssm.exe" (
    set NSSM=%~dp0nssm.exe
) else (
    echo ERROR: nssm.exe not found.
    pause
    exit /b 1
)

sc query %SERVICE_NAME% >nul 2>&1
if not %errorlevel%==0 (
    echo Service %SERVICE_NAME% is not installed.
    pause
    exit /b 0
)

echo Stopping %SERVICE_NAME%...
%NSSM% stop %SERVICE_NAME% 2>nul

echo Removing service...
%NSSM% remove %SERVICE_NAME% confirm

echo Done.
pause
endlocal
