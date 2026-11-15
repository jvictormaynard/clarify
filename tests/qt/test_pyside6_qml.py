import ast
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    from PySide6.QtCore import QObject, QTimer, Signal
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
except (ImportError, ModuleNotFoundError):
    PYSIDE6_AVAILABLE = False
    QObject = object

    def Signal(*args, **kwargs):
        return None
else:
    PYSIDE6_AVAILABLE = True

if PYSIDE6_AVAILABLE:
    from clarify.desktop import qml_app
    from clarify.desktop.qml_app import (
        ShellStartResult,
        _connect_preference_sync,
        _connect_shutdown,
        _branding_icon_path,
        _load_branding_icon,
        _record_voice_translation_usage,
        _register_qml_context,
        _hidden_start_requested,
        _start_shell_if_available,
    )
    from clarify.desktop.qml_bridge import QmlWorkflowBridge
    from clarify.desktop.qml_status import (
        QmlStatusPillController,
        _packaged_app_icon,
        _pillow_data_url,
    )
    from clarify.desktop.qml_settings import QmlSettingsController


ROOT = Path(__file__).resolve().parents[2]
SPIKE = ROOT / "clarify" / "desktop"
QML_ROOT = SPIKE / "qml"


class PySide6QmlFrontendTests(unittest.TestCase):
    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
    def test_branding_icon_loads_from_source_and_frozen_bundle_paths(self):
        self._qt_app = QApplication.instance() or QApplication([])
        source_icon = ROOT / "assets" / "branding" / "clarify.ico"
        self.assertEqual(_branding_icon_path(), source_icon)
        source_qicon = _load_branding_icon()
        self.assertIsInstance(source_qicon, QIcon)
        self.assertFalse(source_qicon.isNull())

        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle_root = Path(temporary_directory)
            frozen_icon = bundle_root / "assets" / "branding" / "clarify.ico"
            frozen_icon.parent.mkdir(parents=True)
            shutil.copyfile(source_icon, frozen_icon)
            with (
                patch.object(qml_app.sys, "_MEIPASS", str(bundle_root), create=True),
                patch.object(qml_app.sys, "frozen", True, create=True),
            ):
                self.assertEqual(_branding_icon_path(), frozen_icon)
                frozen_qicon = _load_branding_icon()

            self.assertIsInstance(frozen_qicon, QIcon)
            self.assertFalse(frozen_qicon.isNull())

    def test_qml_runtime_uses_ui_free_adapters(self):
        for filename in ("qml_bridge.py", "qml_runtime.py"):
            source = (SPIKE / filename).read_text(encoding="utf-8")
            tree = ast.parse(source)
            top_level_imports = set()
            for node in tree.body:
                if isinstance(node, ast.Import):
                    top_level_imports.update(
                        alias.name.split(".")[0] for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top_level_imports.add(node.module.split(".")[0])
            self.assertNotIn("app", top_level_imports, filename)
            self.assertNotIn("customtkinter", top_level_imports, filename)
            self.assertNotIn("tkinter", top_level_imports, filename)

        runtime_source = (SPIKE / "qml_runtime.py").read_text(encoding="utf-8")
        for symbol in (
            "QtProviderGateway",
            "QtRecordingAudioGateway",
            "QtWorkflowRuntime",
            "QtClipboardGateway",
            "QtStatisticsGateway",
        ):
            self.assertIn(f"class {symbol}", runtime_source)
        self.assertIn("self.repositories = repositories", runtime_source)
        self.assertIn("repositories=active", runtime_source)
        self.assertIn("PROVIDER_REGISTRY", runtime_source)
        self.assertIn("QmlClipboardGateway", runtime_source)
        self.assertNotIn("import app", runtime_source)
        self.assertNotIn("to_legacy_mapping", runtime_source)

    def test_qml_bridge_routes_native_hotkeys_to_real_commands(self):
        bridge_source = (SPIKE / "qml_bridge.py").read_text(encoding="utf-8")
        self.assertIn("def handleHotkey(self, action: str) -> bool:", bridge_source)
        self.assertIn('normalized == "recording_hotkey"', bridge_source)
        self.assertIn('normalized == "rewrite_hotkey"', bridge_source)
        self.assertIn('normalized == "translation_hotkey"', bridge_source)
        self.assertIn("def _run_when_ready", bridge_source)
        self.assertIn("_pending_workflow_action", bridge_source)
        self.assertIn("StartRewrite(target)", bridge_source)
        self.assertIn("StartTranslation(target)", bridge_source)
        self.assertIn("CancelTranslation()", bridge_source)
        self.assertIn("ChooseTranslationLanguage", bridge_source)
        self.assertIn(
            "def chooseTranslation(self, language: str) -> bool:", bridge_source
        )
        self.assertIn("def cancelTranslation(self) -> bool:", bridge_source)
        self.assertIn(
            "def translationOptions(self) -> list[dict[str, str]]:", bridge_source
        )
        self.assertIn('return "translation_picker"', bridge_source)

    def test_real_entrypoint_has_no_fake_or_legacy_runtime(self):
        source = (SPIKE / "qml_app.py").read_text(encoding="utf-8")
        runtime_source = (SPIKE / "qml_runtime.py").read_text(encoding="utf-8")
        self.assertIn("QtRuntimeError", source)
        self.assertNotIn("FakeWorkflow", source)
        self.assertNotIn("legacy_adapters", runtime_source)
        self.assertNotIn("QmlRuntimeUnavailableError", runtime_source)
        self.assertIn("_hidden_start_requested", source)
        self.assertIn("presentationVisible", source)

    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
    def test_qml_entrypoint_accepts_only_the_supported_hidden_start_flag(self):
        self.assertFalse(_hidden_start_requested([]))
        self.assertTrue(_hidden_start_requested(["--hidden"]))
        with self.assertRaises(ValueError):
            _hidden_start_requested(["--compat"])

    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
    def test_voice_translation_usage_callback_records_both_legs(self):
        class UsageRepository:
            def __init__(self):
                self.events = []

            def append(self, event):
                self.events.append(event)

        usage_repository = UsageRepository()
        statistics = qml_app.QtStatisticsGateway(
            SimpleNamespace(usage_stats=usage_repository)
        )
        config = SimpleNamespace(
            route=SimpleNamespace(provider_id="openai", model_id="gpt-4o-mini"),
            target_language="en-US",
        )
        state = SimpleNamespace(
            transcription_provider="gemini",
            transcription_model="gemini-audio",
            raw_transcript="Olá",
            translated_text="Hello",
        )

        _record_voice_translation_usage(statistics, config, state, 12.5)

        self.assertEqual(len(usage_repository.events), 1)
        event = usage_repository.events[0]
        self.assertEqual(event["type"], "voice_translation")
        self.assertEqual(event["duration_seconds"], 12.5)
        self.assertEqual(event["target_language"], "en-US")
        self.assertEqual(
            [
                (entry["provider"], entry["model"], entry["purpose"])
                for entry in event["models"]
            ],
            [
                ("gemini", "gemini-audio", "transcription"),
                ("openai", "gpt-4o-mini", "translation"),
            ],
        )


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class QmlWorkflowBridgeHotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    class WorkflowService:
        def __init__(self):
            from workflows import WorkflowState

            self.state = WorkflowState()
            self.commands = []
            self.listeners = []
            self.finish_calls = []

        def subscribe(self, listener):
            self.listeners.append(listener)

        def publish(self, state):
            self.state = state
            for listener in tuple(self.listeners):
                listener(state)

        def dispatch(self, command):
            self.commands.append(command)
            return True

        def finish(self, operation_id):
            from workflows import WorkflowState

            self.finish_calls.append(operation_id)
            self.publish(WorkflowState())
            return True

    class VoiceTranslationController(QObject):
        stateChanged = Signal(object)

        def __init__(self, active):
            super().__init__()
            self.active = active
            self.state = None

    class AudioBatchController(QObject):
        runningChanged = Signal()

        def __init__(self, running):
            super().__init__()
            self.running = running

    def _bridge(self, *, voice_active=False, audio_running=False, handler=None):
        service = self.WorkflowService()
        voice = self.VoiceTranslationController(voice_active)
        audio = self.AudioBatchController(audio_running)
        bridge = QmlWorkflowBridge(
            service,
            voice_translation_handler=handler,
            voice_translation_controller=voice,
            audio_batch_controller=audio,
        )
        return service, bridge

    def test_global_hotkeys_are_blocked_by_voice_or_audio_busy_state(self):
        for busy_kwargs in (
            {"voice_active": True},
            {"audio_running": True},
        ):
            with self.subTest(busy_kwargs=busy_kwargs):
                service, bridge = self._bridge(**busy_kwargs)

                self.assertTrue(bridge.busy)
                for action in (
                    "recording_hotkey",
                    "rewrite_hotkey",
                    "translation_hotkey",
                ):
                    with self.subTest(action=action):
                        self.assertFalse(bridge.handleHotkey(action))
                self.assertEqual(service.commands, [])

    def test_voice_translation_hotkey_stops_active_voice_workflow(self):
        calls = []
        service, bridge = self._bridge(
            voice_active=True,
            handler=lambda: calls.append("toggle"),
        )

        self.assertTrue(bridge.busy)
        self.assertTrue(bridge.handleHotkey("voice_translation_hotkey"))
        self.assertEqual(calls, ["toggle"])
        self.assertEqual(service.commands, [])

    def test_recording_hotkey_stops_active_workflow_even_when_busy(self):
        from workflows import StopDictation, WorkflowPhase, WorkflowState

        service, bridge = self._bridge(audio_running=True)
        service.publish(WorkflowState(phase=WorkflowPhase.RECORDING))

        self.assertTrue(bridge.busy)
        self.assertTrue(bridge.handleHotkey("recording_hotkey"))
        self.assertIsInstance(service.commands[-1], StopDictation)

    def test_terminal_result_is_released_before_next_global_workflow_hotkey(self):
        from workflows import (
            StartDictation,
            StartRewrite,
            StartTranslation,
            WorkflowPhase,
            WorkflowState,
        )

        cases = (
            ("recording_hotkey", StartDictation),
            ("rewrite_hotkey", StartRewrite),
            ("translation_hotkey", StartTranslation),
        )
        for action, command_type in cases:
            with self.subTest(action=action):
                service, bridge = self._bridge()
                service.publish(
                    WorkflowState(
                        phase=WorkflowPhase.COMPLETED,
                        operation_id=17,
                        result_text="previous result",
                    )
                )

                self.assertTrue(bridge.handleHotkey(action))
                self.assertEqual(service.finish_calls, [17])
                self.assertIsInstance(service.commands[-1], command_type)

    def test_completed_workflow_does_not_open_result_surface(self):
        from workflows import WorkflowPhase, WorkflowState

        service, bridge = self._bridge()
        service.publish(
            WorkflowState(
                phase=WorkflowPhase.COMPLETED,
                operation_id=17,
                result_text="previous result",
            )
        )

        self.assertEqual(bridge.surface, "idle")
        self.assertFalse(bridge.feedbackVisible)
        self.assertEqual(bridge.result, "previous result")
        self.assertTrue(bridge.canShowResult)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class QmlEntrypointIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_uses_qapplication_and_registers_real_context_properties(self):
        self.assertIsInstance(self.app, QApplication)
        engine = QQmlApplicationEngine()
        workflow = QObject()
        settings = QObject()

        _register_qml_context(engine, workflow, settings)

        self.assertIs(engine.rootContext().contextProperty("workflow"), workflow)
        self.assertIs(engine.rootContext().contextProperty("settings"), settings)

    def test_status_pill_samples_live_level_and_refreshes_target_icon(self):
        class Bridge(QObject):
            recordingChanged = Signal()
            targetExecutableChanged = Signal()

            def __init__(self):
                super().__init__()
                self.recording = False
                self.targetExecutable = ""

        bridge = Bridge()
        recorder = SimpleNamespace(mic_level=0.0)
        resolved = []
        controller = QmlStatusPillController(
            bridge,
            recorder,
            fallback_icon=QIcon(),
            icon_resolver=lambda executable: (
                resolved.append(executable) or f"icon:{executable}"
            ),
        )

        bridge.targetExecutable = "C:/Windows/notepad.exe"
        bridge.targetExecutableChanged.emit()
        self.assertEqual(controller.targetIcon, "icon:C:/Windows/notepad.exe")

        bridge.recording = True
        bridge.recordingChanged.emit()
        recorder.mic_level = 0.8
        controller._sample_level()
        self.assertGreater(controller.audioLevel, 0.0)

        bridge.recording = False
        bridge.recordingChanged.emit()
        self.assertEqual(controller.audioLevel, 0.0)

    def test_status_pill_prefers_packaged_high_resolution_icon_asset(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "Example.Package"
            executable = package / "bin" / "Example.exe"
            assets = package / "assets"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"MZ")
            assets.mkdir()
            source = assets / "Square44x44Logo.targetsize-64_altform-unplated.png"
            Image.new("RGBA", (128, 128), (24, 96, 220, 255)).save(source)

            icon = _packaged_app_icon(str(executable))

        self.assertIsNotNone(icon)
        assert icon is not None
        self.assertEqual(icon.size, (64, 64))
        self.assertEqual(icon.getchannel("A").getbbox(), (4, 4, 60, 60))
        self.assertTrue(_pillow_data_url(icon).startswith("data:image/png;base64,"))

    def test_shutdown_connections_stop_shell_before_runtime(self):
        events = []

        class Shell(QObject):
            def stop(self):
                events.append("shell")

        class Runtime:
            def shutdown(self):
                events.append("runtime")

        shell = Shell()
        runtime = Runtime()
        _connect_shutdown(self.app, shell, runtime)
        QTimer.singleShot(0, self.app.quit)
        self.app.exec()

        self.assertEqual(events[-2:], ["shell", "runtime"])

    def test_feedback_expiry_releases_only_its_own_non_retryable_error(self):
        from workflows import WorkflowPhase, WorkflowState

        service = QmlWorkflowBridgeHotkeyTests.WorkflowService()
        bridge = QmlWorkflowBridge(service)
        service.publish(
            WorkflowState(
                phase=WorkflowPhase.FAILED, operation_id=9, status_key="no_selection"
            )
        )
        bridge.dismissFeedback(8)
        self.assertEqual(service.finish_calls, [])
        bridge.dismissFeedback(9)
        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        service.publish(
            WorkflowState(
                phase=WorkflowPhase.FAILED,
                operation_id=10,
                status_key="transcription_network",
                can_retry=True,
            )
        )
        bridge.dismissFeedback(10)
        self.assertTrue(bridge.canRetryTranscription)
        self.assertEqual(service.finish_calls, [9])

    def test_preferences_sync_persists_home_changes_and_keeps_settings_as_draft(self):
        from repositories import AppConfig
        from workflows import StartDictation, WorkflowState

        class ConfigRepository:
            def __init__(self, config):
                self.config = config
                self.applied = []

            def load(self):
                return self.config

            def apply(self, config):
                self.config = config
                self.applied.append(config)
                return config

        class Repositories:
            def __init__(self, config):
                self.config = config

        class WorkflowService:
            def __init__(self):
                self.state = WorkflowState()
                self.listeners = []
                self.commands = []

            def subscribe(self, listener):
                self.listeners.append(listener)

            def dispatch(self, command):
                self.commands.append(command)
                return True

        initial = AppConfig.from_mapping(
            {
                "ui_mode": "prompt",
                "ui_language": "en",
                "autostart": False,
                "history_enabled": False,
                "workflows": {
                    "rewrite": {
                        "provider_id": "openai",
                        "model_id": "gpt-4o-mini",
                        "prompt": "Persisted prompt",
                        "enabled": True,
                    }
                },
            }
        )
        config_repository = ConfigRepository(initial)
        config_repository.path = (
            Path(self.enterContext(tempfile.TemporaryDirectory())) / "config.json"
        )
        settings = QmlSettingsController(Repositories(config_repository))
        service = WorkflowService()
        bridge = QmlWorkflowBridge(service, app_config=initial)
        _connect_preference_sync(bridge, settings)

        settings.setMode("transcription")
        settings.setLanguage("pt")
        settings.selectWorkflow("rewrite")
        settings.setRoutePrompt("Draft prompt")
        settings.setHistoryEnabled(True)
        settings.setAutostart(True)
        self.assertEqual(config_repository.applied, [])
        bridge.startRecording()

        self.assertIsInstance(service.commands[-1], StartDictation)
        self.assertEqual(service.commands[-1].mode, "prompt")
        self.assertEqual(service.commands[-1].language, "pt")

        bridge.setMode("prompt")
        bridge.setLanguage("de")
        self.assertEqual(settings.mode, "prompt")
        self.assertEqual(settings.language, "de")
        self.assertEqual(len(config_repository.applied), 1)
        reloaded = QmlSettingsController(Repositories(config_repository))
        self.assertEqual(reloaded.mode, "prompt")
        self.assertEqual(reloaded.language, "de")
        self.assertFalse(reloaded.autostart)
        self.assertFalse(reloaded.historyEnabled)
        self.assertEqual(reloaded.routeFor("rewrite")["prompt"], "Persisted prompt")
        self.assertEqual(settings.routePrompt, "Draft prompt")
        self.assertTrue(settings.autostart)
        self.assertTrue(settings.historyEnabled)

        settings.setMode("transcription")
        settings.setLanguage("pt")
        self.assertEqual(bridge.mode, "prompt")
        self.assertEqual(bridge.language, "pt")
        self.assertTrue(settings.dirty)
        self.assertEqual(len(config_repository.applied), 1)

        self.assertTrue(settings.save())
        self.assertEqual(len(config_repository.applied), 2)
        persisted = config_repository.load()
        self.assertEqual(persisted.ui.mode, "prompt")
        self.assertEqual(persisted.ui.language, "pt")

    def test_shell_failure_is_distinguished_from_secondary_and_success(self):
        shell = SimpleNamespace(
            start=Mock(side_effect=RuntimeError("hotkey setup failed"))
        )
        self.assertIs(_start_shell_if_available(shell), ShellStartResult.SETUP_FAILED)
        self.assertIs(
            _start_shell_if_available(SimpleNamespace(start=lambda: True)),
            ShellStartResult.STARTED,
        )
        self.assertIs(
            _start_shell_if_available(SimpleNamespace(start=lambda: False)),
            ShellStartResult.SECONDARY_INSTANCE,
        )


if __name__ == "__main__":
    unittest.main()
