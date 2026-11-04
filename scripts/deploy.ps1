#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$TargetDir = Join-Path $env:APPDATA "Nook\plugins\minimal-bridge"
$DataDir   = Join-Path $env:APPDATA "Nook\plugin-data\minimal-bridge"

Write-Host "=== Desplegando minimal-bridge en Nook ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir   | Out-Null

# Copiar código fuente y entrypoint
Copy-Item -Path (Join-Path $RepoRoot "main.py") -Destination (Join-Path $TargetDir "main.py") -Force
if (Test-Path (Join-Path $TargetDir "src")) {
    Remove-Item -Path (Join-Path $TargetDir "src") -Recurse -Force
}
Copy-Item -Path (Join-Path $RepoRoot "src") -Destination (Join-Path $TargetDir "src") -Recurse -Force

# Apuntar al Python del .venv del proyecto para tener pydantic disponible sin contaminar el sistema
$VenvPython = (Join-Path $RepoRoot ".venv\Scripts\python.exe") -replace '\\', '/'
$MainPyPath = (Join-Path $TargetDir "main.py") -replace '\\', '/'

$PluginToml = @"
id = "minimal-bridge"
name = "Minimal Bridge"
icon = "paper-plane-tilt"
size = "wide"
mode = "live"
hotkey = "Ctrl+Alt+Space"
run = ["$VenvPython", "$MainPyPath"]
"@

Set-Content -Path (Join-Path $TargetDir "plugin.toml") -Value $PluginToml -Encoding UTF8

Write-Host "  -> Plugin desplegado en: $TargetDir" -ForegroundColor Green
Write-Host "  -> Python configurado:   $VenvPython" -ForegroundColor Green
Write-Host "  -> Si Nook ya está abierto, recarga plugins desde el ícono de bandeja o reinicia Nook." -ForegroundColor Yellow
