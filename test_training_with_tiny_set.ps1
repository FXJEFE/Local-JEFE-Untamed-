# test_training_with_tiny_set.ps1
# SAFE test of the Unsloth training script using only the tiny synthetic dataset.
# This will only do 1 epoch on ~28 examples - very fast and low risk.
#
# Usage:
#   cd C:\Users\LocalLarry\Documents\LocalLarry\GITHUB
#   .\personal_ai_training\test_training_with_tiny_set.ps1

Write-Host "=== SAFE TRAINING SCRIPT TEST ===" -ForegroundColor Cyan
Write-Host "Using tiny synthetic dataset (28 examples)"
Write-Host "Base model: cognitivecomputations/dolphin-2.9-llama3-8b (the only allowed one)"
Write-Host "This will run 1 epoch - should finish in 5-20 minutes depending on your machine.`n"

$dataset = "personal_ai_training/data/tiny_test_training_set.jsonl"
$output = "personal_ai_training/outputs/tiny_test_run"

if (-not (Test-Path $dataset)) {
    Write-Host "ERROR: Tiny dataset not found. Run generate_tiny_training_set.py first." -ForegroundColor Red
    exit 1
}

Write-Host "Starting safe training test...`n" -ForegroundColor Yellow

python personal_ai_training/train_personal_larry.py `
    --dataset $dataset `
    --output $output `
    --epochs 1 `
    --batch-size 1

Write-Host "`n=== Training test complete ===" -ForegroundColor Green
Write-Host "Check the output folder: $output"
Write-Host "If it succeeded without OOM, your hardware can handle the real training." -ForegroundColor Cyan
Write-Host "You can now scale up to your real curated dataset." -ForegroundColor Cyan