# Release readiness and contributor map

Source changes, automated tests, a packaged candidate and a published download
are separate states. The version in `version.py` can be newer than the
[latest Windows release](https://github.com/jvictormaynard/clarify/releases/latest).
This guide defines acceptance work; it does not declare a candidate accepted.

## Use the existing release owners

Use [CI delivery](ci-delivery.md) for automated checks and
[release automation](release-automation.md) for preparation, immutable candidate
creation, acceptance and publication. Test the exact packaged executable;
source tests alone do not establish Windows acceptance. Preview candidates do
not affect the stable updater. Stable publication is a separate action.

The default desktop presentation is Electron. Qt owns the engine, native input
and recovery views. WebView2 is relevant only to the legacy Tauri alternative.
The community portable updater authenticates Ed25519 metadata; the separate MSI
and Authenticode channel remain staged under [Windows distribution](windows-distribution.md).

## Record evidence per candidate

Record the candidate run/artifact identity and digest, source commit, executable
SHA-256, installed version before upgrade, Windows build, DPI, microphone and
processing mode. Use synthetic phrases and a disposable profile or test account.
Keep credentials, personal transcripts and recordings out of reports and captures.

For each applicable scenario record **passed**, **failed** or **not run**, with
expected/observed behavior and an evidence link. Explain a not-run scenario;
a mocked result does not replace physical acceptance. Record elapsed time from
stop to result for live processing and cold/warm startup separately. Compare
the same phrase, hardware, provider and model for performance investigations.

Attach evidence to the candidate report defined by release automation. Keep
its existing acceptance block/schema unchanged. CI receipts and old reports
do not establish acceptance of a new artifact. Historical source acceptance is
available in [PR #96](https://github.com/jvictormaynard/clarify/pull/96) and
[PR #159](https://github.com/jvictormaynard/clarify/pull/159); those records do not
describe current desktop or iOS availability.

## Windows product acceptance

| Scenario and steps | Required result |
| --- | --- |
| Clean Windows user: launch without Python, Node or Rust installed | Onboarding and Settings open; the default Electron shell does not require WebView2 |
| First and second launch: open from Explorer/shortcut, then open again while hidden and while recording | One logical instance; the workspace is recoverable; capture is not interrupted |
| Tray and visibility: minimize, close, restore, use the configured visibility shortcut, then Quit | Expected visible results; Quit leaves no recorder or personal listener running |
| Upgrade from the previous published version with a disposable populated profile | Routes, encrypted keys, dictionary, snippets, history, shortcuts and model choices remain available |
| Update while recording, editing Settings or holding an unsaved result; finish/save/discard and close Settings | No forced loss of work; the waiting state is explained; restart reports the candidate version |
| Update recovery using the existing disposable update fixture | Invalid downloads are rejected; failed startup restores the previous executable; retry works |
| First dictation after idle, then an immediate second dictation | Accurate capture readiness; one result or an actionable error for each operation |
| Portuguese dictation: repeat a synthetic phrase with names, technical terms, dates and numbers, in quiet and with noise | Compare with a reference; review meaning, negation, names and numbers separately from recognition scores |
| Microphones: switch input, disconnect, reconnect and retry | A specific error or recovery path; no stuck capture |
| Toggle and Hold: stop/release, cancel with Escape while held, release after cancellation and start again | No late audio submission after cancellation; the next recording works |
| Dictionary and snippets: create, edit, disable, discard, save and restart | Persistence and enabled substitutions use the selected route; standalone snippets retain exact saved text |
| Dictation, rewrite and translation in Notepad, Word and a browser field; repeat while changing focus | Paste once into the intended app; unsafe paste retains recoverable text without overwriting another app |
| Settings at 100% and scaled DPI, a short window and keyboard-only navigation | Reachable controls, scrolling, draft confirmation, focus return and close |
| Existing user launch from Explorer and development tools | The intended data profile is used; source experiments use isolated profiles |

A PyInstaller launcher and child are one logical instance. Test upgrade and
rollback on disposable profiles; an executable backup does not reverse a data
migration. Preserve recoverable audio and active-work gates during acceptance.

## Processing and device acceptance

Run each relevant mode separately. Fake-provider tests protect orchestration;
they do not measure recognition quality or prove live authentication.

| Mode | Acceptance owner and evidence |
| --- | --- |
| Personal cloud key | Use a test key and synthetic audio/text. Check success, cancellation, invalid key, quota/rate-limit handling and connection failure without recording request bodies. Record provider/model and observed error; do not exhaust a paid quota |
| Clarify account | Use a test account. Verify sign-in/sign-out, allowance display, processing and offline sync/retry without duplicate history or cross-account data |
| Local Whisper | Execute [Local ASR acceptance](local-asr-acceptance.md): verified model, externally blocked network, cloud refinement off, cleanup and measured benchmark. Harness output alone does not prove blocked network |
| Paired iPhone | Follow [computer connection](computer-connection.md) and [physical iOS acceptance](../mobile/README.md). Verify pairing, revocation, reconnect and processing on the intended computer |
| iOS keyboard | Use the existing [iOS validation and release procedures](../mobile/README.md). Installed keyboard, microphone activation and return-to-app require native/device evidence |

Resolve failed cases before stable publication. Keep unavailable device,
provider and clean-machine checks explicit for the maintainer. Testing does not
publish a version or change quotas and production settings.


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
