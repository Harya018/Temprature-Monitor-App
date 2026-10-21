@echo off
title SentinelEdge - make a package for a new laptop
cd /d "%~dp0"
echo Building a clean SentinelEdge copy for a new company's laptop...
echo (no company data, backups, logs, passwords or the Pro-face collector)
echo.
python make_package.py %*
echo.
pause
