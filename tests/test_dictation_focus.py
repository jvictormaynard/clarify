"""Completion must not activate Clarify before the guarded clipboard write."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication
from spikes.pyside6.qml_app import _WorkflowWindowVisibility
from spikes.pyside6.qml_bridge import QmlWorkflowBridge
from spikes.pyside6.qml_clipboard import QmlClipboardGateway
from workflows import WorkflowState, WorkflowPhase, SelectionDisposition
from test_pyside6_qml_clipboard import FakeClipboardAdapter


class DictationFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.foreground = 77
        self.visible = True
        self.service = SimpleNamespace(
            state=WorkflowState(), subscribe=lambda listener: None, finish=Mock()
        )
        self.bridge = QmlWorkflowBridge(self.service)
        self.window = Mock()
        self.window.isVisible.side_effect = lambda: self.visible
        self.shell = Mock()
        self.shell.hide_window.side_effect = self.hide
        self.shell.show_window.side_effect = self.show
        self.shell.show_window_without_activation.side_effect = self.restore
        self.coordinator = _WorkflowWindowVisibility(
            self.bridge, self.shell, self.window
        )
        self.paste = Mock(return_value=True)
        self.clipboard = QmlClipboardGateway(
            adapter=FakeClipboardAdapter(),
            is_windows=True,
            foreground_window=lambda: self.foreground,
            executable_for_window=lambda _: "editor.exe",
            send_ctrl_v=self.paste,
            sleep=lambda _: None,
            alt_pressed=lambda: False,
        )

    def hide(self):
        self.visible = False

    def restore(self):
        self.visible = True

    def show(self):
        self.visible = True
        self.foreground = 999  # Native requestActivate transfers focus to Clarify.

    def complete(self, switch_to=None):
        target = self.clipboard.capture_target()
        for phase in (WorkflowPhase.RECORDING, WorkflowPhase.PROCESSING):
            self.bridge._on_workflow_state(
                WorkflowState(phase=phase, operation_id="dictation")
            )
        if switch_to is not None:
            self.foreground = switch_to
        # WorkflowService delivers COMPLETED before scheduling clipboard publication.
        self.bridge._on_workflow_state(
            WorkflowState(
                phase=WorkflowPhase.COMPLETED,
                operation_id="dictation",
                kind="dictation",
                result_text="Synthetic test",
            )
        )
        return self.clipboard.write_dictation_result(target, "Synthetic test")

    def test_completion_keeps_editor_focus_and_pastes(self):
        self.assertEqual(self.complete(), SelectionDisposition.PASTED)
        self.assertEqual(self.foreground, 77)
        self.shell.show_window.assert_not_called()
        self.shell.show_window_without_activation.assert_called_once()
        self.assertTrue(self.visible)
        self.paste.assert_called_once()

    def test_user_switching_windows_still_prevents_paste(self):
        self.assertEqual(self.complete(switch_to=88), SelectionDisposition.COPIED)
        self.assertEqual(self.foreground, 88)
        self.paste.assert_not_called()

    def test_second_dictation_keeps_the_same_target(self):
        self.assertEqual(self.complete(), SelectionDisposition.PASTED)
        self.bridge._on_workflow_state(WorkflowState())
        self.assertEqual(self.complete(), SelectionDisposition.PASTED)
        self.assertEqual(self.foreground, 77)
        self.assertEqual(self.paste.call_count, 2)

    def test_explicit_settings_request_hides_toolbar_for_native_settings(self):
        self.complete()
        self.bridge.openSettings()
        self.bridge._on_workflow_state(WorkflowState())
        self.assertEqual(self.bridge.surface, "settings")
        self.shell.show_window.assert_not_called()
        self.shell.hide_window.assert_called()
        self.assertFalse(self.visible)

    def test_shell_passive_restore_never_requests_activation(self):
        from spikes.pyside6.qt_shell import QtShell

        window = Mock()
        window.setProperty.return_value = True
        shell = QtShell(window, application=self.app)
        shell.show_window_without_activation()
        window.setProperty.assert_any_call("passivePresentation", True)
        window.show.assert_called_once()
        window.raise_.assert_not_called()
        window.requestActivate.assert_not_called()
        shell.show_window()
        window.setProperty.assert_any_call("passivePresentation", False)
        window.requestActivate.assert_called_once()

    def test_shell_keeps_unsupported_window_hidden(self):
        from spikes.pyside6.qt_shell import QtShell

        window = Mock()
        window.setProperty.return_value = False
        shell = QtShell(window, application=self.app)
        shell.show_window_without_activation()
        window.show.assert_not_called()
        window.requestActivate.assert_not_called()
