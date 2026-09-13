# SentinelEdge — Windows Auto-Start Guide

> Server path: `C:\Users\harya\OneDrive\Desktop\Sensor\sentineledge`

---

## Quick Reference

| Script | Purpose | Needs Admin? |
|---|---|---|
| `start_server.bat` | Start server manually (with auto-restart) | No |
| `check_server.bat` | Check if server is running | No |
| `install_autostart.bat` | Register auto-start via Task Scheduler | **Yes** |
| `uninstall_autostart.bat` | Remove Task Scheduler auto-start | **Yes** |
| `install_service.ps1` | Install as Windows Service (production) | **Yes** |
| `uninstall_service.ps1` | Remove Windows Service | **Yes** |

---

## Option 1 — Task Scheduler (Recommended, no install needed)

Best for: laptops, demo setups, personal machines.

### Setup (one-time)

1. Right-click **`install_autostart.bat`** → **Run as administrator**
2. You should see: *"SentinelEdge Server has been registered to start on boot"*
3. Restart your PC
4. After reboot, open: **http://localhost:5000/api/health**
   - You should see `{"status": "ok"}` — server is running automatically

### How it works

- Windows Task Scheduler starts `start_server.bat` at system boot
- The script auto-restarts uvicorn if it crashes (10-second delay)
- All output is logged to: `logs\server_startup.log`
- Runs as SYSTEM — starts even before anyone logs in

### Remove auto-start

1. Right-click **`uninstall_autostart.bat`** → **Run as administrator**
2. Done — server will no longer auto-start on boot

---

## Option 2 — Windows Service (Best for production)

Best for: dedicated servers, 24/7 deployments, production use.

### Advantages over Task Scheduler

- Starts earlier in the boot process (before Task Scheduler)
- Full service management via Windows Services panel
- Better crash handling and restart control
- Proper service logging with rotation

### Setup (one-time)

1. Right-click **`install_service.ps1`** → **Run with PowerShell**
   - Or: Open PowerShell as Admin → `cd` to project → `.\install_service.ps1`
2. NSSM is downloaded automatically (~300 KB) on first run
3. You should see: *"SUCCESS — SentinelEdge installed as Windows Service"*

### Managing the service

```powershell
# Check status
Get-Service SentinelEdge

# Start / Stop / Restart
Start-Service SentinelEdge
Stop-Service  SentinelEdge
Restart-Service SentinelEdge

# View live logs
Get-Content "logs\service.log" -Tail 50 -Wait

# Open Services GUI
services.msc   # find "SentinelEdge IoT Monitor"
```

### Remove service

1. Right-click **`uninstall_service.ps1`** → **Run with PowerShell**
2. Done — project files are not touched

---

## Manual Start (if needed)

Double-click **`start_server.bat`**  

- Opens a console window showing uvicorn logs  
- Auto-restarts on crash  
- Press **Ctrl+C** to stop  

---

## Check if Server is Running

Double-click **`check_server.bat`**

Output examples:

```
[OK]  SentinelEdge Server is RUNNING on port 5000
      API responded: 200
```

```
[--]  SentinelEdge Server is NOT running on port 5000
      Do you want to start it now? (Y/N): _
```

---

## Log Files

| File | Contains |
|---|---|
| `logs\server_startup.log` | Output when started via Task Scheduler or `start_server.bat` |
| `logs\service.log` | Output when running as Windows Service |
| `logs\app.log` | Application-level logs (from Python logger) |

---

## Troubleshooting

### Server not starting after reboot

1. Double-click `check_server.bat` to diagnose
2. Check Task Scheduler:  
   `Win + R` → `taskschd.msc` → find **SentinelEdge Server**  
   Look at "Last Run Result" — should be `0x0` (success)
3. Check the log: open `logs\server_startup.log`
4. Try running `start_server.bat` manually to see errors in real time

### Task Scheduler says "Access Denied"

- The `install_autostart.bat` must be run as Administrator
- Right-click → Run as administrator

### Port 5000 already in use after reboot

```bat
:: Find what is using port 5000
netstat -ano | findstr :5000

:: Kill by PID (replace XXXX with the PID from above)
taskkill /PID XXXX /F
```

### PowerShell script blocked by Execution Policy

```powershell
# Run this once in Admin PowerShell to allow local scripts
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine
```

### NSSM download fails (no internet on server)

1. Download NSSM manually from https://nssm.cc/download on another PC
2. Extract `nssm-2.24\win64\nssm.exe`
3. Place it at: `tools\nssm\nssm-2.24\win64\nssm.exe`
4. Run `install_service.ps1` again — it will skip the download

---

## Verify Everything Works

After setup, restart the PC and check:

```
http://localhost:5000/api/health
```

Expected response:
```json
{"status": "ok", "version": "...", "uptime_seconds": ...}
```

Mobile app (on same WiFi network): `http://<PC-IP>:5000`

Find your PC's IP:
```bat
ipconfig | findstr IPv4
```
