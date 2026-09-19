# Clarify release contract

## Canonical state

- Repository: `jvictormaynard/clarify`
- Release branch base: `main`
- Versioning: Semantic Versioning with `v`-prefixed Git tags
- Maintained application: Python/Qt `clarify/desktop/qml_app.py`
- Settings: React/TypeScript `desktop/src/` in the Tauri child `desktop/src-tauri/`
- Historical Electron code is retained only in Git history
- Public platform: Windows 10/11, x64 portable executable

The tag, release, and executable must all originate from the same green
`main` commit.

## Required repository files

- `CHANGELOG.md`
- `README.md`
- `docs/README.pt-BR.md`
- `docs/architecture.md`
- `docs/development.md`
- `LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `package.json`
- `requirements.txt`
- `requirements-dev.txt`
- `requirements-lock-linux.txt`
- `requirements-lock-windows.txt`
- `requirements-lock-runtime-windows.txt`
- `scripts/check_runtime_lock.py`
- `scripts/format_staged.py`
- `scripts/install_bootstrap_tools.py`
- `scripts/add_sbom_component.py`
- `scripts/sox-runtime-manifest.json`
- `version.py`
- `scripts/build.ps1`
- `scripts/build-settings.ps1`
- `scripts/check_settings_payload.py`
- `scripts/qt_distribution.py`
- `scripts/qt_sources.json`
- `docs/qt-distribution.md`
- `scripts/settings_inventory.py`
- `desktop/licenses/manifest.json`
- `desktop/package-lock.json`
- `desktop/src-tauri/Cargo.lock`
- `.github/actions/settings-build/action.yml`
- `docs/release-readiness.md`
- `scripts/build-installer.ps1`
- `scripts/test-installer.ps1`
- `scripts/create_release_manifest.py`
- `scripts/verify-signature.ps1`
- `distribution/update-policy.json`
- `docs/windows-distribution.md`
- `.githooks/pre-commit`
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`

## Required validation

Before the release-preparation PR:

- `git diff --check`
- `npm run check`
- `npm test`
- release preflight script
- Settings TypeScript/Vite, isolated Playwright, and locked Rust build checks
- Updated dependency notices and SBOM coverage for the Settings child

For Windows-facing changes:

- `npm run deploy`
- installed process path and responsiveness check
- an explicit publication request is sufficient approval for visible behavior
  and relevant hotkeys; do not require a second manual confirmation
- disclose any manual interaction check that was not performed

On the PR and after merge:

- `Tests (ubuntu-latest)`
- `Tests (windows-latest)`
- `Package Windows executable`
  - includes per-user MSI install, upgrade, repair, rollback, uninstall, and
    signed-manifest contract smoke tests
  - also includes the shared Settings build action and embedded-child hash check

On the tag:

- successful `Release` workflow for signed releases, or successful
  `Community Release` workflow for the no-cost portable track
- Azure OIDC login and Artifact Signing actions pinned to reviewed full commit
  SHAs for signed releases; mutable tags are not an acceptable release trust
  boundary

## Required release assets

The GitHub release must contain exactly one of each:

1. `Clarify.exe`
2. `Clarify.exe.sha256`
3. `Clarify.sbom.json`
4. `Clarify-windows-x64.msi`
5. `Clarify-windows-x64.msi.sha256`
6. `Clarify-release-manifest.cab`
7. `Clarify-release-manifest.cab.sha256`
8. `Clarify-windows-x64.zip`
9. `sox-14.4.2-source.tar.gz`

The ZIP must contain:

- `Clarify.exe`
- `Clarify.sbom.json`
- `LICENSE`
- `THIRD_PARTY_NOTICES.md`

The ZIP also includes `Clarify-settings-NOTICES.txt` and `Clarify-qt-NOTICES.txt`.
Both release tracks also publish and attest `Clarify-qt-sources.zip`, containing
the pinned upstream Qt/PySide archives and source/replacement instructions.
The merged
`Clarify.sbom.json` covers Python, SoX, and the Settings dependency graph.
The portable executable embeds the Settings SBOM and notices; packaging must
verify their bytes and the Settings executable hash before publication.

The SoX source archive must match:

`b45f598643ffbd8e363ff24d61166ccec4836fea6d3888881b8df53e3bb55f6c`

## Community portable release track

The community track is intentionally unsigned and exists for releases without
sponsored signing infrastructure. It must publish exactly these assets:

- `Clarify.exe`
- `Clarify.exe.sha256`
- `Clarify.sbom.json`
- `Clarify-qt-sources.zip`
- `Clarify-windows-x64.zip`
- `sox-14.4.2-source.tar.gz`

The ZIP contains the portable executable, checksum, SBOM, `LICENSE`, and
`THIRD_PARTY_NOTICES.md`, plus `Clarify-settings-NOTICES.txt`. The track does not publish an MSI or authenticated
update manifest. Windows SmartScreen warnings remain expected, and the in-app
update path stays disabled until a signed release satisfies the rollout gates.

## Documentation ownership

- `CHANGELOG.md`: released user-visible behavior and comparison links
- `README.md`: primary English install/download path
- `docs/README.pt-BR.md`: equivalent Portuguese onboarding
- `docs/development.md`: maintainer setup, validation, tagging, and release flow
- `docs/architecture.md`: packaging and runtime boundaries
- `THIRD_PARTY_NOTICES.md`: bundled third-party components and notices

Only update a document when its owned contract changed. Keep English and
Portuguese installation instructions behaviorally equivalent.

## Security and provenance

- Never bundle `.env`, API keys, `%APPDATA%` config, or local credentials.
- Keep provider credentials in the DPAPI secret store; never in plain config.json.
- Preserve contributor attribution and existing Git history.
- Never force-update or reuse a published tag.
- Never overwrite a published asset to conceal provenance drift; publish a new
  patch version instead.
- Require valid, timestamped Authenticode signatures from the publisher pinned
  in `distribution/update-policy.json` for the signed EXE, MSI, and manifest
  CAB track.
- Require GitHub build-provenance attestations for EXE, MSI, CAB, and ZIP.
- Keep the unsigned community-track SmartScreen limitation explicit.
- Follow `docs/windows-distribution.md` for signing ownership, cost, rotation,
  revocation, rollout prerequisites, and manual acceptance.
