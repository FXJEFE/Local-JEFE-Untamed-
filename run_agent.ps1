# run_agent.ps1
# Convenient launcher for the editable source in GITHUB/src
# Usage: .\run_agent.ps1

$ErrorActionPreference = "Stop"

$srcDir = Join-Path $PSScriptRoot "src"
$python = "C:/Users/LocalLarry/AppData/Local/Programs/Python/Python311/python.exe"

if (-not (Test-Path $python)) {
    $python = "python"   # fallback to PATH
}

Write-Host "Launching agent from clean GITHUB structure..." -ForegroundColor Cyan
& $python "$srcDir\agent_v2.py" @args
