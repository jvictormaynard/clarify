"""Latency regressions: leases, cancellation, memory pressure, and delivery order."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import local_asr
from provider_http import CancellationToken
from transcription_performance import model_idle_seconds, safe_timings
import test_local_asr as fixtures
import test_workflows as workflow_fixtures
from workflows import StartDictation, StopDictation, WorkflowService


class TranscriptionPerformanceTests(unittest.TestCase):
    def manager(self, directory, **kwargs):
        return fixtures.LocalASRSidecarTests._manager(self, directory, **kwargs)

    def test_memory_policy_keeps_constrained_and_unknown_hosts_bounded(self):
        gib = 1024 ** 3
        for memory, expected in [(None, 60), ((4*gib, 3*gib), 60),
                                 ((32*gib, gib), 60), ((8*gib, 3*gib), 300),
                                 ((16*gib, 8*gib), 600)]:
            self.assertEqual(model_idle_seconds(memory), expected)

    def test_metrics_reject_content_unknown_fields_and_nonfinite_numbers(self):
        self.assertEqual(safe_timings({"text": "private", "provider_ms": 12.34567,
                                     "delivery_ms": float("inf"), "asr_ms": True,
                                     "inference_ms": -1}), {"provider_ms": 12.346})

    def test_prepare_holds_model_until_recording_stops_then_unloads(self):
        with tempfile.TemporaryDirectory() as directory:
            manager, _, session, factory = self.manager(directory, idle_seconds=0.03)
            done = threading.Event()
            ready = threading.Event()
            original_start = manager.start
            def start(**kwargs):
                result = original_start(**kwargs)
                ready.set()
                return result
            manager.start = start
            errors = []
            def prepare():
                try:
                    manager.prepare(done, CancellationToken())
                except Exception as error:
                    errors.append(error)
            with patch.object(local_asr, "memory_bytes", return_value=None):
                thread = threading.Thread(target=prepare)
                thread.start()
                try:
                    self.assertTrue(ready.wait(2))
                    time.sleep(0.08)
                    self.assertIsNotNone(manager.process_id)
                    self.assertEqual(len(factory.calls), 1)
                    self.assertEqual(session.post_calls, [])
                finally:
                    done.set()
                    thread.join(2)
                    deadline = time.monotonic() + 1
                    while manager.process_id is not None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    manager.shutdown()
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertIsNone(manager.process_id)
            self.assertEqual(manager._active_cancellations, set())

    def test_prepare_skips_low_memory_and_already_finished_recordings(self):
        with tempfile.TemporaryDirectory() as directory:
            manager, _, _, factory = self.manager(directory)
            with patch.object(local_asr, "memory_bytes", return_value=(4*1024**3, 512*1024**2)):
                manager.prepare(threading.Event())
            done = threading.Event()
            done.set()
            manager.prepare(done)
            self.assertEqual(factory.calls, [])
            manager.shutdown()

    def test_cancelled_preparation_never_launches_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            manager, _, _, factory = self.manager(directory)
            token = CancellationToken()
            token.cancel()
            manager.prepare(threading.Event(), token)
            self.assertEqual(factory.calls, [])
            self.assertEqual(manager._active_cancellations, set())
            manager.shutdown()

    def test_local_request_reports_start_and_inference_without_audio_content(self):
        with tempfile.TemporaryDirectory() as directory:
            manager, _, _, _ = self.manager(directory)
            timings = {}
            try:
                manager.transcribe(Path("test.wav"), "pt", audio_bytes=b"RIFFaudio", timings=timings)
                self.assertEqual(set(timings), {"model_start_ms", "inference_ms"})
                self.assertTrue(all(value >= 0 for value in timings.values()))
            finally:
                manager.shutdown()

    def test_delivery_precedes_disk_statistics_and_timings_exclude_persistence(self):
        clock = workflow_fixtures.FakeClock()
        provider = workflow_fixtures.FakeProvider()
        audio = workflow_fixtures.FakeAudio()
        clipboard = workflow_fixtures.FakeClipboard()
        stats = workflow_fixtures.FakeStatistics()
        events = []
        def transcribe():
            clock.now += 0.4
        provider.on_transcribe = transcribe
        def deliver(*args):
            events.append("delivery")
            clock.now += 0.1
        clipboard.write_dictation_result = deliver
        record = stats.record_dictation
        def persist(*args):
            events.append("statistics")
            clock.now += 10
            record(*args)
        stats.record_dictation = persist
        service = WorkflowService(provider, audio, clipboard, workflow_fixtures.FakeConfig(),
                                  stats, workflow_fixtures.ImmediateScheduler(), clock)
        service.dispatch(StartDictation(None, "transcription", "pt"))
        service.dispatch(StopDictation())
        self.assertEqual(events, ["delivery", "statistics"])
        timing = stats.dictations[0][0]["latency_ms"]
        self.assertAlmostEqual(timing["provider_ms"], 400)
        self.assertAlmostEqual(timing["delivery_ms"], 100)
        self.assertAlmostEqual(timing["stop_to_delivery_ms"], 500)

    def test_cloud_preparation_does_not_touch_adapter_or_network(self):
        from spikes.pyside6 import qml_runtime
        gateway = qml_runtime.QtProviderGateway(Mock(), Mock())
        gateway._route = Mock(return_value=SimpleNamespace(provider_id="groq"))
        with patch.object(qml_runtime, "PROVIDER_REGISTRY") as registry:
            gateway.prepare_dictation(Mock())
            registry.adapter.assert_not_called()
            registry.transcribe.assert_not_called()

    def test_recording_reads_only_after_recorder_finalization_without_sleep(self):
        from spikes.pyside6 import qml_runtime
        with tempfile.TemporaryDirectory() as directory:
            recorder = Mock()
            recorder.start.side_effect = lambda path, token: None
            with patch.object(qml_runtime, "_data_directory", return_value=Path(directory)):
                session = qml_runtime.QtRecordingSession(recorder)
                recorder.stop.side_effect = lambda: session.audio_path.write_bytes(b"RIFF" + b"0"*1200)
                session.start()
                with patch.object(qml_runtime.time, "sleep", side_effect=AssertionError("fixed sleep")):
                    snapshot = session.stop()
                self.assertEqual(len(snapshot.audio_bytes), 1204)
                self.assertTrue(session.preparation_done.is_set())
                session.complete()


    def test_idle_watch_rechecks_memory_pressure(self):
        gib = 1024 ** 3
        with tempfile.TemporaryDirectory() as directory:
            manager, _, _, _ = self.manager(directory, idle_seconds=None)
            manager.start()
            with manager._lock:
                manager._cancel_idle_shutdown_locked()
            now = [0.0]
            memory = [(32*gib, 16*gib)]
            timers = []
            def timer(delay, callback):
                result = SimpleNamespace(start=lambda: None, cancel=lambda: None,
                                         callback=callback, delay=delay)
                timers.append(result)
                return result
            with patch.object(local_asr.threading, "Timer", side_effect=timer), \
                 patch.object(local_asr.time, "monotonic", side_effect=lambda: now[0]), \
                 patch.object(local_asr, "memory_bytes", side_effect=lambda: memory[0]):
                with manager._lock:
                    manager._schedule_idle_shutdown_locked()
                self.assertEqual(timers[-1].delay, 15)
                now[0] = 15
                timers[-1].callback()
                self.assertIsNotNone(manager.process_id)
                now[0] = 75
                memory[0] = (32*gib, gib)
                timers[-1].callback()
                self.assertIsNone(manager.process_id)
            manager.shutdown()
