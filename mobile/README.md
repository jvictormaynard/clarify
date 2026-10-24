# Clarify for iOS — MVP

Expo application plus a small Swift keyboard extension. A Clarify account is
required for speech recognition and rewriting. Sign in with an emailed code;
no personal provider key is needed. Native bottom tabs contain Home, Dicionário
and Conta. Ajustes opens from the Account tab. Signed-out users return to the
account screen, including after an upgrade from the former personal-key mode.
SQLite keeps
vocabulary and an offline history copy. New signed-in transcriptions sync
automatically with desktop through the account. Guest and pre-upgrade records
remain local and are never uploaded. Account caches are isolated by endpoint and
user. Existing local history, vocabulary and stored personal keys are preserved;
personal keys no longer enable mobile processing. Signing out stops microphone
access and requires a new sign-in. See [history synchronization](../docs/history-sync.md).

Version **0.8.1 (30)** distinguishes unrecognized speech, transcription failures,
allowance limits and service capacity. The keyboard shows the cause within its
existing toolbar height. Managed short-speech processing uses plain vocabulary
spellings on the server. Failed requests are not repeated automatically; the
existing conservative usage accounting and rewrite fallback are preserved.

Version **0.8.0 (29)** adds automatic account-history synchronization with Windows
0.9.0. Sign in to the same account on both devices and create new transcriptions
on each. Original and revised text, timestamps and source devices are retained.
Pre-upgrade records and account-free history remain on their original devices
and are never uploaded. Pending account changes survive network failures and
app restarts. Deletions synchronize without restoring known deleted records.
The keyboard correction from 0.7.5 (28), accepted on the user's iPhone, remains
unchanged. The temporary opening-measurement screen is hidden after that acceptance.
The source-app return and keyboard-height integration retain private Apple APIs
for the authorized TestFlight experiment; this is not an App Store release.

Version 0.5.0 (20) shows the email field directly before the bottom tabs.
The same emailed code enters an existing account or creates a new one, without
a password. The personal-key alternative from that version is no longer available.
Signing in activates account processing automatically. The final step
explains keyboard installation; microphone permission is requested when needed.
An unfinished setup resumes on the next launch. Existing signed-in accounts
skip first-run setup after an upgrade. A setup preference contains no credentials.
Billing, translation and local models are outside this mobile release.

Version **0.7.3 (26)** fixes short speech such as “oi” when a personal Groq key
and dictionary are active. Whisper receives plain enabled spellings, bounded to
896 characters without splitting a term. Saved aliases, pronunciations and
enabled flags are unchanged; rewriting keeps its vocabulary context. Account
processing uses the same correction already deployed to the Clarify service.
Native tests, live synthetic-speech acceptance and signed TestFlight delivery
are required before reporting this candidate as available. Live acceptance is
explicitly enabled with the workflow's `short_dictation_acceptance` input and a
temporary `CLARIFY_SHORT_DICTATION_ACCEPTANCE` secret. It runs the production
Swift client with synthetic M4A clips, then checks dictionary and history
persistence. Remove the temporary secret after the run. It does not prove
physical microphone capture or insertion in another app on the user's iPhone.

Version **0.7.2 (25)** improves touch coverage between keys, sliding to adjacent
keys, fast overlapping taps and automatic capitalization after `.?!`. Local
correction protects active dictionary words, including terms just saved from
the keyboard. Start waits for a fresh source-app capture and uses the corrected
native callback signature. Two consecutive returns passed in a separate
Release simulator host; return after real microphone authorization still needs
testing on the physical iOS 26.6.2 device. The opening-height jump remains
unresolved and is explicitly deferred for this TestFlight release.

Version **0.7.1 (24)** adds a small Mobile or Desktop icon and label below each
history timestamp, using the same caption size. Earlier iPhone records default
to Mobile. History remains local; account dictionary and usage synchronization
do not transfer history between devices. Off and On align with the center of
the Home switch. Dark keys lift the system material instead of using a fixed
gray fill, with a stronger fill for increased contrast or reduced transparency.
The keyboard opening-height defect
reported in build 23 remains unresolved. This build does not include a sizing
workaround or the separate experimental installed-extension diagnostic.

Version **0.7.0 (23)** groups Home history by the device's calendar day, with
continuous rows containing text and time. A large switch above history turns
Clarify on or off, centered between Off and On. It reflects the native microphone state and shows loading
inside the same row. Home no longer contains a recorder.
Dictionary words use the same continuous table. The word editor has Cancel,
a centered title and Save in one header. Account uses compact identity, monthly
minutes/progress and account-action sections. Consumption excludes pending
reservations. These changes preserve local storage, account sync and BYOK.

The keyboard dictionary capsule uses a smaller, spaced plus symbol. After
inserting a dictation, a left-hand undo button removes only the inserted text;
redo restores it. Typing, changed selection/context, another document or keyboard
dismissal clears this temporary action. Secure or unavailable contexts fail
closed. Existing field text and replaced selections are preserved.

Keyboard height is published before view loading, and `sizeThatFits` uses the
same fixed height as Auto Layout fitting. Regression tests cover temporary
oversized proposals and repeated presentation through a real `UITextField`
input host. The actual WhatsApp extension transition still needs iPhone
acceptance. These fixtures do not prove that the device-reported jump is gone.
Use the direct workflow's `tests_only` input to run native checks without signing
or uploading an existing build number. Uploads retain the full check sequence.
Mobile versions are independent of the Windows release tags.

### Physical-device opening diagnostic — 0.7.4 (27)

This TestFlight candidate adds **Account → Settings → Keyboard opening test**.
It preserves the short-speech correction already shipped in 0.7.3 (26).
It does not change keyboard sizing or claim to fix the opening jump.
Select a label, open the ordinary text field, select that same keyboard with
its globe, and run ten dismiss/reopen cycles. Repeat with Apple and Wispr Flow.
The keyboard label is supplied by the tester, not discovered by the app.

A display link records the host keyboard layout guide and the composer's
presentation position. It requests the screen's maximum refresh rate and
exports callback/display/target timestamps so gaps in sampling remain visible.
iOS controls the actual cadence; no trace proves that every physical frame was
captured. Each phase waits for settled geometry; opening also requires the
system's did-show notification. Timeout, app interruption or dismissal stops
the run. The report retains individual samples, peaks and final heights.

The explicit share action exports temporary JSON with OS/app version, geometry,
timing and the keyboard label. It collects no audio, typed text, credentials or
library data and sends nothing automatically. Sharing completion removes the
temporary export. The tool is enabled only by the temporary containing-app
`ClarifyKeyboardDiagnostic` plist flag. Remove that flag after device acceptance.

### Installed keyboard opening diagnostic

The opening-height defect remains open. On the iPhone 17 Pro simulator
(iOS 26.5), the installed extension briefly reserves 553/598 points before
returning to 370. The ordinary keyboard-frame notification can report only
the final height. A `CADisplayLink` trace of the host's `keyboardLayoutGuide`
and visible composer captures the transient height. The test retains video
for comparison with the device recording. The system-keyboard control passes
in the same host. This simulator result does not establish behavior on the
reported physical iOS 26.6.2 device.
This is an observation, not a confirmed root cause or a validated fix.

Run `node scripts/test-keyboard-extension.cjs --check-opening-height` from
`mobile/` on macOS, or select both `tests_only` and `extension_diagnostic` in
the iOS workflow. The generated
UIKit host installs the real extension sources, tests the system keyboard as
a control, and checks initial switching plus four dismiss/reopen cycles. It
also verifies text insertion, sliding to a neighboring key, sentence casing
after `.?!`, and the bottom keyboard row. Two consecutive activation handoffs
must capture a fresh origin, consume the real one-use nonce and return through
the production native bridge. The fixture uses Release builds and synthetic
text, with no microphone, provider key or user profile.
The current extension is expected to fail the height assertion. The workflow
retains traces, screenshots, video and the result bundle for investigation.
Passing the separate in-process UIKit tests does not resolve this open gate.
No new signing or upload occurs when `tests_only` is selected.
Selecting both diagnostic inputs runs the installed-extension fixture directly;
regular tests-only runs and every signed upload retain all product checks.

Every signed upload runs the installed typing, casing and two-return checks
against production sources. It also records all five opening traces and requires
the final keyboard height and bottom row to be usable. The transient overshoot
assertion remains in the strict diagnostic above; the user explicitly deferred
that known defect to test the other improvements in build 25. This exception does
not allow typing, activation, final-height or native-control failures to pass.
Temporary sizing experiments have been removed from the workflow. An in-process
UIKit test alone is insufficient evidence for a correction to remote keyboard
geometry or return to a separate application.

Version 0.6.0 (22) adds a dictionary action to the keyboard toolbar when one or
two words are selected. Tap **Adicionar ao dicionário** to save without changing
the selected text. The button changes to **Salvo** and is disabled for an enabled
term or a durable pending addition. Labels follow Portuguese, English or Spanish.
Disabled terms are enabled again without losing aliases or pronunciation.
The app imports offline additions into the appropriate guest/account dictionary;
account words synchronize before the next hosted dictation. The toolbar keeps
the keyboard's existing height. Settings uses an icon-only native back button.

Version 0.3.0 (17) adds an optional shared account, vocabulary sync
and hosted Groq dictation through [`server/`](../server/README.md). Account login
uses email codes; sessions stay in the containing app's Keychain and never reach
JavaScript or the keyboard extension. Signed-in accounts use managed models
after explicit processing consent. Personal keys remain available after signing
out. Account vocabulary syncs automatically and usage updates after processing.
The interface and authentication email follow the device language: Portuguese,
English or Spanish. Local dictionary caches preserve offline changes. History stays local. The server is deployed at
`https://clarify-api.victormaynard.com`; hosted processing requires a dedicated
Groq key and an enabled beta budget. The approved global beta budget is US$10
per UTC calendar month, with up to 300 minutes per account. Both limits apply.
Google/Apple login is deferred. Build 16 does not include these account controls.

Version **0.2.2 (16)** handles blocked microphone activation with a Portuguese
recovery message instead of an Expo/native error. Calls have priority over the
app's recording session; finish the call or other recording before activating.
Every audio setup failure stops the engine, removes its tap, deactivates the
session and clears its active state. A later button press can try again.
Activation waits for the app to become active after permission or keyboard
handoff, and never opens the source app after a failed/interrupted activation.
Provider models and rewrite prompts are unchanged. Physical call/permission
flows still need iPhone acceptance; tests use synthetic native failures.

Previous verified TestFlight delivery: **0.5.0 (20)**, available to `Clarify Interno`
on 2026-10-11. [Direct delivery run 38122247572](https://github.com/jvictormaynard/clarify/actions/runs/38122247572)
passed native validation, signed archive checks and direct Apple upload.
Apple processing is `VALID` and the internal state is `IN_BETA_TESTING`.
For **0.6.0 (22)**, follow the [direct delivery workflow](https://github.com/jvictormaynard/clarify/actions/workflows/ios-testflight.yml).
The final Apple processing and internal-group availability are recorded in
[delivery PR 144](https://github.com/jvictormaynard/clarify/pull/144) after upload.

The `iOS TestFlight` GitHub Actions workflow tests and builds the application with
Xcode on a standard macOS runner, then uploads directly to App Store Connect.
It does not use EAS Build or EAS Submit. Apple processing and internal group
availability were verified separately from the upload.

Build 16 comes from source commit `0ccff93d7afde528544b2f3d4bf649b1442e7baa`.
[GitHub Actions run 38088125315](https://github.com/jvictormaynard/clarify/actions/runs/38088125315)
completed successfully: 13 JavaScript contracts, 25 Swift contracts, 19 UIKit
simulator tests, Expo Doctor, native compilation, distribution signature checks
and direct Apple upload. The downloaded IPA is 15,553,431 bytes, with SHA-256
`c573c6203c6174f7828183f2e0e21d296b0ca09b88d63d773e0a79835fda1a4b`.
All three bundles are version 0.2.2 (16). Apple build ID:
`8c8ed273-09ec-4dbf-9332-81846a731df1`; processing `VALID`, internal state
`IN_BETA_TESTING`, with the existing tester present in `Clarify Interno`.
The call/permission recovery, opening animation and automatic return still need
iPhone acceptance. Simulator checks do not prove the real system transition.
General [CI run 38088125314](https://github.com/jvictormaynard/clarify/actions/runs/38088125314)
also passed the Linux/Windows tests and Windows packaging job for that source.

## Experimental opening synchronization — 0.7.5 (28)

This TestFlight candidate synchronizes a measured keyboard height with UIKit's
remote rendering fence. It uses private Apple APIs, separately from the existing
experimental source-app return bridge. Runtime signatures and object types are
checked. Each fresh connection can publish once, after host readiness and during
a provisional keyboard layout; full-screen layouts and already settled layouts
are excluded. Reentrant layout, a replaced owner or a closing controller cancels
publication. The drawing fence is invalidated after the proxy call.

The isolated `872373c` experiment executed seven publications. Both retained
recordings showed four reopenings without the previous rendered key/composer
retreat or excess material. Capture gaps leave initial switching inconclusive;
these observations do not prove every physical display refresh was clean.
The strict guide-height diagnostic still fails. Do not describe this candidate
as a confirmed iPhone fix or as App Store compatible. Physical iOS 26.6.2
acceptance remains required. Disabling `allowsSelfSizing` alone also failed in
the captured pixels, so the existing self-sizing policy is retained.

`KeyboardHeightSync` owns this boundary independently of host-app resolution.
The fixture defaults to the unmodified distribution keyboard sources, with
diagnostic logs and layout instrumentation disabled.
Set `CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS=1` explicitly to trace publications.
The artifact retains the generated project and records this setting.
The installed-extension fixture compiles the product implementation directly.

## Direct TestFlight delivery

`.github/workflows/ios-testflight.yml` runs on application changes to the mobile
delivery branch `codex/ios-testflight`, and supports manual dispatch. Documentation
and ignore-file changes do not trigger another upload of the same build. Increase
`expo.ios.buildNumber` in `app.json` before each new upload. It remains the same
in the container, keyboard and activity. The workflow checks the JavaScript,
Swift and UIKit simulator contracts before creating an archive. Expo CNG generates
the native project; Ruby configures distribution signing only in that output.
Xcode exports the IPA, checks its signatures, bundle IDs, versions, app groups
and bundled license, then `altool` uploads it to Apple. No Expo login is needed.

The existing distribution certificate, three profiles and App Store Connect API
key are stored in GitHub Actions secrets prefixed `CLARIFY_IOS_` and `CLARIFY_ASC_`.
The runner uses a temporary keychain and removes signing files after the job.
Secrets are never committed or included in artifacts. The verified IPA, SHA-256
and simulator results are retained for seven days. An upload alone does not
establish TestFlight availability; verify `VALID` and `IN_BETA_TESTING` in Apple.

## Use

1. Open Clarify, enter your email and press **Continuar**.
   Confirm the account code inside Clarify. Account processing is enabled
   automatically. Read the processing notice before continuing. Account controls
   remain in Conta; keyboard, microphone and history controls are in Conta → Ajustes.
2. Add Clarify under iPhone Settings → General → Keyboard → Keyboards, and enable
   Full Access for the keyboard's shared command/result files.
3. Activate the microphone in Clarify, then return to the application you use.
4. Hold the keyboard microphone to dictate. Release to finish, or slide up
   28 points to lock. Tap the paper plane to finish a locked recording. This
   processes the dictation and inserts text; it does not send the host's message.
5. The app transcribes and rewrites through Groq. The keyboard inserts successful
   results only into the same document where the recording started. Otherwise,
   use Insert text. A rewrite failure preserves the original transcript for
   explicit insertion. Cancellation discards the current operation.

The app owns the microphone, including while backgrounded. Between clips, audio
buffers are discarded. There is no inactivity timeout: the microphone stays
active until the user switches Clarify off or iOS interrupts the session. A clip
still ends at five minutes. Calls, audio-route changes, and media resets stop
the session. iOS can also end a terminated app's session.
The system microphone indicator remains visible while the session is active.
Activate the session again after it expires. The inactive keyboard's “Começar”
button uses SwiftUI OpenURL to open the container and activate the session,
without starting a clip. A missing Groq key opens Ajustes first.

Automatic return is an experimental TestFlight feature explicitly authorized
by the user on 2026-10-10. On iOS 26.4+, a vendored MIT keyboard-arbiter hook
attempts a fresh host bundle-ID capture. The containing app tries to open that
bundle with LSApplicationWorkspace, then tries the system breadcrumb action.
On earlier versions, the candidate uses a guarded PKService/XPC lookup from the
attached keyboard's parent. It does not reuse a previous host or launch a guessed
app. The previous version had no host lookup on these iOS versions.
These are private Apple APIs: availability, behavior and store approval are not
guaranteed. No claim is made that Wispr Flow uses this implementation.
Runtime selectors and signatures are checked; errors fall back to manual return.
An App Group handoff has a single-use UUID nonce and expires after 120 seconds.
The URL cannot supply an arbitrary return destination. Permission denial,
inactive/background transitions and stale requests do not launch another app.
The originating bundle ID stays on this device and is never sent to Groq.
The third-party license is bundled with the keyboard; see third-party/.

The icon is rendered from the existing vector geometry with equal scaling on
both axes, centered, with 16% vertical margins. Regenerate assets/icon.svg and
the opaque 1024-pixel assets/icon.png with `python3 scripts/render-icon.py`
(development-only Pillow dependency). The app and keyboard use the native
`paperplane.fill` finish glyph; Expo Symbols and its Expo Font peer are pinned
to the SDK 57-compatible versions.

Temporary AAC/M4A audio is removed after processing or cancellation. The shared
container stores the current operation, last text and a short-lived activation
handoff. The app's private SQLite database keeps original/revised text and
vocabulary across launches. History starts with this version; previous versions
did not keep an archive. The keyboard never receives history or the API key.
It uses surrounding field
text locally for capitalization and spelling; that context is never saved or sent
to Groq. Local suggestions and correction undo are cleared when the keyboard closes.
The app sends directly to `api.groq.com`: `whisper-large-v3-turbo` for audio and
`openai/gpt-oss-20b` for rewriting. Groq's retention policies apply to cloud data.

The UIKit keyboard has a compact microphone bar above letters, numbers, symbols
and Portuguese accent variants (hold a letter, then move to the accent).
It follows the system keyboard appearance with public APIs. A local `UITextChecker`
adapter supplies Portuguese/English spelling suggestions. It corrects eligible
words on a separator, offers explicit suggestions, and lets Backspace undo the
last correction. It respects fields that disable correction and excludes URL,
email, numeric and secure fields. System lexicon terms are protected locally.
Names and technical identifiers can still require choosing the original spelling.
Apple's proprietary predictive keyboard, emoji panel and swipe typing are not embedded.
Character keys show an opaque enlarged press preview within the keyboard bounds.
Touch areas include the gaps between keys and the grid margins. Initial touches
route to the closest visible key rectangle; the same area applies during button
tracking and release. Accent choices retain their own touch handling. The
extension background is clear and nonopaque so it does not cover the system
keyboard material. iOS still controls the underlying blur and bottom bar.
Only show a language-switch key when `needsInputModeSwitchKey` requires it.
`hasDictationKey = true` disables Apple's dictation action; iOS controls the
bottom bar and can still show its icon. The icon remained visible in the iOS 26
simulator. No public API removes that system UI.
Start, upward lock and finish use retained, prepared standard medium-impact
generators. Typing uses a lighter impact. Generators do not depend
on the extension's remote window and do not scale the standard pulse intensity.
The host enables haptics before activating audio input. Start uses an original
short rising tone; finish uses a falling tone. The start cue is excluded from
captured audio. These are not WhatsApp assets. Haptic intensity needs iPhone acceptance.
While the microphone is held, two upward chevron tips appear inside its button.
The icon shrinks and shifts smoothly; Reduce Motion disables that transition.
The hint disappears after lock or release. Initial layout reports a fixed
278-point input height to UIKit and a fixed 220-point key grid. This addresses
the transient stretched keyboard seen in the supplied screen recording; the
actual host-app opening transition still requires device acceptance.

A local ActivityKit/WidgetKit extension shows the Clarify logo and microphone
state in the Dynamic Island and on the Lock Screen while the session is active.
It sends no push tokens, keys, recordings or transcript text. The session's idle
timeout, deactivation or audio interruption ends the activity. An abandoned
activity is ended at the next app launch; stale content asks to open Clarify.
Live Activities must be enabled on the device. iOS controls placement and priority.
This does not replace the system's microphone icon or orange privacy indicator.

The rewrite rules are generated from the desktop's canonical dictation prompt,
including spoken self-corrections, faithful editing and source-data boundaries.
Run `python3 scripts/sync-prompts.py` after changing the desktop rules; `npm run
check` detects drift. Mobile preserves the source language and has no custom
workflows. Vocabulary supports canonical terms, pronunciation, aliases and an
enabled flag, with the same limits as desktop (512 terms, 256 characters,
32 aliases). Active vocabulary is bounded context for ASR and rewrite, never
an instruction or unconditional replacement. Editing is disabled while busy.
Home pages through all saved results, newest first, and supports original text,
copying, individual deletion and clearing history without deleting vocabulary.
Keep mobile in this repository; Expo builds remain
independent and upload only the mobile directory.

The mobile source and direct build workflow are in this repository on
`codex/ios-testflight`, tracked by draft PR #138. No separate repository was created.

## Development

Use Node 22.21.1, the committed npm lockfile, and a native iOS build. Expo Go
does not include the custom module or keyboard. No Android app is included.

```sh
npm ci
npm run check
npx expo-doctor
npx expo prebuild --platform ios --no-install
npm run test:native # macOS with Xcode; also runs during each EAS build
npx expo export --platform ios
EAS_NO_VCS=1 EAS_PROJECT_ROOT="$PWD" npx eas-cli@24.12.0 build --platform ios --profile simulator
EAS_NO_VCS=1 EAS_PROJECT_ROOT="$PWD" npx eas-cli@24.12.0 build --platform ios --profile production
EAS_NO_VCS=1 EAS_PROJECT_ROOT="$PWD" npx eas-cli@24.12.0 submit --platform ios --profile production --id BUILD_ID
```

`src/app/` owns the three native-tab pages and system-link routing.
`src/components/` contains shared interface elements; `src/state/clarify.tsx`
owns the app snapshot and activation request. Home's switch uses that activation
flow and native deactivation. `src/press-to-talk.ts` retains the tested gesture
contract; recording controls are in the keyboard.
`modules/clarify-core/ios` owns microphone lifetime, Keychain, Groq
requests, local history/vocabulary, cancellation and shared state. `native/keyboard` owns keyboard
gestures, local spelling and safe insertion. `plugins/with-clarify-keyboard.cjs`
adds the keyboard and App Group; `plugins/with-clarify-activity.cjs` adds the
ActivityKit widget during prebuild. Native contract tests use a temporary
container and fake HTTP; they never use real keys, microphones or profiles.
The simulator and production profiles also run UIKit tests against the production keyboard
sources and exports actual light/dark key-preview captures as build artifacts.

## TestFlight and acceptance

The Expo project is `@victormaynard/clarify-ios`; it is separate from all existing
apps. Bundle IDs are `com.jvictormaynard.clarify` and the `.keyboard` suffix.
The verified Apple app record is `6820869157`, configured as
`submit.production.ios.ascAppId`. Store secrets outside this repository. The EAS
archive excludes native generated folders, local environment files and signing
credentials.

A successful simulator build is compilation evidence. A production build must
also be signed, submitted, processed by Apple, and available to a TestFlight
group. Those states do not prove physical-device behavior.

Before acceptance, test on an iPhone: keyboard setup; Full Access off/on;
microphone denial; link activation; app switch and return; hold/release; upward
swipe lock; square stop; cancellation during both network steps; airplane mode;
invalid key; 429; audio interruptions; headphones; session expiration; switching
fields during processing; repeated appearance without duplicate insertion;
light/dark themes; VoiceOver and large text. App Store review is a separate step.

The Expo 57 dependency tree has npm audit findings in build tools,
including `braces`, `node-forge` and `uuid`. Adding Router also introduces a
`decode-uri-component` advisory for malformed URL decoding. Native system URLs
are restricted to short, known routes and UUID activation tokens before reaching
the Router decoder; arbitrary paths and query parameters are discarded. This
does not remove the dependency advisory. Do not force incompatible SDK
downgrades or suppress advisories. Recheck compatible official fixes before
public distribution; record the actual audit with each candidate.

## Delivery evidence — 2026-10-08

- [Reviewed simulator build](https://expo.dev/accounts/victormaynard/projects/clarify-ios/builds/bbcb211f-21d2-454b-87a5-2277e5cbc1eb):
  finished, version 0.1.0 (1). Downloaded archive contains the app and keyboard,
  matching versions and App Group. SHA-256:
  `bdc11cc1e0cde786f5214ed07db3dd1e8b97411293290a0f6edb1a1c5eb5363d`.
- TypeScript, ESLint, five JavaScript tests, six native contract tests, iOS
  export, dependency compatibility and Expo Doctor 21/21 passed.
- Appetize iOS 26 simulator: key setup, microphone permission, app swipe lock,
  square stop, cancellation and invalid-key response checked. Safari keyboard:
  Full Access off/on, background recording, swipe lock, keyboard dismissal and
  reopening while locked, square stop and public link activation checked.
  No private launch API was needed.
- No real Groq key or personal audio was used. Successful live transcription,
  text quality, insertion into a real field and physical-iPhone acceptance
  remain open. The automated HTTP tests cover successful provider responses.
- The desktop Python suite ran 1,177 tests with five failures and five skips.
  A clean archive of starting commit `1c4dbadc4ee583d6dedc1f1fd4ce3496f834ece2`
  reproduced the same five failures (1,148 tests, five skips). The five tests
  pass when run alone in both trees. Desktop files were not changed by this task.
- npm audit: 22 findings, seven moderate and 15 high, in the Expo build-tool
  dependency tree. No forced downgrade or advisory suppression was applied.
- The first production attempt stopped before a signed build. The Apple login
  session was expired; direct API-key requests returned HTTP 403
  `FORBIDDEN.REQUIRED_AGREEMENTS_MISSING_OR_EXPIRED`. The account holder must
  resolve pending agreements. The next day's progress is recorded below.

## TestFlight delivery — 2026-10-09

The account holder accepted the pending Developer Program terms and renewed the
Apple ID CLI session. API access, App Group registration and assignment succeeded.

- [Production build](https://expo.dev/accounts/victormaynard/projects/clarify-ios/builds/d76b566a-a61b-4ea8-a5aa-7a9eaea56ef0):
  finished, version 0.1.0 (2), including six native contract tests with no failures.
- Downloaded signed IPA: SHA-256
  `6b028b276c4f743fc1f01130bc33d83623e632b8e469520d0da1ffa6939f705b`.
  App and keyboard have matching versions, device platform, App Group, active
  distribution profiles and team `8K353P3496`; neither profile allows debugging.
- [EAS submission](https://expo.dev/accounts/victormaynard/projects/clarify-ios/submissions/56cc5577-0b61-4fb6-a14b-c5846446516b):
  finished at 06:53:22 UTC; Apple received the binary.
- Internal group `Clarify Interno` was created with access to all builds. The
  owner's existing Apple account was assigned; no other testers were added.
- [TestFlight](https://appstoreconnect.apple.com/apps/6820869157/testflight/ios):
  verified at 06:55:49 UTC. Apple build
  `cff0eb7e-b1b2-4a19-bc72-b30afe31a3d4` is `VALID`, version 0.1.0 (2),
  with internal state `IN_BETA_TESTING`. The internal group's build list contains
  this exact build and its tester list contains the owner's account.
  Portuguese test instructions were saved in the build's TestFlight notes.
  It is available for internal testing; no external beta review or public
  App Store release was requested. Physical-iPhone and live Groq acceptance
  remain open.

## Platform evidence

- [Wispr Flow keyboard setup](https://docs.wisprflow.ai/articles/7453988911-set-up-the-flow-keyboard-on-iphone)
- [Wispr Flow background microphone session](https://docs.wisprflow.ai/articles/8415579688-why-wispr-flow-doesn-t-pause-background-audio-on-iphone-ios)
- [Apple keyboard sandbox](https://developer.apple.com/documentation/uikit/configuring-open-access-for-a-custom-keyboard)
- [Expo iOS app extensions](https://docs.expo.dev/build-reference/app-extensions/)
- [Expo local modules](https://docs.expo.dev/modules/get-started/)
- [Groq speech API](https://console.groq.com/docs/speech-to-text)
- [Groq active models](https://console.groq.com/docs/models)
- [EAS iOS submission](https://docs.expo.dev/submit/ios/)

## Keyboard update — 2026-10-09

- Desktop dictation prompt rules now generate `RewritePrompt.swift`, including
  self-corrections and faithful editing. The mobile route uses the same source
  delimiters, temperature 0.1 and protection against excessive text removal.
  Mobile keeps the source language; custom desktop workflows/dictionaries are
  outside this MVP.
- A UIKit key grid replaces the microphone-only panel. A compact top bar contains
  the microphone and recording status; cancellation is shown only while busy.
  Upward movement of 28 points locks recording in both app and keyboard.
  The integrated backspace replaces the extra delete button. The system provides
  language switching when possible; a fallback key appears only if iOS requires it.
- Original 90 ms start/finish cues and soft start haptics were added. The start
  cue and its audio buffer interval are excluded from the uploaded recording.
- Final checks: TypeScript, ESLint, five JavaScript tests, ten Swift contract tests,
  Python utility Ruff/compile, prompt synchronization, iOS export and Expo Doctor
  21/21 passed. The required desktop suite ran 1,177 tests in 443.638 seconds with
  the same five baseline failures and five skips documented above. npm audit still
  reports 22 existing build-tool findings: seven moderate and 15 high.
- Appetize iOS 26 candidates: keyboard rendering, letters, numbers, symbols,
  backspace, app/keyboard upward lock, cancellation, background recording,
  keyboard dismissal/reopening while locked, square stop, public activation link
  and invalid-key response were checked. Final simulator build
  [81e52acd-e0cb-409d-ac3c-58318e2f42d3](https://expo.dev/accounts/victormaynard/projects/clarify-ios/builds/81e52acd-e0cb-409d-ac3c-58318e2f42d3)
  finished, version 0.1.1 (3). Archive SHA-256:
  `b92363b27f8263611980b78470b4ac5393e756311986e8c5c96a68962999362d`.
- Appetize reached the account streaming limit. Accent selection, dark appearance,
  VoiceOver, haptic strength and cue volume still require physical-iPhone checks.
  CLI swipe actions did not verify a stationary accent hold; this is an open
  interaction check, not a successful test. No real Groq key or personal audio was
  used. Successful live AI output with the updated prompt also requires device
  acceptance. Apple's bottom dictation icon remained visible in the simulator.
- Sequential self-review covered requirements, UI construction, cancellation,
  once-only insertion, privacy, audio ownership and packaging. Review base/HEAD:
  `1c4dbadc4ee583d6dedc1f1fd4ce3496f834ece2`. All task edits stay under `mobile/`;
  pre-existing desktop/Settings edits were preserved. No commit or Git push was made.
- [Production build 5346e228-b54f-4b9a-8832-e511b776b3b4](https://expo.dev/accounts/victormaynard/projects/clarify-ios/builds/5346e228-b54f-4b9a-8832-e511b776b3b4)
  finished, version 0.1.1 (4), with ten native tests passing. Downloaded IPA SHA-256:
  `53f8e00a2dc7155cfa9d43a114ee93949bda6f4194c28424fb92cb4f12f71aee`.
  Host and keyboard have matching versions, signatures, device platform, App Group
  and team `8K353P3496`; neither provisioning profile permits debugging.
- [Submission 60e55bcd-2b27-4fc5-82d4-8f3c7e980043](https://expo.dev/accounts/victormaynard/projects/clarify-ios/submissions/60e55bcd-2b27-4fc5-82d4-8f3c7e980043)
  completed. [TestFlight](https://appstoreconnect.apple.com/apps/6820869157/testflight/ios)
  verified at 08:09:22 UTC: Apple build `6a85d1c4-e155-481d-9c05-b1c6e73f6481`
  is `VALID` and `IN_BETA_TESTING`, version 0.1.1 (4). `Clarify Interno` contains
  this build and the owner's existing tester account. No additional testers were
  added. Portuguese test notes were saved for this exact build.

## Spelling, key feedback and Dynamic Island update — 2026-10-09

- Local spelling uses the system Portuguese/English dictionaries and an ephemeral
  correction policy. Suggestions preserve valid words from either language.
  Nearby spelling and an accidental repeated letter take priority. A rejected
  correction stays rejected while editing that word. Undo and suggestion choices
  require matching document identity and cursor context before deleting text.
- Key margins, second-row inset, shift/delete widths, corners and dark colors
  follow the supplied reference. The opaque character preview appears above the
  pressed key without drawing outside the keyboard extension.
- Start, lock and finish feedback now has one owner per input path. The keyboard
  uses generators attached to its view on iOS 17.5+, retains and prepares them,
  and uses a lower intensity for keys. The app enables feedback before starting
  its recording session. This addresses missing lock/finish calls and the audio
  configuration; physical haptic output is not established by simulator tests.
- `ClarifyActivity` is a small native WidgetKit target for the existing microphone
  session. Its logo uses the geometry of the existing app icon. Activity content
  contains only the phase. It ends with deactivation and does not replace iOS
  privacy UI. No push service or new dependency was added.
- Checks: five JavaScript tests, sixteen Swift contract tests, three UIKit tests,
  TypeScript, ESLint, prompt synchronization and dependency compatibility passed.
  Expo Doctor passed 21/21. UIKit tests run in both EAS profiles, use production
  keyboard sources with a fake field, and export light/dark press captures.
- The required desktop suite ran 1,177 tests in 408.351 seconds: the same five
  baseline failures in `test_providers.ProviderTests` and five skips remain.
  Desktop source was not changed. No Settings or Windows packaging inputs changed.
- Sequential self-review covered requirements, edit/undo context guards, dictionary
  ordering, preview geometry/opacity, haptic ownership, activity lifecycle,
  source copying, target configuration and credential boundaries. Base/HEAD:
  `1c4dbadc4ee583d6dedc1f1fd4ce3496f834ece2`. Source stays under `mobile/`;
  unrelated edits and all existing profiles/demo artifacts were preserved.
- Open device checks: haptic strength and reliability, actual keyboard focus and
  correction in host apps, long-press accents/VoiceOver, cue volume, and Dynamic
  Island placement/lifecycle. Appetize remains over its streaming quota; no plan
  upgrade was made. Live Activities must be enabled. The system can prioritize
  another activity and still display its microphone indicator.
- [Production build 3834f17d-8972-4aaa-9356-368687bb691b](https://expo.dev/accounts/victormaynard/projects/clarify-ios/builds/3834f17d-8972-4aaa-9356-368687bb691b)
  finished, version 0.1.2 (6). Its post-install checks passed sixteen native and
  three UIKit tests, including the final preview position. Light/dark captures
  were downloaded and visually checked. These capture the production keyboard
  view in a UIKit simulator fixture, not a physical iPhone or a host-app session.
- Downloaded IPA: 9,133,730 bytes, SHA-256
  `1c954b13188e794042fab1fc4af1f8ecf39a5b1b90f1e42b1b44126ba8875b3a`.
  Host, keyboard and activity widget all report 0.1.2 (6), team `8K353P3496`,
  device platform and non-debug profiles. Signature resources are present.
  Host/keyboard App Groups match; the widget requires no shared container.
  Existing host/keyboard profiles and the distribution certificate were reused;
  only the new activity bundle received a new profile.
- [Submission 0b719daf-348f-41b5-baf0-96993c4b75fe](https://expo.dev/accounts/victormaynard/projects/clarify-ios/submissions/0b719daf-348f-41b5-baf0-96993c4b75fe)
  completed. Apple build `42f2feb5-75da-48a9-a222-15557e5aec76` is `VALID` and
  `IN_BETA_TESTING`, verified at 18:27:30 UTC. It is in `Clarify Interno` and the
  owner's existing tester membership is present. No new testers were added.
  Portuguese test notes were saved for this exact build. Update in TestFlight,
  open Clarify and activate the microphone before testing.

## Keyboard feedback update — 2026-10-10

- User reported no Clarify haptics while the Apple keyboard vibrated and System
  Haptics was enabled. Replaced view-bound, scaled impact generators with standard
  selection feedback for typing and light impacts for recording. This is a
  compatibility candidate; physical output has not been reproduced or verified.
- The gaps defect was reproduced by real UIKit tests in EAS build
  184585c3-e323-494b-8398-63e54a66ad82, version 0.1.3 (7): a gap touch selected
  no key, was rejected by UIButton tracking, and inserted no character. The
  baseline also had dead margins. Sixteen native contract tests passed.
- Expanded touch routing covers all keyboard pages, row gaps and margins.
  Button tracking uses the same nearest-key boundary; the accent picker and
  points outside the grid keep UIKit's normal behavior. Geometry is unchanged.
- Removed the explicit opaque light/dark rectangle from the extension.
- Sequential requirements and engineering self-review: base/HEAD
  1c4dbadc4ee583d6dedc1f1fd4ce3496f834ece2; changes confined to mobile/.
  All unrelated existing desktop, Settings and documentation edits were preserved.
- Physical iPhone gates: pulse output and relative strength, touch/hold/delete
  tracking, accent selection, and the actual host app's keyboard backdrop.
- The inactive keyboard button now shows the shared Clarify mark plus "Começar".
  Only that activation link is changed; the active microphone and upward-lock
  gesture remain. The link opens the container and activates the session after
  permission, without starting a clip. A missing API key opens key setup first;
  saving the key from this entry continues activation.
- The container explains how to return manually after activation. Apple DTS
  confirms there is no supported host-identification path for a generic round
  trip: https://developer.apple.com/forums/thread/826851.
  No private host lookup, suspension call, app list or automatic return is used.
- A dedicated keyboard activation URL keeps this entry distinct from the
  existing Live Activity URL. Concurrent activation calls share one request.

- [Production build 3f544398-9df1-47e5-80d9-c5bf35c7541f](https://expo.dev/accounts/victormaynard/projects/clarify-ios/builds/3f544398-9df1-47e5-80d9-c5bf35c7541f)
  finished, version 0.1.3 (8). Checks passed: seven JavaScript tests, sixteen
  Swift contract tests, seven UIKit tests, TypeScript, ESLint, prompt sync and
  Expo dependency compatibility. Clean iOS prebuild includes the shared logo in
  both extensions. The 56-file candidate manifest matches the uploaded source.
- UIKit checks cover standard haptic dispatch, one typing pulse per highlight,
  continuous hit areas and button tracking on three keyboard pages at three
  widths, and a nonopaque clear root in both appearances. These software checks
  do not establish physical haptic output or the host compositor's blur.
  Downloaded light/dark press captures were visually checked. They use production
  keyboard sources in a simulator fixture, not an actual host app on an iPhone.
- The required isolated desktop suite passed: 1,177 tests, zero failures and
  five skips, 358.690 seconds. Logging is closed before temporary-profile cleanup.
  No Settings or Windows packaging inputs changed.
- npm audit remains at 22 existing build-tool findings: seven moderate and
  fifteen high. No dependency changes, forced downgrade or suppression.
- Downloaded IPA: 9,143,917 bytes, SHA-256
  8a013166254a11968c011a32930a6c3557cf72b63de7f066cb9ec6704d3e0353.
  Host, keyboard and activity all report 0.1.3 (8), team 8K353P3496, device
  platform and non-debug profiles. Signature resources are present; host and
  keyboard App Groups match. Existing signing credentials were reused.
- [Submission f473d627-7e6a-43c7-bf4c-bf35b571a467](https://expo.dev/accounts/victormaynard/projects/clarify-ios/submissions/f473d627-7e6a-43c7-bf4c-bf35b571a467)
  is FINISHED at 07:35:48 UTC. The submitted build ID matches the production
  candidate above. Apple processing and TestFlight availability are checked
  separately.

- [TestFlight](https://appstoreconnect.apple.com/apps/6820869157/testflight/ios)
  verified at 07:38:13 UTC: Apple build b3626724-4c42-4c83-abee-a4a08590f77a
  is VALID and IN_BETA_TESTING, version 0.1.3 (8). Clarify Interno contains this
  exact build and the owner's existing tester membership is present. Portuguese
  test notes were saved for this build. No new testers or external beta were added.
- Automatic approval review rejected removal of a temporary fake-test profile
  directory with "blocked by policy" and no further reason. That directory was
  kept; it contains no live profile, API key or recording. This does not affect
  the signed build or TestFlight availability.

## Native tabs, library and experimental return — 2026-10-10

- Native bottom tabs now contain Home, Dicionário and Ajustes. Home shows the
  welcome message and pages through all new transcription results. It supports
  original/revised text, copying and deletion. SQLite persists history and the
  dictionary between launches. Earlier versions did not archive dictations.
- The dictionary uses desktop vocabulary fields and limits: canonical term,
  pronunciation, aliases and enabled flag. Active entries are bounded source
  context for both Groq steps. The canonical desktop rewrite prompt and single
  device-only Groq key remain in use. No backend or account was added.
- Typing uses a standard light impact; start, finish and upward lock use a
  standard medium impact. Two upward chevron tips appear while holding the
  microphone, with a short smooth icon transition and Reduce Motion support.
- A fixed initial input height and fixed key-grid height address the brief
  oversized keyboard in the supplied video. The iOS simulator checks initial
  fitting requests and an oversized host frame. Physical transition acceptance
  remains open.
- Automatic return after activation uses the private-API experiment explicitly
  authorized by the user for TestFlight. It attempts fresh source-app lookup and
  reopening, with a breadcrumb fallback and single-use expiring handoff. The
  inactive-only logo/“Começar” control activates the session without starting a
  clip. Private API compatibility and public App Store approval are not proven.
- Sequential requirements and engineering self-review covered data ownership,
  provider flow, cancellation, source freshness, UI and packaging. Repairs include
  canceling held recordings on page departure while preserving locked recordings,
  rejecting unrecognized external links before Router decoding, guarding runtime
  signatures, and compiling/testing file protection on iOS as well as macOS.
  Review base/HEAD: `1c4dbadc4ee583d6dedc1f1fd4ce3496f834ece2`.
  All task changes remain under `mobile/`; unrelated changes were preserved.
  No Git commit, push or separate repository was created.
- Final checks passed: TypeScript, prompt synchronization, ten JavaScript tests,
  Expo dependency compatibility and iOS export. ESLint has no errors and one
  warning about the intentional native-library revision dependency used to
  refresh Home. Expo Doctor passed 21/21. The isolated desktop suite passed
  1,177 tests with zero failures and five skips in 362.205 seconds.
- [Production build fb3a671d-2b5a-4927-91dc-c555f5bea068](https://expo.dev/accounts/victormaynard/projects/clarify-ios/builds/fb3a671d-2b5a-4927-91dc-c555f5bea068)
  finished, version 0.2.0 (14). It passed 25 Swift contract tests and 14 iOS
  simulator tests (nine keyboard tests and five storage tests). Final light/dark
  key-preview and upward-hint captures were downloaded and visually checked.
  These are production keyboard fixtures, not a full host-app or container UI test.
- Downloaded IPA: 15,746,890 bytes, SHA-256
  `24529e90e7d63f024f7cc7efa9f30feec49c2c1bff728d0bdb959be19f829fc1`.
  App, keyboard and activity widget report 0.2.0 (14), device platform, team
  `8K353P3496` and non-debug distribution profiles. Signature resources are present;
  host/keyboard App Groups match. The keyboard bundles the exact MIT license.
  Existing signing credentials were reused. The 71-file source manifest remained
  unchanged from upload through verification; only this delivery documentation
  was updated afterward.
- npm audit reports 28 findings: ten moderate and eighteen high, no critical.
  Router adds a malformed URL-decoder advisory to the existing build-tool tree.
  The system-link allowlist restricts that input path without suppressing the
  advisory or forcing an incompatible Expo upgrade/downgrade.
- [Submission d5d267f4-0534-49f9-ab11-6b23efdbcadc](https://expo.dev/accounts/victormaynard/projects/clarify-ios/submissions/d5d267f4-0534-49f9-ab11-6b23efdbcadc)
  is FINISHED at 08:59:57 UTC and references the exact production build above.
  [TestFlight](https://appstoreconnect.apple.com/apps/6820869157/testflight/ios)
  verified at 09:02:17 UTC: Apple build `038da945-0969-4e42-af59-f2d4f9869741`
  is VALID and IN_BETA_TESTING, version 0.2.0 (14). `Clarify Interno` contains
  this exact build and the owner's existing tester membership. Portuguese notes
  were saved. No additional testers, external beta or public release were added.
- Device acceptance remains open for automatic return from WhatsApp and Notes,
  physical pulse strength, the actual opening/switching keyboard transition, and
  the new tabs/history/dictionary interactions. Update in TestFlight, open Clarify,
  then test “Começar” from another app with the session deactivated. Confirm return
  before holding to dictate. Add a vocabulary term, dictate and check persistence
  after reopening the app. The previous version's successful user test is not
  proof of these new behaviors.

## 0.2.1 candidate — publication blocked on 2026-10-10

- The user confirmed that rewriting works well after comparing original and
  revised text. Groq processing, prompt, recording lifecycle and haptics are
  byte-identical to the starting source; no model or prompt change was made.
- The new one-second device video shows a position jump around 0.283 seconds:
  the keyboard appears too high for one frame while key sizes remain stable.
  The candidate publishes its preferred height before attachment, sets up the
  self-sizing input view and height constraint in its initializer, and allows
  width-only autoresizing. This is a proposed correction, not proof of the
  cause or of physical-device acceptance.
- The previous activation path skipped source lookup before iOS 26.4. The
  candidate adds the earlier PKService/XPC path with runtime checks and caught
  KVC exceptions. Missing fields return nil; no previously cached host is used.
  Source lookup and reopening still need a device test on the user's exact iOS
  version. The existing private-API TestFlight authorization applies.
- The locked-recording finish square is replaced with the native paper plane
  in the keyboard and container app. Finishing still transcribes and rewrites.
  The icon uses the existing mark at uniform scale with approximately 16%
  vertical margins. The opaque PNG is 1024 × 1024; its vector source and renderer
  are included. Expo Symbols 57.0.3 and Expo Font 57.0.4 are directly pinned.
- Local checks passed: prompt synchronization, TypeScript, ten JavaScript tests,
  dependency compatibility, iOS JS export, Expo Doctor 21/21, Node syntax and
  whitespace checks. ESLint has zero errors and the existing intentional Home
  revision-dependency warning. An isolated Expo prebuild passed; generated
  keyboard sources match the candidate and autolinking includes the core,
  symbols and font modules. This check generated its native project in a temporary
  directory; the pre-existing ignored native project was preserved unchanged.
- The isolated desktop suite passed 1,177 tests, zero failures and five skips
  in 370.278 seconds. Relevant Settings behavior and Windows packaging inputs
  were not changed. Sequential requirements and engineering self-review used
  base/HEAD `1c4dbadc4ee583d6dedc1f1fd4ce3496f834ece2`; unrelated dirty files
  and the starting `main` branch were preserved. No Git operation was performed.
- An EAS simulator build for the before-fix sizing regression was rejected
  after upload because the Free-plan iOS quota is exhausted. No build ID, native
  compilation, simulator test result, IPA, submission or TestFlight version was
  created. The candidate was restored after that attempt. Its additional sizing
  and missing-parent-field tests are pending on macOS, as are the existing Swift
  and UIKit suites for this exact candidate. Previous 0.2.0 results do not verify
  these changes. The quota message reports renewal on 2026-11-01.
- Resume with native regression checks and repair, then the production EAS
  build, exact IPA/signing verification, submission and Apple processing/group
  verification. Physical acceptance remains open for the opening jump and
  automatic return from WhatsApp and Notes. Current TestFlight remains 0.2.0 (14).
