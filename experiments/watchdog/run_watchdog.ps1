# ============================================================================
#  CORTEX_TriggerWatchdog - reads the pulse's raw signal, applies thresholds it
#  never computes, and can only ever write a PROPOSAL.
#
#  Its own schedule, separate from CORTEX_Pulse, on purpose: the thing that
#  decides whether to escalate should not share a heartbeat with the thing that
#  benefits from escalating.
#
#  Needs no model and no network - deterministic, so nothing to wait on.
#
#  ASCII ONLY - powershell.exe 5.1 reads a BOM-less .ps1 as ANSI.
# ============================================================================
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args2)

$ErrorActionPreference = 'Continue'
$Repo   = 'C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED'
$Py     = Join-Path $Repo 'venv\Scripts\python.exe'
$Script = Join-Path $Repo 'experiments\watchdog\trigger_watchdog.py'

$env:PYTHONIOENCODING = 'utf-8'
& $Py $Script @Args2
exit $LASTEXITCODE
