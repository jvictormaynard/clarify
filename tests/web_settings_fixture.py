"""Isolated real-controller RPC fixture. Never opens user config or a microphone."""

import json
import os
from dataclasses import replace
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


class OnboardingAccount:
    """Offline account double for first-run UI acceptance. Never sends e-mail."""

    @property
    def scope(self):
        return "00000000-0000-4000-8000-000000000001" if self.signed_in else None

    def sync_library(self, service, *, prefer=None):
        pass

    @property
    def signed_in(self):
        return self.state["signedIn"]

    def refresh_if_due(self, service, *, force=False):
        if "--usage-error" in sys.argv:
            from clarify_account import AccountError

            raise AccountError("Não foi possível conectar ao Clarify. Tente novamente.")
        if self.signed_in:
            self.state["usage"] = {
                "used_ms": 450000,
                "reserved_ms": 60000,
                "limit_ms": 18000000,
            }

    def refresh(self):
        self.refresh_if_due(None)

    def __init__(self):
        self.state = dict(
            endpoint="https://clarify.example",
            signedIn=False,
            email="",
            pending="",
            hosted=False,
            syncEnabled=False,
            usage={},
        )
        if "--signed-in" in sys.argv:
            self.state.update(
                signedIn=True, hosted=True, managed=True, email="test@example.test"
            )

    def snapshot(self):
        return dict(self.state)

    def begin_change(self):
        return True

    def end_change(self):
        pass

    def authenticate(self, action, value):
        from clarify_account import AccountError

        if action == "confirm":
            if value != "123456":
                raise AccountError("Código inválido. Tente novamente.")
            self.state.update(signedIn=True, pending="", hosted=True, managed=True)
            self.state["usage"] = {
                "used_ms": 450000,
                "reserved_ms": 60000,
                "limit_ms": 18000000,
            }
        else:
            self.state.update(email=value, pending=action)

    def logout(self, **_):
        self.state.update(signedIn=False, pending="", hosted=False, managed=False)

    def authenticate_social(self, provider, *, cancel):
        if "--social-wait" in sys.argv:
            from clarify_account import AccountError

            cancel.wait(30)
            raise AccountError("O login foi cancelado.")
        self.state.update(
            signedIn=True,
            pending="",
            hosted=True,
            managed=True,
            email=f"{provider}@example.test",
        )


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
        if (
            "--history" in sys.argv
            and request.get("method") == "testHistoryContextChange"
        ):
            # Test-only session transition, outside the product RPC allowlist.
            self.protocol.settings._account._generation += 1
            print(json.dumps({"id": request.get("id"), "result": True}), flush=True)
            return
        print(json.dumps(self.protocol.dispatch(request)), flush=True)


def main():
    # Match production's UTF-8 byte pipes, including non-ASCII instructions.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    app = QCoreApplication([])
    with (
        TemporaryDirectory() as directory,
        patch(
            "shared.localization.device_language",
            return_value=os.environ.get("CLARIFY_TEST_UI_LANGUAGE", "pt"),
        ),
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
        repositories = _repositories(directory)
        onboarding = "--onboarding" in sys.argv
        if not onboarding:
            repositories.config.apply(
                replace(repositories.config.load(), onboarding_completed=True)
            )
        settings = QmlSettingsController(
            repositories,
            account_service=OnboardingAccount()
            if onboarding or "--signed-in" in sys.argv
            else None,
            microphone_backend=backend,
            local_product=Mock(state=LocalASRProductState("installed"), busy=False),
        )
        if "--history" in sys.argv:
            from history_store import HistoryRecord, HistoryStore
            from datetime import datetime, timezone

            store = HistoryStore(
                settings._history.local.path, enabled=True, retention_days=None
            )
            store.append(
                HistoryRecord(
                    raw_text="Isolated desktop history.",
                    timestamp=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
                )
            )
            store.append(
                HistoryRecord(
                    raw_text="Isolated mobile history.",
                    source_device="mobile",
                    timestamp=datetime(2026, 10, 16, 13, tzinfo=timezone.utc),
                )
            )
            if "--history-large" in sys.argv:
                from datetime import timedelta

                records = store.list_records()
                base = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)
                records.extend(
                    HistoryRecord(
                        raw_text=f"Isolated large row {index}: " + "é" * 16000,
                        timestamp=base + timedelta(minutes=index),
                    )
                    for index in range(45)
                )
                records.append(
                    HistoryRecord(
                        raw_text="Giant legacy " + "x" * 1100000 + " legacy end.",
                        timestamp=base + timedelta(hours=2),
                    )
                )
                store.path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "records": [record.to_mapping() for record in records],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
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
