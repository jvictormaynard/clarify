"""Keep usable ASR text when optional refinement fails; never bypass cancel."""

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from provider_http import CancellationToken, ProviderCancelledError
from provider_types import RewriteResult, TranscriptionResult
from repositories import AppConfig
from workflow_config import WorkflowConfig, WorkflowRoute
from workflows import (
    RecordingSnapshot,
    StartDictation,
    StopDictation,
    WorkflowPhase,
    WorkflowService,
)

try:
    from spikes.pyside6.qml_runtime import (
        QtHistoryRecorder,
        QtProviderGateway,
        QtWorkflowConfig,
    )
    from spikes.pyside6.qml_bridge import QmlWorkflowBridge
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True


@unittest.skipUnless(QT_AVAILABLE, "PySide6 is required")
class RefinementRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.current = AppConfig(
            workflows=WorkflowConfig(
                transcription=WorkflowRoute(provider_id="openai", model_id="whisper-1"),
                refinement=WorkflowRoute(provider_id="openai", model_id="gpt-4o-mini"),
            )
        )
        self.repositories = SimpleNamespace(config=Mock(load=lambda: self.current))
        self.dictionary = Mock()
        self.dictionary.apply_context.side_effect = lambda request: request
        self.dictionary.expand.side_effect = lambda text: text + " expanded"
        self.gateway = QtProviderGateway(
            QtWorkflowConfig(self.repositories), self.dictionary
        )
        self.token = CancellationToken()
        self.audio = RecordingSnapshot(Path("not-read.wav"), b"audio", self.token)
        self.raw = "  João, use 42 unidades.\nNão envie ainda.  "
        self.asr = self.enterContext(
            patch(
                "spikes.pyside6.qml_runtime.PROVIDER_REGISTRY.transcribe",
                return_value=TranscriptionResult(self.raw, "openai", "whisper-1"),
            )
        )
        self.rewrite = self.enterContext(
            patch(
                "spikes.pyside6.qml_runtime.PROVIDER_REGISTRY.rewrite",
                side_effect=RuntimeError("sensitive provider response"),
            )
        )

    def test_failure_preserves_exact_original_without_second_asr_or_cleanup(self):
        result = self.gateway.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.text, self.raw)
        self.assertEqual(result.raw_text, self.raw)
        self.assertIsNone(result.refined_text)
        self.assertTrue(result.refinement_failed)
        self.assertEqual(result.refinement_model, "gpt-4o-mini")
        self.assertNotIn("sensitive", repr(result))
        self.asr.assert_called_once()
        self.rewrite.assert_called_once()
        self.dictionary.expand.assert_not_called()
        self.assertIn("refinement_ms", result.timings_ms)

    def test_empty_or_invalid_refinement_preserves_original(self):
        self.rewrite.side_effect = None
        for output in ("", " \n ", None):
            with self.subTest(output=output):
                self.rewrite.return_value = RewriteResult(output, "openai", "editor")
                result = self.gateway.transcribe(self.audio, "prompt", "pt")
                self.assertEqual(result.text, self.raw)
                self.assertTrue(result.refinement_failed)

    def test_missing_refinement_model_also_preserves_original(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                refinement=WorkflowRoute(provider_id="openai", model_id=""),
            ),
        )
        result = self.gateway.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.text, self.raw)
        self.assertTrue(result.refinement_failed)
        self.rewrite.assert_not_called()

    def test_cancelled_provider_is_not_a_partial_success(self):
        self.rewrite.side_effect = ProviderCancelledError()
        with self.assertRaises(ProviderCancelledError):
            self.gateway.transcribe(self.audio, "prompt", "pt")

    def test_cancellation_wins_even_when_provider_raises_another_error(self):
        def cancel_then_fail(*args):
            self.token.cancel()
            raise RuntimeError("provider transport failed after cancellation")

        self.rewrite.side_effect = cancel_then_fail
        with self.assertRaises(ProviderCancelledError):
            self.gateway.transcribe(self.audio, "prompt", "pt")
        self.dictionary.expand.assert_not_called()

    def test_asr_failure_does_not_attempt_refinement(self):
        self.asr.side_effect = RuntimeError("ASR failed")
        with self.assertRaisesRegex(RuntimeError, "ASR failed"):
            self.gateway.transcribe(self.audio, "prompt", "pt")
        self.rewrite.assert_not_called()

    def test_success_and_transcription_only_keep_normal_behavior(self):
        self.rewrite.side_effect = None
        self.rewrite.return_value = RewriteResult("Reviewed", "openai", "editor")
        result = self.gateway.transcribe(self.audio, "prompt", "pt")
        self.assertFalse(result.refinement_failed)
        self.assertEqual(result.refined_text, "Reviewed expanded")
        self.rewrite.reset_mock()
        result = self.gateway.transcribe(self.audio, "transcription", "pt")
        self.assertFalse(result.refinement_failed)
        self.assertIsNone(result.refined_text)
        self.rewrite.assert_not_called()

    def test_local_asr_refinement_still_requires_opt_in(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute(
                    provider_id="local_asr", model_id="ggml-small"
                ),
                local_asr_refinement=WorkflowRoute(
                    provider_id="openai", model_id="editor"
                ),
            ),
        )
        with patch.object(self.gateway, "_connection", return_value=None):
            result = self.gateway.transcribe(self.audio, "prompt", "pt")
            self.assertFalse(result.refinement_failed)
            self.rewrite.assert_not_called()
            self.current = replace(self.current, local_asr_cloud_refinement=True)
            result = self.gateway.transcribe(self.audio, "prompt", "pt")
        self.assertTrue(result.refinement_failed)
        self.assertEqual(result.text, self.raw)
        self.rewrite.assert_called_once()

    def test_partial_result_flows_through_clipboard_ui_and_opt_in_history(self):
        from tests.test_workflows import (
            FakeAudio,
            FakeClipboard,
            FakeConfig,
            ImmediateScheduler,
        )

        for moved_focus in (False, True):
            with (
                self.subTest(moved_focus=moved_focus),
                TemporaryDirectory() as directory,
            ):
                self.current = replace(self.current, history_enabled=True)
                self.repositories.config.path = Path(directory) / "config.json"
                clipboard = FakeClipboard()
                target = clipboard.capture_target()
                if moved_focus:
                    clipboard.window = "another-window"
                audio = FakeAudio()
                statistics = Mock()
                scheduler = ImmediateScheduler()
                # No speculative preparation is needed for this gateway test.
                with patch.object(self.gateway, "prepare_dictation"):
                    service = WorkflowService(
                        self.gateway,
                        audio,
                        clipboard,
                        FakeConfig(),
                        statistics,
                        scheduler,
                    )
                    bridge = QmlWorkflowBridge(service)
                    history = QtHistoryRecorder(self.repositories, scheduler)
                    service.subscribe(history.on_state)
                    service.dispatch(StartDictation(target, "prompt", "pt"))
                    service.dispatch(StopDictation())
                self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)
                self.assertEqual(clipboard.writes, [self.raw])
                self.assertEqual(
                    clipboard.auto_pastes, [] if moved_focus else [self.raw]
                )
                self.assertEqual(
                    (audio.started, audio.stopped, audio.completed), (1, 1, 1)
                )
                statistics.record_dictation.assert_called_once()
                self.assertTrue(bridge.refinementFailed)
                self.assertEqual(bridge.surface, "success")
                self.assertIn("Original text", bridge.status)
                records = history.store.list_records()
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0].status, "partial")
                self.assertEqual(records[0].raw_text, self.raw)
                self.assertIsNone(records[0].refined_text)
                self.assertEqual(records[0].error, "refinement_failed")
                history_path = Path(directory) / "history.json"
                before = history_path.read_bytes()
                self.current = replace(self.current, history_enabled=False)
                history.record_state(service.state)
                self.assertEqual(history_path.read_bytes(), before)
                bridge.finish()
                self.assertFalse(bridge.refinementFailed)

    def test_qml_warning_renders_without_focus_and_resets_on_next_operation(self):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("qml_refinement_recovery_smoke.py")),
            ],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: refinement recovery pill", result.stdout)
