<p align="center">
  <img src="assets/branding/clarify-logo.png" alt="Clarify logo" width="112">
</p>

<h1 align="center">Clarify</h1>

<p align="center">
  Windows dictation with local models or your own AI API key. Speak, refine, and paste without leaving your app.
</p>

<p align="center">
  <a href="https://github.com/jvictormaynard/clarify/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/jvictormaynard/clarify/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-0b7285.svg"></a>
  <img alt="Platform: Windows" src="https://img.shields.io/badge/platform-Windows-0078d4.svg">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab.svg">
</p>

<p align="center">
  <a href="docs/README.pt-BR.md">Português (Brasil)</a> ·
  <a href="#installation">Installation</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="SECURITY.md">Security</a>
</p>

Clarify records from a global shortcut, transcribes with Gemini, OpenAI,
Groq, or the optional Local Whisper provider, optionally improves the text, and
pastes the result back into the app you were using. It can also rewrite or
translate selected text without opening a separate editor.

> [!IMPORTANT]
> Clarify supports bring-your-own-key cloud providers and optional hosted
> dictation through a Clarify account. Personal cloud access uses your own
> API key or an eligible ChatGPT plan. On Windows, subscribers can connect their plan
> for text rewriting, translation, and refinement without a Clarify account.
> This uses the existing ChatGPT plan limits and sends text directly to OpenAI;
> it does not include audio transcription. See [ChatGPT plan setup](docs/chatgpt-plan.md).
> The optional Local Whisper provider
> does not require an API key for local transcription; it downloads its
> runtime/model only after an explicit action, and its packaged Windows/offline
> acceptance is still pending. Keys and local usage statistics stay on your
> computer. With your own key, cloud audio/text goes directly to the provider you configure; Local
> Whisper keeps transcription local unless you explicitly enable cloud
> refinement. Hosted dictation sends audio and text through the Clarify service
> to Groq and uses a sponsored individual allowance within the project's funded
> budget. Operating costs are reserved before processing funds are distributed.

> The Settings interface described here follows the current source on `main`.
> Check the [release notes](https://github.com/jvictormaynard/clarify/releases/latest)
> before downloading; older releases have a different interface. Release acceptance is tracked in
> [Release readiness](docs/release-readiness.md).

## Features

Clarify uses the device language for Portuguese, English and Spanish,
including the passwordless authentication email. On first launch, use Google,
Microsoft or GitHub, or enter your email and confirm the code inside the app
to enter or create an account.
**Continue without an account** opens local-model setup; a personal API key is
also available there. Signing in activates Clarify processing automatically.
Signed-in accounts use Clarify-managed models. Personal provider and local-model
settings are available in account-free mode. Style and Text actions are available
in both modes. Weekly sponsored
usage appears as a percentage with the next renewal in your local time. Quotas
renew each Monday at 00:00 UTC. An unknown quota shows a loading state, and an
unfunded allowance has an explicit availability message. Sign-out and deletion
are inside a collapsed Danger zone, with separate confirmations. Vocabulary sync runs automatically,
and usage updates after processing. Local caches preserve offline edits and
conflicts keep both copies until resolved. New account transcriptions synchronize
automatically between Windows and iOS, including original/revised text, time and
source device. The History page supports complete text, pagination and synchronized
deletion. Pre-upgrade records and account-free history remain local; they are never
uploaded. Pending account changes survive connection failures and app restarts.
Guest snippets stay local. Account snippets synchronize separately from vocabulary.
See [history synchronization](docs/history-sync.md) and [voice snippets](docs/dictionary-snippets.md).
Existing profiles retain their setup. The [iOS client](mobile/README.md) is
available on the [App Store](https://apps.apple.com/app/id6820869157).
TestFlight is used for internal testing. The [account service](server/README.md) can also
be self-hosted. Production keys and user data are never public.
The source also supports [pairing an iPhone with a computer](docs/computer-connection.md)
by QR for direct LAN processing with the computer's personal configuration.
The [financial model and public transparency page](docs/finances.md) explain how
confirmed support pays operating costs and weekly processing quotas. Stripe
registration is deferred until a business account is available.

- Voice transcription and prompt-quality rewriting from any Windows app
- Optional Local Whisper transcription after an explicit, verified asset download
- Safe selected-text rewriting that checks focus before replacing content
- Translation picker for selected text
- Gemini, OpenAI, Groq, Local Whisper, and compatible custom endpoints
- Native Windows hotkeys and system tray integration
- Portuguese, English and Spanish interfaces, independently of dictation language
- A React/Tauri workspace with Dictation, Style, Text actions, Dictionary, Snippets and History
- A Settings dialog for General, Devices, Models and services, Shortcuts, Privacy and Clarify account
- Named text actions with custom instructions, optional shortcuts and previews
- Toggle or hold-to-record keyboard activation; the microphone button uses toggle
- A personal dictionary for names and technical terms, with per-term enablement
- Local-only usage statistics without storing transcripts
- Bundled SoX runtime in the portable Windows build
- Optional account with email-code, Google, Microsoft or GitHub login, shared vocabulary, new transcription history and hosted allowance
- Local and personal-key modes remain available without an account; no telemetry service

Settings keeps navigation available while microphone tests, refreshes and saves
run. Choices, switches, shortcuts and flags on saved library rows save
automatically. Text and numeric drafts use **Salvar alterações** (Save changes)
and **Descartar** (Discard) for the current page. Provider key and connection URL
edits on **Modelos e serviços** (Models and services) require **Validar e salvar
chave** (Validate and save key). Validate or discard those edits before saving
other drafts. Closing Settings can save or discard drafts from all pages.

Use **Style** for dictation cleanup, an optional action after dictation and
application writing styles. **Text actions** starts with Rewrite and Translation;
create another action to use your own instructions. Action, processing-profile
and application-style dialogs keep edits as drafts until **Save**. **Cancel**
discards that dialog's edits. Previews use sample text and do not paste into
another application. Local Whisper remains an audio transcription provider.

## Interface preview

Interface captures are retained in the `Settings-tests` artifacts of CI runs.
The [desktop design system](docs/desktop-design-system.md) defines the layout,
tokens and shared components.

See [Release readiness](docs/release-readiness.md) for native acceptance and
release checks.

## Installation

### Windows installer (staged)

The repository now contains the fail-closed MSI and authenticated-update
contract, but it is not enabled for public use until managed signing,
credential-storage, provenance, and manual acceptance gates are complete. When
an MSI is attached to a future release, install only
`Clarify-windows-x64.msi` whose Authenticode publisher and published
SHA-256 match that release. See [Windows distribution and update
security](docs/windows-distribution.md) for the exact install, upgrade, repair,
rollback, uninstall, signing, and incident behavior.

### Community portable release

The project also publishes a no-cost community release for the portable app.
It contains `Clarify.exe`, its SHA-256 file, the runtime SBOM, a ZIP
archive, and verified SoX and Qt/PySide source archives. License notices are
included in the portable package and ZIP. It is intentionally unsigned
until paid publisher signing is sponsored. Windows SmartScreen can therefore
ask for confirmation on first launch. From v0.5.0, this release also provides
Ed25519-authenticated portable update metadata. The MSI and its separate
Authenticode update channel remain staged.

### Portable updates

From v0.5.0, Clarify checks for new stable releases after startup and every six
hours while running. Automatic installation is off by default. A red dot on
the home pill's Settings button marks an available update. Open its menu and
select **Install update** to download and install it.

To enable automatic installation, open **Settings → Geral → Atualizações** and
enable **Atualização automática**. This preference saves automatically. Clarify
downloads in the background, waits until active work is complete and Settings are closed,
then restarts to apply the update. Settings, keys, models, and shortcuts stay
in place. If the new version fails to start, the previous executable is restored.
The app verifies signed metadata and the executable's size and SHA-256 before
replacement. Install v0.5.0 manually once if you are using an older version.

### Portable Windows app

The release workflow produces a self-contained `Clarify.exe`, so end users
do not need Python, Node.js, or SoX.

1. Open the [latest release](https://github.com/jvictormaynard/clarify/releases/latest).
2. Download `Clarify.exe` and place it in a folder you control.
3. Double-click the executable.
4. The first-run page opens automatically. Use Google, Microsoft or GitHub, or enter your email and press **Continuar**,
   or follow **Continuar sem conta**. No password is needed.
   - **Clarify account:** complete provider sign-in or confirm your email code inside the app. Account
     processing is active automatically. No provider key is needed.
   - **Personal key:** save your Groq key. Other providers remain available
     under **Settings → Modelos e serviços** (Models and services).
   - **Local Whisper setup (keyless):** continue to model setup, review its
     requirements, and use the model installation action. No API key is required for
     local transcription. Prompt-mode cloud refinement remains optional; enable
     **Allow cloud refinement** only when desired. The Windows/offline
     acceptance for Local Whisper is still pending; see [Local ASR](docs/local-asr.md).
5. Open **Settings → Ditado** (Dictation) or **Settings → Texto** (Text) to
   choose the route for each workflow. A route selects its provider, model,
   endpoint, enablement, and optional prompt independently.

Community portable executables are not code-signed. Verify the SHA-256 file
published with the release before running the download. The MSI and in-app
update path remain disabled until the signed rollout gates are complete.

### Run from source on Windows

Requirements: Windows 10 or 11, [Python 3.11 or newer](https://www.python.org/downloads/windows/),
and a working microphone. Building the new Settings also requires Node.js 22,
Rust MSVC, Visual Studio C++ Build Tools, and the Windows SDK. Running Settings
requires Microsoft Edge WebView2. See [Development](docs/development.md).

```powershell
git clone https://github.com/jvictormaynard/clarify.git
cd clarify
.\scripts\setup.ps1 -Dev
.\scripts\build-settings.ps1
$env:CLARIFY_SETTINGS_EXECUTABLE = (Resolve-Path .\dist\clarify-settings.exe).Path
.\start.bat
```

On the first run, `start.bat` creates an isolated `.venv`, installs the Python
dependencies from the checked-in lock, and launches Clarify. Later runs
reuse that environment.
You can refresh it at any time with:

```powershell
.\scripts\setup.ps1
```

Setup, CI, packaging, and release workflows consume the checked-in platform
lock (`requirements-lock-linux.txt` or `requirements-lock-windows.txt`), so a
runner resolves the same package set for its operating system. Top-level
dependency intent remains readable in `requirements.txt` and
`requirements-dev.txt`; maintainers regenerate the matching lock with
`python -m piptools compile` when that intent changes.

Linux and macOS source paths are experimental. See
[Development](docs/development.md#experimental-linux-and-macos-support) for
their current limitations.

## Usage

| Shortcut | Action |
| --- | --- |
| `Alt + L` (default) | Start or stop recording |
| `Esc` | Cancel an active recording or close the translation language picker |
| `Alt + K` (default) | Rewrite the selected text |
| `Alt + T` (default) | Translate the selected text |
| `Alt + V` (default) | Record and translate speech |
| `Alt + R` (default) | Show or hide Clarify |

All five global shortcuts can be captured, validated, and reset in **Settings →
Atalhos** (Shortcuts). Standalone Ctrl, Alt, Shift or Windows keys and the Mouse 4
and Mouse 5 side buttons are also supported. Ordinary combinations such as Ctrl+C
keep their behavior. Hover over the pill's flag to open the vertical language list
and select a flag. Toggle starts and stops on successive presses. Hold records
while the shortcut is pressed and stops on release. `Esc` cancels, including
while holding the shortcut. The pill microphone button always uses toggle.
You can also assign a modifier by itself (`Ctrl`, `Alt`, `Shift`, or `Win`) or
a side mouse button (`Mouse 4` or `Mouse 5`). Modifier taps run on release;
normal combinations such as `Ctrl+C` do not trigger a standalone modifier.
Primary, secondary, and middle mouse buttons remain available for normal use.
Hover over the pill's flag to open the animated vertical language menu.
Cancellation feedback and Undo appear inside the pill, not in another window.
While choosing a translation language, `Esc` closes the picker even if the
source application keeps keyboard focus.
The picker focuses the first language when it opens. Use `↑` and `↓` to move
through the languages and `Enter` to select. Navigation wraps at either end.

The floating bar remains available through the Windows system tray. Click the
tray icon to restore it, or right-click the icon to open Clarify or quit.
The minimize button hides the app to the tray instead of closing it.

For rewrite and translation, Clarify only pastes when the original window
and selection are still active. If focus changed while the provider was
processing, the result stays in the clipboard for manual paste. There is no
automatic result window. The pill menu can paste the last transcript from the
current session.
Automatic paste temporarily writes the result and restores the user's Unicode
text, HTML, RTF, and DIB image clipboard formats after a short bounded delay.
If focus, paste confirmation, or clipboard ownership is lost, the generated
result remains available for manual paste and the newer clipboard contents win.

## Providers and workflow routes

Open **Settings → Modelos e serviços** to configure a cloud provider, base URL, and
API key, or to install Local Whisper. Local Whisper does not require an API key
or cloud endpoint; use **Download local ASR** explicitly to install its verified
optional assets. Open **Settings → Ditado** and **Settings → Texto** to select
independent workflow routes. Ordinary settings are
stored in `%APPDATA%\Clarify\config.json`; cloud API keys are kept
separately with Windows Data Protection API (DPAPI).

| Provider | Transcription | Text refinement | Default endpoint |
| --- | --- | --- | --- |
| Gemini | Multimodal audio | Same Gemini model | `generativelanguage.googleapis.com/v1beta` |
| OpenAI | Audio transcription API | OpenAI-compatible text model | `api.openai.com/v1` |
| Groq | Whisper-compatible audio API | OpenAI-compatible text model | `api.groq.com/openai/v1` |
| ChatGPT plan | Not supported | Responses API with the connected account's available models | `api.openai.com/v1` |
| Local Whisper | Local CPU or compatible NVIDIA GPU sidecar (optional download) | None by default; cloud refinement requires explicit opt-in | Local loopback only |

To use a ChatGPT subscription on Windows, select **Continue without an account**.
You do not need a Clarify account or an API key for this connection.

1. Open **Settings → Models and services** and select **ChatGPT (subscription)**.
2. Select **Continue with ChatGPT**, finish sign-in in your browser, and grant
   permission to use your plan.
3. Select **Refresh ChatGPT models**, then open **Settings → Text**. For each
   text workflow, select ChatGPT and an available model for the connected account.
   Sign-in does not change existing routes.

ChatGPT supports rewriting, translation, and optional cloud refinement of Local
Whisper transcripts. It does not transcribe audio. Requests use your existing
ChatGPT allowance and limits, with no additional quota. Windows DPAPI protects
tokens locally, and text requests go directly to OpenAI through a fixed endpoint.
Clarify account mode keeps managed processing on desktop and mobile. See
[ChatGPT setup and limits](docs/chatgpt-plan.md).

Custom endpoints must implement the corresponding provider-compatible routes.
Unknown custom models work, but their cost is intentionally shown as unpriced
instead of using an unreliable estimate.

Local Whisper is transcription-only and is not bundled with the executable. Its
`whisper.cpp` runtime and model are downloaded only after the user authorizes the
action and are verified against the pinned manifest. Dictation uses faithful
refinement by default, with no mode selector. Existing mode settings migrate
automatically. Local transcripts stay on the computer unless **Allow cloud
refinement** is enabled; this setting sends that transcript to the
selected cloud model. The Windows/offline product acceptance remains pending.

## Personal dictionary

Add names and technical terms in **Settings → Dicionário**, for example
`Railway`, `pill`, `Lana`, or `Eva Desktop`. Additions, text edits and removals
remain drafts until you select **Salvar alterações** on this page. Use
**Descartar** to cancel these drafts. Enablement changes on saved terms save
automatically.
Enabled terms provide bounded vocabulary context to ASR and optional text
refinement. They are hints, not guaranteed replacements. When a cloud route is
used, this vocabulary is sent to that provider with the request. See
[Dictionary behavior](docs/dictionary-snippets.md) for limits and processing stages.

## Voice snippets

Open **Settings → Snippets** on desktop or **Dictionary → Snippets** on iOS.
Add a phrase such as `minha assinatura` and the text to insert, then save.
Say the phrase alone to insert its exact saved text. Inside a sentence, the
snippet is substituted before rewriting so the model can adjust the whole message. Search, edit, disable or delete snippets
from the same page. On desktop, additions, text edits and removals use this
page's **Salvar alterações** and **Descartar** actions. Enablement and case
sensitivity changes on saved snippets save automatically.

Account snippets synchronize between devices. Guest snippets stay on their device
and are not uploaded at sign-in. Only trigger phrases can become recognition
context. With rewriting enabled, applied saved text is sent to the rewrite model
as part of the source message; its wording and formatting can change. Rewrite failure keeps the
substituted source, and the original recognized transcript remains in history.
See [matching, sync and limits](docs/dictionary-snippets.md).

## Privacy and local data

In personal mode, cloud requests go directly to the selected provider. ChatGPT
plan requests send text directly to OpenAI. Local Whisper sends audio only to its
own randomized loopback sidecar. Account processing uses the optional Clarify
service; see the [privacy notice](PRIVACY.md). The app stores:

- provider settings in `%APPDATA%\Clarify\config.json`;
- DPAPI-encrypted provider keys in `%APPDATA%\Clarify\secrets.dpapi.json`
  and ChatGPT OAuth credentials in `%APPDATA%\Clarify\chatgpt-secrets.dpapi.json`,
  decryptable only by the same Windows user on the same machine;
- anonymous usage counters in `%APPDATA%\Clarify\usage_stats.json`;
- optional Local ASR assets below `%LOCALAPPDATA%\Clarify\local-asr` after
  an explicit download; the runtime and model are not bundled in the executable;
- dictionary entries in `%APPDATA%\Clarify\dictionary.json`;
- a unique temporary WAV file while processing a recording. Normal cleanup
  removes it when no operation needs it, including cancellation recovery.
  Crashes, forced shutdown, or cleanup failures can leave files behind; do not
  treat this as a secure-erasure guarantee;
- optional local transcript history without an account, and an offline copy of
  automatically synchronized new account history when signed in. Pre-upgrade
  history remains local. Usage counters do not contain transcript text.

Existing plaintext keys are migrated on first load and removed from
`config.json` only after the encrypted copy has been read back successfully.
Environment variables remain runtime-only overrides and are never copied into
either settings or secret storage.

Removing the portable executable does not remove its data. Delete
`%APPDATA%\Clarify\secrets.dpapi.json` (or the whole Clarify data
directory after preserving any settings you want) to remove stored keys.
Transcript and selected-text contents are not written to usage statistics.
Read [Security](SECURITY.md) for responsible reporting guidance.

## Build a portable executable

```powershell
.\build.bat
```

The output is `dist\Clarify.exe`. The build deliberately does **not**
bundle `.env` or any local API key. See [Development](docs/development.md) for
the full setup, checks, release process, and WSL maintainer workflow.

To build an unsigned local MSI for packaging tests after the executable:

```powershell
npm run installer
```

This installs the pinned WiX compiler into ignored `build\tools`, writes only
inside the repository, and does not install or replace Clarify. Public
MSIs must come from the protected signing workflow.

## Project structure

```text
desktop/src/                  React/TypeScript Settings and shared controls
desktop/src-tauri/             Tauri window and private process bridge
clarify/desktop/qml_app.py      Production Qt Quick/QML entrypoint
clarify/desktop/qml/            Production QML surfaces and theme
clarify/desktop/qml_runtime.py  Qt adapters for providers, audio, clipboard, and storage
clarify/desktop/qml_bridge.py   QML-facing workflow state and commands
provider_types.py              Typed provider requests, results, and capabilities
provider_adapters.py           Gemini and OpenAI-compatible adapters
provider_registry.py           Provider metadata and request routing registry
local_asr.py                    Optional local-ASR adapter, installer, and sidecar
local_asr_product.py            Explicit install/progress/removal product boundary
local_asr_manifest.json         Pinned sidecar/model assets and SHA-256 allowlist
repositories.py                Versioned configuration and statistics storage
dictionary_snippets.py         Local dictionary/snippet storage and expansion
dictionary_settings.py         Tk-independent Settings operations for the local profile
microphone_controls.py         Microphone identity and recording boundary policies
update_security.py             Authenticated manifest and atomic update checks
version.py                     Packaged application version
desktop_state.py               Small workflow state controller
workflows.py                  Headless workflow commands and orchestration service
windows_hotkeys.py             Native Windows hotkey helpers
assets/                        Product branding and provider marks
extra/sox-14.4.2/              Bundled Windows audio runtime and license
scripts/                       Setup, build, and maintainer deploy scripts
installer/                     WiX per-user MSI definition
distribution/                  Immutable packaged update trust policy
tests/                         Unit and repository-safety tests
docs/                          Architecture and development documentation
.github/                       CI, release, issue, and PR automation
.agents/skills/                Repository-specific maintainer workflows
```

The application uses Python/PySide6/Qt Quick for the pill and desktop engine,
and React/TypeScript in a Tauri WebView2 window for Settings. It is not Electron.
`start.bat`, the
portable build, and the release workflow all use the QML entrypoint; the old
CustomTkinter entrypoint is not part of the runtime or package. The Electron
prototype was removed from the checkout and remains available in Git history. See
[Architecture](docs/architecture.md) before making structural changes.
Production Qt code lives in `clarify/desktop/`; `spikes/` contains only historical comparison tools.
`app.py` is a legacy frontend retained for compatibility tests, not the shipping
entrypoint. New UI work belongs in `desktop/` or the QML pill, not `app.py`.

Local Whisper is an explicit provider in the current product runtime. The
portable executable includes the pinned Local ASR manifest and license notices,
but not the runtime or model; installation remains an explicit user action.
Maintainers can review the checksummed sidecar design, privacy trade-offs, and
pending Windows/offline acceptance work in [Local ASR](docs/local-asr.md).

## Contributing

Bug reports, documentation improvements, translations, provider integrations,
and focused code changes are welcome. Start with
[CONTRIBUTING.md](CONTRIBUTING.md), which includes the local setup, test command,
visual validation expectations, and pull-request checklist.

- Questions and usage help: [SUPPORT.md](SUPPORT.md)
- Security reports: [SECURITY.md](SECURITY.md)
- Community expectations: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Changes by release: [CHANGELOG.md](CHANGELOG.md)

## License

Clarify source code is available under the [MIT License](LICENSE).
Bundled third-party software and provider marks remain under their respective
licenses and terms. Tagged releases attach the corresponding SoX 14.4.2 source
archive alongside the portable binary. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Local model performance

Install a local model once to prepare CPU and compatible NVIDIA GPU support.
Automatic measures this computer and uses the fastest available device. Model
weights are reused between runtimes. Existing installations can select Optimize
CPU/GPU. Base, Small and Medium trade speed for capacity; accuracy depends on
language and audio. Recognition during recording is experimental, requires
NVIDIA GPU support, and stays off by default. It can reuse a complete snapshot
when recording ends with a pause. Continuous speech can still require the full
recording and can take longer. See the
[background recognition limits](docs/local-asr-profiles-and-streaming.md).
Cloud refinement of local transcripts remains an explicit option.

If optional dictation refinement fails, Clarify keeps the original transcript, shows a brief warning and records a partial result when local history is enabled.
Dictation cleanup uses low reasoning on the official Groq GPT-OSS models.
It preserves unique content, resolves clear spoken corrections, and removes
accidental duplicates. Incomplete provider output also uses the original text.

## Privacy

Read the [privacy notice](PRIVACY.md) before enabling account sync or hosted processing.
