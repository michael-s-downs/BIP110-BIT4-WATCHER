<#
install-or-update-toast-listener-task.ps1
PS 5.1 compatible

Creates or updates the "BIP110 Toast Listener" Scheduled Task to run toast-listener.ps1
in the interactive user session at logon. Copies toast-listener.ps1 into a stable per-user folder.
#>

param(
    [string]$TaskName = "BIP110 Toast Listener",

    # Default: C:\Users\<user>\BIP110Watch\toast-listener.ps1
    [string]$InstallDir = (Join-Path $env:USERPROFILE "BIP110Watch"),

    # Default source: repo root toast-listener.ps1 (script is expected in repo \scripts\)
    [string]$SourceListenerPath = (Join-Path $PSScriptRoot "..\toast-listener.ps1"),

    [ValidateSet("Minimized","Hidden","Normal")]
    [string]$WindowStyle = "Minimized",

    # Restart after updating (default true)
    [bool]$Restart = $true
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO]  $msg" }
function Write-Warn($msg) { Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Err ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Resolve-PathOrNull {
    param([string]$Path)
    try { (Resolve-Path -Path $Path -ErrorAction Stop).Path } catch { $null }
}

# Resolve / normalize paths
$installDirFull = Resolve-PathOrNull $InstallDir
if (-not $installDirFull) { $installDirFull = $InstallDir }

$destListenerPath = Join-Path $installDirFull "toast-listener.ps1"
$sourceFull = Resolve-PathOrNull $SourceListenerPath

Write-Info "TaskName: $TaskName"
Write-Info "InstallDir: $installDirFull"
Write-Info "SourceListenerPath: $SourceListenerPath"
Write-Info "DestListenerPath: $destListenerPath"
Write-Info "WindowStyle: $WindowStyle"

# Validate source exists
if (-not $sourceFull -or -not (Test-Path $sourceFull)) {
    throw "Cannot find toast-listener.ps1 to copy. Expected at: $SourceListenerPath"
}

# Ensure install directory exists and copy listener into place
New-Item -ItemType Directory -Force -Path $installDirFull | Out-Null
Copy-Item -Force $sourceFull $destListenerPath
Write-Info "Copied listener script to: $destListenerPath"

# Build Scheduled Task
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument `
  "-NoProfile -ExecutionPolicy Bypass -WindowStyle $WindowStyle -File `"$destListenerPath`""

$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries

# Run in current interactive user context (toasts!)
$principal = New-ScheduledTaskPrincipal `
  -UserId "$env:USERDOMAIN\$env:USERNAME" `
  -LogonType Interactive `
  -RunLevel Highest

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal

# Update behavior: stop/remove existing, then create
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Warn "Existing task found. Stopping and removing before updating..."
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Info "Removed existing task: $TaskName"
}

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Write-Info "Registered task: $TaskName"

if ($Restart) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Info "Started task: $TaskName"
}

Write-Info "Done."
Write-Info 'Test: curl.exe -X POST http://localhost:8099/ -d "TEST: toast listener installed or updated."'