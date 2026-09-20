# tools/full_suite_detached.ps1 - the full suite, detached, into claude/reports/.
#
# WHY THIS EXISTS (20 September 2026)
# -----------------------------------
# The full suite was killed twice in one afternoon at 42% and 76% - not by a
# failure, by the host reclaiming memory while the session sat idle. A forty
# minute run that only ever happens while somebody is watching is a run that
# happens when the machine is busiest and the memory is thinnest.
#
# So it runs at 05:30, after the nightly cycle (03:04, and 100-108 minutes on
# 18/19/20 Sep), detached from whatever started it, into a dated log a human
# reads in the morning. A console that closes takes its scrollback with it;
# claude/reports/ does not.
#
# WHY A WRAPPER AND NOT A SCHEDULED TASK STRAIGHT TO launch_detached.ps1.
# The pytest marker expression is `-m "not live_state"` - two words, one
# argument. Passing that through schtasks, through powershell -File and into
# Start-Process means three layers of quoting, each with its own rules, all of
# them unattended at half past five. Here the quoting is written once, in a
# file, where it can be RUN and checked instead of reasoned about.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\full_suite_detached.ps1
#   powershell ... -File tools\full_suite_detached.ps1 -Target test\test_quote_gate.py
#
# -Target exists so the quoting can be proved on one cheap file before the run
# that matters. The production path differs by that one argument and nothing
# else.
param(
    [string]$Target = "test/",
    [string]$Tag = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$stamp = Get-Date -Format "yyyy-MM-dd"
$suffix = if ($Tag) { "_$Tag" } else { "" }
$log = "claude\reports\SUITE_FULL_$stamp$suffix.log"

# -rf so the summary names every failure; --continue-on-collection-errors so one
# module that cannot even be imported does not hide the other five thousand
# tests, which is exactly what test_origin_honesty did until this morning.
$pytestArgs = '-m pytest ' + $Target + ' -q -rf -m "not live_state" --continue-on-collection-errors'

& (Join-Path $repo "tools\launch_detached.ps1") `
    -Exe "venv\Scripts\python.exe" `
    -Arguments $pytestArgs `
    -Log $log

Write-Output "full suite launched detached -> $log (.out.log for the result)"
