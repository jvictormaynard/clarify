"""Personal mobile access uses fake hosts and an isolated SQLite profile."""

import json
from pathlib import Path
import threading
import time
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from clarify.desktop.qml_computer import QmlComputerController
from clarify.desktop.qml_settings import QmlSettingsController
from clarify.desktop.qml_web_settings import SettingsProtocol
from local_asr_product import LocalASRProductState

try:
    from .test_pyside6_qml_settings import _repositories
except ImportError:
    from test_pyside6_qml_settings import _repositories


class FakeHost:
    def __init__(self):
        self.ready = False
        self.sequence = 0
        self.devices = [
            {
                "device_id": "phone-1",
                "device_name": "Fixture iPhone",
                "token": "never-return-permanent-token",
            }
        ]
        self.calls = []

    def start(self):
        self.calls.append(("start", threading.get_ident()))
        self.ready = True

    def stop(self):
        self.calls.append(("stop", threading.get_ident()))
        self.ready = False

    def create_pairing(self):
        self.sequence += 1
        return {
            "pairing_url": f"clarify://computer?data=fixture-{self.sequence}",
            "expires_at": 1300,
        }

    def snapshot(self):
        return {"ready": self.ready, "devices": self.devices}

    def revoke_device(self, device_id):
        self.devices = [
            device for device in self.devices if device["device_id"] != device_id
        ]


class ComputerControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtQuickControls2 import QQuickStyle

        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.host = FakeHost()
        self.clock = 1000.0
        self.blocked = False
        self.factory = Mock(return_value=self.host)
        self.controller = self.make_controller()

    def make_controller(self, path=None, **options):
        controller = QmlComputerController(
            path or Path(self.directory.name) / "computer.sqlite3",
            self.factory,
            clock=lambda: self.clock,
            blocked=lambda: self.blocked,
            render_qr=lambda value: "data:image/svg+xml;base64," + value,
            **options,
        )
        self.addCleanup(controller.shutdown)
        return controller

    def wait(self, controller=None):
        controller = controller or self.controller
        deadline = time.monotonic() + 3
        while controller.snapshot()["busy"] and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(controller.snapshot()["busy"])

    def enable(self):
        self.assertTrue(self.controller.command("enable"))
        self.wait()
        self.assertTrue(self.controller.snapshot()["running"])

    def test_default_off_and_profile_local_explicit_restart_consent(self):
        self.controller.initialize()
        self.wait()
        self.factory.assert_not_called()
        self.assertFalse(self.controller.path.exists())
        self.enable()
        self.assertFalse(self.controller.snapshot()["durable"])
        self.assertTrue(self.controller.command("durable", "true"))
        self.wait()
        self.controller.shutdown()
        restored = self.make_controller()
        restored.initialize()
        self.wait(restored)
        self.assertTrue(restored.snapshot()["running"])
        isolated = self.make_controller(
            Path(self.directory.name) / "other" / "computer.sqlite3"
        )
        isolated.initialize()
        self.wait(isolated)
        self.assertFalse(isolated.snapshot()["enabled"])
        restored.command("stop")
        self.wait(restored)
        self.assertFalse(restored.snapshot()["durable"])
        self.assertTrue(
            all(thread != threading.get_ident() for _, thread in self.host.calls)
        )

    def test_stop_before_first_enable_does_not_create_identity_metadata(self):
        self.controller.command("stop")
        self.wait()
        self.assertFalse(self.controller.path.exists())
        self.factory.assert_not_called()

    def test_pairing_is_private_replaceable_expiring_and_revocable(self):
        self.enable()
        self.controller.command("pair")
        self.wait()
        first = self.controller.pairing()["image"]
        state = json.dumps(self.controller.snapshot())
        self.assertNotIn("clarify://", state)
        self.assertNotIn("never-return", state)
        self.controller.command("pair")
        self.wait()
        self.assertNotEqual(first, self.controller.pairing()["image"])
        self.controller.command("close")
        self.assertEqual(self.controller.pairing(), {})
        self.controller.command("pair")
        self.wait()
        self.clock = 1301
        self.assertEqual(self.controller.pairing(), {})
        self.assertFalse(self.controller.snapshot()["pairingReady"])
        self.controller.command("revoke", "phone-1")
        self.wait()
        self.assertEqual(self.controller.snapshot()["devices"], [])

    def test_close_and_shutdown_reject_a_late_pairing(self):
        self.enable()
        entered, release = threading.Event(), threading.Event()

        def create():
            entered.set()
            release.wait(2)
            return {
                "pairing_url": "clarify://computer?data=late-secret",
                "expires_at": 1300,
            }

        self.host.create_pairing = create
        self.controller.command("pair")
        self.assertTrue(entered.wait(1))
        self.controller.command("close")
        release.set()
        self.wait()
        self.assertEqual(self.controller.pairing(), {})
        self.controller.shutdown()
        self.assertFalse(self.host.ready)
        self.assertFalse(self.controller.command("enable"))

    def test_managed_account_blocks_pairing_and_stops_existing_access(self):
        self.blocked = True
        self.assertFalse(self.controller.command("enable"))
        self.factory.assert_not_called()
        self.blocked = False
        self.enable()
        self.blocked = True
        self.controller.refresh()
        self.wait()
        self.assertFalse(self.controller.snapshot()["enabled"])
        self.assertEqual(self.controller.pairing(), {})

    def test_host_errors_cannot_publish_credentials(self):
        self.host.start = Mock(side_effect=RuntimeError("secret-token=private"))
        self.controller.command("enable")
        self.wait()
        state = self.controller.snapshot()
        self.assertEqual(state["error"], "failed")
        self.assertFalse(state["enabled"])
        self.assertNotIn("private", json.dumps(state))
        self.assertEqual(self.host.calls[0][0], "stop")

    def test_stop_closes_listener_even_if_persisting_consent_fails(self):
        self.enable()
        with patch.object(
            self.controller, "_write_durable", side_effect=OSError("locked")
        ):
            self.controller.command("stop")
            self.wait()
        self.assertFalse(self.host.ready)
        self.assertFalse(self.controller.snapshot()["running"])
        self.assertEqual(self.controller.snapshot()["error"], "failed")

    def test_account_restriction_notifies_native_panel_without_recursive_close(self):
        from PySide6.QtCore import QObject, QUrl
        from PySide6.QtQml import QQmlApplicationEngine

        with patch("clarify.desktop.qml_settings._is_windows", return_value=False):
            settings = QmlSettingsController(
                _repositories(self.directory.name),
                local_product=Mock(state=LocalASRProductState("missing"), busy=False),
            )
        self.addCleanup(settings.shutdown)
        settings.bindComputer(self.controller)
        notifications = []
        self.controller.changed.connect(lambda: notifications.append(True))
        self.controller.command("close")
        self.assertEqual(notifications, [])
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(
            lambda errors: warnings.extend(str(error) for error in errors)
        )
        engine.rootContext().setContextProperty("fixtureSettings", settings)
        qml_root = Path(__file__).resolve().parents[1] / "clarify/desktop/qml"
        engine.loadData(
            b'import QtQuick 6.5\nimport "."\nComputerAccess { controller: fixtureSettings; visualTheme: Theme {} }',
            QUrl.fromLocalFile(str(qml_root / "computer-test.qml")),
        )
        self.assertTrue(engine.rootObjects(), warnings)
        root = engine.rootObjects()[0]
        button = root.findChild(QObject, "computerConnectButton")
        self.assertTrue(button.property("enabled"))
        self.blocked = True
        settings.accountStateChanged.emit()
        self.app.processEvents()
        self.assertFalse(button.property("enabled"))
        self.assertEqual(len(notifications), 1)
        self.blocked = False
        settings.accountStateChanged.emit()
        self.app.processEvents()
        self.assertTrue(button.property("enabled"))
        self.assertEqual(len(notifications), 2)
        self.assertEqual(warnings, [])

    def test_shutdown_drains_mobile_work_before_shared_provider_shutdown(self):
        from clarify.desktop.qml_runtime import QtWorkflowRuntime

        self.enable()
        registry = Mock()
        registry.cancel.side_effect = lambda: self.assertFalse(self.host.ready)
        registry.shutdown.side_effect = lambda: self.assertFalse(self.host.ready)
        runtime = QtWorkflowRuntime(
            Mock(), Mock(), Mock(), Mock(), provider_registry=registry
        )
        runtime.computer = self.controller
        runtime.shutdown()
        registry.shutdown.assert_called_once()

    def test_failed_host_shutdown_is_sanitized_and_keeps_provider_lifetime(self):
        from contextlib import redirect_stderr
        import io

        from clarify.desktop.qml_runtime import QtWorkflowRuntime

        self.enable()
        self.host.stop = Mock(side_effect=RuntimeError("permanent-token=private"))
        registry, scheduler, audio = Mock(), Mock(), Mock()
        runtime = QtWorkflowRuntime(
            Mock(), audio, scheduler, Mock(), provider_registry=registry
        )
        runtime.computer = self.controller
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            runtime.shutdown()
        self.assertNotIn("private", stderr.getvalue())
        self.assertEqual(self.controller.snapshot()["error"], "failed")
        registry.cancel.assert_called_once()
        registry.shutdown.assert_not_called()
        scheduler.begin_shutdown.assert_called_once()
        audio.wait_for_shutdown.assert_called_once()
        self.assertFalse(self.controller.shutdown())

    def test_account_transition_cancels_activation_before_host_start(self):
        entered, release = threading.Event(), threading.Event()

        def factory():
            entered.set()
            release.wait(2)
            return self.host

        self.controller._factory = factory
        self.controller.command("enable")
        self.assertTrue(entered.wait(1))
        barrier = self.controller.prepare_account_change()
        release.set()
        self.assertNotIn("error", barrier.result(timeout=2))
        self.wait()
        self.assertFalse(self.host.ready)
        self.assertNotIn("start", [name for name, _ in self.host.calls])

    def test_account_worker_waits_for_personal_host_to_stop(self):
        self.enable()
        account = Mock(history=None, scope=None, signed_in=False)
        account.snapshot.return_value = {
            "signedIn": False,
            "managed": False,
            "hosted": False,
        }
        entered = threading.Event()

        def authenticate(*_):
            self.assertFalse(self.host.ready)
            entered.set()

        account.authenticate.side_effect = authenticate
        with patch("clarify.desktop.qml_settings._is_windows", return_value=False):
            settings = QmlSettingsController(
                _repositories(self.directory.name),
                account_service=account,
                local_product=Mock(state=LocalASRProductState("missing"), busy=False),
            )
        self.addCleanup(settings.shutdown)
        settings.bindComputer(self.controller)
        self.assertTrue(settings.accountCommand("login", "fixture@example.test"))
        self.assertTrue(entered.wait(2))
        account.authenticate.assert_called_once()
        self.wait()

    def test_status_refresh_cannot_reject_an_explicit_preference(self):
        self.enable()
        entered, release = threading.Event(), threading.Event()

        def snapshot():
            entered.set()
            release.wait(2)
            return {"ready": True, "devices": []}

        self.host.snapshot = snapshot
        self.controller.refresh()
        self.assertTrue(entered.wait(1))
        self.assertTrue(self.controller.command("durable", "true"))
        release.set()
        self.wait()
        self.assertTrue(self.controller.snapshot()["durable"])

    def test_bridge_exposes_only_safe_status_and_explicit_pairing_read(self):
        with patch("clarify.desktop.qml_settings._is_windows", return_value=False):
            settings = QmlSettingsController(
                _repositories(self.directory.name),
                local_product=Mock(state=LocalASRProductState("missing"), busy=False),
            )
        self.addCleanup(settings.shutdown)
        settings.bindComputer(self.controller)
        protocol = SettingsProtocol(settings)

        def call(method, *args):
            return protocol.dispatch({"id": 1, "method": method, "args": list(args)})

        self.assertIn("computerState", call("snapshot")["result"])
        self.assertNotIn("error", call("computerCommand", "enable", ""))
        self.wait()
        call("computerCommand", "pair", "")
        self.wait()
        self.assertIn("image", call("getComputerPairing")["result"])
        for method in ("snapshot", "poll"):
            self.assertNotIn("clarify://", json.dumps(call(method)))
        call("computerCommand", "close", "")
        self.assertEqual(call("getComputerPairing")["result"], {})
        self.assertIn("error", call("getComputerPairing", "unexpected"))
        self.assertIn("error", call("computerCommand", "revoke", {}))
        self.assertIn("error", call("_computer", "stop"))


if __name__ == "__main__":
    unittest.main()
