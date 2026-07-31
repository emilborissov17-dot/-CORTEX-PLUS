# ============================================================================
#  CORTEX_Pulse - one tick of the continuum (#50), every 5 minutes.
#
#  OLLAMA-TOLERANT BY DESIGN: ticks 1-5 (context, self-state line, necessity,
#  waking actions) are deterministic and never need the model. The reflection
#  and the ideation articulation skip themselves silently when it is dead. So
#  this wrapper does NOT start ollama and does NOT wait for it -- a pulse that
#  blocks on a model is not a pulse. If the model being down matters, the tick
#  itself scores it (+2 "ollama dead") and the waking action starts it.
#
#  ASCII ONLY - powershell.exe 5.1 reads a BOM-less .ps1 as ANSI.
# ============================================================================
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PulseArgs)

$ErrorActionPreference = 'Continue'
$Repo   = 'C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED'
$Py     = Join-Path $Repo 'venv\Scripts\python.exe'
$Script = Join-Path $Repo 'experiments\pulse\pulse_continuum.py'

$env:PYTHONIOENCODING = 'utf-8'
& $Py $Script @PulseArgs
exit $LASTEXITCODE
