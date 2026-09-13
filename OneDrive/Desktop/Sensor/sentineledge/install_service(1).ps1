#Requires -RunAsAdministrator
<#
.SYNOPSIS
    SentinelEdge — Install as Windows Service using NSSM

.DESCRIPTION
    Downloads NSSM (Non-Sucking Service Manager) if not already present,
    then installs SentinelEdge as a proper Windows Service that:
      - Starts automatically on boot (before user login)
      - Restarts automatically on crash
      - Logs stdout and stderr to logs\service.log

.NOTES
    Run as Administrator:
    Right-click install_service.ps1 → Run with PowerShell (as Admin)
    OR:
    Start-Process powershell -Verb RunAs -ArgumentList "-File install_service.ps1"
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Configuration ─────────────────────────────────────────────────────────────
$ROOT        = "C:\Users\harya\OneDrive\Desktop\Sensor\sentineledge"
$SERVICE     = "SentinelEdge"
$DISPLAY     = "SentinelEdge IoT Monitor"
$DESCRIPTION = "SentinelEdge temperature monitoring server (uvicorn/FastAPI)"
$PORT        = 5000
$LOGFILE     = "$ROOT\logs\service.log"
$NSSM_DIR    = "$ROOT\tools\nssm"
$NSSM_ZIP    = "$ROOT\tools\nssm-2.24.zip"
$NSSM_URL    = "https://nssm.cc/release/nssm-2.24.zip"
$NSSM_EXE    = "$NSSM_DIR\nssm-2.24\win64\nssm.exe"

# ── Helper: coloured output ───────────────────────────────────────────────────
function Write-Step  { param($msg) Write-Host "  [>] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "  [ERROR] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor Magenta
Write-Host "   SentinelEdge — Windows Service Installer" -ForegroundColor Magenta
Write-Host "  =====================================================" -ForegroundColor Magenta
Write-Host ""

# ── Step 1: Verify project root ───────────────────────────────────────────────
Write-Step "Verifying project root..."
if (-not (Test-Path $ROOT)) {
    Write-Fail "Project root not found: $ROOT"
    Write-Host "  Make sure SentinelEdge is installed at the correct path." -ForegroundColor Red
    exit 1
}
Write-Ok "Project root: $ROOT"

# ── Step 2: Find Python in venv ───────────────────────────────────────────────
Write-Step "Locating Python interpreter..."
$PYTHON = "$ROOT\venv\Scripts\python.exe"
if (-not (Test-Path $PYTHON)) {
    # Fallback to system Python
    $PYTHON = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PYTHON) {
        Write-Fail "Python not found. Install Python or create the venv first."
        exit 1
    }
    Write-Warn "venv not found — using system Python: $PYTHON"
} else {
    Write-Ok "Python: $PYTHON"
}

# ── Step 3: Find uvicorn ──────────────────────────────────────────────────────
Write-Step "Locating uvicorn..."
$UVICORN = "$ROOT\venv\Scripts\uvicorn.exe"
if (-not (Test-Path $UVICORN)) {
    $UVICORN = (Get-Command uvicorn -ErrorAction SilentlyContinue).Source
    if (-not $UVICORN) {
        Write-Fail "uvicorn not found. Run: venv\Scripts\pip install uvicorn"
        exit 1
    }
    Write-Warn "venv uvicorn not found — using system uvicorn: $UVICORN"
} else {
    Write-Ok "uvicorn: $UVICORN"
}

# ── Step 4: Download NSSM if not present ─────────────────────────────────────
Write-Step "Checking for NSSM..."
if (-not (Test-Path $NSSM_EXE)) {
    Write-Step "NSSM not found — downloading from $NSSM_URL ..."

    # Create tools directory
    if (-not (Test-Path "$ROOT\tools")) { New-Item -ItemType Directory -Path "$ROOT\tools" | Out-Null }

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $NSSM_URL -OutFile $NSSM_ZIP -UseBasicParsing
        Write-Ok "Downloaded NSSM zip"

        Expand-Archive -Path $NSSM_ZIP -DestinationPath $NSSM_DIR -Force
        Write-Ok "Extracted NSSM to $NSSM_DIR"

        Remove-Item $NSSM_ZIP -Force
    } catch {
        Write-Fail "Failed to download NSSM: $_"
        Write-Host ""
        Write-Host "  Manual fix: Download NSSM from https://nssm.cc/download" -ForegroundColor Yellow
        Write-Host "  Extract nssm.exe to: $NSSM_DIR\nssm-2.24\win64\nssm.exe" -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Ok "NSSM found: $NSSM_EXE"
}

# ── Step 5: Create logs folder ────────────────────────────────────────────────
if (-not (Test-Path "$ROOT\logs")) {
    New-Item -ItemType Directory -Path "$ROOT\logs" | Out-Null
}

# ── Step 6: Remove existing service (if any) ──────────────────────────────────
Write-Step "Removing existing service (if any)..."
$existing = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Status -eq "Running") {
        & $NSSM_EXE stop $SERVICE | Out-Null
        Start-Sleep -Seconds 2
    }
    & $NSSM_EXE remove $SERVICE confirm | Out-Null
    Write-Ok "Old service removed"
} else {
    Write-Ok "No existing service found"
}

# ── Step 7: Install service ───────────────────────────────────────────────────
Write-Step "Installing SentinelEdge Windows Service..."

$UVICORN_ARGS = "backend.main:app --host 0.0.0.0 --port $PORT"

& $NSSM_EXE install $SERVICE $UVICORN $UVICORN_ARGS
if ($LASTEXITCODE -ne 0) {
    Write-Fail "NSSM install failed (exit code $LASTEXITCODE)"
    exit 1
}

# ── Step 8: Configure service properties ─────────────────────────────────────
Write-Step "Configuring service..."

# Working directory = project root (so relative imports work)
& $NSSM_EXE set $SERVICE AppDirectory $ROOT

# Display name and description
& $NSSM_EXE set $SERVICE DisplayName $DISPLAY
& $NSSM_EXE set $SERVICE Description $DESCRIPTION

# Environment: PYTHONPATH and APP_ENV
& $NSSM_EXE set $SERVICE AppEnvironmentExtra `
    "PYTHONPATH=$ROOT;$ROOT\backend" `
    "APP_ENV=development"

# Stdout and stderr → service.log
& $NSSM_EXE set $SERVICE AppStdout $LOGFILE
& $NSSM_EXE set $SERVICE AppStderr $LOGFILE

# Rotate log at 10 MB
& $NSSM_EXE set $SERVICE AppRotateFiles 1
& $NSSM_EXE set $SERVICE AppRotateBytes 10485760

# Restart on crash — wait 10 seconds before restarting
& $NSSM_EXE set $SERVICE AppRestartDelay 10000

# Start type: Automatic
& $NSSM_EXE set $SERVICE Start SERVICE_AUTO_START

Write-Ok "Service configured"

# ── Step 9: Start the service now ────────────────────────────────────────────
Write-Step "Starting service..."
& $NSSM_EXE start $SERVICE

Start-Sleep -Seconds 3

$svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Ok "Service is RUNNING"
} else {
    Write-Warn "Service may still be starting. Check in a few seconds."
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  =====================================================" -ForegroundColor Green
Write-Host "   SUCCESS — SentinelEdge installed as Windows Service" -ForegroundColor Green
Write-Host "  =====================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Service name : $SERVICE" -ForegroundColor White
Write-Host "  Log file     : $LOGFILE" -ForegroundColor White
Write-Host "  Dashboard    : http://localhost:$PORT" -ForegroundColor White
Write-Host "  Health API   : http://localhost:$PORT/api/health" -ForegroundColor White
Write-Host ""
Write-Host "  Manage the service:" -ForegroundColor Gray
Write-Host "    Start   : Start-Service $SERVICE" -ForegroundColor Gray
Write-Host "    Stop    : Stop-Service  $SERVICE" -ForegroundColor Gray
Write-Host "    Status  : Get-Service   $SERVICE" -ForegroundColor Gray
Write-Host "    Logs    : Get-Content '$LOGFILE' -Tail 50 -Wait" -ForegroundColor Gray
Write-Host "    Remove  : Run uninstall_service.ps1 as Admin" -ForegroundColor Gray
Write-Host ""
Write-Host "  The service starts automatically on every Windows boot." -ForegroundColor Cyan
Write-Host ""

Read-Host "  Press Enter to close"
