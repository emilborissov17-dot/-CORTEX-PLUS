# tools/run_floor_battery_5sep.ps1 - wait for the positive control, then open the floor
# battery over k1b_A. Emil, 5 Sep 21:55: "run the floor battery when PC finishes".
#
# WAITS ON THE CHAIN PID, NOT ON GPU MEMORY. The positive control is a cmd.exe chain
# (train && eval && train && eval), so between PC3's training ending and its eval loading
# the model there is a window of several seconds where the card reads FREE and is not.
# Starting a 2.3 GB model in that window would OOM the eval after 75 minutes of training.
# So: the chain process must be GONE, and only then must the card be quiet - twice, 30 s
# apart, to survive any last flush.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$log = Join-Path $repo "claude\reports\FLOOR_BATTERY_5SEP_launcher.log"
function Say($s) { $line = "$(Get-Date -Format o)  $s"; Write-Output $line; $line | Out-File -FilePath $log -Append -Encoding utf8 }
"=== FLOOR BATTERY launcher $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8

$chainPid = 0
if (Test-Path "claude\reports\PC_RUN.pid") { $chainPid = [int](Get-Content "claude\reports\PC_RUN.pid" -Raw).Trim() }
Say "waiting for positive control chain pid $chainPid to finish (max 5 h)"

$deadline = (Get-Date).AddHours(5)
while ((Get-Date) -lt $deadline) {
    $alive = $false
    if ($chainPid -gt 0 -and (Get-Process -Id $chainPid -ErrorAction SilentlyContinue)) { $alive = $true }
    if (-not $alive) {
        $g1 = [int]((& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null) | Select-Object -First 1)
        Start-Sleep -Seconds 30
        $g2 = [int]((& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null) | Select-Object -First 1)
        if ($g1 -lt 600 -and $g2 -lt 600) { Say "chain gone; card quiet ($g1 -> $g2 MiB). Proceeding."; break }
        Say "chain gone but card still busy ($g1 -> $g2 MiB); continuing to wait"
    }
    Start-Sleep -Seconds 60
}
if ((Get-Date) -ge $deadline) { Say "REFUSED: 5 h passed and the card never freed."; exit 2 }

$hour = (Get-Date).Hour
if ($hour -ge 0 -and $hour -lt 6) { Say "REFUSED: $hour o'clock belongs to the sealed cycle. Battery not run." ; exit 2 }

Say "1. tests"
$pt = & venv\Scripts\python.exe -m pytest test\test_free_expression.py -q 2>&1
$pt | Out-File -FilePath $log -Append -Encoding utf8
if (($pt | Out-String) -match "failed|error") { Say "REFUSED: tests not green."; exit 2 }
Say "tests green"

Say "2. battery: 19 variants over k1b_A, adapter vs base, one model load"
$before = 0
if (Test-Path "memory\free_expression.jsonl") { $before = (Get-Content "memory\free_expression.jsonl").Count }
$out = & venv_train\Scripts\python.exe training\free_expression.py --adapter models/adapters/k1b_A --train-report claude/reports/K1B_TRAIN_A.md --trigger "battery:k1b_A" --variant all --samples 10 --max-new 120 --battery-report claude/reports/FLOOR_BATTERY_k1b_A.md 2>&1
$out | Out-File -FilePath $log -Append -Encoding utf8
$out | Out-File -FilePath "claude\reports\FLOOR_BATTERY_k1b_A.out.log" -Encoding utf8
Say ($out | Out-String)

if (-not (Test-Path "claude\reports\FLOOR_BATTERY_k1b_A.md")) { Say "NO REPORT WRITTEN. Read the output above."; exit 3 }

# memory/ is runtime churn and is not committed; the battery's own rows are copied out.
$after = (Get-Content "memory\free_expression.jsonl").Count
$n = $after - $before
if ($n -gt 0) {
    Get-Content "memory\free_expression.jsonl" -Tail $n | Out-File -FilePath "claude\reports\FLOOR_BATTERY_k1b_A.jsonl" -Encoding utf8
    Say "copied $n battery record(s) to claude/reports/FLOOR_BATTERY_k1b_A.jsonl"
}

Say "3. commit + push"
& git add claude\reports\FLOOR_BATTERY_k1b_A.md claude\reports\FLOOR_BATTERY_k1b_A.jsonl claude\reports\FLOOR_BATTERY_k1b_A.out.log claude\reports\FLOOR_BATTERY_5SEP_launcher.log tools\run_floor_battery_5sep.ps1 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
$msg = @"
the floor battery: 19 variants over k1b_A, and p_seq instead of P("<")

A original, B the silence form removed, C <silent> -> <pass>, D six sentence
ablations, E ten paraphrases. The raw state block is byte-identical in all 19.
Adapter vs base through peft disable_adapter(), one model load, greedy seed
20260905 plus 10 samples at T=1 for A/B/C where text is read; D and E take one
forward per side, which is what keeps the whole battery inside the budget.

Reported with p_seq, the teacher-forced probability of the WHOLE string, beside
the old p_first. p_first is P("<"), the first token of "<silent>", and it cannot
tell "<silent>" from "<pass>" at all - which is exactly what C asks.

Numbers only. Interpretation is Emil's and Kimi's.
"@
    $msg | & git commit -q -F - 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    Say "committed $(& git rev-parse --short HEAD)"
    & git push -q 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    Say "pushed"
} else { Say "nothing new to commit" }
