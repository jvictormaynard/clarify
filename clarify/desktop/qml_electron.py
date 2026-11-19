"""Persistent Electron presentation over the engine's private child pipes."""

from __future__ import annotations

import json
import ctypes
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer

try:
    from .qml_web_settings import (
        MAX_SETTINGS_MESSAGE_BYTES,
        METHODS,
        PROPERTIES,
        SettingsProtocol,
    )
    from .qt_shell import QtShell
except ImportError:
    from qml_web_settings import (
        MAX_SETTINGS_MESSAGE_BYTES,
        METHODS,
        PROPERTIES,
        SettingsProtocol,
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
    "recoveryResultVisible",
    "cancellationVisible",
    "canUndoCancellation",
    "feedbackVisible",
    "feedbackOperationId",
    "completionId",
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
    "writingStyleRefinementAllowed",
    "uiLanguage",
    "microphoneDevices",
    "microphoneInventoryBusy",
    "quickMicrophoneId",
    "hotkeyActions",
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


class ElectronDesktopProcess(QObject):
    """Keep presentation alive; controllers retain operation and data ownership."""

    def __init__(self, settings, bridge, status, unavailable, application, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.bridge = bridge
        self._unavailable = unavailable
        self.protocol = SettingsProtocol(settings)
        self._webrtc = getattr(getattr(settings, "_computer", None), "webrtc", None)
        self._webrtc_timer = QTimer(self)
        self._webrtc_timer.setInterval(20)
        self._webrtc_timer.timeout.connect(self._flush_webrtc)
        self._webrtc_timer.start()
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self.process.readAllStandardError)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._failed)
        self.buffer = bytearray()
        self.failed = False
        self._visible = False
        self._shutting_down = False
        self._recovering = False
        self._restart_attempts = 0
        self._stop_attempts = 0
        self.startup_timer = QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.setInterval(15000)
        self.startup_timer.timeout.connect(lambda: self._failed(None))
        self.restart_timer = QTimer(self)
        self.restart_timer.setSingleShot(True)
        self.restart_timer.timeout.connect(self._restart)
        self.health_timer = QTimer(self)
        self.health_timer.setSingleShot(True)
        self.health_timer.setInterval(30000)
        self.health_timer.timeout.connect(self._healthy)
        self.application = application
        bridge.surfaceChanged.connect(self._sync_settings_visibility)
        self.status = status
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
            status,
            ("audioLevel", "recordingReady", "targetIcon", "liveTranscript"),
            self._mark_workflow,
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
        if self._shutting_down or self.failed or self._recovering:
            return False
        self._visible = self._visible or visible
        path = desktop_executable()
        if path is None:
            self.failed = True
            self._unavailable()
            return False
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.buffer.clear()
            self._ready = False
            self._last_settings = self._last_workflow = None
            self._settings_dirty = set(PROPERTIES)
            self._workflow_dirty = True
            self.startup_timer.start()
            self.process.start(str(path), [])
        return True

    def retry(self):
        """Explicit recovery after the bounded automatic restart budget."""
        if self._shutting_down:
            return False
        self.restart_timer.stop()
        self.failed = self._recovering = False
        self._restart_attempts = 0
        self._stop_attempts = 0
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._recovering = True
            self.restart_timer.start(0)
            return True
        return self.start(visible=self._visible)

    def _healthy(self):
        self._restart_attempts = 0

    def _restart(self):
        if self._shutting_down:
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self._stop_attempts += 1
            if self._stop_attempts >= 20:
                self.failed = True
                self._recovering = False
                self._unavailable()
            else:
                self.restart_timer.start(100)
            return
        self._recovering = False
        self.start(visible=self._visible)

    def show(self):
        if not self.start():
            return False
        self._visible = True
        self._accepted_close = False
        self.history_timer.start()
        self._window_command("show")
        if self._ready:
            self._publish_settings(full=True)
        return True

    def _sync_settings_visibility(self):
        if self._visible and self.bridge.surface != "settings":
            self.hide()

    def _close_settings_activity(self):
        self.settings.practiceCommand("close")
        self.settings.cancelChatGPT()
        self.settings.cancelTextActionPreview()
        self.settings.closeComputerPairing()
        self.settings.stopMicrophoneTest()
        self.settings.cancelHotkeyCapture()

    def hide(self):
        self.history_timer.stop()
        self._close_settings_activity()
        if self._visible:
            self._visible = False
            self._window_command("hide")

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
        # Compatibility entry point: the Electron dock stays visible.
        self._window_command("pill-show" if visible else "pill-hide")

    def toggle_pill(self):
        self._window_command("pill-toggle")

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
            hotkeys = self._pill_settings.pop("hotkeyActions")
            self._pill_settings["recordingShortcut"] = next(
                (
                    item["display"]
                    for item in hotkeys
                    if item["id"] == "recording_hotkey"
                ),
                "",
            )
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
            liveTranscript=getattr(self.status, "liveTranscript", ""),
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

    def _flush_webrtc(self):
        if self._webrtc is None:
            self._webrtc = getattr(
                getattr(self.settings, "_computer", None), "webrtc", None
            )
        if self._webrtc is not None and self._ready:
            for message in self._webrtc.drain():
                self._send(message)

    def _receive(self, request):
        if not isinstance(request, dict):
            return
        event = request.get("event")
        if event == "computer-webrtc" and self._webrtc is not None:
            self._webrtc.submit(request)
            return
        if event == "computer-webrtc-state" and self._webrtc is not None:
            self._webrtc.connected = request.get("connected") is True
            return
        if event == "ready":
            self._ready = True
            if self._recovering or self.failed or self._shutting_down:
                self._ready = False
                return
            self.startup_timer.stop()
            self.health_timer.start()
            if self._visible:
                self.history_timer.start()
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
        if self._shutting_down or self._recovering or self.failed:
            return
        self._ready = False
        if self._webrtc is not None:
            self._webrtc.stop()
        self._recovering = True
        self._stop_attempts = 0
        for timer in (
            self.startup_timer,
            self.flush_timer,
            self.history_timer,
            self.health_timer,
        ):
            timer.stop()
        self._close_settings_activity()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        if self._restart_attempts >= 3:
            self.failed = True
            self._recovering = False
            self._unavailable()
            return
        delay = (250, 1000, 3000)[self._restart_attempts]
        self._restart_attempts += 1
        self.restart_timer.start(delay)

    def _finished(self, code, status):
        self._ready = False
        # Unexpected clean exits require the same recovery as crashes.
        self._failed(None)

    def shutdown(self):
        self._shutting_down = True
        self._ready = False
        for timer in (
            self.startup_timer,
            self.flush_timer,
            self.history_timer,
            self.restart_timer,
            self.health_timer,
        ):
            timer.stop()
        self._close_settings_activity()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1000):
                self.process.kill()
                self.process.waitForFinished(1000)


class ElectronQtShell(QtShell):
    """Retain native input ownership while Electron owns normal presentation."""

    def __init__(self, window, *, desktop, **kwargs):
        self.desktop = desktop
        super().__init__(window, **kwargs)

    def activate_existing_window(self):
        if not self.desktop.failed and self.desktop.bridge.surface in {
            "idle",
            "success",
            "settings",
        }:
            self.desktop.bridge.openSettings()
        else:
            self.show_window()

    def show_window(self):
        if self.desktop.bridge.surface == "files":
            super().show_window()
        else:
            self.desktop.set_pill_visible(True)

    def hide_window(self):
        super().hide_window()
        self.desktop.set_pill_visible(False)

    def toggle_window(self):
        self.desktop.toggle_pill()
