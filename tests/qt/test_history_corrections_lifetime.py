"""Isolate Qt destruction and controlled worker GC from the test runner."""

import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import weakref
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]


def _probe(shutdown):
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import Qt, Slot, qInstallMessageHandler
    from PySide6.QtWidgets import QApplication

    # Resolve all application paths inside the fixture before product imports.
    with (
        tempfile.TemporaryDirectory() as directory,
        patch.object(Path, "home", return_value=Path(directory)),
    ):
        from clarify.desktop.qml_settings import QmlSettingsController
        from clarify_account import AccountService
        from history_corrections import CorrectionError, CorrectionSource
        from local_asr_product import LocalASRProductState
        from microphone_controls import MicrophoneInventory
        from secret_store import PlaintextFileSecretStore
        from tests.support.settings import _repositories

        root = Path(directory)
        app = QApplication.instance() or QApplication([])
        main_thread = threading.get_ident()
        destroyed_on = []
        messages = []

        @Slot()
        def destroyed():
            destroyed_on.append(threading.get_ident())

        def new_controller():
            account = AccountService(
                root,
                request=Mock(side_effect=AssertionError("Unexpected network access")),
                secrets=PlaintextFileSecretStore(root / "test-secrets.json"),
                default_endpoint="https://clarify.example",
            )
            with patch("local_asr_catalog.devices", return_value=[]):
                controller = QmlSettingsController(
                    _repositories(root),
                    account_service=account,
                    microphone_inventory_source=Mock(
                        snapshot=Mock(
                            return_value=MicrophoneInventory.unavailable("test")
                        )
                    ),
                    local_product=Mock(
                        state=LocalASRProductState("missing"), busy=False
                    ),
                )
                for worker in (
                    controller._local_inventory_thread,
                    controller._microphone_inventory_thread,
                ):
                    worker.join(5)
                    assert not worker.is_alive()
            controller.destroyed.connect(destroyed, Qt.ConnectionType.DirectConnection)
            if shutdown:
                controller.shutdown()
            return controller

        previous_handler = qInstallMessageHandler(
            lambda kind, context, message: messages.append(message)
        )
        gc.collect()
        gc.disable()
        try:
            controller = new_controller()
            assert threading.enumerate() == [threading.main_thread()]
            reference = weakref.ref(controller)
            del controller

            collected_on = []

            def collect():
                collected_on.append(threading.get_ident())
                gc.collect()

            worker = threading.Thread(target=collect, name="CorrectionLifetimeGC")
            worker.start()
            worker.join(5)
            assert not worker.is_alive()
            # The broken adapter can segfault here, so this runs in a subprocess.
            app.processEvents()
            assert reference() is None
            assert destroyed_on == [main_thread], destroyed_on
            assert collected_on and collected_on[0] != main_thread

            # Retaining the service must not retain its Qt owner either.
            controller = new_controller()
            service = controller._history_corrections
            reference = weakref.ref(controller)
            del controller
            assert reference() is None
            assert destroyed_on == [main_thread, main_thread], destroyed_on
            before = sorted(root.rglob("*"))
            with (
                patch.object(
                    Path,
                    "read_text",
                    side_effect=AssertionError("Unexpected profile read"),
                ),
                patch.object(
                    service.dictionary,
                    "reload",
                    side_effect=AssertionError("Unexpected reload"),
                ),
                patch.object(
                    service.dictionary,
                    "replace",
                    side_effect=AssertionError("Unexpected write"),
                ),
            ):
                for operation in (
                    service._identity,
                    lambda: service._read_part("context", "id", 0, "transcript"),
                    lambda: service.preview(
                        CorrectionSource("context", "revision", "id"),
                        "context",
                        "heard",
                        "corrected",
                    ),
                ):
                    try:
                        operation()
                    except CorrectionError as error:
                        assert error.code == "context_changed", error.code
                    else:
                        raise AssertionError("Released owner accepted a correction")
            assert sorted(root.rglob("*")) == before
            assert not any("QObject::" in message for message in messages), messages
            print(
                json.dumps(
                    {"destroyed_on_main": True, "worker_gc": True, "shutdown": shutdown}
                )
            )
        finally:
            gc.enable()
            qInstallMessageHandler(previous_handler)


class HistoryCorrectionLifetimeTests(unittest.TestCase):
    def test_worker_collection_cannot_destroy_the_correction_owner(self):
        for state in ("active", "shutdown"):
            with self.subTest(state=state):
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--probe", state],
                    cwd=ROOT,
                    env=dict(
                        os.environ, QT_QPA_PLATFORM="offscreen", PYTHONFAULTHANDLER="1"
                    ),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(json.loads(result.stdout)["destroyed_on_main"])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        _probe(sys.argv[2] == "shutdown")
    else:
        unittest.main()
