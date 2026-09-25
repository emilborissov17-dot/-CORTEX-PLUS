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
#   start: {event, cycle_id, witness_pid, witness_parent_pid,
#           launcher_pid, cycle_pid, cycle_pid_source, cmdline, log, ts}
#   exit:  {event, cycle_id, cycle_pid, exit_code, exit_code_hex, exit_source,
#           launcher_exit_code, wall_seconds, meaning, exit_code_note, ts}
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
# CHAIN: witness -> venv\Scripts\python.exe (the launcher, started by the witness
# with CreateProcessW, stdout and stderr on ONE log handle as `> log 2>&1` did) ->
# the real interpreter. The launcher's handle is held from birth; the
# interpreter's is opened as soon as the witness sees it.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\cycle_witness.ps1 -SelfTest
param(
    [string]$Exe = "",
    # The child's arguments as a base64-encoded JSON array of strings. JSON+base64
    # because the arguments cross TWO command-line parsers (Python's list2cmdline
    # into powershell.exe); each element is quoted for CreateProcess here, once.
    [string]$ArgsB64 = "",
    [string]$Log = "",
    [string]$WitnessLog = "",
    [string]$CycleId = "",
    [string]$WorkDir = "",
    # What the supervisor found before the spawn (warm core resident / reloaded),
    # carried into the start row as `preflight`.
    [string]$Preflight = "",
    # "spine" or "edges" (task #8 B.D); the edges' cycle_id is <spine id>#edges.
    [string]$Role = "spine",
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

function Get-Meaning($code, $launcherCode, [string]$logPath) {
    if ($null -eq $code) { return "WITNESS_DEFECT" }   # the launcher handle is held from birth; null must not happen
    if ($code -eq -1) { return "killed (taskkill /F or TerminateProcess)" }
    if ($code -eq -1073741510) { return "console closed / Ctrl+C" }          # 0xC000013A
    if ($code -eq 0) {
        if ($null -ne $launcherCode -and $launcherCode -ne 0) {
            return "killed through its launcher (the launcher exited $launcherCode and its job took the interpreter down, which then reports 0)"
        }
        return "clean exit"
    }
    if ($code -eq 3) {
        # fast_cycle_runner exits 3 when it reached its end but a step crashed, and
        # prints CYCLE_FINISHED_WITH_FAILURES as its last line. Without that line a
        # 3 is an ordinary SystemExit(3) and falls through to "python error".
        $fw = $false
        try { $fw = [bool](Get-Content -LiteralPath $logPath -Tail 20 -ErrorAction Stop | Select-String -SimpleMatch "CYCLE_FINISHED_WITH_FAILURES") } catch { }
        if ($fw) { return "finished with failed steps (CYCLE_FINISHED_WITH_FAILURES in the log)" }
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
    Write-Output ("  {0}  launcher started, handle from birth  (launcher_pid={1})" -f $(if ($start.launcher_pid) {"LIVE "} else {"INERT"}), $start.launcher_pid)
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
# The launcher is started HERE, by CreateProcessW, and its process handle is held
# from that call on - never looked up afterwards. Until 24 Sep the chain was
# witness -> cmd.exe -> launcher, and the launcher was FOUND by a tree walk and
# opened with GetProcessById + .Handle. A child that exits in ~0.3 s is gone by
# then: .Handle fails, PowerShell turns the failed getter into $null WITHOUT
# throwing, the Process object is left with no handle, and .ExitCode fails the
# same silent way - an exit row with exit_code null (10 of 60 fast children,
# measured 24 Sep). The Win32 calls below report failure as a return value.
#
# stdout and stderr share ONE inheritable handle on the log, which is what
# cmd.exe's `> log 2>&1` did. PROC_THREAD_ATTRIBUTE_HANDLE_LIST limits
# inheritance to that handle and NUL, so the cycle holds none of the witness's
# own handles (a caller's pipe would otherwise stay open for 90 minutes).
if (-not ("CortexWitness.Native" -as [type])) {
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
namespace CortexWitness {
public static class Native {
    [StructLayout(LayoutKind.Sequential)]
    struct SECURITY_ATTRIBUTES { public int nLength; public IntPtr lpSecurityDescriptor; public int bInheritHandle; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct STARTUPINFO {
        public int cb; public IntPtr lpReserved, lpDesktop, lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct STARTUPINFOEX { public STARTUPINFO StartupInfo; public IntPtr lpAttributeList; }
    [StructLayout(LayoutKind.Sequential)]
    struct PROCESS_INFORMATION { public IntPtr hProcess, hThread; public int dwProcessId, dwThreadId; }

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr CreateFileW(string name, uint access, uint share, ref SECURITY_ATTRIBUTES sa, uint disp, uint flags, IntPtr tmpl);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool CreateProcessW(string app, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit, uint flags,
                                      IntPtr env, string cwd, ref STARTUPINFOEX si, out PROCESS_INFORMATION pi);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attr, IntPtr val, IntPtr size, IntPtr prev, IntPtr ret);
    [DllImport("kernel32.dll")] static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)] static extern uint WaitForSingleObject(IntPtr h, uint ms);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool GetExitCodeProcess(IntPtr h, out uint code);

    static readonly IntPtr INVALID = new IntPtr(-1);

    // MSVC / CommandLineToArgvW quoting: there is no cmd.exe in the chain any more.
    public static string QuoteArg(string a) {
        if (a.Length > 0 && a.IndexOfAny(new[] { ' ', '\t', '\n', '\v', '"' }) < 0) return a;
        var sb = new StringBuilder("\"");
        int bs = 0;
        foreach (char c in a) {
            if (c == '\\') { bs++; continue; }
            if (c == '"') { sb.Append('\\', 2 * bs + 1).Append('"'); bs = 0; continue; }
            sb.Append('\\', bs).Append(c); bs = 0;
        }
        return sb.Append('\\', 2 * bs).Append('"').ToString();
    }

    // Returns { processHandle, pid }. Throws Win32Exception - it never returns a
    // child it does not hold a handle to.
    public static long[] Start(string exe, string cmdline, string cwd, string logPath) {
        var sa = new SECURITY_ATTRIBUTES { nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES)), bInheritHandle = 1 };
        IntPtr log = CreateFileW(logPath, 0x40000000 /*GENERIC_WRITE*/, 7 /*share r|w|d*/, ref sa, 2 /*CREATE_ALWAYS*/, 0x80, IntPtr.Zero);
        if (log == INVALID) throw new Win32Exception(Marshal.GetLastWin32Error(), "open log " + logPath);
        IntPtr nul = CreateFileW("NUL", 0x80000000 /*GENERIC_READ*/, 3, ref sa, 3 /*OPEN_EXISTING*/, 0, IntPtr.Zero);
        if (nul == INVALID) { int e = Marshal.GetLastWin32Error(); CloseHandle(log); throw new Win32Exception(e, "open NUL"); }
        IntPtr handles = Marshal.AllocHGlobal(2 * IntPtr.Size);
        IntPtr attrs = IntPtr.Zero;
        try {
            Marshal.WriteIntPtr(handles, 0, log);
            Marshal.WriteIntPtr(handles, IntPtr.Size, nul);
            IntPtr size = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
            attrs = Marshal.AllocHGlobal(size);
            if (!InitializeProcThreadAttributeList(attrs, 1, 0, ref size))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "InitializeProcThreadAttributeList");
            if (!UpdateProcThreadAttribute(attrs, 0, (IntPtr)0x20002 /*HANDLE_LIST*/, handles,
                                           (IntPtr)(2 * IntPtr.Size), IntPtr.Zero, IntPtr.Zero))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "UpdateProcThreadAttribute");
            var si = new STARTUPINFOEX();
            si.StartupInfo.cb = Marshal.SizeOf(typeof(STARTUPINFOEX));
            si.StartupInfo.dwFlags = 0x100; // STARTF_USESTDHANDLES
            si.StartupInfo.hStdInput = nul; si.StartupInfo.hStdOutput = log; si.StartupInfo.hStdError = log;
            si.lpAttributeList = attrs;
            PROCESS_INFORMATION pi;
            // EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW
            if (!CreateProcessW(exe, new StringBuilder(cmdline), IntPtr.Zero, IntPtr.Zero, true,
                                0x00080000 | 0x08000000, IntPtr.Zero, cwd, ref si, out pi))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateProcessW " + exe);
            CloseHandle(pi.hThread);
            return new long[] { pi.hProcess.ToInt64(), pi.dwProcessId };
        } finally {
            if (attrs != IntPtr.Zero) { DeleteProcThreadAttributeList(attrs); Marshal.FreeHGlobal(attrs); }
            Marshal.FreeHGlobal(handles);
            CloseHandle(log); CloseHandle(nul);   // the child has its own copies
        }
    }

    // SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION. 0 when the process is gone.
    public static long Open(int pid) { return OpenProcess(0x00100000 | 0x1000, false, pid).ToInt64(); }
    public static bool Wait(long h, uint ms) { return WaitForSingleObject(new IntPtr(h), ms) == 0; }
    public static bool Exited(long h) { return Wait(h, 0); }
    // The exit code as a signed int (0xFFFFFFFF -> -1), or null if it cannot be read.
    public static int? ExitCode(long h) {
        uint c;
        if (!GetExitCodeProcess(new IntPtr(h), out c) || c == 259 /*STILL_ACTIVE*/) return null;
        return unchecked((int)c);
    }
    public static void Close(long h) { if (h != 0) CloseHandle(new IntPtr(h)); }
}
}
'@
}

$cmdline = (@($Exe) + $argv | ForEach-Object { [CortexWitness.Native]::QuoteArg($_) }) -join " "

$t0 = Get-Date
$myParent = $null
try { $myParent = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop).ParentProcessId } catch { }

try {
    $born = [CortexWitness.Native]::Start($Exe, $cmdline, $WorkDir, $Log)
} catch {
    Write-Row ([ordered]@{ event = "witness_error"; cycle_id = $CycleId; witness_pid = $PID;
                           error = "CreateProcess failed: $($_.Exception.InnerException.Message)"; ts = (Now-Iso) })
    exit 3
}
$lh = $born[0]; $launcherPid = [int]$born[1]

# The real interpreter (python under the launcher) is still FOUND, every 100 ms -
# the launcher creates it, not the witness. If the launcher exits before the
# witness holds it, the launcher's code (held from birth) stands in, and the row
# says so.
$ch = 0; $interpPid = $null; $pyRaced = $false
$deadline = (Get-Date).AddSeconds(3)
while ((Get-Date) -lt $deadline) {
    $interp = Get-Children $launcherPid $t0 | Where-Object { $_.Name -like "python*" } | Select-Object -First 1
    if ($interp) {
        $ch = [CortexWitness.Native]::Open([int]$interp.ProcessId)
        if ($ch -ne 0) { $interpPid = [int]$interp.ProcessId } else { $pyRaced = $true }
        break
    }
    if ([CortexWitness.Native]::Exited($lh)) { $pyRaced = $true; break }
    Start-Sleep -Milliseconds 100
}
$cyclePid = $launcherPid; $source = "launcher"
if ($interpPid) { $cyclePid = $interpPid; $source = "interpreter" }

Write-Row ([ordered]@{
    event              = "start"
    cycle_id           = $CycleId
    witness_pid        = $PID
    witness_parent_pid = $myParent
    launcher_pid       = $launcherPid
    cycle_pid          = $cyclePid
    cycle_pid_source   = $source
    cmdline            = $cmdline
    log                = $Log
    preflight          = $(if ($Preflight) { $Preflight } else { $null })
    role               = $Role
    ts                 = (Now-Iso)
})

# Wait on the most specific process the witness holds a handle to.
$code = $null; $exitSource = "none"; $launcherCode = $null; $exitCodeNote = $null
if ($ch -ne 0) {
    $null = [CortexWitness.Native]::Wait($ch, [uint32]::MaxValue)
    $code = [CortexWitness.Native]::ExitCode($ch); $exitSource = "interpreter"
    if ([CortexWitness.Native]::Wait($lh, 15000)) { $launcherCode = [CortexWitness.Native]::ExitCode($lh) }
} else {
    $null = [CortexWitness.Native]::Wait($lh, [uint32]::MaxValue)
    $launcherCode = [CortexWitness.Native]::ExitCode($lh)
    $code = $launcherCode; $exitSource = "launcher"
    if ($pyRaced) { $exitCodeNote = "python exited before the witness opened its handle; launcher code used" }
}
[CortexWitness.Native]::Close($ch); [CortexWitness.Native]::Close($lh)

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
    exit_code_note     = $exitCodeNote
    ts                 = (Now-Iso)
})
exit 0
