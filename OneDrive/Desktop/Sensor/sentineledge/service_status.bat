@echo off
set SERVICE_NAME=SentinelEdge
set LOG_DIR=%~dp0logs

echo === %SERVICE_NAME% Service Status ===
sc query %SERVICE_NAME%
if not %errorlevel%==0 (
    echo Service is not installed. Run setup_service.bat to install.
)

echo.
echo === Recent stdout (last 20 lines) ===
if exist "%LOG_DIR%\service_stdout.log" (
    powershell -NoProfile -Command "Get-Content '%LOG_DIR%\service_stdout.log' -Tail 20"
) else (
    echo ^(no stdout log yet^)
)

echo.
echo === Recent stderr (last 20 lines) ===
if exist "%LOG_DIR%\service_stderr.log" (
    powershell -NoProfile -Command "Get-Content '%LOG_DIR%\service_stderr.log' -Tail 20"
) else (
    echo ^(no stderr log yet^)
)

echo.
pause
