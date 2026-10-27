"""Explicit settings RPC over private child-process pipes, on the Qt thread."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QTimer


# Never expose QObject reflection, repository access, saved API keys, or paths.
# Full guest vocabulary and snippets can contain 6.7M characters. JSON control
# escapes use up to six bytes each, so both native pipe readers allow 64 MiB.
# Account snippets retain the separate, smaller 256 KiB transport limit.
MAX_SETTINGS_MESSAGE_BYTES = 64 * 1024 * 1024

PROPERTIES = (
    "uiLanguage",
    "onboardingRequired",
    "practiceState",
    "accountState",
    "chatgptState",
    "historyState",
    "dirty",
    "dictionaryEntries",
    "dictionaryContext",
    "snippets",
    "snippetContext",
    "lastError",
    "language",
    "languages",
    "mode",
    "modes",
    "autostart",
    "historyEnabled",
    "automaticUpdates",
    "applicationVersion",
    "updateAvailable",
    "updateBusy",
    "updateInstalling",
    "updateSupported",
    "updateVersion",
    "updateStatus",
    "updateProgress",
    "historyRetentionDays",
    "microphoneDevices",
    "microphoneInventoryBusy",
    "selectedMicrophoneId",
    "microphoneStatus",
    "microphoneTestBusy",
    "microphoneTestLevel",
    "microphoneTestStatus",
    "recordingControls",
    "dictationCleanupLevel",
    "applicationWritingStyles",
    "applicationStyleTarget",
    "applicationStyleRefinementAllowed",
    "dictationCleanupRefinementAllowed",
    "selectedScope",
    "routeProviderId",
    "routeModelId",
    "routeModelOptions",
    "routeModelStatus",
    "routePrompt",
    "routeEnabled",
    "routeCustomEndpoint",
    "selectedProviderId",
    "providerDisplayName",
    "providerHasApiKey",
    "providerBaseUrl",
    "providerDirty",
    "providerBusy",
    "providerStatus",
    "providerError",
    "providerSupportsCustomEndpoint",
    "localProfiles",
    "localProfileIndex",
    "localDevices",
    "localDeviceIndex",
    "localAsrStatus",
    "localAsrDetail",
    "localAsrProgress",
    "localAsrBusy",
    "localAsrCanInstall",
    "localAsrRequirementsList",
    "localStreaming",
    "localBenchmarkBusy",
    "localBenchmarkDetail",
    "localAsrCloudRefinement",
    "hotkeyActions",
    "hotkeyCaptureAction",
    "hotkeyActivationMode",
    "hotkeyPushToTalkSupported",
)

METHODS = frozenset(
    (
        "completeOnboarding",
        "practiceCommand",
        "beginHotkeyCapture",
        "cancelHotkeyCapture",
        "accountCommand",
        "chatgptCommand",
        "deleteHistoryEntry",
        "clearHistory",
        "setLanguage",
        "setDictionaryEntries",
        "setSnippets",
        "setMode",
        "setAutostart",
        "setHistoryEnabled",
        "setAutomaticUpdates",
        "checkForUpdates",
        "installUpdate",
        "setHistoryRetentionDays",
        "selectMicrophone",
        "refreshMicrophones",
        "testMicrophone",
        "stopMicrophoneTest",
        "setRecordingControls",
        "setRecordingVadEnabled",
        "savePreference",
        "saveLibraryPreference",
        "selectWorkflow",
        "setRouteProviderId",
        "setRouteModelId",
        "loadRouteModels",
        "refreshRouteModels",
        "setRoutePrompt",
        "setRouteEnabled",
        "setRouteCustomEndpoint",
        "selectProvider",
        "setProviderApiKey",
        "setProviderBaseUrl",
        "validateProvider",
        "selectLocalProfile",
        "selectLocalDevice",
        "installLocalAsr",
        "cancelLocalAsr",
        "refreshLocalAsr",
        "setLocalStreaming",
        "setLocalAsrCloudRefinement",
        "setHotkey",
        "setHotkeyActivationMode",
        "resetHotkey",
        "resetAllHotkeys",
        "clearProvider",
        "removeLocalAsr",
        "useLocalAsr",
        "cancelLocalMeasurement",
        "save",
        "load",
    )
)


class SettingsProtocol:
    def __init__(self, settings):
        self.settings = settings
        self._poll_state = None
        self._poll_dirty = set()

    def snapshot(self):
        library = self.settings.library_snapshot()
        state = {
            key: library[key] if key in library else getattr(self.settings, key)
            for key in PROPERTIES
        }
        state["providers"] = [
            {"id": key, "label": self.settings.providerName(key)}
            for key in self.settings.providerIds
        ]
        state["routeProviders"] = [
            {"id": key, "label": self.settings.providerName(key)}
            for key in self.settings.providersForScope(self.settings.selectedScope)
        ]
        return state

    def poll(self):
        # Read the actual allowlisted values, including asynchronous changes.
        # Keep one baseline only. Full command replies must not consume changes:
        # background callers can intentionally ignore those replies.
        state = self.snapshot()
        previous = self._poll_state
        delta = (
            state
            if previous is None
            else {
                key: value
                for key, value in state.items()
                if key in self._poll_dirty or value != previous[key]
            }
        )
        self._poll_state = state
        self._poll_dirty.clear()
        return delta

    def _client_snapshot(self):
        state = self.snapshot()
        if self._poll_state is not None:
            # Full replies may expose transient state between polls. Remember
            # its keys so a completion that returns to the poll baseline still
            # reaches the client. Retain keys only, never another snapshot.
            self._poll_dirty.update(
                key for key, value in state.items() if value != self._poll_state[key]
            )
        return state

    def dispatch(self, request):
        if not isinstance(request, dict):
            return {"error": "Invalid settings request"}
        reply = {"id": request.get("id")}
        method, args = request.get("method"), request.get("args", [])
        if not isinstance(method, str) or not isinstance(args, list) or len(args) > 8:
            return {**reply, "error": "Invalid settings request"}
        try:
            if method == "snapshot" and not args:
                result = self._client_snapshot()
            elif method == "poll" and not args:
                result = self.poll()
            elif method == "getHistoryPage":
                if len(args) not in (2, 3) or any(
                    type(value) is not str for value in args
                ):
                    raise ValueError()
                result = self.settings.getHistoryPage(*args)
            elif method == "getHistoryTextPart":
                if (
                    len(args) != 4
                    or any(type(args[index]) is not str for index in (0, 1, 3))
                    or type(args[2]) is not int
                ):
                    raise ValueError()
                result = self.settings.getHistoryTextPart(*args)
            elif method == "copyHistoryText":
                if len(args) != 4 or any(type(value) is not str for value in args):
                    raise ValueError()
                result = self.settings.copyHistoryText(*args)
            elif method == "historyCorrection":
                if (
                    len(args) != 2
                    or type(args[0]) is not str
                    or type(args[1]) is not dict
                ):
                    raise ValueError()
                result = self.settings.historyCorrection(*args)
            elif method in METHODS:
                if method == "practiceCommand" and (
                    len(args) != 1
                    or type(args[0]) is not str
                    or args[0] not in {"open", "close", "start", "stop", "cancel"}
                ):
                    raise ValueError()
                if method == "chatgptCommand" and (
                    len(args) != 2 or any(type(value) is not str for value in args)
                ):
                    raise ValueError()
                if method in {"setDictionaryEntries", "setSnippets"} and (
                    len(args)
                    not in ({1, 2, 3} if method == "setDictionaryEntries" else {2, 3})
                    or type(args[0]) is not list
                    or (len(args) >= 2 and type(args[1]) is not str)
                    or (len(args) == 3 and type(args[2]) is not list)
                ):
                    raise ValueError()
                if method == "save" and (
                    len(args) > 1 or (args and type(args[0]) is not str)
                ):
                    raise ValueError()
                if method == "savePreference" and (
                    len(args) != 2
                    or type(args[0]) is not str
                    or type(args[1]) is not list
                ):
                    raise ValueError()
                if method == "saveLibraryPreference" and len(args) != 5:
                    raise ValueError()
                if method == "save" and self.settings.providerDirty:
                    return {
                        **reply,
                        "error": "Valide ou descarte a chave antes de salvar.",
                    }
                ok = getattr(self.settings, method)(*args)
                if ok is False and method not in {
                    "loadRouteModels",
                    "refreshRouteModels",
                }:
                    return {
                        **reply,
                        "error": self.settings.lastError
                        or "Não foi possível aplicar a alteração.",
                    }
                result = self._client_snapshot()
            else:
                return {**reply, "error": "Unsupported settings method"}
            return {**reply, "result": result}
        except (TypeError, ValueError) as error:
            # Do not echo arguments: they can contain a pending API key.
            if method in {"getHistoryPage", "getHistoryTextPart", "copyHistoryText"}:
                return {
                    **reply,
                    "error": "O histórico mudou. Atualize e tente novamente."
                    if str(error) == "O histórico mudou. Atualize e tente novamente."
                    else "Não foi possível carregar o histórico.",
                }
            return {**reply, "error": "Invalid settings value"}
        except Exception:
            if method == "copyHistoryText":
                return {**reply, "error": "Não foi possível copiar. Tente novamente."}
            if method in {"getHistoryPage", "getHistoryTextPart"}:
                return {**reply, "error": "Não foi possível carregar o histórico."}
            return {**reply, "error": "Não foi possível ler as configurações."}


def settings_executable() -> Path | None:
    override = os.environ.get("CLARIFY_SETTINGS_EXECUTABLE")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_absolute() and candidate.is_file() else None
    roots = [Path(sys.executable).parent]
    if getattr(sys, "_MEIPASS", None):
        roots.insert(0, Path(sys._MEIPASS))
    for root in roots:
        candidate = root / "clarify-settings.exe"
        if candidate.is_file():
            return candidate
    return None


class WebSettingsProcess(QObject):
    """The Python engine remains the only owner of config and audio devices."""

    def __init__(self, settings, bridge, fallback, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.bridge = bridge
        self.fallback = fallback
        self.protocol = SettingsProtocol(settings)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._failed)
        self.buffer = bytearray()
        self.failed = False
        self._visible = False
        self._shutting_down = False
        self.process.started.connect(lambda: self._window_command("show"))
        self.process.readyReadStandardError.connect(self.process.readAllStandardError)
        self.startup_timer = QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.setInterval(15000)
        self.startup_timer.timeout.connect(lambda: self._failed(None))

    def _window_command(self, action):
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.write((json.dumps({"window": action}) + "\n").encode())

    def blocks_update(self) -> bool:
        # Hidden WebView instances can still own local unsaved form fields.
        # A confirmed close ends the child and permits a safe app restart.
        return self.process.state() != QProcess.ProcessState.NotRunning

    def show(self) -> bool:
        path = settings_executable()
        if path is None or self.failed:
            return False
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.buffer.clear()
            self._visible = True
            self.process.start(str(path), [])
            self.startup_timer.start()
        elif not self._visible:
            self._visible = True
            self._window_command("show")
        return True

    def hide(self):
        self.settings.practiceCommand("close")
        self.settings.cancelChatGPT()
        if self._visible:
            self._visible = False
            self.settings.stopMicrophoneTest()
            self.settings.cancelHotkeyCapture()
            self._window_command("hide")

    def activate(self):
        if not self.failed:
            self._window_command("show")

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer) > MAX_SETTINGS_MESSAGE_BYTES:
            self.process.kill()
            return
        while b"\n" in self.buffer:
            line, _, remaining = self.buffer.partition(b"\n")
            self.buffer = bytearray(remaining)
            try:
                request = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            self.startup_timer.stop()
            reply = self.protocol.dispatch(request)
            self.process.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())

    def _failed(self, error):
        self.settings.practiceCommand("close")
        self.settings.cancelChatGPT()
        self.startup_timer.stop()
        self.failed = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        if not self._shutting_down and self.bridge.surface == "settings":
            self.fallback()

    def _finished(self, code, status):
        self.settings.practiceCommand("close")
        self.settings.cancelChatGPT()
        self.startup_timer.stop()
        self._visible = False
        self.settings.stopMicrophoneTest()
        if self._shutting_down:
            return
        self.settings.cancelHotkeyCapture()
        if code != 0:
            self.failed = True
            if self.bridge.surface == "settings":
                self.fallback()
        elif self.bridge.surface == "settings":
            self.bridge.closeSettings()

    def shutdown(self):
        self.settings.practiceCommand("close")
        self.settings.cancelChatGPT()
        self._shutting_down = True
        self.startup_timer.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1000):
                self.process.kill()
                self.process.waitForFinished(1000)
