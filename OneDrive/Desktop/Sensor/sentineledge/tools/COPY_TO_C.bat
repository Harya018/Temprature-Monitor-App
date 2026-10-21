@echo off
title SentinelEdge - copy from this drive to C:
color 0A
:: Run this file from the Sensor folder on the USB/external drive (sentineledge\tools).
:: It copies  <this drive>\Sensor  ->  C:\Sensor   (change DEST below if your install is elsewhere)
set "DEST=C:\Sensor"
:: this file lives in <drive>\Sensor\sentineledge\tools - the project root is two levels up
pushd "%~dp0..\.."
set "SRC=%CD%"
popd

echo.
echo  Source      : %SRC%
echo  Destination : %DEST%
echo.
net session >nul 2>&1
if errorlevel 1 (
    echo  Please right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)
if not exist "%SRC%\sentineledge\backend\main.py" (
    echo  ERROR: this does not look like the Sensor project folder: %SRC%
    pause
    exit /b 1
)
if /i "%SRC%"=="%DEST%" (
    echo  Source and destination are the same folder - nothing to do.
    pause
    exit /b 1
)

echo  [1/3] Stopping the old server on port 5000 (if any)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 5000 -State Listen -EA SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 4 } | ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo  [2/3] Copying the project (existing settings and data on C: are kept)...
robocopy "%SRC%" "%DEST%" /E /XD venv venv32 node_modules __pycache__ .git logs "System Volume Information" $RECYCLE.BIN /XF *.pyc *.pid /R:1 /W:1 /NP /NFL /NDL /LOG:"%TEMP%\sentineledge_copy.log"
set RC=%ERRORLEVEL%
if %RC% GEQ 8 (
    echo.
    echo  COPY FAILED (robocopy code %RC%). See %TEMP%\sentineledge_copy.log
    pause
    exit /b %RC%
)

echo  [3/3] Replacing the built dashboard so no old files remain...
robocopy "%SRC%\sentineledge\backend\static" "%DEST%\sentineledge\backend\static" /MIR /R:1 /W:1 /NP /NFL /NDL /NJH /NJS
if %ERRORLEVEL% GEQ 8 (
    echo  Could not replace the dashboard files.
    pause
    exit /b 1
)

echo.
echo  Done. The new version is in %DEST%
echo  Now run  %DEST%\START.bat   (as administrator)
echo  Then open http://localhost:5000/api/hub/ping  - it should say "sentineledge-hub".
echo.
pause
