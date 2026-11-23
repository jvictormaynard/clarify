"""Speaker attribution follows timed speech and keeps names within a meeting."""

import queue
import struct
import threading
import unittest
from contextlib import closing, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from clarify.desktop.meeting_source_labels import (
    BIN_FRAMES,
    LOCAL_MICROPHONE,
    CleanAnchor,
    MixedSpeakerWorker,
    MixedWindow,
    ProfileInference,
    SourceBuffer,
    SourceSpeakerWorker,
    SourceTimeline,
    SourceVoices,
    SourceWindow,
)
from clarify.desktop.meeting_speakers import (
    CONTEXT_BYTES,
    MeetingVoices,
    SpeakerWorker,
    Voice,
)
from clarify.desktop.meetings import MeetingStore
from local_asr_live import RATE, TimedToken


class UnitVector(tuple):
    def __matmul__(self, other):
        return sum(left * right for left, right in zip(self, other))


class MeetingSpeakerTests(unittest.TestCase):
    def test_windows_worker_stops_after_two_native_timeouts(self):
        returned = threading.Event()
        recognizer = Mock()
        recognizer.voices.side_effect = TimeoutError
        publish = Mock()
        with patch(
            "clarify.desktop.meeting_speakers.Sortformer.open",
            side_effect=lambda *_: nullcontext(recognizer),
        ) as native:
            lane = MixedSpeakerWorker(
                None, Mock(), 1, None, lambda: False, publish, lambda _: returned.set()
            )
            self.addCleanup(lane.pace.close)
            complete = lane.pace.complete
            first_timeout = threading.Event()

            def finished(job, **feedback):
                complete(job, **feedback)
                first_timeout.set()

            with patch.object(lane.pace, "complete", finished):
                self.assertTrue(lane.pace.offer(6, lambda: MixedWindow(0, b"")))
                self.assertTrue(first_timeout.wait(1))
                self.assertTrue(lane.pace.offer(12, lambda: MixedWindow(0, b"")))
                self.assertTrue(returned.wait(1))
                lane.thread.join(1)
            self.assertFalse(lane.pace.offer(18, self.fail))
            self.assertEqual(native.call_count, 2)
            publish.assert_not_called()

    def test_close_drains_window_enqueued_after_queue_read_times_out(self):
        timed_out, release = threading.Event(), threading.Event()

        class DelayedTimeout(queue.Queue):
            def get(self, *args, **kwargs):
                if not timed_out.is_set():
                    timed_out.set()
                    release.wait(2)
                    raise queue.Empty
                return super().get(*args, **kwargs)

        published = []
        mailbox = DelayedTimeout(1)
        recognizer = SimpleNamespace(voices=lambda _: [Voice(0, 900, 1)])
        with (
            patch("clarify.desktop.meeting_speakers.queue.Queue", return_value=mailbox),
            patch(
                "clarify.desktop.meeting_speakers.Sortformer.open",
                return_value=nullcontext(recognizer),
            ),
        ):
            worker = SpeakerWorker(
                None,
                SimpleNamespace(verify=lambda _: None),
                (),
                1,
                threading.Event(),
                lambda start, *_: published.append(start),
                self.fail,
            )
            try:
                self.assertTrue(timed_out.wait(2))
                worker.submit(
                    bytes(2 * RATE), 0, 1, "Yes.", [TimedToken(100, 300, b"Yes.")]
                )
                worker.finished.set()
            finally:
                release.set()
                worker.close()
        self.assertEqual(published, [0])

    def test_slow_speaker_pass_accepts_one_waiting_window_and_never_blocks_capture(
        self,
    ):
        entered, release = threading.Event(), threading.Event()
        published, errors = [], []

        def voices(_pcm):
            entered.set()
            if not release.wait(2):
                raise TimeoutError()
            return [Voice(0, 1000, 1)]

        with patch(
            "clarify.desktop.meeting_speakers.Sortformer.open",
            return_value=nullcontext(SimpleNamespace(voices=voices)),
        ):
            worker = SpeakerWorker(
                None,
                SimpleNamespace(verify=lambda _: None),
                (),
                1,
                threading.Event(),
                lambda start, *_: published.append(start),
                errors.append,
            )
            try:
                pcm = bytes(2 * RATE)
                tokens = [TimedToken(100, 300, b"Yes.")]
                worker.submit(pcm, 0, 1, "Yes.", tokens)
                self.assertTrue(entered.wait(2))
                worker.submit(pcm, 4, 5, "Yes.", tokens)
                worker.submit(pcm, 8, 9, "Yes.", tokens)
            finally:
                release.set()
                worker.close()
        self.assertEqual(published, [0, 4])
        self.assertEqual(errors, [])

    def test_overlap_keeps_a_label_when_model_slots_change(self):
        windows = iter(
            (
                [Voice(5200, 9000, 1), Voice(9500, 11100, 2)],
                [
                    Voice(1200, 5000, 2),
                    Voice(5500, 7100, 1),
                    Voice(8100, 8600, 1),
                    Voice(8900, 9700, 2),
                ],
            )
        )

        class Recognizer:
            def voices(self, pcm):
                return next(windows)

        labeling = MeetingVoices(Recognizer(), 1)
        previous = labeling.label(
            bytes(CONTEXT_BYTES + 2 * RATE * 4),
            0,
            12,
            "Yes. Agreed.",
            [TimedToken(5300, 5510, b"Yes."), TimedToken(9560, 9850, b" Agreed.")],
        )
        self.assertEqual([row["speaker"] for row in previous], [1, 2])
        following = labeling.label(
            bytes(2 * RATE * 3),
            12,
            15,
            "Thanks. Good.",
            [TimedToken(150, 350, b"Thanks."), TimedToken(1000, 1200, b" Good.")],
        )
        self.assertEqual([row["speaker"] for row in following], [2, 1])
        self.assertEqual(" ".join(row["text"] for row in following), "Thanks. Good.")

    def test_ambiguous_or_mismatched_timing_preserves_the_plain_transcript(self):
        class Overlapping:
            def voices(self, pcm):
                return [Voice(0, 950, 1), Voice(0, 900, 2)]

        labeling = MeetingVoices(Overlapping(), 1)
        self.assertEqual(
            labeling.label(
                bytes(2 * RATE), 0, 1, "Yes", [TimedToken(100, 300, b"Yes")]
            ),
            [],
        )
        self.assertEqual(
            labeling.label(bytes(2 * RATE), 1, 2, "No", [TimedToken(100, 300, b"Yes")]),
            [],
        )

    def test_strong_tail_only_match_prevents_inheriting_the_wrong_name(self):
        recognizer = SimpleNamespace(
            voices=lambda _: [
                Voice(0, 5000, 1),
                Voice(5000, 5900, 2),
                Voice(8100, 9000, 2),
            ]
        )
        labeling = MeetingVoices(recognizer, 2)
        labeling.tail = bytes(CONTEXT_BYTES)
        labeling.previous = [Voice(0, 6000, 1)]
        labeling.last_end = 8
        rows = labeling.label(
            bytes(2 * RATE), 8, 9, "Hello", [TimedToken(200, 400, b"Hello")]
        )
        self.assertEqual([row["speaker"] for row in rows], [2])

    def test_source_windows_revise_labels_without_forcing_echo_or_overlap(self):
        buffer, tracker, timeline = (
            SourceBuffer(),
            SourceVoices(1, None),
            SourceTimeline(0),
        )

        def fixture(ranges, start):
            return b"".join(
                struct.pack("<h", 2000 if any(a <= point < b for a, b in ranges) else 0)
                * (RATE // 10)
                for point in range(start, start + 60)
            )

        microphone = [(4, 18), (35, 45), (51, 58)]
        system = [(22, 35), (36, 51), (71, 84), (98, 117)]
        first, second = (
            [Voice(2200, 3500, 1), Voice(3600, 5100, 2)],
            [
                Voice(2200, 3500, 2),
                Voice(3400, 5100, 1),
                Voice(7100, 8400, 2),
                Voice(9800, 11700, 1),
            ],
        )
        words = [
            TimedToken(700, 900, b"Local"),
            TimedToken(2700, 2900, b" Remote"),
            TimedToken(3900, 4100, b" Overlap"),
            TimedToken(5160, 5250, b" Echo"),
            TimedToken(7600, 7800, b" Again"),
            TimedToken(10500, 10700, b" Next"),
        ]
        text = "Local Remote Overlap Echo Again Next"

        def speakers():
            return [
                (row["text"], row["speaker"])
                for row in timeline.turns(0, 12, text, words)
            ]

        tracks = []
        for start, voices in ((0, first), (60, second)):
            remote = fixture(system, start)
            tracks.append(remote)
            buffer.append(fixture(microphone, start), remote, RATE * 6)
            window = buffer.snapshot()
            model = SimpleNamespace(voices=Mock(return_value=voices))
            labels = tracker.analyze(window, model)
            model.voices.assert_called_once_with(b"".join(tracks))
            timeline.update(window.start, labels)
            if start == 0:
                self.assertEqual(
                    speakers(),
                    [
                        ("Local", LOCAL_MICROPHONE),
                        ("Remote", 1),
                        ("Overlap Echo Again Next", None),
                    ],
                )
        self.assertEqual(
            speakers(),
            [
                ("Local", LOCAL_MICROPHONE),
                ("Remote", 1),
                ("Overlap Echo", None),
                ("Again", 1),
                ("Next", 2),
            ],
        )
        # After pause, use the old system tail as actual matching evidence.
        context = buffer.paused_context(
            tracker.previous_start, tracker.previous, tracker.next_speaker
        )
        resumed = SourceBuffer(context)
        resumed.append(bytes(12 * RATE), fixture([(2, 15)], 0), RATE * 6)
        window = resumed.snapshot()
        self.assertEqual(window.start, -400)
        resumed_tracker = SourceVoices(tracker.next_speaker, context)
        labels = resumed_tracker.analyze(
            window,
            SimpleNamespace(
                voices=lambda _: [Voice(3100, 4400, 1), Voice(8200, 9500, 1)]
            ),
        )
        self.assertEqual(labels[(9000 // 20)], 1)
        empty_tail = SourceBuffer().paused_context(0, (), 17)
        fresh = SourceVoices(1, empty_tail)
        self.assertEqual(set(fresh._match(0, (1,) * 20)), {17})
        # Revisions may withdraw a prior attribution. Mic signal by itself
        # cannot prove a local source if the tap supplied no samples.
        buffer = SourceBuffer()
        buffer.append(fixture(microphone, 0), bytes(2 * RATE * 6), 0)
        window = buffer.snapshot()
        labels = tracker.analyze(window, None)
        timeline.update(window.start, labels)
        self.assertNotIn(LOCAL_MICROPHONE, timeline.labels.values())
        self.assertNotIn(1, [timeline.labels[i] for i in range(300)])

    def test_source_returns_from_clean_references_without_shared_audio(self):
        buffer = SourceBuffer()
        tracker = SourceVoices(1, None)
        embedding = Mock(
            side_effect=[
                UnitVector((1, 0)),
                UnitVector((0.96, 0.28)),
                UnitVector((1, 0)),
            ]
        )
        tracker.embedding = SimpleNamespace(embedding=embedding)

        def analyze(target, window, voices):
            return target.analyze(window, SimpleNamespace(voices=lambda _: voices))

        sound = struct.pack("<h", 2000) * (RATE * 6)
        buffer.append(bytes(len(sound)), sound, len(sound) // 2)
        first = buffer.snapshot()
        voices = [Voice(200, 2000, 1), Voice(2600, 4500, 1)]
        labels = analyze(tracker, first, voices)
        self.assertEqual(labels[50], 1)
        analyze(tracker, first, voices)
        self.assertEqual(embedding.call_count, 2)

        silence = bytes(2 * RATE * 14)
        buffer.append(silence, silence, len(silence) // 2)
        analyze(tracker, buffer.snapshot(), [])
        context = buffer.paused_context(
            tracker.previous_start,
            tracker.previous,
            tracker.next_speaker,
            tracker.profiles,
        )
        self.assertTrue(all(anchor is None for anchor in context.anchors))
        resumed = SourceBuffer(context)
        resumed.append(bytes(len(sound)), sound, len(sound) // 2)
        tracker = SourceVoices(2, context)
        return_voice = [Voice(8400, 10400, 2)]
        before = resumed.snapshot()
        tracker.embedding = SimpleNamespace(embedding=embedding)
        labels = analyze(tracker, before, return_voice)
        self.assertEqual(labels[450], 1)
        new_meeting = SourceVoices(1, None)
        self.assertEqual(new_meeting.profiles.anchors, {})

    def test_profile_rejects_weak_ambiguous_and_competing_claims(self):
        tracker = SourceVoices(1, None)

        def anchor(first, second):
            return CleanAnchor(0, 80, UnitVector((first, second)))

        profiles = tracker.profiles
        profiles.remember(1, [anchor(1, 0), anchor(0.98, 0.2)], seed_until=0)
        profiles.remember(2, [anchor(0, 1), anchor(0.2, 0.98)], seed_until=0)
        raw = (1,) * 80 + (2,) * 80
        cases = [
            ({1: [anchor(1, 0)], 2: [anchor(0, 1)]}, {}, ({1: 1, 2: 2}, set())),
            ({1: [anchor(0.71, 0.70)]}, {}, ({}, set())),
            ({1: [anchor(0.60, 0.30)]}, {}, ({}, set())),
            ({1: [anchor(1, 0)], 2: [anchor(1, 0)]}, {}, ({}, set())),
            ({1: [anchor(1, 0)]}, {2: 1}, ({}, set())),
            ({1: [anchor(0.30, 0.30)]}, {}, ({}, {1})),
        ]
        for samples, reserved, expected in cases:
            with self.subTest(samples=samples, reserved=reserved):
                self.assertEqual(profiles.resolve([1, 2], reserved, samples), expected)
        tracker.previous = (2,) * 80 + (1,) * 80
        tracker.previous_start = 0
        self.assertEqual(tracker._match(0, raw, cases[0][0]), tracker.previous)

    def test_short_turn_and_single_reference_get_anonymous_timing_labels(self):
        tracker = SourceVoices(7, None)
        tracker.profiles.remember(
            4, [CleanAnchor(0, 80, UnitVector((1, 0)))], seed_until=0
        )
        raw = (1,) * 30
        self.assertEqual(set(tracker._match(0, raw, {})), {None})
        self.assertEqual(set(tracker._match(0, raw + (None,) * 150, {})[:30]), {7})

        raw = (2,) * 30
        samples = {2: [CleanAnchor(240, 310, UnitVector((0.96, 0.28)))]}
        self.assertEqual(set(tracker._match(220, raw, samples, final=True)), {8})
        self.assertEqual(len(tracker.profiles.anchors[4]), 1)

    def test_continuity_cannot_enroll_a_conflicting_late_occupant(self):
        tracker = SourceVoices(3, None)

        def anchor(start, *values):
            return CleanAnchor(start, start + 80, UnitVector(values))

        profiles = tracker.profiles
        profiles.remember(
            1, [anchor(0, 1, 0, 0), anchor(100, 0.98, 0, 0.2)], seed_until=0
        )
        profiles.remember(
            2, [anchor(5, 0, 1, 0), anchor(120, 0, 0.98, -0.2)], seed_until=5
        )
        tracker.previous = (1,) * 20
        raw = (1,) * 160
        late = anchor(80, 0.71, 0.70, 0)
        self.assertEqual(set(tracker._match(0, raw, {1: [late]})), {1})
        self.assertEqual(len(profiles.anchors[1]), 2)

        fresh = SourceVoices(1, None)
        samples = {1: [anchor(0, 1, 0, 0)], 2: [anchor(80, 1, 0, 0)]}
        self.assertEqual(set(fresh._match(0, (1,) * 80 + (2,) * 80, samples)), {1, 2})
        self.assertEqual(fresh.profiles.anchors, {})

    def test_optional_profile_work_skips_pressure_and_obeys_deadline(self):
        release = threading.Event()
        entered = threading.Event()

        def embed(_):
            entered.set()
            release.wait(2)
            return object()

        model = SimpleNamespace(embedding=Mock(side_effect=embed))
        abort = threading.Event()
        inference = ProfileInference(object(), threading.Event(), abort)
        with (
            patch(
                "clarify.desktop.meeting_source_labels.pressure_normal",
                return_value=False,
            ) as pressure,
            patch(
                "clarify.desktop.meeting_source_labels.open_speaker_embedding",
                return_value=model,
            ) as load,
            patch("clarify.desktop.meeting_source_labels.PROFILE_WAIT", 0.08),
        ):
            try:
                inference.prepare()
                load.assert_not_called()
                pressure.return_value = True
                inference.prepare()
                self.assertTrue(inference.ready.wait(1))
                pressure.return_value = False
                inference.prepare()
                self.assertIsNone(inference.embedding(b"pcm"))
                model.embedding.assert_not_called()
                pressure.return_value = True
                inference.prepare()
                self.assertIsNone(inference.embedding(b"pcm"))
                self.assertTrue(entered.is_set())
                self.assertTrue(inference.thread.is_alive())
            finally:
                abort.set()
                inference.close()
                release.set()
                if inference.thread is not None:
                    inference.thread.join(1)
        self.assertFalse(inference.ready.is_set())

    def test_optional_model_load_cannot_hold_source_worker_close(self):
        loading, finish, last_context = (threading.Event() for _ in range(3))
        end = threading.Event()

        def blocked_load(*_):
            loading.set()
            finish.wait(2)
            return object()

        with (
            patch(
                "clarify.desktop.meeting_source_labels.Sortformer.open",
                return_value=nullcontext(object()),
            ),
            patch(
                "clarify.desktop.meeting_source_labels.pressure_normal",
                return_value=True,
            ),
            patch(
                "clarify.desktop.meeting_source_labels.open_speaker_embedding",
                side_effect=blocked_load,
            ),
        ):
            publish = Mock()
            assets = SimpleNamespace(available=lambda: True, verify=Mock())
            worker = SourceSpeakerWorker(
                object(),
                assets,
                1,
                None,
                threading.Event(),
                publish,
                Mock(),
                embedding_assets=assets,
                capture_end=end,
            )

            def close():
                worker.close()
                last_context.set()

            try:
                self.assertTrue(loading.wait(1))
                end.set()
                closer = threading.Thread(target=close)
                closer.start()
                self.assertTrue(last_context.wait(0.5))
                self.assertTrue(worker.inference.thread.is_alive())
            finally:
                finish.set()
                if worker.inference.thread is not None:
                    worker.inference.thread.join(1)
            publish.assert_not_called()
            self.assertEqual(worker.labeling.profiles.anchors, {})

    def test_profile_does_not_sample_simultaneous_or_unavailable_audio(self):
        tracker = SourceVoices(1, None)
        tracker.embedding = SimpleNamespace(embedding=Mock())
        size = 240 * BIN_FRAMES
        voice = struct.pack("<h", 2000) * size
        silence = bytes(len(voice))
        active = b"\x01" * size
        for window, voices in (
            (SourceWindow(0, silence, voice, active), [Voice(100, 4300, 2)]),
            (SourceWindow(0, voice, voice, active), []),
            (SourceWindow(0, silence, voice, bytes(size)), []),
        ):
            tracker.analyze(
                window,
                SimpleNamespace(voices=lambda _: [Voice(200, 4000, 1)] + voices),
            )
        tracker.embedding.embedding.assert_not_called()

    def test_old_transcript_and_per_meeting_names_survive_reopen(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "meetings.sqlite3"
            store = MeetingStore(path)
            first, second = store.create()["id"], store.create()["id"]
            store.checkpoint(first, 0, 3, "Older plain transcript.")
            # Recreate the pre-diarization schema with its persisted data.
            with closing(store.connect()) as db, db:
                db.execute("ALTER TABLE meeting_segments DROP COLUMN speaker_turns")
            store = MeetingStore(path)
            for meeting in (first, second):
                store.checkpoint(meeting, 3, 4, "Thanks.")
                store.annotate(
                    meeting,
                    3,
                    4,
                    "Thanks.",
                    [
                        {"start": 3.1, "end": 3.9, "text": "Thanks.", "speaker": 1},
                    ],
                )
            store.name_speaker(first, 1, "João")
            reopened = MeetingStore(path)
            self.assertEqual(
                reopened.get(first)["segments"][0]["text"], "Older plain transcript."
            )
            self.assertEqual(reopened.get(first)["speakers"], {1: "João"})
            self.assertEqual(reopened.get(second)["speakers"], {})
            reopened.name_speaker(first, 1, "")
            self.assertEqual(reopened.get(first)["speakers"], {})
