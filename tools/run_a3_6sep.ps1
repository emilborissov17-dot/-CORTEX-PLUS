# tools/run_a3_6sep.ps1 - RUN A3: the Run A recipe at THREE epochs.
#
# THE CONFOUND, named 4 Sep and still open. Run A trained for ONE epoch and landed AT
# CHANCE on the bench. That result cannot separate "this corpus contains no learnable
# mapping" from "one epoch was not enough to fit it", because both produce the same
# number. PC3 closed half of it from the other side: the SAME recipe at 3 epochs learned
# a synthetic 12-way rule (0.3333, CI [0.2500, 0.4167], base 0.1417 AT CHANCE), so the
# recipe and the bench can see a mapping that is really there. What PC3 did NOT show is
# that THIS corpus contains one. A3 is that test, and it is the run Kimi R34's rule
# demands: no archive run below 3 epochs.
#
# Everything else is Run A exactly: rank 8, q/k/v/o, max-len 256, 1077 rows, the same
# corpus sha256, the same seed. Only --epochs changes, so a difference in outcome has one
# candidate cause.
#
# PRE-REGISTERED BEFORE LAUNCH (6 Sep 2026, Claude):
#   A3 UNSEEN sig01 -> AT CHANCE, 0.19-0.27, P(above base with CI) = 0.20.
#   A corpus with 44% duplicate targets does not become lessons at three epochs. PC3
#   showed the RECIPE can learn a rule; it did not show this CORPUS holds one. If A3
#   lands above base with a clean CI, that prediction was wrong and the corpus is
#   richer than the duplicate rate suggested - a good outcome, and a measured one.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$log = Join-Path $repo "claude\reports\RUN_A3_6SEP_launcher.log"
function Say($s) { $line = "$(Get-Date -Format o)  $s"; Write-Output $line; $line | Out-File -FilePath $log -Append -Encoding utf8 }
"=== RUN_A3 launcher $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8

# --- preconditions, unchanged from Run A -------------------------------------------------
if (Test-Path "models\adapters\k1b_A3\adapter_config.json") {
    Say "REFUSED: models/adapters/k1b_A3 already holds a finished adapter. Not overwriting a result."
    exit 2
}
$gpu = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
if (-not $gpu) { Say "nvidia-smi gave nothing: GPU occupancy NOT checked" } else { Say "gpu memory.used MiB before launch: $gpu" }

# Death 4 launched into 156 MiB already held by an ollama runner, because the
# line above only NARRATES. gpu_guard frees runners and REFUSES if the card is
# still held, which is the difference between a check and a note.
& (Join-Path $repo "tools\gpu_guard.ps1")
if ($LASTEXITCODE -ne 0) { Say "REFUSED to launch: gpu_guard could not free the card."; exit 4 }
Say "gpu_guard: card free."
if ($gpu -and ([int]($gpu.Trim()) -gt 600)) {
    Say "REFUSED: the card is not free ($gpu MiB in use). Training cannot share 4 GB."
    exit 2
}
$hour = (Get-Date).Hour
if ($hour -ge 0 -and $hour -lt 6) {
    Say "REFUSED: it is $hour o'clock; the 03:04 sealed cycle owns the card. Launch after it finishes."
    exit 2
}

# --- the corpus must be the SAME one Run A saw -------------------------------------------
# A confound test that quietly changed corpora would answer a different question.
$sha = & venv\Scripts\python.exe -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('cortex_memory/training/train.jsonl').read_bytes()).hexdigest())"
Say "train.jsonl sha256: $sha"
# Run A's own recorded corpus sha (claude/reports/K1B_TRAIN_A.md:7). The first
# draft used 2622e01a..., which is the CONTROL's DERANGED corpus - it would have
# warned "not like-for-like" about a corpus that is in fact byte-identical.
$expected = "079a9d1472511aa790e94320067f3ae3890c5c53a3170596c00eb16b2ec6259e"
if ($sha.Trim() -ne $expected) {
    Say "NOTE: corpus sha256 differs from the one recorded for the control/Run A ($expected). A3 is still launched, but the comparison is NOT like-for-like and the report must say so."
}

# --- the control's per-item hits, so LEARNED is not UNKNOWN this time --------------------
# THE CONTROL HAS NO PER-ITEM FILE, so it is re-scored FIRST, in the same chain.
# The V2 control run (10:01-10:59 today) predates the --items-out output added at
# ~10:55, so K1B_CONTROL_RANK_V2.items.json does not exist and LEARNED would read
# UNKNOWN again - the one thing this run was asked to fix. Re-scoring the deranged
# adapter costs ~55 min and must happen BEFORE A3's eval, because that eval reads
# the file. Same knobs, same holdout, same draw.
$controlItems = "claude\reports\K1B_CONTROL_RANK_V3.items.json"
$ctrlArg = " --control-items $controlItems"
if (Test-Path $controlItems) {
    Say "control items already present: $controlItems - skipping the re-score."
    $ctrlEval = ""
} else {
    Say "control items absent - re-scoring the deranged control first so LEARNED is computable."
    $ctrlEval = "venv_train\Scripts\python.exe -u training/run_rank_eval.py --adapter models/adapters/k1b_control --knobs claude/reports/K1B_RANK_KNOBS.json --report claude/reports/K1B_CONTROL_RANK_V3.md --items-out $controlItems && "
}

# --- launch: train && eval, detached, python -u so the logs are live --------------------
$train = "venv_train\Scripts\python.exe -u training/train_lora.py --train cortex_memory/training/train.jsonl --out models/adapters/k1b_A3 --report claude/reports/K1B_TRAIN_A3.md --epochs 3 --max-len 256 --rank 8 --alpha 16 --targets q_proj,k_proj,v_proj,o_proj --save-every 25 --resume"
$eval  = "venv_train\Scripts\python.exe -u training/run_rank_eval.py --adapter models/adapters/k1b_A3 --knobs claude/reports/K1B_RANK_KNOBS.json --report claude/reports/K1B_A3_RANK.md$ctrlArg"
# expandable_segments is an ALLOCATOR setting, not a recipe change: it alters how
# PyTorch maps VRAM, never max-len, batch, K, the draw or the metric, so the numbers
# stay bit-identical. It exists for exactly this failure - variable-length forwards
# fragmenting a small card until no contiguous block is left. A3 died twice inside
# the scoring loop, at items 100 and 125 of 223, with two different memory-class
# CUDA errors and nothing retaining a tensor between items.
$chain = "/c `"set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True && $ctrlEval$train && $eval`""
Say "launching: cmd.exe $chain"

# In-process call, NOT a second powershell.exe: passing $chain through a native command
# line re-splits it on spaces and its own quotes (learned 5 Sep 15:38).
$out = & (Join-Path $repo "tools\launch_detached.ps1") -Exe "C:\Windows\System32\cmd.exe" -Arguments $chain -Log "claude\reports\K1B_RUN_A3.log" 2>&1
$out | Out-File -FilePath $log -Append -Encoding utf8
$outText = ($out | Out-String)
if ($outText -notmatch "DETACHED_PID=(\d+)") {
    Say "LAUNCH FAILED: no DETACHED_PID. A3 did NOT start. Output above."
    exit 3
}
$launchedPid = [int]$Matches[1]
Start-Sleep -Seconds 8
if (-not (Get-Process -Id $launchedPid -ErrorAction SilentlyContinue)) {
    Say "LAUNCH FAILED: pid $launchedPid gone 8 s after start. See claude/reports/K1B_RUN_A3.err.log."
    exit 3
}
# The sampler is the thing that was missing when death 1 could not be explained.
& (Join-Path $repo "tools\launch_detached.ps1") -Exe "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$repo\tools\gpu_sampler.ps1`" -WatchPid $launchedPid" `
    -Log "claude\reports\K1B_A3_SAMPLER.log" | Out-Null
Say "gpu sampler watching pid $launchedPid -> claude/reports/K1B_A3_gpu.log"

$pyCount = (Get-Process python -ErrorAction SilentlyContinue | Measure-Object).Count
Say "A3 started: cmd.exe pid $launchedPid alive after 8 s; python.exe processes now: $pyCount."
Say "Expected: ~1 h control re-score, ~6 h training (3 x the 1-epoch run), then ~1 h eval. Reports: K1B_CONTROL_RANK_V3.md, K1B_TRAIN_A3.md, K1B_A3_RANK.md."
Say "The pid in K1B_RUN_A3.pid is cmd.exe, not the worker. The worker is the python.exe with hundreds of MB RSS."
