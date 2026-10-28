function Get-ClarifyWindowsBuildPaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryPath,
        [string]$TemporaryRoot = $env:TEMP
    )

    $canonicalRepo = [System.IO.Path]::GetFullPath(
        (Resolve-Path -LiteralPath $RepositoryPath -ErrorAction Stop).ProviderPath
    ).TrimEnd([char[]]@('\', '/'))
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $canonicalRepo = $canonicalRepo.ToLowerInvariant()
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $repoHash = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($canonicalRepo))
        $worktreeKey = [BitConverter]::ToString($repoHash).Replace('-', '').Substring(0, 16).ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }

    # Keep caches stable for this worktree, including when its branch changes.
    return [pscustomobject]@{
        SettingsStageRoot = Join-Path $TemporaryRoot "clarify-settings-workspace-$worktreeKey"
        SettingsTarget = Join-Path $TemporaryRoot "clarify-tauri-target-$worktreeKey"
        DeployRoot = Join-Path $TemporaryRoot "clarify-build-$worktreeKey"
    }
}

function Assert-ClarifySettingsStagePath {
    param(
        [Parameter(Mandatory = $true)][string]$StageRoot,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $root = [System.IO.Path]::GetFullPath($StageRoot).TrimEnd('\', '/')
    $destination = [System.IO.Path]::GetFullPath($Path)
    if (-not $destination.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Settings synchronization must stay inside its staging root.'
    }
    $preserveCaches = $destination -eq (Join-Path $root 'desktop')
    # Reject links before robocopy can purge or timestamp a different tree.
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($destination)
    $pending.Push($root)
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        if (-not (Test-Path -LiteralPath $current)) { continue }
        $item = Get-Item -LiteralPath $current -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Settings staging cannot use a reparse point: $current"
        }
        if ($current -eq $root -or -not $item.PSIsContainer) { continue }
        foreach ($child in Get-ChildItem -LiteralPath $current -Force) {
            if ($preserveCaches -and $child.PSIsContainer -and $child.Name -in @('node_modules', 'target', 'dist', 'test-results')) { continue }
            if ($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "Settings staging cannot use a reparse point: $($child.FullName)"
            }
            if ($child.PSIsContainer) { $pending.Push($child.FullName) }
        }
    }
}
