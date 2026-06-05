# test_27b_with_cpu_monitor.ps1
# Launches the 27B abliterated model with HEAVY CPU offloading
# and shows real-time CPU + RAM usage while it runs.
#
# Usage:
#   cd C:\Users\LocalLarry\Documents\LocalLarry\GITHUB
#   .\personal_ai_training\test_27b_with_cpu_monitor.ps1

param(
    [int]$GpuLayers = 12,   # Lower = more CPU/RAM usage. Start at 12 for 27B on 8GB VRAM
    [int]$MonitorSeconds = 300
)

$Model = "huihui_ai/Qwen3.6-abliterated:27b"

Write-Host "=== TESTING 27B MODEL WITH HEAVY CPU OFFLOAD ===" -ForegroundColor Cyan
Write-Host "Model: $Model"
Write-Host "GPU Layers: $GpuLayers (most layers will run on CPU + 64GB RAM)"
Write-Host "This will show CPU/RAM usage in real time.`n"

# Enable flash attention
$env:OLLAMA_FLASH_ATTENTION = "1"

# Start a background job to monitor CPU and RAM every 2 seconds
$monitorJob = Start-Job -ScriptBlock {
    param($duration)
    $endTime = (Get-Date).AddSeconds($duration)
    while ((Get-Date) -lt $endTime) {
        $cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 1).CounterSamples.CookedValue
        $ram = Get-CimInstance Win32_OperatingSystem | 
               Select-Object @{Name="UsedGB"; Expression={[math]::Round(($_.TotalVisibleMemorySize - $_.FreePhysicalMemory)/1MB,1)}},
                             @{Name="TotalGB"; Expression={[math]::Round($_.TotalVisibleMemorySize/1MB,1)}}
        
        $gpu = try { 
            (nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null) 
        } catch { "N/A" }

        Write-Output "CPU: $([math]::Round($cpu,1))% | RAM: $($ram.UsedGB)/$($ram.TotalGB) GB | GPU: $gpu"
        Start-Sleep -Seconds 2
    }
} -ArgumentList $MonitorSeconds

Write-Host "Starting 27B model with heavy CPU offloading...`n" -ForegroundColor Yellow
Write-Host "When the model loads, type test prompts like:" -ForegroundColor Green
Write-Host "  'How do I securely set up LUKS with keyfile on Ubuntu?'"
Write-Host "Watch the CPU and RAM numbers go up as layers run on CPU.`n"

# Launch Ollama with low GPU layers (most work on CPU)
ollama run $Model --num-gpu $GpuLayers

# When user exits the model, stop monitoring
Stop-Job $monitorJob -ErrorAction SilentlyContinue
Remove-Job $monitorJob -ErrorAction SilentlyContinue

Write-Host "`n=== Test complete ===" -ForegroundColor Cyan
Write-Host "If CPU stayed high (30-80%) during generation, offloading is working."
Write-Host "Lower --num-gpu in future runs if you want even more CPU usage." -ForegroundColor Yellow