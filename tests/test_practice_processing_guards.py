"""Every capture and processing entry respects composition-owned exclusion."""

import unittest
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication
from clarify.desktop.qml_bridge import QmlWorkflowBridge
from clarify.desktop.qml_audio_batch import QmlAudioFileImportController
from clarify.desktop.qml_voice_translation import QmlVoiceTranslationController
from test_qml_recording_controls import Service
from workflows import WorkflowPhase, StopDictation


class ProcessingGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_queued_dictation_rechecks_guard_before_dispatch(self):
        service = Service()
        queued = []
        allowed = [True]
        bridge = QmlWorkflowBridge(
            service,
            dispatch_runner=queued.append,
            processing_allowed=lambda: allowed[0],
        )
        bridge.startRecordingFromButton()
        self.assertTrue(bridge.start_pending)
        self.assertEqual(len(queued), 1)
        allowed[0] = False
        queued.pop()()
        self.assertFalse(bridge.start_pending)
        self.assertEqual(service.commands, [])

    def test_guard_blocks_new_dictation_rewrite_and_translation_but_not_stop(self):
        service = Service()
        capture = Mock()
        bridge = QmlWorkflowBridge(
            service,
            target_provider=capture,
            processing_allowed=lambda: False,
        )
        bridge.startRecording()
        for action in ("rewrite_hotkey", "translation_hotkey", "recording_hold_press"):
            self.assertFalse(bridge.handleHotkey(action))
        self.assertEqual(service.commands, [])
        capture.assert_not_called()
        service.publish(WorkflowPhase.RECORDING)
        bridge.stopRecording()
        self.assertIsInstance(service.commands[-1], StopDictation)

    def test_audio_import_and_retry_do_not_start_when_guard_rejects(self):
        service = Mock()
        selection = Mock()
        controller = QmlAudioFileImportController(
            service,
            call_soon=lambda callback: callback(),
            selection_factory=selection,
            processing_allowed=lambda: False,
        )
        self.assertFalse(controller.startSelected("", "", ""))
        self.assertFalse(controller.retryFailed())
        selection.assert_not_called()
        service.transcribe.assert_not_called()

    def test_voice_translation_does_not_capture_target_or_audio_when_guard_rejects(
        self,
    ):
        clipboard = Mock()
        recording = Mock()
        controller = QmlVoiceTranslationController(
            Mock(),
            clipboard,
            recording,
            Mock(),
            provider=Mock(),
            processing_allowed=lambda: False,
        )
        self.assertFalse(controller.start())
        self.assertFalse(controller.startForTarget(object()))
        clipboard.capture_target.assert_not_called()
        recording.assert_not_called()

    def test_capture_remains_busy_until_cancelled_workers_exit(self):
        import threading
        from types import SimpleNamespace
        from clarify.desktop.qml_runtime import QtRecordingAudioGateway

        gateway = QtRecordingAudioGateway(SimpleNamespace(config=None))
        self.assertFalse(gateway.busy)
        released = threading.Event()
        gateway._active = SimpleNamespace(shutdown_complete=released)
        self.assertTrue(gateway.busy)
        released.set()
        self.assertFalse(gateway.busy)

    def test_composition_permits_terminal_recovery_without_clearing_retry_audio(self):
        from types import SimpleNamespace
        from clarify.desktop.qml_app import _capture_idle
        from workflows import WorkflowState

        audio = SimpleNamespace(busy=False)
        bridge = SimpleNamespace(start_pending=False)
        for phase in (
            WorkflowPhase.FAILED,
            WorkflowPhase.CANCELLED,
            WorkflowPhase.MICROPHONE_UNAVAILABLE,
        ):
            state = WorkflowState(phase=phase, can_retry=True, can_undo=True)
            service = SimpleNamespace(state=state)
            self.assertTrue(_capture_idle(service, audio, bridge))
            self.assertIs(service.state, state)
            audio.busy = True
            self.assertFalse(_capture_idle(service, audio, bridge))
            audio.busy = False
            bridge.start_pending = True
            self.assertFalse(_capture_idle(service, audio, bridge))
            bridge.start_pending = False

    def test_retry_and_undo_revalidate_the_guard_without_discarding_retained_audio(
        self,
    ):
        from test_pyside6_qml_runtime import DeterministicWorkflowService
        from workflows import WorkflowState, RetryDictation, UndoCancelDictation

        for phase, method, command in (
            (WorkflowPhase.FAILED, "retryTranscription", RetryDictation),
            (WorkflowPhase.CANCELLED, "undoCancellation", UndoCancelDictation),
        ):
            service = DeterministicWorkflowService()
            allowed = [False]
            queued = []
            bridge = QmlWorkflowBridge(
                service,
                processing_allowed=lambda: allowed[0],
                dispatch_runner=queued.append,
            )
            state = WorkflowState(
                phase=phase, operation_id=7, can_retry=True, can_undo=True
            )
            service.publish(state)
            self.assertFalse(getattr(bridge, method)())
            self.assertIs(service.state, state)
            allowed[0] = True
            self.assertTrue(getattr(bridge, method)())
            self.assertTrue(bridge.start_pending)
            queued.pop()()
            self.assertIsInstance(service.commands[-1], command)

    def test_normal_qml_consumer_has_translated_messages_for_bounded_account_errors(
        self,
    ):
        from test_pyside6_qml_runtime import DeterministicWorkflowService
        from workflows import WorkflowState
        from shared.localization import translate

        expected = {
            "account_allowance_exhausted": "You have reached your allowance.",
            "account_allocation_waiting": "Your account is waiting for the next quota distribution.",
            "account_authentication_required": "Sign in again.",
        }
        for code, message in expected.items():
            service = DeterministicWorkflowService()
            bridge = QmlWorkflowBridge(service)
            service.publish(WorkflowState(phase=WorkflowPhase.FAILED, status_key=code))
            self.assertEqual(translate(bridge.status, lang="en"), message)
            self.assertFalse(bridge.status.startswith("account_"))
