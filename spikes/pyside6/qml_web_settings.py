"""Explicit settings RPC over private child-process pipes, on the Qt thread."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QTimer


# Never expose QObject reflection, repository access, saved API keys, or paths.
PROPERTIES = (
    "dirty",
    "lastError",
    "language",
    "languages",
    "mode",
    "modes",
    "autostart",
    "historyEnabled",
    "historyRetentionDays",
    "microphoneDevices",
    "selectedMicrophoneId",
    "microphoneStatus",
    "microphoneTestBusy",
    "microphoneTestLevel",
    "microphoneTestStatus",
    "recordingControls",
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
    "hotkeyActivationMode",
    "hotkeyPushToTalkSupported",
)

METHODS = frozenset(
    (
        "setLanguage",
        "setMode",
        "setAutostart",
        "setHistoryEnabled",
        "setHistoryRetentionDays",
        "selectMicrophone",
        "refreshMicrophones",
        "testMicrophone",
        "stopMicrophoneTest",
        "setRecordingControls",
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

    def snapshot(self):
        state = {key: getattr(self.settings, key) for key in PROPERTIES}
        state["providers"] = [
            {"id": key, "label": self.settings.providerName(key)}
            for key in self.settings.providerIds
        ]
        state["routeProviders"] = [
            {"id": key, "label": self.settings.providerName(key)}
            for key in self.settings.providersForScope(self.settings.selectedScope)
        ]
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
                result = self.snapshot()
            elif method in METHODS:
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
                result = self.snapshot()
            else:
                return {**reply, "error": "Unsupported settings method"}
            return {**reply, "result": result}
        except (TypeError, ValueError):
            # Do not echo arguments: they can contain a pending API key.
            return {**reply, "error": "Invalid settings value"}
        except Exception:
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
        if self._visible:
            self._visible = False
            self.settings.stopMicrophoneTest()
            self._window_command("hide")

    def activate(self):
        if not self.failed:
            self._window_command("show")

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer) > 1_048_576:
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
        self.startup_timer.stop()
        self.failed = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        if not self._shutting_down and self.bridge.surface == "settings":
            self.fallback()

    def _finished(self, code, status):
        self.startup_timer.stop()
        self._visible = False
        self.settings.stopMicrophoneTest()
        if self._shutting_down:
            return
        if code != 0:
            self.failed = True
            if self.bridge.surface == "settings":
                self.fallback()
        elif self.bridge.surface == "settings":
            self.bridge.closeSettings()

    def shutdown(self):
        self._shutting_down = True
        self.startup_timer.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1000):
                self.process.kill()
                self.process.waitForFinished(1000)
