"""First-run setup uses isolated profiles and fake credentials only."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from repositories import LocalConfigRepository
from secret_store import MemorySecretStore


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
