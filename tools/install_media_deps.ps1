# tools/install_media_deps.ps1 — ffmpeg + deno for the transcript chain (3 Sep 2026)
#
# WHY. Every video in the 1-3 Sep cycle logs printed two yt-dlp warnings:
#   "ffmpeg not found"                          -> the Whisper leg (-x audio extract) never worked
#   "No supported JavaScript runtime ... deno"  -> YouTube signature solving fails
# The cycle does NOT install anything for itself (Kimi, 15 Aug: "pip install без надзор е
# ДУПКА, не бордюр"). This is the HUMAN action, run once, as the user that owns the
# CORTEX_Supervisor scheduled task (the task inherits that user's PATH at next logon;
# core/media_tools.py finds the binaries by explicit path anyway, so no re-logon is needed).
#
# RUN (PowerShell, from the repo root):
#   powershell -ExecutionPolicy Bypass -File tools\install_media_deps.ps1
# or double-click tools\install_media_deps.bat
#
# VERIFY (what the scheduled cycle will actually see):
#   venv\Scripts\python.exe -m core.media_tools --selftest

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo

function Say($m) { Write-Host ("[install_media_deps] " + $m) }

$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    Say "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."
    Say "Manual fallback: drop ffmpeg.exe into $repo\bin\ffmpeg\ and deno.exe into $repo\bin\deno\ (bin/ is gitignored)."
    exit 2
}

# --- ffmpeg (Gyan.FFmpeg = the standard Windows build; winget exposes ffmpeg.exe via WinGet\Links)
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ff) { Say ("ffmpeg already present: " + $ff.Source) }
else {
    Say "installing ffmpeg (Gyan.FFmpeg) via winget..."
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements --silent
    Say ("winget ffmpeg exit code: " + $LASTEXITCODE)
}

# --- deno (DenoLand.Deno; yt-dlp's default JS runtime)
$dn = Get-Command deno -ErrorAction SilentlyContinue
if ($dn) { Say ("deno already present: " + $dn.Source) }
else {
    Say "installing deno (DenoLand.Deno) via winget..."
    winget install --id DenoLand.Deno -e --accept-source-agreements --accept-package-agreements --silent
    Say ("winget deno exit code: " + $LASTEXITCODE)
}

# --- refresh PATH for THIS shell only (winget writes the user PATH; a running shell does not see it)
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("PATH", "User")

# --- prove it, through the interpreter the cycle uses, not through this shell
$py = Join-Path $repo "venv\Scripts\python.exe"
if (Test-Path $py) {
    $env:PYTHONIOENCODING = "utf-8"
    & $py -m core.media_tools --selftest
    if ($LASTEXITCODE -eq 0) { Say "BOTH FOUND. Next 03:00 cycle will pass --ffmpeg-location and --js-runtimes." }
    else { Say "at least one binary still not visible - read the selftest lines above; a new PowerShell window (fresh PATH) and re-running the selftest is the first thing to try." }
} else {
    Say "venv\Scripts\python.exe not found at $py - run the selftest from the repo root by hand."
}
