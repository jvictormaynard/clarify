# Mobile contributor guide

Apply the [root guide](../AGENTS.md), including Humanizer for prose. This is the
Clarify iOS app: Expo/React Native with a Swift module, keyboard and activity
extension. No Android app is included. Expo Go cannot load these native parts.

## Source and dependencies

- Use Node and the committed npm lockfile as defined in the
  [development guide](README.md#development). Read the installed Expo version in
  `package.json` and its matching versioned documentation before changing an
  Expo or React Native API. Use `npx expo install <package>` for SDK compatibility.
- `src/app/` owns Expo Router screens and layouts. Keep shared components and
  state outside that directory.
- `modules/clarify-core/ios/` owns account processing, audio and storage.
  `native/keyboard/` owns keyboard interaction and insertion.
- `app.json` and `plugins/` own generated native configuration. Generate the
  Xcode project in an isolated task worktree. Preserve existing generated output;
  do not hand-edit it as the source of a product change.

## Validation and delivery

Use [component selection](../docs/ci-delivery.md#selected-checks) for the affected
contract. Run `npm run check` for mobile JavaScript/TypeScript or shared-contract
changes; it includes types, lint, contracts and synchronization checks. Native
changes also need the applicable Swift, simulator and unsigned build checks.
Documentation-only work needs documentation validators, not mobile lint or types.
Keep tests isolated from user accounts, microphones, keys and recordings.

The repository uses GitHub Actions and Xcode for signed TestFlight delivery.
Follow [direct delivery](README.md#direct-testflight-delivery) and
[ios-testflight.yml](../.github/workflows/ios-testflight.yml). Use `mode=validate`
for manual validation without signing or upload. Signed publication requires
the reviewed immutable tag, exact source SHA and release authorization. EAS
commands in dated delivery records describe historical work.

Verify the signed IPA, upload, Apple processing and internal-group availability
separately. Source versions and a successful upload do not prove availability
or physical-iPhone acceptance. TestFlight is the production-identity candidate;
App Store handoff must authenticate its run/current attempt and immutable
evidence artifact ID/digest, then reuse the exact verified Apple build UUID.
Never rebuild it for store promotion or accept historical PR179 QA receipts.
The handoff prepares a manual Apple action and claims no submission or public
availability. Keep direct Xcode signing; no EAS provisioning or OTA update
contract is introduced. The optional direct-provider short-speech harness
has the [coverage limit documented here](README.md#short-speech-provider-harness).
