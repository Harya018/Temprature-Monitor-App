# setup_secrets.ps1 - passwords for THIS laptop (called by FIRST_TIME_SETUP.bat)
#   -Mode Db       create / reuse the app's database password, write DATABASE_URL into .env.development
#   -Mode Super    Super Admin = the standard password used on every SentinelEdge PC (no question asked):
#                  a new database gets it on the server's first start, an existing Super Admin is reset to it.
#                  Only its bcrypt HASH is in this file - the password itself is not written anywhere.
#   -Mode Summary  write every password of this PC into one file next to START.bat (shown at the end of setup)
param(
    [Parameter(Mandatory = $true)][ValidateSet('Db', 'Super', 'Summary')][string]$Mode,
    [string]$Psql = '',
    [string]$PgPassword = '',
    [string]$Python = '',
    [string]$OutFile = '',
    [string]$DbUser = 'postgres'          # tests only: another database user
)
$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $root '.env.development'
$secrets = Join-Path $root 'backend\secrets'

# The Super Admin password - the same on every SentinelEdge PC (main server and every company PC).
# Only its bcrypt hash is kept here; the server stores this hash as it is (it never sees the password).
$SuperAdminUser = 'superadmin'
$SuperAdminHash = '$2b$12$NWQahEeIQgOFbYrDSSDc1eZc8JJwHJyMgxLCdrAwt/VgN.mVoKIJO'

function New-Pw([int]$n) {
    $chars = (48..57) + (65..90) + (97..122)
    -join ($chars | Get-Random -Count $n | ForEach-Object { [char]$_ })
}

function Get-DbPassword {
    if (Test-Path $envFile) {
        $m = Select-String -Path $envFile -Pattern '^DATABASE_URL=postgresql://sentineledge:([^@]+)@' | Select-Object -First 1
        if ($m) { return $m.Matches[0].Groups[1].Value }
    }
    return $null
}

if ($Mode -eq 'Db') {
    # the password already in .env.development wins (so a second run never breaks a working install)
    $pw = Get-DbPassword
    if (-not $pw) { $pw = New-Pw 20 }
    if ($PgPassword) { $env:PGPASSWORD = $PgPassword }   # otherwise it is already in the environment
    $sql = "DO `$`$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sentineledge') THEN ALTER USER sentineledge WITH PASSWORD '$pw'; ELSE CREATE USER sentineledge WITH PASSWORD '$pw'; END IF; END `$`$;"
    & $Psql -U postgres -h localhost -v ON_ERROR_STOP=1 -q -c $sql
    if ($LASTEXITCODE -ne 0) { exit 1 }
    $url = "postgresql://sentineledge:$pw@localhost:5432/sentineledge"
    if (Test-Path $envFile) {
        $txt = Get-Content $envFile -Raw
        if ($txt -match '(?m)^DATABASE_URL=') { $txt = [regex]::Replace($txt, '(?m)^DATABASE_URL=.*$', "DATABASE_URL=$url") }
        else { $txt = $txt.TrimEnd() + "`r`nDATABASE_URL=$url`r`n" }
        Set-Content $envFile $txt -Encoding ascii -NoNewline
    } else {
        $tpl = Get-Content (Join-Path $root '.env.template') -Raw
        $tpl = [regex]::Replace($tpl, '(?m)^DATABASE_URL=.*$', "DATABASE_URL=$url")
        Set-Content $envFile $tpl -Encoding ascii -NoNewline
    }
    exit 0
}

if ($Mode -eq 'Super') {
    if ($PgPassword) { $env:PGPASSWORD = $PgPassword }
    # Is there already a Super Admin in this PC's database? (no tables yet = brand-new database)
    $n = '0'
    try {
        $n = (& $Psql -U $DbUser -h localhost -d sentineledge -tAc "SELECT COUNT(*) FROM admins WHERE role='super_admin'" 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $n -notmatch '^\d+$') { $n = '0' }
    } catch { $n = '0' }
    if ($n -eq '0') {
        # brand-new: the server creates the Super Admin with this hash on its first start, then deletes the file
        New-Item -ItemType Directory -Force $secrets | Out-Null
        Set-Content (Join-Path $secrets 'super_admin_setup.txt') $SuperAdminHash -Encoding ascii -NoNewline
        Write-Host '      The Super Admin is created with the standard password when SentinelEdge first starts.'
        exit 0
    }
    # already there (setup run again): set the standard password (its hash), end its old sign-ins
    $sql = "UPDATE admins SET password_hash = '$SuperAdminHash', is_active = 1 WHERE role = 'super_admin'; " +
           "DELETE FROM admin_sessions WHERE admin_id IN (SELECT id FROM admins WHERE role = 'super_admin');"
    & $Psql -U $DbUser -h localhost -d sentineledge -v ON_ERROR_STOP=1 -q -c $sql | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host '      Could not set the Super Admin password.'; exit 1 }
    Write-Host '      Super Admin password set to the standard password.'
    exit 0
}

# ---- Summary: every password of this PC in one file --------------------------------------------
$main = Split-Path -Parent $root                       # the folder with START.bat
if (-not $OutFile) { $OutFile = Join-Path $main 'SentinelEdge PASSWORDS - KEEP PRIVATE.txt' }
if (-not $PgPassword) { $PgPassword = $env:PGPASSWORD }     # typed during setup when PostgreSQL was already there
if (-not $PgPassword) {
    $saved = Join-Path $secrets 'postgres_password.txt'
    if (Test-Path $saved) { $PgPassword = ((Get-Content $saved -Raw) -split ':', 2)[1].Trim() }
}
$dbPw = Get-DbPassword
$ips = @()
try {
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } | ForEach-Object { $_.IPAddress }
} catch {}
$addr = if ($ips) { ($ips | ForEach-Object { "                     http://$($_):5000" }) -join "`r`n" } else { '                     (no network address found yet)' }
$when = Get-Date -Format 'dd-MM-yyyy HH:mm'
$text = @"
=====================================================================
  SENTINELEDGE - PASSWORDS OF THIS PC   ($env:COMPUTERNAME, $when)
=====================================================================
  KEEP THIS FILE PRIVATE: it holds the database passwords of this PC.
  After writing them down in a safe place, move this file off the PC
  or delete it. Never give it to the company.


SUPER ADMIN  (creates companies and their admins)
---------------------------------------------------------------------
  Address  : http://localhost:5000/super-admin/login
  Username : $SuperAdminUser
  Password : the standard Super Admin password (the same on every
             SentinelEdge PC). It is NOT written in this file or anywhere
             on this PC - only its scrambled hash is stored. Ask the
             vendor if you do not know it.


COMPANY ADMINS  (you create them; the program never shows a password again)
---------------------------------------------------------------------
  Super Admin > Companies > + New Company  (or Admins > + New Admin).
  Write each one here when you create it, then hand it over:

  Company : ____________________  Admin : ____________  Password : ____________
  Company : ____________________  Admin : ____________  Password : ____________

  The company admin signs in at  http://localhost:5000


DATABASE  (only needed for repairs - never needed for daily use)
---------------------------------------------------------------------
  PostgreSQL main user     : postgres
  Its password             : $(if ($PgPassword) { $PgPassword } else { '(PostgreSQL was already on this PC - the password typed during setup)' })
  SentinelEdge database    : sentineledge   on localhost:5432
  SentinelEdge user        : sentineledge
  Its password             : $(if ($dbPw) { $dbPw } else { '(not found)' })
  Settings file            : $envFile


DASHBOARD ADDRESSES
---------------------------------------------------------------------
  On this PC             :  http://localhost:5000
  From phones / other PCs on the same network (port 5000 is open):
$addr
=====================================================================
"@
Set-Content -Path $OutFile -Value $text -Encoding UTF8
# only Administrators, SYSTEM and the person who ran setup may open it
try {
    & icacls $OutFile /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" "$($env:USERDOMAIN)\$($env:USERNAME):F" | Out-Null
} catch {}
Write-Output $OutFile
exit 0
