@echo off
:: Sync project from E drive (shared USB) to local Desktop.
:: Excludes venv, venv32, and other build/cache dirs so environments are never deleted.
echo Syncing from E:\Sensor\sentineledge ...
robocopy "E:\Sensor\sentineledge" "C:\Users\COE_AT Admin\Desktop\Sensor\sentineledge" ^
    /MIR ^
    /XD __pycache__ .git node_modules venv venv32 ^
    /XF "*.pyc" "*.pid" "sentineledge.log" "*.env" ".env.*" ^
    /NFL /NJH
echo Done.
