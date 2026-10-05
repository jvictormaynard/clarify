# Portable update review for v0.5.0

This feature follows the reviewed dependency release v0.4.7. Requirements and
engineering were reviewed in sequential self-review passes. No independent
reviewer or subagent was used.

| Requirement | Result | Evidence |
| --- | --- | --- |
| Optional automatic installation | Off by default; only saved Settings affect the updater | Config, controller, RPC, and Playwright save/discard tests |
| Manual notification | Red dot on the home pill's Settings button; **Install update X.Y.Z** in its menu | Real QML render/interaction tests at 100%, 125%, 150%, and 200% scale |
| Background work | Checks after startup and every six hours; downloads and preparation run outside the Qt thread | Fake-worker controller tests; native process acceptance |
| Safe restart | Wait for idle workflows, no audio/model/provider work, no unsaved result/draft, and an ended Settings child | Composition review and controller restart/handoff tests |
| Portable executable replacement | Authenticate metadata; recheck bytes; wait for verified parent exit; stage on the installation volume | Frozen Windows replacement and receipt acceptance |
| Recovery | Keep the previous executable; restore and restart it on failed startup; prevent an automatic retry loop | Frozen Windows failed-startup case and failed-version marker |
| Cancellation/retry | Reject late worker results; isolate a new helper attempt from cancelled state | Controller cancellation tests and frozen Windows cancel/retry case |
| Authenticity | Pin Ed25519 key, repository, stable version, canonical URL, source SHA, size, and SHA-256 | Signature, malformed metadata, downgrade, redirect, interruption, and tamper tests |
| User data | Update only the executable and its owned cache; preserve profile/model locations and shortcuts | Path review; local deployment fingerprint verification |
| Native Settings | Flag visible, off by default, toggle/save/persistence, restore off, normal close | Isolated real Tauri window through Windows UI Automation |
| Packaging | Embed exact Settings binary, public key, and full crypto notices; add bundled OpenSSL to SBOM | Windows build/import smoke and embedded-payload checks |

Validation completed locally: 1,189 Python tests with four existing skips,
plus the new diagnostic-write recovery regression; 13 existing Playwright
tests and the added update save/discard test; pinned Rust/Settings build;
dependency audit with no reported vulnerability; runtime/build lock alignment;
Ruff, targeted types, compile checks, and community release preflight.
The Windows fixture suite tests replacement, cancellation/retry, startup
rollback, and modified-binary rejection using generated test keys. It uses no
user profile, live microphone, provider key, or model.

The review repaired stale-helper acknowledgment/retry hazards and ensured that
failed diagnostic writes cannot prevent relaunch of the previous installation.
A hidden Settings WebView can still own local unsaved fields, so restart waits
for its confirmed close.

The public executable remains unsigned by Authenticode. Ed25519 authentication
protects the portable update channel; it does not remove Windows SmartScreen
warnings. MSI-owned paths and the separate Authenticode CAB channel remain
excluded. Linux/source execution does not check or install Windows updates.
The unrelated Local Whisper Windows/offline gates remain documented separately.

Publication still requires the exact PR and merged main SHA to pass Linux,
Windows, and packaging CI. Tag publication must sign metadata with the protected
environment key, attest all eight assets, and pass post-release signature,
checksum, archive, SBOM, source-SHA, and latest-release verification.
