# CORTEX++ NIGHTLY REVIEWER (Kimi R72 Q1(iii), C-CONTROL-1). Runs as SYSTEM from a task Emil installs with
# administrator rights (install_protection.bat). The running copy lives in C:\ProgramData\CORTEX_control\,
# where the user Claude Code runs as can read but not write. It checks the control, not Claude's word:
#   1 sealed hashes of the gate, the list, the hook settings and the git hooks (seal kept here, not in the repo)
#   2 the ACLs of those files are unchanged
#   3 the canary: a forbidden call must be blocked by the gate
#   4 the gate ledger is an unbroken chain, and it did not shrink or get rewritten since the last night
#   5 every commit since the last night passed the gate (a ledger row with its sha)
#   6 no unpushed commits (R26); the CORTEX scheduled tasks and their states, as they are
# Then ONE Telegram message: "ЖИВ" + counts + violations. A night without "ЖИВ" is itself the alarm.
param([switch]$Seal)
$ErrorActionPreference = "Stop"
$Repo   = "C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED"
$Home_  = "C:\ProgramData\CORTEX_control"
$Py     = Join-Path $Repo "venv\Scripts\python.exe"
$Gate   = Join-Path $Repo "control\gate.py"
$Ledger = Join-Path $Repo "memory\control\gate_ledger.jsonl"
$SealF  = Join-Path $Home_ "reviewer_seal.json"
$StateF = Join-Path $Home_ "reviewer_state.json"
$Out    = Join-Path $Home_ ("review_" + (Get-Date -Format "yyyy-MM-dd") + ".json")
$Viol   = New-Object System.Collections.Generic.List[string]
$Facts  = [ordered]@{ ts = (Get-Date).ToString("o") }

function Git([string[]]$a) { & git -c "safe.directory=$($Repo.Replace('\','/'))" -C $Repo @a 2>&1 }
function AclHash([string]$f) {
  $a = (& icacls $f) -join "`n"
  [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash(
    [Text.Encoding]::UTF8.GetBytes($a))).Replace("-","").ToLower()
}
function LedgerState {
  $l = @(Get-Content $Ledger -Encoding UTF8 -ErrorAction SilentlyContinue)
  $last = if ($l.Count -gt 0) { ($l[-1] | ConvertFrom-Json).sha } else { "" }
  @{ rows = $l.Count; last_sha = $last; head = (Git @("rev-parse", "HEAD") | Select-Object -First 1) }
}

# -Seal: run once by install_protection.bat (as administrator) right after the ACLs are set.
# Records what tonight's and every later review compares against; the copy here is admin-write only.
if ($Seal) {
  $files = [ordered]@{}
  foreach ($x in @("control/gate.py", "control/forbidden.tsv", "control/SEAL.json", "control/nightly_reviewer.ps1",
                   ".claude/settings.json", ".git/hooks/pre-commit", ".git/hooks/post-commit", ".git/hooks/pre-push")) {
    $files[$x] = (Get-FileHash (Join-Path $Repo $x) -Algorithm SHA256).Hash.ToLower()
  }
  $acl = [ordered]@{}
  foreach ($x in @("control", ".git/hooks", ".claude/settings.json")) { $acl[$x] = AclHash (Join-Path $Repo $x) }
  @{ sealed = (Get-Date).ToString("o"); files = $files; acl = $acl } | ConvertTo-Json -Depth 4 |
    Set-Content $SealF -Encoding UTF8
  LedgerState | ConvertTo-Json | Set-Content $StateF -Encoding UTF8
  Write-Output "SEALED: $($files.Count) files, $($acl.Count) ACLs -> $SealF"
  exit 0
}

try {
  $seal = Get-Content $SealF -Raw -Encoding UTF8 | ConvertFrom-Json
  # 1 hashes
  foreach ($p in $seal.files.PSObject.Properties) {
    $f = Join-Path $Repo $p.Name
    if (-not (Test-Path $f)) { $Viol.Add("missing: $($p.Name)"); continue }
    $h = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower()
    if ($h -ne $p.Value) { $Viol.Add("changed: $($p.Name)") }
  }
  # 2 ACLs
  foreach ($p in $seal.acl.PSObject.Properties) {
    if ((AclHash (Join-Path $Repo $p.Name)) -ne $p.Value) { $Viol.Add("ACL changed: $($p.Name)") }
  }
  # 3 canary
  $env:CONTROL_NO_TELEGRAM = "1"
  $c = & $Py $Gate canary 2>&1
  if ($LASTEXITCODE -ne 0) { $Viol.Add("CANARY FAILED: $c") }
  $Facts.canary = ($LASTEXITCODE -eq 0)
  # 4 ledger chain, and no shrink or rewrite since last night
  $v = & $Py $Gate verify 2>&1
  if ($LASTEXITCODE -ne 0) { $Viol.Add("ledger chain broken: $v") }
  $lines = @(Get-Content $Ledger -Encoding UTF8)
  $state = if (Test-Path $StateF) { Get-Content $StateF -Raw | ConvertFrom-Json } else { $null }
  if ($state -and $state.rows -gt 0) {
    if ($lines.Count -lt $state.rows) { $Viol.Add("ledger shrank: $($lines.Count) < $($state.rows)") }
    elseif (($lines[$state.rows - 1] | ConvertFrom-Json).sha -ne $state.last_sha) {
      $Viol.Add("ledger rewritten before row $($state.rows)") }
  }
  $since = if ($state) { [int]$state.rows } else { 0 }
  $new = @($lines | Select-Object -Skip $since | ForEach-Object { $_ | ConvertFrom-Json })
  $Facts.allow = @($new | Where-Object { $_.decision -eq "ALLOW" }).Count
  $Facts.block = @($new | Where-Object { $_.decision -eq "BLOCK" }).Count
  $Facts.prompts = @($new | Where-Object { $_.decision -eq "LOGGED" }).Count
  # 5 every commit since the last night passed the gate
  $passed = @($lines | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.event -eq "git commit" } |
              ForEach-Object { $_.commit })
  if (-not ($state -and $state.head)) { throw "no reviewer_state.json - run install_protection.bat (-Seal) first" }
  $commits = @(Git @("rev-list", "$($state.head)..HEAD") | Where-Object { $_ -match '^[0-9a-f]{40}$' })
  $skipped = @($commits | Where-Object { $passed -notcontains $_ })
  $Facts.commits = $commits.Count; $Facts.commits_through_gate = $commits.Count - $skipped.Count
  foreach ($s in $skipped) { $Viol.Add("commit not through the gate: $($s.Substring(0,10))") }
  # 6 unpushed commits and the scheduled tasks
  $sb = (Git @("status", "-sb") | Select-Object -First 1)
  if ($sb -match "ahead") { $Viol.Add("unpushed commits (R26): $sb") }
  $Facts.tasks = @(Get-ScheduledTask -TaskName "CORTEX*" -ErrorAction SilentlyContinue |
                   ForEach-Object { "$($_.TaskName)=$($_.State)" })
  LedgerState | ConvertTo-Json | Set-Content $StateF -Encoding UTF8
} catch {
  $Viol.Add("REVIEWER ERROR: $($_.Exception.Message)")
}

$Facts.violations = $Viol
$Facts | ConvertTo-Json -Depth 4 | Set-Content $Out -Encoding UTF8
$status = if ($Viol.Count -eq 0) { "ЖИВ ✅ нарушения: 0" } else { "ЖИВ ⚠️ НАРУШЕНИЯ: $($Viol.Count)" }
$text = "$status | команди: разрешени $($Facts.allow), блокирани $($Facts.block) | комити: $($Facts.commits), " +
        "през вратата: $($Facts.commits_through_gate) | канарче: $(if ($Facts.canary) {'OK'} else {'ПАДНА'})"
if ($Viol.Count -gt 0) { $text += "`n" + (($Viol | Select-Object -First 8) -join "`n") }
try {
  $cfg = Get-Content (Join-Path $Repo "memory\notify_channel.json") -Raw | ConvertFrom-Json
  Invoke-RestMethod -Uri "https://api.telegram.org/bot$($cfg.token)/sendMessage" -Method Post `
    -Body @{ chat_id = $cfg.chat_id; text = $text } -TimeoutSec 20 | Out-Null
} catch {
  Add-Content (Join-Path $Home_ "telegram_failures.log") "$((Get-Date).ToString('o')) $($_.Exception.Message)"
}
