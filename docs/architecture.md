# Architecture

Clarify has a local-first Windows desktop client, an iOS client in `mobile/`,
and an account service in `server/`. On desktop, local models and personal API keys
work without an account. The iOS client uses an authenticated Clarify account or
an explicitly paired computer. Stored personal keys from older versions do not
enable mobile processing.
Hosted dictation requires an authenticated account and
uses a server-owned Groq key; personal keys never pass through that service.

All product source remains in this public MIT repository. Production credentials,
user data, backups and administrator access stay private in the hosting platform.
There is no separate closed backend or local/cloud product fork.

Accounts share vocabulary, snippets, sponsored processing quota and new account
transcriptions. Pre-upgrade records, guest history and guest snippets remain local.
Account snippet caches use endpoint and account identity; signing in does not
upload guest snippets. Hosted substitution runs once after recognition and before optional rewriting.
The rewrite model receives the substituted source and can adjust it with the
rest of the message. Rewrite failure returns the substituted source. The
original recognized transcript remains unchanged in history. Standalone triggers
insert the exact saved text without rewriting. Recognition hints contain only
enabled triggers; saved replacements are sent only when applied to rewrite source. Account libraries have a 256 KiB compact UTF-8 JSON limit, and
snippet-expanded dictation fields retain the existing 32 KiB UTF-8 history limit.
Rendered hosted responses also have a 384 KiB bound. Excessive expansion returns
an explicit error without truncation. Account history
uses an endpoint/user-scoped offline cache and durable pending changes; local
records are never inferred to belong to the current account or uploaded.
See the [history synchronization contract](history-sync.md) for cursor,
idempotency, deletion and retry ownership. `clarify_account.py` owns the
desktop account boundary; the iOS containing app owns `CloudAccount.swift`.
Sessions stay in the desktop secret store or app-only iOS Keychain. The keyboard
extension receives neither provider keys nor account sessions. Account-scoped
vocabulary caches preserve the local dictionary when the user signs out.

The iOS keyboard receives a nonsecret App Group vocabulary projection with an
opaque account scope. A tap on a one- or two-word selection writes a separate
atomic inbox file before confirming Saved. The containing app imports these
additions into its scoped SQLite dictionary before dictation or dictionary
access, and while its microphone session is active. Imported files are removed
only after persistence. Account additions invalidate the synchronization interval
so the next hosted dictation includes them. History and credentials remain
app-only; pending additions never cross account or guest scopes.

`server/` uses Django, django-allauth headless email codes, DRF and PostgreSQL.
The server owns provider selection, prompts, billing bounds and per-account/global
admission. Clients cannot send arbitrary model, prompt, endpoint or ownership
settings. A PostgreSQL lock serializes quota reservations and cost settlement.
`shared/dictation_prompt.json` is generated from the canonical desktop prompt.
See [server operations and release gates](../server/README.md).

Sponsored processing uses funded individual weekly quotas with a common Monday
00:00 UTC expiry. Operating provisions and existing commitments precede the
80/20 regular/entry allocation. The server measures provider costs and returns
versioned percentages and reset dates; clients show the reset in local time.
See the [accepted funding contract](agents/plans/weekly-sponsored-usage/spec.md).
Public financial reporting separates project treasury entries from read-only
Stripe balances and sanitized movements. API credentials and contributor identity
stay private. A declared sponsorship or spending cap never becomes a receipt.
New receipts require operating-cost confirmation before a new period can be
distributed. Each receipt retains its net processing basis and monthly release
schedule. Public finance reads use a read-only snapshot and shared request limits;
they do not acquire the financial write mutex.

Desktop startup opens Settings for an unfinished setup;
`AppConfig.onboarding_completed` is saved through the existing config transaction.
Legacy profiles retain their choices. The iOS app stores separate app-only
presentation and setup preferences. General onboarding appears once when first
shown and can be dismissed. Existing signed-in installations and legacy setup
preferences migrate without another presentation. The guide can be replayed from
Account without resetting that marker. Protected Router screens require an
account session or a selected paired computer before the iOS tabs can be used.
The iOS route guard checks the selected processing destination, so a completed
legacy personal-key setup cannot enable processing. Its old history remains on the device
and is never assigned to an account. The existing first-login import of local
dictionary words is preserved; the local dictionary is not deleted.
Setup does not acquire the microphone or send an email without a user action.
The sign-in form supports email codes, Google, Microsoft and GitHub. The server's
`auth/continue` adapter creates an unverified account only when needed, then uses allauth's
same login-code verification and session machinery for both paths. New-account
limits still apply; no usable password is saved. Legacy separate endpoints remain
available. Authentication forms are shared with desktop Settings and the iOS
sign-in screen. After sign-in, the bottom tabs contain Home, Dictionary, Snippets
and Account. Account opens Settings and the explicit guide replay. The tabs,
Settings and guide routes share the destination guard. In iOS account mode,
sign-out or session expiry returns to the connection choice before tabs can be used.

An authenticated account uses Clarify-managed processing for dictation, imported
audio, selected-text rewrite and translation. Personal provider and local-model
controls are hidden in this mode. An expired managed session fails closed; it
cannot fall back to a saved personal key. Signing out explicitly restores the
personal configuration on desktop. The iOS account route stops microphone access
when its session expires; it cannot fall back to a paired computer. In account
mode, signing in activates account processing automatically,
including for existing signed-in profiles. There is no separate activation step.

Shortcut capture is owned by the Qt Settings controller, including the React
dialog's capture state. Capture temporarily releases native hotkeys and input
hooks so an existing binding cannot trigger a workflow or consume a side button.
Successful capture, cancellation, hidden or closed Settings restore the bindings.
Late input events from the replaced hook are ignored; a registration collision
can recover through the existing Apply transaction.

Vocabulary sync runs after login and local edits, then at most once per minute
while the app is active or before a hosted dictation. Failed attempts also use
this interval. Conflicting edits require an explicit resolution. Each account
has its own persistent cache; guest words, guest snippets, settings, keys and history
remain on the device. Processing responses include the updated shared allowance,
and a foreground refresh catches changes made on another device.

`shared/ui_strings.json` owns Portuguese, English and Spanish UI and email copy.
Clients select the device UI language, independently of dictation language, and
send it as `Accept-Language` for authentication. Unsupported device languages
use English. Qt and React read the shared catalog; `scripts/sync_locales.py`
generates the checked Swift copy for the app, keyboard and Live Activity. The
desktop bridge supplies the same Windows UI language used by the account client.
Authentication emails contain the code and localized instructions, without links.

Google, Microsoft and GitHub use server-owned django-allauth OAuth adapters.
The desktop system browser and the iOS authentication session share a bounded,
one-time native handoff protected by a client-generated SHA-256 proof. The
server owns provider secrets, OAuth state, provider code exchange and account
creation. Browser callback URLs contain no Clarify credentials. Native clients
receive the resulting allauth session only through the proof-protected endpoint,
then use the existing account refresh and synchronization owners. Unverified
provider emails continue through the existing email-code confirmation flow.
Matching email addresses do not authorize automatic account linking. The desktop
`social_login.py` boundary owns browser URL validation, bounded polling and
cancellation; `clarify_account.py` owns credential storage and account state.

## Runtime flow

```text
Global hotkey
    |
    v
Desktop workflow ----> temporary audio or selected text
    |                              |
    v                              v
Provider registry ----------> Gemini / OpenAI-compatible adapter
    |                              |
    |                              +----> OpenAI / Groq / custom endpoint
    v
Typed capability result
    |
    v
Focus and selection safety check
    |
    +---- unchanged ----> snapshot, atomically paste, and conditionally restore
    |
    +---- changed ------> keep result in clipboard for manual paste
```

The Qt/QML event loop owns the desktop surface. Provider calls, audio
processing, and clipboard transactions run through scheduled workers so the
floating window remains responsive.

## Paired computer processing

`computer_host.py` owns the opt-in HTTPS listener, TLS identity, expiring one-use
pairing codes, per-device authorization and bounded operation admission. Private
identity material uses `clarify_computer` in the existing secret store. The
profile's `computer.sqlite3` stores device token hashes, operation metadata and
explicit startup consent. Result text remains in a bounded memory cache.

`computer_processing.py` adapts accepted WAV and text input to
`WorkflowProviderService`. It snapshots the computer's personal configuration
and dictionary and reuses the provider registry. It owns no microphone,
clipboard or hosted account. Provider keys, models and prompts remain on the
computer. `clarify/desktop/qml_computer.py` owns Qt lifecycle and temporary QR
presentation. Account transitions stop personal hosting before changing owners.
Application shutdown must drain mobile processing before closing shared providers.

The iOS containing app's `ComputerConnection` owns camera pairing, private
Keychain credentials and scoped HTTPS transport. `ProcessingDestination` selects
it or the existing `CloudAccount` boundary. Computer mode needs no hosted
account and cannot silently fall back to hosted processing. The existing
recorder and keyboard bridge remain authoritative. The keyboard receives no
connection credential. Computer history stays in its own scope on the iPhone;
it does not enter account synchronization. Computer dictation uses the
computer's dictionary and snippets.

See the [computer connection protocol](computer-connection.md) for wire bounds,
certificate pinning, operation identity and open delivery evidence.

## Settings process boundary

`desktop/src/` contains the React/TypeScript Settings pages, Base UI controls,
and styles. `desktop/src-tauri/` hosts them in a Tauri v2 WebView2 window. This is
not Electron and does not replace the Python audio engine or QML pill.

`clarify/desktop/qml_web_settings.py` starts the child with Qt `QProcess` and
exchanges JSON messages over private standard input/output pipes. The Python
allowlist controls which Settings properties and methods are exposed. There is
no public HTTP Settings server. Python owns config, credentials, model assets,
and audio devices; React displays state and submits changes through this bridge.
`qml_settings.py` remains the shared controller. The QML Settings view remains a
fallback when the native child is unavailable.

The new Settings currently use Portuguese labels. QML locale coverage must not
be described as complete localization of the React pages.

The Settings frontend separates window composition (`desktop/src/app.tsx`),
feature pages (`pages/`), reusable controls (`components/`), and application state
(`settings/`). `settings/use-settings.ts` owns local drafts, navigation and
contextual save/discard operations. Its operation boundary controls action-local
pending state, errors and success updates. Navigation stays available during
microphone tests, refreshes and saves; it does not stage free-text drafts.
`savePreference` persists one allowlisted choice without committing other drafts.
`saveLibraryPreference` applies a library flag only under the matching persisted
entry identity and account context. Explicit text saves reserve the connection
for the full staging/persistence transaction, preserving later edits and drafts
on other pages. Library drafts retain their original persisted baseline. Save
merges local edits with a fresh library snapshot. Staging checks the expected
persisted rows under the account/library guard and rejects a stale snapshot
before changing the backend draft. This preserves remote additions received
during editing or while Save waits in the queue. The close confirmation can
explicitly save all pending drafts. `settings/use-settings-window.ts` owns native close
requests. `settings/bridge.ts` defines typed command arguments for frontend
callers without changing the Python allowlist or private pipe protocol.

Periodic Settings reads use top-level deltas from one previous poll snapshot.
Initial reads and command replies remain full snapshots. Only a poll advances
the delta baseline, so an ignored background command reply cannot consume a
later update. Full replies mark changed field names for the next poll, including
transient values that return to the baseline before that poll. React merges fields with structural sharing, skips unchanged
state, and compares library drafts only when their references change. A failed
poll triggers a full read before polling continues. This remains one serialized
frontend connection; Python still reads the allowlisted properties on each poll.
Pending telemetry does not hold the user-operation busy state. Local navigation
uses the latest state and does not publish an old snapshot over a newer delta.

Microphone discovery runs on one worker per Settings controller. Repeated refresh
requests share the pending query. The last completed inventory stays available
while discovery runs. Workers publish data to a plain Python mailbox, drained
by a controller-owned timer on the Qt thread. Inventory, local-product state,
and local-device workers retain the mailbox instead of the Qt controller.
Shutdown closes and clears the mailbox before stopping its timer; generation
and shutdown checks reject late results. Optional backend loading also occurs
on the inventory worker. Device discovery does not change a saved microphone
preference or an unrelated draft error. See [desktop performance](desktop-performance.md)
for shared components, measured cases, and validation limits.

`QtRecorder` loads PortAudio lazily through one shared loader on audio workers.
Each SoX capture has its own identity. Process launch and WAV readiness reads
run outside locks used by Qt; the pill reads cached readiness. One optional
meter worker owns stream open/start/stop/close across rapid restarts. Recording
finalization does not wait for this presentation stream. Late processes and
streams cannot attach to a newer capture, and cancelled late launches repeat
their owned audio cleanup after process termination.
Windows readiness handles share delete access, so cancellation can unlink the
WAV during a pending read. Voice translation uses the same lazy audio loader
from its recording worker; the production import path does not initialize it.

Snippet draft writes retain their captured account context through persistence
and rollback. The account repository supplies an optional transaction guard;
`DictionarySnippetService` acquires it before its own lock for load, replace and
import. Settings uses the same owner guard for its complete save transaction.
The lock order is account before dictionary service, including synchronization.
A session transition cannot redirect an account draft into guest storage.

Shared Settings visual values live in `desktop/src/styles/tokens.css`; base styles,
controls, page layouts and responsive window rules have separate files. Common
fields own their accessible labels and help-text associations. The compact QML
surfaces keep their existing theme and behavior. See `desktop/README.md` for the
source map and component conventions.

## Current modules

### `clarify/desktop/qml_app.py`, `qml_bridge.py`, and `qml_runtime.py`

These modules are the production desktop entrypoint and Qt integration layer:

- `qml_app.py` creates `QApplication`, registers the real QML controllers,
  starts the tray/single-instance shell, and wires shutdown ownership;
- `qml_bridge.py` exposes typed workflow state, commands, settings, files, and
  voice-translation surfaces to QML;
- `qml_runtime.py` composes provider, recording, clipboard, statistics, and
  audio-file gateways without importing the old widget frontend; and
- `clarify/desktop/qml/` contains the compact black-and-white theme, overlay,
  fallback settings, legacy result assets, translation, and file-import surfaces.

The old widget entrypoint is not used by `start.bat`, PyInstaller, CI, or
release packaging. Root `app.py` remains for legacy compatibility tests; new
features must not be added there. Production Qt adapters and assets live in
`clarify/desktop/`; historical comparison tools remain under `spikes/`.
The unused Electron implementation is available in Git history, not the checkout.

### Provider layer

Provider code is split into three UI-independent modules:

- `provider_types.py` defines capabilities, metadata, connections, typed
  transcription/rewrite/translation requests and results, model catalogs, and
  actionable provider errors;
- `provider_adapters.py` implements Gemini and the shared OpenAI-compatible
  protocol used by OpenAI and Groq. Endpoint normalization and model filtering
  live here so display labels never become API IDs;
- `provider_registry.py` is authoritative for provider IDs, display metadata,
  capabilities, default endpoints/models, adapters, and request routing.

The desktop asks the registry whether a provider supports multimodal audio,
text generation, model discovery, or custom base URLs. It does not select a
workflow by comparing provider names. The QML runtime delegates operations to
typed requests and keeps provider-specific behavior out of the UI.

The HTTP dependency is intentionally the narrow `HttpClient` protocol with a
single `request` method and guarded JSON decoding. Adapters preserve the
existing request payloads and response shapes; session ownership, timeouts,
retry, cancellation, logging, and shared error policy live in `provider_http.py`.
Connections arrive from the repository-loaded configuration (with provider
secrets resolved by `SecretStore`); the transport never persists credentials or
reads environment variables itself.

### Workflow-scoped routing

`workflow_config.py` is the UI-free boundary for routing decisions. It models
independent `transcription`, `refinement`, `rewrite`, `translation`, and
`local_asr_refinement` scopes. Each route carries a canonical provider ID,
model ID, prompt policy, optional custom endpoint, an explicit enabled flag,
and an `independent` provenance marker; API keys are never part of a route.
Migrated legacy clones keep the marker false and remain synchronized with the
flat Models selectors, while a route authored through the scoped settings
controller sets it true and remains authoritative even when its values match
a legacy selector. `validate_workflow_config` checks the
registry capability required by every scope and rejects unsupported
combinations before an adapter or local sidecar can start. Custom endpoints are
HTTP(S)-only and cannot contain URL userinfo, query parameters, or fragments;
this keeps adapter path composition deterministic and avoids credential-bearing
URLs at rest. Its
`test_workflow_configuration` result is local and diagnostic-safe: it makes no
provider request and does not persist prompt text.

`workflow_settings.py` is the UI-free settings controller used by the QML
surface. It keeps an immutable typed draft, changes one scope at a time, and
delegates Apply, Reset, and Test to `LocalConfigRepository` so validation and
atomic persistence remain outside the Qt event loop. The controller exposes only redacted
effective-route summaries (provider, model, endpoint, and local/cloud state).
`WorkflowProviderService` resolves the route for each operation, including the
rewrite and translation-specific prompt and endpoint. The legacy
`AppWorkflowProvider` remains a compatibility adapter in `app.py`.

### `workflow_provider.py`

`WorkflowProviderService` owns provider policy for dictation, selected-text
rewrite, and selected-text translation. It constructs typed requests, applies
workflow prompts and dictionary context, preserves raw/refined provenance,
and retains the exact raw transcript when optional refinement fails.
Cancellation still takes precedence over recovery. It delegates HTTP, retries,
and local inference to the existing provider registry.

The service accepts a read-only configuration protocol, a dictionary service,
and an optional registry. It imports no desktop framework and does not own
capture, worker scheduling, clipboard publication, or profile persistence.
`QtProviderGateway` composes this policy with Qt-owned recording preparation;
the recording gateway still owns session exclusivity, stop, and cleanup.
This boundary allows provider policy to be tested without starting Qt or a
microphone. It changes no routes, persisted schemas, prompts, or user controls.

### Dedicated voice translation (`voice_translation.py`, `voice_translation_runtime.py`)

Issue #49 adds a separate, UI-free contract for voice translation rather than
coupling voice capture to the selected-text `WorkflowService`. The versioned
`VoiceTranslationConfig` stores an automatic or explicit source language, one
explicit target language, and an independent provider/model/prompt route,
persisted under `voice_translation` in `config.json`. Route validation
delegates to the provider capability registry and therefore rejects providers
without `TEXT_GENERATION` before a request can start; it performs no network
call and keeps prompts out of diagnostics.

`VoiceTranslationWorkflow` is a deterministic transaction seam for recorder
and Windows adapters. Its immutable state machine retains the raw
transcript across translation, focus, clipboard, and publication failures. A
translation failure or empty result produces an explicit `COPY_ONLY` decision
containing that raw transcript. A successful translation is only `PASTED` when
both the captured target is still current and the clipboard adapter says it
owns the publication transaction; otherwise it is explicitly `COPY_ONLY`.
An atomic `claim_publication` state transition is a non-cancellable barrier:
once the clipboard effect starts, cancellation is ignored and the eventual
completion remains consistent with the published outcome. The application-wide
default `VoiceTranslationPublicationCoordinator` serializes external
publication effects across separately constructed workflow objects, so two
global actions cannot paste over one another. The policy is side-effect free
and can be reviewed independently of any desktop API. Every worker carries the
operation ID captured when it starts; all transitions and publication claims
verify that ID, so a late completion from a cancelled run fails closed instead
of mutating or publishing into a newer operation. Its caller receives the
originating operation's terminal snapshot, never the newer operation's state.

`VoiceTranslationRuntime` connects this contract to one recording owner and
the configurable dedicated Alt+V global action. It publishes only lifecycle
snapshots to Tk and propagates the recording cancellation token through
transcription and translation. The redacted execution summary exposes local
ASR transcription, cloud translation, and the explicit local-ASR
cloud-refinement opt-in independently. Packaged Windows testing across three
representative target applications remains a release acceptance gate; unit
tests do not claim that manual evidence.

#### Adding an OpenAI-compatible provider

1. Add `ProviderMetadata` with a canonical lowercase API ID, a separate display
   name, config keys/defaults, and the capabilities the endpoint really offers.
2. Call `ProviderRegistry.register_openai_compatible`, supplying official model
   IDs or legacy label aliases only when the provider needs them.
3. Extend persisted configuration fields and provider artwork for the new ID.
4. Add fake-HTTP contract tests for discovery, authentication, transcription,
   text generation, custom URL normalization, and unsupported capabilities.

Dictation, rewrite, translation, and model-picker workflows require no new
provider-specific branch. A protocol that is not OpenAI-compatible should use a
new adapter implementing the same typed operations, then be registered once.

### `workflows.py`

Defines the staged, UI-independent application-service boundary for dictation,
rewrite, and translation. The service accepts explicit command dataclasses and
publishes immutable workflow states. It owns overlap prevention and assigns a
monotonic operation ID to every session; workers check that ID before provider
results can change the clipboard, statistics, or current state.

Gateway calls never run while the service lock is held. Dictation delivers its
terminal `COMPLETED` state before claiming clipboard/statistics publication;
rewrite and translation deliver a non-cancellable `PUBLISHING` barrier first.
Cancellation or shutdown that wins before a claim performs neither output nor
usage accounting. An accepted publication records usage once, and terminal
release waits for a blocked external gateway so the UI cannot announce `READY`
before its effect has returned.

```text
Qt/QML command bridge                 QML state renderer
          |                                  ^
          v                                  |
   WorkflowService ---- immutable WorkflowState
          |
          +---- ProviderGateway (typed registry facade)
          +---- AudioGateway
          +---- ClipboardGateway
          +---- WorkflowConfig
          +---- StatisticsGateway
          +---- Scheduler / Clock
```

The gateway protocols describe ownership boundaries; they do not reimplement
provider routing, HTTP policy, recording lifecycle, clipboard transactions, or
configuration persistence. `ProviderGateway` is the workflow-facing facade for
the typed requests and results routed by `ProviderRegistry`; workflows never
branch on provider IDs or call adapter HTTP directly.

The recording boundary is connected to the real `RecordingSession` lifecycle
from issue #18 through `RecordingAudioGateway`. A stop waits for startup to
become terminal and returns an immutable `RecordingSnapshot` containing both
the owned path and in-memory bytes. The session can therefore complete cleanup
as soon as the snapshot exists without tying its temporary WAV to a slow
provider request. `qml_runtime.py` connects the service to the typed provider
registry, the real recording session, and the focus-safe native clipboard.
Windows hotkeys capture the original `SelectionTarget` before the QML window
can take focus and dispatch explicit workflow commands.

### `audio_file_batch.py`

Defines the UI-independent local-file import boundary from issue #54.
`AudioFileBatchService` validates a finite local path list, exposes explicit
provider/model/language selection, snapshots WAV inputs, and normalizes other
allowlisted SoX formats into a private temporary WAV. `AudioBatchJob` submits
at most a configured number of provider operations, publishes per-file states,
propagates cooperative cancellation, and preserves successful results when
another file fails. `RegistryAudioTranscriptionGateway` reuses the typed
`ProviderRegistry` contract rather than duplicating provider or HTTP logic.

Imported paths remain user-owned. The service never deletes an original,
resolves a URL, or creates a persistent queue; conversion directories are
removed in a bounded `TemporaryDirectory` scope. `qml_audio_batch.py` owns the
QML file-picker lifecycle, retry snapshot, and scheduler handoff while
`qml_runtime.py` builds the explicit local/cloud route selection. Standard
drag-and-drop and representative Windows format/offline acceptance remain
follow-up evidence, not a claim of this source integration.

### `microphone_controls.py`

This module is the UI-free foundation for issue #52. It normalizes microphone
inventories into stable identities that do not persist transient PortAudio
indexes (while retaining a current-snapshot index for a future stream adapter),
resolves a saved endpoint to `selected`, `default`, visible
`fallback_default`, or explicit `unavailable` state, and serializes only the
selected identity for a future configuration boundary. Ambiguous same-name
endpoints without a backend-native ID fail closed instead of routing to an
arbitrary device.

`RecordingControls`, `MaximumDurationPolicy`, `SilenceVADPolicy`, and
`RecordingBoundaryPolicy` keep duration/VAD decisions deterministic and UI- or
provider-free. Hard duration limits and silence detection are opt-in; the
defaults preserve the current no-auto-stop behavior. Policies report terminal
reasons but do not stop streams, publish transcripts, or own temporary WAV
cleanup. Settings integration, hot-plug handling, audio cues, and packaged
Windows acceptance remain follow-up work so the existing `Recorder` and
`RecordingSession` cleanup/cancellation contract is not duplicated here.

### `history_store.py` and `QtHistoryRecorder`

Defines the opt-in, local-only transcription history boundary for issue #53.
`HistoryRecord` accepts raw/refined text, workflow, timestamp, provider/model
identifiers, status, and concise error metadata; it has no audio, API-key,
provider-payload, or telemetry fields. `HistoryStore` is disabled by default,
uses a versioned JSON document with atomic same-directory writes, recovers an
intact interrupted snapshot when the primary is missing, enforces configurable
retention, supports delete-all, and exports TXT, Markdown, or JSON. The first
version intentionally avoids SQLite because the staged boundary has no search,
sync, or high-volume requirement.

The production Qt runtime creates a profile-relative store and subscribes
`QtHistoryRecorder` to terminal workflow states. The recorder queues writes
outside the UI thread and records only when local history is enabled.
React Settings and its QML controller expose
the opt-in and retention controls. Production Settings do not yet expose a
history browser, copy, export, delete-all, or retry controls; export and deletion
are storage APIs, and the old widget history page is a legacy surface.
See [the history boundary](history.md) for privacy and acceptance limits.

### `desktop_state.py`

Contains the older `WorkflowController` retained for backend and contract tests.
The production QML entrypoint uses the explicit command/state model in
`workflows.py` and does not instantiate this controller.

### `provider_http.py`

Defines the shared provider transport policy: operation-specific connect/read
timeouts, bounded retries for safe requests, typed errors, cooperative
cancellation, redacted rotating logs, and user-requested safe diagnostic
exports. Provider-specific adapters keep ownership of payload and response
formats. See [Provider HTTP reliability and diagnostics](http-resilience.md).

### `windows_hotkeys.py`

Owns native Windows `RegisterHotKey` registration, scoped low-level keyboard
and mouse hooks for modifier keys and side buttons, and Ctrl-key synthesis. The
typed `HotkeySettings` value in `hotkey_config.py` persists the five actions
(recording, rewrite, selected-text translation, voice translation, and
visibility) without coupling them to provider adapters. Legacy installations
are normalised to Alt+L, Alt+K, Alt+T, Alt+V, and Alt+R. Conflicts are rejected
before registration, and strict registration rolls back every accepted ID if
Windows rejects one combination; settings therefore cannot leave a stale or
partially active set.

The Qt backend owns hook installation, replacement, polling, and cleanup.
Callbacks queue action IDs to Qt and never record text. Standalone modifiers
run on clean release, so ordinary chords do not trigger them. Modifier Hold
recording starts after 200 ms and ends when released or used in a chord. Only
configured side mouse buttons are consumed. Injected input is ignored.

`RegisterHotKey` delivers key-down notifications and has no key-up edge. The
production Qt shell adds a scoped physical-key timer for Hold recording: key
release ends the recording, and Escape cancels it while the shortcut remains
held. Global Escape is also registered while the translation language picker
is open, so cancellation does not depend on Clarify taking keyboard focus.
The binding is released after a language choice or cancellation.
Selected-text translation always includes the chosen language's display name
in the provider instruction and source message. The chosen language takes
precedence over workflow prompt language requests; selected text is delimited
as source data so embedded requests are translated rather than executed.
The legacy adapter remains toggle-only. Packaged Windows builds exclude
the optional cross-platform `keyboard` module.

### `windows_clipboard.py`

Provides the Windows-only clipboard adapter. It snapshots and restores the
supported global-memory formats (text, HTML, RTF, and DIB images) without
attempting to read arbitrary clipboard formats.

### `local_asr.py` (optional Local Whisper provider and asset lifecycle)

Defines an isolated installer and lifecycle manager for a separately downloaded,
checksummed `whisper.cpp` Windows sidecar and model. `LocalASRProviderAdapter`
implements the typed provider-registry contract over the narrow
`LocalTranscriptionBackend` lifecycle seam. The application registers it as an
explicit provider and exposes its install/progress/cancel/remove flow in
Settings → Providers; installation remains an explicit product action and no
cloud fallback is implicit. The #32 signed MSI/update contract is for packaged
Clarify artifacts; this source-only sidecar harness does not claim
signed-release coverage or silently join that updater. It consumes the #18
`TranscriptionRequest.audio_bytes` snapshot;
`RecordingSession` remains the sole owner of the temporary WAV, while the local
adapter owns only inference cancellation and sidecar shutdown. Importing the
module never downloads assets; the application starts the sidecar only after an
explicit installed local route is selected. This product wiring does not by
itself prove the packaged Windows, offline, quality, performance, or cleanup
acceptance gates tracked in issue #23.

The workflow capture path requires a sequence-bearing snapshot; it retries
transient snapshot contention and otherwise fails closed rather than falling
back to an unsafe text-only check-and-set. The copy records the sequence before
Ctrl+C and the sequence observed by that copy, then uses the adapter's atomic
ownership check for restoration. A concurrent clipboard write therefore keeps
the user's newer contents intact, even when the copied selection has no text.

### `update_security.py`

Owns the manual update trust boundary. A Windows-trusted, publisher-pinned CAB
authenticates the strict release manifest. The module rejects unexpected
channels, versions, names, origins, checksums, sizes, or publishers; downloads
through a sibling `.part` file; and revalidates the MSI immediately before
launch. It does not own UI confirmation and never runs an installer by itself.

### `tests/`

The unit suite tests provider routing, URL construction, configuration,
clipboard safety, workflow state, usage statistics, and geometry calculations.
`tests/test_workflows.py` is deliberately separate from the provider suite and
runs the core application services without importing or constructing Tk.
Windows UI acceptance still requires a real packaged build because mocked tests
cannot reveal transparency, focus, DPI, or hotkey integration defects.

Repository behavior is covered separately by configuration, migration, and
statistics tests. Every repository write is JSON-encoded to a same-directory
temporary file, flushed, and atomically replaced. Unknown fields and malformed
values are ignored so a damaged or newer settings file cannot prevent startup.

### `repositories.py`

`ConfigRepository` and `UsageStatsRepository` are the application-facing
interfaces. `LocalConfigRepository` loads the existing flat settings format,
adds `schema_version`, and applies ordered idempotent migrations. Version 2
adds a nested workflow map while retaining flat keys as a compatibility
adapter, so existing transcription/refinement behavior survives migration and
older callers can continue to read their fields. Its typed `AppConfig` model
groups provider endpoints/model IDs, independent workflow routes, provider
selection, UI preferences, and startup settings. `LocalUsageStatsRepository` preserves the
anonymous event list and its existing `version` marker while also writing an
explicit `schema_version`. A file from a newer schema is loaded read-only for
compatibility; saves are refused until a version that understands that schema
is running, so a downgrade cannot delete newer fields. The same on-disk check
guards statistics appends, including when a fresh repository instance writes
without a preceding load. The legacy mapping adapter retains recognized
startup settings such as `autostart` during round-trips. Supported provider
choices and model canonicalization come from the provider registry while the
on-disk keys remain unchanged.

Settings apply through `LocalConfigRepository.apply`: all workflow routes are
validated first, then secure credentials and JSON are committed atomically.
Secret-store read-back or file-write failure restores the prior secret and
leaves the prior configuration recoverable. `reset_workflow` and
`test_workflow` provide UI-independent reset and capability-test operations;
neither operation sends transcript/prompt content to diagnostics.
Until the existing UI is migrated to typed routes, legacy flat saves compare
against the previous on-disk flat values and synchronize only the routes whose
legacy fields changed. Routes with a false provenance marker retain that
compatibility behavior, while explicitly authored routes in any scope remain
authoritative; endpoint-bearing legacy rewrite, translation, and local-ASR
routes therefore survive a shared provider change, while the primary
refinement route drops its endpoint when its provider/model is changed. All
independent custom routes survive an unrelated settings save.

### `dictionary_snippets.py`

The local dictionary and snippets are a separate, versioned non-secret profile
artifact. `LocalDictionarySnippetsRepository` owns its JSON schema, migration,
validation, and atomic replacement; it does not read or write provider keys
and therefore does not duplicate the `SecretStore` boundary. The
`DictionarySnippetService` keeps a validated in-memory snapshot for matching
and context construction. Snippet expansion derives canonical NFC spans from
the active Unicode database and walks a bounded prefix trie, so it is
provider-neutral and does not scale with every rule at every input character;
cloud adapters receive optional vocabulary through the typed
`TranscriptionRequest`. Local Whisper sends the bounded canonical vocabulary
as `initial_prompt`, including pause-processing segments. Optional refinement
receives a separate bounded context. Terms are hints, not forced replacements.
The React Dictionary page edits a draft through `qml_settings.py` and saves or
discards through the shared Settings transaction. Usage statistics
never receive dictionary or snippet content. `DictionarySettingsController`
keeps the Settings page's search, CRUD, reset, preview, and import/export
callbacks independent from Tk and delegates every mutation to the same
validated atomic service boundary. The complete Windows manual acceptance
matrix remains a release-check item for issue #50.

### `secret_store.py`

`SecretStore` is the provider-keyed `get`/`set`/`delete` boundary. Packaged and
source Windows runs use current-user DPAPI and persist only base64 ciphertext.
The configuration repository performs first-read migration: it writes the
legacy plaintext value, reads it back through the secret store, and only then
atomically removes that provider key from `config.json`. A backend, read-back,
or cleanup failure keeps the legacy value recoverable.

Experimental Linux and macOS source runs use a separate plaintext
`~/.clarify/secrets.json` fallback with mode `0600` where supported. This
fallback is intentionally explicit; it does not claim OS-backed protection.

## Data ownership

### Portable updates

`portable_updates.py` owns strict stable-version comparison, Ed25519 manifest
verification, bounded canonical GitHub downloads, binary checks, and atomic
replacement with recovery. The packaged `distribution/portable-update-policy.json`
pins the public key. Neither this module nor its Windows helper reads provider
credentials or user recordings.

`portable_update_windows.py` binds the helper to the installed executable's
path, hash, process ID, and creation time. It waits for graceful process exit,
stages on the installation volume, replaces the binary, and restarts an
independent PyInstaller process. A receipt after Qt, QML, and single-instance
startup confirms acceptance; failed startup restores the previous executable.
MSI-owned paths are excluded from this portable transaction.

`clarify/desktop/qml_updates.py` owns Qt state and worker cancellation. It
checks after startup and every six hours. `automatic_updates` is an optional
configuration boolean, off by default. Settings edits remain drafts until
saved. The composition root permits restart only when workflows, audio,
provider validation, and local-model work are idle, Settings are closed, and
no unsaved draft or result is open. Input is blocked during handoff.

Settings RPC exposes only explicit update status and actions. The QML home
pill shows availability and offers manual installation. Downloads, receipts,
and a failed-version marker live in `%LOCALAPPDATA%\Clarify\updates`; the latest
verified previous executable remains beside the installation. Old owned cache
attempts are pruned after 24 hours. Profiles and model data are outside this
boundary.

| Data | Location | Content |
| --- | --- | --- |
| Settings | `%APPDATA%\Clarify\config.json` | Provider endpoints, models, selections, and UI preferences; no API keys |
| Provider secrets | `%APPDATA%\Clarify\secrets.dpapi.json` | Current-user DPAPI ciphertext keyed by provider |
| Usage stats | `%APPDATA%\Clarify\usage_stats.json` | Counts, durations, model identifiers, and estimates; no transcript text |
| Dictionary and snippets | `%APPDATA%\Clarify\dictionary.json` | Versioned local terms, aliases, and bounded replacement rules; no credentials or usage events |
| Working audio | `%APPDATA%\Clarify\clarify-recording-*.wav` | One unique session-owned file, deleted after the provider no longer needs it |

On non-Windows source runs, the equivalent data directory is
`~/.clarify`.

For API keys, documented environment variables (`GEMINI_API_KEY`, legacy
`API_KEY`, `OPENAI_API_KEY`, and `GROQ_API_KEY`) override the stored credential
for that process and are never persisted. Other settings retain the precedence
of persisted settings, then their environment defaults, then built-in defaults.

Recordings use session-owned temporary WAV files. Cleanup must wait until no
provider, retry, or cancellation-Undo operation needs the audio. Process shutdown
and file cleanup are separate responsibilities; forced termination and cleanup
failures can leave artifacts. Do not promise secure deletion or assume a process
exit proves that audio was removed. The production lifecycle is implemented by
the Qt runtime and audio services, not the old Tk shutdown observers in `app.py`.

On Windows, a development host packaged with MSIX can redirect apparent AppData
paths into its virtual profile. Launch the installed app through Explorer and
verify the physical profile when investigating missing settings or models.
`scripts/deploy.ps1` uses this launch path and refuses to replace an app with an
active SoX recorder. Never merge, reset, or delete user profiles merely because
one launch context appears empty.

## Packaging

PyInstaller creates a one-file Windows executable containing the Python runtime,
PySide6/Qt Quick modules, QML assets, the compiled React/Tauri Settings child,
immutable distribution policy, and the vendored SoX runtime. The build verifies
that the embedded Settings child matches its input hash. `.env` is
never bundled. End-user provider settings are read from the user data directory.

The staged distribution workflow signs the executable, embeds it in a per-user
WiX MSI, signs that MSI and a release-manifest CAB, verifies the pinned
publisher, emits checksums, and creates GitHub provenance attestations. Public
enablement remains gated as documented in
[Windows distribution security](windows-distribution.md). The local-ASR
runtime and model are deliberately excluded from this one-file application.
The current PyInstaller command includes the pinned Local ASR manifest and
license notices in the executable payload; the maintainer harness remains
source-only. This bundled definition does not claim that the runtime/model are
installed, that a Windows sidecar has run, or that the offline/manual #23 gates
are green.

The GitHub release workflow builds on a Windows runner and publishes the
executable plus a SHA-256 checksum. `scripts/deploy.ps1` is a maintainer tool for
updating an existing local installation from WSL; contributors normally use
`scripts/build.ps1`.

## Legacy prototype

The incomplete Electron prototype was removed from the checkout. It remains
available in Git history and is not part of current development or distribution.
