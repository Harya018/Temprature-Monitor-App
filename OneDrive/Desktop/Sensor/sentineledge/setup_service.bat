@echo off
setlocal

set SERVICE_NAME=SentinelEdge
set PROJECT_DIR=%~dp0
set PYTHON_EXE=%PROJECT_DIR%venv\Scripts\python.exe
set LOG_DIR=%PROJECT_DIR%logs

:: Locate nssm — PATH, project root, or bail
where nssm >nul 2>&1
if %errorlevel%==0 (
    set NSSM=nssm
) else if exist "%PROJECT_DIR%nssm.exe" (
    set NSSM=%PROJECT_DIR%nssm.exe
) else (
    echo ERROR: nssm.exe not found.
    echo Download from https://nssm.cc/download or run install_service.ps1 ^(auto-downloads nssm^).
    pause
    exit /b 1
)

sc query %SERVICE_NAME% >nul 2>&1
if %errorlevel%==0 (
    echo Service %SERVICE_NAME% already exists. Run remove_service.bat first.
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo ERROR: Python not found at %PYTHON_EXE%
    echo Run: python -m venv venv   inside the sentineledge folder first.
    pause
    exit /b 1
)

echo Installing %SERVICE_NAME% Windows Service...

%NSSM% install    %SERVICE_NAME% "%PYTHON_EXE%" "-m uvicorn backend.main:app --host 0.0.0.0 --port 5000"
%NSSM% set        %SERVICE_NAME% AppDirectory         "%PROJECT_DIR%"
%NSSM% set        %SERVICE_NAME% AppEnvironmentExtra  "APP_ENV=production" "PYTHONPATH=%PROJECT_DIR%;%PROJECT_DIR%backend"
%NSSM% set        %SERVICE_NAME% AppStdout            "%LOG_DIR%\service_stdout.log"
%NSSM% set        %SERVICE_NAME% AppStderr            "%LOG_DIR%\service_stderr.log"
%NSSM% set        %SERVICE_NAME% AppRotateFiles       1
%NSSM% set        %SERVICE_NAME% AppRotateSeconds     86400
%NSSM% set        %SERVICE_NAME% AppRotateOnline      1
%NSSM% set        %SERVICE_NAME% Start                SERVICE_AUTO_START
%NSSM% set        %SERVICE_NAME% DisplayName          "SentinelEdge Monitoring Service"
%NSSM% set        %SERVICE_NAME% Description          "SentinelEdge IoT sensor monitoring backend"

echo.
echo Starting service...
%NSSM% start %SERVICE_NAME%
echo.
echo Done. Run service_status.bat to verify.
pause
endlocal
