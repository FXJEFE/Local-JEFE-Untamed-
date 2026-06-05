# Tiny Larry Agent Launcher (PowerShell)
# Always does correct bootstrap + venv activation for C:\Users\LocalLarry\Documents\LocalLarry

$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Definition)

# 1. Canonical bootstrap
try {
    Import-Module -Name ".\larry_paths.py" -ErrorAction SilentlyContinue
} catch {}
python -c "import larry_paths; larry_paths.bootstrap()" 2>$null

# 2. Find the best Python (prefer .venv)
$venvPy = ".\.venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    $python = $venvPy
    Write-Host "Using venv Python: $python" -ForegroundColor Green
} else {
    $python = "C:\Users\LocalLarry\AppData\Local\Programs\Python\Python311\python.exe"
    if (-not (Test-Path $python)) { $python = "python" }
    Write-Host "WARNING: No .venv found at .\.venv - using $python" -ForegroundColor Yellow
    Write-Host "Run: python activate_runtime.py --venv-only   to create it" -ForegroundColor Yellow
}

# 3. Launch via central manager when possible
if (Test-Path ".\.venv\Scripts\python.exe") {
    & ".\.venv\Scripts\python.exe" "manage_larry.py" "start-agent" @args
} else {
    & $python "agent_v2.py" @args
}
