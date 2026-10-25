# Release readiness and contributor map

This is a release checklist, not a claim of acceptance. Local code, a passing
test, a merged commit, and a published executable are different states. Record
the commit SHA, Windows version, DPI, and evidence for each release candidate.

## v0.11.0 preparation — 2026-10-25

[PR #159](https://github.com/jvictormaynard/clarify/pull/159) merged social
authentication and the current weekly-quota source at
`37d702ffd75f3f8ce74e55e8c760ec1cf629935a`. The release preparation also merges
the complete iOS source delivered in TestFlight 0.10.4 (37),
`d356ac94352b5c292d7879c1a85152e3b33481df`, to preserve its interface and audio
corrections. Planned versions are desktop 0.11.0 and iOS 0.11.0 (38).
PR #161 requires separate metadata-only preparation PRs for desktop and mobile.
This source integration keeps desktop metadata at 0.10.1 and the Expo identity
at the delivered 0.10.4 (37); it creates no release intent or tag.

The combined source passed 1,384 Python tests with four skips, all 222 PostgreSQL
server tests, 33 mobile JavaScript tests, mobile checks and the Settings build.
All 47 Settings browser cases passed across the full run and one focused retry
after a preparation timeout. The repaired candidate `467d9f9f42dadb1d8a0389121c26ecd6cd498018` also passed
macOS Swift contracts, UIKit integration and unsigned app/extension compilation.
Integration with PR #161 requires fresh CI on the combined source. The containing
app and installed-keyboard acceptance run in the TestFlight workflow.

Windows uses the community portable track. Verify all eight assets, downloaded
hashes, Ed25519 update metadata and GitHub provenance on the exact green source.
The executable is unsigned; SmartScreen warnings remain possible. Native Windows
provider completion/cancellation, physical iPhone and Bluetooth recording, and
live provider/SMTP acceptance require separate evidence. Automated fixtures do
not establish those interactions. iOS distribution is internal TestFlight only.

Production deployed PR #159 automatically and applied its migrations. The
cutover audit found no operations during migration, no running operations or
reservations, and equal historical and treasury processing costs. Health and
both public finance routes return 200. A pre-migration daily backup and a
separate post-migration verified backup exist. The reviewed OAuth referrer-policy
repair was deployed at `9c2cbf4f9f543bd9cd02dbe730686837387bfbc0`, deployment
`1317f2e5-037d-4bf6-bcde-907eea9b8943`. The final release must align production
with its merged main source.

Visible Windows Chrome, through MCP Playwright, completed real Google, Microsoft
and GitHub callbacks without a browser override. Confirmation POSTs returned
200 with the correct origin. All three tested identities returned the expected
existing-email collision, without a native session or a duplicate account.
Attempts were cancelled and their temporary tabs closed. The SMTP connection
opened successfully. These checks do not establish new-user signup, email-code
delivery or native client completion.

The release candidate also repairs late keyboard cancellation and microphone
activation during automatic account refresh. Their Swift and UIKit regression
tests passed on `467d9f9`; combined-source CI must confirm the integration. CSRF regression tests retain
origin validation and reject a literal null origin.

The owner confirmed the current USD 10 contribution. Production records that
receipt, a USD 0.97 provision for observed Railway usage, and USD 1.003217337 of
historical processing. Uncommitted cash is USD 8.026782663. The receipt releases
over one calendar month; historical costs exceed this week's released slice, so
no quota is available before the 2026-10-26 00:00 UTC reset. Distribution retains
the 80 percent regular and 20 percent newcomer split. Future receipts are not
booked in advance. A provision is not evidence of a paid invoice.

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
| Vocabulary | `dictionary_snippets.py`, `desktop/src/pages/dictionary-page.tsx` | A validation or context-limit case with ASR/refinement coverage |
| Desktop behavior | `clarify/desktop/`, `windows_hotkeys.py` | A focused state-transition fix with Windows acceptance |
| Build and security | `scripts/`, `.github/`, `distribution/` | A reproducibility or artifact-content check, without changing trust policy |

## Backlog reconciliation

Before closing an old issue, compare its full acceptance criteria with the
candidate, not just its title. Add the implementation SHA and remaining manual
gates to the issue. In particular, reconcile audio import, history, microphone
controls, configurable shortcuts, Qt migration, local ASR, secret storage, and
signed distribution separately. Partial implementation does not close an issue.
This file does not change public issues or assign contributor work.
