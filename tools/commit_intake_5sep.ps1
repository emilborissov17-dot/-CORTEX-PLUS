# tools/commit_intake_5sep.ps1 - prove core/proposal_intake on THIS repo, then commit it.
# Written 5 Sep 2026 by a session with files but no shell on this machine.
# Log: claude/reports/INTAKE_5SEP_launcher.log. Nothing here touches the GPU or Run A.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$log = Join-Path $repo "claude\reports\INTAKE_5SEP_launcher.log"
function Say($s) { $line = "$(Get-Date -Format o)  $s"; Write-Output $line; $line | Out-File -FilePath $log -Append -Encoding utf8 }
"=== INTAKE launcher $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8

Say "1. compile fast_cycle_runner.py"
& venv\Scripts\python.exe -m py_compile fast_cycle_runner.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { Say "REFUSED: fast_cycle_runner.py does not compile. Nothing committed."; exit 2 }

Say "2. pytest test/test_proposal_intake.py"
$pt = & venv\Scripts\python.exe -m pytest test\test_proposal_intake.py -v 2>&1
$pt | Out-File -FilePath $log -Append -Encoding utf8
$ptText = ($pt | Out-String)
$ok = ($ptText -match "(\d+) passed") -and ($ptText -notmatch "failed|error")
Say "tests green: $ok"
if (-not $ok) { Say "REFUSED: tests not green. Nothing committed."; exit 2 }

Say "3. selftest (LIVE/INERT against this repo)"
$st = & venv\Scripts\python.exe -m core.proposal_intake --selftest 2>&1
$st | Out-File -FilePath $log -Append -Encoding utf8
Say ($st | Out-String)

Say "4. commit + push"
& git add core\proposal_intake.py test\test_proposal_intake.py fast_cycle_runner.py tools\commit_intake_5sep.ps1 tools\COMMIT_INTAKE_5SEP.cmd 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Say "nothing new to commit; HEAD $(& git rev-parse --short HEAD)"; exit 0 }
$msg = @"
intake: a proposal is born gradeable or it is not born (Kimi R31, step 1)

core/proposal_intake.py: a proposal enters memory/improvement_proposals.json only
with an indicator that evaluator.ground_truth resolves today, a non-zero
expected_delta and an ISO deadline within a year. Everything else is REFUSED at
the door with the missing pieces named, one line each in
memory/proposal_intake_refusals.jsonl - the curriculum the generator will be
retrained against.

fast_cycle_runner.py: the three injectors (strategist, growth, hyperclaw) no
longer write the queue themselves; _inject_proposals is the one door. Their
measurable_goal = solution[:80] was a name asserting a property never checked.

Expected tonight: 0 admitted, everything refused, and for the first time that
is a number with reasons instead of 40 rows of imagination.

17 tests; the last one fails if any injector writes the queue directly again.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Dxpf2HqjfhfNFS3BbGQK3e
"@
$msg | & git commit -q -F - 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
Say "committed $(& git rev-parse --short HEAD)"
& git push -q 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
Say "pushed (git output in log)"
