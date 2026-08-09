# Changelog

Notable user-facing changes are documented here. This project follows
[Semantic Versioning](https://semver.org/) for tagged releases.

## [Unreleased]

## [0.2.2] - 2026-08-09

### Added

- Added a no-cost community release workflow for the portable Windows app,
  including a SHA-256 checksum, runtime SBOM, ZIP archive, SoX source archive,
  and GitHub build provenance

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

[Unreleased]: https://github.com/jvictormaynard/clarify-voice/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/jvictormaynard/clarify-voice/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/jvictormaynard/clarify-voice/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jvictormaynard/clarify-voice/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/jvictormaynard/clarify-voice/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/jvictormaynard/clarify-voice/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/jvictormaynard/clarify-voice/releases/tag/v0.1.0
