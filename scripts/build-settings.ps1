[CmdletBinding()]
param([string]$OutputPath)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
if (-not $OutputPath) { $OutputPath = Join-Path $taskRepo 'dist\clarify-settings.exe' }
$taskStage = Join-Path $env:TEMP 'clarify-settings-build'
$taskTarget = Join-Path $env:TEMP 'clarify-tauri-target'
$taskVswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$taskVs = & $taskVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $taskVs) { throw 'Install Visual Studio C++ Build Tools and the Windows SDK first.' }
$taskNode = (Get-Command node.exe -ErrorAction Stop).Source
$taskNpm = Join-Path (Split-Path $taskNode) 'node_modules\npm\bin\npm-cli.js'
New-Item -ItemType Directory -Path $taskStage -Force | Out-Null
& robocopy (Join-Path $taskRepo 'desktop') $taskStage /E /XD node_modules target dist test-results /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw 'Could not stage settings sources.' }
Push-Location $taskStage
try {
    & $taskNode $taskNpm ci --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) { throw 'Settings dependencies failed.' }
    & $taskNode scripts/build.mjs
    if ($LASTEXITCODE -ne 0) { throw 'Settings frontend failed.' }
    & (Join-Path $taskVs 'Common7\Tools\Launch-VsDevShell.ps1') -Arch amd64 -HostArch amd64 -SkipAutomaticLocation
    & cargo build --locked --manifest-path src-tauri/Cargo.toml --release --features custom-protocol --target-dir $taskTarget
    if ($LASTEXITCODE -ne 0) { throw 'Settings native build failed.' }
    New-Item -ItemType Directory -Path (Split-Path $OutputPath) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $taskTarget 'release\clarify-settings.exe') -Destination $OutputPath -Force
    Write-Host "Settings executable: $OutputPath"
} finally { Pop-Location }
