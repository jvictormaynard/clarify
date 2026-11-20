# Clarify desktop

React/TypeScript and Electron provide the desktop interface, including the pill,
Settings, menus and result views. Python/Qt owns capture, workflows, hotkeys,
storage and the private process protocol. Native audio-file import is retained
in `clarify/desktop/qml/AudioFilesWindow.qml`.

## Source map

- `src/main.tsx` selects the Settings window or pill renderer.
- `src/app.tsx`, `pages/` and `components/` own the workspace and shared controls.
- `src/pill.tsx` owns the one pill presentation and its interaction states.
- `src/settings/` owns typed commands, draft state and operation ordering.
- `electron/` owns native windows, focus, hit testing and private pipe transport.
- `assets/` contains the shared desktop branding files.
- `src/styles/` owns semantic tokens, components and layouts.

Use the [desktop design system](../docs/desktop-design-system.md). Keep controls
shared through `components/ui.tsx` and preserve native passive-pill behavior.

## Development and build

Use the pinned Python requirements and `package-lock.json`. Frontend checks use
Node.js 22 or newer:

```powershell
npm ci
npm run typecheck
npm run test:unit
npm run build
```

Build the Windows shell from the repository root:

```powershell
.\scripts\build-desktop.ps1
$env:CLARIFY_DESKTOP_EXECUTABLE = (Resolve-Path ".\dist\desktop-shell\Clarify Desktop.exe").Path
.\.venv\Scripts\python.exe clarify\desktop\qml_app.py
```

On macOS, run `npm run build:electron` in this directory. The Qt engine finds
the result for the current architecture under `electron-dist/`. See
[macOS setup](../docs/development.md#macos-setup) to build the complete app bundle.

`npm run dev` starts Vite for frontend work; it does not connect to user settings.
The product shell requires its Python parent and private standard input/output
protocol. There is no public Settings HTTP server.

`build.ps1` embeds the Electron shell by default. `-DesktopShellDirectory` accepts
a prebuilt shell from the same source revision. The manifest and SBOM cover its
renderer, native runtime and license notices.

## Lifecycle

The Electron process remains resident when Settings closes. Native controllers
retain capture and workflow ownership. A renderer crash or startup timeout uses
bounded restarts and publishes fresh state to the new renderer. After three
unsuccessful restarts, a small native dialog offers Retry or Close. The app never
switches to a second pill, Settings page or result interface.

Saved audio remains under its engine-owned recovery store. UI recovery does not
repeat transcription or paste a result. Existing operation and clipboard guards
continue to decide those effects.

## Validation

`test:unit` covers hooks, queues and operation ownership. `test:browser` and
`test:boot` use isolated Python fixtures and synthetic devices. `test:electron`
checks the host protocol. The Windows packaged smoke test verifies the actual
host and private pipes, including native passive focus and hit testing.

Use [CI delivery](../docs/ci-delivery.md) for the selected commands and platform
gates. Browser evidence does not replace native Windows acceptance.
