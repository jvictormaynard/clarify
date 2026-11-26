"""First-run setup uses isolated profiles and fake credentials only."""

import unittest
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from local_asr_product import LocalASRProductState
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

    def test_macos_onboarding_resumes_practice_until_explicitly_finished(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = QmlSettingsController(repositories)
            try:
                with patch.object(sys, "platform", "darwin"):
                    self.assertTrue(controller.completeOnboarding("local"))
                self.assertTrue(controller.onboardingPracticePending)
            finally:
                controller.shutdown()
            reopened = QmlSettingsController(_repositories(directory))
            try:
                practice = Mock(command=Mock(return_value=True))
                reopened.bindPractice(practice)
                self.assertTrue(reopened.onboardingPracticePending)
                self.assertTrue(reopened.practiceCommand("close"))
                self.assertTrue(reopened.onboardingPracticePending)
                self.assertTrue(reopened.practiceCommand("done"))
                self.assertFalse(reopened.onboardingPracticePending)
                self.assertFalse(repositories.config.load().onboarding_practice_pending)
            finally:
                reopened.shutdown()

    def test_macos_cloud_speech_setup_completes_without_starting_practice(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            product = Mock(state=LocalASRProductState("missing"), busy=False)
            controller = QmlSettingsController(repositories, local_product=product)
            try:
                practice = Mock()
                controller.bindPractice(practice)
                mac_platform = Mock(wraps=sys, platform="darwin")
                with patch("clarify.desktop.qml_settings.sys", mac_platform):
                    product.installer.platform_supported.return_value = True
                    self.assertFalse(controller.personalSetupState["cloudSpeechSetup"])
                    product.installer.platform_supported.return_value = False
                    self.assertTrue(controller.personalSetupState["cloudSpeechSetup"])
                    self.assertTrue(
                        controller.completeOnboarding("cloud-settings"),
                        controller.lastError,
                    )
                self.assertFalse(controller.onboardingRequired)
                self.assertFalse(repositories.config.load().onboarding_practice_pending)
                practice.command.assert_not_called()
            finally:
                controller.shutdown()

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
