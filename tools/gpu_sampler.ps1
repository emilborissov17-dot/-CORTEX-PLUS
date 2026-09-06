# tools/gpu_sampler.ps1 - name the consumer, or rule one out.
#
# WHY (6 Sep 2026, after A3 died a SECOND time)
# Death 1 at 13:24, item 100 of 223: "CUDA error: out of memory". Death 2 at 15:24,
# item 125 of 223: CUBLAS_STATUS_EXECUTION_FAILED. Both inside the same loop, both
# memory-class, and after the first one I wrote that the consumer "was never caught
# in the act" because nothing was watching the card. This watches it.
#
# It samples memory.used AND the per-process compute apps, so a third death is read
# off a timeline rather than argued from absence: either another pid appears in the
# seconds before the crash, or none does and the pressure is the job's own.
param(
    [string]$Out = "claude\reports\K1B_A3_gpu.log",
    [int]$IntervalSec = 20,
    [int]$WatchPid = 0
)
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
"# started {0:yyyy-MM-dd HH:mm:ss}  interval ${IntervalSec}s  watching pid $WatchPid" -f (Get-Date) |
    Out-File -FilePath $Out -Append -Encoding utf8

while ($true) {
    if ($WatchPid -gt 0 -and -not (Get-Process -Id $WatchPid -ErrorAction SilentlyContinue)) {
        "{0:HH:mm:ss}  watched pid $WatchPid is gone - sampler stopping" -f (Get-Date) |
            Out-File -FilePath $Out -Append -Encoding utf8
        break
    }
    $used = (& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
    # Per-process rows are empty on consumer cards under WDDM; when they ARE
    # populated they name the consumer outright, so both are recorded and the log
    # says which one it got.
    $apps = (& nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>$null) -join "; "
    if (-not $apps) { $apps = "(no per-process rows - WDDM)" }
    "{0:HH:mm:ss}  used={1} MiB  apps: {2}" -f (Get-Date), $used, $apps |
        Out-File -FilePath $Out -Append -Encoding utf8

    # 6 Sep, death 4: A3 was relaunched at 16:02 into a card that ALREADY held an
    # ollama runner (pid 428680, spawned 15:58:10), because the launcher only
    # REPORTED gpu memory and never acted on it. Sampling without acting is how the
    # same process gets to kill the job twice. Runners only - the 03:04 cycle needs
    # the server, and killing that would trade one outage for another.
    Get-CimInstance Win32_Process -Filter "Name='ollama.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "runner" } | ForEach-Object {
            "{0:HH:mm:ss}  KILLING ollama runner pid {1} - it is on the card while the job runs" -f (Get-Date), $_.ProcessId |
                Out-File -FilePath $Out -Append -Encoding utf8
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds $IntervalSec
}
