"""Exercise ESC/next shortcut with the real Qt owner, scheduler and bridge."""

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication
from spikes.pyside6.qml_bridge import QmlWorkflowBridge
from spikes.pyside6.qml_runtime import (
    QtRecordingSession,
    QtRecordingAudioGateway,
    QtWorkflowScheduler,
)
from workflows import WorkflowService, WorkflowPhase, SelectionTarget
from test_workflows import FakeProvider, FakeClock
from test_workflow_recording_integration import Config, Clipboard, Statistics


class Recorder:
    sox = "test-sox"

    def start(self, path, cancel_event):
        path.write_bytes(b"a" * 1600)

    def stop(self):
        pass

    def cancel(self):
        pass


class CancelRestartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def wait(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertTrue(predicate(), "Lifecycle did not settle")

    def test_cancel_snapshot_does_not_finish_stream_and_undo_token_is_live(self):
        with (
            TemporaryDirectory() as directory,
            patch(
                "spikes.pyside6.qml_runtime._data_directory",
                return_value=Path(directory),
            ),
        ):
            session = QtRecordingSession(Recorder())
            session.start()
            old_token = session.provider_cancel_token
            stream = Mock()
            stream.finish.side_effect = AssertionError(
                "ESC must not finalize inference"
            )
            session.local_stream = stream
            snapshot = session.stop_for_cancel()
            session.complete()
            stream.finish.assert_not_called()
            stream.cancel.assert_called()
            self.assertTrue(old_token.cancelled)
            self.assertFalse(snapshot.cancel_token.cancelled)
            self.assertEqual(snapshot.audio_bytes, b"a" * 1600)
            self.assertIsNone(snapshot.pretranscribed)
            self.assertFalse(session.audio_path.exists())

    def test_next_hotkey_waits_for_owner_then_starts_without_second_press(self):
        with (
            TemporaryDirectory() as directory,
            patch(
                "spikes.pyside6.qml_runtime._data_directory",
                return_value=Path(directory),
            ),
        ):
            scheduler = QtWorkflowScheduler()
            audio = QtRecordingAudioGateway(Recorder())
            service = WorkflowService(
                FakeProvider(),
                audio,
                Clipboard(),
                Config(),
                Statistics(),
                scheduler,
                FakeClock(),
            )
            bridge = QmlWorkflowBridge(
                service,
                dispatch_runner=scheduler.run_dispatch,
                target_provider=lambda: SelectionTarget(1),
            )
            try:
                self.assertTrue(bridge.handleHotkey("recording_hotkey"))
                self.wait(
                    lambda: bridge.recording and audio._active.start_finished.is_set()
                )
                old = audio._active
                # Deterministically hold the release barrier beyond the cancel
                # worker. Previously READY consumed the queued shortcut here,
                # while create_session returned None: no second state followed.
                held_worker = object()
                old.attach_worker(held_worker)
                self.assertTrue(bridge.handleHotkey("escape"))
                self.wait(lambda: bridge.cancellationVisible)
                self.wait(lambda: old._terminal and len(old._workers) == 1)
                self.assertTrue(bridge.handleHotkey("recording_hotkey"))
                self.assertTrue(bridge.transitionPending)
                self.assertTrue(scheduler.wait_for_dispatches(1))
                self.assertEqual(service.state.phase, WorkflowPhase.CANCELLED)
                old.detach_worker(held_worker)
                self.wait(lambda: bridge.recording and audio._active is not old)
                self.assertFalse(bridge.transitionPending)
                # An expired timer belonging to the old pill cannot kill capture.
                bridge.dismissFeedback(service.state.operation_id - 1)
                self.assertTrue(bridge.recording)
            finally:
                service.cancel_active()
                audio.wait_for_shutdown(2)
                scheduler.wait_for_dispatches(2)
                self.app.processEvents()

    def test_cancel_undo_reuses_audio_without_new_capture(self):
        with (
            TemporaryDirectory() as directory,
            patch(
                "spikes.pyside6.qml_runtime._data_directory",
                return_value=Path(directory),
            ),
        ):
            scheduler = QtWorkflowScheduler()
            audio = QtRecordingAudioGateway(Recorder())
            provider = FakeProvider()
            service = WorkflowService(
                provider,
                audio,
                Clipboard(),
                Config(),
                Statistics(),
                scheduler,
                FakeClock(),
            )
            bridge = QmlWorkflowBridge(
                service,
                dispatch_runner=scheduler.run_dispatch,
                target_provider=lambda: SelectionTarget(1),
            )
            try:
                bridge.handleHotkey("recording_hotkey")
                self.wait(
                    lambda: bridge.recording and audio._active.start_finished.is_set()
                )
                owner = audio._active
                bridge.handleHotkey("escape")
                self.wait(lambda: bridge.canUndoCancellation)
                self.assertTrue(bridge.undoCancellation())
                self.wait(lambda: service.state.phase == WorkflowPhase.COMPLETED)
                self.assertIs(audio._active, owner)
                self.assertEqual(
                    provider.transcription_request[0].audio_bytes, b"a" * 1600
                )
                self.assertFalse(
                    provider.transcription_request[0].cancel_token.cancelled
                )
            finally:
                service.cancel_active()
                audio.wait_for_shutdown(2)
                scheduler.wait_for_dispatches(2)
                self.app.processEvents()

    def test_hotkey_immediately_after_escape_is_not_a_stop_command(self):
        from test_pyside6_qml_runtime import DeterministicWorkflowService
        from workflows import CancelDictation, WorkflowState

        service = DeterministicWorkflowService()
        service.publish(WorkflowState(phase=WorkflowPhase.RECORDING, operation_id=1))
        queued = []
        bridge = QmlWorkflowBridge(service, dispatch_runner=queued.append)
        self.assertTrue(bridge.handleHotkey("escape"))
        self.assertTrue(bridge.handleHotkey("recording_hotkey"))
        self.assertEqual(len(queued), 1, "New hotkey must not dispatch StopDictation")
        queued.pop(0)()
        self.assertIsInstance(service.commands[0], CancelDictation)
        self.assertEqual(len(queued), 1, "New recording must run when READY arrives")
        queued.pop(0)()
        self.assertTrue(bridge.recording)


if __name__ == "__main__":
    unittest.main()
