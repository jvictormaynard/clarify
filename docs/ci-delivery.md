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
| Internal iOS QA workflow, policy or archive-only changes | QA/archive policy tests, without unrelated product builds |
| Settings frontend, styles or browser tests | Frontend build and isolated Playwright/Python bridge tests on Linux |
| Python or QML behavior | Python tests on Linux and Windows, with existing lint and type checks |
| Settings bridge | Settings tests and Python tests |
| Desktop build inputs, Rust, runtime locks or distribution policy | Native Settings, portable EXE, embedded payload, startup and portable update recovery |
| MSI inputs | Portable build plus isolated installer lifecycle and CAB manifest checks |
| Server or its shared contracts | PostgreSQL tests, missing migrations, container build and database startup |
| Computer relay or Desktop Python contracts | Desktop checks, including the relay container build and non-listening entrypoint validation on Linux |
| Mobile JavaScript or TypeScript | Types, lint, contracts, locale/prompt synchronization and an iOS JavaScript bundle |
| Swift, Objective-C, native configuration, plugins or mobile dependencies | Mobile checks, native tests, keyboard simulator integration and unsigned app/extension build |
| Shared contracts or CI policy | All affected consumers; unknown dependencies use full validation |
| Desktop dependency inputs or audit policy | Existing Python and Settings dependency audits |

A small design change does not require Rust, an EXE, MSI, or an unrelated Apple
build. A few changed lines can still affect a native contract; selection uses
the input paths, not line count, PR labels, contributor identity, or an AI risk
score. A manual CI run validates all components, including the MSI path.

Python workflow changes select Desktop, server and mobile checks. Mobile checks
verify that the generated native prompts still match their source. A changed
native prompt or other Swift input also selects the native iOS jobs. Publication
policy changes in `scripts/release_delivery.py` run the existing repository policy
tests; that script is not an application build input.

The UI catalog keeps one translation source. `shared/desktop_ui_keys.json` marks
reviewed text that mobile does not use. New, unclassified text remains in the
native catalog. The locale check scans mobile source for exact desktop key text.
See [localization scope](development.md#interface-localization) for its coverage
limits.
For a catalog change, CI compares the native projections in the base and tested
Git commits. It omits native iOS only when those projections match and no other
changed input selects iOS. Missing, invalid or nonregular catalog inputs retain
native validation. Changing the scope file itself also selects native validation.

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

Repository checks always runs the skill, delivery and release policy checks.
The selector's `qa_policy` metadata adds the QA/archive suites and their locked
Node/YAML setup for affected controls, dependencies or full validation. The
aggregate rejects missing or invalid metadata. Docs-only and native-source-only
changes omit this extra work.
Trusted QA uses the same range selection for the QA/archive extras. It retains
its original delivery, release and trusted-policy suites, plus native/mobile
acceptance. This selection does not change the validation manifest schema.

## Branch protection

The required aggregate is `CI required`; individual job names remain for release
evidence. Source changes do not update GitHub branch protection. When changing
protection or preparing a merge, read the live `main` protection and record its
required checks, strict setting and UTC time. Preserve unrelated protection rules.

Read-only verification on 2026-10-28 at 04:59:20 UTC returned only `CI required`
in the required status checks, with `strict=true`. This is a dated observation,
not a guarantee for a later delivery. Recheck with:

```sh
gh api repos/jvictormaynard/clarify/branches/main/protection/required_status_checks
```

<a id="branch-protection-migration"></a>

The [2026-10-25 migration record](https://github.com/jvictormaynard/clarify/blob/be4796c7c771af98a5782acb2eef9a5d4d50e3c4/docs/ci-delivery.md#branch-protection-migration)
retains the transition from unconditional checks to `CI required`.
It does not request a new activation or protection change.

## Repeated work and caches

Browser validation is separate from the native Settings build. Cargo downloads
and compilation outputs use OS, architecture, compiler and lock-based caches.
iOS caches CocoaPods downloads and Xcode build outputs. Builds still run and
validate restored inputs; a cache hit is not proof of successful validation.
Do not put profiles, secrets, recordings or signing materials in caches.

Native iOS tests and unsigned compilation run in separate parallel jobs. Each
keeps a 60-minute limit, so test setup does not consume the compilation budget.
The existing `Native tests and unsigned build` check requires both jobs to
succeed. Failure, cancellation or skipping either job blocks that check and
client publication. These validation jobs do not sign or upload an app.

Native tests restore Swift package and UIKit build caches before running. UIKit
uses a stable, isolated fixture and DerivedData directory. The harness records
fixture preparation, simulator boot and test/build durations, and retains its
result bundle. The app build emits the Xcode build timing summary. CI uploads
the available evidence after success or failure. Cache keys include the runner,
toolchain and source inputs; restored builds and all assertions still run.

The `iOS validation` workflow also accepts a manual run on a contribution branch.
It runs the same unsigned validation and aggregate gate. For a cache measurement,
compare runs of the same source and toolchain, including cache restore/save cost.
The command is `gh workflow run ios-validation.yml --ref <branch>`. A cache hit
alone is not evidence of a successful or faster build.

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

An explicitly requested internal TestFlight candidate can keep its implementation
PR open. Its separate [candidate gate](release-automation.md#explicit-internal-candidates-from-an-open-pr)
requires current canonical source, completed PR and native CI, a checked build
reservation and an immutable PR-specific tag. This path does not publish a
stable client or change the normal preparation and promotion gates.
