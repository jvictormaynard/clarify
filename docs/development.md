# Development

## Requirements

- Python 3.11 or newer
- Windows 10 or 11 for full product behavior
- A microphone for end-to-end recording checks
- An API key only for live cloud-provider checks
- Git, if cloning instead of downloading a source archive

Settings browser development needs Node.js 22 and the locked Python environment.
The Windows desktop shell uses the pinned Electron runtime. End users do not
need frontend build tools.

## Windows setup

```powershell
git clone https://github.com/jvictormaynard/clarify.git
cd clarify
.\scripts\setup.ps1 -Dev
.\scripts\build-desktop.ps1
$env:CLARIFY_DESKTOP_EXECUTABLE = (Resolve-Path ".\dist\desktop-shell\Clarify Desktop.exe").Path
.\.venv\Scripts\python.exe clarify\desktop\qml_app.py
```

The setup script creates `.venv` and installs runtime dependencies. `-Dev` also
installs the pinned development and packaging tools for local checks. Both modes
consume the platform-specific `requirements-lock-linux.txt` or
`requirements-lock-windows.txt`, generated from the human-maintained
`requirements.txt` and `requirements-dev.txt` intent files. Generate each lock
on its matching runner only when intentionally changing dependency intent. In
particular, compile the Windows lock on Windows so PyInstaller's `colorama`,
`pefile`, and `pywin32-ctypes` markers are resolved and Linux-only `keyboard`
is omitted:

```text
python -m piptools compile --allow-unsafe --strip-extras --output-file=requirements-lock-linux.txt requirements-dev.txt
python -m piptools compile --allow-unsafe --strip-extras --output-file=requirements-lock-windows.txt requirements-dev.txt
python -m piptools compile --strip-extras --output-file=requirements-lock-runtime-windows.txt requirements.txt
```

Do not edit any lock file by hand. Each CI runner checks its corresponding
file in a temporary path, so Linux and Windows platform markers are not
silently treated as interchangeable.

The `requirements-lock-windows.txt` file includes the development and packaging
toolchain used to build and validate the executable. The separate
`requirements-lock-runtime-windows.txt` file is compiled only from
`requirements.txt`; it contains the runtime dependency graph and is the sole
input to the Python portion of the release SBOM. The Settings build generates
its npm and Electron inventory separately, then release workflows merge both;
see [Release readiness](release-readiness.md). Keeping these locks separate prevents Ruff, mypy,
pip-audit, pip-tools, CycloneDX, and PyInstaller from being reported as shipped
application components while retaining pinned, reproducible build inputs.
Development locks are compiled with `--allow-unsafe`, so their exact
`pip==26.2.1`, `setuptools==84.2.1`, and `pip-tools==7.6.1` versions are
committed and installed before the rest of the toolchain. This pip release is
compatible with pip-tools and includes fixes for the audited pip advisories.
The runtime-only lock intentionally excludes those bootstrap tools.
The release checks that every shared runtime package has the same version in
both Windows locks before building or generating the SBOM.

Runtime Qt uses `PySide6-Essentials`, not the full `PySide6`/Addons distribution.
Use a clean build environment after removing dependencies: `pip install` does
not remove packages left from an older lock. The portable archive check rejects
unused Qt modules that can otherwise be collected from that environment.

Environment variables are optional because provider settings can be entered in
the UI. For local automation, copy `.env.example` to `.env` and fill only the
values you need. API-key environment variables override stored credentials for
that process and are never persisted. Never commit `.env`.

Windows uses current-user DPAPI for provider keys. On macOS and Linux, Clarify
stores keys in `~/.clarify/secrets.json` with owner-only permissions. The file
contains plaintext. Tests inject an in-memory store or use temporary
directories and never access the developer's credential store.

## macOS setup

Use macOS 13 or later. Install Python 3.12 and Node.js 22.12 or later.
Run these commands from the repository root.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock-macos.txt
./scripts/build-macos.sh
open dist/macos/Clarify.app
```

The build makes a local app bundle for the Mac's architecture. The menu bar icon
opens Settings and quits Clarify. Use a Clarify account or configure a supported
cloud provider. The bundled Local Whisper installer, launch at login, and desktop
updates are available on Windows. On macOS, audio-file import uses the system's
codecs. WavPack requires conversion before import.

Allow microphone access when macOS asks during the first recording. To paste
into another app or use actions on selected text, enable **Clarify** in
**System Settings → Privacy & Security → Accessibility**. When Clarify cannot
verify the paste target, use the result or paste it manually. Local builds use
an ad hoc signature. If access stops after a rebuild, remove the old app from
Accessibility, add the new app, and reopen it. Check Microphone access again
before recording.

New Mac profiles use Fn for dictation. Hold Fn to speak and release it to
finish. The defaults for voice translation and expanding or collapsing the
pill are Control+Shift+V and Control+Shift+R. Open **Shortcuts**
in Settings to change the bindings. Press and release a chord made of only
modifier keys to capture it, for example Fn, Fn+Option, or Control+Option.
Dictation setup requires Microphone access before the practice test. Accessibility
is optional and enables automatic paste. The shortcut test listens for the
chosen shortcut without recording.
If the shortcut is unavailable, allow Clarify in Accessibility or Input
Monitoring in System Settings.
If the Globe key opens a macOS feature when you use Fn alone, set **Press 🌐
key to** to **Do Nothing** under **System Settings → Keyboard**.

For a source run, build the Electron shell with `npm --prefix desktop ci` and
`npm --prefix desktop run build:electron`, then run
`.venv/bin/python clarify/desktop/qml_app.py`. Set `CLARIFY_DATA_DIR` to an
absolute path to use a separate profile for testing. Use a fake provider and audio
fixtures. To update the macOS dependency lock, run
`.venv/bin/python -m piptools compile --allow-unsafe --strip-extras --output-file=requirements-lock-macos.txt requirements-macos.txt`
on macOS. For the runtime-only lock, run the same command with
`requirements-runtime-macos.txt`, `requirements-lock-runtime-macos.txt`, and
without `--allow-unsafe`. The macOS release SBOM uses the runtime-only lock and
the packaged Electron inventory.

## Settings development

See [CONTRIBUTING](../CONTRIBUTING.md#checks-for-your-change) for the exact npm,
Playwright, and Electron checks. `npm run build` in `desktop/` runs TypeScript
validation with TypeScript 7 before Vite 8. `npm ci` uses the committed
dependency lock. `npm run dev` starts Vite; controller access still requires
the Python process or the isolated test fixture.
`tests/web_settings_fixture.py` uses temporary repositories and fake devices.
Browser tests exercise the real React interface through an Electron-shaped test
transport. Native package smoke tests use the real Electron host and private
Python pipes. The Electron executable is required; no legacy UI is activated
when it is missing or fails.

## Checks

Run the same core checks used in CI:

```powershell
.\.venv\Scripts\python.exe scripts/run_tests.py -v
.\.venv\Scripts\python.exe scripts/ci.py --task static
```

From Linux or WSL with the dependencies installed:

```bash
python3 scripts/run_tests.py -v
python3 scripts/ci.py --task static
```

Use the configured interpreter from the locked environment. `scripts/run_tests.py`
creates a temporary process profile before discovery, removes inherited provider
credentials and sets `CLARIFY_SKIP_DOTENV=1`. It accepts the same arguments as
`unittest`; no arguments run full discovery. For a focused Windows check:

```powershell
.\.venv\Scripts\python.exe scripts/run_tests.py --suite windows -v
```

Standalone isolated fixture commands retain their own setup.

Choose local checks by the affected contract. A Settings-only design change
needs the shared `settings_unit` and `settings_browser` tasks, without Rust or
an EXE build. Documentation needs repository checks. Python behavior needs the
Python suite. Native integration and release candidates still need Windows acceptance.
See [CI selection](ci-delivery.md) and [Contributing](../CONTRIBUTING.md).

Repository-specific tests live in `tests/unit/test_repositories.py` and
`tests/compatibility/test_workflow_config.py` and `tests/contract/test_workflow_config.py`. They cover legacy file loading, the ordered
flat-to-workflow migration, independent routes, canonical model IDs,
capability/custom-endpoint validation, future/unknown fields, atomic writes,
and rollback when a secret backend cannot be verified. The backend contract and
corrupted-entry handling are covered in `tests/compatibility/test_secret_store.py` and `tests/integration/test_secret_store.py` and `tests/windows/test_secret_store.py`.

Workflow settings are persisted below the `workflows` key in `config.json`:

```json
{
  "workflows": {
    "translation": {
      "provider_id": "groq",
      "model_id": "llama-3.3-70b-versatile",
      "prompt": "Translate literally.",
      "custom_endpoint": "",
      "enabled": true
    }
  }
}
```

Use `LocalConfigRepository.apply(...)` to validate and commit a candidate as a
single transaction. `repository.test_workflow(scope)` performs a local
capability check only; it does not send text or prompts. `reset_workflow(scope)`
restores the provider's canonical default model and prompt for that scope.
Provider API keys remain resolved through the secure `SecretStore` and are not
part of a workflow route or its diagnostics.

After a Windows package is built, the executable can validate its actual
credential backend without touching the developer profile:

```powershell
.\dist\Clarify.exe secret-store-self-test
```

The command writes non-production markers to a temporary directory through the
same `LocalConfigRepository` used by the UI, creates a fresh repository/store
instance to verify restart reads, constructs the provider connections used by
the adapters, and then deletes every entry. It also verifies that neither the
marker values nor `gemini_api_key`, `openai_api_key`, or `groq_api_key` are
present in the temporary `config.json`. It prints only safe booleans, a success
flag, and provider names when stdout is available.
Because the release executable is a `--windowed` PyInstaller package, CI uses
`secret-store-self-test --result-file <runner-temp-file>` and validates that
file plus the exit code. A non-zero exit means the packaged backend is
unavailable or failed its config-isolation, read-back, provider-use, or
delete checks.

### Manual provider-key acceptance

The packaged self-test is the automated acceptance gate for the storage
boundary. It does not prove that the Settings UI, a real Windows restart, or a
provider request can use a key. Record those remaining checks only with
revocable, non-production credentials in a disposable Windows account or VM;
never use a personal production key and never run this procedure against an
existing Clarify profile.

Use a temporary profile for the complete manual pass:

```powershell
$dataRoot = Join-Path ([IO.Path]::GetTempPath()) ("clarify-secret-accept-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $dataRoot | Out-Null
$env:APPDATA = $dataRoot
& .\dist\Clarify.exe
```

For each of Gemini, OpenAI, and Groq:

1. In **Models → Providers**, enter a revocable test key and validate/save it
   (use the provider's documented test endpoint or a local provider-compatible
   fixture when available).
2. Before closing the app, copy the path shown below and confirm that
   `config.json` contains no provider key field and no test-key text:

   ```powershell
   $profile = Join-Path $dataRoot "Clarify"
   $config = Get-Content (Join-Path $profile "config.json") -Raw
   if ($config -match 'gemini_api_key|openai_api_key|groq_api_key') {
       throw "A provider key field was written to config.json"
   }
   ```

3. Close Clarify completely, launch the same executable again with the
   same `$env:APPDATA`, and confirm that the provider remains active and can
   complete one harmless validation/request. The masked key field may remain
   blank by design; do not overwrite it with a blank value.
4. Deactivate/clear the provider, repeat for all three providers, close the
   app, and verify that the secure store is gone or contains no entries. Keep
   the `config.json` assertion from step 2 after each clear.
5. Save the exit code, executable SHA-256, Windows version, provider names, and
   redacted screenshots/logs as evidence. Do not attach key values, request
   headers, or the DPAPI container.

Delete the disposable `$dataRoot` after the evidence is captured. This manual
matrix is still required before closing security issue #14 because CI cannot
provide the real-user UI/restart/request evidence.

Headless orchestration tests live in `tests/compatibility/test_workflows.py` and `tests/contract/test_workflows.py`. They exercise
dictation, rewrite, translation, overlap prevention, focus-safe target capture,
publication ordering, shutdown cancellation, and stale-worker rejection without
constructing Tk widgets. A small app-level harness also verifies Escape cannot
reset the UI while a terminal publication is blocked.

The dedicated voice-translation contract is covered by
`tests/contract/test_voice_translation.py`; its recording bridge is covered by
`tests/contract/test_voice_translation_runtime.py`. These tests use fake provider,
clipboard, recording, and monotonic-clock seams to verify language/config
round trips, capability validation, the state sequence, raw-transcript
fallback, copy-only focus and clipboard decisions, cancellation/publication
races, shared publication overlap serialization, and stale-worker operation-ID
rejection. The packaged Alt+V path, restart persistence through the real UI,
and three-application Windows matrix remain manual release acceptance gates.

## Build

```powershell
.\build.bat
```

or:

```powershell
.\scripts\build.ps1
```

The build first packages `dist\desktop-shell`, then embeds the complete shell
into `dist\Clarify.exe`. Pass `-DesktopShellDirectory` to reuse a shell from the
same source revision. Its manifest binds every renderer and native runtime file;
missing or different files fail verification. Keep the generated
`Clarify-settings.sbom.json` and `Clarify-settings-NOTICES.txt` in the parent
output directory. Both are produced by `scripts/settings_inventory.py`.
Local `.env`
files are deliberately excluded from every build.

## Windows acceptance checklist

For changes that affect UI, hotkeys, audio, clipboard behavior, system tray, or
packaging, unit tests are necessary but not sufficient. Verify the built
executable on Windows:

1. Launch `dist\Clarify.exe` and confirm only one logical app instance is
   active. A one-file PyInstaller build may show a launcher and child process.
2. Check the floating bar and menu at 100% and one scaled DPI setting if
   available.
3. Exercise every shortcut touched by the change.
4. Confirm the original application keeps focus through recording or selection.
5. Test the system tray, minimize, restore, and quit paths.
6. For clipboard changes, verify plain text, HTML/RTF, image data, rapid
   repeated hotkeys, a user clipboard write during the restore delay, failed
   paste, and focus change. The generated result must remain available when
   automatic paste is unsafe.
7. Attach before and after screenshots to visual pull requests.
8. Confirm that the executable contains no `.env` or personal key.

### Hotkey configuration acceptance

The persisted `hotkeys` object keeps the original Alt+L/Alt+K/Alt+T/Alt+R
bindings when upgrading a legacy `config.json`. Settings capture validates
modifier/key support and rejects duplicates before applying them. The native
Windows registration is transactional: if another application owns one
combination, all newly accepted IDs are unregistered and the previous set is
restored. Confirm this manually from a packaged build by reserving one test
combination in another application, attempting Apply, and checking that the
other three Clarify actions still use their previous bindings.

Recording defaults to toggle mode. Windows also supports Hold: key down starts
capture and key release finishes it. Check `Esc` while still holding the shortcut,
release after cancellation, immediate restart, and release during microphone
startup. The pill microphone remains a click-to-toggle control in either mode.

## Maintainer deploy from WSL

```bash
npm run deploy -- -ProfilePath 'C:\Users\you\AppData\Roaming\Clarify' -ProfileBackupRoot 'C:\Users\you\ClarifyBackups' -ExclusiveProfileAccess
```

This invokes `scripts/deploy.ps1` with Windows PowerShell, stages source files on
the native Windows temporary directory, builds, verifies a private profile backup,
backs up the installed executable, replaces it, and restarts Clarify. Override the discovered
target with `CLARIFY_INSTALL_PATH` when needed.
Use the installed app's physical profile (`CLARIFY_DATA_DIR`, otherwise
`%APPDATA%\Clarify`), accounting for MSIX redirection. The existing backup directory
must be outside profile, source, installation and build trees.
`-ExclusiveProfileAccess` confirms that all other writers are stopped and cannot
restart during deployment; it is not an application lock. Known process identities
are checked before shutdown. Backup failure prevents replacement/restart.

The private backup includes hidden files, SQLite sidecars and experimental audio.
Only attempts with `manifest.json` passed inventory/hash verification. Backups
preserve file bytes and modification times, not original ACLs or alternate streams.
Retention is unchanged. Keep backups local/private; verify hashes and stop all
writers before a separate restore. Links, reparse points and overlapping trees fail.
The script builds Electron unless `-DesktopShellDirectory` is supplied.
Use `-BuildOnly` to validate a complete portable package without stopping,
replacing, or launching the installed app.
It refuses to replace an app with an active SoX recording and launches through
Explorer so the app does not inherit an MSIX development host's virtual profile.
Check configuration and model discovery after launch, not just the process ID.

For a WSL checkout, use a native Windows checkout for Windows Node/Playwright
checks. Keep
`CLARIFY_TEST_FIXTURE` pointed at the repository fixture and use the Windows
Python interpreter. Do not share a Linux `node_modules` install with Windows.
If mypy reports a locked SQLite cache over UNC, use `--cache-dir` with a fresh
directory under the Windows temporary directory; do not change the type rules.

## Automatic Python formatting before commits

Install the repository hook once in each clone:

```bash
npm run setup-hooks
```

The hook runs `ruff format` on staged Python files and stages the formatted
result automatically. It refuses to change a file that also has unstaged
edits, so unrelated work is not added to the commit. `npm run setup` also
installs the hook on Windows. CI keeps the format check as the final guard.

## Automated quality and supply-chain checks

PR CI selects checks from the complete change range. Every main push runs the
full standard set. Scheduled and manual CI add extended checks. `CI required`
validates the
selected jobs, including failures, cancellation and incorrect skips. See
[CI selection and branch protection](ci-delivery.md) for the current policy.

Python changes select Linux and Windows tests, lint, types and compile checks.
Settings design changes select the frontend build and isolated browser tests,
without Rust or a portable EXE. Native, dependency and packaging inputs select
the corresponding build. MSI checks apply to installer inputs or a full manual
run. The shared Settings action can run browser checks separately from its
native build and inventory. Browser success does not establish Electron native focus or
native window acceptance. Desktop dependency audits run for their changed
inputs, daily, and before Desktop publication.

`scripts/dependency_audit.py` audits the locked Python set with `pip-audit`.
`scripts/javascript_dependency_audit.py` runs npm audit, including development
dependencies, and blocks unapproved high and critical advisories. Both use
`dependency-audit.json` for reviewed exceptions. Each JavaScript exception is
limited to an advisory, package, component, locked versions and UTC expiry.
Expired exceptions fail the gate, including dependent package findings.
Any exception requires a maintainer-approved rationale and must be removed as
soon as the dependency can be upgraded. Registry errors and incomplete advisory
graphs fail the audit; an exception does not disable the audit command.

Tagged releases also publish `Clarify.sbom.json` (CycloneDX) from the
runtime-only `requirements-lock-runtime-windows.txt` lock, include it in the
portable ZIP. The SBOM is augmented with the bundled SoX 14.4.2 component and
the SHA-256 of every `sox.exe`/DLL selected by
`scripts/sox-runtime-manifest.json`; the source-archive SHA-256 remains source
offer evidence only. The same manifest drives `scripts/build.ps1` before GitHub
artifact attestations are created for the release files.
The release workflow merges the Settings SBOM into that inventory and includes
`Clarify-settings-NOTICES.txt` in the ZIP. Settings license supplements are
version-specific, source-linked, and hash-verified in `desktop/licenses/`.
Each selected DLL is represented as its own CycloneDX library component with a
bundle-scoped version, SPDX license, SHA-256, and a dependency edge from the
SoX aggregate component. This avoids attributing the source archive digest to
the executable or hiding codec/runtime libraries in a generic property.
The attestation is verifiable with GitHub's artifact-attestation tooling and is
separate from the existing SHA-256 checksum.

## Experimental Linux support

The legacy Linux source app requires SoX, `xclip`, `xdotool`, Tk, PortAudio,
and permissions for global keyboard events. Wayland global shortcuts and paste
automation are unsupported.

## Desktop presentation and engine

React/Electron owns desktop windows, the pill, menus and Settings. The Python/Qt
composition root is `clarify/desktop/qml_app.py`; Qt remains responsible for
capture, hotkeys and the shared controllers. Only native audio-file import uses
QML in `AudioFilesWindow.qml`. There is no second pill or Settings renderer.

The Electron host restarts after a crash or failed startup handshake with a
bounded budget. Exhaustion shows a minimal native Retry/Close dialog. Native
Windows acceptance must verify focus, hit testing, shortcuts and clipboard
behavior against the packaged Electron executable; browser captures alone do
not prove those properties.

## Release process

The repository-local `$clarify-release` skill under
`.agents/skills/clarify-release/` is the canonical maintainer procedure.
It standardizes the release PR, CI gates, tag provenance, assets, checksums, and
post-release verification.

The signed installer/update contract, Azure OIDC configuration, manual
acceptance matrix, rotation, and revocation procedure are documented in
[Windows distribution and update security](windows-distribution.md). The
desktop release workflow is the no-cost path: it publishes only an unsigned
portable EXE, checksum, SBOM, ZIP, SoX and Qt/PySide source archives, and provenance.
From v0.5.0 it also publishes Ed25519 portable update metadata using the
protected `portable-updates` environment. Do not publish an MSI or Authenticode
CAB manifest until every signed MSI rollout gate there is complete.

For a local unsigned packaging check, run `npm run build` followed by
`npm run installer`. This creates `dist\Clarify-windows-x64.msi`; it does
not install it. The build requires a .NET SDK because
`scripts/build-installer.ps1` installs pinned WiX 6.0.2 under ignored
`build\tools`.

1. Choose the next semantic version from the changes since the latest tag.
   Complete Windows manual acceptance for the exact current main base and record
   its evidence.
2. Follow [client release automation](release-automation.md) to create a dedicated
   draft preparation PR. It sets `version.py` and root `package.json` to the same
   value, updates `CHANGELOG.md` and records the release intent. Preparation needs
   a separate CI-capable token.
3. Check out the prepared source in a dedicated worktree. Review the changelog
   and documentation whose behavior changed. Run local checks and preflight:

   ```bash
   python3 .agents/skills/clarify-release/scripts/release_preflight.py \
     --repo . --version X.Y.Z --channel stable
   ```

4. Review the metadata, scope and Windows evidence. Merge the preparation PR only
   after all PR checks pass. No second-person approval is required.
5. With promotion enabled, successful post-merge CI creates an immutable tag on
   that exact current main commit and explicitly dispatches Desktop Release.
   See [promotion activation](release-automation.md#activation) for the desktop
   setting.
6. Desktop Release builds the unsigned portable EXE, runtime-lock CycloneDX
   SBOM, checksum, ZIP, SoX and Qt/PySide source archives, and provenance
   attestations, plus portable update metadata and its detached Ed25519 signature.
   It publishes no MSI or Authenticode CAB manifest. The signing secret must
   match the public key packaged in the source policy.
7. Download the published assets, verify the checksum, Ed25519 metadata
   signature/source SHA, and SBOM/ZIP contents, inspect attestations, and confirm
   that `/releases/latest` resolves to the new version.

The single portable publisher has explicit preview/stable channels. The blocked
signed publisher has been removed; MSI/runtime compatibility and acceptance gates
remain. When promotion is disabled, a maintainer can create the immutable tag on
the green preparation merge, then manually dispatch Desktop Release on that tag
with `channel=stable` and the exact SHA. Tag pushes do not publish.
The publication workflow still requires the reviewed preparation intent.
Manual branch previews are prereleases, never latest, and have no update feed or
metadata. See [release automation](release-automation.md#desktop-preview).

## Interface localization

Edit the Portuguese, English and Spanish entries in `shared/ui_strings.json`.
Run `python scripts/sync_locales.py` to update the native Swift catalog, then
`python scripts/sync_locales.py --check` before committing. The iOS app, keyboard
and Live Activity use the generated catalog. Authentication email copy uses the
same source. Keep substitutions unchanged across translations. Do not translate
state IDs, prompts, user transcripts, email addresses or dictionary entries.

Text used only by desktop can be listed in `shared/desktop_ui_keys.json`. This
file contains source keys, not translations. The generator omits these keys from
Swift. The scope check searches for exact key text in supported mobile source
files. It can flag comments and cannot resolve keys assembled from multiple
strings or written with escape sequences. Review such uses explicitly. Remove a
key from the scope list before using it in mobile. Unclassified keys remain
shared. The Python and TypeScript catalogs retain every translation, including
desktop text.

The Windows Settings build stages `desktop/` and `shared/` together under
`%TEMP%\clarify-settings-workspace`, with pinned dependencies in the staged
`desktop` folder. The portable package embeds the shared Python UI catalog.
