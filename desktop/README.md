# Clarify Settings

React/TypeScript with Radix and cmdk primitives, hosted by Tauri 2 / WebView2.
Components follow the composition approach used by shadcn/ui and are maintained
here without a shadcn runtime dependency. Settings use the web UI;
the recording engine and pill remain in Python/Qt.

The Python engine remains the sole owner of configuration, secrets, audio,
shortcuts and clipboard delivery. `spikes/pyside6/qml_web_settings.py` defines a
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
[shadcn/ui](https://ui.shadcn.com/docs),
[Radix](https://www.radix-ui.com/primitives/docs/overview/accessibility).
