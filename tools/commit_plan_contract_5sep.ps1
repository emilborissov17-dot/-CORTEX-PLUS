# tools/commit_plan_contract_5sep.ps1 - prove core/proposal_intake on THIS repo, then commit it.
# Written 5 Sep 2026 by a session with files but no shell on this machine.
# Log: claude/reports/PLAN_CONTRACT_5SEP_launcher.log. Nothing here touches the GPU or Run A.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$log = Join-Path $repo "claude\reports\PLAN_CONTRACT_5SEP_launcher.log"
function Say($s) { $line = "$(Get-Date -Format o)  $s"; Write-Output $line; $line | Out-File -FilePath $log -Append -Encoding utf8 }
"=== PLAN_CONTRACT launcher $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8

Say "1. compile fast_cycle_runner.py + hyperclaw_orchestrator.py"
& venv\Scripts\python.exe -m py_compile fast_cycle_runner.py agents\hyperclaw\hyperclaw_orchestrator.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { Say "REFUSED: fast_cycle_runner.py does not compile. Nothing committed."; exit 2 }

Say "2. pytest test/test_hyperclaw_plan_contract.py test/test_proposal_intake.py"
$pt = & venv\Scripts\python.exe -m pytest test\test_hyperclaw_plan_contract.py test\test_proposal_intake.py -v 2>&1
$pt | Out-File -FilePath $log -Append -Encoding utf8
$ptText = ($pt | Out-String)
$ok = ($ptText -match "(\d+) passed") -and ($ptText -notmatch "failed|error")
Say "tests green: $ok"
if (-not $ok) { Say "REFUSED: tests not green. Nothing committed."; exit 2 }

Say "3. the prompt as tonight's cycle would build it (indicators from measured_axes)"
$st = & venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from agents.hyperclaw import hyperclaw_orchestrator as h; ind=h._gradeable_indicators(); print('gradeable indicators:', len(ind)); print(h._indicator_block(ind)[:1500])" 2>&1
$st | Out-File -FilePath $log -Append -Encoding utf8
Say ($st | Out-String)

Say "4. commit + push"
& git add agents\hyperclaw\hyperclaw_orchestrator.py test\test_hyperclaw_plan_contract.py fast_cycle_runner.py tools\commit_plan_contract_5sep.ps1 tools\COMMIT_PLAN_CONTRACT_5SEP.cmd 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Say "nothing new to commit; HEAD $(& git rev-parse --short HEAD)"; exit 0 }
$msg = @"
hyperclaw: the planner is told what it can do, what is gradeable, and what a step must carry (Kimi R31, step 2)

agents/hyperclaw/hyperclaw_orchestrator.py: the prompt now states CAPABILITIES
(CAN read indicators / write JSON / register predictions / publish / propose a
patch for a human; CANNOT email, survey, fund, build, deploy, contact anyone),
lists the GRADEABLE INDICATORS with tonight's values (core.hypothesis_intake.
measured_axes - the same gate as K1), and requires INDICATOR / EXPECTED_DELTA /
DEADLINE under every STEP. parse_plan() moves here from fast_cycle_runner and
reads exactly those three lines; it never fills a field it did not read, and the
fake measurable_goal = solution[:80] is gone.

fast_cycle_runner._hyperclaw_to_proposals now only picks the file and walks the
proposals to _inject_proposals; the private regex parser is deleted and a test
fails if it comes back.

Tonight: the first plan written under the contract. Steps that carry the three
lines and name a resolving indicator are admitted; the rest are refused by name.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Dxpf2HqjfhfNFS3BbGQK3e
"@
$msg | & git commit -q -F - 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
Say "committed $(& git rev-parse --short HEAD)"
& git push -q 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
Say "pushed (git output in log)"
