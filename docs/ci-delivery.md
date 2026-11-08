# Validation and delivery

`CI` is the validation entry point. Pull requests to `main` run affected tasks.
Every push to `main` requires the full standard set. Exact merged PR evidence can
satisfy selected components under the rules below. Daily runs at 03:17 UTC and
manual runs add extended checks, including the disposable installer lifecycle.
Contribution-branch pushes do not start a duplicate run. Validation does not
publish a desktop or mobile release. Fork PRs need no signing or provider keys.

## Reuse successful PR validation on main

`ci/evidence.py` owns read-only PR evidence authentication. Successful PR
`CI required` emits schema-1 `proof.json`, then uploads it as its last step.
A failed emission or upload fails the aggregate. The proof records CI selection
and results, repository, workflow, run/current attempt, PR event base/head, and
the checked-out synthetic merge SHA, tree and ordered parents.

Canonical main pushes can reuse only selected successful components from the
latest canonical same-repository PR CI, which must be successful and within
24 hours. Authentication
requires one merged nonfork PR, an actual two-parent integration, matching tested
tree and ordered base/head parents, successful `CI required`, and the immutable
artifact ID and GitHub SHA-256 digest. It checks the producer attempt again after
reading the artifact. It does not depend on the run's `pull_requests` array or
confuse the run's PR head SHA with the tested synthetic merge SHA.

Planning uncertainty runs ordinary main CI. The main aggregate reauthenticates
the same artifact and recomputes the original plan minus verified coverage;
authentication failure or a changed selection fails the aggregate. Policy always
runs fresh. Mobile and iOS also run fresh so internal TestFlight proof still
contains the required native jobs and steps in the main run. Installer remains
fresh, and package remains fresh when installer needs its main-SHA artifact.
No artifact transfer or release evidence contract changes are included.

CI control changes (including `ci/`, workflows/actions, scripts, policy tests and
shared classifier inputs) disable reuse for the integration. Bootstrap therefore runs
ordinary main CI. Direct pushes, squash/rebase integrations, changed base,
foreign/fork PRs, absent or expired artifacts, scheduled and manual runs also
use ordinary CI. Main runs never emit reusable evidence. Hosted validation of
the workflow and artifact transport remains separate from local fake-API tests.

Reviewed release-intent data and version/build metadata can use the same evidence
rules. They do not change the CI mechanism or relax release authorization.

## Optional Bitrise macOS capacity

Set repository variable `CLARIFY_IOS_RUNNER=bitrise` to use the existing
`bitrise-runner-clarify-ios-validation` pool for canonical main pushes, same-repo
PRs and manual iOS runs. Fork PRs and unrecognized events keep GitHub-hosted
`macos-26`. Removing the variable restores that default.

The Bitrise pool uses Xcode 26.6 at
`/Applications/Xcode-26.6.0.app/Contents/Developer`; GitHub uses
`/Applications/Xcode_26.6.app/Contents/Developer`. Native build caches are
separated by host. Test commands, regular/compact profiles, budgets and required
checks are the same. Manual TestFlight runs retain the reviewed tag/source gate,
protected signing environment, temporary keychain cleanup and IPA/upload checks.

The pool needs active Bitrise capacity. The current Build Hub trial ends on
2026-11-15 and does not renew automatically. No paid plan or RDE beta is enabled
by this variable. This runner selection does not enable release promotion.

## Ownership and commands

`ci/impact.py` owns dependency selection. `ci/tasks.py` owns component commands.
`ci/cli.py` owns bounded execution and explicit unexecuted results. Workflows
install pinned tools, start services, select runners and transfer artifacts.
Component runners own collection and assertions.

| Task | Checks |
| --- | --- |
| `policy` | Always required: skills, parsed workflow contracts and Python policies |
| `static` | Ruff lint and format for maintained Python, targeted mypy, compilation |
| `python` | Unit, contract and integration suites; two shards on Linux and Windows |
| `qt` | Qt/QML, DPI and retained GUI compatibility on both platforms; Windows contracts on Windows |
| `settings_unit` | Types and headless units; no controller or browser |
| `settings_browser` | Production build and boot, browser behavior, isolated Python bridge |
| `package` | Native Settings, inventory, Windows EXE, embedded payload, startup, update recovery |
| `installer` | Disposable Windows install, upgrade, repair, rollback and removal |
| `server` | PostgreSQL behavior, migrations, container startup and database health |
| `mobile` | Types, lint, contracts, locale/prompt synchronization, iOS JavaScript bundle |
| `ios` | Swift library, keyboard simulator, installed keyboard typing/activation, containing-app UI, unsigned app/extension build |
| `audit` | Locked Python and JavaScript dependency audits |

The full standard set includes every task except `installer`. An affected
installer change requires that task on its PR. Required native Windows and iOS
coverage stays in CI. Main requires every standard component, including
components not selected by PR CI.
Containing-app UI validation runs regular and compact iPhone profiles in separate
required matrix jobs with distinct evidence artifacts. Each keeps its 60-minute
budget and runs native text-input regressions; the iOS aggregate requires both
profiles, keyboard/library tests and the unsigned app build. Full local app
validation and default signed publication retain the two-profile run on one test build.

The explicit installed-keyboard fixture uses `xcodeproj` 1.27.0 and retains its
receipts, captures and logs. Ordinary required CI runs this same fixture after
native keyboard/library tests, including typing, opening/final height and two
fresh activation attempts. It permits the authorized internal manual return
below. This does not establish automatic-return or App Store acceptance.
The mobile CI job also runs Expo Doctor. Internal publication can reuse this
proof only from successful canonical main CI at its exact source SHA and run
attempt. Missing, failed or skipped installed coverage blocks reuse.
Strict installed typing and both automatic returns remain in default signed
publication and the default focused manual validation.

For an activation regression, the manual `ios-validation.yml` run accepts
`activation_only=true` with the exact reviewed `source_sha`. It runs the original
installed-keyboard fixture first, with a 20-minute job limit and required
evidence. The containing-app profiles, unsigned build and full iOS aggregate
are skipped in this focused mode. This result proves only the installed-keyboard
scenario. An explicitly authorized internal test can additionally select
`manual_return=true`: it accepts only the known `unknown` origin with a consumed
nonce, failed automatic return and visible container, then switches apps manually
for each of the two attempts. Its summary records incomplete keyboard acceptance.
The default remains strict; signing and package checks are unchanged.

Use the first failed step and its retained evidence to choose the repair. A
fixture assertion is a native acceptance failure; runner or tool setup is an
environment failure. Credential, archive and Apple upload failures require their
own signing or Apple evidence. Passing one layer does not clear another layer's
failure. An uncertain upload requires Apple reconciliation before another upload.

Python test modules have explicit suite ownership under `tests/`. Shared fakes
belong in `tests/support/`. Tests must not import another test-case module as a
fixture. The runner rejects unknown suites and unclassified tests. Preserve
behavior assertions when moving tests; file count does not prove coverage.

```sh
python scripts/run_tests.py --list-suites --json
python scripts/run_tests.py --suite unit --suite contract -v
python scripts/run_tests.py --suite qt -v
python scripts/run_tests.py
```

No arguments run all suites for the current platform. `--shard N/M` splits the
inventory without duplicate collection. Temporary profiles and removal of
provider credentials precede product imports. Qt uses the Basic style. Personal
keys, accounts, microphones and recordings are not test fixtures.

<a id="selected-checks"></a>
## Selection and terminal results

PR selection compares the tested merge with its base, including both paths of
renames. Unknown controls, invalid paths, symlinks and unavailable ranges request
full validation. A checkout that does not match the event SHA fails. Shared
inputs select all consumers. A locale change can avoid native iOS only when its
native catalog projection is unchanged and the inputs are regular Git blobs.
Uncertainty retains native checks.

`CI required` is the terminal aggregate. The planner and policy job must succeed.
Every selected job and every matrix row must succeed. Only unselected jobs can
be skipped. Missing or unexpected jobs, invalid flags, failures and cancellation
cannot produce a green aggregate. A cache hit is not a test result.

<a id="branch-protection-migration"></a>
Keep `CI required` as the required branch-protection check. Source changes do not
change live protection. Read it before merging or an authorized settings change.
The aggregate name is retained. Release verification authenticates the canonical
workflow, exact source SHA, successful attempt and aggregate, without a duplicate
hardcoded checklist of historical jobs.

<a id="local-validation"></a>
## Local execution and evidence

`--plan` needs Python and Git. For execution, activate the locked Python
environment and install the always-required policy tool dependencies:

```sh
cd ci
npm ci --ignore-scripts --no-fund
cd ..
```

Install the locked dependencies in `desktop/` or `mobile/` when those components
are selected. The component guides describe their platform setup. Then run:

```sh
python scripts/ci.py --plan
python scripts/ci.py
python scripts/ci.py --full
python scripts/ci.py --task settings_unit
python scripts/ci.py --task python --shard 1/2
```

The npm aliases are `ci:plan`, `ci` and `ci:full`. `--base` defaults to
`origin/main`. Local planning includes committed, staged, unstaged and untracked
paths from its merge base. Invalid references fail even with `--full`. The
command never fetches, installs dependencies or publishes.

JSON reports record each check, status and duration. `--timeout` limits the run;
`--check-timeout` limits each command. Defaults are 3600 and 1800 seconds.
Cancellation and timeout stop owned descendants. Missing tools and platform or
service requirements remain `unexecuted`. Exit 0 means passed, 1 means failed,
and 2 means selected gates remain open. A local Windows result cannot prove
Linux, PostgreSQL, Xcode or remote CI results.

Browser supervision supports Linux and Windows. Linux uses a standard-library
Python child subreaper; Windows uses a kill-on-close Job Object. Both include
detached browser and web-server sessions. Other local platforms report the
browser task as unexecuted. Headless Settings units do not need the Python supervisor.

Set `CLARIFY_TEST_DURATIONS_JSON` for Python timings and
`CLARIFY_TEST_DURATIONS_UNIT=test|file` for granularity. CI retains each lane's
reports through `CLARIFY_CI_DURATIONS_DIR`. Use measurements to balance shards.
Caches hold tool downloads and compiler output. Passing tests are not cached.
Qt screenshots use `CLARIFY_TEST_ARTIFACTS_DIR` and stay with CI evidence.
Without an explicit artifact path, tests use temporary output directories.
PR-only captures and diagnostic reports follow [file retention](agents/workflow.md#files-and-evidence).
Upload them as PR attachments or CI artifacts; do not commit them. The repository
policy check rejects tracked files in reserved evidence/runtime output directories.
It does not judge test value or block maintained product and documentation assets.

## Runners

GitHub runners are the default: Ubuntu 24.04, Windows 2025 and macOS 26. Node is
22.21.1 and Python is 3.12. Lockfiles and native toolchain files own dependency
versions. Destructive installer checks always use disposable GitHub Windows.

An organization repository can set `CI_RUNNER_PROVIDER=blacksmith` to route
eligible Linux jobs to `blacksmith-4vcpu-ubuntu-2404`. Invalid values fail. The
planner rejects Blacksmith on personal repositories. Clarify is currently under
a personal account, so this option is inactive. Install and verify the
organization integration before changing the variable. Xcode routing uses the
separate optional Bitrise setting above. Windows packaging
remains on GitHub runners. See [Blacksmith setup](https://docs.blacksmith.sh/introduction/quickstart)
and [runner images](https://docs.blacksmith.sh/blacksmith-runners/overview).

## Delivery and reference

Desktop candidates and public releases follow [release automation](release-automation.md).
TestFlight receives a signed production-identity candidate. Public App Store
handoff uses that same verified Apple build ID. Server delivery follows
[native Railway delivery](server-delivery.md).

[T3 Code CI](https://github.com/pingdotgg/t3code/blob/d2d1e4f50ef856f940d91858915368500657b0b7/.github/workflows/ci.yml)
is the reference for task ownership, PR selection, full main checks, separate
browser boot checks and sharding. Clarify keeps required Windows coverage and
direct Xcode builds for its Python/Qt and keyboard contracts. T3's EAS/OTA policy
does not prove Clarify's native extension compatibility.
