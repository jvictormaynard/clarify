"""Isolated real-controller RPC fixture. Never opens user config or a microphone."""

import json
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QObject, Signal, Qt, Slot, QTimer
from types import SimpleNamespace
from test_pyside6_qml_settings import _repositories, _MicrophoneBackend
from microphone_controls import MicrophoneInventory, MicrophoneDevice
from local_asr_product import LocalASRProductState
from spikes.pyside6.qml_settings import QmlSettingsController
from spikes.pyside6.qml_web_settings import SettingsProtocol, WebSettingsProcess


class Dispatcher(QObject):
    request = Signal(object)

    def __init__(self, protocol):
        super().__init__()
        self.protocol = protocol
        self.request.connect(self.dispatch, Qt.QueuedConnection)

    @Slot(object)
    def dispatch(self, request):
        if request.get("method") == "quit":
            QCoreApplication.quit()
            return
        print(json.dumps(self.protocol.dispatch(request)), flush=True)


def main():
    # Match production's UTF-8 byte pipes, including non-ASCII instructions.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    app = QCoreApplication([])
    with (
        TemporaryDirectory() as directory,
        patch("spikes.pyside6.qml_settings._is_windows", return_value=False),
        patch(
            "local_asr_catalog.installer_for",
            side_effect=lambda model, device: Mock(
                status=lambda: {"state": "installed"}
            ),
        ),
    ):
        inventory = MicrophoneInventory(
            devices=(
                MicrophoneDevice(
                    stable_id="usb",
                    name="USB Microphone",
                    is_default=True,
                    input_channels=1,
                ),
            ),
            default_id="usb",
        )
        backend = _MicrophoneBackend(inventory)

        def preview(selection, inventory, *, on_level, cancel_event, duration):
            for level in (0.1, 0.5, 0.8, 0.3) * 50:
                if cancel_event.wait(0.05):
                    break
                on_level(level)
            return 0.5

        backend.test_microphone = preview
        settings = QmlSettingsController(
            _repositories(directory),
            microphone_backend=backend,
            local_product=Mock(state=LocalASRProductState("installed"), busy=False),
        )
        native = "--native" in sys.argv
        host = None
        if native:
            host = WebSettingsProcess(
                settings,
                SimpleNamespace(surface="settings", closeSettings=app.quit),
                lambda: app.exit(3),
                app,
            )
            if not host.show():
                raise RuntimeError("Native test executable is missing")
            QTimer.singleShot(90000, lambda: app.exit(4))
        dispatcher = Dispatcher(SettingsProtocol(settings))

        def read():
            for line in sys.stdin:
                dispatcher.request.emit(json.loads(line))
            app.quit()

        if not native:
            threading.Thread(target=read, daemon=True).start()
        try:
            result = app.exec()
        finally:
            if host is not None:
                host.shutdown()
            settings.shutdown()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
