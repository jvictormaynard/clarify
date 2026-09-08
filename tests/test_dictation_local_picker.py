"""Dictation lists verified local installations and saves the chosen model."""

import time
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from test_pyside6_qml_settings import _repositories
from spikes.pyside6.qml_settings import QmlSettingsController
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
                        "spikes.pyside6.qml_settings.PROVIDER_REGISTRY.discover_models"
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
                    engine = QQmlApplicationEngine()
                    engine.rootContext().setContextProperty("testSettings", controller)
                    qml_dir = Path(directory) / "qml"
                    shutil.copytree(
                        Path(__file__).resolve().parents[1] / "spikes/pyside6/qml",
                        qml_dir,
                    )
                    source = """import QtQuick
import QtQuick.Controls
import "DIRECTORY"
ApplicationWindow {
    visible: true; width: 600; height: 480
    Theme { id: theme }
    WorkflowModelForm {
        anchors.fill: parent; anchors.margins: 16
        visualTheme: theme; settingsController: testSettings
    }
}""".replace("DIRECTORY", qml_dir.as_uri())
                    engine.loadData(
                        source.encode(),
                        QUrl.fromLocalFile(str(qml_dir / "picker-test.qml")),
                    )
                    self.assertTrue(engine.rootObjects())
                    window = engine.rootObjects()[0]
                    QTest.qWait(350)
                    self.assertIsInstance(window, QQuickWindow)
                    self.assertIsNone(
                        window.findChild(QQuickItem, "manageLocalModelsButton")
                    )
                    picker = window.findChild(QQuickItem, "workflowModelPicker")
                    self.assertTrue(picker.property("visible"))
                    point = picker.mapToScene(
                        QPointF(picker.width() / 2, picker.height() / 2)
                    ).toPoint()
                    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
                    QTest.qWait(250)
                    self.assertTrue(picker.property("popupVisible"))
                    QTest.keyClick(window, Qt.Key_Home)
                    QTest.keyClick(window, Qt.Key_Down)
                    QTest.keyClick(window, Qt.Key_Return)
                    QTest.qWait(250)
                    self.assertEqual(controller.routeModelId, "ggml-medium")
                    window.close()
                    engine.deleteLater()
                    self.app.processEvents()
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
