# Clarify Settings

React/TypeScript with reusable Base UI controls and Tailwind CSS, hosted by
Tauri 2 / WebView2. Settings use the web UI;
the recording engine and pill remain in Python/Qt.

## Source map

```text
src/
  main.tsx                    React entrypoint
  app.tsx                     Window layout, navigation and page selection
  components/                 Reusable controls and shared Settings views
    primitives/               Base UI controls, variants and overlay composition
    settings-navigation.tsx   Grouped sidebar navigation
  lib/utils.ts                Conditional and merged utility classes
  pages/                      General, Dictation, Text, Dictionary, Shortcuts, Models
  settings/
    bridge.ts                 Typed commands and serialized Settings state
    use-settings.ts           Drafts, operations, save/discard and navigation
    use-settings-window.ts    Native close requests and window lifecycle
    recording.ts              Recording draft conversion and validation
    settings-dialogs.tsx      Confirmation and shortcut dialogs
    navigation.ts             Page IDs, labels and icons
  styles/
    tokens.css                Colors, type, spacing, radius and motion values
    base.css                  Document defaults
    components.css            Common control states and dialogs
    primitives.css            Shared overlay surfaces and opaque fallbacks
    pages.css                 Feature-specific layouts
    layout.css                Window layout and responsive overrides
```

Add a page under `pages/`. Use the controls in `components/ui.tsx`:
`Button`, `Field`, `Input`, `TextArea`, `Picker`, `Toggle`, `Row`, `Section`, and
`Confirm`. `Field` owns the input label and help-text association. `Toggle`
provides the same association for switches. Base UI imports belong in
`components/primitives/`; page code uses the facade and does not duplicate
keyboard, focus or popup behavior.

Put multi-command operations in `use-settings.ts`. Its operation boundary owns
ordered transactions, local pending states, errors and success updates. Choice
controls persist only their preference. Text drafts remain local until a contextual
save or the explicit save-all action on close. Native close handling has its own hook. Command argument
tuples in `bridge.ts` check frontend callers; the Python allowlist remains the
runtime authority. Keep providers, persisted configuration and credentials in
their existing Python owners.

Use `styles/tokens.css` for shared values and common theme roles. Keep values
specific to one component with that component's styles. Keep feature geometry in
`pages.css` and window geometry in `layout.css`. The Qt/QML pill retains its
existing theme and behavior. Settings tests cover help-text associations,
placeholder contrast, keyboard selection, drafts, persistence and window geometry.

The [desktop design system](../docs/desktop-design-system.md) records the pinned
shared tokens, component rules and UX contracts.
`Section` places its heading above a shared `.section-content` panel. Sidebar
buttons remain available during settings operations. Managed-account visibility
applies to navigation and the rendered pages. Global Settings search is omitted;
long option lists and libraries retain their own filters.

The Python engine remains the sole owner of configuration, secrets, audio,
shortcuts and clipboard delivery. `clarify/desktop/qml_web_settings.py` defines a
small allowlisted protocol over QProcess stdin/stdout. Saved API keys are not
included in snapshots. No HTTP listener, browser filesystem API or shell API
is exposed. The frontend has no production mock-data fallback.

## Development

Use Node 22 or newer, Rust, and the Tauri platform prerequisites. On Windows,
install the Visual C++ build tools, Windows SDK and WebView2 runtime.

```
npm run build:settings
npm run deploy -- -SettingsExecutable <absolute-path-to-dist/clarify-settings.exe>
```

Run these commands from the repository root. `scripts/build.ps1` also accepts
`-SettingsExecutable`; omitting it preserves the QML-only build. The build script
stages files on a local drive to avoid UNC issues. Keep the lockfiles.

For frontend development, run `npm ci` and `npm run dev` in `desktop`.
Vite alone is not connected to user settings. The standalone host requires a
Python parent implementing the private pipe protocol.

## Lifecycle and migration scope

`_SettingsWindowVisibility` opens the bundled host. Missing binaries, launch
failures and startup timeouts fall back to QML. Explicit Settings requests restore
a minimized window. Starting a workflow hides settings without discarding drafts.
Closing settings prompts about unsaved edits and terminates the separate host.

General, Dictation, Text, Shortcuts, and Models & services are in the web UI.
Recording boundaries and silence detection are under Dictation. Text includes
the local-transcription cleanup route. Custom model IDs/endpoints, shortcut resets,
credential removal, local-model removal/use/measurement and experimental streaming
are integrated into their relevant sections. There is no advanced-options handoff.
Audio file import remains in the pill's quick menu. Dictionary and diagnostic
pages were not part of the QML SettingsWindow; the earlier description was wrong.
QML is retained only as a launch-failure fallback and for QML-only builds.

## Tests

- `tests/test_web_settings.py`: RPC allowlist, secret exclusion, real draft/save/
  discard, lifecycle and explicit activation.
- `desktop/tests/settings.spec.ts`: real React UI with an isolated Qt controller;
  keyboard/model search, persistence, invalid input, microphone test lifecycle
  and screenshots at 640/820/1040 px.
- `desktop/scripts/native-smoke.mjs`: real Tauri and QProcess pipes, model save,
  unsaved close/cancel/discard and process termination.

Browser tests use installed Edge. Set `CLARIFY_TEST_PYTHON` to a Python with
PySide6, and `CLARIFY_TEST_FIXTURE` to the absolute `tests/web_settings_fixture.py`
path, then run `npm test` from the staged desktop directory. The native test also
needs `CLARIFY_SETTINGS_EXECUTABLE` and `CLARIFY_TEST_OUTPUT`. Its remote-debugging
port is test-only, never enabled by the app. Fixtures use temporary config, fake
audio and installation status: no real capture or paid provider requests.

The native test reports startup and summed working sets. These include test
overhead and can double-count shared memory; they are not an Electron comparison
or an end-user latency guarantee.

References: [Tauri](https://v2.tauri.app/start/),
[Base UI](https://base-ui.com/react/overview/accessibility),
[Tailwind CSS](https://tailwindcss.com/docs).
