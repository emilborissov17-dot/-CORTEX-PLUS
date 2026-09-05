# tools/run_pc_5sep.ps1 - POSITIVE CONTROL: can the bench see a mapping that is really there?
# Pre-registered 5 Sep 2026 17:30, before any number. Two adapters on the SAME synthetic
# corpus (300 rows, 12 codes, rule in training/make_positive_control.py), same bench,
# same knobs as the control and Run A (K=4, batch 1):
#   PC1: the Run A recipe exactly   (r=8, q/k/v/o, 1 epoch)   ~25 min train + ~30 min eval
#   PC3: the same recipe, 3 epochs                             ~75 min train + ~30 min eval
# Verdict table for this corpus is SEEN (finite label set; see the script's docstring).
# Refuses while the card is busy (Run A) or during the 03:04 cycle window.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$log = Join-Path $repo "claude\reports\PC_5SEP_launcher.log"
function Say($s) { $line = "$(Get-Date -Format o)  $s"; Write-Output $line; $line | Out-File -FilePath $log -Append -Encoding utf8 }
"=== POSITIVE CONTROL launcher $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8

$gpu = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
if (-not $gpu) { Say "nvidia-smi gave nothing: GPU occupancy NOT checked" } else { Say "gpu memory.used MiB: $gpu" }
if ($gpu -and ([int]($gpu.Trim()) -gt 600)) { Say "REFUSED: card busy ($gpu MiB). Run A or the cycle owns it."; exit 2 }
$hour = (Get-Date).Hour
if ($hour -ge 0 -and $hour -lt 6) { Say "REFUSED: $hour o'clock is the sealed cycle's window."; exit 2 }
if (Test-Path "models\adapters\pc_A1\adapter_config.json") { Say "REFUSED: pc_A1 already exists. Not overwriting a result."; exit 2 }

Say "1. build the corpus (deterministic, seed 20260905)"
$mk = & venv_train\Scripts\python.exe training\make_positive_control.py 2>&1
$mk | Out-File -FilePath $log -Append -Encoding utf8
Say ($mk | Out-String)
if (-not (Test-Path "cortex_memory\training\positive_control\holdout.jsonl")) { Say "REFUSED: corpus not written."; exit 2 }

Say "2. commit the generator + manifest (the corpus itself is small; committed too, it IS the pre-registration)"
& git add training\make_positive_control.py cortex_memory\training\positive_control\manifest.json cortex_memory\training\positive_control\train.jsonl cortex_memory\training\positive_control\holdout.jsonl tools\run_pc_5sep.ps1 tools\RUN_PC_5SEP.cmd 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
$msg = @"
positive control: a known 12-way rule, so a chance result can be told from a blind bench

training/make_positive_control.py writes 300 train + 120 holdout rows from a
deterministic rule over four axis readings (lowest axis x direction of its
delta -> one of 12 PROTOCOL codes that name no axis). Base model and the
axis-name rule are at chance by construction; only a learned mapping can rise.
Pre-registered: verdict table is SEEN (finite label set), pass = adapter CI
above 0.20 and above base; FAIL means the Run A recipe + bench cannot see a
real mapping of this size, and chance on the real corpus is uninterpretable.

tools/run_pc_5sep.ps1: PC1 = exact Run A recipe (1 epoch), PC3 = 3 epochs,
same bench and knobs as the control. Refuses while the card is busy.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Dxpf2HqjfhfNFS3BbGQK3e
"@
    $msg | & git commit -q -F - 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    Say "committed $(& git rev-parse --short HEAD)"
    & git push -q 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
} else { Say "nothing new to commit" }

Say "3. launch PC1 -> eval -> PC3 -> eval, detached"
$c = "cortex_memory/training/positive_control"
$t1 = "venv_train\Scripts\python.exe training/train_lora.py --train $c/train.jsonl --out models/adapters/pc_A1 --report claude/reports/PC_TRAIN_A1.md --epochs 1 --max-len 256 --rank 8 --alpha 16 --targets q_proj,k_proj,v_proj,o_proj --save-every 25 --resume"
$e1 = "venv_train\Scripts\python.exe training/run_rank_eval.py --adapter models/adapters/pc_A1 --train $c/train.jsonl --holdout $c/holdout.jsonl --knobs claude/reports/K1B_RANK_KNOBS.json --report claude/reports/PC_A1_RANK.md"
$t3 = "venv_train\Scripts\python.exe training/train_lora.py --train $c/train.jsonl --out models/adapters/pc_A3 --report claude/reports/PC_TRAIN_A3.md --epochs 3 --max-len 256 --rank 8 --alpha 16 --targets q_proj,k_proj,v_proj,o_proj --save-every 25 --resume"
$e3 = "venv_train\Scripts\python.exe training/run_rank_eval.py --adapter models/adapters/pc_A3 --train $c/train.jsonl --holdout $c/holdout.jsonl --knobs claude/reports/K1B_RANK_KNOBS.json --report claude/reports/PC_A3_RANK.md"
$chain = "/c `"$t1 && $e1 && $t3 && $e3`""
Say "launching: cmd.exe $chain"
$out = & (Join-Path $repo "tools\launch_detached.ps1") -Exe "C:\Windows\System32\cmd.exe" -Arguments $chain -Log "claude\reports\PC_RUN.log" 2>&1
$out | Out-File -FilePath $log -Append -Encoding utf8
$outText = ($out | Out-String)
if ($outText -notmatch "DETACHED_PID=(\d+)") { Say "LAUNCH FAILED: no DETACHED_PID."; exit 3 }
$launchedPid = [int]$Matches[1]
Start-Sleep -Seconds 8
if (-not (Get-Process -Id $launchedPid -ErrorAction SilentlyContinue)) { Say "LAUNCH FAILED: pid $launchedPid gone after 8 s. See claude/reports/PC_RUN.err.log"; exit 3 }
Say "Positive control started: pid $launchedPid alive. Progress: claude/reports/PC_RUN.out.log. Reports: PC_A1_RANK.md (~1 h), PC_A3_RANK.md (~3 h)."
