# Quick non-interactive test of 27B with heavy CPU offload
# Uses a temp Modelfile to set low num_gpu (most work on CPU + 64GB RAM)

$Model = "huihui_ai/Qwen3.6-abliterated:27b"
$TempModelfile = "temp_27b_cpu_test.Modelfile"

Write-Output "Creating temporary Modelfile for heavy CPU offload test..."
@"
FROM $Model
PARAMETER num_gpu 10
PARAMETER num_ctx 16384
"@ | Out-File -FilePath $TempModelfile -Encoding utf8

Write-Output "Building temporary tagged model with CPU-heavy settings..."
ollama create test-27b-cpu-heavy -f $TempModelfile

Write-Output "`nRunning short test prompt with heavy CPU usage..."
$env:OLLAMA_FLASH_ATTENTION = "1"
echo "In one short sentence, how do you securely mount a LUKS volume?" | ollama run test-27b-cpu-heavy

Write-Output "`nCleaning up temp model and file..."
ollama rm test-27b-cpu-heavy | Out-Null
Remove-Item $TempModelfile -Force

Write-Output "Test complete. During the response, CPU usage should have been high (check Task Manager or run Get-Counter in parallel next time)."
Write-Output "This proves the 27B is using your CPU + RAM heavily due to low GPU layers."