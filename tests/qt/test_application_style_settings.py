from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from PySide6.QtWidgets import QApplication
from clarify.desktop.qml_settings import QmlSettingsController
from clarify.desktop.qml_application_style import style_caption
from repositories import (
    ApplicationRepositories,
    LocalConfigRepository,
    LocalUsageStatsRepository,
)
from secret_store import MemorySecretStore
from workflows import WorkflowState, WorkflowPhase, WorkflowKind


class ApplicationStyleSettingsTests(unittest.TestCase):
    def test_missing_or_invalid_executable_keeps_last_known_application(self):
        from unittest.mock import Mock
        from clarify.desktop.qml_quick_paste import QuickPasteController
        from workflows import SelectionTarget

        window = Mock()
        window.isActive.return_value = False
        window.winId.return_value = 1
        clipboard = Mock()
        editor = SelectionTarget(2, r"C:\Apps\Editor.exe")
        clipboard.capture_target.return_value = editor
        controller = QuickPasteController(
            clipboard, lambda callback: callback(), lambda: [window], lambda: None
        )
        try:
            for executable in (None, "", "editor.exe", r"C:\Apps\NUL.exe"):
                with self.subTest(executable=executable):
                    clipboard.capture_target.return_value = SelectionTarget(
                        3, executable
                    )
                    self.assertIsNone(controller.capture_target())
                    self.assertEqual(controller.target, editor)
        finally:
            controller.timer.stop()

    def test_native_settings_outside_qt_windows_preserves_external_app(self):
        from unittest.mock import Mock
        from clarify.desktop.qml_quick_paste import QuickPasteController
        from workflows import SelectionTarget

        window = Mock()
        window.isActive.return_value = False
        window.winId.return_value = 1
        clipboard = Mock()
        editor = SelectionTarget(2, r"C:\Apps\Editor.exe")
        clipboard.capture_target.return_value = editor
        controller = QuickPasteController(
            clipboard, lambda callback: callback(), lambda: [window], lambda: None
        )
        controller.excluded_executable = lambda: r"C:\Clarify\clarify-settings.exe"
        try:
            clipboard.capture_target.return_value = SelectionTarget(
                3, "c:/CLARIFY/CLARIFY-SETTINGS.EXE"
            )
            self.assertEqual(controller.capture_target(), editor)
            self.assertEqual(controller.target, editor)
        finally:
            controller.timer.stop()

    def test_unavailable_foreground_defaults_without_losing_capsule_target(self):
        from unittest.mock import Mock
        from clarify.desktop.qml_quick_paste import QuickPasteController
        from workflows import SelectionTarget

        window = Mock()
        window.isActive.return_value = False
        window.winId.return_value = 1
        clipboard = Mock()
        target = SelectionTarget(2, r"C:\Apps\Editor.exe")
        clipboard.capture_target.return_value = target
        controller = QuickPasteController(
            clipboard, lambda callback: callback(), lambda: [window], lambda: None
        )
        try:
            self.assertEqual(controller.capture_target(), target)
            window.isActive.return_value = True
            self.assertEqual(controller.capture_target(), target)
            window.isActive.return_value = False
            clipboard.capture_target.return_value = None
            self.assertIsNone(controller.capture_target())
            self.assertEqual(controller.target, target)
        finally:
            controller.timer.stop()

    def test_real_capsule_shows_selection_and_confirmed_result_then_expires(self):
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                str(
                    Path(__file__).resolve().parents[1]
                    / "support/qml_application_style_smoke.py"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_style_preference_saves_only_its_rule_and_can_remove_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repositories = ApplicationRepositories(
                config=LocalConfigRepository(
                    root / "config.json", secret_store=MemorySecretStore()
                ),
                usage_stats=LocalUsageStatsRepository(root / "usage_stats.json"),
            )
            target = SimpleNamespace(executable=r"C:\Apps\Editor.exe")
            from tests.support.settings import _MicrophoneBackend
            from microphone_controls import MicrophoneInventory

            settings = QmlSettingsController(
                repositories,
                application_target=lambda: target,
                microphone_backend=_MicrophoneBackend(
                    MicrophoneInventory.unavailable("fixture")
                ),
            )
            try:
                settings.selectWorkflow("refinement")
                settings.setRoutePrompt("Unrelated unsaved text")
                before = repositories.config.load().workflow("refinement").prompt
                self.assertTrue(
                    settings.savePreference(
                        "setApplicationWritingStyle", [target.executable, "informal"]
                    )
                )
                self.assertEqual(
                    settings.applicationWritingStyles,
                    [{"executable": r"c:\apps\editor.exe", "style": "informal"}],
                )
                self.assertEqual(settings.applicationStyleTarget, r"c:\apps\editor.exe")
                self.assertEqual(
                    repositories.config.load().workflow("refinement").prompt, before
                )
                self.assertEqual(settings.routePrompt, "Unrelated unsaved text")
                self.assertTrue(
                    settings.savePreference(
                        "setApplicationWritingStyle", [target.executable, ""]
                    )
                )
                self.assertEqual(settings.applicationWritingStyles, [])
            finally:
                settings.shutdown()

    def test_caption_distinguishes_selection_application_default_and_fallback(self):
        state = WorkflowState(
            phase=WorkflowPhase.RECORDING,
            kind=WorkflowKind.DICTATION,
            writing_style_requested="informal",
        )
        from dataclasses import replace
        from unittest.mock import patch

        with patch("shared.localization.device_language", return_value="en"):
            self.assertEqual(style_caption(state), "Selected: Informal")
            self.assertEqual(
                style_caption(
                    replace(
                        state,
                        phase=WorkflowPhase.COMPLETED,
                        writing_style_applied="informal",
                        writing_style_status="applied",
                    )
                ),
                "Applied: Informal",
            )
            self.assertEqual(
                style_caption(replace(state, phase=WorkflowPhase.COMPLETED)),
                "Style not applied",
            )
            self.assertEqual(
                style_caption(replace(state, writing_style_requested=None)),
                "Style: Default",
            )
