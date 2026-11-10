"""Policy, persistence and downgrade contracts; no language quality claims."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repositories import (
    AppConfig,
    LocalConfigRepository,
    UnsupportedSchemaVersionError,
    migrate_config_payload,
)
from secret_store import MemorySecretStore
from shared.dictation_policy import (
    DictationCleanupLevel,
    DictationCleanupPolicy,
    cleanup_level,
)


class DictationPolicyTests(unittest.TestCase):
    def test_new_profile_defaults_do_not_change_an_existing_legacy_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            repo = LocalConfigRepository(
                path, environment={}, secret_store=MemorySecretStore()
            )
            fresh = repo.load()
            self.assertEqual(fresh.ui.language, "auto")
            self.assertEqual(fresh.dictation_cleanup_level, "clarity")
            self.assertEqual(fresh.application_writing_styles.default_style, "natural")
            repo.apply(fresh)
            self.assertEqual(repo.load().dictation_cleanup_level, "clarity")
            path.write_text(json.dumps({"schema_version": 6, "history_enabled": True}))
            legacy = repo.load()
            self.assertEqual(legacy.ui.language, "en")
            self.assertIsNone(legacy.dictation_cleanup_level)
            self.assertIsNone(legacy.application_writing_styles.default_style)

    def test_enum_is_bounded_and_policy_is_immutable(self):
        for invalid in ("", "legacy", "Preserve", "formal", 1, [], {}):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                cleanup_level(invalid)
        policy = DictationCleanupPolicy(DictationCleanupLevel.PRESERVE)
        with self.assertRaises(FrozenInstanceError):
            policy.requested = DictationCleanupLevel.CLARITY
        self.assertIsNone(cleanup_level(None))

    def test_light_preserves_words_numbers_negations_uncertainty_and_corrections(self):
        policy = DictationCleanupPolicy(DictationCleanupLevel.LIGHT)
        for original, expected in (
            (
                "João,  não envie 15,5. Talvez terça, quer dizer, sexta.",
                "João, não envie 15,5. Talvez terça, quer dizer, sexta.",
            ),
            ("May  May not send 42. No, 43.", "May May not send 42. No, 43."),
            (
                "No  envíes 1.200,5. Quizás sí, o no.",
                "No envíes 1.200,5. Quizás sí, o no.",
            ),
            ("Да,  нет.\n\n不是  12。", "Да, нет.\n\n不是 12。"),
        ):
            with self.subTest(original=original):
                self.assertEqual(policy.prepare_source(original), expected)

    def test_v2_migration_keeps_legacy_and_roundtrip_is_atomic(self):
        old = {"schema_version": 2, "history_enabled": True}
        migrated = migrate_config_payload(old)
        self.assertEqual(migrated["schema_version"], 6)
        self.assertEqual(migrate_config_payload(migrated), migrated)
        self.assertIsNone(AppConfig.from_mapping(migrated).dictation_cleanup_level)
        self.assertIsNone(
            AppConfig.from_mapping(
                {"dictation_cleanup_level": "unknown"}
            ).dictation_cleanup_level
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            repo = LocalConfigRepository(path, secret_store=MemorySecretStore())
            repo.save(
                replace(
                    AppConfig(), dictation_cleanup_level=DictationCleanupLevel.LIGHT
                )
            )
            original = path.read_bytes()
            self.assertEqual(json.loads(original)["dictation_cleanup_level"], "light")
            self.assertEqual(repo.load().dictation_cleanup_level, "light")
            # Exercise the same future-schema guard used by shipped v2 readers.
            with patch("repositories.CONFIG_SCHEMA_VERSION", 2):
                repo.load()
                with self.assertRaises(UnsupportedSchemaVersionError):
                    repo.save({"history_enabled": False})
            self.assertEqual(path.read_bytes(), original)
