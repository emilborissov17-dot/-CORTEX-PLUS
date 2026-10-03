# experiments/kill_probe/probe.ps1 - a timer that records its own life (C-KILL-1, 3 Oct 2026).
#
# Question: why do Claude Code background jobs vanish at about 25-26 minutes? Two copies run at
# the same moment, one as a Claude Code background shell, one through tools/launch_detached.ps1.
# Every 30 s each appends ONE line to out/<Label>.log; nobody has to watch (R47).
# No network, no model.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File experiments\kill_probe\probe.ps1 -Label A -Minutes 45
param(
    [Parameter(Mandatory=$true)][string]$Label,
    [int]$Minutes = 45
)

$ErrorActionPreference = "Stop"
$dir = Join-Path $PSScriptRoot "out"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$log = Join-Path $dir "$Label.log"
$t0 = Get-Date

function Chain {
    $out = @()
    $id = $PID
    for ($i = 0; $i -lt 8 -and $id; $i++) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        if (-not $p) { $out += "${id}:gone"; break }
        $out += "$($p.ProcessId):$($p.Name)"
        $id = $p.ParentProcessId
    }
    return ($out -join ">")
}

function Line([string]$tag) {
    $os = Get-CimInstance Win32_OperatingSystem
    $freeMb = [math]::Round($os.FreePhysicalMemory / 1KB)
    $commit = [math]::Round(100 * ($os.TotalVirtualMemorySize - $os.FreeVirtualMemory) / $os.TotalVirtualMemorySize, 1)
    $age = [int]((Get-Date) - $t0).TotalSeconds
    $utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $row = "$tag utc=$utc age_s=$age pid=$PID free_mb=$freeMb commit_pct=$commit chain=$(Chain)"
    Add-Content -Path $log -Value $row -Encoding utf8
}

Line "START"
$end = $t0.AddMinutes($Minutes)
while ((Get-Date) -lt $end) {
    Start-Sleep -Seconds 30
    Line "TICK"
}
Line "END clean"
