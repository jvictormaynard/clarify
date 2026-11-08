[CmdletBinding()]
param(
    [string]$Python,
    [string]$OutputDirectory,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repoRoot 'dist\desktop-shell' }
$Python = (Resolve-Path -LiteralPath $Python).ProviderPath
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$desktop = Join-Path $repoRoot 'desktop'
$packaged = Join-Path $desktop 'electron-dist\Clarify Desktop-win32-x64'
$node = (Get-Command node -ErrorAction Stop).Source
$npmCli = Join-Path (Split-Path -Parent $node) 'node_modules\npm\bin\npm-cli.js'
if (-not (Test-Path -LiteralPath $npmCli)) { throw 'The installed Node npm CLI is required.' }
$logs = Join-Path $env:TEMP ('clarify-desktop-build-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $logs | Out-Null
function Invoke-DesktopNpm([string[]]$Arguments) {
    $stdout = Join-Path $logs 'npm.stdout.log'
    $stderr = Join-Path $logs 'npm.stderr.log'
    $process = Start-Process -FilePath $node -ArgumentList (@('"' + $npmCli + '"') + $Arguments) -WorkingDirectory $desktop -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if ($process.ExitCode -ne 0) {
        Get-Content -LiteralPath $stdout, $stderr -Tail 40
        throw 'Desktop npm command failed.'
    }
    Get-Content -LiteralPath $stdout -Tail 8
}

Push-Location $desktop
try {
    if (-not $SkipInstall) {
        Invoke-DesktopNpm -Arguments @('ci', '--no-fund')
    }
    Invoke-DesktopNpm -Arguments @('run', 'build:electron')
} finally { Pop-Location }

# Replace generated output only. Refuse to remove a root or any source directory.
$repoResolved = [IO.Path]::GetFullPath($repoRoot)
if ($OutputDirectory -eq $repoResolved -or $repoResolved.StartsWith($OutputDirectory.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $OutputDirectory.StartsWith($desktop.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Desktop output must be outside the source directories.'
}
if (Test-Path -LiteralPath $OutputDirectory) {
    if ((Get-Item -LiteralPath $OutputDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Desktop output cannot be a linked directory.' }
    $ancestor = [IO.DirectoryInfo]$OutputDirectory
    while ($null -ne $ancestor) {
        if ($ancestor.Exists -and ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Desktop output cannot pass through a linked directory.' }
        $ancestor = $ancestor.Parent
    }
    if (Get-ChildItem -LiteralPath $OutputDirectory -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Desktop output contains a linked entry.' }
    $marker = Join-Path $OutputDirectory 'resources\app\package.json'
    if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -Raw -LiteralPath $marker | ConvertFrom-Json).name -ne 'clarify-desktop') { throw 'Refusing to replace a directory that is not generated Clarify output.' }
    Remove-Item -LiteralPath $OutputDirectory -Recurse -Force
}
New-Item -ItemType Directory -Path (Split-Path -Parent $OutputDirectory) -Force | Out-Null
Copy-Item -LiteralPath $packaged -Destination $OutputDirectory -Recurse
& $Python (Join-Path $PSScriptRoot 'settings_inventory.py') --desktop $desktop --output-dir (Split-Path -Parent $OutputDirectory) --electron-shell $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Electron payload and license inventory failed.' }
Write-Host "Desktop shell: $OutputDirectory"
