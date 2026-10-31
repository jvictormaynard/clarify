"""Latency regressions: leases, cancellation, memory pressure, and delivery order."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tests.support.local_asr as fixtures


class TranscriptionPerformanceTests(unittest.TestCase):
    def manager(self, directory, **kwargs):
        return fixtures.LocalASRSidecarFixture._manager(self, directory, **kwargs)

    def test_cloud_preparation_does_not_touch_adapter_or_network(self):
        from clarify.desktop import qml_runtime

        gateway = qml_runtime.QtProviderGateway(Mock(), Mock())
        gateway._route = Mock(return_value=SimpleNamespace(provider_id="groq"))
        with patch.object(qml_runtime, "PROVIDER_REGISTRY") as registry:
            gateway.prepare_dictation(Mock())
            registry.adapter.assert_not_called()
            registry.transcribe.assert_not_called()

    def test_recording_reads_only_after_recorder_finalization_without_sleep(self):
        from clarify.desktop import qml_runtime

        with tempfile.TemporaryDirectory() as directory:
            recorder = Mock()
            recorder.start.side_effect = lambda path, token: None
            with patch.object(
                qml_runtime, "_data_directory", return_value=Path(directory)
            ):
                session = qml_runtime.QtRecordingSession(recorder)
                recorder.stop.side_effect = lambda: session.audio_path.write_bytes(
                    b"RIFF" + b"0" * 1200
                )
                session.start()
                with patch.object(
                    qml_runtime.time, "sleep", side_effect=AssertionError("fixed sleep")
                ):
                    snapshot = session.stop()
                self.assertEqual(len(snapshot.audio_bytes), 1204)
                self.assertTrue(session.preparation_done.is_set())
                session.complete()
