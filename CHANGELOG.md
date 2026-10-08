# Changelog

Notable user-facing changes are documented here. This project follows
[Semantic Versioning](https://semver.org/) for tagged releases.

## [Unreleased]

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

[Unreleased]: https://github.com/jvictormaynard/clarify/compare/v0.5.3...HEAD
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
