# ============================================================================
#  CORTEX_Collector - the independent sensing layer on a clock (#44).
#
#  Runs goal_impact_collector.py --from-needs: the SYSTEM picks the axis from
#  its own declared hunger, browses headless, and commits a real Merkle drop.
#
#  Doubles as the OLLAMA WATCHDOG: nothing here works without the local model,
#  so the first thing it does is check 11434 and start `ollama serve` hidden if
#  dead. A run that produced nothing because Ollama was down would otherwise be
#  indistinguishable from "the world had no signal today", so a failed start is
#  recorded in the run log as an explicit blocked entry, never as an empty read.
#
#  Args pass straight through to the collector (e.g. --dry to verify without
#  committing). No args = real drops, exactly what the schedule runs.
#
#  ASCII ONLY, deliberately: powershell.exe 5.1 reads a BOM-less .ps1 as ANSI,
#  and a stray multi-byte character breaks the parser at load time.
# ============================================================================
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CollectorArgs)

$ErrorActionPreference = 'Continue'
$Repo    = 'C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED'
$Py      = Join-Path $Repo 'venv\Scripts\python.exe'
$Script  = Join-Path $Repo 'experiments\browser_scout\goal_impact_collector.py'
$RunsLog = Join-Path $Repo 'memory\collector_runs.jsonl'
$Ollama  = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
$Tags    = 'http://localhost:11434/api/tags'

function Write-Beat($phase, $msg) {
    $ts = (Get-Date).ToUniversalTime().ToString('HH:mm:ss')
    Write-Host "[WRAPPER $ts] $phase -> $msg"
}

function Test-Ollama {
    try { $null = Invoke-RestMethod -Uri $Tags -TimeoutSec 5 -ErrorAction Stop; return $true }
    catch { return $false }
}

function Write-Blocked($reason) {
    # the run log must say WHY there is no drop, or a dead dependency reads as silence
    $entry = [ordered]@{
        ts      = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        mode    = 'blocked'
        axis    = $null
        blocked = $reason
    } | ConvertTo-Json -Compress
    Add-Content -Path $RunsLog -Value $entry -Encoding utf8
}

# ---- 1. Ollama alive-check / watchdog --------------------------------------
if (Test-Ollama) {
    Write-Beat 'ollama' 'already up'
} else {
    Write-Beat 'ollama' 'DOWN - starting serve (hidden)'
    if (-not (Test-Path $Ollama)) {
        Write-Beat 'ollama' "NOT INSTALLED at $Ollama - aborting"
        Write-Blocked "ollama binary missing at $Ollama"
        exit 3
    }
    Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden
    $up = $false
    foreach ($i in 1..20) {
        Start-Sleep -Seconds 3
        if (Test-Ollama) { $up = $true; Write-Beat 'ollama' "up after $($i*3)s"; break }
    }
    if (-not $up) {
        Write-Beat 'ollama' 'did NOT come up within 60s - aborting'
        Write-Blocked 'ollama did not answer /api/tags within 60s of serve'
        exit 3
    }
}

# ---- 2. Guards + headless, then run ----------------------------------------
# HEADFUL KNOB -- currently '1' as a STOPGAP, and it should go back to '0'.
#
# Headless search is blocked: measured 2026-07-31, same query back to back, headful 3
# pages vs headless 0 (DuckDuckGo and Google time out on the results selector, Bing
# returns no links; AutomationControlled/webdriver hiding does not help). Only the
# TYPING-INTO-AN-ENGINE half is blocked, so human_browse_read now discovers URLs through
# the Brave Search API when headless and still reads each page in the browser.
#
# That path needs BRAVE_API_KEY in .env, which is NOT set on this box (checked
# 2026-07-31: 9 other keys present, no Brave). Free tier is 2000 req/month at
# brave.com/search/api -- at 4-hourly runs that is ~180/month, well inside it.
#
# Until the key exists this must be '1' or the scheduled eye is blind: a visible browser
# window 4x/day, which is the only way it senses anything at all. Set it back to '0' the
# moment BRAVE_API_KEY is configured.
$HeadfulMode = '1'

$env:PYTHONIOENCODING        = 'utf-8'
$env:CORTEX_BROWSER_HEADFUL  = $HeadfulMode
$env:CORTEX_LOCAL_MODEL      = 'qwen2.5:7b'
$env:CORTEX_STRUCTURAL_GUARD = '1'    # DNA-vs-DNA decomposition, opt-in elsewhere
$env:CORTEX_SIGN_GUARD       = '1'    # canon-anchored sign skeptic (default on)
$env:CORTEX_RELEVANCE_GATE   = '1'    # boilerplate + axis relevance (default on)

Write-Beat 'run' "model=$($env:CORTEX_LOCAL_MODEL) headful=$($env:CORTEX_BROWSER_HEADFUL) guards=structural+sign+relevance"
& $Py $Script --from-needs @CollectorArgs
$code = $LASTEXITCODE
Write-Beat 'done' "collector exit=$code"
exit $code
