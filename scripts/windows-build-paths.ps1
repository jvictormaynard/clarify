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
