"""Qt recording lifecycle preserves once-only archive ownership."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from clarify.desktop.qml_runtime import QtRecordingSession
from tests.support.audio_history import wav_bytes


class RecordingArchiveTests(unittest.TestCase):
    def session(self, root, enabled):
        class Recorder:
            def start(self, path, _event):
                path.write_bytes(wav_bytes())

            def stop(self):
                pass

            def cancel(self):
                pass

        config = SimpleNamespace(
            current=lambda: SimpleNamespace(experimental_audio_history=enabled)
        )
        with patch("clarify.desktop.qml_runtime._data_directory", return_value=root):
            session = QtRecordingSession(Recorder(), config)
        session.start()
        return session

    def test_enabled_normal_stop_archives_once_and_original_is_cleaned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = self.session(root, True)
            session.stop()
            session.stop()
            session.complete()
            copies = list((root / "experimental-audio").glob("*.wav"))
            self.assertEqual(len(copies), 1)
            self.assertEqual(copies[0].read_bytes(), wav_bytes())
            self.assertFalse(session.audio_path.exists())

    def test_disabled_stop_does_not_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = self.session(root, False)
            session.stop()
            session.complete()
            self.assertFalse((root / "experimental-audio").exists())

    def test_cancel_snapshot_does_not_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = self.session(root, True)
            session.stop_for_cancel()
            session.cancel()
            self.assertFalse((root / "experimental-audio").exists())

    def test_failed_processing_keeps_full_recording_after_session_release(self):
        from recording_recovery import RecordingRecovery

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = self.session(root, False)
            audio = wav_bytes(frames=16000 * 181)
            session.audio_path.write_bytes(audio)
            session.stop()
            session.stop()
            session.fail(RuntimeError("provider failed"))
            self.assertFalse(session.audio_path.exists())
            # A new store represents restarting the app. No provider or account
            # connection is required to find the exact original recording.
            store = RecordingRecovery(root)
            rows = store.entries()
            self.assertEqual(len(rows), 1)
            self.assertEqual(store.path(rows[0]["id"]).read_bytes(), audio)
            store.delete(rows[0]["id"])
            self.assertEqual(store.entries(), [])

    def test_disk_failure_preserves_working_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self.session(Path(temporary), False)
            with patch(
                "recording_recovery.RecordingRecovery.save", side_effect=OSError("full")
            ):
                self.assertEqual(session.stop().audio_bytes, wav_bytes())
                session.fail(OSError("full"))
            self.assertEqual(session.audio_path.read_bytes(), wav_bytes())
            from recording_recovery import RecordingRecovery

            store = RecordingRecovery(Path(temporary))
            self.assertEqual(
                store.path(store.entries()[0]["id"]).read_bytes(), wav_bytes()
            )

    def test_undo_persists_audio_after_cancel_cleanup(self):
        from recording_recovery import RecordingRecovery

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = self.session(root, False)
            snapshot = session.stop_for_cancel()
            session.complete()
            self.assertEqual(RecordingRecovery(root).entries(), [])
            with patch(
                "recording_recovery.RecordingRecovery.save", side_effect=OSError("full")
            ):
                session.persist_audio(snapshot)
                self.assertEqual(RecordingRecovery(root).entries(), [])
            session.fail(RuntimeError("provider failed"))
            store = RecordingRecovery(root)
            self.assertEqual(
                store.path(store.entries()[0]["id"]).read_bytes(), wav_bytes()
            )

    def test_redirected_recovery_directory_releases_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "elsewhere").mkdir()
            try:
                (root / "recording-recovery").symlink_to(
                    root / "elsewhere", target_is_directory=True
                )
            except OSError:
                self.skipTest("Directory symlinks unavailable")
            session = self.session(root, False)
            self.assertEqual(session.stop().audio_bytes, wav_bytes())
            session.fail(ValueError("unavailable"))
            self.assertTrue(session.shutdown_complete.is_set())
            self.assertTrue(session.audio_path.exists())
            from recording_recovery import RecordingRecovery

            store = RecordingRecovery(root)
            self.assertEqual(
                store.path(store.entries()[0]["id"]).read_bytes(), wav_bytes()
            )

    def test_reprocess_reuses_saved_audio_without_recording_or_deleting_original(self):
        from clarify.desktop.qml_runtime import QtRecordingAudioGateway
        from recording_recovery import RecordingRecovery
        from tests.support.workflows import WorkflowFixture
        from workflows import WorkflowPhase
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RecordingRecovery(root)
            # SoX on Windows can leave its open-stream sizes after termination.
            # Duration must use the captured PCM, not those declared sizes.
            audio = bytearray(wav_bytes(frames=16000 * 181))
            audio[4:8] = (0x7FFFF024).to_bytes(4, "little")
            audio[40:44] = (0x7FFFF000).to_bytes(4, "little")
            audio = bytes(audio)
            token = store.save(audio)
            recorder = Mock(sox=None, config=None)
            gateway = QtRecordingAudioGateway(recorder)
            with patch(
                "clarify.desktop.qml_runtime._data_directory", return_value=root
            ):
                recording = gateway.create_recovery_session(store.path(token))
            self.assertIsNotNone(recording)
            fixture = WorkflowFixture()
            fixture.setUp()
            from repositories import AppConfig
            from clarify.desktop.qml_runtime import QtHistoryRecorder

            history = QtHistoryRecorder(
                SimpleNamespace(
                    config=SimpleNamespace(
                        path=root / "config.json",
                        load=lambda: AppConfig(history_enabled=True),
                    )
                ),
                fixture.scheduler,
            )
            fixture.service.subscribe(history.on_state)
            self.assertTrue(fixture.service.recover_dictation(recording, "auto"))
            self.assertEqual(
                store.metadata(token)["history_id"], history.store.list_records()[0].id
            )
            self.assertEqual(fixture.service.state.phase, WorkflowPhase.COMPLETED)
            self.assertEqual(
                fixture.provider.transcription_request[0].audio_bytes, audio
            )
            self.assertEqual(fixture.statistics.dictations[0][1], 181)
            self.assertEqual(store.path(token).read_bytes(), audio)
            import base64
            import io
            import wave

            exported = bytearray()
            while len(exported) < len(audio):
                chunk = store.audio_chunk(token, len(exported))
                exported.extend(base64.b64decode(chunk["data"]))
            with wave.open(io.BytesIO(exported), "rb") as stream:
                self.assertEqual(stream.getnframes(), 16000 * 181)
                self.assertEqual(stream.readframes(stream.getnframes()), audio[44:])
            self.assertEqual(store.path(token).read_bytes(), audio)
            self.assertEqual(len(store.entries()), 1)
            recorder.start.assert_not_called()
            self.assertFalse(gateway.busy)

    def test_cancellation_releases_processing_even_when_metadata_write_failed(self):
        from clarify.desktop.qml_runtime import QtRecordingAudioGateway
        from recording_recovery import RecordingRecovery
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RecordingRecovery(root)
            token = store.save(wav_bytes())
            store.update(token, status="complete")
            gateway = QtRecordingAudioGateway(Mock(config=None))
            with patch(
                "clarify.desktop.qml_runtime._data_directory", return_value=root
            ):
                session = gateway.create_recovery_session(store.path(token))
            with patch("recording_recovery.os.replace", side_effect=OSError("full")):
                session.begin_processing()
            self.assertEqual(store.entries()[0]["status"], "processing")
            session.cancel()
            self.assertEqual(store.entries()[0]["status"], "complete")
            store.delete(token)
            self.assertEqual(store.entries(), [])
