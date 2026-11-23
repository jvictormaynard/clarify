"""Controlled admission and feedback for Windows speaker windows."""

import unittest

from clarify.desktop.meeting_speaker_pace import SpeakerPace


class SpeakerPaceTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.pace = SpeakerPace(clock=lambda: self.now)

    def test_admission_replaces_unclaimed_audio_and_drops_on_pressure(self):
        self.assertFalse(self.pace.offer(5.99, self.fail))
        self.assertTrue(self.pace.offer(6, lambda: "old"))
        self.now += 0.1
        self.assertTrue(self.pace.offer(6.1, lambda: "latest"))
        job = self.pace.take(timeout=0)
        self.assertEqual((job.window, job.admitted), ("latest", 0))
        self.assertTrue(self.pace.accepts(job))

        self.assertFalse(self.pace.offer(12.2, self.fail))
        self.assertFalse(self.pace.accepts(job))
        self.pace.complete(job)
        self.assertIsNone(self.pace.take(timeout=0))
        self.assertFalse(self.pace.offer(18.1, self.fail))
        self.assertTrue(self.pace.offer(18.3, lambda: "after backlog"))
        self.assertFalse(self.pace.offer(18.4, self.fail, pressured=True))
        self.assertIsNone(self.pace.take(timeout=0))
        self.assertFalse(self.pace.offer(24.3, self.fail))
        self.assertTrue(self.pace.offer(24.5, lambda: "after capture pressure"))
        self.now += 0.5
        self.assertIsNone(self.pace.take(timeout=0))

    def test_promotion_requires_sustained_wall_budget_and_backs_off(self):
        audio_end = 0.0
        for stride in (6, 4, 2.5, 1.5):
            for _ in range(3):
                self.assertEqual(self.pace.stride, stride)
                audio_end += stride + 0.01
                self.assertTrue(self.pace.offer(audio_end, lambda: audio_end))
                job = self.pace.take(timeout=0)
                self.now += 0.2
                self.pace.complete(job)
        self.assertEqual(self.pace.stride, 0.8)

        audio_end += 0.81
        self.assertTrue(self.pace.offer(audio_end, lambda: audio_end))
        self.now += 0.3  # Waiting for the worker uses the same budget as inference.
        job = self.pace.take(timeout=0)
        self.now += 0.33
        self.pace.complete(job)
        self.assertEqual(self.pace.stride, 1.5)

        self.assertTrue(self.pace.offer(audio_end + 1.51, lambda: "timeout"))
        job = self.pace.take(timeout=0)
        self.pace.complete(job, timed_out=True)
        self.assertEqual(self.pace.stride, 6)

    def test_close_drops_waiting_work_and_rejects_late_admission(self):
        self.assertTrue(self.pace.offer(6, lambda: "waiting"))
        self.pace.close()
        self.assertFalse(self.pace.offer(100, self.fail))
        self.assertIsNone(self.pace.take(timeout=0))
