---
name: clarify-release
description: Prepare, publish, and verify Clarify GitHub releases with SemVer, changelog and documentation maintenance, Windows executable validation, CI gates, tags, release assets, checksums, and post-release checks. Use when the user asks to release, publish, tag, version, or audit a Clarify release in the clarify repository.
---

# Clarify Release

Publish a reproducible Windows-first Clarify release without allowing the
tag, documentation, executable, or source state to drift apart.

## Required context

Use a dedicated linked release worktree under the
[project workflow](../../../docs/agents/workflow.md#worktrees-and-parallel-work),
based on freshly fetched `origin/main`. Preserve the primary checkout and other
tasks. Read [references/release-contract.md](references/release-contract.md)
completely before changing release state.

Follow the project workflow for authorization. A release audit is read-only;
publication requires a publication request or a maintainer review and merge of
the dedicated release intent under [client release automation](../../../docs/release-automation.md).
An ordinary code merge does not authorize a release. Resolve checkout and
deployment paths from Git and the current installation instead of machine-specific defaults.

The current operational path is `community`. Signed publication is blocked:
the preflight expects a tag-triggered `Release`, but that workflow is manual-only.
The gated `Community Release` workflow owns `v*` tags and explicit tag dispatch.
Do not dispatch a competing signed release. Repair track selection and preflight under a separate authorized
change before using the signed path; preserve its signing and acceptance gates.

For manual Git operations, use native `git` for branches, commits, tags and
pushes. The release automation uses its scoped GitHub API token for these
operations. Prefer the GitHub connector for manual PR metadata; use `gh` for
authentication, Actions, release inspection, downloads and connector gaps.

## Workflow

### 1. Establish the release boundary

1. Fetch `origin`, including tags, and inspect the source state.
2. Preserve unrelated changes. Require a clean linked release worktree before
   editing release files; an unrelated dirty checkout is not the release target.
3. Inspect the latest GitHub release, existing tags, open PRs, and commits since
   the latest tag.
4. Choose the next SemVer:
   - patch for compatible fixes and dependency maintenance;
   - minor for backward-compatible user features;
   - major only for intentional breaking changes.
5. Stop if the proposed tag already exists or the target commits are not on the
   canonical `main`.

### 2. Prepare release documentation

For automated preparation, follow [client release automation](../../../docs/release-automation.md).
Dispatch `Release Preparation` on `main` only when preparation is authorized.
It creates a draft `release-preparation/vX.Y.Z` PR with strict declarative intent.
It does not publish. For authorized local preparation, use a linked worktree
under the project workflow and preserve the same intent and branch contract.
Repeat the current-base check before final review and delivery.

Update `CHANGELOG.md`:

- move user-visible entries from `Unreleased` into `[X.Y.Z] - YYYY-MM-DD`;
- group entries under `Added`, `Changed`, `Fixed`, `Security`, or `Removed`;
- describe observable behavior, not commit mechanics;
- change the `Unreleased` comparison to start at the new tag;
- add the comparison link from the previous tag to the new tag.

Set `__version__` in `version.py` and the top-level `version` in `package.json`
to the same exact `X.Y.Z` value before running preflight. The tag, manifest,
MSI, in-app comparison, runtime diagnostics, and packaged executable derive
from this value; the preflight rejects drift between the module, package
metadata, and proposed tag.

Audit documentation touched by the release contract:

- update `README.md` and `docs/README.pt-BR.md` when installation, shortcuts,
  configuration, requirements, or download behavior changed;
- update architecture/development docs when build or maintainer workflows changed;
- update `THIRD_PARTY_NOTICES.md` when bundled components or their terms changed;
- keep secrets, `.env`, local config, and credentials out of every artifact.

Do not make cosmetic documentation edits merely to create a release commit.

### 3. Run preflight and product validation

Run:

```bash
python3 .agents/skills/clarify-release/scripts/release_preflight.py \
  --repo . \
  --version X.Y.Z \
  --track community
git diff --check
npm run check
npm test
```

The commands show Linux/WSL. On Windows, use the configured Python interpreter.
This skill covers desktop publication; for iOS/TestFlight use the mobile guide
and publication rules in the project workflow.

For Windows UI, dependency, packaging, hotkey, focus, microphone, or
transparency changes, perform the Windows build and applicable acceptance from
the release contract. For local deployment, use `scripts/deploy.ps1` with the
observed installation path or `CLARIFY_INSTALL_PATH`. From PowerShell on a WSL
UNC checkout, invoke the script directly if npm cannot use that directory.
Verify the resulting executable hash, process path, and responsiveness.
An explicit publication request authorizes release work. It does not prove
that Windows acceptance was performed. Record manual evidence for the exact
prepared base; missing required acceptance is an open publication gate. Do not
ask for another confirmation when valid acceptance evidence already exists.

Never treat unit tests or a successful PyInstaller build as visual acceptance.

### 4. Publish the release-preparation PR

1. Prepare the metadata-only PR through `Release Preparation`, or stage only
   equivalent authorized preparation files. The intent records the accepted base
   SHA, release scope and Windows manual acceptance evidence.
2. Review version, changelog, notes and evidence. An automated preparation needs
   `CLARIFY_RELEASE_PREPARATION_TOKEN`; do not fall back to a bot PR with CI
   suppressed or pending workflow approval.
3. Mark the draft ready only after local gates pass.
4. Require `Tests (ubuntu-latest)`, `Tests (windows-latest)` and
   `Package Windows executable`, including its embedded Settings and installer
   smoke checks.
5. The maintainer reviews and merges the dedicated preparation PR. The
   single-maintainer repository does not require a second person's approval.
6. Wait for successful post-merge push CI on the exact main commit. Main must
   still point to that SHA when promotion starts. Code changes since the
   accepted base require new acceptance and preparation.

Do not tag an unmerged branch or a commit with failing post-merge CI.

### 5. Tag and publish

With `CLARIFY_RELEASE_PROMOTION_ENABLED=true`, the standalone `Release Promotion`
workflow validates the exact CI workflow, SHA, required jobs and dedicated merged
PR. It creates an annotated tag on that source, then explicitly dispatches
`Community Release` on the tag. An unset or false variable leaves promotion
inactive. Ordinary code pushes never request publication.

When automated promotion is disabled and publication is authorized, create the
annotated `vX.Y.Z` tag on the exact green preparation merge with native Git.
A human-pushed tag starts Community Release. Inspect its run before dispatching
anything else. If the tag push used `GITHUB_TOKEN`, or no run started, explicitly
dispatch Community Release with that tag and exact `source_sha`. The workflow
still requires the reviewed intent and Windows acceptance evidence. Never move
an existing tag.

A `GITHUB_TOKEN` tag push does not trigger another workflow; explicit dispatch
handles that event rule. Existing publication runs and complete releases are
left in place. Inspect or rerun the existing failed run; do not create a second
publication or replace assets. Follow the automation guide for recovery after a
partial dispatch or upload.

Community Release publishes the unsigned portable EXE, checksum, runtime SBOM,
ZIP, Qt and SoX source archives, and provenance attestations. From v0.5.0 it also
publishes Ed25519-authenticated portable metadata and its signature, as specified
in the release contract. The build, tag, metadata and provenance keep the exact
green source SHA. Verify metadata against the bundled key, executable hash and
version. This path publishes no MSI or Authenticode CAB update manifest.

The blocked signed path retains its protected Azure OIDC, timestamped EXE/MSI/CAB
signatures, checksums, source archives and provenance gates. Repair its
trigger/preflight conflict in a separate authorized change before using it.

### 6. Verify the published release

Require all of the following:

- release is published, not draft or prerelease;
- tag resolves to the intended green `main` commit;
- release is the current latest release;
- all required assets from the contract exist exactly once;
- downloaded `Clarify.exe` matches `Clarify.exe.sha256`;
- for a signed release, downloaded MSI and manifest CAB match their checksums,
  have valid RFC 3161 timestamped Authenticode signatures, and match the pinned
  publisher;
- for a signed release, authenticated manifest version, tag, channel, asset
  name, URL, size, and MSI checksum all match the release;
- GitHub provenance attestations verify for every published asset;
- ZIP contains the executable, `LICENSE`, and `THIRD_PARTY_NOTICES.md`;
- SoX source digest matches the pinned release-workflow digest;
- `/releases/latest` resolves to the new version.

Download assets into a temporary directory for verification. Do not replace the
user's installed executable with a release download unless explicitly asked.

### 7. Hand off

Report:

- version, tag, release URL, and commit SHA;
- PR and merge result;
- local, PR, `main`, and release-workflow validation;
- exact published assets and checksum result;
- documentation files updated;
- any remaining signing or SmartScreen limitation.
- manual installer acceptance evidence and any unmet rollout gate from
  `docs/windows-distribution.md`.

Preserve the starting checkout, branch, and unrelated work. Retain the verified
release source and evidence. Clean up only task-owned temporary resources after
their results are preserved; do not switch the primary checkout to `main`.

## Stop conditions

Stop publication and explain the blocker if:

- unrelated local changes make scope ambiguous;
- a required test, package job, or post-merge check fails;
- the Windows build, deployment, or installed-process verification fails;
- the tag exists at another commit;
- the release workflow or any required asset is missing;
- signed-release signing configuration, timestamp, publisher identity, or
  provenance fails;
- the installer/update rollout gates are incomplete for a release that intends
  to enable that path;
- checksum, ZIP contents, SoX source digest, or tag provenance does not match.

Never force-move a published tag, rewrite contributor history, or silently
replace release assets.
