# Settings window

React renders Settings in the retained Electron child. Python and Qt own the
controllers, configuration, recording and providers. See
[desktop development](../desktop/README.md) for the private-pipe integration,
build and tests.

Choice controls save directly. Text and service drafts retain their Save,
Discard and validation controls. Closing waits for accepted operations and
asks about unsaved changes. Workflow navigation hides the window and stops
Settings-only activities while retaining drafts.

Electron is the required presenter. Launch failures and unexpected exits use
bounded restart attempts, then a minimal native Retry/Close dialog. There is
no QML Settings fallback. The native file-import panel remains separate.

Browser tests cover navigation, input, drafts and close guards with isolated
controllers. Native Windows acceptance checks focus, resizing, DPI and the
complete packaged application separately.
