$ErrorActionPreference = 'Stop'
$toolRoot = $PSScriptRoot
$logDir = Join-Path $toolRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$env:OLLAMA_MODELS = Join-Path $toolRoot 'local-models\ollama'
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_KEEP_ALIVE = '0'

function Test-LocalService([string] $Url) {
    try { Invoke-RestMethod -Uri $Url -TimeoutSec 2 | Out-Null; return $true }
    catch { return $false }
}

if (-not (Test-LocalService 'http://127.0.0.1:11434/api/tags')) {
    $ollamaExe = Join-Path $toolRoot 'tools\ollama\ollama.exe'
    if (-not (Test-Path -LiteralPath $ollamaExe)) { throw 'Portable Ollama is missing. Run download_local_models.py.' }
    Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden -WorkingDirectory $toolRoot -RedirectStandardOutput (Join-Path $logDir 'ollama.out.log') -RedirectStandardError (Join-Path $logDir 'ollama.err.log') | Out-Null
}
if (-not (Test-LocalService 'http://127.0.0.1:8190/system_stats')) {
    $comfyRoot = 'C:\src\ai drama\tools\ComfyUI'
    $comfyPython = 'C:\src\ai drama\.wan-venv\Scripts\python.exe'
    $comfyArgs = 'main.py --listen 127.0.0.1 --port 8190 --lowvram --cache-none --reserve-vram 0.6 --disable-auto-launch --disable-pinned-memory'
    Start-Process -FilePath $comfyPython -ArgumentList $comfyArgs -WindowStyle Hidden -WorkingDirectory $comfyRoot -RedirectStandardOutput (Join-Path $logDir 'comfyui.out.log') -RedirectStandardError (Join-Path $logDir 'comfyui.err.log') | Out-Null
}
$deadline = (Get-Date).AddMinutes(10)
do {
    if ((Test-LocalService 'http://127.0.0.1:11434/api/tags') -and (Test-LocalService 'http://127.0.0.1:8190/system_stats')) {
        Write-Host 'Local AI services ready.'
        exit 0
    }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
throw "AI services did not start. Check logs in $logDir."
