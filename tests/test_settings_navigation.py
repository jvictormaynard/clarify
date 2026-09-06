"""Settings must open after completion and after either menu close ordering."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication
from spikes.pyside6.qml_bridge import QmlWorkflowBridge
from workflows import WorkflowState, WorkflowPhase

class SettingsNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_completed_dictation_releases_then_opens_settings(self):
        service = SimpleNamespace(state=WorkflowState(), subscribe=lambda listener: None, finish=Mock())
        bridge = QmlWorkflowBridge(service, paste_runner=Mock())
        bridge._on_workflow_state(WorkflowState(phase=WorkflowPhase.COMPLETED, operation_id="done", kind="dictation", result_text="kept"))
        self.assertEqual(bridge.surface, "idle")
        bridge.openSettings()
        service.finish.assert_called_once_with("done")
        bridge._on_workflow_state(WorkflowState())
        self.assertEqual(bridge.surface, "settings")
        self.assertTrue(bridge.canPasteLastTranscription)

    def test_repeated_click_during_finish_opens_once(self):
        queued = []
        service = SimpleNamespace(state=WorkflowState(), subscribe=lambda listener: None, finish=Mock())
        bridge = QmlWorkflowBridge(service, dispatch_runner=queued.append)
        bridge._on_workflow_state(WorkflowState(phase=WorkflowPhase.COMPLETED, operation_id="done"))
        bridge.openSettings()
        bridge.openSettings()
        self.assertEqual(len(queued), 1)
        queued.pop()()
        bridge._on_workflow_state(WorkflowState())
        self.assertEqual(bridge.surface, "settings")
        service.finish.assert_called_once()

    def test_active_recording_is_not_interrupted(self):
        service = SimpleNamespace(state=WorkflowState(phase=WorkflowPhase.RECORDING), subscribe=lambda listener: None, finish=Mock())
        bridge = QmlWorkflowBridge(service)
        bridge.openSettings()
        self.assertEqual(bridge.surface, "recording")
        service.finish.assert_not_called()

    def test_menu_action_runs_once_for_both_close_orders(self):
        import os
        from pathlib import Path
        import subprocess
        import sys
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("qml_settings_menu_smoke.py"))], capture_output=True, text=True, timeout=15, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_settings_preserves_failed_operation_for_retry(self):
        service = SimpleNamespace(state=WorkflowState(phase=WorkflowPhase.FAILED, operation_id="retry"), subscribe=lambda listener: None, finish=Mock())
        bridge = QmlWorkflowBridge(service)
        bridge.openSettings()
        self.assertEqual(bridge.surface, "settings")
        service.finish.assert_not_called()
        bridge.closeSettings()
        self.assertEqual(bridge.surface, "error")
        service.finish.assert_not_called()

    def test_settings_restores_window_after_completed_workflow(self):
        from spikes.pyside6.qml_app import _WorkflowWindowVisibility
        service = SimpleNamespace(state=WorkflowState(), subscribe=lambda listener: None, finish=Mock())
        bridge = QmlWorkflowBridge(service)
        bridge._on_workflow_state(WorkflowState(phase=WorkflowPhase.COMPLETED, operation_id="done"))
        window = Mock()
        window.isVisible.return_value = True
        shell = Mock()
        coordinator = _WorkflowWindowVisibility(bridge, shell, window)
        bridge.openSettings()
        bridge._on_workflow_state(WorkflowState())
        self.assertEqual(bridge.surface, "settings")
        shell.show_window.assert_called_once()
        self.assertIsNone(coordinator._restore_visible)
