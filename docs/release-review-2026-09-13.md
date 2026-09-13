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

## Remaining publication gates

- Record the final package's Qt/PySide6 license texts, third-party notices,
  corresponding-source availability, and build/replacement instructions. The
  npm/Cargo inventory does not close this separate distribution review.
- Obtain explicit user acceptance of the final Windows package, especially
  first capture after idle, Hold/Escape, immediate restart after cancellation,
  focus/clipboard delivery, saved settings and installed local-ASR discovery.
- Complete clean-user and scaled-DPI checks from
  [release readiness](release-readiness.md), with synthetic profiles.
- Once approved, prepare the appropriate SemVer release, merge, and require
  green post-merge CI before tagging. The latest public release remains v0.3.0.
