#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$VenvPython = (Join-Path $RepoRoot ".venv\Scripts\python.exe") -replace '\\', '/'
$Utf8NoBom  = New-Object System.Text.UTF8Encoding($false)

# Nook 0.4.0+ usa %APPDATA%\Fenn; mantener soporte para %APPDATA%\Nook si existe
$HostRoots = @()
$FennRoot = Join-Path $env:APPDATA "Fenn"
$NookRoot = Join-Path $env:APPDATA "Nook"
if (Test-Path $FennRoot) {
    $HostRoots += $FennRoot
}
if ((Test-Path $NookRoot) -or ($HostRoots.Count -eq 0)) {
    $HostRoots += $NookRoot
}

Write-Host "=== Desplegando minimal-bridge en Nook / Fenn ===" -ForegroundColor Cyan

foreach ($RootDir in $HostRoots) {
    $TargetDir = Join-Path $RootDir "plugins\minimal-bridge"
    $DataDir   = Join-Path $RootDir "plugin-data\minimal-bridge"

    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    New-Item -ItemType Directory -Force -Path $DataDir   | Out-Null

    # Copiar código fuente y entrypoint
    Copy-Item -Path (Join-Path $RepoRoot "main.py") -Destination (Join-Path $TargetDir "main.py") -Force
    if (Test-Path (Join-Path $TargetDir "src")) {
        Remove-Item -Path (Join-Path $TargetDir "src") -Recurse -Force
    }
    Copy-Item -Path (Join-Path $RepoRoot "src") -Destination (Join-Path $TargetDir "src") -Recurse -Force

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

    [System.IO.File]::WriteAllText((Join-Path $TargetDir "plugin.toml"), $PluginToml, $Utf8NoBom)
    Write-Host "  -> Plugin desplegado en: $TargetDir" -ForegroundColor Green
}

# Reparar rutas heredadas de %APPDATA%\Nook\plugins -> %APPDATA%\Fenn\plugins tras actualización a Fenn 0.4.0+
if (Test-Path (Join-Path $FennRoot "plugins")) {
    Get-ChildItem -Path (Join-Path $FennRoot "plugins") -Filter "plugin.toml" -Recurse | ForEach-Object {
        $RawToml = [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8).TrimStart([char]0xFEFF)
        $FixedToml = $RawToml -replace 'AppData/Roaming/Nook/plugins/', 'AppData/Roaming/Fenn/plugins/'
        if ($FixedToml -ne $RawToml) {
            [System.IO.File]::WriteAllText($_.FullName, $FixedToml, $Utf8NoBom)
            Write-Host "  -> Ruta reparada en:     $($_.FullName)" -ForegroundColor Cyan
        }
    }
}

Write-Host "  -> Python configurado:   $VenvPython" -ForegroundColor Green
Write-Host "  -> Si Nook/Fenn ya está abierto, recarga plugins desde el ícono de bandeja o reinicia la app." -ForegroundColor Yellow
