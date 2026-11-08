[CmdletBinding()]
param([string]$OutputPath, [string]$PythonExecutable = 'python', [switch]$StageOnly)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'windows-build-paths.ps1')
$taskBuildPaths = Get-ClarifyWindowsBuildPaths -RepositoryPath $taskRepo
if (-not $OutputPath) { $OutputPath = Join-Path $taskRepo 'dist\clarify-settings.exe' }
$OutputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
$taskStageRoot = [System.IO.Path]::GetFullPath($taskBuildPaths.SettingsStageRoot)
$taskStage = Join-Path $taskStageRoot 'desktop'
$taskSharedStage = Join-Path $taskStageRoot 'shared'
$taskTarget = $taskBuildPaths.SettingsTarget
Assert-ClarifySettingsStagePath -StageRoot $taskStageRoot -Path $taskStage
Assert-ClarifySettingsStagePath -StageRoot $taskStageRoot -Path $taskSharedStage
$taskSharedFiles = @('i18n.ts', 'ui_strings.json', 'usage.ts')
foreach ($taskFile in $taskSharedFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $taskRepo "shared\$taskFile") -PathType Leaf)) {
        throw "Missing required Settings input: shared\$taskFile"
    }
}
New-Item -ItemType Directory -Path $taskStage -Force | Out-Null
& robocopy (Join-Path $taskRepo 'desktop') $taskStage /MIR /XJ /XD node_modules target dist test-results /XF node_modules /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw 'Could not stage settings sources.' }
New-Item -ItemType Directory -Path $taskSharedStage -Force | Out-Null
foreach ($taskEntry in Get-ChildItem -LiteralPath $taskSharedStage -Force) {
    if ($taskEntry.Name -notin $taskSharedFiles) {
        # The destination tree was checked before any recursive deletion.
        Remove-Item -LiteralPath $taskEntry.FullName -Recurse -Force
    }
}
& robocopy (Join-Path $taskRepo 'shared') $taskSharedStage @taskSharedFiles /XJ /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw 'Could not stage shared Settings inputs.' }
# Refresh access times for temporary-file cleanup without invalidating build inputs.
$taskStagedAt = [DateTime]::UtcNow
$taskDirectories = New-Object 'System.Collections.Generic.Stack[string]'
$taskDirectories.Push($taskStage)
$taskDirectories.Push($taskSharedStage)
while ($taskDirectories.Count -gt 0) {
    $taskDirectory = $taskDirectories.Pop()
    (Get-Item -LiteralPath $taskDirectory).LastAccessTimeUtc = $taskStagedAt
    foreach ($taskEntry in Get-ChildItem -LiteralPath $taskDirectory -Force) {
        if ($taskEntry.PSIsContainer -and $taskEntry.Name -in @('node_modules', 'target', 'dist', 'test-results')) { continue }
        if ($taskEntry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { continue }
        $taskEntry.LastAccessTimeUtc = $taskStagedAt
        if ($taskEntry.PSIsContainer) { $taskDirectories.Push($taskEntry.FullName) }
    }
}
if ($StageOnly) { return }
$taskVswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$taskVs = & $taskVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $taskVs) { throw 'Install Visual Studio C++ Build Tools and the Windows SDK first.' }
$taskNode = (Get-Command node.exe -ErrorAction Stop).Source
$taskNpm = Join-Path (Split-Path $taskNode) 'node_modules\npm\bin\npm-cli.js'
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
    & $PythonExecutable (Join-Path $taskRepo 'scripts\settings_inventory.py') --desktop $taskStage --output-dir (Split-Path $OutputPath)
    if ($LASTEXITCODE -ne 0) { throw 'Settings dependency inventory failed.' }
    Write-Host "Settings executable: $OutputPath"
} finally { Pop-Location }
