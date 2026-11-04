#Requires -Version 5.1
$ErrorActionPreference = "Continue"

$RepoRoot = Split-Path -Parent $PSScriptRoot

function Find-OllamaExe {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$OllamaExe = Find-OllamaExe
if (-not $OllamaExe) {
    Write-Host "=== [1/3] Instalando/Reparando Ollama vía winget ===" -ForegroundColor Cyan
    winget install --id Ollama.Ollama --force --accept-package-agreements --accept-source-agreements
    $OllamaExe = Find-OllamaExe
}

if (-not $OllamaExe) {
    Write-Error "No se encontró ollama.exe tras la instalación."
    exit 1
}
Write-Host "-> Ollama binario: $OllamaExe" -ForegroundColor Green

# Verificar si el servidor localhost:11434 está escuchando
$ServerUp = $false
try {
    $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 2
    $ServerUp = $true
} catch {
    $ServerUp = $false
}

if (-not $ServerUp) {
    Write-Host "=== [2/3] Iniciando servidor local de Ollama (localhost:11434) ===" -ForegroundColor Cyan
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        try {
            $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 2
            $ServerUp = $true
            break
        } catch {}
    }
}

Write-Host "=== [3/3] Verificando modelo qwen2.5:3b ===" -ForegroundColor Cyan
& $OllamaExe pull qwen2.5:3b

Write-Host "`n=== Ejecutando prueba de clasificación en vivo ===" -ForegroundColor Cyan
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$TestScript = Join-Path $RepoRoot "scripts\test_brain_cli.py"
& $VenvPython $TestScript "Comí 200g de pollo, gasté 120 en café y recuérdame pagar la luz a las 18:00"
