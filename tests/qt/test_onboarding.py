"""First-run setup uses isolated profiles and fake credentials only."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from tests.support.settings import (
    _repositories,
)


try:
    from PySide6.QtWidgets import QApplication  # noqa: F401
except ImportError:
    PYSIDE6_AVAILABLE = False
else:
    PYSIDE6_AVAILABLE = True
    from clarify.desktop.qml_settings import QmlSettingsController


@unittest.skipUnless(PYSIDE6_AVAILABLE, "Qt is required")
class OnboardingControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_byok_is_saved_securely_and_routes_both_stages_to_groq(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = QmlSettingsController(repositories)
            try:
                self.assertTrue(controller.onboardingRequired)
                self.assertFalse(controller.completeOnboarding("byok", ""))
                self.assertTrue(controller.onboardingRequired)
                self.assertTrue(controller.completeOnboarding("byok", "gsk_test_only"))
                self.assertFalse(controller.onboardingRequired)
                config = repositories.config.load()
                self.assertTrue(config.onboarding_completed)
                self.assertEqual(config.groq.api_key, "gsk_test_only")
                self.assertEqual(config.workflow("transcription").provider_id, "groq")
                self.assertEqual(config.workflow("refinement").provider_id, "groq")
                self.assertNotIn(
                    "gsk_test_only", Path(repositories.config.path).read_text()
                )
            finally:
                controller.shutdown()

    def test_verified_account_completes_setup_without_an_activation_choice(self):
        with TemporaryDirectory() as directory:
            account = Mock(snapshot=lambda: {"signedIn": False, "hosted": False})
            controller = QmlSettingsController(
                _repositories(directory), account_service=account
            )
            try:
                self.assertFalse(controller.completeOnboarding("account", ""))
                account.snapshot = lambda: {"signedIn": True, "hosted": False}
                self.assertTrue(controller.completeOnboarding("account", ""))
            finally:
                controller.shutdown()

    def test_failed_storage_does_not_complete_setup_and_local_has_no_cloud_fallback(
        self,
    ):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = QmlSettingsController(repositories)
            try:
                with patch.object(
                    repositories.config,
                    "apply",
                    side_effect=OSError("Test storage failure"),
                ):
                    self.assertFalse(controller.completeOnboarding("local", ""))
                self.assertTrue(controller.onboardingRequired)
                self.assertTrue(controller.completeOnboarding("local", ""))
                config = repositories.config.load()
                self.assertEqual(
                    config.workflow("transcription").provider_id, "local_asr"
                )
                self.assertFalse(config.local_asr_cloud_refinement)
            finally:
                controller.shutdown()
