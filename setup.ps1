# Installs or updates the portal on this computer. Run it with setup.bat (double-click).
#
#   1. checks Python 3.12+
#   2. creates backend\.venv and installs the libraries (the first time: 5-15 minutes)
#   3. uses the built portal pages (frontend\dist) - Node.js is only needed if they are missing
#   4. makes the portal start by itself at Windows login (task "Email Meeting Portal")
#   5. starts it and opens http://localhost:8000, where the Setup page asks for your keys
#
# Run it again after downloading a new version: it updates everything and keeps your data.
# -NoAutoStart: install only, without the Windows task (start: backend\.venv\Scripts\python backend\run_portal.py)

param([switch]$NoAutoStart)

$ErrorActionPreference = 'Stop'
$TaskName = 'Email Meeting Portal'
$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$VenvPython = Join-Path $Backend '.venv\Scripts\python.exe'
$Url = 'http://localhost:8000'

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nERROR: $text" -ForegroundColor Red; exit 1 }

function Test-Python($command, $arguments) {
    # True when this command runs Python 3.12 or newer (the Microsoft Store "python" alias does not).
    try {
        $out = & $command @arguments -c 'import sys; print(sys.version_info >= (3, 12))' 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True')
    } catch { return $false }
}

function Stop-Portal {
    # Only this folder's portal: another copy on this computer keeps running.
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task -and "$($task.Actions[0].Execute)".StartsWith($Backend, 'OrdinalIgnoreCase')) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    $script = Join-Path $Backend 'run_portal.py'
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($script) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Test-Portal {
    try { return (Invoke-WebRequest "$Url/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 }
    catch { return $false }
}

Write-Host 'Email & Meeting Portal - setup' -ForegroundColor Green
Write-Host "Folder: $Root"
if ($Root -match 'OneDrive') {
    Write-Host 'Warning: this folder is inside OneDrive. Syncing can break the database.' -ForegroundColor Yellow
    Write-Host '         A folder like Documents\Communication_Portal (not synced) is better.' -ForegroundColor Yellow
}

# ---- 1. Python ------------------------------------------------------------------------
Step '1/5 Checking Python 3.12 or newer'
$python = $null
foreach ($candidate in @(@('py', @('-3')), @('python', @()), @('python3', @()))) {
    if ((Get-Command $candidate[0] -ErrorAction SilentlyContinue) -and (Test-Python $candidate[0] $candidate[1])) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    Fail ('Python 3.12 or newer was not found. Install it from https://www.python.org/downloads/ ' +
          '(tick "Add python.exe to PATH"), then run setup.bat again.')
}
$version = & $python[0] @($python[1]) --version
Write-Host "Found: $version"

# ---- 2. Libraries ---------------------------------------------------------------------
Step '2/5 Installing the libraries (the first time takes 5-15 minutes)'
Stop-Portal  # an update cannot replace files the running portal is using
if (-not (Test-Path $VenvPython)) {
    & $python[0] @($python[1]) -m venv (Join-Path $Backend '.venv')
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create backend\.venv.' }
}
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip | Out-Null
& $VenvPython -m pip install --disable-pip-version-check -e $Backend
if ($LASTEXITCODE -ne 0) { Fail 'Installing the libraries failed. Check the internet connection and run setup.bat again.' }

# ---- 3. Portal pages ------------------------------------------------------------------
Step '3/5 Portal pages'
if (Test-Path (Join-Path $Frontend 'dist\index.html')) {
    Write-Host 'Ready (built pages are included).'
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location $Frontend
    try {
        npm install
        if ($LASTEXITCODE -eq 0) { npm run build }
        if ($LASTEXITCODE -ne 0) { Fail 'Building the pages failed.' }
    } finally { Pop-Location }
} else {
    Fail 'The folder frontend\dist is missing and Node.js is not installed. Download the project again.'
}

# ---- 4. Start with Windows ------------------------------------------------------------
if ($NoAutoStart) {
    Step '4/5 Start with Windows: skipped (-NoAutoStart)'
} else {
    Step '4/5 Making the portal start at Windows login'
    $pythonw = Join-Path $Backend '.venv\Scripts\pythonw.exe'
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$(Join-Path $Backend 'run_portal.py')`"" -WorkingDirectory $Backend
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Task '$TaskName' is ready."
}

# ---- 5. Start ---------------------------------------------------------------------------
Step '5/5 Starting the portal'
if ($NoAutoStart) {
    Write-Host 'Start it with:  backend\.venv\Scripts\python backend\run_portal.py'
    exit 0
}
if (Test-Portal) { Fail 'Port 8000 is already used by another program. Close it and run setup.bat again.' }
Start-ScheduledTask -TaskName $TaskName
$started = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    if (Test-Portal) { $started = $true; break }
}
if (-not $started) {
    Fail "The portal did not start. See the log: $(Join-Path $Backend 'data\logs\portal.log')"
}
Write-Host "`nDone. The portal runs at $Url and starts by itself when you log in to Windows." -ForegroundColor Green
Write-Host 'Next: fill in the Setup page (password and keys), then Settings -> Connect Google.'
Start-Process $Url
