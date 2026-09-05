# tools/launch_detached.ps1 - start a long run that OUTLIVES its launcher.
#
# WHY THIS EXISTS (4/5 September 2026)
# ------------------------------------
# A 1077-example training run was killed twice-over-investigated and finally traced
# to the launcher, not the machine. The agent harness that started it as a background
# job writes "[killed]" into the job's own output file - a marker distinct from
# "[exited with code N]" - and every background job observed so far that ran past
# ~26 minutes carried it, while every job under ~25 minutes exited normally.
#
# Hours were spent searching the Windows Event Log, the Task Scheduler, supervisor.py
# and every taskkill/Stop-Process in the repo. All of it came back empty, because the
# killer was never on this machine. The nvlddmkm errors in the System log were a
# CONSEQUENCE of abrupt CUDA teardown, not a cause: there is no Display 4101 in ten
# days, so no TDR reset ever happened.
#
# THE RULE THIS ENFORCES: a run that survives its launcher cannot be killed by its
# launcher. Start-Process detaches the child from this shell's job/process tree, so
# the training continues even if the tool session that started it is torn down. The
# caller then POLLS THE LOG instead of owning the process.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\launch_detached.ps1 `
#       -Exe venv_train\Scripts\python.exe `
#       -Arguments "training/train_lora.py --out models/adapters/k1b_A --resume" `
#       -Log claude\reports\K1B_RUN_A.log
param(
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string]$Arguments,
    [Parameter(Mandatory=$true)][string]$Log
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$exePath = if ([System.IO.Path]::IsPathRooted($Exe)) { $Exe } else { Join-Path $repo $Exe }
$logPath = if ([System.IO.Path]::IsPathRooted($Log)) { $Log } else { Join-Path $repo $Log }
$errPath = [System.IO.Path]::ChangeExtension($logPath, ".err.log")

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logPath) | Out-Null

# A marker the poller can key on, written BEFORE the child starts so a launch that
# fails outright is still distinguishable from one that never began.
"=== DETACHED LAUNCH $(Get-Date -Format o) ===" | Out-File -FilePath $logPath -Encoding utf8
"exe  : $exePath"   | Out-File -FilePath $logPath -Append -Encoding utf8
"args : $Arguments" | Out-File -FilePath $logPath -Append -Encoding utf8

# 5 Sep 2026: the detached suite finished, then died on its LAST line - cp1252 could not
# encode a replacement character in the captured stdout, and _suite_brainfix.out.log was
# left at 0 bytes with the verdict only recoverable from memory/suite_runs.jsonl. A detached
# process inherits no PYTHONIOENCODING from anyone, so it is set here, once, for every child.
# Whatever the harness or a console had is irrelevant: the child gets utf-8 or it does not start.
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$p = Start-Process -FilePath $exePath `
                   -ArgumentList $Arguments `
                   -WorkingDirectory $repo `
                   -RedirectStandardOutput $logPath.Replace(".log", ".out.log") `
                   -RedirectStandardError $errPath `
                   -WindowStyle Hidden `
                   -PassThru

# The pid is the handle the poller needs; the process itself is nobody's child now.
$pidFile = [System.IO.Path]::ChangeExtension($logPath, ".pid")
$p.Id | Out-File -FilePath $pidFile -Encoding ascii
"pid  : $($p.Id)" | Out-File -FilePath $logPath -Append -Encoding utf8

Write-Output "DETACHED_PID=$($p.Id)"
Write-Output "STDOUT=$($logPath.Replace('.log', '.out.log'))"
Write-Output "STDERR=$errPath"
Write-Output "PIDFILE=$pidFile"
