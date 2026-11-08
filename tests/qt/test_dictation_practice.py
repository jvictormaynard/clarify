"""Practice exercises the production workflow with fake audio and providers."""

import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from tests.support.workflows import (
    FakeAudio,
    FakeProvider,
    ImmediateScheduler,
)
from clarify.desktop.dictation_practice import (
    PracticeController,
    practice_readiness,
)


class PracticeSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tests.support.settings import (
            _repositories,
            _MicrophoneBackend,
        )
        from clarify.desktop.qml_settings import QmlSettingsController
        from tests.support.practice_settings_fixture import bind_practice
        from microphone_controls import MicrophoneInventory
        from local_asr_product import LocalASRProductState
        from unittest.mock import Mock

        self.directory = TemporaryDirectory()
        self.settings = QmlSettingsController(
            _repositories(self.directory.name),
            microphone_backend=_MicrophoneBackend(
                MicrophoneInventory.unavailable("fixture")
            ),
            local_product=Mock(state=LocalASRProductState("missing"), busy=False),
        )
        self.settings._microphone_inventory_generation += 1
        self.settings._microphone_inventory_busy = False
        self.practice = bind_practice(self.settings, self.app)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.settings.shutdown)

    def test_setup_opens_practice_only_after_storage_succeeds(self):
        from unittest.mock import patch

        repo = self.settings.repositories.config
        with patch.object(repo, "apply", side_effect=OSError("fixture failure")):
            self.assertFalse(self.settings.completeOnboarding("byok", "gsk_test_only"))
        self.assertFalse(self.settings.practiceState["open"])
        self.assertTrue(self.settings.completeOnboarding("byok", "gsk_test_only"))
        self.assertTrue(self.settings.practiceState["open"])
        self.assertEqual(self.practice.workflow.state.phase.value, "ready")
        self.settings.practiceCommand("close")
        before = repo.path.read_bytes()
        self.settings.practiceCommand("open")
        self.settings.practiceCommand("close")
        self.assertEqual(repo.path.read_bytes(), before)

    def test_local_readiness_blocks_missing_model_and_pending_download(self):
        self.settings.completeOnboarding("local", "")

        def unavailable(_model, _device):
            return False

        self.assertEqual(
            practice_readiness(self.settings, lambda: True, unavailable),
            "practice_model",
        )
        self.settings._local_state = SimpleNamespace(status="installed")
        self.assertEqual(
            practice_readiness(self.settings, lambda: False, unavailable),
            "practice_busy",
        )

    def test_local_readiness_uses_saved_route_and_device_instead_of_browsed_model(self):
        from dataclasses import replace
        from unittest.mock import Mock

        self.settings.completeOnboarding("local", "")
        repo = self.settings.repositories.config
        config = repo.load()
        config = replace(
            config,
            local_asr_device="cuda:1",
            workflows=config.workflows.with_route(
                "transcription",
                replace(config.workflow("transcription"), model_id="ggml-small"),
            ),
        )
        repo.apply(config)
        self.settings._local_profile = "ggml-medium"
        self.settings._local_state = SimpleNamespace(status="missing")
        ready = Mock(return_value=True)
        self.assertEqual(practice_readiness(self.settings, lambda: True, ready), "")
        ready.assert_called_once_with("ggml-small", "cuda:1")
        self.settings._local_state = SimpleNamespace(status="installed")
        ready.return_value = False
        self.assertEqual(
            practice_readiness(self.settings, lambda: True, ready), "practice_model"
        )

    def test_readiness_keeps_expired_managed_session_out_of_personal_route(self):
        self.settings.completeOnboarding("byok", "gsk_test_only")
        self.settings._account.snapshot = lambda: {"managed": True, "signedIn": False}
        self.assertEqual(
            practice_readiness(self.settings, lambda: True), "practice_session"
        )
        self.settings._account.snapshot = lambda: {"managed": True, "signedIn": True}
        self.assertEqual(practice_readiness(self.settings, lambda: True), "")
        self.settings._account.snapshot = lambda: {
            "managed": True,
            "signedIn": True,
            "usage": {"schema_version": 2, "hosted_available": False},
        }
        self.assertEqual(
            practice_readiness(self.settings, lambda: True), "practice_quota"
        )

    def test_protocol_allowlist_and_window_close_cancel_practice(self):
        from clarify.desktop.qml_web_settings import (
            SettingsProtocol,
            WebSettingsProcess,
        )
        from unittest.mock import Mock

        protocol = SettingsProtocol(self.settings)
        for args in ([], ["start", "extra"], [7], ["rewrite"], ["shutdown"]):
            self.assertIn(
                "error", protocol.dispatch({"method": "practiceCommand", "args": args})
            )
        self.settings.completeOnboarding("local", "")
        host = WebSettingsProcess(
            self.settings,
            SimpleNamespace(surface="settings", closeSettings=Mock()),
            Mock(),
        )
        host._finished(0, None)
        self.assertFalse(self.settings.practiceState["open"])

    def test_session_change_stops_the_microphone_test_and_clears_results(self):
        import threading

        identity = ["session-a"]
        self.practice.identity = lambda: identity[0]
        self.practice.command("open")
        self.settings._microphone_test_busy = True
        self.settings._microphone_test_cancel = threading.Event()
        identity[0] = "session-b"
        state = self.practice.snapshot()
        self.assertTrue(self.settings._microphone_test_cancel.is_set())
        self.assertEqual(state["text"], "")
        self.assertEqual(state["blocked"], "practice_session")

    def test_runtime_practice_uses_shared_pipeline_without_touching_clipboard(self):
        import os
        from unittest.mock import Mock, patch
        from clarify.desktop.qml_runtime import create_real_workflow_runtime

        with patch.dict(os.environ, {"CLARIFY_DATA_DIR": self.directory.name}):
            runtime = create_real_workflow_runtime(
                ImmediateScheduler(),
                repositories=self.settings.repositories,
            )
        self.assertIs(
            runtime.practice_workflow._provider, runtime.workflow_service._provider
        )
        self.assertIs(runtime.practice_workflow._audio, runtime.recording_audio)
        self.assertIs(
            runtime.practice_workflow._config, runtime.workflow_service._config
        )
        clipboard_write = Mock()
        runtime.clipboard.write_dictation_result = clipboard_write
        runtime.recording_audio.microphone_available = lambda: True
        runtime.recording_audio.create_session = FakeAudio
        runtime.practice_workflow._provider.transcribe = FakeProvider().transcribe
        runtime.practice_workflow._provider.prepare_dictation = lambda _recording: None
        practice = PracticeController(
            runtime.practice_workflow, language=lambda: "pt", readiness=lambda: ""
        )
        practice.command("open")
        practice.command("start")
        practice.command("stop")
        self.assertEqual(practice.snapshot()["text"], "Transcribed")
        self.assertEqual(len(runtime.repositories.usage_stats.load_events()), 1)
        clipboard_write.assert_not_called()
