"""First-run setup uses isolated profiles and fake credentials only."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from repositories import LocalConfigRepository
from secret_store import MemorySecretStore
from test_pyside6_qml_settings import (
    PYSIDE6_AVAILABLE,
    QmlSettingsController,
    _repositories,
)


class OnboardingPersistenceTests(unittest.TestCase):
    def test_fresh_profile_requires_setup_and_incomplete_setup_survives_save(self):
        with TemporaryDirectory() as directory:
            repo = LocalConfigRepository(
                Path(directory) / "config.json", secret_store=MemorySecretStore()
            )
            self.assertFalse(repo.load().onboarding_completed)
            repo.apply(repo.load())
            self.assertFalse(repo.load().onboarding_completed)

    def test_old_profile_keeps_preferences_and_does_not_force_setup(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"ui_language": "en", "transcription_provider": "groq"})
            )
            repo = LocalConfigRepository(path, secret_store=MemorySecretStore())
            self.assertTrue(repo.load().onboarding_completed)
            self.assertEqual(repo.load().ui.language, "en")


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

    def test_account_requires_verified_session_and_explicit_hosted_choice(self):
        with TemporaryDirectory() as directory:
            account = Mock(snapshot=lambda: {"signedIn": False, "hosted": False})
            controller = QmlSettingsController(
                _repositories(directory), account_service=account
            )
            try:
                self.assertFalse(controller.completeOnboarding("account", ""))
                account.snapshot = lambda: {"signedIn": True, "hosted": False}
                self.assertFalse(controller.completeOnboarding("account", ""))
                account.snapshot = lambda: {"signedIn": True, "hosted": True}
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
