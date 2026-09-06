# tools/detached_watchdog.ps1 - one line when a detached job dies, wherever it dies.
#
# THE GAP THIS FILLS (6 Sep 2026)
# A3 was launched at 13:04:32 and died at 13:24:22 with CUDA out of memory, 100
# items into step 1 of 3. NOTHING RECORDED IT. The chain wrote to its own err.log
# and stopped; night_events.jsonl said nothing; the launcher log's last line still
# read "A3 started". It was found by hand, an hour and a half later, only because
# somebody happened to look at the GPU and wonder why it was idle.
#
# A detached job is the one kind of work with no observer by construction: it
# outlives the session that started it, so if it does not report its own death
# nobody learns of it until they check. This polls the pid and writes ONE line to
# night_events.jsonl and one to the launcher log when it exits - exit code, wall
# time, the last stdout line and the tail of stderr, which together are usually
# enough to say what happened without opening anything.
#
# Started by launch_detached.ps1 as its own detached process, so watching costs the
# launcher nothing and the watchdog cannot hold the parent open.
param(
    [Parameter(Mandatory = $true)][int]$WatchPid,
    [Parameter(Mandatory = $true)][string]$Log,
    [int]$IntervalSec = 60
)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$outLog = $Log.Replace(".log", ".out.log")
$errLog = [System.IO.Path]::ChangeExtension($Log, ".err.log")
$started = Get-Date

while ($true) {
    $p = Get-Process -Id $WatchPid -ErrorAction SilentlyContinue
    if (-not $p) { break }
    Start-Sleep -Seconds $IntervalSec
}

$secs = [int]((Get-Date) - $started).TotalSeconds
$code = "unknown"          # a detached pid we did not parent has no exit code to read
$lastOut = ""
$errTail = ""
if (Test-Path $outLog) {
    $lines = @(Get-Content $outLog -ErrorAction SilentlyContinue | Where-Object { $_.Trim() })
    if ($lines.Count) { $lastOut = $lines[-1] }
}
if (Test-Path $errLog) {
    $raw = (Get-Content $errLog -Raw -ErrorAction SilentlyContinue)
    if ($raw) { $errTail = $raw.Substring([Math]::Max(0, $raw.Length - 200)) }
}

# "observed after" and not "after": $secs is how long the WATCHDOG waited, not how
# long the job lived. A job that dies before the first poll shows 0 here, which
# would read as "died instantly" if the label were wrong. The job's own duration is
# in its report or its logs; this line is about detection.
$ranFor = ""
if (Test-Path $Log) { $ranFor = " job_started={0:HH:mm:ss}" -f (Get-Item $Log).CreationTime }
$line = "DETACHED EXIT pid=$WatchPid code=$code observed_after=${secs}s$ranFor, last out.log line: $lastOut, err.log tail: $errTail"
$line | Out-File -FilePath $Log -Append -Encoding utf8

# night_events.jsonl is the file the morning check reads. One line, best effort, and
# it PRINTS if it cannot write - a recorder that fails silently is the same defect
# one level up.
try {
    $rec = [ordered]@{
        ts      = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
        subject = "detached job exited"
        outcome = "DETACHED_EXIT"
        gate    = "watchdog"
        step    = [System.IO.Path]::GetFileNameWithoutExtension($Log)
        detail  = $line
        pid     = $WatchPid
        observed_after_sec = $secs
    }
    $json = $rec | ConvertTo-Json -Compress
    Add-Content -Path (Join-Path $repo "memory\night_events.jsonl") -Value $json -Encoding utf8
} catch {
    Write-Output "watchdog: could not write night_events.jsonl: $_"
}
Write-Output $line
