param([switch]$Install, [switch]$WithVideo)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
if ($Install) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Install Microsoft App Installer (winget) from Microsoft Store first.' }
    Write-Host 'Installing prerequisites for this Windows user. Windows may ask for approval.'
    foreach ($package in @('Python.Python.3.11','Git.Git','Ollama.Ollama')) {
        & winget install --id $package --exact --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { Write-Warning "winget returned $LASTEXITCODE for $package. Checking installed commands next." }
    }
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Python launcher missing. Install Python 3.11 or reopen terminal after setup.' }
if ($Install -and -not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is not available. Reopen terminal and retry.' }
if ($Install) {
    try { Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 2 | Out-Null }
    catch { Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden; Start-Sleep -Seconds 5 }
}
$installerArgs = @('-3.11', (Join-Path $PSScriptRoot 'setup_windows.py'))
if ($Install) { $installerArgs += '--install' }
if ($WithVideo) { $installerArgs += '--with-video' }
& py @installerArgs
if ($LASTEXITCODE -ne 0) { throw 'Setup did not finish. Read the error above; rerun to reuse verified downloads.' }
