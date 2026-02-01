# toast-listener.ps1
# Listens on http://+:8099/ and shows a Windows toast for each POST body.

param(
    [int]$Port = 8099,
    [string]$ToastTitle = "BIP110 Watch",
    [string]$LogDir = (Join-Path $env:ProgramData "BIP110Watch\logs")
)

$ErrorActionPreference = "Stop"
$prefix   = "http://+:$Port/"
$logFile  = Join-Path $LogDir "toast-listener.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log {
    param(
        [Parameter(Mandatory=$true)][string]$Message,
        [ValidateSet("INFO","WARN","ERROR")][string]$Level = "INFO"
    )
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$ts][$Level] $Message"
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

# --- Fail-fast module import ---
try {
    Import-Module BurntToast -ErrorAction Stop
    if (-not (Get-Command New-BurntToastNotification -ErrorAction SilentlyContinue)) {
        throw "BurntToast imported but New-BurntToastNotification not found."
    }
    Write-Log "BurntToast loaded OK. PSVersion=$($PSVersionTable.PSVersion) Prefix=$prefix"
} catch {
    Write-Log "FAILED to load BurntToast: $($_.Exception.Message)" "ERROR"
    Write-Log "PSModulePath=$env:PSModulePath" "ERROR"
    throw
}

$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add($prefix)

try {
    $listener.Start()
    Write-Log "This is your Toast-Listener, listening on $prefix . Keep this window open to keep listening, but it may be minimized."
} catch {
    Write-Log "FAILED to start listener on $prefix : $($_.Exception.Message)" "ERROR"
    Write-Log "Tip: http://+:PORT requires admin; try http://localhost:PORT for non-admin testing." "ERROR"
    throw
}

while ($listener.IsListening) {
    $ctx = $null
    $resp = $null

    try {
        $ctx  = $listener.GetContext()
        $req  = $ctx.Request
        $resp = $ctx.Response

        $resp.StatusCode  = 200
        $resp.ContentType = "text/plain"

        if ($req.HttpMethod -ne "POST") {
            $msg = "Use POST"
            $bytes = [Text.Encoding]::UTF8.GetBytes($msg)
            $resp.OutputStream.Write($bytes, 0, $bytes.Length)
            $resp.Close()
            continue
        }

        # Read body safely (may be empty)
        $body = ""
        $enc = if ($req.ContentEncoding) { $req.ContentEncoding } else { [Text.Encoding]::UTF8 }

        $reader = $null
        try {
            $reader = [IO.StreamReader]::new($req.InputStream, $enc)
            $body = $reader.ReadToEnd()
        } finally {
            if ($reader) { $reader.Dispose() }
        }

        if ([string]::IsNullOrWhiteSpace($body)) { $body = "(empty body)" }

        # Log a trimmed body (avoid megaspam)
        $bodyTrim = $body
        if ($bodyTrim.Length -gt 240) { $bodyTrim = $bodyTrim.Substring(0,240) + "..." }
        Write-Log "POST from $($req.RemoteEndPoint) body='$bodyTrim'"

        try {
            New-BurntToastNotification -Text $ToastTitle, $body
        } catch {
            Write-Log "Toast FAILED: $($_.Exception.Message)" "ERROR"
        }

        $bytes = [Text.Encoding]::UTF8.GetBytes("ok")
        $resp.OutputStream.Write($bytes, 0, $bytes.Length)
        $resp.Close()
    }
    catch {
        Write-Log "Listener error: $($_.Exception.Message)" "ERROR"
        try { if ($resp) { $resp.Close() } } catch {}
        Start-Sleep -Milliseconds 200
    }
}