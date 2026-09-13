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
from clarify.desktop.qml_settings import QmlSettingsController
from clarify.desktop.qml_web_settings import SettingsProtocol, WebSettingsProcess


def check_native_corners(process_id):
    """Inspect only the isolated fixture's HWND; never inspect user windows."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    dwm = ctypes.windll.dwmapi
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    dwm.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    matches = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process_id:
            corner = wintypes.DWORD()
            corner_result = dwm.DwmGetWindowAttribute(hwnd, 33, ctypes.byref(corner), 4)
            if corner_result == 0 and corner.value == 2:
                matches.append(hwnd)
                # Border color is a set-only DWM attribute on this Windows
                # build. Capture the actual frame for visual verification.
                import os

                screenshot = os.environ.get("CLARIFY_TEST_CHROME_SCREENSHOT")
                if screenshot:
                    from PIL import ImageGrab

                    rect = wintypes.RECT()
                    if (
                        dwm.DwmGetWindowAttribute(
                            hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)
                        )
                        == 0
                    ):
                        ImageGrab.grab(
                            bbox=(rect.left, rect.top, rect.right, rect.bottom)
                        ).save(screenshot)
        return True

    user32.EnumWindows(visit, 0)
    return bool(matches)


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
        patch("clarify.desktop.qml_settings._is_windows", return_value=False),
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
            if "--check-chrome" in sys.argv:
                chrome_attempts = 0

                def verify_chrome():
                    nonlocal chrome_attempts
                    chrome_attempts += 1
                    if check_native_corners(host.process.processId()):
                        print("PASS: native rounded corners", flush=True)
                    elif chrome_attempts >= 100:
                        print("FAIL: native corner/border attributes", flush=True)
                        app.exit(5)
                    else:
                        QTimer.singleShot(200, verify_chrome)

                QTimer.singleShot(200, verify_chrome)
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
