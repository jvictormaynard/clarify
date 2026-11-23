"""Durable live claims share WAV admission, cancellation and publication."""

import base64
import hashlib
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from computer_live import ComputerLivePeer
from tests.support.computer_host import ComputerHostFixture


class Native:
    def __init__(self, callback):
        self.callback = callback
        self.pcm = bytearray()
        self.cancel = Mock()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def feed(self, pcm):
        self.pcm.extend(pcm)
        self.callback(SimpleNamespace(text="Partial", final=False))

    def finish(self, **options):
        self.entered.set()
        self.release.wait(3)
        return SimpleNamespace(text="Raw words", received_seconds=len(self.pcm) / 32000)


class LiveHostTests(ComputerHostFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        _, session = self.pair()
        self.auth = "Bearer " + session["session_token"]
        self.device = session["device_id"]
        self.native = None

        def open_live_session(language, on_result):
            self.native = Native(on_result)
            return self.native

        self.engine = SimpleNamespace(
            open_live_session=Mock(side_effect=open_live_session)
        )
        self.processor.require_live = Mock()
        self.processor.live_engine = Mock(return_value=self.engine)
        self.processor.process_dictation = Mock(
            return_value={
                "transcript": "Raw words",
                "text": "Edited words",
                "rewritten": True,
                "successful": True,
            }
        )
        self.peer = ComputerLivePeer(self.host)
        self.addCleanup(self.peer.close)
        self.op = self.operation()
        self.pcm = b"\1\0" * 160

    def call(self, action, body=None, op=None):
        return self.peer(self.auth, action, op or self.op, body)

    def feed(self):
        return self.call(
            "feed", {"sequence": 0, "data": base64.b64encode(self.pcm).decode()}
        )

    def finish(self):
        return self.call(
            "finish",
            {"sha256": hashlib.sha256(self.pcm).hexdigest(), "bytes": len(self.pcm)},
        )

    def test_final_reuses_frozen_workflow_and_duplicate_finish_never_republishes(self):
        self.assertEqual(self.call("start", {"language": "en"})["status"], 200)
        self.assertEqual(self.feed()["body"]["partial"], "Partial")
        frame = base64.b64encode(self.pcm).decode()
        batched = self.call(
            "feed",
            {
                "frames": [
                    {"sequence": 1, "data": frame},
                    {"sequence": 2, "data": frame},
                ]
            },
        )
        self.assertEqual(batched["status"], 200)
        self.assertEqual(batched["body"], {"accepted": 2})
        self.pcm *= 3
        final = self.finish()
        self.assertEqual(final["body"]["text"], "Edited words")
        self.assertEqual(self.finish(), final)
        self.processor.process_dictation.assert_called_once()
        args, kwargs = self.processor.process_dictation.call_args
        self.assertTrue(args[0].startswith(b"RIFF"))
        self.assertEqual(kwargs["pretranscribed"].text, "Raw words")
        self.assertEqual(self.call("start", {"language": "pt"})["status"], 409)

    def test_real_processor_uses_final_raw_text_without_transcribing_again(self):
        from computer_processing import ComputerProcessor
        from dictionary_snippets import (
            DictionarySnippets,
            DictionarySnippetService,
            InMemoryDictionarySnippetsRepository,
        )
        from repositories import AppConfig
        from provider_registry import PROVIDER_REGISTRY
        from unittest.mock import patch

        config = AppConfig.from_mapping(
            {
                "transcription_provider": "local_asr",
                "local_asr_model": "nemotron-3.5-streaming",
                "dictation_cleanup_level": "preserve",
            }
        )
        processor = ComputerProcessor(
            SimpleNamespace(current=lambda: config),
            DictionarySnippetService(
                InMemoryDictionarySnippetsRepository(DictionarySnippets())
            ),
        )
        processor.live_engine = self.processor.live_engine
        self.host.processor = processor
        with patch.object(
            PROVIDER_REGISTRY,
            "transcribe",
            side_effect=AssertionError("Must not transcribe twice"),
        ):
            self.assertEqual(self.call("start", {"language": "en"})["status"], 200)
            self.feed()
            result = self.finish()
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["body"]["transcript"], "Raw words")
        self.assertEqual(result["body"]["text"], "Raw words")

    def test_capacity_rejected_before_loading_and_revoke_cancels_capture(self):
        self.call("start", {"language": "en"})
        self.feed()
        # Exhaust admission without opening additional model sessions.
        acquired = []
        while self.host._capacity.acquire(False):
            acquired.append(True)
        try:
            self.assertEqual(
                self.call("start", {"language": "en"}, self.operation())["status"], 429
            )
            self.processor.live_engine.assert_called_once()
        finally:
            for _ in acquired:
                self.host._capacity.release()
        self.host.revoke_device(self.device)
        self.assertTrue(self.peer.sessions[(self.device, self.op)].done.wait(2))
        self.assertFalse(self.host._running)
        self.processor.process_dictation.assert_not_called()

    def test_pre_admission_rejections_never_open_model(self):
        self.call("cancel")
        self.assertEqual(self.call("start", {"language": "en"})["status"], 409)
        self.processor.live_engine.assert_not_called()
        self.assertEqual(
            self.call("start", {"language": "en", "unknown": True}, self.operation())[
                "status"
            ],
            400,
        )
        self.processor.live_engine.assert_not_called()

    def test_mismatch_and_pressure_cancel_claim(self):
        for bad in (
            {"sha256": "wrong", "bytes": 320},
            {"sequence": 0, "data": "A" * 4000},
            {"frames": []},
            {"frames": [{"sequence": 1, "data": "AA=="}] * 9},
        ):
            self.op = self.operation()
            self.assertEqual(self.call("start", {"language": "en"})["status"], 200)
            self.feed()
            self.assertEqual(
                self.call("finish" if "sha256" in bad else "feed", bad)["status"], 400
            )
            self.assertTrue(self.peer.sessions[(self.device, self.op)].done.wait(2))
        self.processor.process_dictation.assert_not_called()

    def test_cancellation_during_final_and_revocation_suppress_result(self):
        for revoke in (False, True):
            self.op = self.operation()
            self.assertEqual(self.call("start", {"language": "en"})["status"], 200)
            self.feed()
            self.native.release.clear()
            result = []
            thread = threading.Thread(target=lambda: result.append(self.finish()))
            thread.start()
            self.assertTrue(self.native.entered.wait(2))
            if revoke:
                self.host.revoke_device(self.device)
            else:
                self.call("cancel")
            self.native.release.set()
            thread.join(3)
            self.assertEqual(result[0]["status"], 401 if revoke else 409)
        self.processor.process_dictation.assert_not_called()

    def test_native_receipt_mismatch_cannot_enter_workflow(self):
        self.call("start", {"language": "en"})
        self.feed()
        self.native.finish = lambda **kwargs: SimpleNamespace(
            text="Wrong audio", received_seconds=0
        )
        self.assertEqual(self.finish()["status"], 502)
        self.processor.process_dictation.assert_not_called()

    def test_cancel_after_processing_before_publication_discards_final(self):
        self.call("start", {"language": "en"})
        self.feed()
        original = self.processor.process_dictation.return_value

        def process(*args, **kwargs):
            self.host._cancel(self.device, self.op)
            return original

        self.processor.process_dictation.side_effect = process
        self.assertEqual(self.finish()["status"], 409)
        self.assertNotIn((self.device, self.op), self.host._results)

    def test_host_stop_cancels_capture_and_drains_native_worker(self):
        self.call("start", {"language": "en"})
        self.feed()
        self.host.stop()
        self.peer.close()
        self.assertFalse(self.host._running)
        self.native.cancel.assert_called()
        self.processor.process_dictation.assert_not_called()

    def test_close_cancels_idle_claim_and_rejects_output(self):
        self.call("start", {"language": "en"})
        self.feed()
        self.peer.close()
        self.assertEqual(self.call("partial")["status"], 410)
        self.assertFalse(self.host._running)
        self.native.cancel.assert_called()
        self.processor.process_dictation.assert_not_called()
