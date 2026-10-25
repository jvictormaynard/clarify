# Changelog

Notable user-facing changes are documented here. This project follows
[Semantic Versioning](https://semver.org/) for tagged releases.

## [Unreleased]

## [0.11.0] - 2026-10-25

### Added

- Sign in or create an account with Google, Microsoft or GitHub on Windows and iOS. Keep email-code login and local cancellation. Provider credentials stay on the server.
- Configure voice snippets in desktop Settings and the iOS Snippets tab. Create, search, edit, enable or remove saved text, including multiline content.
- Synchronize account snippets between desktop and iOS with separate guest storage, offline caches and explicit conflict resolution. Apply hosted snippets once on the server.
- Show funded weekly account quotas as percentages with the next reset in local time. Keep pending reservations separate from consumed quota and explain unavailable funding.
- Add a public financial ledger and private account administration to the self-hostable server. Contributions and operating provisions determine processing availability.

### Changed

- Substitute spoken snippets after recognition and before optional rewriting so the model can edit the complete message. Preserve original transcripts, direct exact insertion for standalone triggers, and substituted text when rewriting fails. Do not substitute triggers produced by the model.
- Require a Clarify account for iOS processing. Preserve stored personal keys and local records during upgrade; account-free desktop routes remain available.
- iOS 0.11.0 (38) includes the interface and recording changes already delivered in build 37: four bottom tabs, first-presentation onboarding, an optional guide, tap-to-record controls and an audio waveform.

### Fixed

- Hosted dictation uses plain vocabulary spellings for short speech. Distinguish unrecognized speech from transcription, service-capacity and allowance errors. Preserve the transcript if rewriting fails, without repeating paid requests.
- Show localized processing causes instead of a generic quota warning. Preserve safe operation diagnostics and updated usage. Keep the full keyboard error visible within its existing height.
- iOS converts native microphone input to 24 kHz mono AAC, including inputs whose rate or channel count cannot be encoded directly. Preserve clip cleanup and cancellation.
- Keep a keyboard Cancel action effective when a result arrives late, after acknowledgement or timeout.
- Wait for automatic account refresh before iOS microphone activation, then verify the account and foreground state again.
- Preserve the browser origin during OAuth confirmation so Chrome accepts the protected form submission. Suppress cross-origin referrers.

### Security

- Update pinned desktop build and runtime dependencies. Keep account data isolated across sign-in, sign-out and endpoint changes.

## [0.9.0] - 2026-10-16

### Added

- Automatically synchronize new account transcriptions between Windows and iOS, with the original and revised text, creation time and source device. Keep pre-upgrade records and account-free history on their original devices.
- Add a Windows History page with bounded pages, complete text access and account-scoped delete and clear actions. Preserve large existing local records.
- iOS 0.8.0 (29): share new account history with desktop, preserve offline copies and retry pending changes automatically. Hide the temporary keyboard-opening measurement screen after device acceptance of the existing correction.
- iOS 0.7.1 (24): show a small device icon and Mobile or Desktop below each history timestamp. Preserve the source in each record and identify earlier iPhone records as Mobile. History remains local.

### Fixed

- Preserve pending history changes after network failures and app restarts. Prevent deleted account records from returning through stale synchronization.
- Reject late history responses and actions after sign-out, account changes or endpoint changes. Remove only the deleted account's local cache.
- Keep Windows Settings responsive with large histories and capture account ownership before fast operations complete.
- iOS: preserve the keyboard-opening correction accepted on the user's iPhone in 0.7.5 (28), short-speech transcription with vocabulary, improved key touch coverage, sentence capitalization and the experimental source-app return.
- Center the iOS Home switch vertically between Off and On. Increase dark keyboard key separation from the system material on brighter backgrounds, while preserving the transparent keyboard surface.

### Changed

- Document synchronized account-history storage and deletion. Preserve personal provider keys, local-only modes and the existing hosted allowance.

## [0.8.0] - 2026-10-12

### Added

- Windows shortcuts accept standalone Ctrl, Alt, Shift and Windows keys, plus the two side mouse buttons. Ordinary keyboard combinations keep their behavior.
- Hover over the pill's language flag to open an animated vertical list of all supported dictation languages.
- iOS keyboard: select one or two words to add them directly to the dictionary. The localized action confirms Saved, prevents duplicate additions and preserves the selected text. Offline additions stay on the device and account words synchronize automatically.
- iOS keyboard: undo or redo the last inserted dictation from the toolbar. Preserve existing text and clear the action after typing or changing the document context.

### Changed

- Activate Clarify processing when signing in, including for existing signed-in profiles. Remove the separate activation step and preserve personal settings for account-free use.
- Show consumed minutes with a quota progress bar. Keep account sign-out and deletion in a collapsed Danger zone with visible buttons and separate confirmation dialogs.
- Hide the Text settings page when Clarify manages its models and instructions.
- iOS 0.7.0 (23): show history in continuous tables grouped by local day, remove the Home recorder, and use continuous dictionary rows. Center the word-editor title between Cancel and Save.
- Simplify the iOS account page into identity, monthly usage and account actions. Show actual consumed minutes, a percentage and an accessible progress bar.
- Add a large Clarify switch above Home history. Keep the microphone session active until the user switches it off or iOS interrupts it; remove the five-minute inactivity timeout and retain the five-minute limit per recording.

### Fixed

- Show loading while the account quota is unknown, instead of displaying 0 of 0. Start the query after startup operations finish and allow retry after a failed query.
- Remove the quick-menu divider above Settings and the empty space from hidden update actions.
- Release global shortcuts while capturing a new binding, so existing keyboard and side-mouse shortcuts cannot trigger a workflow or prevent capture. Restore bindings on cancellation and window close.
- Show only the native back chevron on iOS Settings, instead of the internal “(tabs)” route name.
- Scale and space the keyboard dictionary plus symbol. Publish the keyboard height before view loading and keep fitting requests independent of temporary host frames.

## [0.7.0] - 2026-10-11

### Added

- Use the device language for Portuguese, English and Spanish throughout the desktop and mobile interfaces. Authentication emails use the same language and a localized subject without a brand prefix.
- Route desktop selected-text rewriting, translation and imported audio through the Clarify account when signed in, with fixed server models and bounded processing.

### Changed

- Separate managed-account settings from personal keys, providers and local models. Keep personal settings and vocabulary when switching accounts or signing out. An expired session requires sign-in or an explicit return to account-free mode.
- Synchronize account vocabulary automatically after sign-in, on foreground entry and after edits. Refresh usage after processing, with a one-minute foreground refresh interval and conflict protection.
- Keep local settings, dictionary caches and history for offline use and account-free operation.
- Apply the same passwordless steps, full-width fields, Back action and initial “Continue without an account” link on both platforms. Put the mobile link outside the authentication card.
- Use stable button labels with integrated loading indicators. Describe managed data processing using Clarify in the interface.
- Prepare iOS 0.5.0 (20) for direct TestFlight delivery, separately from the Windows release.

### Fixed

- Prevent stored personal providers from receiving managed-account operations or being contacted by hidden model controls.
- Preserve reported usage when a completed operation is cancelled locally, and prevent stale refresh responses from replacing newer consumption.

## [0.6.0] - 2026-10-11

### Added

- Optional Clarify accounts on Windows and iOS. Receive an email code and confirm it inside the app, without a password or browser link.
- Show the email field on first launch. One passwordless code flow enters an existing account or creates a new one. Keep a small link for account-free setup; Windows links directly to local models. Preserve existing profiles and resume unfinished setup.
- Connect the personal dictionary to the account and sync vocabulary between Windows and iPhone. Concurrent edits preserve both copies for explicit conflict resolution.
- Optional hosted Groq transcription and rewriting with a shared monthly allowance. Local models and personal API keys remain available; signing in does not enable hosted processing automatically. Hosted availability depends on the service's global beta budget.
- Open-source iOS client, keyboard extension and self-hostable account service in this repository. iOS 0.4.1 (19) adds the unified first-run flow and Account tab for internal TestFlight delivery, separately from the Windows release.

### Security

- Keep account sessions in Windows DPAPI or the containing iOS app's Keychain. Apply verified-account checks, request and concurrency limits, bounded audio, idempotency and atomic usage/cost reservations to hosted dictation. Provider credentials remain on the server.

### Changed

- Add the Account page to Windows Settings and an iOS Account tab with a settings button and a sign-in invitation for account-free users. History and snippets remain local in this release.
- Use the Clarify mark without an icon background in the account setup screens.

## [0.5.3] - 2026-10-08

### Changed

- Separate dictation, text rewrite, and translation provider policy from the Qt runtime. Keep existing prompts, route selection, cancellation, dictionary expansion, and original-transcript recovery, with direct tests that run without a desktop framework.
- Document the current local-history integration and distinguish its storage APIs from the controls available in production Settings.

## [0.5.2] - 2026-10-08

### Changed

- Organize Settings into focused pages, reusable controls, shared draft operations, and separate style files. Add a source map for contributors and typed frontend command arguments. Preserve the existing pill, recording engine, and portable update behavior.

### Fixed

- Associate Settings field labels and help text with their controls, improve instruction placeholder contrast, and avoid duplicate model requirement entries.

## [0.5.1] - 2026-10-06

### Fixed

- Focus the first language when opening the translation picker. Use Up and Down to move through the languages, including from either end of the list, and Enter to select the focused language.

## [0.5.0] - 2026-10-05

### Added

- Check for new stable Windows portable releases in the background. Show a red notification dot on the home pill's Settings button and an **Install update** action in its menu.
- Add optional **Atualização automática** under General Settings, disabled by default. When enabled and saved, download updates in the background, wait for active work to finish and Settings to close, then install and restart Clarify.
- Authenticate update metadata with a pinned Ed25519 key and recheck the executable's size and SHA-256 before installation. Keep the previous executable and restore it if the new version fails to start. Preserve settings, provider credentials, models, and shortcuts.

### Security

- Restrict automatic updates to stable canonical GitHub releases with signed metadata. Reject altered files, downgrades, unexpected download hosts, and MSI-owned installations. Keep the separate Authenticode MSI channel gated.

## [0.4.7] - 2026-10-05

### Security

- Update the bundled HTTP transport to urllib3 2.8.0 to fix HTTPS proxy TLS policy separation, unbounded chunk headers, and a deflate streaming loop.
- Update the locked wheel and Tauri CLI build tools with archive-handling and Windows command-execution fixes.

### Changed

- Update Vite, CycloneDX, and Ruff with build, schema path, and validation fixes. Keep the native Settings runtime and provider behavior unchanged.

## [0.4.6] - 2026-09-30

### Changed

- Reduce dictation cleanup latency on the official Groq GPT-OSS models with a low reasoning budget while preserving unique content and clear spoken corrections.
- Use complete recording snapshots for experimental recognition during recording on compatible NVIDIA GPUs. Reuse a snapshot only when it covers the final recording through a verified quiet tail; otherwise transcribe the complete recording. The option remains off by default.

### Fixed

- Accept cleanup that removes exact repeated sentences while retaining every unique sentence, without weakening recovery for substantial content loss.
- Keep the original transcript when a text provider stops at its output limit, instead of delivering incomplete text.

## [0.4.5] - 2026-09-30

### Fixed

- Preserve the main pill's hidden state after cancelling or completing selected-text translation, including a shortcut pressed during the hide animation.
- Keep the translation picker layout throughout its fade-out so the home pill does not flash when closing the picker or choosing a language.

## [0.4.4] - 2026-09-27

### Fixed

- Keep the selected-text translation picker compact, with a vertical language list, rounded flags sized to match the initial pill, and the same interface scale and dark styling.
- Let Escape cancel the translation picker while keyboard focus remains in the source application.
- Allow dragging the translation picker with the same native window movement as the initial pill, without choosing a language during a drag.
- Always send the selected target language to the translation provider, including when the default or a custom workflow prompt is configured.

## [0.4.3] - 2026-09-19

### Changed

- Refresh the pinned Settings, Python packaging, syntax highlighting, and HTTP encoding dependencies.

### Fixed

- Ignore the visibility shortcut during an active recording so the compact home pill cannot overlap the recording pill; restore the shortcut after recording stops or is cancelled.

## [0.4.2] - 2026-09-15

### Changed

- Update the Qt desktop runtime to 6.11.2 and refresh its matching source archives and notices.
- Update the Settings interface dependencies to React 19.3 and Lucide 1.43, with TypeScript 7 and Vite 8 for builds.
- Update sounddevice and the dependency validation tools, and refresh the pinned release authentication and provenance actions.

## [0.4.1] - 2026-09-15

### Fixed

- Preserve speech across long Local Whisper recordings by keeping internal segment timestamps enabled.
- Keep the original transcript when optional rewriting removes most of its content, with the existing recovery warning.
- Restore the recording and processing pill above other windows whenever it appears, without changing keyboard focus.

## [0.4.0] - 2026-09-13

### Changed

- Settings use React and Tauri with an integrated title bar and a scrollable content area.
- Save and discard actions appear in a floating bar only when preferences change.
- Added explicit handling for unsaved preferences and service credentials; invalid recording values cannot be saved.
- Windows builds include and verify the Settings executable; CI checks its frontend, Python bridge, and native build.
- Updated contributor guidance and documented production and legacy boundaries.
- Reconciled pending local work with the published local-model improvements.
- Updated release instructions to use the current main branch and production entrypoints.
- Portable packages include verified Qt license notices; corresponding Qt/PySide source archives are provided with the release.

### Added

- A Dictionary page for personal vocabulary hints used by transcription and optional refinement.
- Hold-to-record keyboard activation, with Escape cancellation while the shortcut is held.

### Fixed

- Kept the Settings title bar outside page scrolling.
- Local deployment launches through Explorer to avoid inheriting an isolated application data profile from the development host.

- Local deployment now stops the executable at the installation path, including legacy ClarifyVoice.exe installs.
- Preserve the exact original transcript when optional refinement fails, with a brief status warning and partial history record.
- Respect cancellation after refinement and keep existing same-audio retry, cancellation undo and focus-safe delivery.
- Release local-model callbacks when Settings closes or switches models, preventing retained controllers and an intermittent native crash.
- Clear picker searches when reopening during the closing animation, so other installed models remain available.

### Removed

- Removed the unused Electron prototype; excluded unused optional Qt modules from the portable build.

## [0.3.0] - 2026-09-06

### Added

- Local Whisper Base, Small and Medium profiles with CPU and compatible NVIDIA GPU support.
- One model installation prepares available devices, reuses verified model files and measures the fastest device for Automatic mode.
- Experimental processing during speech pauses, disabled by default.
- Explicit transcription retry, cancellation undo and focus-safe quick actions.

### Changed

- Renamed the application and downloads to Clarify.
- Reduced local startup delay with model preparation during recording and idle retention.
- Improved refinement instructions for spoken corrections and lists.
- Buttons and selectors use the hover background for click, selection and focus without a bright focus border.

### Fixed

- Restored the compact settings interface and reliable Settings navigation.
- Kept the destination field focused when the toolbar returns before pasting.
- Added content-free refinement outcome and stage latency diagnostics.

## [0.2.2] - 2026-08-09

### Added

- Added a no-cost community release workflow for the portable Windows app,
  including a SHA-256 checksum, runtime SBOM, ZIP archive, SoX source archive,
  and GitHub build provenance
- Added a repository Git hook that formats staged Python files before commit

### Changed

- Kept the paid Authenticode signing, MSI, and authenticated update workflow
  manual until sponsored signing infrastructure is available

## [0.2.1] - 2026-08-09

### Fixed

- Made the Windows release type-check gate portable across the supported
  Python environments so tagged release builds can complete successfully

## [0.2.0] - 2026-08-09

### Added

- Added a staged per-user Windows MSI, authenticated release-manifest contract,
  explicit in-app update check, atomic download verification, and rollback-safe
  installer tests
- Added managed signing, publisher verification, provenance attestation,
  certificate rotation, and emergency revocation documentation and release
  gates
- Replaced the desktop frontend with a native Qt Quick/QML shell connected to
  the real workflow runtime
- Added workflow-focused Settings pages for General, Shortcuts, Recording,
  Speech-to-text, Text processing, and Integrations
- Added configurable global shortcuts, microphone selection, recording limits,
  voice-activity controls, local history, dictionary snippets, audio-file
  import, and voice translation
- Added opt-in Local Whisper onboarding with verified runtime and model
  lifecycle management

### Changed

- Separated provider credentials from workflow routes so each workflow can use
  its own provider, model, endpoint, enablement, and prompt settings
- Refined the QML interface with scalable sizing, minimal sidebar navigation,
  local SVG icons, rounded language flags, and reliable dropdown controls
- Applied fade animations to transient controls while keeping page navigation
  immediate and stable

### Fixed

- Showed completed recording results immediately without a separate View step
- Rearmed recording and the Alt+K, Alt+T, and Alt+L actions after a terminal
  result without requiring Dismiss
- Fixed Windows QML dropdown options, microphone refresh controls, and several
  alignment and asset-loading issues
- Gave each recording an explicit session owner with unique temporary audio,
  bounded SoX shutdown, cancellation, stale-worker protection, and cleanup on
  success, failure, cancellation, and application exit
- Moved stale SoX discovery out of the first-audio hot path and coordinated
  shutdown with active provider uploads before the final cleanup retry
- Removed legacy and session-pattern WAVs left behind by an interrupted
  startup on Windows, while keeping cleanup limited to the exclusively owned
  app data directory
- Kept failed-cleanup sessions owned until a bounded retry succeeds, preventing
  a later recording from overwriting an unremoved temporary WAV
- Kept UI ownership observers alive through the bounded cleanup policy so a
  late successful retry releases the session, while exhausted cleanup remains
  deterministically owned and observable
- Made each recording's terminal outcome immutable; cleanup failures no longer
  rewrite a published `completed` or `cancelled` state
- Retained rapid stop requests issued before recorder startup publication and
  bounded provider-worker shutdown joins without deleting an in-use WAV
- Snapshotted recording bytes before long provider uploads so cleanup no longer
  depends on a Requests read timeout or an in-flight provider file handle

### Security

- Moved Windows provider API keys out of `config.json` into a current-user
  DPAPI-backed secret store with verified legacy migration and explicit
  non-Windows source fallback behavior

## [0.1.2] - 2026-07-31

### Fixed

- Allowed short and sub-second recordings to be transcribed while preventing
  an immediate stop from racing microphone startup

## [0.1.1] - 2026-07-27

### Fixed

- Preserved provider-card borders with CustomTkinter 6
- Removed the initial microphone capture delay caused by stale-recorder cleanup
- Restored reliable `Alt+R` visibility toggling after `Alt+T` translations
- Restored the standard fade-in when the main window returns after translation
- Shared native layered-window types to prevent Windows transparency failures
- Made Windows release-source downloads resilient to redirects and transient
  network failures

### Changed

- Updated CustomTkinter, Pillow, sounddevice, Requests, and PyInstaller
- Isolated maintainer deployments from system Python dependencies

## [0.1.0] - 2026-07-19

### Added

- Open-source project documentation and contribution guidelines
- Automated Windows setup, build, CI, and tagged-release workflows
- Native system-tray branding and expanded interface languages on the active
  development branch

### Changed

- Clarified the Python application as the maintained implementation
- Archived the incomplete Electron prototype under `legacy/`
- Removed the redundant vendored SoX ZIP while retaining the runtime and license

### Security

- Local `.env` files and API keys are excluded from portable builds

[Unreleased]: https://github.com/jvictormaynard/clarify/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/jvictormaynard/clarify/compare/v0.9.0...v0.11.0
[0.9.0]: https://github.com/jvictormaynard/clarify/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/jvictormaynard/clarify/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/jvictormaynard/clarify/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/jvictormaynard/clarify/compare/v0.5.3...v0.6.0
[0.5.3]: https://github.com/jvictormaynard/clarify/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/jvictormaynard/clarify/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/jvictormaynard/clarify/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/jvictormaynard/clarify/compare/v0.4.7...v0.5.0
[0.4.7]: https://github.com/jvictormaynard/clarify/compare/v0.4.6...v0.4.7
[0.4.6]: https://github.com/jvictormaynard/clarify/compare/v0.4.5...v0.4.6
[0.4.5]: https://github.com/jvictormaynard/clarify/compare/v0.4.4...v0.4.5
[0.4.4]: https://github.com/jvictormaynard/clarify/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/jvictormaynard/clarify/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/jvictormaynard/clarify/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/jvictormaynard/clarify/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/jvictormaynard/clarify/compare/v0.3.0...v0.4.0
[0.2.2]: https://github.com/jvictormaynard/clarify/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/jvictormaynard/clarify/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jvictormaynard/clarify/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/jvictormaynard/clarify/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/jvictormaynard/clarify/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/jvictormaynard/clarify/releases/tag/v0.1.0

[0.3.0]: https://github.com/jvictormaynard/clarify/compare/v0.2.2...v0.3.0
