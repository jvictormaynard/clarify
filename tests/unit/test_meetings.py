"""Meeting capture and save contracts with isolated text and fake PCM."""

import base64
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
from contextlib import closing, contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from clarify.desktop import meeting_overlap, meetings
from clarify.desktop.meeting_source_labels import (
    LOCAL_MICROPHONE,
    SYSTEM_AUDIO,
    Sortformer,
)
from clarify.desktop.meeting_speakers import Voice
from clarify.desktop.meetings import (
    Capture,
    MeetingError,
    Meetings,
    MeetingStore,
    configured_summary,
    local_summary,
)
from local_asr import LocalASRCancelledError
from local_asr_live import MAX_CHUNK, RATE, LiveResult, TimedToken
from provider_http import CancellationToken
from repositories import AppConfig
from workflow_config import WorkflowRoute, WorkflowScope


class FakeLive:
    def __init__(self, publish):
        self.publish = publish
        self.ready = threading.Event()
        self.ready.set()
        self.done = threading.Event()
        self.samples = 0
        self.error = None

    def feed(self, chunk, **kwargs):
        self.samples += len(chunk) // 2
        self.publish(
            LiveResult("A decision.", "A decision.", False, self.samples / 16000)
        )

    def finish(self, **_options):
        return LiveResult("A decision.", "A decision.", True, self.samples / 16000)

    def end_input(self, **_options):
        pass

    def cancel(self):
        self.done.set()


class MeetingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name)
        self.path = folder / "meetings.sqlite3"
        executable, model = folder / "native", folder / "model"
        executable.touch()
        model.touch()
        installer = SimpleNamespace(
            platform_supported=lambda: True,
            executable_path=executable,
            model_path=model,
        )
        self.controller = Meetings(
            self.path,
            backend=lambda: SimpleNamespace(
                reserve_live=lambda **_options: nullcontext(
                    lambda _language, publish: FakeLive(publish)
                ),
                isolated_decoder=lambda _cancel, **_options: nullcontext(
                    lambda _language, publish: FakeLive(publish)
                ),
            ),
            language=lambda: "en",
            allowed=lambda: True,
            summary_provider=lambda: self.summarize,
            copy=lambda _: None,
            installer=installer,
            loopback=False,
        )
        self.addCleanup(self.controller.shutdown)
        self.summarize = Mock(return_value="Generated summary")

    def wait_for(self, condition):
        deadline = time.monotonic() + 2
        while not condition():
            if time.monotonic() >= deadline:
                self.fail("Expected meeting state did not arrive")
            threading.Event().wait(0.005)

    def begin_audio(self, meeting_id):
        self.controller.media_ready(meeting_id)
        self.wait_for(
            lambda: self.controller.state()["active"]["status"] == "recording"
        )
        self.controller.feed(
            meeting_id, base64.b64encode(b"\x11\x22" * (MAX_CHUNK // 2)).decode()
        )

    def test_windows_paired_turns_survive_pause_and_failed_stop_checkpoint(self):
        controller = self.controller
        controller.loopback = True
        meeting_id = controller.create()["id"]
        inputs = {"mic": b"\x11\x22", "system": b"\x33\x44"}
        mic, system = (
            base64.b64encode(sample * (MAX_CHUNK // 2)).decode()
            for sample in inputs.values()
        )
        finalized = set()
        sessions = []

        def decoder(source):
            def open_live(_language, publish):
                text = {"mic": "Local voice.", "system": "Remote voice."}[source]
                tokens = (TimedToken(20, 70, text.encode()),)
                live = FakeLive(publish)
                sessions.append(live)

                def feed(chunk, **_):
                    self.assertEqual(chunk, inputs[source] * (MAX_CHUNK // 2))
                    live.samples += len(chunk) // 2
                    publish(LiveResult(text, text, False, live.samples / RATE, tokens))

                def finish(**_options):
                    self.assertEqual(finalized, {"mic", "system"})
                    return LiveResult(text, text, True, live.samples / RATE, tokens)

                live.feed = feed
                live.end_input = lambda **_options: finalized.add(source)
                live.finish = finish
                return live

            return nullcontext(open_live)

        controller.backend = lambda: SimpleNamespace(
            reserve_live=lambda **_: decoder("system"),
            isolated_decoder=lambda _, **__: decoder("mic"),
        )
        with (
            patch.object(meetings, "sys", SimpleNamespace(platform="win32")),
            patch.object(meetings, "windows_cpu_count", return_value=4),
        ):
            lease = controller.start(meeting_id, "system")["captureId"]
            controller.media_ready(meeting_id, lease_id=lease)
            self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
            for args, error in [
                ((mic, "AAA=", lease), "invalid_audio"),
                ((mic, system, "stale"), "capture_unavailable"),
            ]:
                with self.assertRaisesRegex(MeetingError, error):
                    controller.feed_channels(meeting_id, *args)
            with self.assertRaisesRegex(MeetingError, "capture_unavailable"):
                controller.feed(meeting_id, mic, False, lease)
            controller.feed_channels(meeting_id, mic, system, lease)
            self.wait_for(lambda: len(controller.state()["partialTurns"]) == 2)
            live_turns = controller.state()["partialTurns"]
            self.assertEqual(
                [turn["speaker"] for turn in live_turns],
                [LOCAL_MICROPHONE, SYSTEM_AUDIO],
            )
            self.assertEqual(
                [(turn["start"], turn["end"]) for turn in live_turns],
                [(0.02, 0.07)] * 2,
            )
            controller.release_media(lease)
            controller.pause(meeting_id)
            self.wait_for(lambda: controller.get(meeting_id)["status"] == "paused")
            self.assertEqual(controller.get(meeting_id)["segments"], live_turns)
            self.assertEqual(
                [row["id"] for row in controller.list("Remote voice.", 0)], [meeting_id]
            )
            self.assertEqual(controller.list("voice. Remote", 0), [])

            finalized.clear()
            resumed = controller.resume(meeting_id)["captureId"]
            controller.media_ready(meeting_id, lease_id=resumed)
            self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
            controller.feed_channels(meeting_id, mic, system, resumed)
            self.wait_for(lambda: len(controller.state()["partialTurns"]) == 2)
            resumed_turns = controller.state()["partialTurns"]
            controller.release_media(resumed)
            with patch.object(
                controller.store, "checkpoint", side_effect=sqlite3.OperationalError
            ):
                controller.stop(meeting_id)
                self.wait_for(lambda: controller.state()["active"] is None)
                self.assertEqual(
                    controller.get(meeting_id)["segments"], live_turns + resumed_turns
                )
            self.assertEqual(
                controller.get(meeting_id)["segments"], live_turns + resumed_turns
            )
            self.assertEqual(len(sessions), 4)
            self.assertFalse(controller.busy)

    def test_windows_low_cpu_combines_both_inputs_in_one_decoder(self):
        controller = self.controller
        controller.loopback = True
        meeting_id = controller.create()["id"]
        paired = (12000, 0, 25000, -25000), (0, 10000, 22000, -22000)
        mic, system = [
            base64.b64encode(struct.pack("<4h", *channel)).decode()
            for channel in paired
        ]
        session = FakeLive(lambda _: None)
        feed = session.feed = Mock(wraps=session.feed)

        def open_live(_language, publish):
            session.publish = publish
            return session

        engine = SimpleNamespace(
            reserve_live=Mock(return_value=nullcontext(open_live)),
            isolated_decoder=Mock(side_effect=AssertionError("One model required")),
        )
        controller.backend = lambda: engine
        with (
            patch.object(meetings, "sys", SimpleNamespace(platform="win32")),
            patch.object(meetings, "windows_cpu_count", return_value=2),
            patch.object(controller, "speakers_ready", return_value=True),
        ):
            lease = controller.start(meeting_id, "system")["captureId"]
            controller.media_ready(meeting_id, lease_id=lease)
            self.wait_for(
                lambda: (
                    controller.state()["active"] is None
                    or (controller.state()["active"]["status"] == "recording")
                )
            )
            active = controller.state()["active"]
            self.assertIsNotNone(active)
            self.assertTrue(active["lightMode"])
            self.assertFalse(active["speakerLabels"])
            with self.assertRaisesRegex(MeetingError, "capture_unavailable"):
                controller.feed_channels(meeting_id, mic, system, "stale")
            controller.feed_channels(meeting_id, mic, system, lease)
            self.wait_for(lambda: bool(controller.state()["partial"]))
            controller.release_media(lease)
            controller.pause(meeting_id)
            self.wait_for(lambda: controller.get(meeting_id)["status"] == "paused")
            self.assertTrue(controller.state()["active"]["lightMode"])
            controller.stop(meeting_id)
            self.assertEqual(controller.get(meeting_id)["status"], "completed")
        engine.reserve_live.assert_called_once_with(threads=2)
        engine.isolated_decoder.assert_not_called()
        self.assertEqual(
            feed.call_args.args[0], struct.pack("<4h", 12000, 10000, 32767, -32768)
        )
        [turn] = controller.get(meeting_id)["segments"]
        self.assertEqual(turn["text"], "A decision.")
        self.assertNotIn("source", turn)

    def test_windows_light_mode_drains_audio_after_a_recognizer_stall(self):
        for source in ("system", "mic"):
            with self.subTest(source=source):
                self._assert_windows_stall_drains(source)

    def _assert_windows_stall_drains(self, source):
        controller = self.controller
        controller.loopback = True
        meeting = controller.create()["id"]
        packet = base64.b64encode(b"\x11\x22" * (meetings.MAX_PACKET // 2)).decode()
        stalled, release = threading.Event(), threading.Event()
        session = FakeLive(lambda _: None)

        def open_live(_language, publish):
            session.publish = publish
            return session

        def feed(chunk, **options):
            if not session.samples:
                self.assertGreater(options["timeout"], 12)
                stalled.set()
                if not release.wait(options["timeout"]):
                    raise AssertionError("Recognition should have time to drain")
            FakeLive.feed(session, chunk, **options)

        session.feed = feed
        reserve = Mock(return_value=nullcontext(open_live))
        controller.backend = lambda: SimpleNamespace(reserve_live=reserve)

        def feed_packet(lease):
            if source == "mic":
                controller.feed(meeting, packet, lease_id=lease)
            else:
                controller.feed_channels(meeting, packet, packet, lease)

        with (
            patch.object(meetings, "sys", SimpleNamespace(platform="win32")),
            patch.object(meetings, "windows_cpu_count", return_value=2),
        ):
            lease = controller.start(meeting, source)["captureId"]
            controller.media_ready(meeting, lease_id=lease)
            self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
            self.assertEqual(
                controller.state()["active"]["lightMode"], source == "system"
            )
            feed_packet(lease)
            try:
                self.assertTrue(stalled.wait(1))
                # More than the old 25-packet capture queue can hold.
                for _ in range(30):
                    feed_packet(lease)
                self.assertEqual(controller.state()["active"]["status"], "recording")
                self.assertTrue(controller.drain_light_capture_for_quit())
                self.assertEqual(controller.state()["active"]["status"], "finalizing")
                controller.release_media(lease)
            finally:
                release.set()
            self.wait_for(lambda: controller.get(meeting)["status"] == "completed")
            self.assertFalse(controller.drain_light_capture_for_quit())
        reserve.assert_called_once_with(threads=2)
        saved = MeetingStore(self.path).get(meeting)
        self.assertAlmostEqual(saved["duration"], 31 * meetings.MAX_PACKET / (2 * RATE))
        self.assertEqual(session.samples, 31 * meetings.MAX_PACKET // 2)
        self.assertEqual(saved["segments"][0]["text"], "A decision.")

    def test_system_tap_feeds_separate_decoders_and_releases_between_intervals(self):
        microphone = b"\x11\x22" * (MAX_CHUNK // 2)
        mixed = b"\x33\x44" * (MAX_CHUNK // 2)
        first, second = Mock(), Mock()
        system = b"\x55\x66" * (MAX_CHUNK // 2)
        first.mix.return_value = mixed, system, len(system) // 2, True
        second.mix.return_value = (
            microphone,
            bytes(len(microphone)),
            len(microphone) // 2,
            False,
        )
        factory = self.controller.system_audio = Mock(side_effect=[first, second])
        self.controller.loopback = True
        meeting = self.controller.create()["id"]

        with patch.object(
            FakeLive, "feed", autospec=True, side_effect=FakeLive.feed
        ) as feed:
            admission = self.controller.start(meeting, "system")
            factory.assert_not_called()
            self.begin_audio(meeting)
            self.wait_for(lambda: feed.call_count == 2)
            self.assertCountEqual(
                [call.args[1] for call in feed.call_args_list], [microphone, system]
            )
            self.assertTrue(self.controller.state()["active"]["systemAudio"])

            self.controller.release_media(admission["captureId"])
            first.close.assert_called_once_with()
            self.controller.pause(meeting)
            self.wait_for(
                lambda: self.controller.state()["active"]["status"] == "paused"
            )

            resumed = self.controller.resume(meeting)
            self.assertEqual(factory.call_count, 1)
            self.begin_audio(meeting)
            self.controller.release_media(admission["captureId"])
            second.close.assert_not_called()
            self.controller.stop(meeting)
            second.close.assert_called_once_with()
            self.controller.release_media(resumed["captureId"])
            self.wait_for(lambda: self.controller.state()["active"] is None)
            first.close.assert_called_once_with()
            second.close.assert_called_once_with()

    def test_capture_waits_for_history_playback_to_stop(self):
        requested, stopped = threading.Event(), threading.Event()

        def stop_playback(_cancel):
            requested.set()
            if not stopped.wait(2):
                raise RuntimeError("Audio playback did not stop")

        controller = self.controller
        controller.before_capture = stop_playback
        controller.loopback = True
        tap = Mock()
        controller.system_audio = tap
        meeting_id = controller.create()["id"]
        admission = controller.start(meeting_id, "system")
        try:
            self.assertTrue(requested.wait(2))
            controller.media_ready(meeting_id)
            self.assertEqual(controller.state()["active"]["status"], "starting")
            tap.assert_not_called()
        finally:
            stopped.set()
        self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
        tap.assert_called_once_with()
        controller.stop(meeting_id)
        controller.release_media(admission["captureId"])
        self.wait_for(lambda: controller.get(meeting_id)["status"] == "completed")

    def test_interruption_notice_survives_background_reads(self):
        controller = self.controller
        meeting_id = controller.create()["id"]
        admission = controller.start(meeting_id, "mic")
        self.begin_audio(meeting_id)
        controller.interrupt(meeting_id, "capture_overload")
        controller.release_media(admission["captureId"])
        self.wait_for(lambda: controller.state()["active"] is None)
        self.assertEqual(controller.get(meeting_id)["error"], "capture_overload")
        controller.acknowledge_interruption("different-meeting")
        self.assertEqual(controller.state()["interruptedId"], meeting_id)
        controller.acknowledge_interruption(meeting_id)
        self.assertIsNone(controller.state()["interruptedId"])
        self.assertEqual(controller.get(meeting_id)["status"], "interrupted")

    def test_native_source_labels_keep_simultaneous_local_and_remote_turns(self):
        microphone = b"\x00\x08" * (MAX_CHUNK // 2)
        system = b"\x00\x10" * (MAX_CHUNK // 2)
        tap = Mock()
        tap.mix.return_value = bytes(len(system)), system, len(system) // 2, True
        controller = self.controller
        controller.system_audio = lambda: tap
        controller.loopback = True
        meeting_id = controller.create()["id"]
        remote_voice = Mock()
        progressed = threading.Event()
        allow_labels = threading.Event()

        def analyze_remote(_pcm):
            if not allow_labels.wait(5):
                raise TimeoutError("Meeting checkpoint did not arrive")
            return [Voice(0, 7000, 1)]

        remote_voice.voices.side_effect = analyze_remote

        def decoder(text, expected):
            def open_session(_language, publish):
                live = FakeLive(publish)
                tokens = (TimedToken(300, 650, text.encode()),)

                def feed(chunk, **_options):
                    self.assertEqual(chunk, expected)
                    live.samples += len(chunk) // 2
                    publish(LiveResult(text, text, False, live.samples / RATE, tokens))
                    if expected == system:
                        progressed.set()

                live.feed = feed
                live.finish = lambda **_: LiveResult(
                    text, text, True, live.samples / RATE, tokens
                )
                return live

            return nullcontext(open_session)

        controller.backend = lambda: SimpleNamespace(
            reserve_live=lambda **_: decoder("Remote.", system),
            isolated_decoder=lambda _cancel, **_: decoder("Local.", microphone),
            verified_library=object(),
        )
        encoded = base64.b64encode(microphone).decode()
        with (
            patch.object(controller, "speakers_ready", return_value=True),
            patch.object(controller.speaker_assets, "verify"),
            patch(
                "clarify.desktop.meeting_source_labels.Sortformer.open",
                return_value=nullcontext(remote_voice),
            ),
        ):
            controller.start(meeting_id, "system")
            controller.media_ready(meeting_id)
            self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
            try:
                for _ in range(75):
                    progressed.clear()
                    controller.feed(meeting_id, encoded)
                    self.assertTrue(progressed.wait(1))
                self.assertEqual(
                    [row["speaker"] for row in controller.state()["partialTurns"]],
                    [LOCAL_MICROPHONE, SYSTEM_AUDIO],
                )
                controller.stop(meeting_id)
                self.wait_for(
                    lambda: bool(controller.store.get(meeting_id)["segments"])
                )
                checkpoint = controller.store.get(meeting_id)["segments"]
                self.assertEqual(
                    [row["speaker"] for row in checkpoint],
                    [LOCAL_MICROPHONE, SYSTEM_AUDIO],
                )
            finally:
                allow_labels.set()
            self.wait_for(lambda: controller.state()["active"] is None)
        turns = controller.get(meeting_id)["segments"]
        self.assertEqual(
            [
                (turn["text"], turn["speaker"], turn["start"], turn["end"])
                for turn in turns
            ],
            [("Local.", LOCAL_MICROPHONE, 0.3, 0.65), ("Remote.", 1, 0.3, 0.65)],
        )
        self.assertFalse(list(self.path.parent.rglob("*.wav")))

    def test_windows_system_labels_follow_live_tokens_and_reject_late_results(self):
        controller = self.controller
        controller.loopback = True
        meeting_id = controller.create()["id"]
        pcm = b"\x00\x08" * (MAX_CHUNK // 2)
        packet = base64.b64encode(pcm).decode()
        silent_packet = base64.b64encode(bytes(len(pcm))).decode()
        text = "First. Mixed."
        tokens = (TimedToken(300, 600, b"First."), TimedToken(900, 1200, b" Mixed."))
        fed, analyzing, release, closed = (threading.Event() for _ in range(4))
        self.addCleanup(release.set)
        pressure = threading.Event()
        sessions, cancellations = [], []

        def open_live(**options):
            self.assertEqual(options, {"live_tokens": True})

            def session(_language, publish):
                live = FakeLive(publish)
                live.queue = SimpleNamespace(
                    qsize=lambda: 8 if pressure.is_set() else 0
                )
                sessions.append(live)
                return live

            return nullcontext(session)

        def decode(live, chunk, **_options):
            self.assertEqual(chunk, pcm)
            live.samples += len(chunk) // 2
            live.publish(LiveResult(text, text, False, live.samples / RATE, tokens))
            fed.set()

        def finish(live, **_options):
            return LiveResult(text, text, True, live.samples / RATE, tokens)

        recognizer = Mock()

        def voices(window):
            if recognizer.voices.call_count == 1:
                self.assertGreater(len(window), 12 * RATE)
                return [Voice(200, 1700, 7), Voice(800, 1450, 9)]
            analyzing.set()
            self.assertTrue(release.wait(5))
            return [Voice(200, 1700, 3)]

        recognizer.voices.side_effect = voices

        @contextmanager
        def open_sortformer(_library, _path, cancel):
            cancellations.append(cancel)
            try:
                yield recognizer
            finally:
                closed.set()

        def send(chunks, lease):
            for _ in range(chunks):
                fed.clear()
                controller.feed_channels(meeting_id, silent_packet, packet, lease)
                self.assertTrue(fed.wait(1))

        def open_mic(_language, _publish):
            # The loopback labels and pressure checks use only system PCM.
            live = FakeLive(None)
            live.feed = lambda chunk, **_: self.assertEqual(chunk, bytes(len(pcm)))
            live.finish = lambda **_options: LiveResult("", "", True, 0)
            live.queue = SimpleNamespace(qsize=lambda: 0)
            return live

        controller.backend = lambda: SimpleNamespace(
            reserve_live=open_live,
            verified_library=object(),
            isolated_decoder=lambda _, **__: nullcontext(open_mic),
        )
        with (
            patch.object(meetings, "sys", SimpleNamespace(platform="win32")),
            patch.object(meetings, "windows_cpu_count", return_value=4),
            patch.object(controller, "speakers_ready", return_value=True),
            patch.object(controller.speaker_assets, "verify"),
            patch.object(Sortformer, "open", open_sortformer),
            patch.object(FakeLive, "feed", decode),
            patch.object(FakeLive, "finish", finish),
        ):
            lease = controller.start(meeting_id, "system")["captureId"]
            controller.media_ready(meeting_id, lease_id=lease)
            self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
            self.assertTrue(controller.state()["active"]["liveSpeakerLabels"])

            send(74, lease)
            pressure.set()
            send(2, lease)
            pressure.clear()
            send(73, lease)
            self.assertEqual(recognizer.voices.call_count, 0)
            send(3, lease)
            self.wait_for(
                lambda: any(
                    r["speaker"] == 1 for r in controller.state()["partialTurns"]
                )
            )
            self.assertEqual(
                [r["speaker"] for r in controller.state()["partialTurns"]],
                [1, SYSTEM_AUDIO],
            )

            send(75, lease)
            self.assertTrue(analyzing.wait(1))
            previous_samples = sessions[0].samples
            pressure.set()
            send(3, lease)
            self.assertEqual(sessions[0].samples, previous_samples + 3 * MAX_CHUNK // 2)
            self.assertTrue(cancellations[0].is_set())
            pressure.clear()
            controller.release_media(lease)
            controller.pause(meeting_id)
            self.wait_for(lambda: controller.get(meeting_id)["status"] == "paused")
            self.assertFalse(closed.is_set())
            paused = controller.get(meeting_id)["segments"]
            self.assertEqual([r["speaker"] for r in paused], [1, SYSTEM_AUDIO])
            self.assertEqual(" ".join(r["text"] for r in paused), text)

            resumed = controller.resume(meeting_id)["captureId"]
            controller.media_ready(meeting_id, lease_id=resumed)
            self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
            release.set()
            self.assertTrue(closed.wait(1))
            self.assertEqual(controller.state()["partialTurns"], [])
            self.assertEqual(controller.get(meeting_id)["segments"], paused)

            analyzing.clear()
            closed.clear()
            release.clear()
            send(75, resumed)
            self.assertTrue(analyzing.wait(1))
            controller.release_media(resumed)
            controller.stop(meeting_id)
            self.wait_for(lambda: controller.state()["active"] is None)
            self.assertFalse(closed.is_set())
            saved = controller.get(meeting_id)["segments"]
            self.assertEqual(saved[:-1], paused)
            self.assertEqual(saved[-1]["text"], text)
            self.assertEqual(saved[-1]["speaker"], SYSTEM_AUDIO)
            release.set()
            self.assertTrue(closed.wait(1))
            self.assertEqual(controller.get(meeting_id)["segments"], saved)
            self.assertEqual(recognizer.voices.call_count, 3)

            meeting_id = controller.create()["id"]
            lease = controller.start(meeting_id, "system")["captureId"]
            controller.media_ready(meeting_id, lease_id=lease)
            self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
            send(20, lease)
            controller.release_media(lease)
            # SQLite revision starts outside the capture lock.
            original_revise = controller.store.revise_speakers
            revised = []

            def revise(*args, **kwargs):
                revised.append(not controller.lock._is_owned())
                return original_revise(*args, **kwargs)

            with patch.object(controller.store, "revise_speakers", revise):
                controller.stop(meeting_id)
                self.wait_for(lambda: controller.state()["active"] is None)
            rows = controller.get(meeting_id)["segments"]
            self.assertEqual(revised, [True])
            self.assertEqual([(r["text"], r["speaker"]) for r in rows], [(text, 1)])

            meeting_id = controller.create()["id"]
            closed.clear()
            analyzing.clear()
            release.clear()
            lease = controller.start(meeting_id, "system")["captureId"]
            controller.media_ready(meeting_id, lease_id=lease)
            self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
            send(75, lease)
            self.assertTrue(analyzing.wait(1))

            cancelling_main, release_main = threading.Event(), threading.Event()
            self.addCleanup(release_main.set)

            def cancel_main(live):
                cancelling_main.set()
                release_main.wait(3)
                live.done.set()

            with (
                patch.object(FakeLive, "feed", side_effect=OSError("failed feed")),
                patch.object(FakeLive, "cancel", cancel_main),
            ):
                controller.feed_channels(meeting_id, silent_packet, packet, lease)
                self.assertTrue(cancelling_main.wait(1))
                self.assertTrue(cancellations[-1].is_set())
                release.set()
                self.assertTrue(closed.wait(1))
                self.assertEqual(
                    [turn["speaker"] for turn in controller.state()["partialTurns"]],
                    [SYSTEM_AUDIO],
                )
                release_main.set()
                self.wait_for(lambda: controller.state()["active"] is None)
            controller.release_media(lease)
            self.assertEqual(controller.get(meeting_id)["status"], "interrupted")

    def test_optional_speaker_write_checks_checkpoint_revision_and_lease(self):
        store = self.controller.store
        meeting = store.create()["id"]
        store.capture_state(meeting, "recording")
        store.checkpoint(meeting, 0, 1, "Mixed.")
        turns = [{"start": 0.0, "end": 1.0, "text": "Mixed.", "speaker": 1}]
        revision = (0, 1, "Mixed.", [], turns)
        missed_lease = Mock(side_effect=(True, False))
        self.assertEqual(
            store.revise_speakers(
                meeting, [revision], missed_lease, status="recording"
            ),
            [],
        )
        self.assertNotIn("speaker", store.get(meeting)["segments"][0])
        with closing(store.connect()) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with self.assertRaises(sqlite3.OperationalError):
                store.revise_speakers(
                    meeting, [revision], lambda: True, status="recording"
                )
        self.assertEqual(
            store.revise_speakers(
                meeting, [revision], lambda: True, status="recording"
            ),
            [True],
        )
        self.assertEqual(
            store.revise_speakers(
                meeting, [revision], lambda: True, status="recording"
            ),
            [False],
        )
        self.assertEqual(store.get(meeting)["segments"], turns)

    def test_recovered_turns_arrive_while_main_transcript_keeps_recording(self):
        controller = self.controller
        tap = Mock()
        pcm = b"\x11\x22" * (MAX_CHUNK // 2)
        packet = base64.b64encode(bytes(len(pcm))).decode()
        marker = b"\x33\x44" * 4
        packet_index = 0

        def mix(_mic):
            nonlocal packet_index
            signal = (
                (marker + pcm[len(marker) :])
                if packet_index in (0, 44, 88, 132, 176, 200)
                else pcm
            )
            packet_index += 1
            return signal, signal, len(signal) // 2, True

        tap.mix.side_effect = mix
        controller.loopback = True
        controller.system_audio = lambda: tap
        mixed = "The mixed phrase keeps going."
        first = {"start": 0.6, "end": 1.5, "text": mixed, "overlap": True, "speaker": 1}
        other = {
            "start": 0.7,
            "end": 1.6,
            "text": "A second complete phrase.",
            "overlap": True,
            "speaker": 2,
        }
        decode_entered, release = threading.Event(), threading.Event()
        pause_entered, finish_pause = threading.Event(), threading.Event()
        main_updates = 0
        recognizer = Mock()

        def voices(window):
            result = []
            offset = window.find(marker)
            while offset >= 0:
                start = offset * 1000 // (2 * RATE)
                result.extend(
                    (
                        Voice(start + 200, start + 1500, 1),
                        Voice(start + 550, start + 1650, 2),
                    )
                )
                offset = window.find(marker, offset + len(marker))
            return result

        recognizer.voices.side_effect = voices
        isolated_session = object()
        main_tokens = tuple(
            TimedToken(600 + i * 120, 720 + i * 120, word.encode())
            for i, word in enumerate(mixed.split())
        )

        class Primary(FakeLive):
            def feed(self, chunk, **kwargs):
                nonlocal main_updates
                self.samples += len(chunk) // 2
                main_updates += 1
                self.publish(
                    LiveResult(mixed, mixed, False, self.samples / RATE, main_tokens)
                )

            def finish(self, **_options):
                return LiveResult(mixed, mixed, True, self.samples / RATE, main_tokens)

        def compute(_sep, _emb, decoder, _language, _budget, clip):
            self.assertIs(decoder, isolated_session)
            decode_entered.set()
            self.assertTrue(release.wait(2))
            if 14 < clip.start < 15:
                pause_entered.set()
                self.assertTrue(finish_pause.wait(2))
            offset = clip.start - 0.2
            return [
                {**turn, "start": turn["start"] + offset, "end": turn["end"] + offset}
                for turn in (first, other)
            ]

        class LocalMicrophone(FakeLive):
            tokens = (TimedToken(600, 800, b"Local."),)

            def feed(self, chunk, **_options):
                self.samples += len(chunk) // 2
                self.publish(self.result(final=False))

            def finish(self, **_options):
                return self.result(final=True)

            def result(self, *, final):
                return LiveResult(
                    "Local.", "Local.", final, self.samples / RATE, self.tokens
                )

        decoder = Mock(return_value=nullcontext(isolated_session))

        def isolated(_cancel, *, live_tokens=False):
            if live_tokens:
                return nullcontext(lambda _language, publish: LocalMicrophone(publish))
            return decoder(_cancel)

        controller.backend = lambda: SimpleNamespace(
            reserve_live=lambda **_options: nullcontext(
                lambda _language, publish: Primary(publish)
            ),
            verified_library=object(),
            isolated_decoder=isolated,
        )
        meeting_id = controller.create()["id"]
        with (
            patch.object(controller, "overlap_ready", return_value=True),
            patch.object(controller, "speakers_ready", return_value=True),
            patch.object(controller.speaker_assets, "verify"),
            patch.object(controller.overlap_assets, "verify"),
            patch.object(
                controller.overlap_embedding_assets, "available", return_value=False
            ),
            patch(
                "clarify.desktop.meeting_source_labels.Sortformer.open",
                return_value=nullcontext(recognizer),
            ),
            patch.object(meeting_overlap, "pressure_normal", return_value=True),
            patch.object(meeting_overlap, "Separator"),
            patch.object(meeting_overlap, "_recover_clip", side_effect=compute),
        ):
            lease = controller.start_with_overlap(meeting_id, "system")["captureId"]
            controller.media_ready(meeting_id, lease_id=lease)
            self.wait_for(lambda: controller.state()["active"]["status"] == "recording")
            try:
                for i in range(30):
                    controller.feed(meeting_id, packet, lease_id=lease)
                    self.wait_for(lambda: main_updates >= i + 1)
                self.assertTrue(decode_entered.wait(1))
                for i in range(30, 35):
                    controller.feed(meeting_id, packet, lease_id=lease)
                    self.wait_for(lambda: main_updates >= i + 1)
                self.assertEqual(controller.state()["partial"], f"Local. {mixed}")
                self.assertFalse(controller.get(meeting_id)["segments"])
                release.set()
                self.wait_for(lambda: controller.state()["overlapRevision"] == 1)
                self.assertEqual(controller.state()["active"]["status"], "recording")
                self.assertEqual(
                    [row["text"] for row in controller.state()["projectedPartial"]],
                    ["Local."],
                )
                live = controller.get(meeting_id)
                self.assertEqual(live["segments"], [first, other])
                self.assertEqual(
                    controller.name_speaker(meeting_id, 1, "Participant A")["speakers"],
                    {1: "Participant A"},
                )

                def feed_until(count):
                    while packet_index < count:
                        target = packet_index + 1
                        controller.feed(meeting_id, packet, lease_id=lease)
                        self.wait_for(lambda: main_updates >= target)

                for revision, count in enumerate((75, 119, 163), start=2):
                    feed_until(count)
                    self.wait_for(
                        lambda: controller.state()["overlapRevision"] == revision
                    )
                    self.assertEqual(
                        controller.state()["active"]["status"], "recording"
                    )
                live = controller.get(meeting_id)
                recovered = [row for row in live["segments"] if row.get("overlap")]
                self.assertEqual(len(recovered), 8)
                for index in range(0, len(recovered), 2):
                    self.assertEqual(
                        [row["speaker"] for row in recovered[index : index + 2]], [1, 2]
                    )
                feed_until(200)
                self.assertTrue(pause_entered.wait(1))
                controller.pause(meeting_id)
                tap.close.assert_called_once()
                controller.release_media(lease)
                self.assertEqual(controller.state()["active"]["status"], "finalizing")
                finish_pause.set()
                self.wait_for(
                    lambda: controller.state()["active"]["status"] == "paused"
                )
                self.assertFalse(controller.overlap_context.clips)
                self.assertFalse(controller.overlap_context.blocks)
                paused = [
                    row
                    for row in controller.get(meeting_id)["segments"]
                    if row.get("overlap")
                ]
                self.assertEqual(paused[:8], recovered)
                self.assertEqual(len(paused), 10)

                previous_lease = lease
                lease = controller.resume(meeting_id)["captureId"]
                self.assertNotEqual(lease, previous_lease)
                controller.media_ready(meeting_id, lease_id=lease)
                self.wait_for(
                    lambda: controller.state()["active"]["status"] == "recording"
                )
                feed_until(232)
                self.wait_for(lambda: controller.state()["overlapRevision"] == 6)
                recovered = [
                    row
                    for row in controller.get(meeting_id)["segments"]
                    if row.get("overlap")
                ]
                self.assertEqual(recovered[:10], paused)
                self.assertEqual(len(recovered), 12)
                self.assertGreater(recovered[10]["start"], paused[-1]["end"])
                controller.stop(meeting_id)
                controller.release_media(lease)
                self.wait_for(lambda: controller.state()["active"] is None)
            finally:
                release.set()
                finish_pause.set()
        saved = MeetingStore(self.path).get(meeting_id)
        self.assertEqual(
            [row for row in saved["segments"] if row.get("overlap")], recovered
        )
        self.assertEqual(saved["speakers"], {1: "Participant A"})
        local_turns = [row for row in saved["segments"] if row.get("source") == "mic"]
        original_local = [
            row for row in saved["originalSegments"] if row.get("source") == "mic"
        ]
        self.assertTrue(local_turns)
        self.assertEqual(local_turns, original_local)
        self.assertEqual(tap.close.call_count, 2)
        self.assertEqual(decoder.call_count, 2)

    def test_optional_overlap_deadline_cannot_hold_the_meeting(self):
        meeting = self.controller.create()
        meeting_id = meeting["id"]
        candidates = meeting_overlap.OverlapCandidates()
        candidates.clips.append(meeting_overlap.OverlapClip(0, 2, b"pcm"))
        capture = self.controller.capture = Capture(
            meeting_id, "en", 0, "draft", overlap=candidates
        )
        self.controller.active = self.controller.store.capture_state(
            meeting_id, "finalizing"
        )
        self.controller.store.checkpoint(meeting_id, 0, 2, "Verified mixed transcript.")
        release = threading.Event()

        def stalled(*_args):
            release.wait(1)
            return {
                "turns": [{"start": 1, "end": 2, "text": "Discard the late result."}],
                "blocks": {},
            }

        try:
            with (
                patch.object(meeting_overlap, "recover", side_effect=stalled),
                patch.object(meeting_overlap, "pressure_normal", return_value=True),
                patch.object(meeting_overlap, "MAX_SECONDS", 0.03),
            ):
                result = self.controller._recover_overlap(
                    capture, lambda _: nullcontext(Mock())
                )
            self.assertIsNone(result)
            self.assertTrue(self.controller.overlap_worker.is_alive())
            self.controller._complete_capture(capture, (), True, "", result)
            saved = self.controller.get(meeting_id)
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(saved["segments"][0]["text"], "Verified mixed transcript.")
            self.assertNotIn("originalSegments", saved)
        finally:
            release.set()
            if self.controller.overlap_worker:
                self.controller.overlap_worker.join(timeout=1)

    def test_cancel_while_opening_system_tap_closes_late_handle(self):
        opening, finish_open = threading.Event(), threading.Event()
        tap = Mock()

        def open_tap():
            opening.set()
            self.assertTrue(finish_open.wait(2))
            return tap

        self.controller.system_audio = open_tap
        self.controller.loopback = True
        meeting = self.controller.create()["id"]
        admission = self.controller.start(meeting, "system")
        self.controller.media_ready(meeting, "", admission["captureId"])
        try:
            self.assertTrue(opening.wait(2))
            self.controller.release_media(admission["captureId"])
            self.controller.stop(meeting)
        finally:
            finish_open.set()
        self.wait_for(lambda: self.controller.state()["active"] is None)
        tap.close.assert_called_once_with()
        tap.mix.assert_not_called()
        self.assertEqual(self.controller.get(meeting)["status"], "draft")

    def test_pause_resume_stop_preserves_notes_and_separate_timestamps(self):
        meeting_id = self.controller.create()["id"]
        self.controller.save(
            meeting_id, {"title": "100% complete", "notes": "Keep this."}
        )
        admission = self.controller.start(meeting_id, "mic")
        self.begin_audio(meeting_id)
        with self.assertRaisesRegex(MeetingError, "capture_busy"):
            self.controller.delete(meeting_id)
        self.controller.pause(meeting_id)
        self.controller.release_media(admission["captureId"])
        self.wait_for(lambda: self.controller.get(meeting_id)["status"] == "paused")
        with self.assertRaisesRegex(MeetingError, "capture_unavailable"):
            self.controller.feed(meeting_id, "AAE=")
        admission = self.controller.resume(meeting_id)
        self.begin_audio(meeting_id)
        self.controller.stop(meeting_id)
        self.controller.release_media(admission["captureId"])
        self.wait_for(lambda: self.controller.state()["active"] is None)
        saved = MeetingStore(self.path).get(meeting_id)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["summary"], "")
        self.summarize.assert_not_called()
        self.assertEqual(saved["notes"], "Keep this.")
        self.assertEqual(
            saved["segments"],
            [
                {"start": 0.0, "end": 0.08, "text": "A decision."},
                {"start": 0.08, "end": 0.16, "text": "A decision."},
            ],
        )
        self.assertEqual(
            [row["id"] for row in self.controller.list("100%", 0)], [meeting_id]
        )
        self.assertEqual(self.controller.list("100_", 0), [])
        self.controller.delete(meeting_id)
        self.assertIsNone(MeetingStore(self.path).get(meeting_id))

    def test_startup_recovers_capture_checkpoint_after_interrupted_process(self):
        store = MeetingStore(self.path)
        meeting_id = store.create()["id"]
        store.capture_state(meeting_id, "recording")
        store.checkpoint(meeting_id, 0, 1, "Meeting text.")
        recovered = MeetingStore(self.path).get(meeting_id)
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(recovered["error"], "capture_interrupted")
        self.assertEqual(
            recovered["segments"], [{"start": 0.0, "end": 1.0, "text": "Meeting text."}]
        )

    def test_cancel_start_keeps_the_draft_available_for_another_attempt(self):
        opened = threading.Event()
        cancel_requested = threading.Event()
        live = FakeLive(lambda _: None)
        live.ready.clear()
        live.cancel = cancel_requested.set

        def open_session(_language, _publish):
            opened.set()
            return live

        self.controller.backend = lambda: SimpleNamespace(
            reserve_live=lambda **_options: nullcontext(open_session)
        )
        self.addCleanup(live.done.set)
        meeting_id = self.controller.create()["id"]
        admission = self.controller.start(meeting_id, "mic")
        self.assertTrue(opened.wait(2))
        self.controller.stop(meeting_id)
        self.controller.release_media(admission["captureId"])
        self.assertTrue(cancel_requested.wait(2))
        self.assertTrue(self.controller.busy)
        with self.assertRaisesRegex(MeetingError, "capture_busy"):
            self.controller.start(meeting_id, "mic")
        live.done.set()
        self.wait_for(lambda: self.controller.state()["active"] is None)
        saved = self.controller.get(meeting_id)
        self.assertEqual(saved["status"], "draft")
        self.assertIsNone(saved["startedAt"])
        self.assertEqual(saved["segments"], [])

    def test_windows_cancel_while_loading_second_engine_preserves_status(self):
        controller = self.controller
        controller.loopback = True
        opening = threading.Event()

        @contextmanager
        def open_sibling(cancel, **_options):
            opening.set()
            self.assertTrue(cancel.wait(2))
            raise LocalASRCancelledError("Recognition was cancelled")
            yield

        controller.backend = lambda: SimpleNamespace(
            reserve_live=lambda **_options: nullcontext(
                lambda _language, publish: FakeLive(publish)
            ),
            isolated_decoder=open_sibling,
        )
        with (
            patch.object(meetings, "sys", SimpleNamespace(platform="win32")),
            patch.object(meetings, "windows_cpu_count", return_value=4),
        ):
            for previous in ("draft", "paused"):
                with self.subTest(previous=previous):
                    opening.clear()
                    meeting_id = controller.create()["id"]
                    if previous == "paused":
                        controller.active = controller.store.capture_state(
                            meeting_id, "paused", source="system"
                        )
                        admission = controller.resume(meeting_id)
                    else:
                        admission = controller.start(meeting_id, "system")
                    lease = admission["captureId"]
                    controller.media_ready(meeting_id, lease_id=lease)
                    self.assertTrue(opening.wait(2))
                    controller.stop(meeting_id)
                    controller.release_media(lease)
                    self.wait_for(lambda: controller.capture is None)
                    saved = controller.get(meeting_id)
                    self.assertEqual(saved["status"], previous)
                    self.assertEqual(saved["error"], "")
                    self.assertEqual(saved["segments"], [])

    def test_summary_does_not_overwrite_a_later_edit(self):
        ready, release = threading.Event(), threading.Event()

        def summarize(*_):
            ready.set()
            release.wait(2)
            return "Generated summary."

        self.summarize = summarize
        meeting_id = self.controller.create()["id"]
        self.controller.save(meeting_id, {"notes": "Signed off."})
        self.controller.generate(meeting_id, "decisions")
        self.assertTrue(ready.wait(2))
        with self.assertRaisesRegex(MeetingError, "summary_busy"):
            self.controller.start(meeting_id, "mic")
        self.controller.save(meeting_id, {"summary": "Hand-written summary."})
        release.set()
        self.wait_for(lambda: self.controller.state()["generating"] is None)
        self.assertEqual(
            self.controller.state()["summaryError"],
            {"id": meeting_id, "code": "summary_changed"},
        )
        self.assertEqual(
            self.controller.get(meeting_id)["summary"], "Hand-written summary."
        )

    def test_stop_and_generate_reads_final_saved_transcript_and_notes(self):
        meeting_id = self.controller.create()["id"]
        self.controller.save(meeting_id, {"title": "Decision", "notes": "Keep this."})
        admission = self.controller.start(meeting_id, "mic")
        self.begin_audio(meeting_id)
        self.assertTrue(self.controller.state()["summaryAvailable"])
        self.summarize.return_value = "## Decisions\n\nA decision."
        self.controller.stop_and_generate(meeting_id, "decisions")
        self.controller.release_media(admission["captureId"])
        self.wait_for(lambda: self.controller.get(meeting_id)["summary"])
        template, source, _ = self.summarize.call_args.args
        self.assertEqual(template, "decisions")
        self.assertEqual(source["status"], "completed")
        self.assertEqual(source["notes"], "Keep this.")
        self.assertEqual(source["segments"][0]["text"], "A decision.")
        saved = MeetingStore(self.path).get(meeting_id)
        self.assertEqual(saved["summary"], "## Decisions\n\nA decision.")
        self.assertEqual(saved["notes"], "Keep this.")

    def test_stop_from_pause_saves_locally_if_route_disappears_or_fails(self):
        for expected in ("summary_setup", "summary_failed"):
            with self.subTest(expected=expected):
                meeting_id = self.controller.create()["id"]
                self.controller.save(meeting_id, {"notes": "Keep this."})
                admission = self.controller.start(meeting_id, "mic")
                self.begin_audio(meeting_id)
                self.controller.pause(meeting_id)
                self.controller.release_media(admission["captureId"])
                self.wait_for(
                    lambda: self.controller.get(meeting_id)["status"] == "paused"
                )
                self.summarize.reset_mock(side_effect=True)
                self.summarize.side_effect = OSError("fake provider unavailable")
                self.controller.summary_provider = (
                    (lambda: None)
                    if expected == "summary_setup"
                    else (lambda: self.summarize)
                )
                self.controller.stop_and_generate(meeting_id, "brief")
                self.wait_for(
                    lambda: (
                        self.controller.state()["summaryError"]
                        == {"id": meeting_id, "code": expected}
                    )
                )
                self.assertEqual(
                    self.summarize.call_count, int(expected == "summary_failed")
                )
                saved = MeetingStore(self.path).get(meeting_id)
                self.assertEqual(saved["status"], "completed")
                self.assertEqual(saved["notes"], "Keep this.")
                self.assertEqual(saved["summary"], "")
                self.assertTrue(saved["segments"])

    def test_failed_final_checkpoint_and_status_recover_without_restart(self):
        meeting_id = self.controller.create()["id"]
        admission = self.controller.start(meeting_id, "mic")
        self.begin_audio(meeting_id)
        store = self.controller.store
        checkpoint = store.checkpoint
        capture_state = store.capture_state

        def full_disk(*_args):
            raise sqlite3.OperationalError("disk is full")

        def unavailable_status(identifier, status, **kwargs):
            if status == "interrupted":
                full_disk()
            return capture_state(identifier, status, **kwargs)

        store.checkpoint = full_disk
        store.capture_state = unavailable_status
        self.controller.stop(meeting_id)
        self.wait_for(lambda: self.controller.state()["active"] is None)
        self.assertTrue(self.controller.busy)
        self.controller.release_media("stale attempt")
        self.assertTrue(self.controller.busy)
        self.controller.release_media(admission["captureId"])
        self.assertFalse(self.controller.busy)
        self.assertEqual(self.controller.get(meeting_id)["status"], "interrupted")
        self.assertEqual(store.get(meeting_id)["status"], "finalizing")
        store.checkpoint, store.capture_state = checkpoint, capture_state
        self.assertEqual(
            self.controller.get(meeting_id)["error"], "meeting_storage_failed"
        )
        self.assertEqual(store.get(meeting_id)["status"], "interrupted")
        self.assertEqual(store.get(meeting_id)["segments"][0]["text"], "A decision.")

    def test_summary_accepts_explicit_loopback_and_rejects_public_provider(self):
        config = AppConfig()
        calls = []

        def rewrite(request, connection, _cancel):
            calls.append((request, connection))
            return SimpleNamespace(text="The team signed off.")

        adapter = SimpleNamespace(rewrite=rewrite)
        meeting = {"title": "Release", "notes": "Signed off.", "segments": []}
        cancel = CancellationToken()
        self.assertIsNone(configured_summary(None, config))
        self.assertEqual(calls, [])
        local = replace(
            config,
            workflows=config.workflows.with_route(
                WorkflowScope.REFINEMENT,
                WorkflowRoute(
                    model_id="local-test", custom_endpoint="http://127.0.0.1:11434/v1"
                ),
            ),
        )
        self.assertIsNotNone(configured_summary(None, local))
        self.assertEqual(
            local_summary(
                adapter,
                "http://127.0.0.1:11434/v1",
                "local-test",
                "brief",
                meeting,
                cancel,
            ),
            "The team signed off.",
        )
        request, connection = calls[0]
        self.assertIn("Signed off.", request.source_message)
        self.assertEqual(connection.base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(connection.api_key, "")
