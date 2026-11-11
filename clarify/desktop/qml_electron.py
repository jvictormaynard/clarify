"""Persistent Electron presentation over the engine's private child pipes."""

from __future__ import annotations

import json
import ctypes
import os
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from PySide6.QtWidgets import QSystemTrayIcon

try:
    from .qml_web_settings import (
        MAX_SETTINGS_MESSAGE_BYTES,
        METHODS,
        PROPERTIES,
        WebSettingsProcess,
    )
    from .qt_shell import QtShell
except ImportError:
    from qml_web_settings import (
        MAX_SETTINGS_MESSAGE_BYTES,
        METHODS,
        PROPERTIES,
        WebSettingsProcess,
    )
    from qt_shell import QtShell


WORKFLOW_PROPERTIES = (
    "surface",
    "status",
    "result",
    "busy",
    "recording",
    "showRecordingStop",
    "refinementFailed",
    "canShowResult",
    "canRetryTranscription",
    "cancellationVisible",
    "canUndoCancellation",
    "feedbackVisible",
    "feedbackOperationId",
    "feedbackTitle",
    "transitionPending",
    "writingStyleCaption",
    "writingStyleFinished",
    "writingStyleApplied",
    "mode",
    "language",
    "translationOptions",
    "canPasteLastTranscription",
)
WORKFLOW_METHODS = {
    "startRecordingFromButton": (),
    "stopRecording": (),
    "cancelRecording": (),
    "chooseTranslation": (str,),
    "cancelTranslation": (),
    "openSettings": (),
    "openFiles": (),
    "showResult": (),
    "copyResult": (),
    "finish": (),
    "reset": (),
    "undoCancellation": (),
    "dismissFeedback": (int,),
    "retryTranscription": (),
    "pasteLastTranscription": (),
    "setLanguage": (str,),
    "setMode": (str,),
    "runTextAction": (str,),
}
LIBRARY_PROPERTIES = frozenset(
    (
        "dictionaryEntries",
        "dictionaryContext",
        "snippets",
        "snippetContext",
    )
)
PILL_SETTINGS = (
    "dictationWritingStyle",
    "applicationStyleRefinementAllowed",
    "uiLanguage",
    "microphoneDevices",
    "microphoneInventoryBusy",
    "quickMicrophoneId",
    "textActions",
    "updateAvailable",
    "updateBusy",
    "updateVersion",
)


def desktop_executable() -> Path | None:
    override = os.environ.get("CLARIFY_DESKTOP_EXECUTABLE")
    if override:
        path = Path(override)
        return path if path.is_absolute() and path.is_file() else None
    roots = [Path(sys.executable).parent]
    if getattr(sys, "_MEIPASS", None):
        roots.insert(0, Path(sys._MEIPASS))
    for root in roots:
        path = root / "desktop-shell" / "Clarify Desktop.exe"
        if path.is_file():
            return path
    return None


class ElectronDesktopProcess(WebSettingsProcess):
    """Keep presentation alive; controllers retain operation and data ownership."""

    def __init__(self, settings, bridge, status, fallback, application, parent=None):
        super().__init__(settings, bridge, fallback, parent)
        self.application = application
        self.status = status
        self._pill_visible = True
        self._settings_dirty: set[str] = set()
        self._workflow_dirty = True
        self._last_workflow = None
        self._last_settings = None
        self._ready = False
        self._accepted_close = True
        self._pill_settings = None
        self._accepting_close = False
        environment = QProcessEnvironment.systemEnvironment()
        environment.remove("ELECTRON_RUN_AS_NODE")
        environment.remove("NODE_OPTIONS")
        self.process.setProcessEnvironment(environment)
        self.process.started.disconnect()
        self.flush_timer = QTimer(self)
        self.flush_timer.setSingleShot(True)
        self.flush_timer.setInterval(16)
        self.flush_timer.timeout.connect(self._flush)
        # History revisions are derived from storage stamps, including changes
        # published by background account synchronization outside Qt signals.
        self.history_timer = QTimer(self)
        self.history_timer.setInterval(1000)
        self.history_timer.timeout.connect(self._check_history)
        self._connect_notifications(bridge, WORKFLOW_PROPERTIES, self._mark_workflow)
        self._connect_notifications(
            status, ("audioLevel", "recordingReady", "targetIcon"), self._mark_workflow
        )
        self._connect_notifications(
            settings, (*PROPERTIES, "quickMicrophoneId"), self._mark_settings
        )

    def _connect_notifications(self, owner, names, callback):
        meta = owner.metaObject()
        signals = {}
        for name in names:
            index = meta.indexOfProperty(name)
            if index < 0:
                continue
            prop = meta.property(index)
            if prop.hasNotifySignal():
                signal = bytes(prop.notifySignal().name()).decode("ascii")
                signals.setdefault(signal, set()).add(name)
        for signal, keys in signals.items():
            getattr(owner, signal).connect(lambda *args, keys=keys: callback(keys))

    def _mark_workflow(self, _keys=None):
        if self._shutting_down:
            return
        self._workflow_dirty = True
        if not self.flush_timer.isActive():
            self.flush_timer.start()

    def _mark_settings(self, keys):
        if self._shutting_down:
            return
        self._settings_dirty.update(keys)
        if set(keys) & set(PILL_SETTINGS):
            self._pill_settings = None
            self._mark_workflow()
        if self._settings_dirty & LIBRARY_PROPERTIES:
            self._settings_dirty.update(LIBRARY_PROPERTIES)
        if "selectedScope" in keys:
            self._settings_dirty.add("routeProviders")
        if not self.flush_timer.isActive():
            self.flush_timer.start()

    def start(self, *, visible=True):
        path = desktop_executable()
        if path is None or self.failed:
            return False
        self._pill_visible = visible
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.buffer.clear()
            self._ready = False
            self.process.start(str(path), [])
            self.startup_timer.start()
        return True

    def show(self):
        if not self.start(visible=self._pill_visible):
            return False
        self._visible = True
        self._accepted_close = False
        self.history_timer.start()
        self._window_command("show")
        if self._ready:
            self._publish_settings(full=True)
        return True

    def activate(self):
        if self._visible:
            self._window_command("show")

    def hide(self):
        self.history_timer.stop()
        super().hide()

    def _check_history(self):
        if self._visible and self._last_settings is not None:
            if self.settings.historyState != self._last_settings.get("historyState"):
                self._mark_settings({"historyState"})

    def _window_command(self, action):
        if action == "hide" and self._accepting_close:
            return
        self._send(
            {
                "window": {"show": "settings-show", "hide": "settings-hide"}.get(
                    action, action
                )
            }
        )

    def set_pill_visible(self, visible):
        self._pill_visible = bool(visible)
        self._window_command("pill-show" if visible else "pill-hide")

    def toggle_pill(self):
        self.set_pill_visible(not self._pill_visible)

    def blocks_update(self):
        # A hidden, clean retained renderer is not an update operation.
        return self._visible or not self._accepted_close

    def _send(self, message):
        if self.process.state() != QProcess.ProcessState.Running:
            return
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        if len(payload) > MAX_SETTINGS_MESSAGE_BYTES:
            self._failed(None)
            return
        self.process.write(payload)

    def workflow_snapshot(self):
        if self._pill_settings is None:
            self._pill_settings = {
                key: getattr(self.settings, key) for key in PILL_SETTINGS
            }
            self._pill_settings["textActions"] = [
                {key: action[key] for key in ("id", "name", "enabled")}
                for action in self._pill_settings["textActions"]
            ]
        state = {key: getattr(self.bridge, key) for key in WORKFLOW_PROPERTIES}
        state.update(self._pill_settings)
        state.update(
            recordingReady=self.status.recordingReady,
            level=self.status.audioLevel,
            targetIcon=self.status.targetIcon,
            uiLanguage=self.settings.uiLanguage,
        )
        return state

    def _settings_values(self, keys):
        library = self.settings.library_snapshot() if keys & LIBRARY_PROPERTIES else {}
        action_keys = {
            key
            for key in keys
            if key.startswith("textAction") or key.startswith("afterDictation")
        }
        actions = self.settings.text_action_snapshot() if action_keys else {}
        values = {}
        for key in keys:
            if key in library:
                values[key] = library[key]
            elif key in actions:
                values[key] = actions[key]
            elif key == "routeProviders":
                values[key] = [
                    {"id": item, "label": self.settings.providerName(item)}
                    for item in self.settings.providersForScope(
                        self.settings.selectedScope
                    )
                ]
            else:
                values[key] = getattr(self.settings, key)
        return values

    def _publish_settings(self, *, full=False):
        if full or self._last_settings is None:
            state = self.protocol.snapshot()
        else:
            state = self._settings_values(self._settings_dirty)
        previous = self._last_settings or {}
        patch = {
            key: value
            for key, value in state.items()
            if full or previous.get(key) != value
        }
        if "snippetContext" in patch or "dictionaryContext" in patch:
            patch.update({key: state[key] for key in LIBRARY_PROPERTIES})
        self._last_settings = {**previous, **state}
        self._settings_dirty.clear()
        if patch:
            self._send({"event": "settings", "state": patch})

    def _flush(self):
        if not self._ready or self.failed or self._shutting_down:
            return
        if self._workflow_dirty:
            state = self.workflow_snapshot()
            if state != self._last_workflow:
                previous_surface = (self._last_workflow or {}).get("surface")
                if (
                    state["surface"] == "translation_picker"
                    and previous_surface != "translation_picker"
                ):
                    self._allow_picker_activation()
                self._last_workflow = state
                self._send({"event": "workflow", "state": state})
            self._workflow_dirty = False
        if self._visible and self._settings_dirty:
            self._publish_settings()

    def _allow_picker_activation(self):
        # The native hotkey belongs to this process. Pass its foreground
        # permission to our presentation child after selection capture ends.
        if sys.platform != "win32":
            return False
        pid = int(self.process.processId())
        if pid <= 0:
            return False
        try:
            allow = ctypes.WinDLL(
                "user32", use_last_error=True
            ).AllowSetForegroundWindow
            allow.argtypes = [ctypes.c_ulong]
            allow.restype = ctypes.c_int
            return bool(allow(pid))
        except (OSError, AttributeError):
            return False

    def dispatch_workflow(self, request):
        reply = {"id": request.get("id")}
        method, args = request.get("method"), request.get("args", [])
        if not isinstance(method, str) or not isinstance(args, list):
            return {**reply, "error": "Invalid workflow request"}
        if method == "snapshot" and not args:
            return {**reply, "result": self.workflow_snapshot()}
        if method in {"refreshMicrophones", "selectQuickMicrophone", "installUpdate"}:
            valid = (
                method == "selectQuickMicrophone"
                and len(args) == 1
                and type(args[0]) is str
            ) or (method != "selectQuickMicrophone" and not args)
            if not valid:
                return {**reply, "error": "Invalid desktop command"}
            try:
                ok = getattr(self.settings, method)(*args)
                return {
                    **reply,
                    **(
                        {"result": True}
                        if ok is not False
                        else {
                            "error": self.settings.lastError
                            or "Could not apply desktop command"
                        }
                    ),
                }
            except Exception:
                return {**reply, "error": "Could not apply desktop command"}
        if method in {"quit", "toggleWindow"} and not args:
            if method == "quit":
                QTimer.singleShot(0, self.application.quit)
            else:
                self.toggle_pill()
            return {**reply, "result": True}
        signature = WORKFLOW_METHODS.get(method)
        if (
            signature is None
            or len(args) != len(signature)
            or any(
                type(value) is not expected for value, expected in zip(args, signature)
            )
        ):
            return {**reply, "error": "Unsupported workflow method"}
        try:
            result = getattr(self.bridge, method)(*args)
            return {**reply, "result": result}
        except Exception:
            return {**reply, "error": "Could not apply desktop command"}

    def _receive(self, request):
        if not isinstance(request, dict):
            return
        event = request.get("event")
        if event == "ready":
            self._ready = True
            self.startup_timer.stop()
            self._window_command("pill-show" if self._pill_visible else "pill-hide")
            self._window_command("show" if self._visible else "hide")
            self._workflow_dirty = True
            self._flush()
            return
        if event == "settings-hidden":
            self._accepted_close = True
            self._accepting_close = True
            try:
                self.hide()
            finally:
                self._accepting_close = False
            self.bridge.closeSettings()
            return
        if event == "quit":
            self.application.quit()
            return
        if type(request.get("id")) is not int:
            return
        if request.get("channel", "settings") == "settings":
            reply = self.protocol.dispatch(request)
            result = reply.get("result")
            if isinstance(result, dict) and request.get("method") in METHODS | {
                "snapshot",
                "poll",
            }:
                # Compare pushes with the state actually exposed by each reply,
                # including a transient value that reverts before the next push.
                self._last_settings = {**(self._last_settings or {}), **result}
            self._send(reply)
        elif request.get("channel") == "workflow":
            self._send(self.dispatch_workflow(request))
        else:
            self._send({"id": request["id"], "error": "Unsupported desktop channel"})

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer) > MAX_SETTINGS_MESSAGE_BYTES:
            self._failed(None)
            return
        while b"\n" in self.buffer:
            line, _, remaining = self.buffer.partition(b"\n")
            self.buffer = bytearray(remaining)
            try:
                request = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            self._receive(request)

    def _failed(self, error):
        self.flush_timer.stop()
        self.history_timer.stop()
        super()._failed(error)
        if not self._shutting_down and self.bridge.surface != "settings":
            self.fallback()

    def _finished(self, code, status):
        self._ready = False
        self.flush_timer.stop()
        self.history_timer.stop()
        if not self._shutting_down:
            self.failed = True
        # Even a clean unexpected Electron exit is a presentation failure. It
        # must restore native Settings instead of treating it as accepted close.
        super()._finished(code if self._shutting_down else 1, status)
        if not self._shutting_down and self.bridge.surface != "settings":
            self.fallback()

    def shutdown(self):
        self._shutting_down = True
        self._ready = False
        self.flush_timer.stop()
        self.history_timer.stop()
        super().shutdown()


class ElectronQtShell(QtShell):
    """Retain native input ownership while Electron owns normal presentation."""

    def __init__(self, window, *, desktop, **kwargs):
        self.desktop = desktop
        super().__init__(window, **kwargs)

    def restore_native_tray(self):
        if (
            self.is_running
            and self.tray is None
            and QSystemTrayIcon.isSystemTrayAvailable()
        ):
            self._create_tray()
            self._install_window_close_filter()

    def show_window(self):
        if self.desktop.failed or self.desktop.bridge.surface == "files":
            super().show_window()
        else:
            self.desktop.set_pill_visible(True)

    def show_window_without_activation(self):
        if self.desktop.failed:
            super().show_window_without_activation()
        else:
            self.desktop.set_pill_visible(True)

    def hide_window(self):
        super().hide_window()
        if not self.desktop.failed:
            self.desktop.set_pill_visible(False)

    def toggle_window(self):
        if self.desktop.failed or self.desktop.bridge.surface == "files":
            super().toggle_window()
        else:
            self.desktop.toggle_pill()
