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


class AudioArchiveTests(unittest.TestCase):
    def test_config_requires_explicit_true_and_round_trips(self):
        self.assertFalse(AppConfig().experimental_audio_history)
        for value in (None, False, "true", 1):
            self.assertFalse(
                AppConfig.from_mapping(
                    {"experimental_audio_history": value}
                ).experimental_audio_history
            )
        configured = AppConfig.from_mapping({"experimental_audio_history": True})
        self.assertTrue(configured.experimental_audio_history)
        self.assertIs(configured.to_mapping()["experimental_audio_history"], True)

    def test_archive_preserves_exact_wav_and_has_no_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = wav_bytes()
            target = archive.archive_audio(root, audio)
            self.assertIsNotNone(target)
            self.assertEqual(target.read_bytes(), audio)
            self.assertEqual(list(target.parent.iterdir()), [target])
            self.assertEqual(target.parent.name, "experimental-audio")

    def test_invalid_and_truncated_wav_do_not_create_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for data in (b"", b"not audio", wav_bytes()[:-1]):
                self.assertIsNone(archive.archive_audio(root, data))
            self.assertFalse((root / "experimental-audio").exists())

    def test_stopped_sox_placeholder_header_preserves_all_actual_pcm(self):
        # Native pinned SoX leaves these sizes when TerminateProcess ends capture.
        # This is generated PCM, never a microphone or personal recording.
        audio = bytearray(wav_bytes(16000 * 5))
        audio[4:8] = (0x7FFFF024).to_bytes(4, "little")
        audio[40:44] = (0x7FFFF000).to_bytes(4, "little")
        with tempfile.TemporaryDirectory() as temporary:
            target = archive.archive_audio(Path(temporary), bytes(audio))
            self.assertIsNotNone(target)
            self.assertEqual(target.read_bytes(), bytes(audio))

    def test_placeholder_does_not_accept_unaligned_or_other_truncation(self):
        audio = bytearray(wav_bytes())
        audio[4:8] = (0x7FFFF024).to_bytes(4, "little")
        audio[40:44] = (0x7FFFF000).to_bytes(4, "little")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertIsNone(archive.archive_audio(root, bytes(audio[:-1])))
            audio[4:8] = (0x7FFFF028).to_bytes(4, "little")
            self.assertIsNone(archive.archive_audio(root, bytes(audio)))

    def test_size_rejection_leaves_existing_audio_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = archive.archive_audio(root, wav_bytes())
            with patch.object(archive, "MAX_CLIP_BYTES", 10):
                self.assertIsNone(archive.archive_audio(root, wav_bytes()))
            self.assertTrue(first.exists())

    def test_prune_expiry_preserves_foreign_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = archive.archive_audio(root, wav_bytes())
            recent = archive.archive_audio(root, wav_bytes())
            foreign = old.parent / "my-recording.wav"
            foreign.write_bytes(b"keep")
            expired = time.time() - archive.RETENTION_SECONDS - 1
            os.utime(old, (expired, expired))
            os.utime(foreign, (expired, expired))
            archive.prune_audio_history(root)
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertEqual(foreign.read_bytes(), b"keep")

    def test_space_cap_evicts_oldest_before_new_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = wav_bytes()
            first = archive.archive_audio(root, data)
            os.utime(first, (time.time() - 10, time.time() - 10))
            with patch.object(archive, "MAX_TOTAL_BYTES", len(data)):
                second = archive.archive_audio(root, data)
            self.assertFalse(first.exists())
            self.assertEqual(second.read_bytes(), data)

    def test_prune_expired_interrupted_write_preserves_foreign_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "experimental-audio"
            directory.mkdir()
            orphan = directory / ".benchmark-a1b2c3_d"
            foreign = directory / ".benchmark-my-recording.wav"
            for path in (orphan, foreign):
                path.write_bytes(wav_bytes())
                expired = time.time() - archive.RETENTION_SECONDS - 1
                os.utime(path, (expired, expired))
            archive.prune_audio_history(root)
            self.assertFalse(orphan.exists())
            self.assertEqual(foreign.read_bytes(), wav_bytes())

    def test_interrupted_write_counts_toward_space_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "experimental-audio"
            directory.mkdir()
            descriptor, raw_path = tempfile.mkstemp(prefix=".benchmark-", dir=directory)
            os.close(descriptor)
            orphan = Path(raw_path)
            audio = wav_bytes()
            orphan.write_bytes(audio)
            os.utime(orphan, (time.time() - 10, time.time() - 10))
            with patch.object(archive, "MAX_TOTAL_BYTES", len(audio)):
                saved = archive.archive_audio(root, audio)
            self.assertFalse(orphan.exists())
            self.assertEqual(saved.read_bytes(), audio)

    def test_file_symlink_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "experimental-audio"
            directory.mkdir()
            foreign = root / "foreign.wav"
            foreign.write_bytes(wav_bytes())
            link = directory / ("clarify-benchmark-" + "a" * 32 + ".wav")
            try:
                link.symlink_to(foreign)
            except OSError:
                self.skipTest("symlink privilege unavailable")
            with patch.object(archive, "MAX_TOTAL_BYTES", 0):
                archive.prune_audio_history(root)
            self.assertTrue(link.is_symlink())
            self.assertTrue(foreign.exists())

    def test_directory_symlink_refuses_writes_and_pruning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            foreign = root / "foreign"
            foreign.mkdir()
            link = root / "experimental-audio"
            try:
                link.symlink_to(foreign, target_is_directory=True)
            except OSError:
                self.skipTest("symlink privilege unavailable")
            self.assertIsNone(archive.archive_audio(root, wav_bytes()))
            archive.prune_audio_history(root)
            self.assertEqual(list(foreign.iterdir()), [])

    def test_windows_directory_junction_refuses_writes_and_pruning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(Path, "is_junction", return_value=True, create=True):
                self.assertIsNone(archive.archive_audio(root, wav_bytes()))
                archive.prune_audio_history(root)
            self.assertFalse((root / "experimental-audio").exists())

    def test_write_failure_is_nonfatal_and_temporary_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(archive.os, "replace", side_effect=OSError("disk full")):
                self.assertIsNone(archive.archive_audio(root, wav_bytes()))
            self.assertEqual(list((root / "experimental-audio").iterdir()), [])


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
