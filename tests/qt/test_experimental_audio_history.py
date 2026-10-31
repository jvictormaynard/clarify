"""Device-only benchmark retention must not alter normal recording ownership."""

import io
import os
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import experimental_audio_history as archive
from repositories import AppConfig


def wav_bytes(frames=1600):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\x10\x00" * frames)
    return output.getvalue()


try:
    from clarify.desktop.qml_runtime import QtRecordingSession
except ImportError:
    QtRecordingSession = None


@unittest.skipIf(QtRecordingSession is None, "Qt runtime dependencies unavailable")
class RecordingArchiveTests(unittest.TestCase):
    def test_startup_prunes_existing_audio_even_with_default_disabled(self):
        from clarify.desktop.qml_runtime import create_real_workflow_runtime

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = archive.archive_audio(root, wav_bytes())
            expired = time.time() - archive.RETENTION_SECONDS - 1
            os.utime(old, (expired, expired))
            self.assertFalse(AppConfig().experimental_audio_history)
            active = SimpleNamespace(config=SimpleNamespace(path=root / "config.json"))
            with patch(
                "clarify.desktop.qml_runtime.AccountService",
                side_effect=RuntimeError("stop after prune"),
            ):
                with self.assertRaisesRegex(RuntimeError, "stop after prune"):
                    create_real_workflow_runtime(None, repositories=active)
            self.assertFalse(old.exists())

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

    def test_archive_failure_does_not_break_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = self.session(root, True)
            with patch(
                "clarify.desktop.qml_runtime.archive_audio", side_effect=OSError("disk")
            ):
                snapshot = session.stop()
            self.assertEqual(snapshot.audio_bytes, wav_bytes())
            session.complete()
