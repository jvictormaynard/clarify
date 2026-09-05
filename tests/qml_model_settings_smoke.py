"""Render the real settings window using isolated config and offline doubles.

Run with QT_QPA_PLATFORM=offscreen and an optional screenshot output directory.
No microphone capture, model download, API request, or user config access.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import (
    QObject,
    QEvent,
    QPointF,
    Qt,
    QUrl,
    Property,
    Signal,
    Slot,
    qInstallMessageHandler,
)
from PySide6.QtGui import QFont, QFontDatabase, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from local_asr_product import LocalASRProductState
from microphone_controls import MicrophoneDevice, MicrophoneInventory
from provider_types import ModelCatalog
from repositories import (
    AppConfig,
    ApplicationRepositories,
    LocalConfigRepository,
    LocalUsageStatsRepository,
)
from secret_store import MemorySecretStore
from spikes.pyside6.qml_bridge import QmlWorkflowBridge
from spikes.pyside6.qml_settings import QmlSettingsController
from workflows import WorkflowState, WorkflowPhase, RetryDictation

ROOT = Path(__file__).resolve().parents[1]


class PillStatus(QObject):
    audioLevel = Property(float, lambda self: 0.0, constant=True)
    targetIcon = Property(str, lambda self: "", constant=True)


class AudioBatch(QObject):
    changed = Signal()
    copyCompleted = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.busy = False
        self.calls = []

    running = Property(bool, lambda self: self.busy, notify=changed)
    canRetry = Property(bool, lambda self: False, notify=changed)
    lastError = Property(str, lambda self: "", notify=changed)
    selectedFiles = Property(
        "QVariantList", lambda self: ["fixture.wav"], notify=changed
    )
    results = Property(
        "QVariantList",
        lambda self: [
            {
                "name": "Meeting.wav",
                "path": "fixture.wav",
                "status": "succeeded",
                "text": "A sample transcript. Select and copy the text you need.",
            }
        ],
        notify=changed,
    )

    @Slot("QVariantList", str, str, str, str, result=bool)
    def start(self, paths, provider, model, language, mode):
        self.calls.append((provider, model))
        self.busy = True
        self.changed.emit()
        return True


class LocalProduct:
    def __init__(self):
        self.requirements = json.loads((ROOT / "local_asr_manifest.json").read_text())[
            "requirements"
        ]
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
        self.listener(
            LocalASRProductState(
                "installing",
                "download:model",
                250000000,
                487601967,
                requirements=self.requirements,
            )
        )

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
        # Stage assets locally, as the Windows packager does. Qt resolves some
        # relative image URLs incorrectly when Main.qml is loaded from WSL UNC.
        qml_source = Path(
            os.environ.get(
                "CLARIFYVOICE_TEST_QML_ROOT", str(ROOT / "spikes/pyside6/qml")
            )
        )
        qml_root = Path(shutil.copytree(qml_source, base / "qml"))
        repositories = ApplicationRepositories(
            LocalConfigRepository(
                base / "config.json", secret_store=MemorySecretStore()
            ),
            LocalUsageStatsRepository(base / "usage.json"),
        )
        repositories.config.save(
            AppConfig.from_mapping({"openai_api_key": "offline-fixture"})
        )
        local = LocalProduct()
        inventory = MicrophoneInventory(
            devices=(
                MicrophoneDevice(
                    "fixture-usb", "USB microphone", input_channels=1, is_default=True
                ),
            ),
            default_id="fixture-usb",
        )
        preview = SimpleNamespace(level=0.0, selected_id=None, closed=True)

        def test_microphone(selection, inventory, *, on_level, cancel_event, duration):
            preview.selected_id = selection.device.stable_id
            preview.closed = False
            try:
                while not cancel_event.wait(0.04):
                    on_level(preview.level)
                return preview.level
            finally:
                preview.closed = True

        controller = QmlSettingsController(
            repositories,
            local_product=local,
            microphone_inventory_source=SimpleNamespace(snapshot=lambda: inventory),
            microphone_backend=SimpleNamespace(
                test_microphone=test_microphone,
                supports_explicit_microphone_selection=lambda: True,
                selectable_microphone_devices=lambda snapshot: (
                    snapshot.available_devices
                ),
            ),
        )
        controller.setRouteProviderId("openai")
        service = SimpleNamespace(
            state=WorkflowState(), subscribe=lambda _listener: None
        )
        bridge = QmlWorkflowBridge(service)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("settings", controller)
        engine.rootContext().setContextProperty("workflow", bridge)
        audio_batch = AudioBatch()
        engine.rootContext().setContextProperty("audioBatch", audio_batch)

        def settle():
            for _ in range(35):
                app.processEvents()
                time.sleep(0.01)

        def shot(name):
            settle()
            if output:
                assert window.grabWindow().save(str(output / f"{name}.png"))

        def click(item, target_window=None):
            ancestor = item.parentItem()
            while ancestor is not None:
                if ancestor.inherits("QQuickFlickable"):
                    offset = item.mapToItem(ancestor, QPointF(0, 0)).y()
                    if offset < 0 or offset + item.height() > ancestor.height():
                        maximum = max(
                            0, ancestor.property("contentHeight") - ancestor.height()
                        )
                        ancestor.setProperty(
                            "contentY",
                            min(
                                maximum,
                                max(0, ancestor.property("contentY") + offset - 12),
                            ),
                        )
                        settle()
                ancestor = ancestor.parentItem()
            position = item.mapToScene(
                QPointF(item.width() / 2, item.height() / 2)
            ).toPoint()
            QTest.mouseClick(
                target_window or window,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                position,
            )
            settle()

        def visible_item(name):
            # Repeater delegates can have different QObject and visual parents.
            candidates = list(window.findChildren(QObject, name))
            pending = [window.contentItem()]
            while pending:
                item = pending.pop()
                if item.objectName() == name:
                    candidates.append(item)
                pending.extend(item.childItems())
            return next(item for item in candidates if item.property("visible"))

        def choose(name, index):
            control = visible_item(name)
            click(control)
            QTest.keyClick(window, Qt.Key.Key_Home)
            for _ in range(index):
                QTest.keyClick(window, Qt.Key.Key_Down)
            QTest.keyClick(window, Qt.Key.Key_Return)
            settle()
            assert not control.property("popupVisible"), name

        def type_text(value):
            # QTest.keyClicks supports QWidget, not QQuickWindow.
            for character in value:
                for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                    app.sendEvent(
                        window,
                        QKeyEvent(
                            kind,
                            ord(character.upper()),
                            Qt.KeyboardModifier.NoModifier,
                            character,
                        ),
                    )

        def edit(name, value):
            field = visible_item(name)
            click(field)
            QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            type_text(value)
            QTest.keyClick(window, Qt.Key.Key_Return)
            QTest.keyClick(window, Qt.Key.Key_Tab)
            settle()

        with patch(
            "spikes.pyside6.qml_settings.PROVIDER_REGISTRY.discover_models",
            return_value=ModelCatalog(
                audio_models=(
                    "whisper-1",
                    "gpt-4o-transcribe",
                    "gpt-4o-mini-transcribe",
                ),
                text_models=("fixture-text",),
            ),
        ) as discovery:
            engine.load(QUrl.fromLocalFile(str(qml_root / "Main.qml")))
            if not engine.rootObjects():
                raise AssertionError("\n".join(messages))
            window = engine.rootObjects()[0]
            window.show()
            shot("home")
            bridge.openSettings()
            settings_page = window.findChild(QObject, "settingsPage")
            shot("general")
            initial_config = controller._config
            for index in (1, 2, 3, 4, 0):
                click(visible_item(f"settingsSection{index}"))
                assert settings_page.property("selectedSection") == index
            assert controller._config == initial_config
            click(visible_item("settingsSection1"))
            shot("models-cloud")
            assert not window.findChild(QObject, "textWorkflowTabs").property("visible")
            assert not window.findChild(QObject, "maximumDurationField").property(
                "visible"
            )
            if "--baseline" in sys.argv:
                settings_page.selectSection(4)
                shot("local-install")
                controller.shutdown()
                return
            assert controller.routeModelStatus == "ready", controller.routeModelStatus
            picker = window.findChild(QObject, "workflowModelPicker")
            assert picker is not None and picker.property("count") == 3
            click(picker)
            shot("model-picker-open")
            QTest.keyClick(window, Qt.Key.Key_Home)
            QTest.keyClick(window, Qt.Key.Key_Return)
            settle()
            assert controller.routeModelId == "gpt-4o-mini-transcribe", (
                controller.routeModelId
            )
            discovery.return_value = ModelCatalog(
                audio_models=tuple(f"fixture-audio-{index}" for index in range(10))
            )
            controller.refreshRouteModels()
            settle()
            assert not picker.property("popupVisible")
            click(picker)
            search = visible_item("workflowModelPickerSearch")
            search.setProperty("text", "audio-7")
            settle()
            assert picker.property("count") == 1
            QTest.keyClick(window, Qt.Key.Key_Return)
            settle()
            assert controller.routeModelId == "fixture-audio-7"
            assert not picker.property("popupVisible")
            click(picker)
            search.setProperty("text", "does-not-exist")
            settle()
            assert picker.property("count") == 0
            QTest.keyClick(window, Qt.Key.Key_Return)
            assert controller.routeModelId == "fixture-audio-7"
            QTest.keyClick(window, Qt.Key.Key_Escape)
            settle()
            assert not picker.property("popupVisible")
            assert bridge.surface == "settings"
            click(picker)
            visible_item("workflowModelPickerSecondary").clicked.emit()
            settle()
            assert visible_item("workflowModelField") is not None
            prompt = visible_item("workflowPromptField")
            prompt.setProperty("text", "A longer instruction.\n" * 12)
            settle()
            assert prompt.property("implicitHeight") > 96
            prompt.editingFinished.emit()
            assert controller.routePrompt == ("A longer instruction.\n" * 12).strip()
            settings_page = window.findChild(QObject, "settingsPage")
            settings_page.selectSection(4)
            shot("connections")
            settings_page.selectSection(0)
            shot("preferences")
            choose("settingsModeBox", controller.modes.index("transcription"))
            assert controller.mode == "transcription"
            settings_page.selectSection(1)
            settle()
            click(visible_item("settingsLanguageBox"))
            type_text("Portuguese")
            QTest.keyClick(window, Qt.Key.Key_Return)
            settle()
            assert controller.language == "pt"
            click(visible_item("settingsLanguageBox"))
            shot("language-picker")
            QTest.keyClick(window, Qt.Key.Key_Escape)
            settle()
            assert bridge.surface == "settings"
            assert not visible_item("settingsLanguageBox").property("popupVisible")
            settings_page.selectSection(0)
            settle()
            was_autostart = controller.autostart
            click(visible_item("autostartBox"))
            assert controller.autostart is not was_autostart
            # These are draft-only changes: no Windows startup or user settings writes.
            controller.setAutostart(was_autostart)
            click(visible_item("historyBox"))
            assert controller.historyEnabled
            edit("historyRetentionField", "45")
            assert controller.historyRetentionDays == 45, (
                controller.historyRetentionDays,
                visible_item("historyRetentionField").property("text"),
                messages,
            )
            shot("general-edited")

            settings_page.selectSection(3)
            settle()
            choose(
                "hotkeyActivationBox",
                controller.hotkeyActivationModes.index("push_to_talk"),
            )
            if controller.hotkeyPushToTalkSupported:
                assert controller.hotkeyActivationMode == "push_to_talk"
            else:
                assert controller.hotkeyActivationMode == "toggle"
                assert "key-release" in controller.lastError
                choose(
                    "hotkeyActivationBox",
                    controller.hotkeyActivationModes.index("toggle"),
                )
            shot("shortcuts")
            # Escape must dismiss a non-searchable selector without closing settings.
            click(visible_item("hotkeyActivationBox"))
            QTest.keyClick(window, Qt.Key.Key_Escape)
            settle()
            assert bridge.surface == "settings"
            assert not visible_item("hotkeyActivationBox").property("popupVisible")

            settings_page.selectSection(1)
            settle()
            click(visible_item("microphoneBox"))
            shot("microphone-picker")
            click(visible_item("microphoneBoxRefresh"))
            settle()
            type_text("USB")
            QTest.keyClick(window, Qt.Key.Key_Return)
            settle()
            assert controller.selectedMicrophoneId == "fixture-usb"
            click(visible_item("microphoneTestButton"))
            assert controller.microphoneTestBusy
            assert preview.selected_id == "fixture-usb"
            wave = visible_item("microphoneTestWaveform")
            assert wave.property("running")
            shot("microphone-silent")
            assert controller.microphoneTestLevel == 0
            preview.level = 0.8
            settle()
            assert controller.microphoneTestLevel == 0.8
            assert max(wave.property("samples").toVariant()) > 0.5
            shot("microphone-live")
            preview.level = 0
            settle()
            assert controller.microphoneTestLevel == 0
            click(visible_item("microphoneTestButton"))
            assert preview.closed and not controller.microphoneTestBusy
            assert not wave.property("visible")
            click(visible_item("microphoneTestButton"))
            settings_page.selectSection(0)
            settle()
            assert preview.closed and not controller.microphoneTestBusy
            settings_page.selectSection(1)
            settle()
            click(visible_item("microphoneTestButton"))
            controller.selectMicrophone("")
            settle()
            assert preview.closed and not controller.microphoneTestBusy
            click(visible_item("microphoneTestButton"))
            window.hide()
            settle()
            assert preview.closed and not controller.microphoneTestBusy
            window.show()
            settle()
            click(visible_item("advancedRecordingGroupToggle"))
            edit("maximumDurationField", "120")
            assert controller.recordingControls["max_duration_seconds"] == 120
            previous_vad = controller.recordingControls["vad"]["enabled"]
            click(visible_item("vadEnabledBox"))
            assert controller.recordingControls["vad"]["enabled"] is not previous_vad
            shot("recording")
            click(visible_item("advancedRecordingGroupToggle"))

            settings_page.selectSection(4)
            settle()
            services = [
                provider
                for provider in controller.providerIds
                if provider != "local_asr"
            ]
            choose("onboardingProviderBox", services.index("openai"))
            assert controller.selectedProviderId == "openai"
            edit("providerApiKeyField", "offline-replacement")
            api_field = visible_item("providerApiKeyField")
            assert api_field.property("displayText") != "offline-replacement"
            assert controller.providerApiKey == "offline-replacement"
            edit("providerBaseUrlField", "https://example.invalid/v1")
            assert controller.providerBaseUrl == "https://example.invalid/v1"
            shot("integrations")
            # Restore defaults before subsequent mocked catalog checks.
            controller.setProviderBaseUrl("")

            bridge.openFiles()
            shot("audio-files")
            choose("batchExecutionBox", 1)
            cloud_providers = [
                provider
                for provider in controller.providersForScope("transcription")
                if provider != "local_asr"
            ]
            choose("batchProviderBox", cloud_providers.index("openai"))
            files_page = visible_item("filesPage")
            assert files_page.property("batchProviderId") == "openai", (
                files_page.property("batchProviderId"),
                cloud_providers,
                visible_item("batchProviderBox").property("selectedLabel"),
                messages,
            )
            click(visible_item("batchModelBox"))
            shot("batch-model-picker")
            visible_item("batchModelBoxSecondary").clicked.emit()
            settle()
            edit("batchModelField", "custom-audio-model")
            assert files_page.property("batchModelId") == "custom-audio-model"
            shot("batch-custom-model")
            files_page.startBatch()
            settle()
            assert audio_batch.calls == [("openai", "custom-audio-model")]
            for name in (
                "batchExecutionBox",
                "batchProviderBox",
                "batchModelBox",
                "batchModelField",
            ):
                assert not visible_item(name).property("enabled"), name
            audio_batch.busy = False
            audio_batch.changed.emit()
            bridge.openSettings()
            settings_page.selectSection(1)
            controller.setRouteProviderId("local_asr")
            shot("local-selection")
            click(visible_item("manageLocalModelsButton"))
            assert settings_page.property("selectedSection") == 4
            shot("local-install")
            assert local.install_calls == 0
            click(visible_item("localInstallButton"))
            assert local.install_calls == 1
            shot("local-progress")
            click(visible_item("localCancelButton"))
            assert controller.localAsrStatus == "cancelled"
            controller._apply_local_state(
                LocalASRProductState("installed", requirements=local.requirements)
            )
            shot("local-ready")
            assert not controller.localAsrCloudRefinement
            # Context navigation must preserve separate routes and cloud consent.
            settings_page.selectSection(2)
            settle()
            for scope in ("rewrite", "translation", "refinement"):
                click(visible_item(f"workflowTab{scope}"))
                assert controller.selectedScope == scope
                shot(f"text-{scope}")
            controller.setRoutePrompt("Standard cleanup fixture")
            choose("cleanupContextBox", 1)
            assert controller.selectedScope == "local_asr_refinement"
            assert not controller.localAsrCloudRefinement
            controller.setRoutePrompt("Local cleanup fixture")
            click(visible_item("workflowEnabledBox"))
            assert controller.localAsrCloudRefinement
            assert controller.routeEnabled
            shot("local-cleanup")
            click(visible_item("workflowEnabledBox"))
            assert not controller.localAsrCloudRefinement
            assert not controller.routeEnabled
            click(visible_item("workflowEnabledBox"))
            assert controller.localAsrCloudRefinement and controller.routeEnabled
            click(visible_item("workflowEnabledBox"))
            assert (
                not controller.localAsrCloudRefinement and not controller.routeEnabled
            )
            choose("cleanupContextBox", 0)
            assert controller.routePrompt == "Standard cleanup fixture"
            choose("cleanupContextBox", 1)
            assert controller.routePrompt == "Local cleanup fixture"
            assert not controller.localAsrCloudRefinement
            settings_page.selectSection(4)
            settle()
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
            click(visible_item("localRemoveButton"))
            visible_item("localConfirmRemoveButton").clicked.emit()
            settle()
            assert local.remove_calls == 1
            assert controller.localAsrStatus == "missing"
            settings_page.selectSection(1)
            controller.setRouteProviderId("groq")
            shot("provider-not-connected")
            assert controller.routeModelStatus == "not_configured"

            # The real secondary window must remain visible on failure and
            # receive mouse actions without accepting keyboard focus.
            pill_status = PillStatus()
            engine.rootContext().setContextProperty("pillStatus", pill_status)
            engine.load(QUrl.fromLocalFile(str(qml_root / "StatusPill.qml")))
            assert len(engine.rootObjects()) == 2, messages
            pill = engine.rootObjects()[1]
            window.hide()
            commands = []

            def dispatch(command):
                commands.append(command)
                bridge._on_workflow_state(
                    WorkflowState(phase=WorkflowPhase.PROCESSING, operation_id=7)
                )

            service.dispatch = dispatch
            service.finish = lambda operation_id: bridge._on_workflow_state(
                WorkflowState()
            )
            bridge.closeSettings()
            bridge._on_workflow_state(
                WorkflowState(
                    phase=WorkflowPhase.FAILED,
                    operation_id=7,
                    status_key="transcription_network",
                    can_retry=True,
                )
            )
            settle()
            assert pill.isVisible() and pill.property("requestedVisible")
            assert pill.flags() & Qt.WindowType.WindowDoesNotAcceptFocus
            assert not window.isVisible()
            if output:
                assert pill.grabWindow().save(str(output / "retry-feedback.png"))
            click(pill.findChild(QObject, "retryTranscriptionButton"), pill)
            assert commands == [RetryDictation(7)]
            assert bridge.surface == "processing"
            assert not bridge.canRetryTranscription
            bridge._on_workflow_state(
                WorkflowState(
                    phase=WorkflowPhase.COMPLETED,
                    operation_id=7,
                    result_text="Recovered fixture transcript",
                )
            )
            settle()
            assert not bridge.feedbackVisible
            assert not pill.property("requestedVisible")
            assert not pill.isVisible()
            assert not window.isVisible()
            bridge._on_workflow_state(
                WorkflowState(
                    phase=WorkflowPhase.FAILED,
                    operation_id=7,
                    status_key="transcription_network",
                    can_retry=True,
                )
            )
            settle()
            click(pill.findChild(QObject, "dismissFeedbackButton"), pill)
            assert not pill.property("requestedVisible")
            assert not window.isVisible()
            bridge.setLanguage("pt")
            bridge._on_workflow_state(
                WorkflowState(
                    phase=WorkflowPhase.FAILED,
                    operation_id=8,
                    status_key="no_selection",
                )
            )
            settle()
            assert pill.isVisible() and bridge.feedbackVisible
            assert "Nenhum texto selecionado" in bridge.status
            assert not pill.findChild(QObject, "retryTranscriptionButton").property(
                "visible"
            )
            assert not window.isVisible()
            if output:
                assert pill.grabWindow().save(str(output / "no-selection-feedback.png"))
            click(pill.findChild(QObject, "dismissFeedbackButton"), pill)
        controller.shutdown()
        failures = [
            message
            for message in messages
            if any(
                word in message
                for word in (
                    "Error:",
                    "Binding loop",
                    "Unable to assign",
                    "is not defined",
                    "Cannot assign",
                    "Cannot open",
                    "Error decoding",
                )
            )
        ]
        if failures:
            raise AssertionError("\n".join(failures))
        print(
            "PASS: full QML settings render; all tabs, input editing, switches, language/microphone selectors, batch custom model and busy state; no QML binding errors"
        )
        window.close()
        engine.deleteLater()
        app.processEvents()
        qInstallMessageHandler(None)


if __name__ == "__main__":
    main()
