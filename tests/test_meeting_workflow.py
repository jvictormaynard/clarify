import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import contextmanager

from meeting_provider import MeetingProviderService
from meeting_store import MeetingStore
from meeting_workflow import MeetingWorkflow
from provider_types import ProviderConnection
from shared.meeting_contract import MeetingError, MeetingIdentity
from workflow_config import WorkflowRoute


def wait_for(predicate):
    until = time.monotonic() + 3
    while not predicate() and time.monotonic() < until:
        time.sleep(0.01)
    if not predicate():
        raise AssertionError("fixture worker did not reach expected state")


class FakeProvider:
    def __init__(self):
        self.current = MeetingIdentity("guest", 0, False)
        self.acquire = Mock()
        self.release = Mock()
        self.snapshot = Mock(return_value=None)
        self.calls = []
        self.entered = threading.Event()
        self.resume = threading.Event()
        self.delayed = False
        self.failure = False

    def identity(self):
        return self.current

    def validate(self, expected):
        if expected != self.current:
            raise MeetingError("meeting.scope_changed")

    @contextmanager
    def publication(self, expected):
        self.validate(expected)
        yield

    def transcribe(self, expected, routes, chunk, path, language, cancel):
        self.calls.append((chunk["operation_id"], language))
        self.entered.set()
        if self.delayed:
            self.resume.wait(3)
        if self.failure:
            raise TimeoutError("uncertain provider failure")
        return "Original speech"

    def summarize(self, *args):
        self.entered.set()
        if self.delayed:
            self.resume.wait(3)
        return "New summary"


class FakeCapture:
    last = None

    def __init__(self, store, owner, mid, **kwargs):
        FakeCapture.last = self
        self.alive = False
        self.closed = False

    def start(self):
        self.alive = True

    def stop(self):
        self.alive = False
        self.closed = True

    def snapshot(self):
        return {}


class MeetingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MeetingStore(self.temp.name)
        self.provider = FakeProvider()
        self.workflow = MeetingWorkflow(
            self.store,
            self.provider,
            source_factory=Mock(),
            capture_factory=FakeCapture,
        )
        self.addCleanup(self.workflow.shutdown)

    def pending(self, *, language="es"):
        row = self.store.create("guest", language=language)
        cid, path = self.store.open_chunk("guest", row["id"], "microphone", 0)
        path.write_bytes(b"synthetic fixture")
        self.store.finish_chunk("guest", row["id"], cid, 1000)
        self.store.end("guest", row["id"])
        self.workflow.selected = row["id"]
        return row["id"], cid, path

    def test_stop_closes_capture_even_while_transcription_is_blocked(self):
        self.provider.delayed = True
        self.workflow.start(language="pt")
        wait_for(lambda: self.workflow.phase == "recording")
        mid = self.workflow.selected
        cid, path = self.store.open_chunk("guest", mid, "microphone", 0)
        path.write_bytes(b"synthetic fixture")
        self.store.finish_chunk("guest", mid, cid, 1000)
        self.assertTrue(self.provider.entered.wait(2))
        self.workflow.stop()
        self.assertTrue(FakeCapture.last.closed)
        self.assertTrue(self.workflow.active)
        self.provider.resume.set()
        wait_for(lambda: not self.workflow.active)
        self.assertFalse(path.exists())
        self.provider.release.assert_called_once()

    def test_cancel_or_session_switch_rejects_late_result_and_retains_audio(self):
        for cancel in (True, False):
            mid, cid, path = self.pending()
            self.provider.entered.clear()
            self.provider.resume.clear()
            self.provider.delayed = True
            self.workflow.retry()
            self.assertTrue(self.provider.entered.wait(2))
            if cancel:
                self.workflow.cancel()
            else:
                self.provider.current = MeetingIdentity("guest", 1, False)
            self.provider.resume.set()
            wait_for(lambda: not self.workflow.active)
            self.assertTrue(path.exists())
            self.assertEqual(
                self.store.get("guest", mid)["chunks"][0]["transcript"], ""
            )

    def test_uncertain_retry_after_restart_keeps_operation_and_original_language(self):
        mid, cid, path = self.pending()
        self.provider.failure = True
        self.workflow.retry()
        wait_for(lambda: not self.workflow.active)
        self.assertTrue(path.exists())
        other = MeetingWorkflow(self.store, self.provider, source_factory=Mock())
        self.addCleanup(other.shutdown)
        other.selected = mid
        other.language = "en"
        self.provider.failure = False
        other.retry()
        wait_for(lambda: not other.active)
        self.assertEqual(self.provider.calls, [(cid, "es"), (cid, "es")])
        self.assertFalse(path.exists())

    def test_cancelled_summary_keeps_personal_note_and_previous_summary(self):
        mid, cid, path = self.pending()
        self.store.save_notes("guest", mid, "Manual note")
        op, rev, _ = self.store.summary_request("guest", mid)
        self.store.save_summary("guest", mid, rev, "Previous summary")
        self.provider.delayed = True
        self.workflow.summarize()
        self.assertTrue(self.provider.entered.wait(2))
        self.workflow.cancel()
        self.provider.resume.set()
        wait_for(lambda: not self.workflow.active)
        saved = self.store.get("guest", mid)
        self.assertEqual(
            (saved["notes"], saved["summary"]), ("Manual note", "Previous summary")
        )
        self.assertEqual(op, self.store.summary_request("guest", mid)[0])

    def test_stale_manual_notes_and_other_capture_cannot_start(self):
        mid, _, _ = self.pending()
        with self.assertRaises(MeetingError):
            self.workflow.save_notes(mid, "guest:old", "late note")
        self.workflow.can_start = lambda: False
        with self.assertRaises(MeetingError):
            self.workflow.start()
        self.provider.acquire.assert_not_called()

    def test_oversized_summary_preserves_all_source_and_previous_summary(self):
        mid, cid, _ = self.pending()
        self.store.save_notes("guest", mid, "personal")
        op, revision, _ = self.store.summary_request("guest", mid)
        self.store.save_summary("guest", mid, revision, "previous")
        self.store.save_transcript("guest", mid, cid, "A" * 32000)
        second, path = self.store.open_chunk("guest", mid, "system", 2000)
        self.store.finish_chunk("guest", mid, second, 1000)
        self.store.save_transcript("guest", mid, second, "B" * 32000)
        self.workflow.summarize()
        wait_for(lambda: not self.workflow.active)
        self.assertEqual(self.workflow.error, "meeting.too_large")
        saved = self.store.get("guest", mid)
        self.assertEqual(saved["summary"], "previous")
        self.assertEqual(sum(len(c["transcript"]) for c in saved["chunks"]), 64000)


class MeetingProviderTests(unittest.TestCase):
    def test_local_asr_has_no_key_and_routes_connections_are_fixed_per_job(self):
        account = Mock()
        service = Mock()
        route = WorkflowRoute(provider_id="local_asr", model_id="ggml-base")
        service._route.return_value = route
        connection = ProviderConnection(api_key="", base_url="")
        service._connection.return_value = connection
        service.registry.canonical_audio_model.side_effect = lambda provider, model: (
            model
        )
        provider = MeetingProviderService(service, account)
        provider.validate = Mock()
        expected = MeetingIdentity("guest", 0, False)
        routes = provider.snapshot(expected, notes=WorkflowRoute(enabled=False))
        service._route.return_value = WorkflowRoute(
            provider_id="groq", model_id="changed"
        )
        service.registry.transcribe.return_value = SimpleNamespace(text="speech")
        provider.transcribe(expected, routes, {}, Path("fixture.wav"), "pt", Mock())
        self.assertEqual(service.registry.transcribe.call_args.args[0], "local_asr")
        self.assertEqual(
            service.registry.transcribe.call_args.args[1].model, "ggml-base"
        )
        self.assertEqual(service._connection.call_count, 1)
        with self.assertRaises(MeetingError):
            provider.summarize(expected, routes, "op", "source", "pt", Mock())
        service.registry.rewrite.assert_not_called()
