# setup_prereqs.ps1 - make sure Python 3.12 and PostgreSQL 16 are installed (called by FIRST_TIME_SETUP.bat)
# Downloads the official installers and installs them silently. Run as Administrator.
#   -Check   only report what is missing (installs nothing)
param([switch]$Check)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$secrets  = Join-Path $root 'backend\secrets'
$dl       = Join-Path $env:TEMP 'sentineledge_installers'
$pyUrl    = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$pgUrl    = 'https://get.enterprisedb.com/postgresql/postgresql-16.9-1-windows-x64.exe'
$state    = Join-Path $env:TEMP 'sentineledge_setup_state.txt'     # read back by FIRST_TIME_SETUP.bat

function Find-Python {
    foreach ($p in @("$env:ProgramFiles\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
        if (Test-Path $p) { return $p }
    }
    # only 3.11 / 3.12: the pinned libraries (e.g. psycopg2-binary 2.9.9) have no ready-made
    # packages for 3.13+, so a newer Python on the PATH is skipped and 3.12 is installed next to it
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c -and $c.Source -notmatch 'WindowsApps') {
        $v = & $c.Source --version 2>&1
        if ($v -match 'Python 3\.1[12]\.') { return $c.Source }
    }
    return $null
}

function Find-Psql {
    $c = Get-Command psql -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($d in Get-ChildItem "$env:ProgramFiles\PostgreSQL" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending) {
        $p = Join-Path $d.FullName 'bin\psql.exe'
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Get-File($url, $name) {
    New-Item -ItemType Directory -Force $dl | Out-Null
    $out = Join-Path $dl $name
    if (Test-Path $out) { return $out }
    Write-Host "      Downloading $name ..."
    try { Start-BitsTransfer -Source $url -Destination $out -ErrorAction Stop }
    catch { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing }
    return $out
}

$py   = Find-Python
$psql = Find-Psql
Write-Host ("      Python     : " + $(if ($py) { $py } else { 'NOT INSTALLED' }))
Write-Host ("      PostgreSQL : " + $(if ($psql) { $psql } else { 'NOT INSTALLED' }))
if ($Check) { exit 0 }

# ---- Python -----------------------------------------------------------------
if (-not $py) {
    $f = Get-File $pyUrl 'python-3.12.10-amd64.exe'
    Write-Host '      Installing Python 3.12 (about 1 minute) ...'
    $p = Start-Process $f -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_test=0','Include_launcher=0' -Wait -PassThru
    if ($p.ExitCode -ne 0) { Write-Host "      Python installer failed (code $($p.ExitCode))."; exit 2 }
    $py = Find-Python
    if (-not $py) { Write-Host '      Python installed but not found - restart the PC and run this again.'; exit 2 }
}
"PYTHON=$py" | Set-Content $state -Encoding ascii

# ---- PostgreSQL ---------------------------------------------------------------
if (-not $psql) {
    $pw = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
    $f  = Get-File $pgUrl 'postgresql-16.9-1-windows-x64.exe'
    Write-Host '      Installing PostgreSQL 16 (5-10 minutes, please wait) ...'
    $p = Start-Process $f -ArgumentList '--mode','unattended','--unattendedmodeui','none','--superpassword',$pw,'--serverport','5432',
            '--enable_acledit','0','--disable-components','stackbuilder' -Wait -PassThru
    if ($p.ExitCode -ne 0) { Write-Host "      PostgreSQL installer failed (code $($p.ExitCode))."; exit 3 }
    $psql = Find-Psql
    if (-not $psql) { Write-Host '      PostgreSQL installed but psql was not found.'; exit 3 }
    New-Item -ItemType Directory -Force $secrets | Out-Null
    "postgres user password (created by setup): $pw" | Set-Content (Join-Path $secrets 'postgres_password.txt') -Encoding ascii
    "PGPASSWORD=$pw" | Add-Content $state -Encoding ascii
    Write-Host '      PostgreSQL installed. Its password is saved in sentineledge\backend\secrets\postgres_password.txt'
}
# PostgreSQL was installed by an earlier run of this setup: reuse the password it saved
if (-not (Select-String -Path $state -Pattern '^PGPASSWORD=' -Quiet)) {
    $saved = Join-Path $secrets 'postgres_password.txt'
    if (Test-Path $saved) {
        $pw = ((Get-Content $saved -Raw) -split ':', 2)[1].Trim()
        if ($pw) { "PGPASSWORD=$pw" | Add-Content $state -Encoding ascii; Write-Host '      Using the PostgreSQL password saved by the earlier setup.' }
    }
}
"PSQL=$psql" | Add-Content $state -Encoding ascii
exit 0
