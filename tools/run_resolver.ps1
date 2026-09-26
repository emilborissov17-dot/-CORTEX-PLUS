# tools/run_resolver.ps1 - the forward-row resolver, witnessed (task #30, 26 Sep 2026).
#
# Fired by the CORTEX_ResolveForward task (monthly, the 5th and the 22nd at 06:00;
# UCDP extracts candidate data on the 20th). It starts
#   experiments/institution/resolve_forward_rows.py --publish
# under tools/cycle_witness.ps1 with role "resolver" (start and exit rows in
# memory/witness.jsonl, cycle_id "resolver:<timestamp>"), and launches that through
# tools/launch_detached.ps1 so the run outlives the task's own process.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\run_resolver.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$cid = "resolver:" + (Get-Date -Format "o")
$py = Join-Path $repo "venv\Scripts\python.exe"
$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$argv = @("-u", (Join-Path $repo "experiments\institution\resolve_forward_rows.py"), "--publish")
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json $argv -Compress)))
$log = Join-Path $repo "memory\cycle_logs\resolver_$stamp.log"
$witnessLog = Join-Path $repo "memory\witness.jsonl"
$env:PYTHONIOENCODING = "utf-8"
$wargs = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$repo\tools\cycle_witness.ps1`" " +
         "-Exe `"$py`" -ArgsB64 $b64 -Log `"$log`" -WitnessLog `"$witnessLog`" " +
         "-CycleId `"$cid`" -WorkDir `"$repo`" -Role resolver"
& $ps -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "tools\launch_detached.ps1") `
    -Exe $ps -Arguments $wargs -Log "memory\cycle_logs\resolver_launch_$stamp.log"
Write-Output "resolver launched: cycle_id=$cid log=$log"
