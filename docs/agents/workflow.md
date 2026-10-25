# Clarify engineering workflow

This workflow applies to this repository and its worktrees. Skills live in
`.agents/skills/`; they are project instructions, not new execution permissions.
Read only the skill and reference that the current task needs.

## Scope and autonomy

Inspect the current request, source, tests, and Git state first. If an issue is
supplied, read its description, comments, checklists, dependencies, subtasks, and
relevant attachments. Work from the observable outcome, not just the title.

Make routine reversible technical decisions within the authorized task.
Choose test boundaries, internal names, and focused implementation details from
the existing contracts. State consequential assumptions. Ask for a decision
only when missing information changes product behavior, persisted compatibility,
data ownership, a costly design choice, or scope. Continue independent work while
a required answer is pending; silence is not approval.

Preserve the starting branch and unrelated changes. Every implementation uses
a linked worktree on its own `codex/` branch, based on freshly fetched
`origin/main`. Follow [worktree preparation and parallel work](#worktrees-and-parallel-work)
before edits, delegation, integration, and delivery. Do not switch or rewrite
someone else's in-progress branch. Stage explicit paths.

Commit, push, PR creation, merge, issue mutation, account changes, local deployment,
and release follow the user's request and prior authorization. Prepare all local
work first if an additional approval is required. Never force-move a published
tag, erase a user profile, or include secrets in artifacts.

This project requests parallel delegation for independent implementation tasks
when supported; a repeated user instruction is unnecessary. Use the worktree
and review rules below. Do not create user-owned chats unless the user asks.

## Worktrees and parallel work

Run worktree commands with Linux Git for a WSL repository. Use an
explicit working directory. Do not use Windows Git on a WSL checkout.

```bash
git -C /home/ork/repos/clarify status --short --branch
git -C /home/ork/repos/clarify worktree list
git -C /home/ork/repos/clarify fetch origin
git -C /home/ork/repos/clarify rev-parse --verify origin/main
git -C /home/ork/repos/clarify worktree add -b codex/feature-name /home/ork/worktrees/clarify-feature-name <resolved-main-sha>
```

Use each command only after the previous command succeeds. Replace the example
task name and path; replace `<resolved-main-sha>` with the exact SHA returned by
`rev-parse`. The coordinator prepares worktrees serially and checks the current
worktree list before each creation. Select a new branch and a nonexistent path
outside existing worktrees. Do not use force options, overwrite an existing
branch, or copy dirty files, profiles, secrets, or dependencies from the source.

Before editing an existing task worktree, before final validation/review, and
immediately before requested delivery, inspect it and refresh the base:

```bash
git -C <task-worktree> rev-parse --show-toplevel --absolute-git-dir --git-common-dir
git -C <task-worktree> branch --show-current
git -C <task-worktree> status --short
git -C <task-worktree> fetch origin
git -C <task-worktree> rev-parse origin/main HEAD
git -C <task-worktree> merge-base --is-ancestor origin/main HEAD
```

Confirm the top-level path is the assigned linked worktree, its resolved Git
directory differs from the shared common Git directory, and its task branch
starts with `codex/`. A primary checkout or detached implementation is not ready;
prepare a linked worktree or assign a distinct task branch first. Dirty task
files are permitted and remain in the candidate. `merge-base` must exit zero;
a nonzero result requires investigation or integration of current `main`.
Retain the path, branch, fetched SHA, HEAD, dirty paths, and UTC fetch time as
concise task evidence. These commands do not commit, publish, or integrate work.

The guarantee applies at the recorded fetch time. The remote can advance during
work; never claim continuous synchronization or use cached refs after failure.
Do not reset, clean, stash, or replace existing work to make a check pass.
If governing guidance is still uncommitted, pass its explicit absolute paths
and rules to workers as context. Do not copy the dirty checkout to carry rules.

Delegate two or more independent implementation outcomes when tools support it.
A single small task normally needs one implementer. Inspect source and full task
context before splitting. Give shared interfaces one owner before starting
dependent work. Serialize competing edits to locks, schemas, migrations, and
release metadata. Do not split tightly coupled work just to keep agents busy.

The coordinator prepares one current-base worktree per writer and supplies:

- Outcome, acceptance criteria, source context, dependencies, and owned paths.
- Absolute worktree path, branch, base SHA, governing guide paths, and shared contracts.
- Focused checks, isolation constraints, permitted Git operations, and required
  return: changed files, HEAD/dirty state, results, findings, and unresolved limits.

Workers verify their assigned directory before editing, use explicit working
directories for commands, and target absolute paths for edits. Spawning does not
isolate a shared filesystem or default directory. Do not share writable profiles,
config, caches, build outputs, test databases, recordings, or ports. Use lockfiles
and temporary fixtures. Workers do not edit sibling worktrees, integrate siblings,
publish, rewrite branches, or start more implementers without assignment.
Read-only reviewers may inspect the fixed candidate without writing. If tools
or capacity prevent delegation, use the same workflow serially and state this.

Only the coordinator integrates results. For multiple features, prepare a separate
integration worktree from freshly fetched `origin/main` and combine outcomes in
dependency order. Preserve each worker's uncommitted work until integration is
verified. Git operations retain the authorization rules above. For uncommitted
local delivery, transfer only explicit task diffs, including new files. If the
base advanced, preserve the old worktree and integrate on the new base. Inspect
both intents for conflicts; a material product conflict needs a user decision.

Run applicable checks and review on the complete integrated candidate. Worker
passes do not prove combined behavior. If the base or candidate changes, repeat
affected checks and review. Retain the reviewable result and report its worktree
path and freshness evidence. Remove only task-owned temporary resources after
results are preserved; never remove a dirty or unrelated worktree automatically.

## Ownership and architecture

[Architecture](../architecture.md) is the source of truth for production owners,
provider/storage contracts, data, platform behavior, and packaging. Read
[Contributing](../../CONTRIBUTING.md) before a structural change.

Trace a behavior from its entrypoint through state and effects to its observable
result. Keep domain decisions outside QML/React renderers. Use the existing typed
provider registry, HTTP policy, workflow services, recording lifecycle,
configuration repository, and SecretStore rather than creating parallel owners.

Keep interfaces small and explicit about cancellation, errors, ordering, and
resource ownership. A thin platform adapter can be necessary. Compare alternative
interfaces when a decision is costly; use one coherent change for a small fix.
Broad unrelated refactoring belongs in a separate proposal or task.

Preserve stale-operation rejection, publication claims, once-only usage accounting,
focus-safe clipboard ownership, audio cleanup, atomic persistence, migrations,
and read-only handling of newer schemas. Keep BYOK cloud routes distinct from
optional Local Whisper. A local route has no implicit cloud fallback.

## Validation by affected contract

Use the highest applicable row. Read the current commands and tool versions in
[Contributing](../../CONTRIBUTING.md), [Development](../development.md),
`package.json`, and `.github/workflows/ci.yml`; those files own the executable
checks. Do not duplicate their complete command lists in each skill.

| Change | Validation |
| --- | --- |
| Instructions, docs, or skill metadata | Skill validator, references, attribution, `git diff --check`; no new product test for wording alone |
| Python behavior or internal refactor | Focused behavior/contract tests during work; final Python suite and relevant compile/lint/type checks |
| Qt/QML visual or interaction behavior | Relevant Python and QML smoke checks; real Windows executable checks for focus, hotkeys, tray, geometry, transparency, and affected DPI |
| Settings or Python-to-Settings bridge | Relevant Python tests, frontend build/type check, isolated Playwright fixture, and native Windows acceptance for integration behavior |
| Persistence, credentials, provider routing, workflow concurrency, clipboard, audio, or ASR lifecycle | Regression evidence for affected failure/cancellation/compatibility paths, full Python suite, relevant Settings/Windows checks, and focused architecture review |
| Dependencies, CI, or packaging | Applicable Python/Settings checks, pinned lock and audit rules, Windows build and embedded-payload checks when build inputs changed |
| Desktop publication | Existing `clarify-release` contract, exact source/tag/CI alignment, track-specific assets, downloaded hashes and provenance |
| iOS/TestFlight publication | Existing mobile guide and iOS workflow, exact source/version/build identity, native tests, verified signed IPA, successful upload, Apple processing and target-group availability |

The repository agent guide requires the Python suite after repository changes.
Run relevant Settings tests when their behavior or bridge is affected. A CI-only
skills-check step does not change product build inputs and does not itself require
a local Windows rebuild. Release and platform acceptance gates still apply to
the product changes they cover.

Use the configured interpreter, not a guessed executable alias. On Windows it is
normally `.venv/Scripts/python.exe`; on Linux a Linux interpreter/environment is
needed. A Windows virtual environment is not a Linux environment. When accessing
a WSL checkout from PowerShell, invoke a `.ps1` directly if the npm shell cannot
use the UNC working directory.

Initialize a temporary profile before importing application code. Pass fake
providers, clocks, clipboard/secret stores, and audio fixtures. A test environment
must never read the developer's live profile, keys, microphone, or recordings.
Settings tests use `tests/web_settings_fixture.py`. Keep Windows SQLite and type
checker caches on a Windows-local temporary path when a UNC path is unsupported.

For changed behavior, confirm a regression can fail for the actual symptom before
the fix, then pass afterward. Retain existing tests until equivalent behavior and
platform/security evidence are accounted for. Avoid tests that copy the implementation
or merely match instruction wording.

Run narrow checks during development and the applicable final suite after the
candidate stabilizes. Repeat or broaden checks only for a new change, failure,
or unresolved concern. Distinguish an environment failure from a product defect.
Repair in-scope failures; report unrelated failures with evidence.

## Publication after parallel implementation

For CI/CD changes, start with [main validation and delivery](../ci-delivery.md).
The server uses native Railway GitHub autodeploy with `Wait for CI` and source
watch paths. Inspect the connected repository, branch, CI wait setting, and
healthcheck before changing infrastructure. Follow the
[server delivery guide](../server-delivery.md) for activation and migration limits.
Implementing automation does not authorize a live deployment or its activation.

Desktop and mobile code changes run validation without publishing each push.
A dedicated release-preparation PR records the selected platform version and
acceptance evidence. Its reviewed merge and exact green source are the release
boundary. See [release automation](../release-automation.md) for preparation,
promotion, opt-in settings, and retry behavior. App Store publication stays a
separate action.

Publication has one coordinator per platform. Workers implement and validate
features; they do not independently reserve version numbers, create release
tags, or submit builds. Integrate the accepted features first, then choose and
record the exact source SHA in a dedicated release worktree. Further changes
belong to the next candidate unless the current one is rebuilt and revalidated.
Desktop and mobile versions are independent. Publication still follows the
user's authorization; integrating instructions alone does not request a release.

For desktop, use [clarify-release](../../.agents/skills/clarify-release/SKILL.md).
The coordinator owns SemVer, changelog, release PR, green post-merge CI, immutable
tag, and the selected release track. Verify downloaded assets, checksums, update
metadata and provenance before reporting availability.

For iOS, follow [the mobile guide](../../mobile/README.md) and
[the iOS workflow](../../.github/workflows/ios-testflight.yml). Check the existing
App Store Connect build numbers and pending submissions before reserving a new
`expo.ios.buildNumber` in `mobile/app.json`. Keep the app and extensions aligned.
Use `tests_only` for validation without signing/upload. For publication, run the
workflow on the immutable reviewed `ios/vX.Y.Z-buildN` tag and pass its exact
source SHA. The guarded workflow no longer uploads on delivery-branch pushes.
An older remote `codex/ios-testflight` workflow can still upload until that branch
receives the guarded workflow; avoid source pushes there before this update.
Uploads, Apple processing, and group availability share a serialized workflow
group; this does not reserve build numbers or prove availability.
Verify the signed IPA and upload, then Apple processing and the intended
TestFlight group separately. App Store distribution is a separate delivery scope.

## Review and completion

Record the review's base/HEAD SHAs and dirty paths. Include new, staged, and
unstaged files when reviewing unfinished work. Review requirements separately
from engineering. Investigate callers, effects, and tests outside the changed hunk
when necessary. Report defects with a failure scenario and location.

Use one fresh read-only reviewer for changed behavior in a few adjacent modules.
For high-risk boundaries in the validation table, broad changes across independent
features, or substantial delivery-rule changes, use two fresh read-only reviewers:
one for requirements, one for engineering. An isolated wording change needs
self-review only. Reviewers receive the same complete candidate and do not spawn
more reviewers. A blocking finding must be repaired and the changed candidate
checked again. Do not claim an independent review if tools were unavailable.

Before final review and delivery, run the current-base check in the integration
worktree. A successful check proves ancestry at its recorded fetch time, not
continuous synchronization. If the base or candidate changes, repeat affected
checks and review. Preserve task-owned uncommitted work during integration.

Complete the delivery level the user requested:

- Local implementation: a coherent diff, applicable terminal checks, repaired
  in-scope findings, and a clear report of limitations.
- PR: the exact source state, accurate description, and requested PR operation.
- Merge: passing required checks for the actual candidate and verified merge state.
- Desktop release: all gates in `clarify-release`, including the post-merge/tag workflows
  and downloaded asset verification.
- TestFlight: exact source/build identity, successful signed upload, completed
  Apple processing, and verified availability to the intended testing group.

Passing automated checks does not establish manual Windows acceptance. Deployment
hash/process evidence does not establish a user-observed visual result. State which
interaction check was performed and which was unavailable. Never label a still-running
check, pending CI job, incomplete build, or unverified publication as complete.

## Maintenance

The [skill audit](skill-audit.md) records every upstream decision and its pinned
source. Update adapted skills deliberately; never run an unattended upstream
overwrite. Use `python scripts/check_agent_skills.py` and the creator's validator
when available. CI checks local integrity on Linux and Windows.

The validator checks packaging and provenance, not architectural judgment. Walk
through realistic tasks after a behavior-changing skill edit and measure actual
delivery outcomes before claiming an improvement in speed or defect rate.
