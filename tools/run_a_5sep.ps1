# tools/run_a_5sep.ps1 - ONE CLICK: prove the launcher fix, commit it, start Run A detached.
#
# Written 5 Sep 2026 from a session that can write files on this machine but has no shell
# on it. Everything this script decides is written to claude/reports/RUN_A_5SEP_launcher.log
# so the decision can be read later, not remembered.
#
# Run A (pre-registered 4/5 Sep): rank 8, targets q/k/v/o, 1 epoch, max-len 256, on the
# REAL corpus cortex_memory/training/train.jsonl (1077 rows). Followed, in the same detached
# process, by the within-stratum ranking eval with the SAME knobs the control used
# (claude/reports/K1B_RANK_KNOBS.json: K=4, chance 0.20, batch 1). The control's verdict on
# that bench was AT CHANCE (0.2111, CI [0.156, 0.272]) - that is what licenses this run.
#
# Order of operations, and why:
#   1. pytest test/test_launch_detached_encoding.py   - the fix has to fail-when-broken
#      before it is trusted. If the STATIC test fails the launcher is not fixed: stop.
#   2. git commit + push of the two files (only if BOTH tests passed).
#   3. tools/launch_detached.ps1 with cmd.exe chaining train && eval, so the eval starts
#      the moment training ends and nobody has to be awake for it.
# Nothing here touches the ladder, model_window.json, or any scheduled task.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$log = Join-Path $repo "claude\reports\RUN_A_5SEP_launcher.log"
function Say($s) { $line = "$(Get-Date -Format o)  $s"; Write-Output $line; $line | Out-File -FilePath $log -Append -Encoding utf8 }

"=== RUN_A launcher $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8

# --- 0. preconditions -------------------------------------------------------------------
if (Test-Path "models\adapters\k1b_A\adapter_config.json") {
    Say "REFUSED: models/adapters/k1b_A already holds a finished adapter. Run A has run. Not overwriting."
    exit 2
}
$gpu = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
if (-not $gpu) { Say "nvidia-smi gave nothing: GPU occupancy NOT checked" } else { Say "gpu memory.used MiB before launch: $gpu" }
if ($gpu -and ([int]($gpu.Trim()) -gt 600)) {
    Say "REFUSED: the card is not free ($gpu MiB in use). Training and whatever holds it cannot share 4 GB."
    exit 2
}
$hour = (Get-Date).Hour
if ($hour -ge 0 -and $hour -lt 6) {
    Say "REFUSED: it is $hour o'clock; the 03:04 sealed cycle owns the card until it finishes (~05:10). Launch after that."
    exit 2
}

# --- 1. the test that must fail when the fix is broken ----------------------------------
Say "pytest test/test_launch_detached_encoding.py"
$pt = & venv\Scripts\python.exe -m pytest test\test_launch_detached_encoding.py -v 2>&1
$pt | Out-File -FilePath $log -Append -Encoding utf8
$ptText = ($pt | Out-String)
$staticOk = $ptText -match "test_script_sets_utf8_before_start_process PASSED"
$behavOk  = $ptText -match "test_detached_child_can_print_replacement_character PASSED"
Say "static test passed: $staticOk   behavioural test passed: $behavOk"
if (-not $staticOk) {
    Say "REFUSED: launch_detached.ps1 does not set PYTHONIOENCODING before Start-Process. Nothing committed, Run A not started."
    exit 2
}

# --- 2. commit the fix, only if it is proven ---------------------------------------------
if ($staticOk -and $behavOk) {
    & git add tools\launch_detached.ps1 test\test_launch_detached_encoding.py tools\run_a_5sep.ps1 tools\RUN_A_5SEP.cmd 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    $msg = @"
launcher: every detached child gets utf-8 stdout, with the test that would have caught 00:27

The detached suite of 5 Sep 00:27 finished and then died on its last print: no
PYTHONIOENCODING in the child, cp1252, U+FFFD at position 17043, .out.log left at
0 bytes. launch_detached.ps1 now sets PYTHONIOENCODING=utf-8 and PYTHONUTF8=1
before Start-Process. test_launch_detached_encoding.py launches a real child
through the script that prints U+FFFD and reads it back from the .out.log.

Also adds tools/run_a_5sep.ps1 + RUN_A_5SEP.cmd: one click runs the test, commits
if green, and starts Run A (r=8, q/k/v/o, 1 epoch) chained with the ranking eval.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Dxpf2HqjfhfNFS3BbGQK3e
"@
    $msg | & git commit -q -F - 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    $head = & git rev-parse --short HEAD
    Say "committed $head"
    & git push -q 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    Say "pushed (see log for git output)"
} else {
    Say "NOT COMMITTED: behavioural test did not pass; the fix stays in the working tree. Run A still starts - the launcher was already good enough for the control."
}

# --- 3. Run A, detached, train && eval ---------------------------------------------------
$train = "venv_train\Scripts\python.exe training/train_lora.py --train cortex_memory/training/train.jsonl --out models/adapters/k1b_A --report claude/reports/K1B_TRAIN_A.md --epochs 1 --max-len 256 --rank 8 --alpha 16 --targets q_proj,k_proj,v_proj,o_proj --save-every 25 --resume"
$eval  = "venv_train\Scripts\python.exe training/run_rank_eval.py --adapter models/adapters/k1b_A --knobs claude/reports/K1B_RANK_KNOBS.json --report claude/reports/K1B_A_RANK.md"
$chain = "/c `"$train && $eval`""
Say "launching: cmd.exe $chain"
$out = & powershell -NoProfile -ExecutionPolicy Bypass -File tools\launch_detached.ps1 -Exe "C:\Windows\System32\cmd.exe" -Arguments $chain -Log claude\reports\K1B_RUN_A.log 2>&1
$out | Out-File -FilePath $log -Append -Encoding utf8
Say ($out | Out-String)
Say "Run A started. Progress: claude/reports/K1B_RUN_A.out.log - training ~2h, then eval ~1h. Report: K1B_TRAIN_A.md then K1B_A_RANK.md."
Say "The pid in K1B_RUN_A.pid is cmd.exe, not the worker. The worker is the python.exe with hundreds of MB RSS."
