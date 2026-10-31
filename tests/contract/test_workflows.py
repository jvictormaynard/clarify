"""Headless tests for dictation, rewrite, and translation orchestration."""

from __future__ import annotations

import inspect
import threading
import unittest
from pathlib import Path

import workflows
from provider_types import TranscriptionResult
from workflows import (
    CancelDictation,
    CancelTranslation,
    ChooseTranslationLanguage,
    DismissMicrophoneUnavailable,
    MicrophoneUnavailableError,
    RecordingSnapshot,
    SelectionDisposition,
    SelectionTarget,
    StartDictation,
    StartRewrite,
    StartTranslation,
    StopDictation,
    RetryDictation,
    TranscriptionTransportError,
    WorkflowPhase,
    WorkflowState,
)


from tests.support.workflows import (
    ManualScheduler,
    ThreadScheduler,
    BlockingAudio,
    WorkflowFixture,
)


class WorkflowServiceTests(WorkflowFixture, unittest.TestCase):
    def test_service_module_has_no_tk_dependency(self):
        source = inspect.getsource(workflows)
        self.assertNotIn("customtkinter", source)
        self.assertNotIn("tkinter", source)

    def test_rewrite_network_failure_has_actionable_status_and_no_retry(self):
        from provider_http import NetworkError

        def fail():
            raise NetworkError(provider="groq", operation="text_generation")

        self.provider.on_rewrite = fail
        self.service.dispatch(StartRewrite())
        self.assertEqual(self.service.state.phase, WorkflowPhase.FAILED)
        self.assertEqual(self.service.state.status_key, "provider_network")
        self.assertFalse(self.service.state.can_retry)
        self.assertEqual(self.statistics.rewrites, [])

    def test_chatgpt_plan_limit_is_actionable_without_retry_or_publication(self):
        from provider_http import ChatGPTUsageLimitError

        attempts = []

        def fail():
            attempts.append(True)
            raise ChatGPTUsageLimitError(
                provider="chatgpt", operation="text_generation"
            )

        self.provider.on_rewrite = fail
        self.service.dispatch(StartRewrite())
        self.assertEqual(self.service.state.phase, WorkflowPhase.FAILED)
        self.assertEqual(self.service.state.status_key, "provider_chatgpt_plan_limit")
        self.assertFalse(self.service.state.can_retry)
        self.assertEqual(attempts, [True])
        self.assertEqual(self.statistics.rewrites, [])

    def test_network_failure_retries_same_audio_only_after_explicit_command(self):
        requests = []

        def fail_once():
            requests.append(self.provider.transcription_request[0])
            if len(requests) == 1:
                raise TranscriptionTransportError("offline")

        self.provider.on_transcribe = fail_once
        self.service.dispatch(StartDictation(None, "transcription", "pt"))
        self.clock.now += 7
        self.service.dispatch(StopDictation())
        self.assertEqual(self.service.state.phase, WorkflowPhase.FAILED)
        self.assertTrue(self.service.state.can_retry)
        self.assertEqual(len(requests), 1)
        self.assertIsNone(self.audio.failures[0].__traceback__)
        self.assertIsNone(self.audio.failures[0].__context__)
        self.assertIsNone(self.audio.failures[0].__cause__)
        self.assertEqual(self.statistics.dictations, [])
        session = self.service._session
        self.assertIsNotNone(session.retry_audio)
        operation_id = self.service.state.operation_id
        self.assertFalse(self.service.dispatch(RetryDictation(operation_id + 1)))
        self.assertTrue(self.service.dispatch(RetryDictation(operation_id)))
        self.assertFalse(self.service.dispatch(RetryDictation(operation_id)))
        self.assertEqual(self.service.state.phase, WorkflowPhase.COMPLETED)
        self.assertEqual(self.audio.started, 1)
        self.assertEqual(self.audio.stopped, 1)
        self.assertIs(requests[0], requests[1])
        self.assertEqual(len(self.statistics.dictations), 1)
        self.assertEqual(self.statistics.dictations[0][1], 7)
        self.assertIsNone(session.retry_audio)

    def test_discard_and_shutdown_release_retry_audio(self):
        def fail():
            raise TranscriptionTransportError("offline")

        self.provider.on_transcribe = fail
        for discard in (
            lambda: self.service.finish(self.service.state.operation_id),
            self.service.cancel_active,
        ):
            self.service.dispatch(StartDictation(None, "transcription", "pt"))
            self.service.dispatch(StopDictation())
            session = self.service._session
            self.assertIsNotNone(session.retry_audio)
            # A second failure remains retryable and never records again.
            self.assertTrue(self.service.dispatch(RetryDictation(session.operation_id)))
            self.assertTrue(self.service.state.can_retry)
            discard()
            self.assertIsNone(session.retry_audio)
            self.assertFalse(
                self.service.dispatch(RetryDictation(session.operation_id))
            )
        self.assertEqual(self.statistics.dictations, [])

    def test_retry_is_reserved_once_and_cancelled_worker_cannot_publish(self):
        requests = []

        def fail():
            requests.append(self.provider.transcription_request[0])
            raise TranscriptionTransportError("offline")

        self.provider.on_transcribe = fail
        self.service.dispatch(StartDictation(None, "transcription", "pt"))
        self.service.dispatch(StopDictation())
        operation_id = self.service.state.operation_id
        scheduler = ManualScheduler()
        self.service._scheduler = scheduler
        self.assertTrue(self.service.dispatch(RetryDictation(operation_id)))
        self.assertFalse(self.service.dispatch(RetryDictation(operation_id)))
        self.assertEqual(len(scheduler.background), 1)
        self.assertEqual(self.service.state.phase, WorkflowPhase.PROCESSING)
        self.service.cancel_active()
        scheduler.background.pop()()
        for callback in scheduler.soon:
            callback()
        self.assertEqual(self.service.state.phase, WorkflowPhase.READY)
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.statistics.dictations, [])

    def test_rewrite_runs_headlessly_and_records_the_result(self):
        self.assertTrue(self.service.dispatch(StartRewrite()))

        state = self.service.state
        self.assertEqual(state.phase, WorkflowPhase.COMPLETED)
        self.assertEqual(state.result_text, "Rewritten")
        self.assertIsNone(state.status_key)
        self.assertEqual(self.clipboard.writes, ["Rewritten"])
        self.assertEqual(len(self.clipboard.applied), 1)
        self.assertEqual(
            self.statistics.rewrites,
            [("openai", "gpt-test", "Original", "Rewritten")],
        )
        self.assertEqual(
            [state.phase for state in self.states],
            [
                WorkflowPhase.REWRITING,
                WorkflowPhase.PUBLISHING,
                WorkflowPhase.COMPLETED,
            ],
        )

    def test_rewrite_focus_change_after_safe_capture_keeps_copied_result(self):
        original_rewrite = self.provider.rewrite

        def change_focus(text):
            result = original_rewrite(text)
            self.clipboard.window = 88
            return result

        self.provider.rewrite = change_focus

        self.service.dispatch(StartRewrite())

        self.assertEqual(self.service.state.phase, WorkflowPhase.COMPLETED)
        self.assertEqual(self.service.state.status_key, "rewrite_copied")
        self.assertEqual(self.service.state.result_text, "Rewritten")
        self.assertEqual(self.clipboard.writes, ["Rewritten"])
        self.assertEqual(len(self.clipboard.applied), 1)
        self.assertEqual(self.clipboard.restores, ["previous"])
        self.assertEqual(
            self.statistics.rewrites,
            [("openai", "gpt-test", "Original", "Rewritten")],
        )

    def test_rewrite_focus_change_during_alt_wait_skips_capture_and_provider(self):
        alt_checks = 0

        def release_alt_after_focus_change():
            nonlocal alt_checks
            alt_checks += 1
            if alt_checks == 1:
                return True
            self.clipboard.window = 88
            return False

        self.clipboard.alt_pressed = release_alt_after_focus_change

        self.service.dispatch(StartRewrite())

        self.assertEqual(self.service.state.phase, WorkflowPhase.FAILED)
        self.assertEqual(self.service.state.status_key, "no_selection")
        self.assertFalse(hasattr(self.provider, "rewrite_request"))
        self.assertEqual(self.clipboard.captures, [])
        self.assertEqual(self.clipboard.applied, [])
        self.assertEqual(self.clipboard.restores, [])
        self.assertEqual(self.statistics.rewrites, [])

    def test_rewrite_focus_change_during_capture_restores_before_provider(self):
        capture_selection = self.clipboard.capture_selection

        def capture_then_change_focus(target):
            capture = capture_selection(target)
            self.clipboard.window = 88
            return capture

        self.clipboard.capture_selection = capture_then_change_focus

        self.service.dispatch(StartRewrite())

        self.assertEqual(self.service.state.phase, WorkflowPhase.FAILED)
        self.assertEqual(self.service.state.status_key, "no_selection")
        self.assertFalse(hasattr(self.provider, "rewrite_request"))
        self.assertEqual(len(self.clipboard.captures), 1)
        self.assertEqual(self.clipboard.applied, [])
        self.assertEqual(self.clipboard.restores, ["previous"])
        self.assertEqual(self.statistics.rewrites, [])

    def test_rewrite_provider_failure_restores_capture_without_statistics(self):
        self.provider.rewritten = ""

        self.service.dispatch(StartRewrite())

        self.assertEqual(self.service.state.phase, WorkflowPhase.FAILED)
        self.assertEqual(self.service.state.status_key, "rewrite_failed")
        self.assertEqual(self.clipboard.restores, ["previous"])
        self.assertEqual(self.statistics.rewrites, [])

    def test_rewrite_restores_before_blocked_provider_and_cancel_stays_safe(self):
        scheduler = ThreadScheduler()
        provider_entered = threading.Event()
        provider_release = threading.Event()

        def block_provider():
            provider_entered.set()
            if not provider_release.wait(timeout=1.0):
                raise AssertionError("test did not release rewrite provider")

        self.provider.on_rewrite = block_provider
        service = self.make_service(scheduler)

        self.assertTrue(service.dispatch(StartRewrite()))
        self.assertTrue(provider_entered.wait(timeout=1.0))
        self.assertEqual(self.clipboard.current_text, "previous")
        self.assertEqual(self.clipboard.restores, ["previous"])

        service.cancel_active()
        provider_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.clipboard.current_text, "previous")
        self.assertEqual(self.clipboard.applied, [])
        self.assertEqual(self.statistics.rewrites, [])

    def test_rewrite_cancel_during_capture_restores_once(self):
        scheduler = ThreadScheduler()
        capture_entered = threading.Event()
        capture_release = threading.Event()
        capture_selection = self.clipboard.capture_selection

        def block_capture(target):
            capture = capture_selection(target)
            capture_entered.set()
            if not capture_release.wait(timeout=1.0):
                raise AssertionError("test did not release rewrite capture")
            return capture

        self.clipboard.capture_selection = block_capture
        service = self.make_service(scheduler)

        self.assertTrue(service.dispatch(StartRewrite()))
        self.assertTrue(capture_entered.wait(timeout=1.0))
        self.assertEqual(self.clipboard.current_text, "Original")

        service.cancel_active()
        capture_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.clipboard.current_text, "previous")
        self.assertEqual(self.clipboard.restores, ["previous"])
        self.assertFalse(hasattr(self.provider, "rewrite_request"))
        self.assertEqual(self.clipboard.applied, [])
        self.assertEqual(self.statistics.rewrites, [])

    def test_rewrite_cancel_before_queued_publication_has_no_late_output(self):
        scheduler = ManualScheduler()
        service = self.make_service(scheduler)

        self.assertTrue(service.dispatch(StartRewrite()))
        scheduler.background.pop(0)()  # capture/provider worker
        self.assertEqual(service.state.phase, WorkflowPhase.PUBLISHING)
        # Deliver the barrier first.  It queues the external publication only
        # after the view has observed the non-cancellable phase.
        while scheduler.soon:
            scheduler.soon.pop(0)()
        self.assertEqual(len(scheduler.background), 1)

        service.cancel_active()
        scheduler.background.pop(0)()  # queued publication

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.clipboard.applied, [])
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.statistics.rewrites, [])

    def test_translation_prepares_picker_then_translates_after_choice(self):
        picker_restores = []
        self.service.subscribe(
            lambda state: (
                picker_restores.append(list(self.clipboard.restores))
                if state.phase is WorkflowPhase.TRANSLATION_PICKER
                else None
            )
        )

        self.assertTrue(self.service.dispatch(StartTranslation()))
        self.assertEqual(self.service.state.phase, WorkflowPhase.TRANSLATION_PICKER)
        self.assertEqual(picker_restores, [["previous"]])
        self.assertEqual(self.clipboard.restores, ["previous"])
        self.assertEqual(self.clipboard.writes, [])

        self.assertTrue(self.service.dispatch(ChooseTranslationLanguage("de")))

        self.assertEqual(self.provider.translation_request, ("Original", "de"))
        self.assertEqual(self.clipboard.activations, [77])
        self.assertEqual(self.service.state.phase, WorkflowPhase.COMPLETED)
        self.assertEqual(self.service.state.result_text, "Translated")
        self.assertEqual(
            self.statistics.translations,
            [("openai", "gpt-test", "Original", "Translated", "de")],
        )
        self.assertEqual(self.clipboard.restores, ["previous"])

    def test_translation_focus_change_during_capture_stops_before_picker(self):
        capture_selection = self.clipboard.capture_selection

        def capture_then_change_focus(target):
            capture = capture_selection(target)
            self.clipboard.window = 88
            return capture

        self.clipboard.capture_selection = capture_then_change_focus

        self.service.dispatch(StartTranslation())

        self.assertEqual(self.service.state.phase, WorkflowPhase.FAILED)
        self.assertEqual(self.service.state.status_key, "no_selection")
        self.assertFalse(hasattr(self.provider, "translation_request"))
        self.assertNotIn(
            WorkflowPhase.TRANSLATION_PICKER,
            [state.phase for state in self.states],
        )
        self.assertEqual(self.clipboard.applied, [])
        self.assertEqual(self.clipboard.restores, ["previous"])
        self.assertEqual(self.statistics.translations, [])

    def test_translation_cancel_during_capture_restores_once(self):
        scheduler = ThreadScheduler()
        capture_entered = threading.Event()
        capture_release = threading.Event()
        capture_selection = self.clipboard.capture_selection

        def block_capture(target):
            capture = capture_selection(target)
            capture_entered.set()
            if not capture_release.wait(timeout=1.0):
                raise AssertionError("test did not release translation capture")
            return capture

        self.clipboard.capture_selection = block_capture
        service = self.make_service(scheduler)
        states = []
        service.subscribe(states.append)

        self.assertTrue(service.dispatch(StartTranslation()))
        self.assertTrue(capture_entered.wait(timeout=1.0))
        self.assertEqual(self.clipboard.current_text, "Original")

        service.cancel_active()
        capture_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.clipboard.current_text, "previous")
        self.assertEqual(self.clipboard.restores, ["previous"])
        self.assertFalse(hasattr(self.provider, "translation_request"))
        self.assertNotIn(
            WorkflowPhase.TRANSLATION_PICKER,
            [state.phase for state in states],
        )
        self.assertEqual(self.clipboard.applied, [])
        self.assertEqual(self.statistics.translations, [])

    def test_translation_cancel_before_queued_publication_has_no_late_output(self):
        scheduler = ManualScheduler()
        service = self.make_service(scheduler)

        self.assertTrue(service.dispatch(StartTranslation()))
        scheduler.background.pop(0)()  # capture/restore worker
        self.assertEqual(service.state.phase, WorkflowPhase.TRANSLATION_PICKER)
        self.assertTrue(service.dispatch(ChooseTranslationLanguage("de")))
        scheduler.background.pop(0)()  # provider worker
        self.assertEqual(service.state.phase, WorkflowPhase.PUBLISHING)
        while scheduler.soon:
            scheduler.soon.pop(0)()
        self.assertEqual(len(scheduler.background), 1)

        service.cancel_active()
        scheduler.background.pop(0)()  # queued publication

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.clipboard.applied, [])
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.statistics.translations, [])

    def test_rewrite_shutdown_does_not_wait_for_blocked_apply(self):
        scheduler = ThreadScheduler()
        service = self.make_service(scheduler)
        apply_entered = threading.Event()
        apply_release = threading.Event()
        apply_result = self.clipboard.apply_result

        def blocked_apply(capture, result):
            apply_entered.set()
            if not apply_release.wait(timeout=1.0):
                raise AssertionError("test did not release rewrite apply")
            return apply_result(capture, result)

        self.clipboard.apply_result = blocked_apply

        self.assertTrue(service.dispatch(StartRewrite()))
        self.assertTrue(apply_entered.wait(timeout=1.0))

        cancel_finished = threading.Event()

        def cancel_for_shutdown():
            service.cancel_active()
            cancel_finished.set()

        threading.Thread(target=cancel_for_shutdown, daemon=True).start()
        self.assertTrue(
            cancel_finished.wait(timeout=0.5),
            "shutdown cancellation waited behind the clipboard gateway",
        )
        apply_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(len(self.clipboard.applied), 1)
        self.assertEqual(len(self.statistics.rewrites), 1)

    def test_translation_shutdown_does_not_wait_for_blocked_apply(self):
        scheduler = ThreadScheduler()
        service = self.make_service(scheduler)
        apply_entered = threading.Event()
        apply_release = threading.Event()
        apply_result = self.clipboard.apply_result

        def blocked_apply(capture, result):
            apply_entered.set()
            if not apply_release.wait(timeout=1.0):
                raise AssertionError("test did not release translation apply")
            return apply_result(capture, result)

        self.clipboard.apply_result = blocked_apply

        self.assertTrue(service.dispatch(StartTranslation()))
        # The picker is delivered synchronously by the test scheduler.
        self.assertTrue(service.dispatch(ChooseTranslationLanguage("de")))
        self.assertTrue(apply_entered.wait(timeout=1.0))

        cancel_finished = threading.Event()

        def cancel_for_shutdown():
            service.cancel_active()
            cancel_finished.set()

        threading.Thread(target=cancel_for_shutdown, daemon=True).start()
        self.assertTrue(
            cancel_finished.wait(timeout=0.5),
            "shutdown cancellation waited behind the clipboard gateway",
        )
        apply_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(len(self.clipboard.applied), 1)
        self.assertEqual(len(self.statistics.translations), 1)

    def test_translation_blocks_rewrite_while_selection_is_preparing(self):
        scheduler = ManualScheduler()
        service = self.make_service(scheduler)

        self.assertTrue(service.dispatch(StartTranslation()))
        self.assertEqual(service.state.phase, WorkflowPhase.PREPARING_TRANSLATION)
        self.assertFalse(service.dispatch(StartRewrite()))

        scheduler.background.pop(0)()
        self.assertEqual(service.state.phase, WorkflowPhase.TRANSLATION_PICKER)

    def test_translation_picker_cancel_restores_target_and_releases_flow(self):
        self.service.dispatch(StartTranslation())

        self.assertTrue(self.service.dispatch(CancelTranslation()))

        self.assertEqual(self.clipboard.activations, [77])
        self.assertEqual(self.clipboard.restores, ["previous"])
        self.assertEqual(self.service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.statistics.translations, [])

    def test_dictation_owns_start_stop_provider_and_statistics_sequence(self):
        self.assertTrue(
            self.service.dispatch(
                StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "pt")
            )
        )
        self.clock.now = 12.5
        self.assertTrue(self.service.dispatch(StopDictation()))

        self.assertEqual(self.audio.started, 1)
        self.assertEqual(self.audio.startup_waits, 1)
        self.assertEqual(self.audio.stopped, 1)
        self.assertEqual(self.audio.completed, 1)
        self.assertEqual(
            self.provider.transcription_request,
            (
                RecordingSnapshot(Path("recording.wav"), b"audio"),
                "prompt",
                "pt",
            ),
        )
        self.assertEqual(self.clipboard.auto_pastes, ["Transcribed"])
        self.assertEqual(
            self.clipboard.dictation_outputs,
            [
                (
                    SelectionTarget(77, "editor.exe"),
                    "Transcribed",
                    SelectionDisposition.PASTED,
                )
            ],
        )
        self.assertEqual(len(self.statistics.dictations), 1)
        context, duration, result = self.statistics.dictations[0]
        self.assertEqual((duration, result), (2.5, "Transcribed"))
        self.assertEqual(context["provider"], "gemini")
        self.assertEqual(context["mode"], "prompt")
        self.assertIn("stop_to_delivery_ms", context["latency_ms"])
        self.assertEqual(self.service.state.source_text, "Transcribed")
        self.assertIsNone(self.service.state.refined_text)
        self.assertIsNone(self.service.state.refinement_provider_id)
        self.assertIsNone(self.service.state.refinement_model)
        self.assertEqual(self.service.state.phase, WorkflowPhase.COMPLETED)

    def test_prompt_dictation_forwards_raw_and_refinement_route_metadata(self):
        self.provider.transcribe = lambda _audio, _mode, _language: TranscriptionResult(
            "refined transcript",
            "openai",
            "whisper-1",
            raw_text="raw transcript",
            refined_text="refined transcript",
            refinement_provider_id="groq",
            refinement_model="llama-refiner",
            cleanup_level_requested="clarity",
            cleanup_level_applied="clarity",
        )

        self.service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )
        self.service.dispatch(StopDictation())

        state = self.service.state
        self.assertEqual(state.result_text, "refined transcript")
        self.assertEqual(state.source_text, "raw transcript")
        self.assertEqual(state.refined_text, "refined transcript")
        self.assertEqual(state.provider_id, "openai")
        self.assertEqual(state.model, "whisper-1")
        self.assertEqual(state.refinement_provider_id, "groq")
        self.assertEqual(state.refinement_model, "llama-refiner")
        self.assertEqual(state.cleanup_level_requested, "clarity")
        self.assertEqual(state.cleanup_level_applied, "clarity")
        self.assertEqual(state.phase, WorkflowPhase.COMPLETED)

    def test_dictation_focus_change_during_transcription_uses_copied_fallback(self):
        self.provider.on_transcribe = lambda: setattr(self.clipboard, "window", 88)

        self.service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )
        self.service.dispatch(StopDictation())

        self.assertEqual(self.clipboard.auto_pastes, [])
        self.assertEqual(self.clipboard.writes, ["Transcribed"])
        self.assertEqual(
            self.clipboard.dictation_outputs,
            [
                (
                    SelectionTarget(77, "editor.exe"),
                    "Transcribed",
                    SelectionDisposition.COPIED,
                )
            ],
        )
        self.assertEqual(self.service.state.phase, WorkflowPhase.COMPLETED)

    def test_immediate_stop_waits_for_blocked_startup_before_stopping(self):
        scheduler = ThreadScheduler()
        self.audio = BlockingAudio()
        service = self.make_service(scheduler)

        self.assertTrue(
            service.dispatch(
                StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
            )
        )
        self.assertTrue(self.audio.start_entered.wait(timeout=1.0))
        self.assertTrue(service.dispatch(StopDictation()))
        self.assertTrue(self.audio.wait_entered.wait(timeout=1.0))
        self.assertEqual(self.audio.stopped, 0)

        self.audio.start_release.set()
        scheduler.join()

        self.assertEqual(self.audio.started, 1)
        self.assertEqual(self.audio.startup_waits, 1)
        self.assertEqual(self.audio.stopped, 1)
        self.assertLess(
            self.audio.order.index("start_terminal"),
            self.audio.order.index("stop"),
        )
        self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)

    def test_immediate_stop_propagates_blocked_startup_failure(self):
        scheduler = ThreadScheduler()
        self.audio = BlockingAudio(RuntimeError("startup failed"))
        service = self.make_service(scheduler)

        service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )
        self.assertTrue(self.audio.start_entered.wait(timeout=1.0))
        service.dispatch(StopDictation())
        self.assertTrue(self.audio.wait_entered.wait(timeout=1.0))
        self.audio.start_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.FAILED)
        self.assertEqual(service.state.status_key, "error")
        self.assertEqual(self.audio.stopped, 0)
        self.assertEqual(len(self.audio.failures), 1)
        self.assertFalse(hasattr(self.provider, "transcription_request"))
        self.assertEqual(self.clipboard.auto_pastes, [])
        self.assertEqual(self.statistics.dictations, [])

    def test_generic_startup_failure_is_not_reported_as_microphone_unavailable(self):
        scheduler = ThreadScheduler()
        self.audio = BlockingAudio(RuntimeError("SoX permission denied"))
        service = self.make_service(scheduler)

        service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )
        self.assertTrue(self.audio.start_entered.wait(timeout=1.0))
        self.audio.start_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.FAILED)
        self.assertEqual(service.state.status_key, "error")

    def test_typed_microphone_startup_failure_reports_microphone_unavailable(self):
        scheduler = ThreadScheduler()
        self.audio = BlockingAudio(MicrophoneUnavailableError("no input"))
        service = self.make_service(scheduler)

        service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )
        self.assertTrue(self.audio.start_entered.wait(timeout=1.0))
        self.audio.start_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.MICROPHONE_UNAVAILABLE)
        self.assertIsInstance(self.audio.failures[0], MicrophoneUnavailableError)

    def test_immediate_stop_preserves_typed_microphone_startup_failure(self):
        scheduler = ThreadScheduler()
        self.audio = BlockingAudio(MicrophoneUnavailableError("no input"))
        service = self.make_service(scheduler)

        service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )
        self.assertTrue(self.audio.start_entered.wait(timeout=1.0))
        self.assertTrue(service.dispatch(StopDictation()))
        self.assertTrue(self.audio.wait_entered.wait(timeout=1.0))
        self.audio.start_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.MICROPHONE_UNAVAILABLE)

    def test_audio_owner_rejection_keeps_dictation_ready_without_worker(self):
        scheduler = ManualScheduler()
        self.audio.create_session = lambda: None
        service = self.make_service(scheduler)

        self.assertFalse(
            service.dispatch(
                StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
            )
        )

        self.assertEqual(service.state, WorkflowState())
        self.assertEqual(scheduler.background, [])
        self.assertFalse(hasattr(self.provider, "transcription_request"))
        self.assertEqual(self.statistics.dictations, [])

    def test_cancel_during_blocked_startup_prevents_late_stop_or_provider(self):
        scheduler = ThreadScheduler()
        self.audio = BlockingAudio()
        service = self.make_service(scheduler)

        service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )
        self.assertTrue(self.audio.start_entered.wait(timeout=1.0))
        self.assertTrue(service.dispatch(CancelDictation()))
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.audio.stopped, 0)
        self.assertGreaterEqual(self.audio.cancelled, 1)
        self.assertEqual(self.audio.failures, [])
        self.assertLess(
            self.audio.order.index("cancel"),
            self.audio.order.index("start_terminal"),
        )
        self.assertFalse(hasattr(self.provider, "transcription_request"))
        self.assertEqual(self.clipboard.auto_pastes, [])
        self.assertEqual(self.statistics.dictations, [])

    def test_no_usable_audio_is_a_distinct_failure(self):
        self.audio.present = False
        self.service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )

        self.service.dispatch(StopDictation())

        self.assertEqual(self.service.state.phase, WorkflowPhase.FAILED)
        self.assertEqual(self.service.state.status_key, "no_audio")
        self.assertEqual(len(self.audio.failures), 1)
        self.assertFalse(hasattr(self.provider, "transcription_request"))

    def test_microphone_unavailable_can_be_dismissed_without_a_session(self):
        self.audio.available = False

        self.service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )

        self.assertEqual(self.service.state.phase, WorkflowPhase.MICROPHONE_UNAVAILABLE)
        self.assertEqual(self.audio.started, 0)
        self.assertTrue(self.service.dispatch(DismissMicrophoneUnavailable()))
        self.assertEqual(self.service.state.phase, WorkflowPhase.READY)

    def test_cancelled_recording_start_cannot_restore_stale_state(self):
        scheduler = ManualScheduler()
        service = self.make_service(scheduler)
        states = []
        service.subscribe(states.append)

        self.assertTrue(
            service.dispatch(
                StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
            )
        )
        self.assertTrue(service.dispatch(CancelDictation()))
        self.assertEqual(service.state.phase, WorkflowPhase.READY)

        start_worker = scheduler.background.pop(0)
        start_worker()

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.audio.started, 1)
        self.assertGreaterEqual(self.audio.cancelled, 1)
        self.assertEqual(self.statistics.dictations, [])
        self.assertEqual(self.clipboard.auto_pastes, [])

    def test_stale_rewrite_completion_cannot_touch_clipboard_or_statistics(self):
        self.provider.on_rewrite = self.service.cancel_active

        self.assertTrue(self.service.dispatch(StartRewrite()))

        self.assertEqual(self.service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.clipboard.applied, [])
        self.assertEqual(self.statistics.rewrites, [])

    def test_finished_dictation_waits_for_a_delayed_clipboard_worker(self):
        scheduler = ManualScheduler()
        service = self.make_service(scheduler)
        service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )
        scheduler.background.pop(0)()  # recording start
        self.clock.now = 11.0
        service.dispatch(StopDictation())
        scheduler.background.pop(0)()  # stop/provider worker
        while scheduler.soon:
            scheduler.soon.pop(0)()  # terminal delivery, then publication queue
        operation_id = service.state.operation_id
        self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)

        self.assertTrue(service.finish(operation_id))
        scheduler.background.pop(0)()  # delayed clipboard delivery
        while scheduler.soon:
            scheduler.soon.pop(0)()  # deferred READY delivery

        self.assertEqual(self.clipboard.auto_pastes, ["Transcribed"])
        self.assertEqual(len(self.statistics.dictations), 1)
        self.assertEqual(service.state.phase, WorkflowPhase.READY)

    def test_terminal_listener_can_finish_before_dictation_publication_claim(self):
        scheduler = ManualScheduler()
        service = self.make_service(scheduler)
        finished = []

        def finish_on_terminal(state):
            if state.phase is WorkflowPhase.COMPLETED:
                finished.append(service.finish(state.operation_id))

        service.subscribe(finish_on_terminal)
        service.dispatch(
            StartDictation(SelectionTarget(77, "editor.exe"), "prompt", "en")
        )
        scheduler.background.pop(0)()  # recording start
        service.dispatch(StopDictation())
        scheduler.background.pop(0)()  # stop/provider worker
        while scheduler.soon:
            scheduler.soon.pop(0)()  # terminal listener queues publication
        scheduler.background.pop(0)()  # publication claimed after listener
        while scheduler.soon:
            scheduler.soon.pop(0)()  # deferred READY delivery

        self.assertEqual(finished, [True])
        self.assertEqual(self.clipboard.auto_pastes, ["Transcribed"])
        self.assertEqual(len(self.statistics.dictations), 1)
        self.assertEqual(service.state.phase, WorkflowPhase.READY)

    def test_dictation_cancel_wins_before_queued_publication(self):
        scheduler = ManualScheduler()
        service = self.make_service(scheduler)
        target = SelectionTarget(77, "editor.exe")

        service.dispatch(StartDictation(target, "prompt", "en"))
        scheduler.background.pop(0)()  # recording start
        service.dispatch(StopDictation())
        scheduler.background.pop(0)()  # stop/provider worker
        while scheduler.soon:
            scheduler.soon.pop(0)()  # terminal delivery, then publication queue
        self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)
        self.assertEqual(len(scheduler.background), 1)

        # Invalidate the operation before the queued external publication.
        service.cancel_active()
        scheduler.background.pop(0)()  # dictation publication

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.clipboard.auto_pastes, [])
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.statistics.dictations, [])

    def test_dictation_shutdown_does_not_wait_for_blocked_clipboard_write(self):
        scheduler = ThreadScheduler()
        service = self.make_service(scheduler)
        write_entered = threading.Event()
        write_release = threading.Event()
        write_result = self.clipboard.write_dictation_result

        def blocked_write(target, text):
            write_entered.set()
            if not write_release.wait(timeout=1.0):
                raise AssertionError("test did not release dictation write")
            return write_result(target, text)

        self.clipboard.write_dictation_result = blocked_write
        target = SelectionTarget(77, "editor.exe")
        service.dispatch(StartDictation(target, "prompt", "en"))
        service.dispatch(StopDictation())
        self.assertTrue(write_entered.wait(timeout=1.0))

        cancel_finished = threading.Event()

        def cancel_for_shutdown():
            service.cancel_active()
            cancel_finished.set()

        threading.Thread(target=cancel_for_shutdown, daemon=True).start()
        self.assertTrue(
            cancel_finished.wait(timeout=0.5),
            "shutdown cancellation waited behind the clipboard gateway",
        )
        write_release.set()
        scheduler.join()

        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.clipboard.auto_pastes, ["Transcribed"])
        self.assertEqual(len(self.statistics.dictations), 1)

    def test_terminal_operation_releases_only_matching_operation_id(self):
        self.service.dispatch(StartRewrite())
        operation_id = self.service.state.operation_id

        self.assertFalse(self.service.finish(operation_id + 1))
        self.assertEqual(self.service.state.phase, WorkflowPhase.COMPLETED)
        self.assertTrue(self.service.finish(operation_id))
        self.assertEqual(self.service.state.phase, WorkflowPhase.READY)

    def test_finish_publishes_ready_after_completed_or_failed_animation(self):
        for rewritten, terminal_phase in (
            ("Rewritten", WorkflowPhase.COMPLETED),
            ("", WorkflowPhase.FAILED),
        ):
            with self.subTest(terminal_phase=terminal_phase):
                self.provider.rewritten = rewritten
                self.service.dispatch(StartRewrite())
                operation_id = self.service.state.operation_id
                self.assertEqual(self.states[-1].phase, terminal_phase)

                self.assertTrue(self.service.finish(operation_id))

                self.assertEqual(self.states[-1].phase, WorkflowPhase.READY)
                self.assertEqual(self.states[-1].operation_id, 0)
                self.assertEqual(
                    [state.phase for state in self.states[-2:]],
                    [terminal_phase, WorkflowPhase.READY],
                )


if __name__ == "__main__":
    unittest.main()
