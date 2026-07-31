# ============================================================================
#  Hyperon/MeTTa sidecar setup - engine local, isolated, main venv UNTOUCHED.
#
#  hyperon publishes no wheel for the main venv's Python (3.14), so the engine
#  gets its own 3.12 interpreter and venv. Nothing is installed into venv/, and
#  nothing here is on the cycle's critical path: metta_oracle.py speaks to this
#  over stdin/stdout JSON and fails open if it is missing.
#
#  Idempotent: re-running only fills in what is absent.
#
#  ASCII ONLY - powershell.exe 5.1 reads a BOM-less .ps1 as ANSI and a stray
#  multi-byte character breaks the parser at load time.
#
#    powershell -ExecutionPolicy Bypass -File experiments\symbolic_duel\setup_sidecar.ps1
# ============================================================================
$ErrorActionPreference = 'Stop'

$Repo    = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$VenvDir = Join-Path $Repo 'venv312_metta'
$VenvPy  = Join-Path $VenvDir 'Scripts\python.exe'
$Py312   = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'

function Say($m) { Write-Host "[sidecar] $m" }

# ---- 1. a 3.12 interpreter -------------------------------------------------
if (-not (Test-Path $Py312)) {
    Say "Python 3.12 not found at $Py312"
    Say "winget is NOT present on this box, so install the official user-scope build:"
    Say "  1. download https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    Say "  2. run: python-3.12.10-amd64.exe /quiet InstallAllUsers=0 PrependPath=0 \"
    Say "          InstallLauncherAllUsers=0 Include_launcher=1 Include_test=0 Include_doc=0"
    Say "PrependPath=0 is deliberate: PATH stays as it is so the main venv workflow"
    Say "is unaffected. 3.12.11+ are source-only releases - .10 is the newest binary."
    throw "no Python 3.12 interpreter"
}
Say "interpreter: $Py312 ($(& $Py312 --version))"

# ---- 2. the sidecar venv ---------------------------------------------------
if (Test-Path $VenvPy) {
    Say "venv already present: $VenvDir"
} else {
    Say "creating venv -> $VenvDir"
    & $Py312 -m venv $VenvDir
}

# ---- 3. hyperon ------------------------------------------------------------
$have = & $VenvPy -c "import hyperon,sys; sys.stdout.write(getattr(hyperon,'__version__','?'))" 2>$null
if ($LASTEXITCODE -eq 0 -and $have) {
    Say "hyperon already installed: $have"
} else {
    Say "installing hyperon..."
    & $VenvPy -m pip install --disable-pip-version-check hyperon
    $have = & $VenvPy -c "import hyperon,sys; sys.stdout.write(getattr(hyperon,'__version__','?'))"
}

Say "hyperon $have on $(& $VenvPy --version)"
Say "verifying the oracle end to end..."
& (Join-Path $Repo 'venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'metta_oracle.py')
exit $LASTEXITCODE
