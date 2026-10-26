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
