# Publication review — 2026-09-13

## Decision

Not approved for publication yet. A green functional CI is necessary, but does
not establish license compliance or manual Windows product acceptance. Do not
create a release tag or treat earlier UI feedback as acceptance of a changed
portable package.

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
segmentation fault during Settings tests; that failure requires investigation,
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

## Remaining publication gates

- Pass the final candidate's Linux/Windows CI and inspect the generated Qt
  source/notice release artifacts. Verify the documented replacement route.
- Obtain explicit user acceptance of the final Windows package, especially
  first capture after idle, Hold/Escape, immediate restart after cancellation,
  focus/clipboard delivery, saved settings and installed local-ASR discovery.
- Complete clean-user and scaled-DPI checks from
  [release readiness](release-readiness.md), with synthetic profiles.
- Once approved, prepare the appropriate SemVer release, merge, and require
  green post-merge CI before tagging. The latest public release remains v0.3.0.
