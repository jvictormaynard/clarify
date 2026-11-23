"""Dictation lists verified local installations and saves the chosen model."""

import time
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from tests.support.settings import _repositories
from clarify.desktop.qml_settings import QmlSettingsController
from local_asr_product import LocalASRProductState


class LocalPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_lists_installed_profiles_and_persists_selection_without_download(self):
        with TemporaryDirectory() as directory:
            product = Mock(state=LocalASRProductState("missing"))
            controller = QmlSettingsController(
                _repositories(directory), local_product=product
            )
            installed = {"ggml-base", "ggml-medium"}

            def installer(model, device):
                return Mock(
                    status=lambda: {
                        "state": "installed" if model in installed else "not_installed"
                    }
                )

            try:
                controller.selectWorkflow("transcription")
                controller.setRouteProviderId("local_asr")
                with (
                    patch("local_asr_catalog.installer_for", side_effect=installer),
                    patch(
                        "clarify.desktop.qml_settings.PROVIDER_REGISTRY.discover_models"
                    ) as cloud,
                ):
                    self.assertTrue(controller.loadRouteModels())
                    deadline = time.monotonic() + 5
                    while (
                        controller.routeModelStatus == "loading"
                        and time.monotonic() < deadline
                    ):
                        self.app.processEvents()
                        time.sleep(0.01)
                    self.assertEqual(controller.routeModelStatus, "ready")
                    self.assertEqual(
                        [x["id"] for x in controller.routeModelOptions],
                        ["ggml-base", "ggml-medium"],
                    )
                    self.assertIn("Medium", controller.routeModelOptions[1]["label"])
                    self.assertTrue(controller.setRouteModelId("ggml-medium"))
                    self.assertTrue(controller.save())
                    self.assertEqual(
                        controller.repositories.config.load().local_asr.audio_model,
                        "ggml-medium",
                    )
                    cloud.assert_not_called()
                    product.install_async.assert_not_called()
                    installed.clear()
                    self.assertTrue(controller.refreshRouteModels())
                    deadline = time.monotonic() + 5
                    while (
                        controller.routeModelStatus == "loading"
                        and time.monotonic() < deadline
                    ):
                        self.app.processEvents()
                        time.sleep(0.01)
                    self.assertEqual(controller.routeModelOptions, [])
                    self.assertEqual(controller.routeModelStatus, "empty")
                    self.assertEqual(controller.routeModelId, "ggml-medium")
            finally:
                controller.shutdown()
