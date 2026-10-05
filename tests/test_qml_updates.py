"""The update controller uses fake transport, workers, and restart effects."""

import os
from pathlib import Path
import tempfile
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from clarify.desktop.qml_updates import QmlUpdateController
from portable_updates import PortableUpdateError, verify_manifest
from repositories import AppConfig
from test_portable_updates import ReleaseFixture


class UpdateControllerTests(ReleaseFixture):
    def setUp(self):
        super().setUp()
        self.app = QApplication.instance() or QApplication([])
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.jobs = []
        self.restarts = []
        self.idle = False
        self.release = verify_manifest(*self.encoded(), self.policy, "0.5.0")
        self.transport = Mock()
        self.transport.latest.return_value = self.release

        def download(release, directory, cancel, progress):
            if cancel.is_set():
                raise PortableUpdateError("Atualização cancelada.")
            path = directory / "Clarify.exe"
            path.write_bytes(self.binary)
            progress(100)
            return path

        self.transport.download.side_effect = download
        self.prepared = Mock()
        self.prepared.process.poll.return_value = None
        self.prepared.armed.return_value = False
        self.prepare = Mock(return_value=self.prepared)

    def controller(self, automatic=False, supported=True):
        controller = QmlUpdateController(
            transport=self.transport,
            supported=supported,
            automatic=automatic,
            cache_root=Path(self.temporary.name),
            can_restart=lambda: self.idle,
            restart=lambda: self.restarts.append(True),
            prepare=self.prepare,
            run_worker=self.jobs.append,
        )
        self.addCleanup(controller.shutdown)
        return controller

    def complete_job(self):
        self.assertTrue(self.jobs)
        self.jobs.pop(0)()
        for _ in range(3):
            self.app.processEvents()

    def test_disabled_flag_notifies_without_downloading_or_restarting(self):
        controller = self.controller()
        self.assertTrue(controller.check())
        self.complete_job()
        self.assertTrue(controller.available)
        self.transport.download.assert_not_called()
        self.idle = True
        controller._poll()
        self.assertEqual(self.restarts, [])

    def test_enabled_flag_downloads_and_waits_for_idle_and_helper_acknowledgment(self):
        controller = self.controller(automatic=True)
        self.assertTrue(controller.check())
        self.complete_job()
        self.complete_job()
        controller._poll()
        self.prepare.assert_not_called()
        self.idle = True
        controller._poll()
        self.complete_job()
        controller._poll()
        self.assertEqual(self.restarts, [])
        self.prepared.armed.return_value = True
        controller._poll()
        controller._poll()
        self.assertEqual(self.restarts, [True])

    def test_manual_install_uses_the_same_idle_gate_with_flag_disabled(self):
        controller = self.controller()
        controller.check()
        self.complete_job()
        self.assertTrue(controller.install())
        self.complete_job()
        controller._poll()
        self.prepare.assert_not_called()
        self.idle = True
        controller._poll()
        self.complete_job()
        self.prepared.armed.return_value = True
        controller._poll()
        self.assertEqual(self.restarts, [True])

    def test_disabling_automatic_download_rejects_its_late_result(self):
        controller = self.controller(automatic=True)
        controller.check()
        self.complete_job()
        controller.setAutomatic(False)
        self.complete_job()
        self.idle = True
        controller._poll()
        self.prepare.assert_not_called()
        self.assertTrue(controller.available)

    def test_shutdown_rejects_late_check_results(self):
        controller = self.controller()
        controller.check()
        controller.shutdown()
        self.complete_job()
        self.assertFalse(controller.available)
        self.transport.download.assert_not_called()

    def test_disabling_automatic_preparation_cancels_a_late_helper_without_restart(
        self,
    ):
        controller = self.controller(automatic=True)
        controller.check()
        self.complete_job()
        self.complete_job()
        self.idle = True
        controller._poll()
        controller.setAutomatic(False)
        self.complete_job()
        self.prepared.armed.return_value = True
        controller._poll()
        self.prepared.cancel.assert_called_once()
        self.assertEqual(self.restarts, [])

    def test_source_run_has_no_network_or_install_effects(self):
        controller = self.controller(automatic=True, supported=False)
        self.assertFalse(controller.check())
        self.assertFalse(controller.install())
        self.assertEqual(self.jobs, [])
        self.transport.latest.assert_not_called()

    def test_optional_flag_requires_a_real_boolean_and_survives_serialization(self):
        config = AppConfig.from_mapping({"automatic_updates": True})
        self.assertTrue(getattr(config, "automatic_updates", False))
        self.assertTrue(AppConfig.from_mapping(config.to_mapping()).automatic_updates)
        for value in ("true", "false", 1, None):
            self.assertFalse(
                AppConfig.from_mapping({"automatic_updates": value}).automatic_updates
            )
