"""Headless tests for dictation, rewrite, and translation orchestration."""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import app
import workflows
from workflows import (
    SelectionTarget,
    StartDictation,
    StartRewrite,
    StopDictation,
    WorkflowPhase,
    WorkflowState,
)


from tests.support.workflows import (
    ThreadScheduler,
    WorkflowFixture,
)


class WorkflowServiceTests(WorkflowFixture, unittest.TestCase):
    def test_app_microphone_error_implements_the_workflow_domain_contract(self):
        self.assertTrue(
            issubclass(
                app.MicrophoneUnavailableError,
                workflows.MicrophoneUnavailableError,
            )
        )

    def test_app_escape_during_blocked_dictation_publication_stays_terminal(self):
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
        operation_id = service.state.operation_id
        harness = SimpleNamespace(
            _workflow_service=service,
            _translation_picker=None,
            app_state="success",
        )

        app.App._on_escape(harness)
        app.App._cancel(harness)

        self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)
        self.assertEqual(self.clipboard.dictation_outputs, [])
        self.assertIsNotNone(service._session)

        write_release.set()
        scheduler.join()
        self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)
        self.assertTrue(service.finish(operation_id))
        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(self.clipboard.auto_pastes, ["Transcribed"])

    def test_app_escape_during_blocked_selection_publication_stays_publishing(self):
        scheduler = ThreadScheduler()
        service = self.make_service(scheduler)
        apply_entered = threading.Event()
        apply_release = threading.Event()
        apply_result = self.clipboard.apply_result

        def blocked_apply(capture, result):
            apply_entered.set()
            if not apply_release.wait(timeout=1.0):
                raise AssertionError("test did not release selection apply")
            return apply_result(capture, result)

        self.clipboard.apply_result = blocked_apply
        service.dispatch(StartRewrite())
        self.assertTrue(apply_entered.wait(timeout=1.0))
        operation_id = service.state.operation_id
        harness = SimpleNamespace(
            _workflow_service=service,
            _translation_picker=None,
            app_state="rewriting",
        )

        app.App._on_escape(harness)
        app.App._cancel(harness)

        self.assertEqual(service.state.phase, WorkflowPhase.PUBLISHING)
        self.assertIsNotNone(service._session)
        self.assertEqual(self.clipboard.applied, [])

        apply_release.set()
        scheduler.join()
        self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)
        self.assertTrue(service.finish(operation_id))
        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        self.assertEqual(len(self.clipboard.applied), 1)
        self.assertEqual(len(self.statistics.rewrites), 1)

    def test_app_renders_the_non_cancellable_publishing_barrier(self):
        set_state = Mock()
        harness = SimpleNamespace(_set_state=set_state)

        app.App._on_workflow_state(
            harness,
            WorkflowState(
                phase=WorkflowPhase.PUBLISHING,
                operation_id=1,
                kind=workflows.WorkflowKind.REWRITE,
            ),
        )

        set_state.assert_called_once_with("processing")


if __name__ == "__main__":
    unittest.main()
