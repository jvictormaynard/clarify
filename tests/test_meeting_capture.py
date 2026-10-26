import struct
import tempfile
import threading
import unittest
from array import array

from meeting_capture import MeetingCapture
from meeting_store import MeetingStore
from windows_meeting_audio import pcm16_mono


class MeetingCaptureTests(unittest.TestCase):
    def test_dual_source_failure_is_isolated_and_stop_finalizes_chunks(self):
        ready = threading.Event()

        class Source:
            def __init__(self, name):
                self.name = name

            def run(self, stop, packet, warning):
                if self.name == "system":
                    raise OSError("fixture disconnect")
                packet(b"\x01\0" * (16000 * 31), 16000)
                ready.set()
                stop.wait()

        with tempfile.TemporaryDirectory() as directory:
            store = MeetingStore(directory)
            mid = store.create("guest")["id"]
            capture = MeetingCapture(store, "guest", mid, source_factory=Source)
            capture.start()
            self.assertTrue(ready.wait(3))
            capture.stop()
            self.assertFalse(capture.alive)
            self.assertEqual(capture.snapshot()["system"]["state"], "failed")
            chunks = store.get("guest", mid)["chunks"]
            self.assertEqual([c["duration_ms"] for c in chunks], [30000, 1000])
            self.assertTrue(all(c["state"] == "pending" for c in chunks))
            self.assertTrue(
                all(store.audio_path(mid, c["id"]).exists() for c in chunks)
            )

    def test_float_stereo_and_pcm24_are_converted_to_bounded_mono(self):
        data = struct.pack("<ffff", 0.5, -0.5, float("nan"), 2.0)
        self.assertEqual(array("h", pcm16_mono(data, 2, 32, True)).tolist(), [0, 32767])
        self.assertEqual(
            array("h", pcm16_mono(b"\xff\xff\x7f", 1, 24)).tolist(), [32767]
        )
