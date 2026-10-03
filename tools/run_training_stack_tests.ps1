# tools/run_training_stack_tests.ps1 - the tests the gate deselects as `training_stack`, run where
# they belong (C-GATE-1, 3 Oct 2026).
#
# The main venv has no bitsandbytes; venv_train has it. The tests marked
# @pytest.mark.training_stack build the real BitsAndBytesConfig, so the gate
# (tools/suite_gate.py, tools/full_suite_detached.ps1) deselects them by that marker and THIS
# script runs them under venv_train. A failure here is a failure: the exit code is non-zero.
#
# REFUSED, not passed: a run in which nothing passed, or in which any selected test was skipped -
# a skip would turn a red into something that looks like a result (DEFECT-B).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\run_training_stack_tests.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$py = Join-Path $repo "venv_train\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Output "REFUSED: no venv_train at $py - the training_stack tests cannot run anywhere else"
    exit 3
}

# Only the files that carry the marker are collected: venv_train lacks the main venv's packages,
# and collecting all of test/ there fails on modules that have nothing to do with this stack.
$files = @(git grep -l -E "^[[:space:]]*@pytest[.]mark[.]training_stack" -- "test/test_*.py")
if ($files.Count -eq 0) {
    Write-Output "REFUSED: no test file carries @pytest.mark.training_stack"
    exit 4
}
Write-Output ("files: " + ($files -join " "))

$env:PYTHONIOENCODING = "utf-8"
$env:CORTEX_NO_REAL_MODEL = "1"
$out = & $py -m pytest @files -v -rA -m training_stack -p no:cacheprovider 2>&1 | ForEach-Object { "$_" }
$rc = $LASTEXITCODE
$out | ForEach-Object { Write-Output $_ }

$summary = ($out | Where-Object { $_ -match "^=+ .* in [0-9.]+s" } | Select-Object -Last 1)
if ($rc -ne 0) {
    Write-Output "TRAINING_STACK: FAILED (pytest exit $rc)"
    exit $rc
}
if (-not $summary -or $summary -notmatch " passed" -or $summary -match " skipped") {
    Write-Output "TRAINING_STACK: REFUSED - nothing passed or a selected test was skipped: $summary"
    exit 4
}
Write-Output "TRAINING_STACK: OK - $summary"
exit 0
