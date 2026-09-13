# Publication review — 2026-09-13

## Decision

The product and cleanup baseline is approved for v0.4.0 community portable
release preparation. PR #96 and its post-merge CI passed, and the maintainer
authorized proceeding after reviewing the recorded test limitations. This
does not approve signed MSI/update rollout or certify legal compliance.
Publish only after the release-preparation PR, post-merge CI and tag workflow
pass. Verify the published assets before announcing availability.

## Evidence and correction

The PR candidate `b2f073c0879dccb692c417f0c2b6e68c743c9c4b` passed all jobs in
[PR CI](https://github.com/jvictormaynard/clarify/actions/runs/34728809064).
However, inspecting the local portable archive revealed optional Qt libraries,
including Graphs, Quick 3D and Virtual Keyboard. The default PyInstaller QML
hook collected installed QML plugins, not just the imports used by Clarify.

The [Qt licensing page](https://doc.qt.io/qt-6/licensing.html) lists those modules
under GPL-specific open-source terms, rather than the common LGPL option.
This finding does not change Clarify's source license or establish a legal
conclusion about a combined distribution. It means the existing high-level
PySide6 notice is insufficient evidence for approving that package.

The corrective build policy:

- installs `PySide6-Essentials` without the unused full `PySide6` metapackage or
  `PySide6-Addons`; the three platform/runtime locks retain the same Qt version;
- selects Clarify's QtQml and QtQuick modules before native dependency analysis;
- excludes unused QML-profiler plugins and modules not needed by Clarify;
- checks the final archive for restored optional QML modules and known unwanted
  Qt DLLs, regardless of the dependency that added them;
- loads hidden QML controls in the packaged smoke test without creating an app
  profile, registering hotkeys or opening a recorder.

The policy and archive checks are in `scripts/qt_package_policy.py`,
`scripts/pyinstaller-hooks/`, and `scripts/check_settings_payload.py`. They are
packaging controls, not a license-compliance certification. Do not infer that
passing this bounded check reviews every present or future Qt module.

## Source distribution follow-up

The cleaned candidate `28be3cf` passed local Windows packaging and 1,133 Python
tests (5 existing platform skips), plus all 12 Settings browser tests. Its
remote Windows tests passed. The remote Linux suite exited with a native
segmentation fault during Settings tests; that failure required investigation,
not a skip or an assumption that the Windows result approves the candidate.

The crash reproduced locally while repeatedly creating/closing Settings and
validating a fake provider. Faulthandler showed Qt signal emission concurrent
with garbage collection. Local-model callbacks retained old controllers in
cycles, including after switching the browsed product. The correction removes
old subscriptions and uses weak, generation-bound callbacks. A lifetime test
now checks that shutdown releases the controller. The previously crashing
scenario passed 100 repetitions on Linux after that correction. Final complete
suites and packaging still apply to the corrected commit, not the earlier one.

`scripts/qt_distribution.py` now prepares six checksummed, complete upstream
source archives and their conservative license/attribution collection. Both
portable build paths embed and verify `Clarify-qt-NOTICES.txt`; release tracks
include it in the ZIP and publish/attest `Clarify-qt-sources.zip` separately.
See [source and replacement instructions](qt-distribution.md). This closes the
missing source/notice artifact implementation, not legal certification or
acceptance of a final release package.

## Candidate verification and user acceptance

Candidate `df15100` passed 1,140 Python tests on each CI runner. Windows had
5 existing platform skips; Linux had 4. Its push workflow then found a
Settings picker race: reopening during the closing animation retained the
previous search and hid other installed models. The correction resets the
controlled search on opening. A regression keeps the closing popup mounted
and checks both selection/reopen and Escape/reopen; it failed before the fix.
The corrected frontend passed all 13 browser tests, 10 repeated reopen tests,
native WebView checks, and its own CI and packaging inspection. It was merged
as `926b305879dee078c912e07a6afa0b569934e335`; all jobs in
[post-merge CI](https://github.com/jvictormaynard/clarify/actions/runs/34733753038)
also passed. The merged tree was identical to the verified candidate.

The installed `df15100` runtime matched the locally validated portable build,
with the previous executable preserved in backup. On 2026-09-13, the user
confirmed preserved settings and local models, working recording, and an
immediate new recording after Escape. This is acceptance of those scenarios,
not of an untested subsequent package.

Native WebView checks also passed dictionary/save/navigation, title-bar scroll
isolation and window controls at normal scale and a forced WebView scale factor
of 1.5. The synthetic-profile screenshot was inspected. This is not a claim
that Windows system DPI or a clean Windows VM was tested.

## Release preparation and remaining limits

- The final baseline's downloaded CI package passed independent Settings/SBOM
  hash verification, Qt notice comparison, module policy and six source digests.
- The user accepted proceeding without a clean Windows machine/VM. No test was
  fabricated or marked passed for this gap. System DPI, fully offline ASR,
  broader cross-app acceptance and a custom Qt rebuild remain unverified; see
  [release readiness](release-readiness.md).
- v0.4.0 adds compatible Settings, dictionary and Hold functionality. Prepare
  it as a minor community release; do not merge dependency upgrades into it.
- Require green release-preparation PR and post-merge CI before creating the
  tag, then verify all published assets and provenance. Signed distribution
  remains gated separately by [Windows distribution](windows-distribution.md).
