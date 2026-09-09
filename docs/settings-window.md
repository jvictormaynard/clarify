# Settings window

Builds that include `clarify-settings.exe` use the React/Tauri settings window.
See `desktop/README.md` for the private-pipe integration, build and tests.
The QML window described below remains the fallback and advanced-options screen.

Settings use a dedicated Qt Quick Controls ApplicationWindow. The compact dictation toolbar remains a separate tool window. The settings window has no transient parent, uses Qt.Window, and supports the Windows taskbar, native resizing, minimization, and maximization.

The existing Basic controls and shared monochrome theme are retained. No Electron runtime or new UI dependency is needed. Form columns align across pages; the footer and errors stay visible while the page scrolls.

Preferences are drafts until Save. Closing a draft offers Save, Discard, or Cancel. Service keys and endpoints require Validate & save; their pending state is shown separately and switching services asks before discarding a draft. Numeric recording inputs are checked before persistence.

Validation includes real QML navigation and input tests, small and large window sizes, unsaved close/discard, invalid duration rejection, persisted duration updates, and native Windows owner/style checks. Native tests verify a normal unowned window with a resize frame and maximize control. Screenshots use isolated test data, without reading user credentials or starting audio capture.
