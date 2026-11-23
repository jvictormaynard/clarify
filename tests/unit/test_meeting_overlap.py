"""Protect the optional two-voice path without models or hardware."""

from contextlib import nullcontext
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from clarify.desktop import meeting_overlap as overlap
from clarify.desktop.meeting_source_labels import SourceWindow
from clarify.desktop.meeting_speakers import Voice
from clarify.desktop.meetings import MeetingStore, TranscriptBlock
from local_asr_live import RATE, TimedToken


def tokens(text, start=400):
    return tuple(
        TimedToken(start + i * 200, start + i * 200 + 200, word.encode())
        for i, word in enumerate(text.split())
    )


class MeetingOverlapTests(unittest.TestCase):
    def test_rolling_admission_drops_backlog_without_rediscovering_old_audio(self):
        candidates = overlap.OverlapCandidates()
        pcm = b"\x11\x22" * (14 * RATE)
        known = b"\x01" * (14 * RATE)
        window = SourceWindow(0, pcm, pcm, known)
        candidates.observe(0, window, [Voice(0, 1500, 1), Voice(2000, 3000, 2)], ())
        self.assertEqual(candidates.clips, [])
        voices = [
            Voice(1000, 2500, 1),
            Voice(1300, 2600, 2),
            Voice(4500, 6000, 1),
            Voice(4800, 6200, 2),
            Voice(7500, 9000, 1),
            Voice(7800, 9200, 2),
        ]
        candidates.observe(0, SourceWindow(0, pcm, pcm, bytes(14 * RATE)), voices, ())
        self.assertEqual(candidates.clips, [])
        candidates.observe(0, window, voices, ())
        candidates.observe(0, window, voices, ())
        self.assertEqual([clip.start for clip in candidates.clips], [0.95, 4.45])
        self.assertTrue(
            all(0 < len(clip.pcm) < 4 * RATE * 2 for clip in candidates.clips)
        )
        self.assertEqual(candidates.dropped, 1)
        for clip in candidates.clips[:]:
            candidates.complete(clip, None)
        self.assertFalse(candidates.observe(0, window, voices, ()))
        for offset in (18, 50, 90, 150):
            (clip,) = candidates.observe(
                0, SourceWindow(offset * 50, pcm, pcm, known), voices[:2], ()
            )
            self.assertAlmostEqual(clip.start, offset + 0.95)
            candidates.complete(clip, None)
            self.assertFalse(candidates.clips)

    def test_sustained_overlap_is_split_into_bounded_nonrepeated_clips(self):
        candidates = overlap.OverlapCandidates()
        pcm = b"\x11\x22" * (12 * RATE)
        window = SourceWindow(0, pcm, pcm, b"\x01" * (12 * RATE))
        voices = [Voice(200, 11000, 1), Voice(600, 10600, 2)]
        seen = []
        for offset in (0, 2, 4, 6):
            size = (6 + offset) * RATE
            rolling = SourceWindow(
                0, pcm[: 2 * size], pcm[: 2 * size], window.known[:size]
            )
            current = [
                Voice(voice.start, min(voice.end, (6 + offset) * 1000), voice.speaker)
                for voice in voices
            ]
            for clip in candidates.observe(0, rolling, current, ()):
                self.assertLessEqual(len(clip.pcm), 3600 * RATE * 2 // 1000)
                if seen:
                    self.assertGreaterEqual(clip.start, seen[-1].end)
                seen.append(clip)
                candidates.complete(clip, None)
        self.assertGreaterEqual(len(seen), 3)
        self.assertGreater(seen[-1].end, 10)

    def test_retirement_keeps_a_cross_block_replacement_and_archives_turns_once(self):
        candidates = overlap.OverlapCandidates()
        clip = overlap.OverlapClip(3, 5, b"mixed")
        candidates.clips.append(clip)
        text = "The lamp shines brightly."
        first = TranscriptBlock(
            0.0, 4, "The summary stays.", tokens("The summary stays.")
        )
        second = TranscriptBlock(4.0, 10, text, tokens(text))
        for block in (first, second):
            candidates.remember(block)
        turns = [
            {"start": 4.1, "end": 5, "text": text, "speaker": 2, "overlap": True},
            {
                "start": 4.2,
                "end": 5,
                "text": "We meet after lunch.",
                "speaker": 3,
                "overlap": True,
            },
        ]
        self.assertTrue(candidates.complete(clip, turns))
        self.assertFalse(candidates.clips)
        with tempfile.TemporaryDirectory() as directory:
            store = MeetingStore(Path(directory) / "meetings.sqlite3")
            meeting_id = store.create()["id"]
            for block in (first, second):
                store.checkpoint(meeting_id, block.start, block.end, block.text)
            batch = candidates.retire(4)
            self.assertEqual(batch["turns"], turns)
            with patch.object(store, "save_overlap", side_effect=OSError):
                with self.assertRaises(OSError):
                    store.save_overlap(meeting_id, batch)
            self.assertNotIn("originalSegments", store.get(meeting_id))
            self.assertEqual(candidates.view()["turns"], turns)
            retry = candidates.retire(4)
            self.assertEqual(retry, batch)
            store.save_overlap(meeting_id, retry)
            candidates.archive.clear()
            self.assertIsNone(candidates.retire(7))
            closing = candidates.retire(10)
            self.assertEqual(closing["blocks"], {"4.0": []})
            store.save_overlap(meeting_id, closing)
            candidates.archive.clear()
            self.assertFalse(candidates.blocks)
            self.assertFalse(candidates.pairs)
            self.assertEqual(candidates.revision, 1)
            saved = store.get(meeting_id)
            self.assertEqual(
                [row["text"] for row in saved["originalSegments"]], [first.text, text]
            )
            self.assertEqual(saved["segments"][1:], turns)

    def test_feeds_each_separated_stream_and_saves_only_text_beside_original(self):
        candidates = overlap.OverlapCandidates()
        clip = overlap.OverlapClip(1, 3, b"mixed")
        candidates.clips = [clip]
        original = "The lamp shines brightly above us."
        recovered = (original, "We will leave before noon.")
        mixed = TranscriptBlock(0, 4, original, tokens(original, 1200))
        candidates.remember(mixed)
        pcm = (b"\x11\x22" * 8, b"\x33\x44" * 8)
        records = []

        def new_session(language, callback):
            text = recovered[len(records)]
            feed = Mock()
            records.append(feed)
            done = threading.Event()
            done.set()
            return SimpleNamespace(
                feed=feed,
                finish=lambda **kwargs: SimpleNamespace(text=text, tokens=tokens(text)),
                cancel=lambda: None,
                done=done,
            )

        assets = Mock()
        with (
            patch.object(overlap, "pressure_normal", return_value=True),
            patch.object(
                overlap, "Separator", return_value=Mock(separate=Mock(return_value=pcm))
            ),
        ):
            view = overlap.recover(
                candidates,
                assets,
                new_session,
                "en",
                overlap.RecoveryBudget(threading.Event()),
            )
            self.assertEqual([feed.call_args.args[0] for feed in records], list(pcm))
            self.assertEqual([turn["text"] for turn in view["turns"]], list(recovered))
            self.assertTrue(all(not turn.get("speaker") for turn in view["turns"]))
            self.assertEqual(view["blocks"], {"0": []})

            # An unverified word-time mapping cannot safely remove duplicate text.
            candidates.blocks[0] = TranscriptBlock(0, 4, original, ())
            records.clear()
            self.assertIsNone(
                overlap.recover(
                    candidates,
                    assets,
                    new_session,
                    "en",
                    overlap.RecoveryBudget(threading.Event()),
                )
            )

        with tempfile.TemporaryDirectory() as directory:
            store = MeetingStore(Path(directory) / "meetings.sqlite3")
            meeting_id = store.create()["id"]
            store.checkpoint(meeting_id, 0.0, 4, original)
            store.save(meeting_id, {"notes": "User edit while stopping"})
            # Native segment starts are floating-point seconds.
            view["blocks"] = {"0.0": []}
            store.capture_state(meeting_id, "completed", recovery=view)
            saved = store.get(meeting_id)
            self.assertEqual(saved["notes"], "User edit while stopping")
            self.assertEqual(
                [turn["text"] for turn in saved["segments"]], list(recovered)
            )
            self.assertEqual(saved["originalSegments"][0]["text"], original)
            self.assertEqual(store.list("before noon", 0)[0]["id"], meeting_id)
            self.assertEqual(sorted(Path(directory).iterdir()), [store.path])
            store.delete(meeting_id)
            self.assertIsNone(store.get(meeting_id))

    def test_speaker_matching_uses_both_lane_margins_and_abstains(self):
        speakers = (8, 3)
        for scores, expected in (
            ([[0.81, 0.05], [0.12, 0.75]], speakers),
            ([[0.12, 0.75], [0.81, 0.05]], speakers[::-1]),
            ([[0.85, 0.05], [0.83, 0.07]], (None, None)),
            ([[0.66, 0.52], [0.08, 0.79]], (None, None)),
            ([[0.44, 0.05], [0.09, 0.8]], (None, None)),
        ):
            with self.subTest(scores=scores):
                self.assertEqual(overlap._match_embeddings(scores, speakers), expected)

    def test_live_worker_bounds_backlog_and_cancels_before_publishing(self):
        blocked, release = threading.Event(), threading.Event()
        publish = Mock()

        def compute(*args):
            blocked.set()
            self.assertTrue(release.wait(2))
            return [{"text": "Late recovery"}]

        with (
            patch.object(overlap, "pressure_normal", return_value=True),
            patch.object(overlap, "Separator"),
            patch.object(overlap, "_recover_clip", side_effect=compute),
        ):
            decoder = Mock(return_value=nullcontext(Mock()))
            worker = overlap.LiveRecovery(
                decoder, Mock(), None, "en", threading.Event(), publish
            )
            clip = overlap.OverlapClip(1, 2, b"pcm")
            try:
                self.assertTrue(worker.submit(clip))
                self.assertTrue(blocked.wait(1))
                self.assertTrue(worker.submit(clip))
                for _ in range(20):
                    self.assertFalse(worker.submit(clip))
                self.assertEqual(worker.jobs.qsize(), overlap.MAX_PENDING - 1)
                worker.close()
                publish.assert_not_called()
            finally:
                release.set()
                self.assertTrue(worker.finished.wait(1))
                worker.thread.join(timeout=1)
            self.assertEqual(worker.jobs.qsize(), 0)
            decoder.assert_called_once()
            publish.assert_not_called()

    def test_worker_setup_failure_preserves_the_unprocessed_clip_for_fallback(self):
        setup, release = threading.Event(), threading.Event()
        candidates = overlap.OverlapCandidates()
        clip = overlap.OverlapClip(1, 2, b"pcm")
        candidates.clips.append(clip)
        assets = Mock()

        def fail(_budget):
            setup.set()
            release.wait(2)
            raise OSError("Model setup failed")

        assets.verify.side_effect = fail
        with patch.object(overlap, "pressure_normal", return_value=True):
            worker = overlap.LiveRecovery(
                Mock(), assets, None, "en", threading.Event(), candidates.complete
            )
            try:
                self.assertTrue(setup.wait(1))
                self.assertTrue(worker.submit(clip))
            finally:
                release.set()
                self.assertTrue(worker.finished.wait(1))
            self.assertEqual(candidates.clips, [clip])
            with (
                patch.object(overlap, "Separator"),
                patch.object(
                    overlap,
                    "_recover_clip",
                    return_value=[{"start": 1, "end": 2, "text": "Retried the clip."}],
                ),
            ):
                view = overlap.recover(
                    candidates, Mock(), Mock(), "en", overlap.RecoveryBudget()
                )
            self.assertEqual(view["turns"][0]["text"], "Retried the clip.")

    def test_pressure_and_expired_decode_leave_no_pending_publication(self):
        candidates = overlap.OverlapCandidates()
        candidates.clips = [overlap.OverlapClip(0, 2, b"\x00\x00")]
        assets, open_session = Mock(), Mock()
        cancel = threading.Event()
        with patch.object(overlap, "pressure_normal", return_value=False):
            self.assertIsNone(
                overlap.recover(
                    candidates,
                    assets,
                    open_session,
                    "en",
                    overlap.RecoveryBudget(cancel),
                )
            )
        assets.verify.assert_not_called()
        open_session.assert_not_called()

        live = open_session.return_value
        budget = overlap.RecoveryBudget(cancel)

        def stop(**kwargs):
            cancel.set()
            raise TimeoutError

        live.finish.side_effect = stop
        with self.assertRaises(TimeoutError):
            overlap._decode(
                open_session, "en", b"\x11\x22", budget, candidates.clips[0]
            )
        live.cancel.assert_called_once()
        live.done.wait.assert_called_once_with(timeout=0)
