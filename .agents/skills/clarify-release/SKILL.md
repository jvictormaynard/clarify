---
name: clarify-release
description: Prepare, build, accept, publish, and verify Clarify desktop release candidates with immutable source, assets, provenance and explicit publication.
---

# Clarify Release

Build a candidate once with its final identity. Publish only that authenticated
candidate after its native acceptance and a separate explicit publication action.

## Required context

Read the complete [release contract](references/release-contract.md) and
[automation guide](../../../docs/release-automation.md). Use the
[project workflow](../../../docs/agents/workflow.md#worktrees-and-parallel-work)
for authorization, a linked current-main worktree and ownership. Preserve other
checkouts, user profiles, existing artifacts and unrelated edits.

A release audit is read-only. An authorized preparation creates a reviewed
metadata-only PR. Its merge authorizes candidate creation after exact green main
CI. It does not prove Windows acceptance or authorize implicit desktop
publication. Publication requires the accepted packaged candidate and explicit
`publish-candidate` action. A skill grants no Git, provider or publication rights.

`release.yml` is the only active desktop release owner. It is manual-only with
`build-candidate` (default) and `publish-candidate`, and `preview` (default) or
`stable`. Preview has no stable updater or latest effect. There is no active
MSI/Authenticode/CAB publication path. Preserve their runtime compatibility and
future rollout gates in `docs/windows-distribution.md`.

## Prepare reviewed source

1. Inspect current main, tags, release state and intended source changes. Use
   native Git for authorized branch, commit, tag and push operations. Never
   force-move a tag or change a sibling checkout.
2. Choose SemVer according to the actual changes. Keep `version.py`, root
   `package.json`, the dated changelog section and comparison links aligned.
3. Use **Release Preparation** on main, or equivalent authorized local
   preparation. Schema 2 contains `component`, `version`, `base_sha`, `notes`
   and `evidence`, in addition to `schema`. Desktop evidence contains only a
   canonical `report_url`. Do not restore pre-build Windows acceptance fields.
4. Review the metadata-only `release-preparation/vX.Y.Z` PR. Only intent,
   changelog and desktop version values can differ from the prepared source.
   Review scope, notes, notices and relevant documentation. Update only documents
   whose owned behavior changed. Never include secrets, local config or audio.
5. Complete applicable checks under `docs/ci-delivery.md`, including policy tests
   with `python scripts/run_tests.py --suite policy`, and the read-only preflight:

   ```sh
   python .agents/skills/clarify-release/scripts/release_preflight.py --repo . --version X.Y.Z --channel stable
   git diff --check
   ```

6. After maintainer review and merge, require canonical successful main push
   `CI` at `.github/workflows/ci.yml`, exact merge SHA and its unique completed
   successful `CI required`. Ordinary CI owns its component graph. Do not copy
   old component job names into release consumers.

## Build a candidate

Main must still identify the reviewed source at candidate creation. Create an
immutable annotated stable tag on that source only when authorized. With
`CLARIFY_RELEASE_PROMOTION_ENABLED=true`, promotion can create the tag and
explicitly dispatch the stable candidate build. Unset/false remains inactive.
Promotion never dispatches desktop publication.

Dispatch **Desktop Release** on the reviewed stable tag with
`action=build-candidate`, `channel=stable` and exact `source_sha`. Preview uses
an exact branch dispatch with `channel=preview`. A tag push alone publishes
nothing. Inspect existing runs before dispatch; preserve partial/uncertain state.

The candidate build retains current pinned dependencies, audits, native Settings
and embedded payload checks, portable startup/recovery smoke checks, licenses,
SBOM, checksums, pinned source archives and build provenance. Stable update
metadata is signed once inside `portable-updates`, with no fallback key. The
build has no Contents write permission. Preview disables its update policy
before packaging and contains neither update manifest nor signature.

Record source/ref, run/attempt, final channel/version/tag, artifact ID and digest.
`Clarify-candidate.json` binds exactly the allowed assets, hashes and sizes.
Do not repackage, re-sign or mutate that candidate after acceptance.

## Accept and publish the existing bytes

Perform Windows manual acceptance on the actual stable artifact after packaging.
Verify the artifact digest and executable checksum first. Cover the affected
native contracts. Record results and limits in a fresh canonical maintainer
report with the exact `clarify-candidate-acceptance` block from the automation
guide. Both source SHA and candidate digest must match. CI, compilation and a
preview of different bytes do not establish acceptance. No second unrelated
pre-build manual acceptance is required.

When publication is authorized, dispatch **Desktop Release** from main with
`action=publish-candidate`, channel/version/source, explicit completed candidate
run ID/current attempt, immutable artifact ID/digest and stable acceptance JSON.
The protected `desktop-publication` job requires separate opt-in
`CLARIFY_RELEASE_PUBLICATION_ENABLED=true`. It authenticates the producer and
receipts, verifies every input and provenance, and uploads only existing candidate bytes.
It installs no application dependencies, builds nothing and has no signing key.

It rejects stale attempts, wrong source/channel/version, path escapes, symlinks,
extra or missing inputs, preview metadata, wrong tags and partial/uncertain assets.
It creates a draft, uploads once, verifies exact remote hashes/sizes, then publishes.
Stable explicitly becomes latest; preview is a nonlatest prerelease. A complete
matching release is verified without another upload. Never overwrite assets,
retry an uncertain upload automatically, or use a rebuild to hide a gap.

## Verify and hand off

Verify the exact tag/source, release state, candidate identity, downloaded hashes,
checksums, ZIP licenses, Qt/SoX sources, signed stable update metadata and
provenance for every asset. Stable must be latest after its publication. Preview
must remain a prerelease without updater metadata or a stable-feed change.
Download into a temporary directory; replacing a user's installed app requires
its own authorization.

Report source/base/HEAD, version/tag, candidate run/attempt/artifact ID/digest,
manual report, publication action/result, exact asset verification and open gates.
A local build, accepted workflow dispatch, passing unit test or merged PR proves
only that stage. Keep Windows packaging/acceptance and GitHub/Apple results separate.

For iOS, follow the [mobile guide](../../../mobile/README.md#direct-testflight-delivery).
`validate` is unsigned. TestFlight is the signed production-identity candidate.
App Store handoff authenticates its exact Apple build ID and evidence artifact
without rebuilding. Submission/release is manual; no handoff is public availability.
