#Requires -RunAsAdministrator
<#
.SYNOPSIS
    SentinelEdge — Remove Windows Service

.DESCRIPTION
    Stops and permanently removes the SentinelEdge Windows Service.
    Does NOT delete any project files or logs.

.NOTES
    Run as Administrator.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SERVICE  = "SentinelEdge"
$NSSM_EXE = "C:\Users\harya\OneDrive\Desktop\Sensor\sentineledge\tools\nssm\nssm-2.24\win64\nssm.exe"

function Write-Step { param($msg) Write-Host "  [>] $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail { param($msg) Write-Host "  [ERROR] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor Magenta
Write-Host "   SentinelEdge — Windows Service Removal" -ForegroundColor Magenta
Write-Host "  =====================================================" -ForegroundColor Magenta
Write-Host ""

# ── Check if service exists ───────────────────────────────────────────────────
Write-Step "Looking for service: $SERVICE ..."
$svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue

if (-not $svc) {
    Write-Host "  [INFO] Service '$SERVICE' is not installed. Nothing to remove." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to close"
    exit 0
}

Write-Ok "Found service: $SERVICE (Status: $($svc.Status))"

# ── Stop service if running ───────────────────────────────────────────────────
if ($svc.Status -eq "Running") {
    Write-Step "Stopping service..."
    if (Test-Path $NSSM_EXE) {
        & $NSSM_EXE stop $SERVICE | Out-Null
    } else {
        Stop-Service -Name $SERVICE -Force
    }
    Start-Sleep -Seconds 3
    Write-Ok "Service stopped"
}

# ── Remove service ────────────────────────────────────────────────────────────
Write-Step "Removing service..."
if (Test-Path $NSSM_EXE) {
    & $NSSM_EXE remove $SERVICE confirm
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "NSSM remove failed — trying sc.exe fallback..."
        sc.exe delete $SERVICE
    }
} else {
    # Fallback: use sc.exe if NSSM was deleted
    sc.exe delete $SERVICE
}

Start-Sleep -Seconds 2

# ── Verify removal ────────────────────────────────────────────────────────────
$check = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if ($check) {
    Write-Host "  [WARN] Service still appears in registry — a reboot may be needed." -ForegroundColor Yellow
} else {
    Write-Ok "Service removed successfully"
}

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor Green
Write-Host "   SentinelEdge Windows Service has been removed." -ForegroundColor Green
Write-Host "  =====================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Project files and logs are untouched." -ForegroundColor Gray
Write-Host "  To re-install the service, run: install_service.ps1" -ForegroundColor Gray
Write-Host "  To start manually, double-click: start_server.bat" -ForegroundColor Gray
Write-Host ""

Read-Host "  Press Enter to close"
