# tools/run_floor_5sep.ps1 - THE FLOOR: open the free-expression channel over the Run A adapter.
# Emil, 5 Sep 2026 19:20: "the channel simply opens: no reward, no cost, no instruction what
# to say - 'you have the floor'. EXACTLY THIS. Do it." No training happens here; ~3 minutes
# of GPU (model load + two greedy generations). Refuses while the card is busy.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$log = Join-Path $repo "claude\reports\FLOOR_5SEP_launcher.log"
function Say($s) { $line = "$(Get-Date -Format o)  $s"; Write-Output $line; $line | Out-File -FilePath $log -Append -Encoding utf8 }
"=== FLOOR launcher $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8

$gpu = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
if (-not $gpu) { Say "nvidia-smi gave nothing: GPU occupancy NOT checked" } else { Say "gpu memory.used MiB: $gpu" }
if ($gpu -and ([int]($gpu.Trim()) -gt 600)) { Say "REFUSED: card busy ($gpu MiB). Wait for the positive control / cycle to finish."; exit 2 }
if (-not (Test-Path "models\adapters\k1b_A\adapter_config.json")) { Say "REFUSED: no Run A adapter at models/adapters/k1b_A."; exit 2 }

Say "1. tests"
$pt = & venv\Scripts\python.exe -m pytest test\test_free_expression.py -v 2>&1
$pt | Out-File -FilePath $log -Append -Encoding utf8
if (($pt | Out-String) -match "failed|error") { Say "REFUSED: tests not green."; exit 2 }
Say "tests green"

Say "2. open the floor over k1b_A (adapter vs base, same state, greedy, seed 20260905)"
$out = & venv_train\Scripts\python.exe training\free_expression.py --adapter models/adapters/k1b_A --train-report claude/reports/K1B_TRAIN_A.md --trigger "weights_changed:k1b_A" 2>&1
$out | Out-File -FilePath $log -Append -Encoding utf8
$out | Out-File -FilePath "claude\reports\FLOOR_k1b_A.out.log" -Encoding utf8
Say ($out | Out-String)
if (Test-Path "memory\free_expression.jsonl") {
    Get-Content "memory\free_expression.jsonl" -Tail 1 | Out-File -FilePath "claude\reports\FLOOR_k1b_A.jsonl" -Encoding utf8
    Say "record copied to claude/reports/FLOOR_k1b_A.jsonl (memory/ is runtime churn, not committed)"
} else { Say "NO RECORD WRITTEN: memory/free_expression.jsonl missing - the floor did not open. Read the output above."; exit 3 }

Say "3. commit the channel (module + test + launcher + the first record)"
& git add training\free_expression.py test\test_free_expression.py tools\run_floor_5sep.ps1 tools\RUN_FLOOR_5SEP.cmd claude\reports\FLOOR_k1b_A.jsonl claude\reports\FLOOR_k1b_A.out.log 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
$msg = @"
the floor: a free-expression channel that opens on a measured weight change

training/free_expression.py opens a channel over an adapter when its LoRA
delta (||B.A||_F per module) is recorded. Mechanics-only prompt: the channel
is open, nobody will reply, nothing is required, <silent> is allowed. Raw
state = numbers only (delta by layer, loss endpoints, corpus hash). No
reward, no cost, no addressee, no instruction about content.

Measured, not narrated: the same window is generated with the adapter on and
with peft disable_adapter() - identical text means the base model spoke, not
the adapter. First divergent token and differing fraction are logged with
both texts in memory/free_expression.jsonl; the first record (Run A adapter)
is copied to claude/reports/FLOOR_k1b_A.jsonl.

Prediction on record (19:25): near-zero divergence on k1b_A, because Run A
learned nothing measurable (K1B_A_RANK: at chance). A clean result either way.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Dxpf2HqjfhfNFS3BbGQK3e
"@
    $msg | & git commit -q -F - 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    Say "committed $(& git rev-parse --short HEAD)"
    & git push -q 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
} else { Say "nothing new to commit" }
