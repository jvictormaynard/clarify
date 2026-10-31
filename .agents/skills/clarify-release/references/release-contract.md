# Clarify release contract

## Canonical state

- Repository: `jvictormaynard/clarify`
- Reviewed stable source: exact metadata-only preparation merge on `main`
- Version: Semantic Versioning, immutable annotated `vX.Y.Z` tags
- Maintained desktop: Python/Qt `clarify/desktop/qml_app.py`
- Settings: React/TypeScript in the Tauri child under `desktop/`
- Public desktop platform: Windows 10/11 x64 portable executable

Read [release automation](../../../../docs/release-automation.md) for exact inputs,
intent, evidence, activation and recovery. This contract defines release gates;
it does not grant authorization. Schema-2 preparation authorizes source and
version. Public desktop publication requires acceptance of the packaged candidate.
There is no second unrelated pre-build Windows acceptance requirement.

## Required source and validation

Retain version/changelog alignment, LICENSE and THIRD_PARTY_NOTICES.md, pinned
Python/npm/Cargo locks, runtime lock checks, Settings license/source inventory,
Qt distribution sources and replacement instructions, portable crypto inventory,
SoX pinned source and manifest, embedded Settings hash verification and portable
update policy/key pin. Never package .env, local config, keys, profiles or audio.

Release owners are:

- `.github/workflows/release-preparation.yml`: reviewed metadata preparation
- `.github/workflows/release-promotion.yml`: disabled-by-default candidate dispatch
- `.github/workflows/release.yml`: explicit build/publish actions and permissions
- `scripts/release_delivery.py`: preparation, immutable tags, exact source/CI
- `scripts/release_candidate.py`: sealed bytes, producer/artifact verification,
  native acceptance and once-only publication
- `tests/policy/test_release_delivery.py`, `test_release_candidate.py`,
  `test_release_channels.py`, `test_release_preflight.py`: isolated policy evidence

Use `python scripts/run_tests.py --suite policy` and applicable validation from
`docs/ci-delivery.md`. Canonical release verification authenticates repository,
workflow name `CI`, path `.github/workflows/ci.yml`, successful completed main
push on the exact source and one successful terminal `CI required`. Component
job names and their graph belong to ordinary CI, not release consumers.

A stable source needs one dedicated merged preparation PR, expected branch/title,
a maintainer merge, metadata-only comparison from the prepared base, aligned
versions and current exact green main at promotion/build. Tag changes are atomic;
never move or reuse an existing mismatched tag. Later main commits cannot change
the bytes of a selected candidate.

## Build candidate

Desktop Release is manual-only. `action=build-candidate` and `channel=preview`
are the defaults. Build never publishes. No push or schedule triggers publication.
Stable dispatch requires its reviewed immutable tag and exact source SHA.
Preview dispatch requires an exact branch SHA and uses
`preview/<run-id>-<attempt>-<short-sha>` outside the stable namespace.

Package once with the final version and channel. Keep audits, native Settings
build and embedded child hash checks, frozen portable startup/replacement/recovery
smoke checks, runtime/Settings/SoX SBOM, licenses, pinned Qt/SoX sources and checksums.
Stable Ed25519 update metadata is signed within protected `portable-updates` using
the existing pinned key. Missing or wrong key fails, without fallback. Preview
uses `desktop-preview`, disables the feed before packaging, and has no update
metadata. There is no new signed installer or paid service.

One immutable `desktop-candidate-<run>-<attempt>` artifact contains exactly the
allowed assets plus `Clarify-candidate.json`. The manifest binds source SHA/ref,
repository, workflow, job, run, attempt, channel, version/tag and each allowed
asset's SHA-256 and size. Provenance covers every asset and the manifest. Record
the artifact ID and archive SHA-256 digest. No overwrite is permitted.

## Stable portable assets

The stable portable release contains exactly:

- `Clarify.exe`
- `Clarify.exe.sha256`
- `Clarify.sbom.json`
- `Clarify-qt-sources.zip`
- `Clarify-windows-x64.zip`
- `sox-14.4.2-source.tar.gz`
- `Clarify-portable-update.json`
- `Clarify-portable-update.json.sig`

The ZIP contains exactly Clarify.exe, its checksum, the merged SBOM, LICENSE,
THIRD_PARTY_NOTICES.md, Clarify-settings-NOTICES.txt, Clarify-qt-NOTICES.txt and
Clarify-crypto-NOTICES.txt. Qt sources include pinned upstream archives and
replacement/source instructions. SoX source SHA-256 is
`b45f598643ffbd8e363ff24d61166ccec4836fea6d3888881b8df53e3bb55f6c`.

The EXE is unsigned; Windows SmartScreen warnings remain possible. Update
metadata uses the separate Ed25519 pin and exact version, tag, channel, source,
EXE hash/size and canonical URL. This path publishes no MSI or signed CAB.
Keep MSI lifecycle, Authenticode/runtime compatibility and future rollout gates
in `docs/windows-distribution.md`; activation needs separate authorization.

## Preview assets

Preview has the same six portable/source assets, plus `Clarify-preview.json`,
with neither update metadata file. The identity receipt records source, run,
attempt, version/tag and disabled updater. Source X.Y.Z is retained for runtime
compatibility; the final channel/tag is nonstable before packaging. The runtime
rejects its preview policy before creating an update transport. A published
preview is always a prerelease and explicitly nonlatest. It never changes the
stable update feed. A preview does not accept changed stable candidate bytes.

## Native acceptance and publication

Windows acceptance covers the actual packaged stable artifact. First verify its
artifact digest and executable checksum. Record the affected native checks and
limits in a fresh canonical maintainer issue/comment, with the exact source and
candidate digest. The automation guide defines the strict acceptance JSON.
Publication reads the canonical report, verifies author permission, exact evidence
and freshness within 24 hours. A CI result or report link alone is insufficient.

`action=publish-candidate` is a separate explicit dispatch from trusted main,
protected by `desktop-publication`. It is disabled unless
`CLARIFY_RELEASE_PUBLICATION_ENABLED` is exactly `true`. It takes exact
source/version/channel, completed producer run/current attempt and artifact ID/digest. Only this job has
release-write permission. It has no signing credential, dependency installation,
build, packaging or signing step. It must not execute downloaded candidate code.

Authenticate the canonical successful producer, workflow/job/required step
identity, latest run attempt and immutable artifact metadata. Reject expired,
replaced or ambiguous artifacts. Verify archive digest before extraction; reject
absolute/escaping/duplicate paths, links, directories and extra inputs. Verify
strict manifest fields, final identity, exact asset set/hashes/sizes, ZIP contents,
source checksum, provenance source/signer and stable metadata signature/pin.
Recheck producer, bytes, source/CI, immutable tag and release state before effects.

Upload the verified bytes once into a draft. Verify exact remote uploaded states,
hashes and sizes before making public. Stable explicitly becomes latest. Preview
explicitly sets prerelease and nonlatest. Download and hash published assets.
A complete matching release is verified without another upload. A partial,
uncertain, replaced or draft release stops for operator inspection. Never
clobber, automatically retry uncertain uploads, move tags, repackage or re-sign.

## iOS boundary

Unsigned branch/simulator validation is `mode=validate`. Direct Xcode remains
the production signer for the containing app, keyboard and activity extensions.
No EAS provisioning or OTA contract is introduced. Mobile preparation retains
fresh Apple build/pending inventory and monotonic reservation, reviewed metadata,
immutable source tag and exact canonical CI.

TestFlight verifies and uploads the exact signed IPA, then checks Apple processing
and internal-group availability. Its digest-bound candidate evidence contains
signed bundle/hash verification, confirmed source/run/attempt-bound upload receipt,
exact Apple build UUID/availability and a file-hash manifest. Remove temporary
Apple credentials on every outcome. An uncertain upload blocks another upload;
processing recovery never rebuilds it.

The App Store workflow authenticates that completed producer/current attempt and
explicit artifact ID/digest, then reuses the same Apple build UUID. It creates a
manual readiness handoff only, with no Apple API mutation. It rejects historical
PR179 QA receipts and unsigned evidence. Physical-device/store-policy acceptance
and current submission inventory remain separate. Submission, approved-version
release and regional public availability require their own verified manual Apple
steps. A handoff artifact does not claim any of them.

## Documentation and completion

CHANGELOG.md owns released behavior and comparison links. READMEs own equivalent
English/Portuguese install paths. Development/architecture docs own maintainer and
packaging boundaries. THIRD_PARTY_NOTICES.md owns bundled notices. Change each
only when its contract changes.

Report source/tag, candidate run/attempt/artifact ID/digest, applicable checks,
manual acceptance, publication state and downloaded-asset verification. Keep local
policy evidence separate from Windows packaging/acceptance, GitHub provenance and
protected environments, Apple signing/processing and public availability. Stop
publication if any required gate is missing or fails. Preserve existing source,
profiles, artifacts, tags and published bytes.
