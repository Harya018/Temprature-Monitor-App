@echo off
title SentinelEdge - First-time setup
color 0B
cd /d "%~dp0"

:: Needs Administrator rights (to install Python / PostgreSQL and open the firewall) - ask Windows for them
net session >nul 2>&1
if errorlevel 1 (
    echo Asking Windows for Administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ==========================================================
echo   SENTINELEDGE - FIRST-TIME SETUP (run once per PC)
echo ==========================================================
echo   Everything is done for you: Python, PostgreSQL, libraries,
echo   database, Super Admin, firewall - then SentinelEdge starts.
echo   Needs internet. Takes 5-20 minutes. Do not close this window.
echo.

:: The program lives in the "sentineledge" folder next to this file (and next to START.bat)
set "MAIN=%~dp0"
set "APP=%~dp0sentineledge"
if not exist "%APP%\setup_prereqs.ps1" (
    echo.
    echo  The "sentineledge" folder is missing or incomplete.
    echo  FIRST_TIME_SETUP.bat must be in the main folder, next to START.bat and the
    echo  "sentineledge" folder. Copy the whole SentinelEdge folder again, then run this file again.
    pause
    exit /b 1
)
cd /d "%APP%"

:: Files copied from another PC / a download are "blocked" by Windows, which then asks about every
:: script it runs. Unblock the whole folder once.
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%MAIN:~0,-1%' -Recurse -File -EA SilentlyContinue | Unblock-File -EA SilentlyContinue" >nul 2>&1

set "SETUP_STATE=%TEMP%\sentineledge_setup_state.txt"
if exist "%SETUP_STATE%" del "%SETUP_STATE%" >nul 2>&1

echo [1/7] Checking / installing Python and PostgreSQL...
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\setup_prereqs.ps1"
if not "%errorlevel%"=="0" (
    echo.
    echo  Installing the required programs FAILED. Check the internet connection and run again.
    pause
    exit /b 1
)

if not exist "%SETUP_STATE%" (
    echo  The setup helper did not finish. Run this file again.
    pause
    exit /b 1
)
set "PYEXE="
set "PSQL="
set "PGPASSWORD="
for /f "usebackq tokens=1,* delims==" %%A in ("%SETUP_STATE%") do (
    if /i "%%A"=="PYTHON"     set "PYEXE=%%B"
    if /i "%%A"=="PSQL"       set "PSQL=%%B"
    if /i "%%A"=="PGPASSWORD" set "PGPASSWORD=%%B"
)
if exist "%SETUP_STATE%" del "%SETUP_STATE%" >nul 2>&1
if not defined PYEXE (
    echo  Python was not found. Restart the PC and run this file again.
    pause
    exit /b 1
)
:: START.bat uses exactly this Python (the one the libraries are installed into), even if
:: another "python" - or the Microsoft Store placeholder - comes first on the PATH
>"%APP%\python_path.txt" echo(%PYEXE%
echo.

echo [2/7] Installing the Python libraries from requirements.txt (a few minutes)...
"%PYEXE%" -m pip install --upgrade pip --quiet
"%PYEXE%" -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo.
    echo  Installing the libraries FAILED. Check the internet connection and run again.
    pause
    exit /b 1
)
echo       Checking every library...
"%PYEXE%" backend\check_install.py
if errorlevel 1 (
    echo       Something is missing - installing it now...
    "%PYEXE%" -m pip install -r backend\requirements.txt
    "%PYEXE%" backend\check_install.py
    if errorlevel 1 (
        echo.
        echo  A library still could not be installed. Check the internet connection and run this file again.
        pause
        exit /b 1
    )
)
echo       Libraries installed and checked.
echo.

echo [3/7] Creating the database and its password...
:: Only when PostgreSQL was ALREADY on this PC (not installed by this setup) its password is needed
if not defined PGPASSWORD set /p "PGPASSWORD=  PostgreSQL was already installed. Type the password of its 'postgres' user: "
"%PSQL%" -U postgres -h localhost -c "SELECT 1" >nul 2>&1
if errorlevel 1 (
    set "PGPASSWORD="
    echo.
    echo  Could not reach the database. Check the postgres password and that PostgreSQL is running.
    pause
    exit /b 1
)
"%PSQL%" -U postgres -h localhost -c "CREATE DATABASE sentineledge;" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\setup_secrets.ps1" -Mode Db -Psql "%PSQL%"
if errorlevel 1 (
    set "PGPASSWORD="
    echo.
    echo  Could not create the database user. Run this file again.
    pause
    exit /b 1
)
"%PSQL%" -U postgres -h localhost -c "ALTER DATABASE sentineledge OWNER TO sentineledge;" >nul
"%PSQL%" -U postgres -h localhost -c "GRANT ALL PRIVILEGES ON DATABASE sentineledge TO sentineledge;" >nul
"%PSQL%" -U postgres -h localhost -d sentineledge -c "ALTER SCHEMA public OWNER TO sentineledge;" >nul
echo       Database ready (its password was created automatically).
echo.

echo [4/7] Super Admin account (the standard Super Admin password of every SentinelEdge PC)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\setup_secrets.ps1" -Mode Super -Psql "%PSQL%" -Python "%PYEXE%"
if errorlevel 1 (
    set "PGPASSWORD="
    echo  The Super Admin could not be prepared. Run this file again.
    pause
    exit /b 1
)
echo.

echo [5/7] Windows firewall: letting the phone app and the main server reach port 5000...
netsh advfirewall firewall delete rule name="SentinelEdge (port 5000)" >nul 2>&1
netsh advfirewall firewall add rule name="SentinelEdge (port 5000)" dir=in action=allow protocol=TCP localport=5000 profile=any >nul 2>&1
if errorlevel 1 (
    echo       Could not add the firewall rule - the phone app may not connect until port 5000 is allowed.
) else (
    echo       Port 5000 allowed.
)
echo.

echo [6/7] Checking the program files...
"%PYEXE%" -c "import ast; [ast.parse(open(f, encoding='utf-8-sig').read()) for f in ('backend/main.py', 'backend/config.py')]; print('      Program files OK')"
if errorlevel 1 (
    set "PGPASSWORD="
    echo  The program files look damaged or incomplete. Copy the folder again and run setup again.
    pause
    exit /b 1
)
if not exist "%APP%\backend\static\index.html" (
    set "PGPASSWORD="
    echo  The dashboard files are missing ^(sentineledge\backend\static^). Copy the folder again from the package.
    pause
    exit /b 1
)
echo.

echo [7/7] Writing all passwords of this PC into one file...
set "PWFILE=%MAIN%SentinelEdge PASSWORDS - KEEP PRIVATE.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\setup_secrets.ps1" -Mode Summary -OutFile "%PWFILE%" >nul
set "PGPASSWORD="
if not exist "%PWFILE%" echo       Could not write the passwords file.
echo.

:: Start SentinelEdge now - through Explorer, so the server and the browser run as the normal user
:: (not as Administrator). START.bat opens its own window and then the dashboard in the browser.
if exist "%MAIN%START.bat" explorer.exe "%MAIN%START.bat"
if exist "%PWFILE%" start "" notepad.exe "%PWFILE%"

cls
color 0A
echo ======================================================================
echo   SENTINELEDGE IS INSTALLED AND STARTING
echo ======================================================================
echo.
echo   The passwords of this PC (database) and the addresses are saved in this
echo   file (it is open in Notepad):
echo.
echo       %PWFILE%
echo.
echo   Super Admin   http://localhost:5000/super-admin/login
echo                 username: superadmin
echo                 password: the standard Super Admin password - the same on every
echo                           SentinelEdge PC. It is not written anywhere ^(only its hash^).
echo.
echo   Next: sign in as Super Admin, create the company and its admin
echo   (Companies ^> + New Company), write the admin's name and password into
echo   the file, and hand the admin login over.
echo.
echo   KEEP THE PASSWORDS FILE PRIVATE: move it off this PC or delete it after
echo   you have stored the passwords safely. Never give it to the company.
echo.
echo   Every day: START.bat to start, STOP.bat to stop.
echo ======================================================================
echo.
pause
