# Quick launcher for the Live CLI TUI Monitor
Write-Host "🚀 Starting Larry Live Monitor TUI..." -ForegroundColor Cyan
Write-Host "This gives you real-time visibility into Telegram bot + heavy agent tasks." -ForegroundColor Yellow
Write-Host ""

cd $PSScriptRoot
python live_monitor.py
