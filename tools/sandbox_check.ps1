# tools\sandbox_check.ps1 — Windows launcher for the sandbox probes.
#
# Runs tools/sandbox/check.sh inside WSL2 Ubuntu as root and relays its output.
# It copies check.sh into the distro first and strips CRLF: this repo checks out
# with CRLF on Windows, and `sh` answers a CRLF script with
#     run.sh: 8: Syntax error: end of file unexpected (expecting "then")
# which reads like a bug in the script rather than a line-ending problem. That
# exact error cost time on 18 Sep 2026; it is handled here so nobody pays twice.
#
# Exit code is check.sh's own: 0 when all ten probes behaved, 1 when a probe
# failed (check.sh names which and stops), 2 when the sandbox is not built.
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\sandbox_check.ps1

$ErrorActionPreference = 'Stop'

$repo   = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo 'tools\sandbox\check.sh'
if (-not (Test-Path $script)) { Write-Error "not found: $script"; exit 2 }

# The literal WSL path of this repo's check.sh, via /mnt/c.
$wslSrc = '/mnt/c' + ($script.Substring(2) -replace '\\', '/')

Write-Host "sandbox_check: copying $wslSrc -> /root/omega-check.sh" -ForegroundColor DarkGray
wsl -d Ubuntu -u root -e bash -lc "cp '$wslSrc' /root/omega-check.sh && sed -i 's/\r`$//' /root/omega-check.sh && chmod 755 /root/omega-check.sh"
if ($LASTEXITCODE -ne 0) { Write-Error "could not stage check.sh into the distro"; exit 2 }

wsl -d Ubuntu -u root -e bash -lc "bash /root/omega-check.sh"
$rc = $LASTEXITCODE

Write-Host ""
switch ($rc) {
    0 { Write-Host "sandbox_check: all thirteen probes behaved as required (exit 0)" -ForegroundColor Green }
    1 { Write-Host "sandbox_check: A PROBE FAILED (exit 1). The named probe is above. Do not weaken the fence to make it pass." -ForegroundColor Red }
    2 { Write-Host "sandbox_check: the sandbox is not built in this distro (exit 2). See tools/sandbox/README.md." -ForegroundColor Yellow }
    default { Write-Host "sandbox_check: check.sh exited $rc" -ForegroundColor Red }
}
exit $rc
