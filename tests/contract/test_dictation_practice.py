"""Practice exercises the production workflow with fake audio and providers."""

import unittest
from itertools import product

from provider_types import TranscriptionResult
from tests.support.workflows import (
    FakeAudio,
    FakeClock,
    FakeConfig,
    FakeProvider,
    FakeStatistics,
    ImmediateScheduler,
    ManualScheduler,
)
from workflows import WorkflowService
from clarify.desktop.dictation_practice import (
    PracticeController,
    PracticeDestination,
)


class PracticeTests(unittest.TestCase):
    def setUp(self):
        self.audio = FakeAudio()
        self.provider = FakeProvider()
        self.statistics = FakeStatistics()
        self.reason = ""
        self.scheduler = ImmediateScheduler()
        self.make_practice()

    def make_practice(self):
        self.workflow = WorkflowService(
            self.provider,
            self.audio,
            PracticeDestination(),
            FakeConfig(),
            self.statistics,
            self.scheduler,
            FakeClock(),
        )
        self.practice = PracticeController(
            self.workflow,
            language=lambda: "pt",
            readiness=lambda: self.reason,
        )

    def test_open_is_optional_and_never_starts_capture(self):
        self.assertFalse(self.practice.snapshot()["open"])
        self.practice.command("open")
        self.assertTrue(self.practice.snapshot()["open"])
        self.assertEqual(self.audio.started, 0)
        self.assertFalse(hasattr(self.provider, "transcription_request"))
        self.practice.command("close")
        self.assertFalse(self.practice.snapshot()["open"])

    def test_real_workflow_delivers_only_to_practice_and_accounts_once(self):
        self.practice.command("open")
        self.practice.handle_hotkey("recording_hotkey")
        self.assertEqual(self.practice.snapshot()["phase"], "recording")
        self.practice.handle_hotkey("recording_hotkey")
        self.assertEqual(self.practice.snapshot()["text"], "Transcribed")
        self.assertEqual(len(self.statistics.dictations), 1)
        self.assertEqual(self.provider.transcription_request[1:], ("prompt", "pt"))
        self.assertIsNone(self.workflow._session.target)
        self.practice.command("close")
        self.practice.command("open")
        self.assertEqual(self.practice.snapshot()["text"], "")

    def test_each_readiness_failure_blocks_capture_and_can_recover(self):
        self.practice.command("open")
        for reason in (
            "practice_configuration",
            "practice_model",
            "practice_session",
            "practice_busy",
        ):
            self.reason = reason
            self.practice.command("start")
            self.assertEqual(self.practice.snapshot()["blocked"], reason)
            self.assertEqual(self.audio.started, 0)
        self.reason = ""
        self.practice.command("start")
        self.assertEqual(self.audio.started, 1)

    def test_missing_microphone_and_cancel_do_not_send_audio(self):
        self.practice.command("open")
        self.audio.available = False
        self.practice.command("start")
        self.assertEqual(self.practice.snapshot()["phase"], "microphone_unavailable")
        self.practice.command("cancel")
        self.audio.available = True
        self.practice.handle_hotkey("recording_hold_press")
        self.practice.handle_hotkey("escape")
        self.practice.handle_hotkey("recording_hold_release")
        self.assertEqual(self.practice.snapshot()["phase"], "ready")
        self.assertFalse(hasattr(self.provider, "transcription_request"))

    def test_close_while_processing_rejects_late_result_and_usage(self):
        self.scheduler = ManualScheduler()
        self.make_practice()
        self.practice.command("open")
        self.practice.command("start")
        self.scheduler.background.pop(0)()
        self.practice.command("stop")
        self.provider.on_transcribe = lambda: self.practice.command("close")
        self.scheduler.background.pop(0)()
        while self.scheduler.soon:
            self.scheduler.soon.pop(0)()
        while self.scheduler.background:
            self.scheduler.background.pop(0)()
        self.assertFalse(self.practice.snapshot()["open"])
        self.assertEqual(self.practice.snapshot()["text"], "")
        self.assertEqual(self.statistics.dictations, [])

    def test_review_failure_retains_useful_transcript_and_warning(self):
        self.provider.transcribe = lambda *_: TranscriptionResult(
            "Texto aproveitável.",
            "groq",
            "fake",
            raw_text="Texto aproveitável.",
            refinement_failed=True,
        )
        self.practice.command("open")
        self.practice.command("start")
        self.practice.command("stop")
        state = self.practice.snapshot()
        self.assertEqual(state["text"], "Texto aproveitável.")
        self.assertEqual(state["source"], "Texto aproveitável.")
        self.assertEqual(state["status"], "refinement_failed")

    def test_quota_and_expired_session_are_not_retried(self):
        from provider_types import ProviderError

        for code in ("quota", "authentication"):
            self.practice.command("open")
            error = ProviderError("fake", "test failure")
            error.code = code
            self.provider.on_transcribe = lambda: (_ for _ in ()).throw(error)
            self.practice.command("start")
            self.practice.command("stop")
            self.assertEqual(self.practice.snapshot()["status"], f"provider_{code}")
            self.assertEqual(self.statistics.dictations, [])
            self.practice.command("close")

    def test_other_hotkeys_are_consumed_until_practice_closes(self):
        self.assertFalse(self.practice.handle_hotkey("rewrite_hotkey"))
        self.practice.command("open")
        for action in (
            "rewrite_hotkey",
            "translation_hotkey",
            "voice_translation_hotkey",
        ):
            self.assertTrue(self.practice.handle_hotkey(action))
        self.assertEqual(self.audio.started, 0)

    def test_another_workflow_cannot_be_interrupted_by_opening_practice(self):
        self.practice.can_open = lambda: False
        self.assertFalse(self.practice.command("open"))
        self.assertFalse(self.practice.snapshot()["open"])
        self.assertFalse(self.practice.handle_hotkey("recording_hotkey"))

    def test_close_reopen_and_account_generation_never_restore_old_result(self):
        for identity in (
            ("server", "account-a", 1),
            None,
            ("server", "account-b", 2),
            ("server", "account-a", 3),
        ):
            self.practice.identity = lambda identity=identity: identity
            self.practice.command("open")
            self.assertEqual(self.practice.snapshot()["text"], "")
            self.assertEqual(self.practice.snapshot()["source"], "")
            self.practice.command("start")
            self.practice.command("stop")
            self.assertEqual(self.practice.snapshot()["text"], "Transcribed")
            self.practice.command("close")
        self.assertEqual(len(self.statistics.dictations), 4)

    def test_identity_change_during_job_suppresses_late_text_and_accounting(self):
        identity = ["account-a-session-1"]
        self.practice.identity = lambda: identity[0]
        self.practice.command("open")
        self.practice.command("start")

        def revoke():
            identity[0] = "account-a-session-2"
            self.practice.snapshot()

        self.provider.on_transcribe = revoke
        self.practice.command("stop")
        self.assertEqual(self.practice.snapshot()["text"], "")
        self.assertTrue(self.practice.snapshot()["open"])
        self.assertEqual(self.practice.snapshot()["blocked"], "practice_session")
        self.assertEqual(self.statistics.dictations, [])

    def test_reopen_during_accepted_publication_hides_previous_result_and_waits(self):
        record = self.statistics.record_dictation
        observed = []

        def publishing(*args):
            self.practice.command("close")
            self.practice.command("open")
            observed.append(self.practice.snapshot())
            record(*args)

        self.statistics.record_dictation = publishing
        self.practice.command("open")
        self.practice.command("start")
        self.practice.command("stop")
        self.assertEqual(observed[0]["text"], "")
        self.assertEqual(observed[0]["source"], "")
        self.assertEqual(observed[0]["blocked"], "practice_busy")
        self.assertEqual(self.practice.snapshot()["blocked"], "")
        self.assertEqual(len(self.statistics.dictations), 1)

    def test_repeat_waits_for_ready_and_revalidates_before_new_capture(self):
        for outcome in ("start", "close", "blocked", "identity"):
            self.setUp()
            self.scheduler = ManualScheduler()
            self.make_practice()
            self.practice.command("open")
            self.practice.command("start")
            self.scheduler.background.pop(0)()
            self.practice.command("stop")
            self.scheduler.background.pop(0)()
            while self.scheduler.soon:
                self.scheduler.soon.pop(0)()
            self.practice.command("start")
            self.assertEqual(self.practice.snapshot()["phase"], "waiting")
            self.assertEqual(self.audio.started, 1)
            if outcome == "close":
                self.practice.command("close")
            elif outcome == "blocked":
                self.reason = "practice_model"
            elif outcome == "identity":
                self.practice.identity = lambda: "new session"
            while self.scheduler.background:
                self.scheduler.background.pop(0)()
            while self.scheduler.soon:
                self.scheduler.soon.pop(0)()
            while self.scheduler.background:
                self.scheduler.background.pop(0)()
            self.assertEqual(self.audio.started, 2 if outcome == "start" else 1)
            self.assertLessEqual(len(self.statistics.dictations), 1)

    def test_real_account_codes_are_bounded_and_keep_unknown_errors_generic(self):
        from clarify_account import AccountError

        cases = (
            ("allowance_exhausted", "account_allowance_exhausted"),
            ("allocation_waiting", "account_allocation_waiting"),
            ("authentication_required", "account_authentication_required"),
            ("untrusted diagnosis", "error"),
            (None, "error"),
            ([], "error"),
        )
        for code, expected in cases:
            self.practice.command("open")
            error = AccountError("private diagnostic must not be displayed", code=code)
            self.provider.on_transcribe = lambda: (_ for _ in ()).throw(error)
            self.practice.command("start")
            self.practice.command("stop")
            self.assertEqual(self.practice.snapshot()["status"], expected)
            self.assertEqual(self.statistics.dictations, [])
            self.practice.command("close")

    def test_close_after_completion_does_not_queue_an_old_recorder_cancel(self):
        self.practice.command("open")
        self.practice.command("start")
        self.practice.command("stop")
        self.scheduler = ManualScheduler()
        self.workflow._scheduler = self.scheduler
        self.practice.command("close")
        self.assertEqual(self.scheduler.background, [])
        # A later capture can start before any queued UI callbacks are drained.
        self.practice.command("open")
        self.practice.command("start")
        while self.scheduler.soon:
            self.scheduler.soon.pop(0)()
        while self.scheduler.background:
            self.scheduler.background.pop(0)()
        self.assertEqual(self.audio.started, 2)
        self.assertEqual(self.audio.cancelled, 0)

    def test_unaccepted_publication_is_discarded_on_close_cancel_or_identity_change(
        self,
    ):
        for delivered, boundary in product(
            (False, True), ("close", "cancel", "identity")
        ):
            self.setUp()
            self.scheduler = ManualScheduler()
            self.make_practice()
            identity = ["session-a"]
            self.practice.identity = lambda: identity[0]
            self.practice.command("open")
            self.practice.command("start")
            self.scheduler.background.pop(0)()
            self.practice.command("stop")
            self.scheduler.background.pop(0)()
            # COMPLETED exists; delivery has not yet accepted publication.
            self.assertEqual(self.workflow.state.phase.value, "completed")
            if delivered:
                while self.scheduler.soon:
                    self.scheduler.soon.pop(0)()
            if boundary == "identity":
                identity[0] = "session-b"
                self.practice.snapshot()
            else:
                self.practice.command(boundary)
            while self.scheduler.soon:
                self.scheduler.soon.pop(0)()
            while self.scheduler.background:
                self.scheduler.background.pop(0)()
            self.assertEqual(self.statistics.dictations, [])
            self.assertEqual(self.audio.cancelled, 0)
            self.assertEqual(self.practice.snapshot()["text"], "")

    def test_identity_change_after_publication_claim_keeps_one_usage_without_cancelling_recorder(
        self,
    ):
        identity = ["session-a"]
        self.practice.identity = lambda: identity[0]
        record = self.statistics.record_dictation

        def accepted(*args):
            identity[0] = "session-b"
            state = self.practice.snapshot()
            self.assertEqual(state["text"], "")
            self.assertEqual(state["blocked"], "practice_session")
            record(*args)

        self.statistics.record_dictation = accepted
        self.practice.command("open")
        self.practice.command("start")
        self.practice.command("stop")
        self.assertEqual(len(self.statistics.dictations), 1)
        self.assertEqual(self.audio.cancelled, 0)
        self.assertEqual(self.workflow.state.phase.value, "ready")

    def test_discard_completed_rejects_old_ids_and_active_capture(self):
        self.practice.command("open")
        self.practice.command("start")
        operation = self.workflow.state.operation_id
        self.assertFalse(self.workflow.discard_completed(operation))
        self.assertEqual(self.workflow.state.phase.value, "recording")
        self.practice.command("stop")
        self.assertFalse(self.workflow.discard_completed(operation + 1))
        self.assertEqual(self.workflow.state.phase.value, "completed")
        self.assertTrue(self.workflow.discard_completed(operation))
        self.assertEqual(self.workflow.state.phase.value, "ready")
        self.assertEqual(self.audio.cancelled, 0)
