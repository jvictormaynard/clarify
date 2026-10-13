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
publication requires a publication request. Resolve checkout and deployment
paths from Git and the current installation instead of machine-specific defaults.

The current operational path is `community`. Signed publication is blocked:
the preflight expects a tag-triggered `Release`, but that workflow is manual-only,
and every `v*` tag also starts `Community Release`. Do not dispatch a competing
signed release. Repair track selection and preflight under a separate authorized
change before using the signed path; preserve its signing and acceptance gates.

Use local `git` for branches, commits, tags, and pushes. Prefer the GitHub
connector for PR creation and metadata; use `gh` for authentication, Actions,
release inspection, downloads, and gaps in connector coverage.

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

Create or verify `codex/release-vX.Y.Z` in its own linked worktree using the
project workflow. Repeat the current-base check before final review and delivery.

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
When the user explicitly requests publication, treat that request as approval
of visible and interaction changes. Do not require a second manual-acceptance
confirmation. Report any manual interaction check that was not performed as an
open validation limitation.

Never treat unit tests or a successful PyInstaller build as visual acceptance.

### 4. Publish the release-preparation PR

1. Stage only release-preparation files.
2. Commit tersely, for example `docs: prepare vX.Y.Z release`.
3. Push the branch with upstream tracking.
4. Open a draft PR against `main` explaining scope, version choice,
   documentation changes, validation, and expected assets.
5. Mark ready only after local gates pass.
6. Require all PR checks:
   - `Tests (ubuntu-latest)`;
  - `Tests (windows-latest)`;
  - `Package Windows executable` (including MSI lifecycle and manifest smoke
    tests).
7. Merge without rewriting existing contributor history.
8. Wait for the post-merge `main` CI, including Windows packaging.

Do not tag an unmerged branch or a commit whose post-merge CI is failing.

### 5. Tag and publish

Resolve the exact green `origin/main` SHA. Create an annotated tag:

```bash
git tag -a vX.Y.Z <main-sha> -m "Clarify vX.Y.Z"
git push origin vX.Y.Z
```

Watch the tag-triggered `Community Release` workflow. It publishes the unsigned portable
EXE, checksum, runtime SBOM, ZIP, Qt and SoX source archives, and provenance
attestations. From v0.5.0 it also publishes Ed25519-authenticated portable
metadata and its signature, as specified in the release contract. Verify these
against the bundled public key, executable hash, version, and source SHA.
It must not publish an MSI or an Authenticode CAB update manifest.

The blocked signed path retains its protected Azure OIDC, timestamped EXE/MSI/CAB
signatures, checksums, source archives, and provenance gates. It is not an
alternative publication command until the trigger/preflight conflict is repaired.

Do not create a second manual release while the workflow is running.

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
