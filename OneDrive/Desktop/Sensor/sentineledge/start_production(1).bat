@echo off
echo Starting SentinelEdge PRODUCTION...
cd /d "%~dp0"
set APP_ENV=production
set PYTHONPATH=%CD%;%CD%\backend
call venv\Scripts\activate
uvicorn backend.main:app --host 0.0.0.0 --port 5000
pause
