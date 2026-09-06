"""Render the real settings window using isolated config and offline doubles.

Run with QT_QPA_PLATFORM=offscreen and an optional screenshot output directory.
No microphone capture, model download, API request, or user config access.
"""
from __future__ import annotations

# Source execution needs the repository on sys.path before application imports.
# ruff: noqa: E402

import json
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, QPointF, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from local_asr_product import LocalASRProductState
from microphone_controls import MicrophoneInventory
from provider_types import ModelCatalog
from repositories import AppConfig, ApplicationRepositories, LocalConfigRepository, LocalUsageStatsRepository
from secret_store import MemorySecretStore
from spikes.pyside6.qml_bridge import QmlWorkflowBridge
from spikes.pyside6.qml_settings import QmlSettingsController
from workflows import WorkflowState


class LocalProduct:
    def __init__(self):
        self.requirements = json.loads((ROOT / "local_asr_manifest.json").read_text())["requirements"]
        self.state = LocalASRProductState("missing", requirements=self.requirements)
        self.installer = SimpleNamespace(platform_supported=lambda: True)
        self.busy = False
        self.install_calls = 0
        self.remove_calls = 0

    def subscribe(self, listener):
        self.listener = listener

    def refresh_async(self):
        pass

    def shutdown(self):
        pass

    def install_async(self):
        self.install_calls += 1
        self.listener(LocalASRProductState("installing", "download:model", 250000000, 487601967, requirements=self.requirements))

    def cancel(self):
        self.listener(LocalASRProductState("cancelled", requirements=self.requirements))

    def remove_async(self):
        self.remove_calls += 1
        self.listener(LocalASRProductState("missing", requirements=self.requirements))


def main():
    QQuickStyle.setStyle("Basic")
    app = QApplication([])
    # The Windows offscreen plugin has no system font database.
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    if font_path.exists():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    messages = []
    qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if output:
        output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as directory:
        base = Path(directory)
        repositories = ApplicationRepositories(
            LocalConfigRepository(base / "config.json", secret_store=MemorySecretStore()),
            LocalUsageStatsRepository(base / "usage.json"),
        )
        repositories.config.save(AppConfig.from_mapping({"openai_api_key": "offline-fixture"}))
        local = LocalProduct()
        controller = QmlSettingsController(
            repositories, local_product=local,
            microphone_inventory_source=lambda: MicrophoneInventory.unavailable("fixture"),
        )
        controller.setRouteProviderId("openai")
        service = SimpleNamespace(state=WorkflowState(), subscribe=lambda _listener: None)
        bridge = QmlWorkflowBridge(service)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("settings", controller)
        engine.rootContext().setContextProperty("workflow", bridge)
        engine.rootContext().setContextProperty("audioBatch", {
            "running": False, "canRetry": False, "lastError": "", "results": [], "selectedFiles": []
        })

        def settle():
            for _ in range(35):
                app.processEvents()
                time.sleep(0.01)

        def shot(name):
            settle()
            if output:
                assert window.grabWindow().save(str(output / f"{name}.png"))

        def click(item):
            # Expanded local-model controls can place the button below the
            # viewport. Scroll to the real item before sending a mouse event.
            ancestor = item.parentItem()
            while ancestor is not None:
                if ancestor.property("contentY") is not None:
                    content = ancestor.property("contentItem")
                    center = item.mapToItem(content, QPointF(0, item.height() / 2)).y()
                    maximum = max(0, ancestor.property("contentHeight") - ancestor.height())
                    ancestor.setProperty("contentY", min(maximum, max(0, center - ancestor.height() / 2)))
                    settle()
                ancestor = ancestor.parentItem()
            position = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, position)
            settle()

        def visible_item(name):
            return next(item for item in window.findChildren(QObject, name) if item.property("visible"))

        with patch("spikes.pyside6.qml_settings.PROVIDER_REGISTRY.discover_models", return_value=ModelCatalog(
            audio_models=("whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"),
            text_models=("fixture-text",),
        )):
            engine.load(QUrl.fromLocalFile(str(ROOT / "spikes/pyside6/qml/Main.qml")))
            if not engine.rootObjects():
                raise AssertionError("\n".join(messages))
            window = engine.rootObjects()[0]
            bridge.openSettings()
            window.show()
            shot("models-cloud")
            assert controller.routeModelStatus == "ready", controller.routeModelStatus
            picker = window.findChild(QObject, "workflowModelPicker")
            assert picker is not None and picker.property("count") == 3
            click(picker)
            shot("model-picker-open")
            QTest.keyClick(window, Qt.Key.Key_Home)
            QTest.keyClick(window, Qt.Key.Key_Return)
            settle()
            assert controller.routeModelId == "gpt-4o-mini-transcribe", controller.routeModelId
            settings_page = window.findChild(QObject, "settingsPage")
            settings_page.setProperty("settingsTab", "connections")
            shot("connections")
            settings_page.setProperty("settingsTab", "preferences")
            shot("preferences")
            settings_page.setProperty("settingsTab", "models")
            controller.setRouteProviderId("local_asr")
            shot("local-install")
            assert local.install_calls == 0
            click(visible_item("localInstallButton"))
            assert local.install_calls == 1
            shot("local-progress")
            click(visible_item("localCancelButton"))
            assert controller.localAsrStatus == "cancelled"
            controller._apply_local_state(LocalASRProductState("installed", requirements=local.requirements))
            shot("local-ready")
            assert not controller.localAsrCloudRefinement
            assert controller.useLocalAsr()
            assert controller.routeModelId == "ggml-small"
            click(visible_item("localRemoveButton"))
            assert visible_item("localConfirmRemoveButton") is not None
            assert local.remove_calls == 0
            # Reject removal; the model must remain installed.
            # Invoke the button signal because the confirmation may require scrolling.
            visible_item("localKeepButton").clicked.emit()
            settle()
            assert controller.localAsrStatus == "installed"
            assert local.remove_calls == 0
            controller.setRouteProviderId("groq")
            shot("provider-not-connected")
            assert controller.routeModelStatus == "not_configured"
        controller.shutdown()
        failures = [message for message in messages if any(word in message for word in (
            "Error:", "Binding loop", "Unable to assign", "is not defined", "Cannot assign"
        ))]
        if failures:
            raise AssertionError("\n".join(failures))
        print("PASS: full QML settings render; cloud, disconnected, local install/progress/ready; no QML binding errors")
        window.close()
        engine.deleteLater()
        app.processEvents()
        qInstallMessageHandler(None)


if __name__ == "__main__":
    main()
