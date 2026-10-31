# Client release automation

Ordinary CI validates source. It does not publish a desktop release or upload an
iOS app. Release preparation authorizes a selected source and version. A desktop
candidate is built once, accepted on Windows, then published by a separate action.
TestFlight is the production-identity iOS candidate. App Store work reuses its
exact Apple build ID through a verified manual handoff.

## Activation

`CLARIFY_RELEASE_PROMOTION_ENABLED` must be exactly `true` to enable promotion.
Unset and false values leave it inactive. Installing this architecture does not
activate promotion, reserve a version, configure an environment, or publish.

Preparation requires `CLARIFY_RELEASE_PREPARATION_TOKEN`, restricted to this
repository with Contents and Pull requests write access. It must create PR events
that start normal CI. There is no fallback to `GITHUB_TOKEN`. Keep credentials out
of inputs, reports and artifacts. Promotion uses its scoped `GITHUB_TOKEN` to
create immutable tags and dispatch a candidate build. Restrict release tag changes
and deletion to the release maintainer.

Desktop candidate signing uses the protected `portable-updates` environment and
its existing `CLARIFY_UPDATE_SIGNING_KEY`. Permit only reviewed stable tags there.
The key must match the packaged Ed25519 pin. Preview builds use `desktop-preview`
and have no update key. The build has Contents read permission, plus the existing
OIDC/attestation permissions. It cannot create releases or tags.

Publication uses a separate protected `desktop-publication` environment and runs
from `main`. Its separate `CLARIFY_RELEASE_PUBLICATION_ENABLED` variable must be
exactly `true`; unset/false blocks the job and command. Configure protection and
restrict trusted source branches before activation. Only that job has Contents write permission. It has no signing key,
OIDC permission, dependency installation, Settings build, packaging or signing
step. It needs the runner's existing `gh` and OpenSSL verification tools. It
checks out trusted publisher code, then treats candidate downloads only as data.
No credentials or signing fallback is available.

The direct Xcode TestFlight path keeps the working app, keyboard and activity
signing contracts. Signed delivery uses the `ios-testflight` environment;
unsigned branch validation uses `ios-validation`. Apple secrets stay out of the
App Store handoff. EAS provisioning and OTA updates are not part of this contract.

Before pushing an older `codex/ios-testflight` branch, bring its workflow forward
through an authorized Git change. GitHub evaluates workflows from the pushed ref;
old branch workflows can still have their old upload trigger.

## Desktop preview

Dispatch **Desktop Release** on a branch with `action=build-candidate`,
`channel=preview` and that dispatch's exact `source_sha`. These are the default
action and channel. This action builds an artifact and publishes nothing.

The final candidate identity is `preview/<run-id>-<attempt>-<short-sha>`. It keeps
the source's packaged X.Y.Z version for runtime/Windows compatibility. Before
packaging, a disposable policy sets channel `preview`. The runtime accepts only
`stable`, so no updater transport can start. `Clarify-preview.json` records the
source, run, attempt, tag, version and disabled updater. No portable update
manifest or signature can enter a preview candidate.

A separate `action=publish-candidate` dispatch from `main` can publish that exact
preview artifact. It creates the unique preview tag, marks the release as a
prerelease, and sets `make_latest=false`. It never changes the stable feed or
latest release. Preview/native testing does not accept a different stable build.

## Prepare a desktop release

1. Merge the intended source changes and complete main CI.
2. Run **Release Preparation** on `main`. Select `desktop`, a future X.Y.Z
   `version`, empty `build`, and release scope/limits in `notes`. Supply source
   review evidence: `{"report_url":"https://github.com/jvictormaynard/clarify/issues/123"}`.
   Do not claim Windows acceptance before the final candidate exists.
3. Review the draft `release-preparation/vX.Y.Z` PR. Its only allowed changes are
   `version.py`, root `package.json`, `CHANGELOG.md` and `.github/release-intent.json`.
   Review the dated changelog section and comparison links. A maintainer can
   review and merge their own PR. No second-person approval is required.
4. Require successful canonical `CI` and its terminal `CI required` on the exact
   merge. Main must still identify that commit when candidate creation starts.
5. Create the immutable annotated `vX.Y.Z` tag on that source, or let enabled
   promotion do so. Never move or reuse a tag. Dispatch **Desktop Release** on
   that tag with `action=build-candidate`, `channel=stable`, exact `source_sha`.

Only reviewed release metadata may differ from the prepared `base_sha`. Other
source changes require new preparation. Schema 2 removes the old pre-build
`tested_sha` and `windows_accepted` intent fields. The intent authorizes candidate
creation. Public publication requires acceptance of the actual packaged artifact.

### Public desktop release notes

The publisher reads only the version's dated `CHANGELOG.md` section from the
exact authenticated source. Changes come first, followed by the tagged changelog
link and portable distribution notices. Missing, duplicate, undated or empty
sections fail. Intent `notes` records review scope; it does not replace that
public section. A read-only inspection remains available:

```sh
python scripts/release_delivery.py notes --tag vX.Y.Z --output release-notes.md
```

## Build, accept and publish a desktop candidate

The build packages once with the final channel/version identity. It retains
locked dependencies, current audits, Settings payload verification, frozen
portable replacement/recovery smoke checks, licenses, merged runtime SBOM,
pinned Qt/SoX sources, checksums, signed stable update metadata and provenance.
No new signed installer or paid service is introduced.

`Clarify-candidate.json` records schema, repository, workflow, build job, exact
source SHA/ref, run ID, attempt, channel, version, final tag and every allowed
asset's SHA-256 and size. One artifact named `desktop-candidate-<run>-<attempt>`
contains this manifest and exactly those assets. Its immutable artifact ID and
`sha256:<hex>` digest appear in the run summary. Provenance covers the manifest
and every asset. Build outputs and candidate artifacts are never overwritten.

Perform applicable Windows manual acceptance on the downloaded stable candidate
after packaging. Verify its artifact digest and executable checksum first.
Cover the native contracts affected by this release, including focus/hotkeys,
Settings, startup and portable update behavior where applicable. Record results
and limits in a fresh canonical issue or issue comment authored by a maintainer.
Include exactly one fenced `clarify-candidate-acceptance` block:

```clarify-candidate-acceptance
{
  "schema": 1,
  "source_sha": "<exact candidate source SHA>",
  "candidate_digest": "sha256:<artifact SHA-256>",
  "windows_accepted": true,
  "checked_at": "<UTC YYYY-MM-DDTHH:MM:SSZ>",
  "report_url": "https://github.com/jvictormaynard/clarify/issues/123#issuecomment-456"
}
```

Both the check and the canonical report update must be within 24 hours at
publication. Publication fetches that report, verifies its author permission and
exact block, and rejects foreign, stale or unrelated acceptance. A link or a
passing CI alone does not establish manual acceptance.

Dispatch **Desktop Release** from `main` with `action=publish-candidate`, the
same `channel`, exact `source_sha` and `version`, and explicit `candidate_run_id`,
`candidate_attempt`, `artifact_id`, `artifact_digest`. Stable publication also
requires the exact acceptance JSON above. Preview does not require this stable
acceptance and cannot acquire update metadata.

Before any publication effect, the publisher authenticates the canonical
completed successful producer, workflow path/name, source ref/SHA, current run
attempt, successful build/smoke/seal/provenance/upload steps and immutable artifact
identity/digest. It verifies archive paths and regular files, exact manifest
inventory, hashes and sizes, portable ZIP contents, pinned SoX source, checksums,
provenance source/signer and stable Ed25519 metadata against the trusted pin.
It repeats producer/byte/tag/state checks after verification. Stable also repeats
reviewed-source and exact canonical CI checks and rejects a superseded version.

Publication uploads the existing bytes once into a draft. Only after every
allowed remote asset has its expected uploaded state, hash and size does it make
the release public. Stable explicitly becomes latest; preview explicitly does
not. The publisher downloads and hashes the resulting assets. A complete exact
existing release is verified and left in place. A partial, draft, replaced or
uncertain release stops for inspection; there is no overwrite, automatic upload
retry, re-sign or rebuild recovery. A missing preview release with an existing
preview tag also stops. Never use `--clobber` or move the tag to conceal a gap.

## Intent and canonical CI

`scripts/release_delivery.py` owns reviewed preparation and source authorization.
The exact intent fields are `schema` (integer `2`), `component`, `version`,
`base_sha`, `notes` and `evidence`. Duplicate and unknown fields fail. Desktop
evidence contains only `report_url`. Mobile evidence contains exactly the fields
below. Schema 1 is retired; do not retain both authorization systems.

Release checks authenticate canonical `jvictormaynard/clarify`, workflow name
`CI`, path `.github/workflows/ci.yml`, completed successful main `push`, exact
source SHA, and one completed successful `CI required`. Component job names and
their graph belong to ordinary CI. Release consumers do not duplicate that
inventory. Reviewed preparation additionally requires one exact merged PR,
canonical branch/title, maintainer merge and metadata-only source comparison.
Main freshness is required at promotion/build; a later main push cannot change
an already selected candidate's immutable source.

Enabled **Release Promotion** handles only a dedicated preparation merge. It
creates the immutable tag and dispatches `action=build-candidate, channel=stable`
for desktop, or `mode=testflight` for mobile. It never dispatches desktop
publication. Ordinary merges with an old intent are inert. Existing runs prevent
a second automatic dispatch. Desktop releases share a serialized queue. An
overflow cancellation is an open gate and needs inspection before a manual run.

## Prepare a TestFlight build

Inspect Apple's existing builds, processing uploads, pending submissions and
other reservations before selecting an unused build number. Choose a number
greater than both the highest reservation and checked-in build. `mode=status`
helps inspect recent Apple state; it is not a complete reservation inventory.
Preparation neither queries Apple nor reserves a build there.

Run **Release Preparation** on `main`, select `mobile`, stable `version`, decimal
`build`, scope in `notes`, and this exact evidence:

```json
{
  "build": "<selected unused build>",
  "highest_build": "<highest existing or reserved build>",
  "pending_builds_checked": true,
  "checked_at": "<UTC YYYY-MM-DDTHH:MM:SSZ>",
  "report_url": "https://github.com/jvictormaynard/clarify/issues/123#issuecomment-456"
}
```

The inventory check must be within 24 hours at preparation. Recheck reservation
conflicts before merge. The metadata-only PR changes `mobile/app.json` and the
schema-2 intent. Its reviewed merge and exact green main CI permit an immutable
`ios/vX.Y.Z-buildN` tag. App, keyboard and activity versions/builds derive from
that identity. Signed TestFlight dispatch uses the tag, exact SHA and
`mode=testflight`. Branch `mode=validate` is unsigned simulator validation and
cannot install signing credentials, archive a production IPA or upload it.
Direct Xcode remains the signing owner. Validation is the default.

The TestFlight run verifies the signed IPA and both extensions, uploads that
exact IPA, verifies Apple processing and existing internal-group availability,
then seals `verification.json`, confirmed `upload-receipt.json`, availability
receipt and `TestFlight-candidate.json` into
`clarify-testflight-candidate-<run>-<attempt>`. The summary records artifact ID
and digest. Evidence is retained for 90 days. Signing credentials and upload
private keys are cleaned on success or failure.

The existing upload guard reads all prior runs/attempts. A successful upload
resumes only processing/group availability. A failed, cancelled or unknown
upload is uncertain and blocks another upload. Inspect Apple and use
`mode=status` or `mode=availability`; do not rebuild or reupload to hide a gap.
Only runs whose gates prove no upload in every attempt can be replaced safely.
An availability-only recovery does not manufacture a complete signed producer.
Retain the original identity and reconcile evidence manually if necessary.

## Manual App Store promotion

**iOS App Store handoff** is manual and read-only against Apple. Dispatch the
reviewed tag with exact source SHA, successful TestFlight run/current attempt,
explicit evidence `artifact_id`/`artifact_digest`, exact Apple build UUID and
`action=prepare-submission` or `prepare-release`. No new binary is built or
uploaded. The handoff authenticates the producer, successful signing/upload/
availability/seal steps, immutable evidence artifact and every receipt hash.
It rejects historical PR179 QA receipts, unsigned validation, stale attempts,
uncertain uploads and an Apple build ID that differs from the verified receipt.

Provide fresh operator readiness for that exact source and Apple build:

```json
{
  "report_url": "https://github.com/jvictormaynard/clarify/issues/123#issuecomment-456",
  "checked_at": "<UTC YYYY-MM-DDTHH:MM:SSZ>",
  "metadata_reviewed": true,
  "native_accepted": true,
  "store_policy_reviewed": true,
  "existing_submissions_checked": true,
  "manual_release": true,
  "store_state": "PREPARE_FOR_SUBMISSION"
}
```

These are operator assertions, not Apple API proof. The report must cover
physical-device acceptance, privacy, screenshots, metadata, export compliance,
agreements, availability and current store-policy risks. The retained keyboard
experiment uses private APIs. TestFlight permission does not establish App Store
eligibility. Missing native acceptance or policy clearance blocks handoff.

`prepare-submission` requires `PREPARE_FOR_SUBMISSION` or `READY_FOR_REVIEW`.
The operator selects this existing build in App Store Connect, chooses manual
release and submits it for review. Record the submission ID and inspect any
existing submission before creating another. `prepare-release` requires
`PENDING_DEVELOPER_RELEASE`; the operator releases that same approved build.
Verify regional public availability separately. The artifact explicitly records
that no Apple mutation or public availability verification occurred. No successful
handoff, upload, TestFlight availability, submission or approval is public-release
proof. A complete producer gap needs reviewed manual reconciliation, never a rebuild.

## Reference and local checks

The architecture uses T3 Code's pinned
[tested-source/shared-bundle release reference](https://github.com/pingdotgg/t3code/tree/d2d1e4f50ef856f940d91858915368500657b0b7/.github/workflows).
Clarify keeps reviewed preparation, exact canonical CI, native acceptance,
portable update signatures and its direct Xcode signing contracts.

Run release policy checks through `python scripts/run_tests.py --suite policy`.
During focused work, use targeted discovery under `tests/policy`. The Python
suite interface permits repeated `--suite` flags for `unit`, `contract`,
`integration`, `qt`, `windows` and `compatibility`. Do not use the retired
`--ci-product-tests` route. Local fake-API tests and static checks do not prove
Windows packaging, GitHub environments/attestations, Apple signing or availability.


Existing schema-1 intents remain historical release data. They do not authorize
this publisher. After CI changes are merged, use a new metadata-only preparation
with schema 2. Do not reuse acceptance of an older installed executable as
acceptance of the new candidate artifact.
