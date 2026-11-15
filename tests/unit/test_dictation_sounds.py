"""Dictation cues must finish playback without reopening the output device."""

import threading
import unittest
from unittest.mock import Mock, patch

from clarify.desktop.dictation_sounds import DictationCuePlayer


class DictationSoundTests(unittest.TestCase):
    def setUp(self):
        self.output = Mock()
        self.backend = Mock(RawOutputStream=Mock(return_value=self.output))
        self.backend.default.device = (-1, 2)
        self.enterContext(patch.dict("sys.modules", sounddevice=self.backend))
        self.player = DictationCuePlayer()
        self.addCleanup(self.player.close)

    def test_cues_reuse_prepared_output_and_drain_before_return(self):
        events = []
        self.output.start.side_effect = lambda: events.append("start")
        self.output.write.side_effect = lambda data: events.append(("write", len(data)))
        self.output.stop.side_effect = lambda: events.append("drained")
        self.player.prepare()
        self.player(True)
        self.player(False)
        self.assertEqual(self.backend.RawOutputStream.call_count, 1)
        self.assertEqual(
            events,
            [
                "start",
                ("write", 17468),
                "drained",
                "start",
                ("write", 17444),
                "drained",
            ],
        )
        self.output.close.assert_not_called()
        self.player.close()
        self.player.prepare()
        self.player(True)
        self.output.close.assert_called_once()
        self.assertEqual(self.backend.RawOutputStream.call_count, 1)

    def test_failed_playback_and_device_change_reopen_output(self):
        self.output.write.side_effect = OSError("Disconnected")
        with self.assertRaises(OSError):
            self.player(True)
        self.output.close.assert_called_once()
        self.output.write.side_effect = None
        self.player(False)
        self.backend.default.device = (-1, 3)
        self.player(True)
        self.assertEqual(self.backend.RawOutputStream.call_count, 3)
        self.assertEqual(self.backend.RawOutputStream.call_args.kwargs["device"], 3)

    def test_close_during_preparation_releases_late_output(self):
        entered, release = threading.Event(), threading.Event()

        def open_stream(**kwargs):
            entered.set()
            if not release.wait(2):
                raise TimeoutError("Test did not release output open")
            return self.output

        self.backend.RawOutputStream.side_effect = open_stream
        worker = threading.Thread(target=self.player.prepare)
        closer = threading.Thread(target=self.player.close)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            closer.start()
        finally:
            release.set()
            worker.join(2)
            if closer.ident is not None:
                closer.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.output.close.assert_called_once()
        self.player(False)
        self.output.start.assert_not_called()
