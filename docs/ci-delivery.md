# Validation by affected component

`CI` runs for pull requests to `main` or `master`, pushes to those branches, and
manual runs. A push to a contribution branch does not start a second CI run.
Fork pull requests use the same read-only workflow and need no signing,
provider, Railway, or Apple secrets. GitHub may require a maintainer to approve
a first-time contributor's workflow run.

## Selected checks

`scripts/delivery_policy.py` compares a push with its `before` commit. For a pull
request, it compares the tested merge with the pull request's base commit. The
comparison includes both paths of a rename and the whole change range. Invalid
or missing boundaries fail validation. Unknown inputs select all checks.

| Changed contract | Checks |
| --- | --- |
| Prose or agent metadata | Repository policies and skill integrity |
| Settings frontend, styles or browser tests | Frontend build and isolated Playwright/Python bridge tests on Linux |
| Python or QML behavior | Python tests on Linux and Windows, with existing lint and type checks |
| Settings bridge | Settings tests and Python tests |
| Desktop build inputs, Rust, runtime locks or distribution policy | Native Settings, portable EXE, embedded payload, startup and portable update recovery |
| MSI inputs | Portable build plus isolated installer lifecycle and CAB manifest checks |
| Server or its shared contracts | PostgreSQL tests, missing migrations, container build and database startup |
| Mobile JavaScript or TypeScript | Types, lint, contracts, locale/prompt synchronization and an iOS JavaScript bundle |
| Swift, Objective-C, native configuration, plugins or mobile dependencies | Mobile checks, native tests, keyboard simulator integration and unsigned app/extension build |
| Shared contracts or CI policy | All affected consumers; unknown dependencies use full validation |
| Desktop dependency inputs or audit policy | Existing Python and Settings dependency audits |

A small design change does not require Rust, an EXE, MSI, or an unrelated Apple
build. A few changed lines can still affect a native contract; selection uses
the input paths, not line count, PR labels, contributor identity, or an AI risk
score. A manual CI run validates all components, including the MSI path.

Release-preparation intent selects its platform. Desktop preparation forces its
tests, Settings, portable build and audit. Mobile preparation forces mobile,
native iOS checks without Desktop builds or audits. Malformed or unknown
intent selects full validation; publication separately rejects invalid intent.

`Repository checks` runs for every CI event. `CI required` runs even after a
dependency fails or is skipped. It requires a successful classifier and
repository check, every selected job to succeed, and a valid result for every
declared job. A selected job that is missing, cancelled, failed or skipped fails
the final check. Unselected jobs may be skipped. Do not skip the entire required
workflow with path filters or commit-message markers.

## Branch protection migration

The previous protection requires `Tests (ubuntu-latest)`,
`Tests (windows-latest)` and `Package Windows executable` for every PR. The new
required check is `CI required`; the individual job names remain for release
evidence. Source changes alone do not update the GitHub protection setting.

Before enabling the new policy on `main`:

1. Run this workflow on its PR and confirm `CI required` checks the actual tested
   candidate. Inspect documentation, design, native and failed-job cases.
2. Add `CI required` as a required GitHub Actions check, then remove the three
   unconditional Desktop checks. Keep current-base validation, PR requirements,
   conversation resolution and force-push restrictions.
3. Verify that a docs-only PR can pass without product jobs, a Settings design
   PR runs browser checks, and a failed selected job blocks a merge.

Do not remove the old required checks before the replacement check is present
and required. The repository workflows cannot apply this setting themselves.

## Repeated work and caches

Browser validation is separate from the native Settings build. Cargo downloads
and compilation outputs use OS, architecture, compiler and lock-based caches.
iOS caches CocoaPods downloads and Xcode build outputs. Builds still run and
validate restored inputs; a cache hit is not proof of successful validation.
Do not put profiles, secrets, recordings or signing materials in caches.

The existing Desktop dependency audits run when their dependency inputs change
and daily at 04:23 UTC on the default branch. Desktop release builds retain
fresh audits. Mobile and server checks validate their own locked inputs; this
change does not add new vulnerability-audit coverage for those platforms. The separate
`iOS audio contracts` workflow remains manual; native CI already runs those
audio tests. There is no scheduled full native build.

## Integration and publication

Each writer uses a separate current-base worktree. Local native staging, Cargo
targets and deploy build roots use a stable suffix from that worktree path.
PyInstaller caches are also isolated. Run one native build per worktree at a
time; separate worktrees can build concurrently. Run focused checks while
implementing, then applicable checks on the complete integration candidate.
One coordinator orders merges and one coordinator per platform selects release
versions. Workers can continue other tasks while GitHub validates a PR.

Each push to `main` keeps its own CI concurrency group. New pushes do not cancel
that commit's validation: Railway's `Wait for CI` can ignore some cancellations
when another workflow passed. Keep this protection while reducing selected work.
Server delivery follows the [native Railway setup](server-delivery.md).

Client checks do not publish on every merge. Publication uses dedicated
[release preparation and promotion](release-automation.md), with exact source
SHA, platform-specific evidence, immutable tags and separate publication
credentials. Windows interaction acceptance and physical iPhone/TestFlight
acceptance remain required where applicable. Browser tests do not prove native
focus, hotkeys, tray behavior, microphone routing or keyboard insertion.
