@echo off
echo ============================================================
echo  SentinelEdge Collector — Setup
echo ============================================================
echo.

echo [1] Python version:
python --version

echo.
echo [2] Python architecture:
python -c "import platform; print(platform.architecture())"

echo.
echo [3] Python executable:
python -c "import sys; print(sys.executable)"

echo.
echo [4] Installing pythonnet and requests...
python -m pip install --upgrade pip
python -m pip install pythonnet requests

echo.
echo [5] Verifying pythonnet import:
python -c "import clr; print('pythonnet OK')"

echo.
echo [6] Verifying requests import:
python -c "import requests; print('requests OK')"

echo.
echo ============================================================
echo  If pythonnet OK above, run:
echo    python proserver_collector.py --test
echo ============================================================
pause
