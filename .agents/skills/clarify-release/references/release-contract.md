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
`main` preparation merge commit. Publication requires a dedicated reviewed and
merged metadata-only PR with strict `.github/release-intent.json`. A maintainer
merge authorizes that release; a second-person approval is not required.

The [automation guide](../../../../docs/release-automation.md) owns activation,
preparation inputs, intent fields and dispatch recovery. Promotion is opt-in:
`CLARIFY_RELEASE_PROMOTION_ENABLED` must be exactly `true`. It is a separate
completed-CI workflow, not part of ordinary validation. Preparation needs a
separate CI-capable token and fails before writes when that token is absent.
No release intent or version is reserved by installing automation.

Desktop intent must link Windows manual acceptance for its exact base SHA.
Only release metadata can differ between that base and the release source.
The gate requires the canonical repository, main push CI, exact workflow path,
required successful jobs, freshness against main and the exact merged PR before
creating an immutable tag. Publication repeats these checks and keeps the same
source SHA in its executable, Ed25519 metadata and provenance.

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
- `.github/workflows/release-preparation.yml`
- `.github/workflows/release-promotion.yml`
- `scripts/release_delivery.py`
- `tests/test_release_delivery.py`
- `docs/release-automation.md`

## Required validation

Before the release-preparation PR:

- `git diff --check`
- `npm run check`
- `npm test`
- release preflight script
- Settings TypeScript/Vite, isolated Playwright, and locked Rust build checks
- Updated dependency notices and SBOM coverage for the Settings child

For Windows-facing changes:

- Windows build and applicable acceptance checks
- for local deployment, `scripts/deploy.ps1` with the observed installation path
  or `CLARIFY_INSTALL_PATH`; invoke directly from PowerShell when npm cannot use
  a WSL UNC working directory
- installed executable hash, process path, and responsiveness check
- an explicit publication request authorizes the release work; it does not
  establish that manual checks were performed
- record applicable Windows acceptance for the prepared base in the intent;
  missing required acceptance blocks publication, without a repeated approval
  request when valid evidence already exists

On the desktop preparation PR and after merge:

- `CI required`
- `Tests (ubuntu-latest)`
- `Tests (windows-latest)`
- `Package Windows executable`
  - includes the native Settings build and embedded-child hash check
  - includes frozen portable update replacement, startup receipt, rollback, and
    tamper rejection with generated fixture keys and isolated paths

- `Settings web and bridge` runs separately for the prepared source.
- MSI lifecycle and signed-manifest checks run when installer inputs change or
  during a full manual CI run. They are not a requirement for a Community
  portable release. Keep the signed-channel acceptance requirements below.

On publication:

- tag resolves to the exact green preparation merge; dispatch uses that tag and
  exact source SHA, never mutable main;
- `GITHUB_TOKEN`-created tags require explicit workflow dispatch because their
  pushes do not trigger another workflow;
- an existing mismatched tag fails; complete releases are left unchanged and
  partial releases require operator inspection without replacing assets;
- the signed `Release` workflow remains blocked and manual-only; the following
  signed requirements remain gates for a separately repaired signed path;
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

From v0.5.0 the community track also publishes exactly one of each:

- `Clarify-portable-update.json`
- `Clarify-portable-update.json.sig`

The ZIP contains the portable executable, checksum, SBOM, `LICENSE`, and
`THIRD_PARTY_NOTICES.md`, plus Settings, Qt, and crypto notices. The track does
not publish an MSI or Authenticode CAB manifest. Windows SmartScreen warnings
remain expected. Portable in-app updates use the separate pinned Ed25519
policy and protected `portable-updates` environment described in
`docs/windows-distribution.md`. Verify both signed metadata assets against
the packaged pin, executable hash/size, tag, and exact green source SHA.
Keep the Authenticode MSI rollout gates intact.

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
