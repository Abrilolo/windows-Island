#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host "=== [1/4] Creando directorios de Nook en %APPDATA% ===" -ForegroundColor Cyan
$NookAppData = Join-Path $env:APPDATA "Nook"
$PluginDir   = Join-Path $NookAppData "plugins\minimal-bridge"
$DataDir     = Join-Path $NookAppData "plugin-data\minimal-bridge"

New-Item -ItemType Directory -Force -Path $PluginDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir   | Out-Null
Write-Host "  -> Plugins: $PluginDir" -ForegroundColor Green
Write-Host "  -> Data:    $DataDir" -ForegroundColor Green

Write-Host "`n=== [2/4] Verificando / Instalando Nook (v0.3.0) ===" -ForegroundColor Cyan
$NookExeCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Nook\Nook.exe"),
    (Join-Path $env:LOCALAPPDATA "Nook\Nook.exe"),
    (Join-Path $env:ProgramFiles "Nook\Nook.exe")
)
$NookInstalled = $NookExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($NookInstalled) {
    Write-Host "  -> Nook ya está instalado en: $NookInstalled" -ForegroundColor Green
} else {
    $InstallerUrl  = "https://github.com/Geguchh024/nook/releases/download/v0.3.0/Nook-Setup-0.3.0.exe"
    $InstallerPath = Join-Path $env:TEMP "Nook-Setup-0.3.0.exe"
    Write-Host "  -> Descargando $InstallerUrl ..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $InstallerUrl -OutFile $InstallerPath
    Write-Host "  -> Ejecutando instalador de Nook..." -ForegroundColor Yellow
    Start-Process -FilePath $InstallerPath -Wait
}

Write-Host "`n=== [3/4] Verificando / Instalando Ollama ===" -ForegroundColor Cyan
$OllamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $OllamaExe)) {
    $OllamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($OllamaCmd) {
        $OllamaExe = $OllamaCmd.Source
    }
}

if (Test-Path $OllamaExe) {
    Write-Host "  -> Ollama encontrado en: $OllamaExe" -ForegroundColor Green
} else {
    Write-Host "  -> Instalando/reparando Ollama con winget..." -ForegroundColor Yellow
    winget install --id Ollama.Ollama --force --accept-package-agreements --accept-source-agreements
    $OllamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
}

Write-Host "`n=== [4/4] Descargando modelo ligero para Structured Outputs (qwen2.5:3b) ===" -ForegroundColor Cyan
if (Test-Path $OllamaExe) {
    & $OllamaExe pull qwen2.5:3b
    Write-Host "  -> Modelo qwen2.5:3b listo." -ForegroundColor Green
} else {
    Write-Host "  -> Aviso: Reinicia la terminal tras instalar Ollama y ejecuta: ollama pull qwen2.5:3b" -ForegroundColor Yellow
}

Write-Host "`n=== Entorno listo para nook-bridge ===" -ForegroundColor Cyan
