@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM setup_postgres.bat — One-time PostgreSQL setup for SentinelEdge
REM
REM Run this ONCE on the client's PC after installing PostgreSQL.
REM PostgreSQL must be installed and the bin directory on the system PATH.
REM
REM Default installer adds: C:\Program Files\PostgreSQL\<version>\bin
REM
REM Run as: .\setup_postgres.bat
REM You will be prompted for the PostgreSQL superuser (postgres) password.
REM ─────────────────────────────────────────────────────────────────────────────

echo.
echo ============================================================
echo  SentinelEdge — PostgreSQL Database Setup
echo ============================================================
echo.
echo This will create:
echo   User    : sentineledge  (password: sentineledge123)
echo   Database: sentineledge
echo.
echo You will be prompted for the 'postgres' superuser password.
echo.

REM Create the database user
psql -U postgres -c "CREATE USER sentineledge WITH PASSWORD 'sentineledge123';"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] User may already exist — continuing...
)

REM Create the database
psql -U postgres -c "CREATE DATABASE sentineledge OWNER sentineledge;"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] Database may already exist — continuing...
)

REM Grant privileges
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE sentineledge TO sentineledge;"

REM Allow the user to create tables in the public schema (PostgreSQL 15+)
psql -U postgres -d sentineledge -c "GRANT ALL ON SCHEMA public TO sentineledge;"
psql -U postgres -d sentineledge -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO sentineledge;"
psql -U postgres -d sentineledge -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO sentineledge;"

echo.
echo ============================================================
echo  Done! Database 'sentineledge' is ready.
echo.
echo  Next steps:
echo    1. Make sure your .env file has:
echo       DATABASE_URL=postgresql://sentineledge:sentineledge123@localhost:5432/sentineledge
echo    2. Run: pip install -r backend\requirements.txt
echo    3. Start the server: cd backend ^& python -m uvicorn main:app --host 0.0.0.0 --port 8000
echo    4. (Optional) Run: python migrate_sqlite_to_postgres.py  (to import old data)
echo ============================================================
echo.
pause
