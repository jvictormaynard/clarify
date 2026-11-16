"""Safety contracts that do not load native binaries or personal profiles."""

import hashlib
import io
import tarfile
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace

from local_asr_live import (
    CaptureStream,
    LiveResult,
    LiveSession,
    MAX_CHUNK,
    MAX_PENDING,
)
from local_asr import LocalASRCancelledError, LocalASRSidecarError
from local_asr_streaming import wav_bytes
from workflows import CancellationToken


class LiveSafetyTests(unittest.TestCase):
    def test_native_archive_rejects_links_and_verifies_regular_members(self):
        from local_asr_live_assets import NativeInstaller
        from local_asr import LocalASRIntegrityError

        installer = NativeInstaller.__new__(NativeInstaller)
        payload = b"verified runtime"
        installer.manifest = {
            "extracted_files": [
                {
                    "archive_path": "package/runtime.dll",
                    "path": "runtime/runtime.dll",
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for is_link in (False, True):
                archive = root / "runtime.tar.gz"
                with tarfile.open(archive, "w:gz") as output:
                    entry = tarfile.TarInfo("package/runtime.dll")
                    entry.size = len(payload)
                    if is_link:
                        entry.type = tarfile.SYMTYPE
                        entry.linkname = "/outside"
                    output.addfile(entry, io.BytesIO(payload))
                if is_link:
                    with self.assertRaises(LocalASRIntegrityError):
                        installer._extract_runtime(archive, root / "stage")
                else:
                    installer._extract_runtime(archive, root / "stage")
                    self.assertEqual(
                        (root / "stage/runtime/runtime.dll").read_bytes(), payload
                    )

    def test_capture_queue_never_drops_audio_to_make_room(self):
        live = LiveSession(None, "en", None)  # consumer deliberately stalled
        for _ in range(MAX_PENDING):
            live.feed(b"\0" * MAX_CHUNK)
        with self.assertRaises(LocalASRSidecarError):
            live.feed(b"\0" * MAX_CHUNK)
        self.assertEqual(live.queue.qsize(), MAX_PENDING)
        self.assertTrue(live.abort.is_set())

    def test_cancel_rejects_stale_partial_and_final_publication(self):
        results = []
        live = LiveSession(None, "en", results.append)
        live.cancel()
        for final in (False, True):
            with self.assertRaises(LocalASRCancelledError):
                live._publish(LiveResult("stale", "", final, 1))
        self.assertEqual(results, [])
        with self.assertRaises(LocalASRCancelledError):
            live.finish()

    def test_finish_is_repeatable_and_closes_input(self):
        live = LiveSession(None, "en", None)
        expected = LiveResult("raw transcript", "raw transcript", True, 1)
        live.result = expected
        live.done.set()
        self.assertIs(live.finish(), expected)
        self.assertIs(live.finish(), expected)
        with self.assertRaises(LocalASRSidecarError):
            live.feed(b"\0\0")
        self.assertEqual(live.queue.qsize(), 1)

    def test_capture_backlog_fails_before_feeding_future_or_skipping_samples(self):
        class FakeSession:
            def __init__(self):
                self.worker = threading.Thread(target=lambda: None)
                self.worker.start()
                self.chunks = []

            def feed(self, chunk):
                self.chunks.append(chunk)

            def cancel(self):
                pass

        live = FakeSession()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.wav"
            path.write_bytes(wav_bytes(b"\0" * (MAX_CHUNK * (MAX_PENDING + 1))))
            backend = SimpleNamespace(open_live_session=lambda *args: live)
            stream = CaptureStream(path, backend, "test", "en", CancellationToken())
            stream.start()
            stream.worker.join(2)
            self.assertFalse(stream.worker.is_alive())
            self.assertIsInstance(stream.error, LocalASRSidecarError)
            self.assertEqual(live.chunks, [])

    def test_changed_final_audio_cannot_reuse_stream_transcript(self):
        stream = CaptureStream("unused", None, "test", "en", CancellationToken())
        stream._count = 2
        stream._digest = hashlib.sha256(b"\0\0")
        stream.result = LiveResult("stale", "", True, 0)
        with self.assertRaises(LocalASRSidecarError):
            stream.finish(wav_bytes(b"\1\0"))
