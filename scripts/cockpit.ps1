<#
    scripts/cockpit.ps1 — launch the cockpit and open the browser.

    MANUAL LAUNCH ONLY. Nothing is registered with schtasks for v1: a read-only
    window that starts itself is a window nobody chose to open, and the terminal
    bridge inside it should exist only while somebody is looking at it.

    The session token for the terminal is printed to THIS console by the server
    and nowhere else. Leave the console open; paste the token into the terminal
    panel when you want a shell.

        powershell -ExecutionPolicy Bypass -File scripts\cockpit.ps1
        powershell -ExecutionPolicy Bypass -File scripts\cockpit.ps1 -Port 5060
        powershell -ExecutionPolicy Bypass -File scripts\cockpit.ps1 -Snapshot
#>
param(
    [int]$Port = 5055,
    [switch]$Snapshot,
    [switch]$NoBrowser,
    [switch]$NoTerminal
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo "venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "venv python not found at $py" -ForegroundColor Red
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"
Set-Location $repo

if ($Snapshot) {
    Write-Host "Writing a self-contained snapshot (no server, no browser)..."
    & $py -m cockpit.snapshot
    exit $LASTEXITCODE
}

$args = @("-m", "cockpit.server", "--port", "$Port")
if ($NoTerminal) { $args += "--no-terminal" }

if (-not $NoBrowser) {
    # A short delay so the first request does not race the bind.
    Start-Job -ScriptBlock {
        param($u) Start-Sleep -Seconds 2; Start-Process $u
    } -ArgumentList "http://127.0.0.1:$Port" | Out-Null
}

Write-Host "CORTEX++ cockpit -> http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "Read-only over memory/. Ctrl+C to stop." -ForegroundColor DarkGray
& $py @args
