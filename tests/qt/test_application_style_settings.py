from pathlib import Path
import tempfile
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

    def test_macos_settings_does_not_replace_the_external_target(self):
        from unittest.mock import Mock
        from clarify.desktop.qml_quick_paste import QuickPasteController
        from workflows import SelectionTarget

        clipboard = Mock(platform_name="Darwin")
        applications = Path(tempfile.gettempdir()) / "Applications"
        editor = SelectionTarget(
            object(), str(applications / "Editor.app/Contents/MacOS/Editor")
        )
        clipboard.capture_target.return_value = editor
        controller = QuickPasteController(
            clipboard, lambda callback: callback(), list, lambda: None
        )
        shell = str(applications / "Clarify Desktop.app/Contents/MacOS/Clarify Desktop")
        controller.excluded_executable = lambda: shell
        try:
            self.assertEqual(controller.capture_target(), editor)
            clipboard.capture_target.return_value = SelectionTarget(object(), shell)
            self.assertEqual(controller.capture_target(), editor)
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

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_general_tone_saves_without_other_drafts_and_app_rule_command_is_retired(
        self,
    ):
        from clarify.desktop.qml_web_settings import SettingsProtocol

        with tempfile.TemporaryDirectory() as directory:
            repositories = ApplicationRepositories(
                LocalConfigRepository(
                    Path(directory) / "config.json", secret_store=MemorySecretStore()
                ),
                LocalUsageStatsRepository(Path(directory) / "usage.json"),
            )
            settings = QmlSettingsController(repositories)
            try:
                original = repositories.config.load()
                settings.setLanguage("pt")
                settings.setProviderApiKey("pending-key")
                self.assertTrue(
                    settings.savePreference("setDictationWritingStyle", ["formal"])
                )
                saved = repositories.config.load()
                self.assertEqual(saved.dictation_writing_style, "formal")
                self.assertEqual(saved.ui, original.ui)
                self.assertEqual(saved.gemini.api_key, original.gemini.api_key)
                reply = SettingsProtocol(settings).dispatch(
                    {
                        "id": 1,
                        "method": "savePreference",
                        "args": [
                            "setApplicationWritingStyle",
                            [r"C:\Apps\Editor.exe", "casual"],
                        ],
                    }
                )
                self.assertIn("error", reply)
                self.assertEqual(repositories.config.load(), saved)
                self.assertNotIn(
                    "applicationWritingStyles", SettingsProtocol(settings).snapshot()
                )
                self.assertNotIn(
                    "applicationStyleTarget", SettingsProtocol(settings).snapshot()
                )
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
                "Style: Natural",
            )
