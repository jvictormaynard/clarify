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
