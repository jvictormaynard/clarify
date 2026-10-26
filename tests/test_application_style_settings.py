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
            settings = QmlSettingsController(
                repositories, application_target=lambda: target
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
