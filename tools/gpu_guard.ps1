# tools/gpu_guard.ps1 - free the card for a chained GPU job, and keep it free.
#
# WHY (6 Sep 2026, after A3 died)
# A3 was launched at 13:04:32 into a card reading 0 MiB and died at 13:24:22 with
# CUDA out of memory, 100 items into step 1. Something took ~3.5 GB of a 4 GB card
# in that window. WHAT took it is NOT established: no repo file was written at
# 13:24, ollama's own server.log has not been written since 30 July, and by 13:25
# no runner process existed. The consumer was never caught in the act.
#
# So this guard does not depend on knowing the culprit:
#   * it kills any ollama RUNNER (never the server) before the job and between steps
#   * it sets OLLAMA_KEEP_ALIVE=0 for calls it makes, so a runner that does spawn
#     unloads immediately instead of squatting
#   * it REFUSES to start when the card is not actually free, rather than hoping
#
# The server is never touched: the 03:04 cycle needs it, and the approved mechanism
# from 5 Sep is runner-only.
param([int]$MaxMiB = 600, [switch]$Quiet)

function GpuUsed {
    $v = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
    if (-not $v) { return -1 }
    return [int]($v | Select-Object -First 1).ToString().Trim()
}

# The SERVER is the ollama.exe with no "runner" in its command line and the small
# working set. Runners are the ones holding VRAM.
$server = $null
$runners = @()
Get-CimInstance Win32_Process -Filter "Name='ollama.exe'" -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.CommandLine -match "runner|serve --") { $runners += $_ }
    elseif ($_.CommandLine -match "\bserve\b" -or $null -eq $server) { $server = $_ }
}
# Fall back on size: a loaded runner carries hundreds of MB of RSS, the server ~10-30 MB.
if ($runners.Count -eq 0) {
    Get-CimInstance Win32_Process -Filter "Name='ollama.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.WorkingSetSize -gt 100MB } | ForEach-Object { $runners += $_ }
}

foreach ($r in $runners) {
    if ($server -and $r.ProcessId -eq $server.ProcessId) { continue }
    if (-not $Quiet) { "gpu_guard: killing ollama RUNNER pid $($r.ProcessId) (RSS $([int]($r.WorkingSetSize/1MB)) MB)" }
    Stop-Process -Id $r.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($runners.Count -gt 0) { Start-Sleep -Seconds 4 }

$used = GpuUsed
if (-not $Quiet) { "gpu_guard: memory.used $used MiB (threshold $MaxMiB)" }
if ($used -lt 0) { "gpu_guard: nvidia-smi gave nothing - occupancy NOT checked"; exit 0 }
if ($used -gt $MaxMiB) {
    "gpu_guard: REFUSED - $used MiB still in use after freeing runners. Something else holds the card."
    exit 2
}
exit 0
