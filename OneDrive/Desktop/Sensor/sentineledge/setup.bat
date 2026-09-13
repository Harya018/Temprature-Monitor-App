@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM setup.bat — First-time SentinelEdge setup on Windows
REM
REM Requires:
REM   - Python 3.11+  (python.exe on PATH)
REM   - PostgreSQL 14+ (psql.exe on PATH — add C:\Program Files\PostgreSQL\XX\bin)
REM   - Node.js 18+   (npm.exe on PATH)
REM
REM Run once from the project root:  .\setup.bat
REM ─────────────────────────────────────────────────────────────────────────────

setlocal

echo.
echo ============================================================
echo  SentinelEdge — First-Time Setup
echo ============================================================
echo.

REM ── 1. Verify prerequisites ──────────────────────────────────────────────────
where python >nul 2>&1 || (echo [ERROR] Python not found on PATH. & pause & exit /b 1)
where psql   >nul 2>&1 || (echo [ERROR] psql not found on PATH. Add PostgreSQL bin to PATH. & pause & exit /b 1)
where npm    >nul 2>&1 || (echo [ERROR] npm not found on PATH. Install Node.js. & pause & exit /b 1)

echo [OK] Prerequisites found.
echo.

REM ── 2. Copy .env.example → .env.development (if missing) ─────────────────────
if not exist ".env.development" (
    copy ".env.example" ".env.development" >nul
    echo [OK] Created .env.development from .env.example
    echo      IMPORTANT: Edit .env.development with your real credentials before starting.
) else (
    echo [SKIP] .env.development already exists.
)
echo.

REM ── 3. Create Python virtual environment ─────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo Creating Python virtual environment...
    python -m venv venv
    if %ERRORLEVEL% neq 0 ( echo [ERROR] Failed to create venv. & pause & exit /b 1 )
    echo [OK] Virtual environment created.
) else (
    echo [SKIP] Virtual environment already exists.
)
echo.

REM ── 4. Install Python dependencies ───────────────────────────────────────────
echo Installing Python dependencies...
call venv\Scripts\activate
pip install -r backend\requirements.txt --quiet
if %ERRORLEVEL% neq 0 ( echo [ERROR] pip install failed. & pause & exit /b 1 )
echo [OK] Python dependencies installed.
echo.

REM ── 5. Setup PostgreSQL database ─────────────────────────────────────────────
echo Setting up PostgreSQL database...
echo You will be prompted for the PostgreSQL superuser (postgres) password.
echo.
psql -U postgres -c "CREATE USER sentineledge WITH PASSWORD 'sentineledge123';" 2>nul
psql -U postgres -c "CREATE DATABASE sentineledge OWNER sentineledge;" 2>nul
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE sentineledge TO sentineledge;"
psql -U postgres -d sentineledge -c "GRANT ALL ON SCHEMA public TO sentineledge;"
psql -U postgres -d sentineledge -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO sentineledge;"
psql -U postgres -d sentineledge -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO sentineledge;"
echo [OK] Database ready.
echo.

REM ── 6. Install frontend dependencies and build ────────────────────────────────
echo Installing frontend dependencies...
cd frontend-web
npm install --silent
if %ERRORLEVEL% neq 0 ( echo [ERROR] npm install failed. & cd .. & pause & exit /b 1 )
echo.
echo Building frontend...
npm run build
if %ERRORLEVEL% neq 0 ( echo [ERROR] npm build failed. & cd .. & pause & exit /b 1 )
cd ..
echo [OK] Frontend built.
echo.

REM ── 7. Done ──────────────────────────────────────────────────────────────────
echo ============================================================
echo  Setup complete!
echo.
echo  Next steps:
echo  1. Edit .env.development with your SMTP, SMS and other credentials.
echo  2. Run start.bat to launch the server.
echo  3. Open http://localhost:5000 in your browser.
echo ============================================================
echo.
pause
