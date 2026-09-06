"""Esc keeps audio for one explicit Undo, without publishing or blocking hotkeys."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from spikes.pyside6.qml_bridge import QmlWorkflowBridge
from spikes.pyside6.qml_app import _WorkflowWindowVisibility
from test_workflows import (
    FakeAudio,
    FakeClipboard,
    FakeClock,
    FakeConfig,
    FakeProvider,
    FakeStatistics,
    ImmediateScheduler,
    ManualScheduler,
)
from workflows import (
    CancelDictation,
    StartDictation,
    StopDictation,
    UndoCancelDictation,
    TranscriptionTransportError,
    RetryDictation,
    WorkflowPhase,
    WorkflowService,
)


class CancelledDictationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.audio = FakeAudio()
        self.provider = FakeProvider()
        self.clipboard = FakeClipboard()
        self.statistics = FakeStatistics()
        self.clock = FakeClock()
        self.service = self.make_service(ImmediateScheduler())
        self.bridge = QmlWorkflowBridge(
            self.service, target_provider=self.clipboard.capture_target
        )
        self.bridge.setLanguage("pt")

    def make_service(self, scheduler):
        return WorkflowService(
            self.provider,
            self.audio,
            self.clipboard,
            FakeConfig(),
            self.statistics,
            scheduler,
            self.clock,
        )

    def cancel(self):
        self.assertTrue(self.bridge.handleHotkey("recording_hotkey"))
        self.clock.now += 4
        self.assertTrue(self.bridge.handleHotkey("escape"))
        return self.service.state.operation_id

    def test_escape_preserves_audio_without_provider_or_clipboard_calls(self):
        self.cancel()
        self.assertEqual(self.service.state.phase, WorkflowPhase.CANCELLED)
        self.assertEqual(self.bridge.feedbackTitle, "Transcrição cancelada")
        self.assertTrue(self.bridge.feedbackVisible)
        self.assertTrue(self.bridge.canUndoCancellation)
        self.assertFalse(self.bridge.canRetryTranscription)
        self.assertFalse(self.bridge.busy)
        self.assertEqual(self.audio.stopped, 1)
        self.assertEqual(self.audio.completed, 1)
        self.assertEqual(self.audio.cancelled, 0)
        self.assertFalse(hasattr(self.provider, "transcription_request"))
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.statistics.dictations, [])

    def test_undo_transcribes_original_audio_once_with_original_target_and_options(
        self,
    ):
        operation_id = self.cancel()
        source = self.service._session.retry_audio
        self.clipboard.window = 999  # Focus changed: copy, do not paste elsewhere.
        self.bridge.setLanguage("en")
        self.assertTrue(self.bridge.undoCancellation())
        self.assertFalse(self.bridge.undoCancellation())
        self.assertFalse(self.service.dispatch(UndoCancelDictation(operation_id)))
        self.assertEqual(self.service.state.phase, WorkflowPhase.COMPLETED)
        self.assertIs(self.provider.transcription_request[0], source)
        self.assertEqual(self.provider.transcription_request[1:], ("prompt", "pt"))
        self.assertEqual((self.audio.started, self.audio.stopped), (1, 1))
        self.assertEqual(self.clipboard.writes, ["Transcribed"])
        self.assertEqual(self.clipboard.auto_pastes, [])
        self.assertEqual(self.clipboard.dictation_outputs[0][0].window, 77)
        self.assertEqual(self.statistics.dictations[0][1], 4)
        self.assertEqual(self.bridge.surface, "idle")
        self.assertFalse(self.bridge.feedbackVisible)

    def test_expiry_close_and_shutdown_discard_audio(self):
        for method in ("expiry", "close", "shutdown"):
            with self.subTest(method=method):
                self.setUp()
                operation_id = self.cancel()
                session = self.service._session
                if method == "expiry":
                    self.bridge.dismissFeedback(operation_id)
                elif method == "close":
                    self.bridge.reset()
                else:
                    self.service.cancel_active()
                self.assertIsNone(session.retry_audio)
                self.assertEqual(self.service.state.phase, WorkflowPhase.READY)
                self.assertFalse(self.bridge.undoCancellation())
                self.assertFalse(hasattr(self.provider, "transcription_request"))

    def test_new_shortcuts_discard_old_audio_without_dismiss(self):
        for action in ("recording_hotkey", "rewrite_hotkey", "translation_hotkey"):
            with self.subTest(action=action):
                self.setUp()
                operation_id = self.cancel()
                session = self.service._session
                self.assertTrue(self.bridge.handleHotkey(action))
                self.assertIsNone(session.retry_audio)
                self.assertNotEqual(self.service.state.operation_id, operation_id)
                self.bridge.dismissFeedback(operation_id)
                self.assertNotEqual(self.service.state.phase, WorkflowPhase.READY)
                self.assertFalse(
                    self.service.dispatch(UndoCancelDictation(operation_id))
                )

    def test_empty_capture_has_no_undo_and_still_allows_next_recording(self):
        self.audio.present = False
        self.cancel()
        self.assertTrue(self.bridge.cancellationVisible)
        self.assertFalse(self.bridge.canUndoCancellation)
        self.assertTrue(self.bridge.handleHotkey("recording_hotkey"))
        self.assertEqual(self.service.state.phase, WorkflowPhase.RECORDING)

    def test_pending_capture_cannot_resurrect_expired_audio(self):
        scheduler = ManualScheduler()
        service = self.make_service(scheduler)
        service.dispatch(StartDictation(None, "transcription", "en"))
        scheduler.background.pop(0)()  # Start capture.
        self.assertTrue(service.dispatch(CancelDictation(retain_audio=True)))
        operation_id = service.state.operation_id
        session = service._session
        self.assertFalse(service.dispatch(StopDictation()))
        self.assertFalse(service.dispatch(UndoCancelDictation(operation_id)))
        self.assertTrue(service.finish(operation_id))
        scheduler.background.pop(0)()  # Capture finishes after dismissal.
        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertIsNone(session.retry_audio)
        self.assertFalse(service.dispatch(UndoCancelDictation(operation_id)))
        self.assertTrue(service.dispatch(StartDictation(None, "prompt", "pt")))

    def test_duplicate_undo_and_old_expiry_cannot_interrupt_processing(self):
        operation_id = self.cancel()
        scheduler = ManualScheduler()
        self.service._scheduler = scheduler
        self.assertTrue(self.service.dispatch(UndoCancelDictation(operation_id)))
        self.assertFalse(self.service.dispatch(UndoCancelDictation(operation_id)))
        self.assertFalse(self.service.finish(operation_id))
        while scheduler.soon:
            scheduler.soon.pop(0)()
        self.bridge.dismissFeedback(operation_id)
        self.assertEqual(self.service.state.phase, WorkflowPhase.PROCESSING)
        self.assertEqual(len(scheduler.background), 1)

    def test_undo_network_failure_keeps_explicit_retry(self):
        operation_id = self.cancel()
        self.provider.on_transcribe = Mock(side_effect=TranscriptionTransportError())
        self.assertTrue(self.bridge.undoCancellation())
        self.assertTrue(self.bridge.canRetryTranscription)
        self.assertFalse(self.bridge.canUndoCancellation)
        self.provider.on_transcribe.assert_called_once()
        self.provider.on_transcribe = None
        self.assertTrue(self.service.dispatch(RetryDictation(operation_id)))
        self.assertEqual(self.clipboard.writes, ["Transcribed"])
        self.assertEqual((self.audio.started, self.audio.stopped), (1, 1))

    def test_cancellation_and_undo_do_not_open_or_focus_main_window(self):
        shell = SimpleNamespace(hide_window=Mock(), show_window=Mock())
        coordinator = _WorkflowWindowVisibility(
            self.bridge, shell, SimpleNamespace(isVisible=lambda: True)
        )
        self.cancel()
        self.bridge.undoCancellation()
        shell.show_window.assert_not_called()
        self.assertIsNotNone(coordinator)

    def test_real_recording_session_removes_wav_and_undo_uses_detached_bytes(self):
        from spikes.pyside6.qml_runtime import QtRecordingAudioGateway

        payload = b"RIFF" + b"0" * 1196
        recorder = SimpleNamespace(
            sox=True,
            start=lambda path, _event: path.write_bytes(payload),
            stop=Mock(),
            cancel=Mock(),
        )
        with (
            TemporaryDirectory() as directory,
            patch(
                "spikes.pyside6.qml_runtime._data_directory",
                return_value=Path(directory),
            ),
        ):
            self.service._audio = QtRecordingAudioGateway(recorder)
            self.cancel()
            snapshot = self.service._session.retry_audio
            self.assertEqual(snapshot.audio_bytes, payload)
            self.assertFalse(snapshot.audio_path.exists())
            self.assertFalse(snapshot.cancel_token.cancelled)
            self.assertTrue(self.bridge.undoCancellation())
            self.assertEqual(
                self.provider.transcription_request[0].audio_bytes, payload
            )
            recorder.stop.assert_called_once()
            recorder.cancel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
