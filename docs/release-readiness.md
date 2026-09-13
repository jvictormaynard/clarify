# Release readiness and contributor map

This is a release checklist, not a claim of acceptance. Local code, a passing
test, a merged commit, and a published executable are different states. Record
the commit SHA, Windows version, DPI, and evidence for each release candidate.

## Local verification — 2026-09-13

Checked the working tree on `codex/settings-local`, not a release tag:

- Python discovery: 1,124 tests, no failures, 5 platform skips.
- Settings: all 12 Playwright tests passed; the dictionary test also passed
  after adding stable, animation-complete documentation screenshots.
- TypeScript/Vite and the Rust 1.94.0 release build passed on Windows.
- The configured Ruff checks, format gate, targeted mypy checks, PowerShell
  syntax, YAML parsing, local documentation links, and `git diff --check` passed.
- The production npm audit reported no vulnerabilities in the locked frontend
  dependencies. This does not certify the Python or Rust dependency graphs.
- Payload verification has matching, missing, and mismatched-input tests,
  including a real PyInstaller archive round trip.

Follow-up packaging checks on the same development tree:

- The full Windows portable build passed, including the embedded Settings hash
  and byte-for-byte inventory checks. The installed application was not replaced.
- The Settings inventory contains 42 npm packages and 259 Cargo crates, including
  build-only crates marked as excluded. All have collected license texts.
- The generated Settings SBOM passed CycloneDX 1.5 schema validation.

Remote Actions and clean-user Windows acceptance are still required before
publication. Local evidence does not replace those gates.

## Scope before publication

See the [publication review](release-review-2026-09-13.md) for the optional Qt
payload finding, corrective packaging policy, and still-open acceptance gates.

- [ ] Review the existing Settings, dictionary, hotkey, and deployment changes
  as focused groups. Do not stage an entire dirty worktree without review.
- [ ] Align the English and Portuguese README with the candidate. Keep
  unreleased work distinct from the latest download.
- [ ] Pass both Python CI runners and Windows packaging, including the Settings
  action and embedded-child hash check, on the exact candidate SHA.
- [ ] Resolve any dependency audit or test failure; do not hide it with skips.
- [x] Inventory the new bundled JavaScript and Rust dependencies and include
  their notices and SBOM coverage in the packaging and release workflows.
- [ ] Review Qt module, source-availability, and distribution obligations.
- [ ] Capture real app screenshots at normal and scaled DPI with an empty or
  synthetic profile. Do not publish personal paths, keys, or transcripts.
- [ ] Obtain Windows acceptance below before preparing a release tag.

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
