"""Quick menu actions must preserve drafts, transcripts and paste targets."""

import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QCoreApplication
from spikes.pyside6.qml_bridge import QmlWorkflowBridge
from spikes.pyside6.qml_quick_paste import QuickPasteController
from workflows import (
    WorkflowState,
    WorkflowKind,
    WorkflowPhase,
    SelectionDisposition,
    SelectionTarget,
)
from test_pyside6_qml_settings import _repositories, _MicrophoneBackend
from spikes.pyside6.qml_settings import QmlSettingsController
from microphone_controls import MicrophoneDevice, MicrophoneInventory


class QuickActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_only_completed_dictation_is_retained_in_memory(self):
        service = SimpleNamespace(
            state=WorkflowState(), subscribe=lambda listener: None
        )
        paste = Mock()
        bridge = QmlWorkflowBridge(service, paste_runner=paste)
        self.assertFalse(bridge.canPasteLastTranscription)
        bridge._on_workflow_state(
            WorkflowState(
                phase=WorkflowPhase.COMPLETED,
                kind=WorkflowKind.DICTATION,
                result_text="Last transcript",
            )
        )
        bridge._on_workflow_state(WorkflowState())
        bridge._on_workflow_state(
            WorkflowState(
                phase=WorkflowPhase.COMPLETED,
                kind=WorkflowKind.REWRITE,
                result_text="Not a transcript",
            )
        )
        bridge._on_workflow_state(WorkflowState())
        self.assertTrue(bridge.pasteLastTranscription())
        self.assertEqual(paste.call_args.args[0], "Last transcript")
        self.assertFalse(bridge.pasteLastTranscription())
        self.assertFalse(bridge.handleHotkey("recording_hotkey"))
        paste.call_args.args[1]("copied")
        self.assertTrue(bridge.feedbackVisible)
        self.assertIn("Ctrl+V", bridge.feedbackTitle)
        bridge.dismissFeedback(bridge.feedbackOperationId)
        self.assertFalse(bridge.feedbackVisible)
        self.assertTrue(bridge.canPasteLastTranscription)
        self.assertFalse(
            QmlWorkflowBridge(service, paste_runner=paste).canPasteLastTranscription
        )

    def test_menu_does_not_replace_external_target(self):
        external = SelectionTarget(123, "editor.exe")
        own_window = Mock()
        own_window.isActive.return_value = False
        own_window.winId.return_value = 456
        clipboard = Mock()
        clipboard.capture_target.return_value = external
        clipboard.write_dictation_result.return_value = SelectionDisposition.PASTED
        hide, finished = Mock(), Mock()
        controller = QuickPasteController(
            clipboard, lambda action: action(), lambda: [own_window], hide
        )
        try:
            controller.remember_target()
            own_window.isActive.return_value = True
            clipboard.capture_target.return_value = SelectionTarget(
                456, "ClarifyVoice.exe"
            )
            controller.paste("Transcript", finished)
            hide.assert_called_once()
            clipboard.activate.assert_called_once_with(external)
            clipboard.write_dictation_result.assert_called_once_with(
                external, "Transcript"
            )
            finished.assert_called_once_with("pasted")
        finally:
            controller.timer.stop()

    def test_quick_microphone_does_not_save_unrelated_drafts(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            inventory = MicrophoneInventory(
                devices=(MicrophoneDevice("usb", "USB", input_channels=1),)
            )
            controller = QmlSettingsController(
                repositories, microphone_backend=_MicrophoneBackend(inventory)
            )
            try:
                persisted = repositories.config.load()
                controller.setHistoryEnabled(not persisted.history_enabled)
                self.assertTrue(controller.selectQuickMicrophone("usb"))
                self.assertEqual(
                    repositories.config.load().microphone.selected_id, "usb"
                )
                self.assertEqual(
                    repositories.config.load().history_enabled,
                    persisted.history_enabled,
                )
                self.assertTrue(controller.dirty)
                self.assertFalse(controller.selectQuickMicrophone("missing"))
                self.assertEqual(
                    repositories.config.load().microphone.selected_id, "usb"
                )
            finally:
                controller.shutdown()

    def test_missing_target_copies_without_activation(self):
        clipboard = Mock()
        clipboard.capture_target.return_value = None
        clipboard.write_dictation_result.return_value = SelectionDisposition.COPIED
        finished = Mock()
        controller = QuickPasteController(
            clipboard, lambda action: action(), lambda: [], Mock()
        )
        try:
            controller.paste("Transcript", finished)
            clipboard.activate.assert_not_called()
            clipboard.write_dictation_result.assert_called_once_with(None, "Transcript")
            finished.assert_called_once_with("copied")
        finally:
            controller.timer.stop()

    def test_voice_translation_success_does_not_open_result(self):
        from voice_translation import VoiceTranslationPhase

        service = SimpleNamespace(
            state=WorkflowState(), subscribe=lambda listener: None
        )
        voice = SimpleNamespace(
            state=SimpleNamespace(
                phase=VoiceTranslationPhase.COMPLETED,
                workflow_state=SimpleNamespace(published_text="Translated text"),
            ),
            active=False,
            stateChanged=Mock(),
        )
        bridge = QmlWorkflowBridge(service, voice_translation_controller=voice)
        self.assertEqual(bridge.surface, "idle")
        self.assertFalse(bridge.feedbackVisible)

    def test_all_successful_workflows_remain_on_compact_home(self):
        from spikes.pyside6.qml_app import _WorkflowWindowVisibility

        service = SimpleNamespace(
            state=WorkflowState(), subscribe=lambda listener: None
        )
        for kind in WorkflowKind:
            bridge = QmlWorkflowBridge(service)
            restored_surfaces = []
            shell = SimpleNamespace(
                hide_window=Mock(),
                show_window=lambda: restored_surfaces.append(bridge.surface),
            )
            coordinator = _WorkflowWindowVisibility(
                bridge, shell, SimpleNamespace(isVisible=lambda: True)
            )
            bridge._on_workflow_state(
                WorkflowState(phase=WorkflowPhase.PROCESSING, kind=kind)
            )
            bridge._on_workflow_state(
                WorkflowState(
                    phase=WorkflowPhase.COMPLETED,
                    kind=kind,
                    result_text="Already published",
                )
            )
            self.assertEqual(restored_surfaces, ["idle"])
            self.assertFalse(bridge.feedbackVisible)
            self.assertIsNotNone(coordinator)

    def test_clipboard_failure_does_not_retry_or_expose_text(self):
        clipboard = Mock()
        clipboard.capture_target.return_value = None
        clipboard.write_dictation_result.side_effect = RuntimeError(
            "private transcript"
        )
        finished = Mock()
        controller = QuickPasteController(
            clipboard, lambda action: action(), lambda: [], Mock()
        )
        try:
            controller.paste("Transcript", finished)
            self.assertEqual(clipboard.write_dictation_result.call_count, 1)
            finished.assert_called_once_with("failed")
        finally:
            controller.timer.stop()


if __name__ == "__main__":
    unittest.main()
