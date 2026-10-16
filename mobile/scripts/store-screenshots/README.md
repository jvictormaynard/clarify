# Store screenshots of build 0.8.0 (29)

The isolated `iOS store screenshots` workflow reuses the simulator app built from
the exact published source `542b8a742634183bf7fb857305674968e96f559b` in the first
capture run. It verifies the archive checksum and source/version manifest before
use. The helper also supports a fresh simulator build when run without the reuse
argument. It does not rebuild
or upload an IPA, sign an app, change App Store Connect, or edit product code.

It captures onboarding, Home, Dictionary and the guest Account screen in
Portuguese, English and Spanish on fresh iPhone 17 Pro simulators. PNG files are
native 1206 × 2622 screenshots for the medium Dynamic Island iPhone slot required
by App Store Connect. They have no added captions, overlays or resizing.

After the first onboarding screenshot, the helper inserts synthetic examples
into that simulator's real local SQLite history and vocabulary. It selects the
completed-onboarding state with the existing standard UserDefaults launch
argument. It does not create a fake account or API key. It does not activate the
microphone, send an authentication email or invoke transcription providers.

The separate XCTest runner contains no product UI. It opens the real Clarify
container, waits for expected localized controls/data, selects its real tabs,
and saves `XCUIScreen` attachments. The workflow retains the original PNG files,
XCTest results, a reusable simulator-app archive and a provenance/hash manifest.
Simulator profiles are disposable and are removed after capture.

Review every screenshot before uploading it to the store. A successful capture
does not submit the App Store version or establish device acceptance.

References: [Apple screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)
and [Expo SDK 57](https://docs.expo.dev/versions/v57.0.0/).
