"""Contract tests between the workflow service and the real recording owner."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app
from workflows import (
    RecordingSnapshot,
    SelectionTarget,
    StartDictation,
    StopDictation,
    WorkflowPhase,
    WorkflowService,
)


from tests.support.recording import (
    ImmediateScheduler,
    ThreadScheduler,
    Provider,
    Clipboard,
    Config,
    Statistics,
    Clock,
    Recorder,
)


class WorkflowRecordingIntegrationTests(unittest.TestCase):
    def make_service(self, gateway, provider, clipboard, scheduler, clock):
        return WorkflowService(
            provider,
            gateway,
            clipboard,
            Config(),
            Statistics(),
            scheduler,
            clock,
        )

    def test_real_session_snapshots_audio_before_terminal_cleanup(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(app.time, "sleep", return_value=None),
        ):
            path = Path(directory) / "recording.wav"
            recorder = Recorder()
            sessions = []

            def create_session():
                session = app.RecordingSession(recorder, audio_path=path)
                sessions.append(session)
                return session

            gateway = app.RecordingAudioGateway(create_session, lambda: True)
            provider = Provider()
            clipboard = Clipboard()
            clock = Clock()
            service = self.make_service(
                gateway, provider, clipboard, ImmediateScheduler(), clock
            )
            target = SelectionTarget(77, "editor.exe")

            self.assertTrue(service.dispatch(StartDictation(target, "prompt", "en")))
            clock.now = 12.5
            self.assertTrue(service.dispatch(StopDictation()))

            session = sessions[0]
            self.assertIsInstance(provider.audio_source, RecordingSnapshot)
            self.assertEqual(provider.audio_source.audio_bytes, b"a" * 1200)
            self.assertIsNotNone(provider.audio_source.duration_seconds)
            self.assertGreaterEqual(provider.audio_source.duration_seconds, 0.0)
            self.assertTrue(provider.path_existed_during_call)
            self.assertFalse(path.exists())
            self.assertTrue(session.audio_snapshot_complete.is_set())
            self.assertTrue(session.shutdown_complete.is_set())
            self.assertEqual(
                session.state_history,
                ["created", "recording", "processing", "completed"],
            )
            self.assertEqual(
                recorder.order, ["start_entered", "start_terminal", "stop"]
            )
            self.assertEqual(clipboard.outputs, [(target, "Transcribed")])
            self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)

    def test_real_session_defers_immediate_stop_until_startup_finishes(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(app.time, "sleep", return_value=None),
        ):
            path = Path(directory) / "recording.wav"
            recorder = Recorder(block_start=True)
            sessions = []

            def create_session():
                session = app.RecordingSession(recorder, audio_path=path)
                sessions.append(session)
                return session

            gateway = app.RecordingAudioGateway(create_session, lambda: True)
            scheduler = ThreadScheduler()
            service = self.make_service(
                gateway, Provider(), Clipboard(), scheduler, Clock()
            )

            service.dispatch(
                StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
            )
            self.assertTrue(recorder.start_entered.wait(timeout=1))
            self.assertTrue(service.dispatch(StopDictation()))
            self.assertNotIn("stop", recorder.order)

            recorder.start_release.set()
            scheduler.join()

            self.assertLess(
                recorder.order.index("start_terminal"), recorder.order.index("stop")
            )
            self.assertEqual(recorder.order.count("start_entered"), 1)
            self.assertEqual(recorder.order.count("stop"), 1)
            self.assertEqual(sessions[0].state, "completed")
            self.assertFalse(path.exists())
            self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)

    def test_cancel_keeps_recording_owner_until_attached_workers_detach(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(app.time, "sleep", return_value=None),
        ):
            path = Path(directory) / "recording.wav"
            recorder = Recorder(block_start=True)
            cancel_entered = threading.Event()
            cancel_release = threading.Event()

            def blocked_cancel():
                cancel_entered.set()
                cancel_release.wait(timeout=1)
                recorder.start_release.set()

            recorder.cancel = blocked_cancel
            session = app.RecordingSession(recorder, audio_path=path)
            gateway = app.RecordingAudioGateway(lambda: session, lambda: True)
            tk_loop = SimpleNamespace(after=lambda _delay, callback: callback())
            scheduler = app.AppWorkflowScheduler(tk_loop)
            service = self.make_service(
                gateway, Provider(), Clipboard(), scheduler, Clock()
            )

            service.dispatch(
                StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
            )
            self.assertTrue(recorder.start_entered.wait(timeout=1))
            self.assertTrue(session._active_workers())

            service.cancel_active()
            self.assertTrue(cancel_entered.wait(timeout=1))

            # READY is published before cancellation workers finish, but the
            # owner must remain live and reject a replacement in this window.
            self.assertFalse(session.shutdown_complete.is_set())
            owner = SimpleNamespace(
                _recording_session=session,
                _new_recording_session=lambda: SimpleNamespace(
                    shutdown_complete=threading.Event()
                ),
            )
            self.assertIsNone(app.App._new_workflow_recording_session(owner))

            cancel_release.set()
            self.assertTrue(session.shutdown_complete.wait(timeout=2))
            replacement = app.App._new_workflow_recording_session(owner)

        self.assertIsNot(replacement, session)
        self.assertEqual(recorder.order[0], "start_entered")


if __name__ == "__main__":
    unittest.main()
