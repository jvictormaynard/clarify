# Release readiness and contributor map

This is a release checklist, not a claim of acceptance. Local code, a passing
test, a merged commit, and a published executable are different states. Record
the commit SHA, Windows version, DPI, and evidence for each release candidate.

## Verified baseline for v0.4.0 — 2026-09-13

Production changes were merged through [PR #96](https://github.com/jvictormaynard/clarify/pull/96)
at `926b305879dee078c912e07a6afa0b569934e335`. Its
[post-merge CI](https://github.com/jvictormaynard/clarify/actions/runs/34733753038)
passed Linux and Windows tests and Windows packaging. A release-metadata
preparation still needs its own PR, post-merge and tag checks.

- Python suite: 1,140 tests per OS, with 4 existing Linux and 5 Windows skips.
- All 13 Settings browser tests passed; the rapid picker-reopen regression
  also passed 10 repeated local runs. The native-crash reproduction passed
  100 repetitions after the callback-lifetime correction.
- TypeScript/Vite, locked Rust 1.94.0, configured lint/format/types, dependency
  audits, packaged QML loading and embedded Settings/inventory checks passed.
- The downloaded PR artifact passed independent Settings/SBOM hash checks,
  Qt notice equality, unwanted-module policy and all six upstream source hashes.
- Settings inventory includes 42 npm packages and 259 Cargo crates with license
  texts; build-only crates are marked excluded. Its CycloneDX schema was checked.
- Hosted Windows CI passed install, upgrade, repair, rollback and uninstall.
  This is not a signed-installer or clean-user desktop acceptance claim.
- The local portable build was installed with backup. The user confirmed
  preserved settings/models, working recording and immediate restart after Esc.
  The subsequent picker fix passed native WebView tests and was installed too.
- Native checks covered dictionary/save/navigation, scroll isolation, window
  controls and clean close. Synthetic screenshots were inspected at normal
  WebView scale and forced factor 1.5, not at changed Windows system DPI.

The maintainer has no clean Windows machine/VM and accepted proceeding with
that limitation. Clean-user/WebView2-absence tests, actual Windows-scaled DPI,
network-blocked local ASR, broader cross-app focus tests and a full custom Qt
rebuild remain unverified. Do not turn these gaps into passed checklist items.
Settings localization beyond Portuguese and backlog/dependency triage are
separate follow-up work, not additions to this release.

## Scope before publication

See the [publication review](release-review-2026-09-13.md) for the optional Qt
payload finding, corrective packaging policy, and still-open acceptance gates.

- [x] Review and integrate the product/cleanup changes in PR #96.
- [x] Align English and Portuguese documentation with the v0.4.0 scope.
- [x] Resolve the native callback and picker-reopen failures without skips.
- [x] Inventory the new bundled JavaScript and Rust dependencies and include
  their notices and SBOM coverage in the packaging and release workflows.
- [x] Remove unwanted Qt modules and supply pinned sources and notices;
  document replacement instructions without claiming legal certification.
- [x] Record available manual/native acceptance and the untested scenarios.
- [ ] Pass release-preparation PR and post-merge CI on the exact release SHA.
- [ ] Verify tag workflow, published files, checksums, source archives and
  provenance before announcing the download. Record final evidence in the
  release-preparation PR and release notes.

## Windows product acceptance

| Scenario | Required result |
| --- | --- |
| Clean Windows user | Settings starts without Python/Node/Rust installed; verify WebView2 availability and the behavior when it is absent |
| Existing user upgrade | Provider routes, encrypted keys, dictionary, and installed CPU/GPU models remain available |
| Launch from Explorer and development tools | The installed app uses the intended physical data profile, not an MSIX virtual profile |
| First recording after idle | Loading lasts until capture is active; audio produces a result or a specific actionable error |
| Toggle and Hold | Stop/release works; Escape cancels while held; releasing a cancelled shortcut does not submit audio |
| Immediate next recording | Cancellation notice and Undo do not block new shortcuts or leave a recorder running |
| Dictionary | Add, edit, disable, delete, save, discard, and restart work; enabled terms reach the correct ASR/refinement route |
| Offline local ASR | A verified installed model transcribes with network blocked and cloud refinement off |
| Focus and clipboard | Test at least three target apps; unsafe paste leaves text available without an automatic result window |
| Settings layout | Title bar stays fixed, only content scrolls; floating save bar, keyboard focus, and close confirmation work at 100% and scaled DPI |
| Shutdown and update | No live recorder or local server is left behind; do not delete recoverable user audio to make a check pass |

Unsigned portable releases and signed MSI/update releases have different gates.
Do not enable MSI or authenticated updates without the acceptance in
[Windows distribution](windows-distribution.md). Do not publish or replace assets
as a side effect of local build validation.

## Contributor entry points

| Area | Start here | Small, reviewable contribution |
| --- | --- | --- |
| Settings UX | `desktop/src/`, `desktop/tests/` | A keyboard or layout regression with a failing test and a real screenshot |
| Localization | React labels and QML catalogs | Inventory missing React translations before claiming full locale support |
| Dictation | `provider_types.py`, `provider_adapters.py`, `local_asr.py` | A bounded provider contract test using synthetic input |
| Vocabulary | `dictionary_snippets.py`, `desktop/src/dictionary.tsx` | A validation or context-limit case with ASR/refinement coverage |
| Desktop behavior | `clarify/desktop/`, `windows_hotkeys.py` | A focused state-transition fix with Windows acceptance |
| Build and security | `scripts/`, `.github/`, `distribution/` | A reproducibility or artifact-content check, without changing trust policy |

## Backlog reconciliation

Before closing an old issue, compare its full acceptance criteria with the
candidate, not just its title. Add the implementation SHA and remaining manual
gates to the issue. In particular, reconcile audio import, history, microphone
controls, configurable shortcuts, Qt migration, local ASR, secret storage, and
signed distribution separately. Partial implementation does not close an issue.
This file does not change public issues or assign contributor work.
