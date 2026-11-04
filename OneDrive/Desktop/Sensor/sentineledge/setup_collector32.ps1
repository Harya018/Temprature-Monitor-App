# setup_collector32.ps1 - the Pro-face live collector, set up automatically when Pro-Server EX is on this PC
# (called by FIRST_TIME_SETUP.bat; also by tools\SETUP_PROFACE_COLLECTOR.bat when Pro-Server EX is installed later)
#
#   * finds Pro-Server EX's SDK (ProEasyDotNet.dll) and writes its path into collector\collector_config.json
#   * installs the official 32-bit Python 3.12 into C:\Python312-32 if it is missing (the SDK is 32-bit)
#   * creates collector\venv32 with the collector's libraries (collector\requirements32.txt) and checks them
# No Pro-Server EX on this PC = nothing is installed; the PC uses the Excel live reader.
#   -Check   only report what is there (installs nothing)
#   -DllSearchRoot / -Py32Dir   tests only
param([switch]$Check, [string]$DllSearchRoot = '', [string]$Py32Dir = 'C:\Python312-32')

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$coll    = Join-Path $root 'collector'
$venv    = Join-Path $coll 'venv32'
$venvPy  = Join-Path $venv 'Scripts\python.exe'
$cfgFile = Join-Path $coll 'collector_config.json'
$reqs    = Join-Path $coll 'requirements32.txt'
$py32    = Join-Path $Py32Dir 'python.exe'
$pyUrl   = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10.exe'    # official 32-bit installer

if (-not (Test-Path $coll)) { Write-Host '      No collector folder in this copy - the Excel live reader is used.'; exit 0 }

# ---- 1. Pro-Server EX on this PC? ---------------------------------------------------------
$dll = $null
try {
    $cfg = Get-Content $cfgFile -Raw | ConvertFrom-Json
    if ($cfg.dll_path -and (Test-Path -LiteralPath $cfg.dll_path)) { $dll = $cfg.dll_path }
} catch {}
if (-not $dll) {
    $roots = if ($DllSearchRoot) { @($DllSearchRoot) } else { @("${env:ProgramFiles(x86)}\Pro-face", "$env:ProgramFiles\Pro-face") }
    foreach ($base in $roots) {
        if (-not (Test-Path -LiteralPath $base)) { continue }
        $all = @(Get-ChildItem -LiteralPath $base -Recurse -Filter 'ProEasyDotNet.dll' -ErrorAction SilentlyContinue)
        $f = $all | Where-Object { $_.FullName -match 'DotNet40' } | Select-Object -First 1
        if (-not $f) { $f = $all | Select-Object -First 1 }
        if ($f) { $dll = $f.FullName; break }
    }
}
if (-not $dll) {
    Write-Host '      Pro-Server EX is not installed on this PC - the Excel live reader is used (nothing to set up).'
    exit 0
}
Write-Host "      Pro-Server EX found: $dll"

function Test-Venv {
    if (-not (Test-Path $venvPy)) { return $false }
    try {
        & $venvPy -c "import struct, sys, clr_loader, requests; sys.exit(0 if struct.calcsize('P') == 4 else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }      # e.g. a venv32 copied from another PC whose Python is missing here
}
$venvOk = Test-Venv
if ($Check) {
    Write-Host ("      32-bit Python : " + $(if (Test-Path $py32) { $py32 } else { 'NOT INSTALLED' }))
    Write-Host ("      Collector env : " + $(if ($venvOk) { 'ready' } else { 'NOT READY' }))
    exit 0
}

# the collector reads the SDK from this path
try {
    $txt = Get-Content $cfgFile -Raw
    $esc = ($dll -replace '\\', '\\')
    if ($txt -notmatch [regex]::Escape('"dll_path": "' + $esc + '"')) {
        $txt = [regex]::Replace($txt, '"dll_path"\s*:\s*"[^"]*"', ('"dll_path": "' + ($esc -replace '\$', '$$$$') + '"'))
        [IO.File]::WriteAllText($cfgFile, $txt, (New-Object Text.UTF8Encoding $false))   # no BOM
        Write-Host '      collector_config.json: SDK path updated.'
    }
} catch { Write-Host "      Could not update collector_config.json: $($_.Exception.Message)" }

if ($venvOk) { Write-Host '      Pro-face collector already set up (venv32 ready).'; exit 0 }

# ---- 2. 32-bit Python ---------------------------------------------------------------------
if (-not (Test-Path $py32)) {
    $dl = Join-Path $env:TEMP 'sentineledge_installers'; New-Item -ItemType Directory -Force $dl | Out-Null
    $inst = Join-Path $dl 'python-3.12.10-32bit.exe'
    if (-not (Test-Path $inst)) {
        Write-Host '      Downloading the 32-bit Python 3.12 installer ...'
        try { Start-BitsTransfer -Source $pyUrl -Destination $inst -ErrorAction Stop }
        catch { Invoke-WebRequest -Uri $pyUrl -OutFile $inst -UseBasicParsing }
    }
    Write-Host "      Installing 32-bit Python into $Py32Dir (about 1 minute) ..."
    $p = Start-Process $inst -ArgumentList '/quiet', 'InstallAllUsers=0', "TargetDir=$Py32Dir", 'PrependPath=0', 'Include_launcher=0',
            'Include_test=0', 'Include_doc=0', 'Include_pip=1', 'Shortcuts=0', 'AssociateFiles=0' -Wait -PassThru
    if ($p.ExitCode -ne 0 -or -not (Test-Path $py32)) { Write-Host "      32-bit Python installer failed (code $($p.ExitCode))."; exit 2 }
}
& $py32 -c "import struct, sys; sys.exit(0 if struct.calcsize('P') == 4 else 1)"
if ($LASTEXITCODE -ne 0) { Write-Host "      $py32 is not a 32-bit Python - the collector cannot use it."; exit 2 }

# ---- 3. venv32 with the collector's libraries ----------------------------------------------
Write-Host '      Creating the collector environment (venv32) ...'
& $py32 -m venv --clear $venv
if ($LASTEXITCODE -ne 0) { Write-Host '      Could not create venv32.'; exit 3 }
& $venvPy -m pip install --quiet --upgrade pip 2>$null | Out-Null
& $venvPy -m pip install --quiet -r $reqs
if ($LASTEXITCODE -ne 0) { Write-Host '      Installing the collector libraries failed (internet?).'; exit 3 }
$env:PYTHONNET_RUNTIME = 'netfx'
& $venvPy -c "import clr, System, requests; print('      Collector ready - .NET', System.Environment.Version)"
if ($LASTEXITCODE -ne 0) { Write-Host '      The collector libraries do not load (.NET Framework 4 missing?).'; exit 3 }
exit 0
