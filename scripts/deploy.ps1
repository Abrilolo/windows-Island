#Requires -Version 5.1
<#
.SYNOPSIS
    Despliega plugins de plugins/<id>/ en Fenn (y en Nook si existe la carpeta heredada).

.DESCRIPTION
    Por cada plugin copia su carpeta + core/ a %APPDATA%\Fenn\plugins\<id> y reescribe la línea
    `run` del plugin.toml para usar el Python del .venv del repo (necesario por pydantic).

.EXAMPLE
    .\scripts\deploy.ps1                          # solo minimal-bridge (comportamiento anterior)
.EXAMPLE
    .\scripts\deploy.ps1 -Plugin ai-agents,minimal-bridge
.EXAMPLE
    .\scripts\deploy.ps1 -All
#>
param(
    [string[]]$Plugin = @("minimal-bridge"),
    [switch]$All
)

$ErrorActionPreference = "Stop"

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$PluginsRoot = Join-Path $RepoRoot "plugins"
$CoreDir     = Join-Path $RepoRoot "core"
$VenvPython  = (Join-Path $RepoRoot ".venv\Scripts\python.exe") -replace '\\', '/'
$Utf8NoBom   = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path $VenvPython)) {
    throw "No existe $VenvPython. Ejecuta primero .\scripts\setup_env.ps1 (o 'uv sync')."
}

if ($All) {
    $Plugin = Get-ChildItem -Path $PluginsRoot -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "plugin.toml") } |
        ForEach-Object { $_.Name }
}

# Un único destino: Fenn 0.4.0+ solo carga plugins de %APPDATA%\Fenn\plugins.
# (La carpeta heredada %APPDATA%\Nook ya no se usa; desplegar ahí creaba copias duplicadas.)
$FennRoot = Join-Path $env:APPDATA "Fenn"
New-Item -ItemType Directory -Force -Path (Join-Path $FennRoot "plugins") | Out-Null
$HostRoots = @($FennRoot)

$LegacyNookPlugins = Join-Path $env:APPDATA "Nook\plugins"
if (Test-Path $LegacyNookPlugins) {
    Write-Host "  !  Existe la carpeta heredada $LegacyNookPlugins (Fenn no la usa). Puedes borrarla." -ForegroundColor Yellow
}

function Copy-Tree([string]$Source, [string]$Destination) {
    # Copia recursiva sin __pycache__ ni .pyc
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -Path $Source -Force | Where-Object { $_.Name -ne "__pycache__" } | ForEach-Object {
        $Target = Join-Path $Destination $_.Name
        if ($_.PSIsContainer) {
            Copy-Tree $_.FullName $Target
        } elseif ($_.Extension -ne ".pyc") {
            Copy-Item -Path $_.FullName -Destination $Target -Force
        }
    }
}

foreach ($Id in $Plugin) {
    $SourceDir  = Join-Path $PluginsRoot $Id
    $SourceToml = Join-Path $SourceDir "plugin.toml"
    if (-not (Test-Path $SourceToml)) {
        throw "No existe $SourceToml"
    }

    Write-Host "=== Desplegando $Id ===" -ForegroundColor Cyan

    foreach ($RootDir in $HostRoots) {
        $TargetDir = Join-Path $RootDir "plugins\$Id"
        $DataDir   = Join-Path $RootDir "plugin-data\$Id"

        # Carpeta limpia: evita restos de layouts anteriores (p. ej. el antiguo src/)
        if (Test-Path $TargetDir) {
            try {
                Remove-Item -Path $TargetDir -Recurse -Force -ErrorAction Stop
            } catch {
                Write-Host "  !! $Id está en uso (Fenn lo está ejecutando). Cierra Fenn y vuelve a desplegar." -ForegroundColor Red
                exit 1
            }
        }
        New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

        Copy-Tree $SourceDir $TargetDir
        Copy-Tree $CoreDir (Join-Path $TargetDir "core")

        $MainPyPath = (Join-Path $TargetDir "main.py") -replace '\\', '/'
        $RawToml    = [System.IO.File]::ReadAllText($SourceToml, [System.Text.Encoding]::UTF8).TrimStart([char]0xFEFF)
        $RunLine    = "run = [`"$VenvPython`", `"$MainPyPath`"]"
        $Toml       = [regex]::Replace($RawToml, '(?m)^run\s*=.*$', $RunLine)

        [System.IO.File]::WriteAllText((Join-Path $TargetDir "plugin.toml"), $Toml, $Utf8NoBom)
        Write-Host "  -> Plugin desplegado en: $TargetDir" -ForegroundColor Green
    }
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
Write-Host "  -> Si Fenn ya está abierto, activa Plugin dev mode o recarga los plugins." -ForegroundColor Yellow
