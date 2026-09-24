# tools/ollama_serve.ps1 - the ONE way `ollama serve` is started, and it writes a log.
#
# WHY (24 Sep 2026, task #19 e). Phase 1 could not say when a model was loaded or
# unloaded, by whom, or what a switch cost: the server running since 12:59 had been
# started by pulse_continuum with Popen and no redirection, and
# %LOCALAPPDATA%\Ollama\server.log had been 0 bytes since 30 Jul. Every starter now
# calls this script (experiments/pulse/pulse_continuum.py, experiments/collector/
# run_collector.ps1), so the server's own log exists whoever wakes it.
#
#   logs/ollama_server.log      the server's log (Ollama logs to stderr)
#   logs/ollama_server.out.log  its stdout
#   logs/ollama_server.pid      the pid this script started
# Rotated at every start (the server holds the live file open, and Start-Process
# cannot append): the last 3 runs are kept as .1 .. .3.
# OLLAMA_DEBUG is forced off. Other OLLAMA_* variables are inherited unchanged.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\ollama_serve.ps1            # start if down
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\ollama_serve.ps1 -Restart   # replace a running one
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\ollama_serve.ps1 -WarmCore   # + hold the cycle model
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\ollama_serve.ps1 -SelfTest
#
# -WarmCore (task #8 part 1): after the server is up, load the cycle's one model
# (config/model_window.json "cycle_local_model", default cortex-l1b-3b:latest) with
# keep_alive -1 and verify it on /api/ps. A cycle never loads a model itself: a
# local call whose model is not resident is refused ("warm core absent"). The
# CORTEX_WarmCore scheduled task (tools/install_warm_core_task.ps1) runs this at
# logon and at startup.
param([switch]$Restart, [switch]$SelfTest, [switch]$WarmCore)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repo "logs"
$log = Join-Path $logDir "ollama_server.log"
$out = Join-Path $logDir "ollama_server.out.log"
$pidFile = Join-Path $logDir "ollama_server.pid"
$exe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$Keep = 3

function Test-Up {
    try { $null = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3; return $true }
    catch { return $false }
}

function Rotate([string]$path) {
    if (-not (Test-Path $path)) { return }
    for ($i = $Keep - 1; $i -ge 1; $i--) {
        $src = "$path.$i"; $dst = "$path.$($i + 1)"
        if (Test-Path $src) { Move-Item -Force $src $dst }
    }
    Move-Item -Force $path "$path.1"
}

if ($SelfTest) {
    Write-Output "tools/ollama_serve.ps1 -SelfTest"
    Write-Output ("  {0}  ollama.exe                ({1})" -f $(if (Test-Path $exe) {"LIVE "} else {"INERT"}), $exe)
    Write-Output ("  {0}  server answers on 11434" -f $(if (Test-Up) {"LIVE "} else {"INERT"}))
    $logged = (Test-Path $log) -and ((Get-Item $log).Length -gt 0)
    Write-Output ("  {0}  server log has content    ({1})" -f $(if ($logged) {"LIVE "} else {"INERT"}), $log)
    $mine = $null
    if (Test-Path $pidFile) { $mine = Get-Process -Id ([int](Get-Content $pidFile -Raw)) -ErrorAction SilentlyContinue }
    Write-Output ("  {0}  running server was started here (pid file)" -f $(if ($mine) {"LIVE "} else {"INERT"}))
    exit 0
}

if (-not (Test-Path $exe)) { Write-Error "ollama.exe not found at $exe"; exit 2 }

function Get-CoreModel {
    $cfg = Join-Path $repo "config\model_window.json"
    try { $m = (Get-Content $cfg -Raw | ConvertFrom-Json).cycle_local_model } catch { $m = $null }
    if (-not $m) { $m = "cortex-l1b-3b:latest" }
    return $m
}

function Invoke-WarmCore {
    $m = Get-CoreModel
    $body = @{ model = $m; keep_alive = -1 } | ConvertTo-Json -Compress
    try {
        $null = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:11434/api/generate" -Body $body `
                                  -ContentType "application/json" -TimeoutSec 300
    } catch { Write-Output "warm core: load of $m FAILED - $($_.Exception.Message)"; exit 4 }
    $names = @((Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/ps" -TimeoutSec 5).models | ForEach-Object { $_.name })
    if ($names -contains $m) { Write-Output "warm core: $m resident, keep_alive -1"; exit 0 }
    Write-Output "warm core: $m NOT resident after the load (resident: $($names -join ', '))"; exit 5
}

if (Test-Up) {
    if (-not $Restart) {
        if ($WarmCore) { Write-Output "ollama: already running"; Invoke-WarmCore }
        Write-Output "ollama: already running - not started (use -Restart to replace it)"; exit 0
    }
    Get-Process -Name "ollama" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $exe } |
        ForEach-Object { Write-Output "ollama: stopping pid $($_.Id)"; Stop-Process -Id $_.Id -Force }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Test-Up) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Rotate $log
Rotate $out
$env:OLLAMA_DEBUG = "0"
$p = Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden -PassThru `
                   -RedirectStandardError $log -RedirectStandardOutput $out
Set-Content -Path $pidFile -Value $p.Id -Encoding ascii
$deadline = (Get-Date).AddSeconds(30)
while (-not (Test-Up) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
if (Test-Up) {
    Write-Output "ollama: started pid $($p.Id), log $log"
    if ($WarmCore) { Invoke-WarmCore }
    exit 0
}
Write-Output "ollama: pid $($p.Id) started but 11434 does not answer after 30 s - see $log"
exit 3
