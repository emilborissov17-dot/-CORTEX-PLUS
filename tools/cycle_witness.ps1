# tools/cycle_witness.ps1 - the cycle is started BY a witness, and the witness writes down how it ended.
#
# WHY THIS EXISTS (24 Sep 2026)
# -----------------------------
# Six catch-up cycles in two days (23-24 Sep) died with no record of HOW: no
# traceback, no exit code, no blackbox `exit` row. The reaper that was supposed
# to record the exit code (memory/cycle_reaper.py) was a Python process spawned by
# the same tick as the cycle, and it vanished with it - so the one instrument
# built to answer "how did it end" was taken out by the same event it was meant
# to observe. claude/reports/STEP_AUDIT_2026-09-24.md Parts 3-5 have the evidence.
#
# So the witness is a process of a DIFFERENT KIND from the thing it watches:
# PowerShell, not Python; it is the PARENT of the cycle, not a sibling; and
# supervisor.py starts it with CREATE_BREAKAWAY_FROM_JOB so it does not share the
# Task Scheduler job of the tick that launched it.
#
# WHAT IT WRITES - memory/witness.jsonl, one JSON object per line, fsync'd:
#   start: {event, cycle_id, witness_pid, witness_parent_pid, cmd_pid,
#           launcher_pid, cycle_pid, cycle_pid_source, cmdline, log, ts}
#   exit:  {event, cycle_id, cycle_pid, exit_code, exit_code_hex, exit_source,
#           launcher_exit_code, wall_seconds, meaning, ts}
#
# IF THE WITNESS ITSELF DIES, a start row with no exit row for the same cycle_id
# IS the evidence: the watcher was killed, so the death was not a normal exit of
# the cycle. The supervisor reads exactly that absence as "unexplained" and does
# not restart (supervisor.py, witness_exit_for()).
#
# THE EXIT CODES, MEASURED ON THIS MACHINE 24 Sep 2026 - not taken from docs:
#   taskkill /F on the interpreter     -> 1          (NOT -1)
#   Stop-Process / Process.Kill        -> -1 (0xFFFFFFFF)
#   taskkill /F on the venv LAUNCHER   -> launcher 1, and the interpreter dies
#                                         with 0 - the launcher's job kills it.
# So 1 is ambiguous (taskkill /F OR an uncaught Python exception) and is split by
# whether the log ENDS in a traceback; and 0 is "clean" only if the launcher also
# returned 0 - otherwise it is the launcher-kill signature, never a clean exit.
#
# CHAIN: witness -> cmd.exe (does the `> log 2>&1`, so stdout and stderr land in
# ONE file exactly as supervisor.spawn_cycle did before) -> venv\Scripts\python.exe
# (the launcher) -> the real interpreter. The witness opens a handle to each as
# soon as it sees it, so an exit code can still be read after the process is gone.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\cycle_witness.ps1 -SelfTest
param(
    [string]$Exe = "",
    # The child's arguments as a base64-encoded JSON array of strings. JSON+base64
    # because the arguments cross TWO command-line parsers (Python's list2cmdline
    # into powershell.exe, then cmd.exe); a quote that survives one is mangled by
    # the other. Each element is quoted for cmd.exe here, once.
    [string]$ArgsB64 = "",
    [string]$Log = "",
    [string]$WitnessLog = "",
    [string]$CycleId = "",
    [string]$WorkDir = "",
    [switch]$SelfTest
)
$ErrorActionPreference = "Continue"

function Now-Iso { (Get-Date).ToUniversalTime().ToString("o") }

function Write-Row([System.Collections.Specialized.OrderedDictionary]$row) {
    # One line, appended, flushed to the platter before returning. A witness that
    # buffers is a witness whose last sentence dies with it.
    $line = ($row | ConvertTo-Json -Compress -Depth 4) + "`n"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($line)
    $dir = Split-Path -Parent $WitnessLog
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $fs = [System.IO.File]::Open($WitnessLog, [System.IO.FileMode]::Append,
                                 [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
    try { $fs.Write($bytes, 0, $bytes.Length); $fs.Flush($true) } finally { $fs.Close() }
}

function Get-Children([int]$ParentPid, [datetime]$NotBefore) {
    # Children by ParentProcessId AND created no earlier than the parent. The
    # creation-time guard is the whole point: a parent pid is only a number, and
    # Windows hands freed numbers out again - matching on it alone is how an
    # unrelated process gets adopted (Part 5 of the step audit).
    $out = @()
    try {
        foreach ($p in (Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentPid" -ErrorAction Stop)) {
            if ($p.CreationDate -ge $NotBefore.AddSeconds(-1)) { $out += $p }
        }
    } catch { }
    return $out
}

function Open-Proc([int]$ProcId) {
    try { $p = [System.Diagnostics.Process]::GetProcessById($ProcId); $null = $p.Handle; return $p } catch { return $null }
}

function Get-Meaning($code, $launcherCode, [string]$logPath) {
    if ($null -eq $code) { return "unknown (no handle was open to read an exit code)" }
    if ($code -eq -1) { return "killed (taskkill /F or TerminateProcess)" }
    if ($code -eq -1073741510) { return "console closed / Ctrl+C" }          # 0xC000013A
    if ($code -eq 0) {
        if ($null -ne $launcherCode -and $launcherCode -ne 0) {
            return "killed through its launcher (the launcher exited $launcherCode and its job took the interpreter down, which then reports 0)"
        }
        return "clean exit"
    }
    if ($code -eq 1) {
        $tb = $false
        try { $tb = [bool](Get-Content -LiteralPath $logPath -Tail 60 -ErrorAction Stop | Select-String -SimpleMatch "Traceback (most recent call last)") } catch { }
        if ($tb) { return "python error, see log" }
        return "killed (taskkill /F or TerminateProcess: exit code 1 and no traceback at the end of the log)"
    }
    return "python error, see log"
}

if ($SelfTest) {
    $repo = Split-Path -Parent $PSScriptRoot
    $py = Join-Path $repo "venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "python.exe" }
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("cycle_witness_selftest_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $wl = Join-Path $tmp "witness.jsonl"; $lg = Join-Path $tmp "child.log"
    $a = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -Compress @("-c", "import time,sys; print('selftest child'); time.sleep(2); sys.exit(0)"))))
    & powershell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Exe $py -ArgsB64 $a -Log $lg -WitnessLog $wl -CycleId "selftest" -WorkDir $tmp
    $rows = @(Get-Content $wl -ErrorAction SilentlyContinue | ForEach-Object { $_ | ConvertFrom-Json })
    $start = $rows | Where-Object { $_.event -eq "start" } | Select-Object -First 1
    $exit  = $rows | Where-Object { $_.event -eq "exit" }  | Select-Object -First 1
    $childOut = (Get-Content $lg -Raw -ErrorAction SilentlyContinue)
    Write-Output "tools/cycle_witness.ps1 -SelfTest (PowerShell $($PSVersionTable.PSVersion))"
    Write-Output ("  {0}  witness row written and fsync'd       ({1})" -f $(if ($start) {"LIVE "} else {"INERT"}), $wl)
    Write-Output ("  {0}  launcher found under cmd.exe         (launcher_pid={1})" -f $(if ($start.launcher_pid) {"LIVE "} else {"INERT"}), $start.launcher_pid)
    Write-Output ("  {0}  real interpreter found under launcher (cycle_pid={1}, source={2})" -f $(if ($start.cycle_pid_source -eq "interpreter") {"LIVE "} else {"INERT"}), $start.cycle_pid, $start.cycle_pid_source)
    Write-Output ("  {0}  exit code read after exit             (exit_code={1}, meaning={2})" -f $(if ($null -ne $exit.exit_code) {"LIVE "} else {"INERT"}), $exit.exit_code, $exit.meaning)
    Write-Output ("  {0}  child stdout reached the log          ({1})" -f $(if ($childOut -match "selftest child") {"LIVE "} else {"INERT"}), $lg)
    $ok = $start -and $exit -and ($exit.exit_code -eq 0) -and ($childOut -match "selftest child")
    Write-Output ("  RESULT: " + $(if ($ok) {"OK"} else {"BROKEN"}))
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    if ($ok) { exit 0 } else { exit 1 }
}

if (-not $Exe -or -not $WitnessLog -or -not $Log) {
    Write-Error "cycle_witness.ps1: -Exe, -Log and -WitnessLog are required (or -SelfTest)"
    exit 2
}
if (-not $WorkDir) { $WorkDir = (Get-Location).Path }

$argv = @()
if ($ArgsB64) {
    # foreach, not @(... | ConvertFrom-Json): PowerShell 5.1 emits a JSON array as
    # ONE object, and @() would wrap it into a one-element array of arrays.
    $parsed = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ArgsB64)) | ConvertFrom-Json
    foreach ($x in $parsed) { $argv += [string]$x }
}
# Quote each argument for cmd.exe: wrap in double quotes, escape embedded quotes.
$quoted = ($argv | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " "
$inner = '"' + $Exe + '" ' + $quoted + ' > "' + $Log + '" 2>&1'
$cmdline = '/d /s /c "' + $inner + '"'

$t0 = Get-Date
$myParent = $null
try { $myParent = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop).ParentProcessId } catch { }

try {
    $cmd = Start-Process -FilePath $env:ComSpec -ArgumentList $cmdline -WorkingDirectory $WorkDir -WindowStyle Hidden -PassThru
    $null = $cmd.Handle
} catch {
    Write-Row ([ordered]@{ event = "witness_error"; cycle_id = $CycleId; witness_pid = $PID;
                           error = "Start-Process failed: $($_.Exception.Message)"; ts = (Now-Iso) })
    exit 3
}

# Find launcher (python under cmd) and the real interpreter (python under the launcher).
$launcher = $null; $interp = $null; $lp = $null; $cp = $null
$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline -and -not $launcher) {
    $launcher = Get-Children $cmd.Id $t0 | Where-Object { $_.Name -like "python*" } | Select-Object -First 1
    if ($launcher) { $lp = Open-Proc $launcher.ProcessId; break }
    if ($cmd.HasExited) { break }
    Start-Sleep -Milliseconds 100
}
if ($launcher) {
    $deadline = (Get-Date).AddSeconds(3)
    while ((Get-Date) -lt $deadline -and -not $interp) {
        $interp = Get-Children $launcher.ProcessId $t0 | Where-Object { $_.Name -like "python*" } | Select-Object -First 1
        if ($interp) { $cp = Open-Proc $interp.ProcessId; break }
        if ($lp -and $lp.HasExited) { break }
        Start-Sleep -Milliseconds 100
    }
}
$cyclePid = $null; $source = "unknown"
if ($cp) { $cyclePid = $cp.Id; $source = "interpreter" }
elseif ($launcher) { $cyclePid = [int]$launcher.ProcessId; $source = "launcher" }

Write-Row ([ordered]@{
    event              = "start"
    cycle_id           = $CycleId
    witness_pid        = $PID
    witness_parent_pid = $myParent
    cmd_pid            = $cmd.Id
    launcher_pid       = $(if ($launcher) { [int]$launcher.ProcessId } else { $null })
    cycle_pid          = $cyclePid
    cycle_pid_source   = $source
    cmdline            = "$env:ComSpec $cmdline"
    log                = $Log
    ts                 = (Now-Iso)
})

# Wait on the most specific process we hold a handle to.
$code = $null; $exitSource = "none"
if ($cp)      { $cp.WaitForExit();  $code = $cp.ExitCode;  $exitSource = "interpreter" }
elseif ($lp)  { $lp.WaitForExit();  $code = $lp.ExitCode;  $exitSource = "launcher" }
else          { $cmd.WaitForExit(); $code = $cmd.ExitCode; $exitSource = "cmd" }
$launcherCode = $null
if ($lp) { if ($lp.WaitForExit(15000)) { $launcherCode = $lp.ExitCode } }
$null = $cmd.WaitForExit(15000)

Write-Row ([ordered]@{
    event              = "exit"
    cycle_id           = $CycleId
    cycle_pid          = $cyclePid
    exit_code          = $code
    exit_code_hex      = $(if ($null -ne $code) { '0x{0:X8}' -f $code } else { $null })
    exit_source        = $exitSource
    launcher_exit_code = $launcherCode
    wall_seconds       = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    meaning            = (Get-Meaning $code $launcherCode $Log)
    ts                 = (Now-Iso)
})
exit 0
