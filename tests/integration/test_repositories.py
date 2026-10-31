import json
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints
from unittest.mock import patch

import repositories
from hotkey_config import HotkeyAction
from provider_adapters import OpenAICompatibleAdapter
from provider_registry import build_provider_registry
from provider_types import ProviderCapability, ProviderMetadata
from repositories import (
    CONFIG_SCHEMA_VERSION,
    AppConfig,
    LocalConfigRepository,
    LocalUsageStatsRepository,
    ConfigRepository,
    UnsupportedSchemaVersionError,
    migrate_config_payload,
)
from microphone_controls import MicrophoneSettings, RecordingControls, VADSettings
from secret_store import (
    MemorySecretStore,
    SecretStore,
    SecretStoreCorruptedError,
    SecretStoreUnavailableError,
)
from voice_translation import (
    VoiceTranslationConfig,
    VoiceTranslationLanguages,
    VoiceTranslationRoute,
)


class DeleteUnavailableStore(MemorySecretStore):
    def delete(self, _provider):
        raise SecretStoreUnavailableError("The credential store could not be updated")


class DeleteReadbackStore(MemorySecretStore):
    def delete(self, _provider):
        # Simulate a backend that reports success without removing the entry.
        return None


class ConfigurationRepositoryTests(unittest.TestCase):
    def test_config_repository_declares_typed_atomic_apply_contract(self):
        self.assertIn("apply", ConfigRepository.__abstractmethods__)
        annotations = get_type_hints(ConfigRepository.apply)
        self.assertIs(annotations["config"], AppConfig)
        self.assertIs(annotations["return"], AppConfig)

        class LoadAndSaveOnly(ConfigRepository):
            def load(self):
                return AppConfig()

            def save(self, _config):
                return None

        with self.assertRaises(TypeError):
            LoadAndSaveOnly()

    def test_voice_translation_preferences_survive_repository_round_trip(self):
        config = AppConfig.from_mapping(
            {
                "voice_translation": VoiceTranslationConfig(
                    languages=VoiceTranslationLanguages("pt-BR", "de-DE"),
                    route=VoiceTranslationRoute(
                        provider_id="groq",
                        model_id="llama-3.3-70b-versatile",
                        prompt="Translate literally.",
                    ),
                ).to_mapping(),
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = LocalConfigRepository(Path(directory) / "config.json")
            repository.save(config)
            loaded = repository.load()

        self.assertEqual(loaded.voice_translation, config.voice_translation)
        self.assertEqual(
            loaded.to_mapping()["voice_translation"]["target_language"], "de-DE"
        )

    def test_microphone_and_recording_controls_round_trip(self):
        config = AppConfig.from_mapping(
            {
                "microphone": {"selected_id": "mic-v1-usb"},
                "recording_controls": {
                    "max_duration_seconds": 120,
                    "warning_seconds": 15,
                    "vad": {
                        "enabled": True,
                        "level_threshold": 0.12,
                        "minimum_speech_seconds": 0.4,
                        "silence_duration_seconds": 1.1,
                    },
                },
            }
        )

        self.assertEqual(config.microphone, MicrophoneSettings("mic-v1-usb"))
        self.assertEqual(
            config.recording_controls.vad,
            VADSettings(
                enabled=True,
                level_threshold=0.12,
                minimum_speech_seconds=0.4,
                silence_duration_seconds=1.1,
            ),
        )
        mapped = config.to_mapping()
        self.assertEqual(mapped["microphone"]["selected_id"], "mic-v1-usb")
        self.assertEqual(
            AppConfig.from_mapping(mapped).recording_controls,
            config.recording_controls,
        )

    def test_invalid_microphone_controls_fall_back_to_safe_defaults(self):
        config = AppConfig.from_mapping(
            {
                "microphone": {"schema_version": 99, "selected_id": "bad"},
                "recording_controls": {
                    "max_duration_seconds": 1,
                    "warning_seconds": 2,
                },
            }
        )

        self.assertEqual(config.microphone, MicrophoneSettings.defaults())
        self.assertEqual(config.recording_controls, RecordingControls.defaults())

    def test_legacy_microphone_id_is_migrated_to_typed_mapping(self):
        config = AppConfig.from_mapping({"microphone_id": "mic-v1-legacy"})
        self.assertEqual(config.microphone.selected_id, "mic-v1-legacy")
        self.assertNotIn("microphone_id", config.to_mapping())

    def test_local_repository_defaults_do_not_mask_legacy_microphone_ids(self):
        for legacy_key in ("microphone_id", "selected_microphone_id"):
            with self.subTest(legacy_key=legacy_key):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "config.json"
                    path.write_text(
                        json.dumps({legacy_key: "mic-v1-legacy"}),
                        encoding="utf-8",
                    )
                    repository = LocalConfigRepository(
                        path, defaults=repositories.environment_defaults({})
                    )

                    loaded = repository.load()
                    self.assertEqual(loaded.microphone.selected_id, "mic-v1-legacy")

                    repository.save({"ui_language": "pt"})
                    persisted = json.loads(path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        persisted["microphone"]["selected_id"],
                        "mic-v1-legacy",
                    )
                    self.assertNotIn(legacy_key, persisted)
                    saved = repository.load()
                    self.assertEqual(saved.microphone.selected_id, "mic-v1-legacy")

    def test_local_repository_defaults_do_not_mask_legacy_recording_controls(self):
        legacy_recording = {
            "max_duration_seconds": 45,
            "warning_seconds": 8,
            "vad": {
                "enabled": True,
                "level_threshold": 0.15,
                "minimum_speech_seconds": 0.5,
                "silence_duration_seconds": 1.2,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"recording": legacy_recording}),
                encoding="utf-8",
            )
            repository = LocalConfigRepository(
                path, defaults=repositories.environment_defaults({})
            )

            loaded = repository.load()
            self.assertEqual(
                loaded.recording_controls,
                RecordingControls.from_mapping(legacy_recording),
            )

            repository.save({"ui_language": "pt"})
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("recording", persisted)
            self.assertEqual(
                persisted["recording_controls"]["max_duration_seconds"], 45.0
            )
            self.assertEqual(
                persisted["recording_controls"]["vad"]["silence_duration_seconds"],
                1.2,
            )
            saved = repository.load()
            self.assertEqual(saved.recording_controls, loaded.recording_controls)

    def test_local_asr_selection_and_cloud_refinement_opt_in_round_trip(self):
        config = AppConfig.from_mapping(
            {
                "transcription_provider": "local_asr",
                "local_asr_model": "ggml-small",
                "local_asr_cloud_refinement": True,
            }
        )

        self.assertEqual(config.selection.transcription_provider, "local_asr")
        self.assertEqual(config.local_asr.audio_model, "ggml-small")
        self.assertTrue(config.local_asr_cloud_refinement)
        values = config.to_mapping()
        self.assertEqual(values["transcription_provider"], "local_asr")
        self.assertTrue(values["local_asr_cloud_refinement"])

    def test_missing_refinement_preserves_legacy_capability_defaults(self):
        gemini = AppConfig.from_mapping(
            {
                "transcription_provider": "gemini",
            }
        )
        groq = AppConfig.from_mapping(
            {
                "transcription_provider": "groq",
            }
        )

        self.assertEqual(gemini.selection.refinement_provider, "openai")
        self.assertEqual(groq.selection.refinement_provider, "groq")

    def test_local_asr_is_rejected_as_refinement_provider(self):
        config = AppConfig.from_mapping(
            {
                "transcription_provider": "local_asr",
                "refinement_provider": "local_asr",
                "refinement_model": "ggml-small",
            }
        )

        self.assertEqual(config.selection.refinement_provider, "openai")
        self.assertEqual(config.selection.refinement_model, "gpt-4o-mini")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "transcription_provider": "local_asr",
                        "refinement_provider": "local_asr",
                        "refinement_model": "ggml-small",
                    }
                ),
                encoding="utf-8",
            )
            loaded = LocalConfigRepository(path).load()

        self.assertEqual(loaded.selection.refinement_provider, "openai")
        self.assertEqual(loaded.selection.refinement_model, "gpt-4o-mini")

    def test_asr_only_provider_uses_openai_refinement_fallback_on_mapping_and_load(
        self,
    ):
        registry = build_provider_registry()
        registry.register(
            OpenAICompatibleAdapter(
                ProviderMetadata(
                    provider_id="asr-only",
                    display_name="ASR Only",
                    capabilities=frozenset(
                        {
                            ProviderCapability.AUDIO_TRANSCRIPTION,
                        }
                    ),
                    default_base_url="https://asr-only.example/v1",
                    audio_model_key="asr-only_audio_model",
                    text_model_key="asr-only_text_model",
                    default_audio_model="asr-only-v1",
                    default_text_model="",
                ),
                object(),
            )
        )

        with (
            patch.object(repositories, "PROVIDER_REGISTRY", registry),
            patch.object(repositories, "SUPPORTED_PROVIDERS", registry.provider_ids),
        ):
            mapped = AppConfig.from_mapping(
                {
                    "transcription_provider": "asr-only",
                }
            )
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(
                    json.dumps(
                        {
                            "transcription_provider": "asr-only",
                        }
                    ),
                    encoding="utf-8",
                )
                loaded = LocalConfigRepository(
                    path, defaults={"refinement_provider": ""}
                ).load()

        self.assertEqual(mapped.selection.transcription_provider, "asr-only")
        self.assertEqual(mapped.selection.refinement_provider, "openai")
        self.assertEqual(mapped.selection.refinement_model, "gpt-4o-mini")
        self.assertEqual(loaded.selection.transcription_provider, "asr-only")
        self.assertEqual(loaded.selection.refinement_provider, "openai")
        self.assertEqual(loaded.selection.refinement_model, "gpt-4o-mini")

    def test_new_api_key_is_stored_outside_config_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            secrets = MemorySecretStore()
            repository = LocalConfigRepository(path, secret_store=secrets)

            repository.save(
                {
                    "openai_api_key": "test-openai-credential",
                    "ui_language": "pt",
                }
            )
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertNotIn("openai_api_key", payload)
            self.assertEqual(secrets.get("openai"), "test-openai-credential")
            self.assertEqual(repository.load().openai.api_key, "test-openai-credential")

    def test_submitted_environment_key_is_not_persisted_after_override_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            secrets = MemorySecretStore(
                {
                    "openai": "stored-test-credential",
                }
            )
            repository = LocalConfigRepository(
                path,
                environment={"OPENAI_API_KEY": "environment-test-credential"},
                secret_store=secrets,
            )

            loaded = repository.load()
            repository.save(loaded)
            restarted = LocalConfigRepository(
                path, environment={}, secret_store=secrets
            ).load()

            self.assertEqual(loaded.openai.api_key, "environment-test-credential")
            self.assertEqual(secrets.get("openai"), "stored-test-credential")
            self.assertEqual(restarted.openai.api_key, "stored-test-credential")
            self.assertNotIn(
                "openai_api_key",
                json.loads(path.read_text(encoding="utf-8")),
            )

    def test_environment_override_does_not_erase_unmigrated_legacy_key(self):
        class UnavailableStore(MemorySecretStore):
            def get(self, _provider):
                raise SecretStoreUnavailableError("The credential store is unavailable")

            def set(self, _provider, _secret):
                raise SecretStoreUnavailableError("The credential store is unavailable")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            original = {
                "openai_api_key": "recoverable-test-credential",
                "ui_language": "de",
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            repository = LocalConfigRepository(
                path,
                environment={"OPENAI_API_KEY": "environment-test-credential"},
                secret_store=UnavailableStore(),
            )

            loaded = repository.load()
            with self.assertRaises(SecretStoreUnavailableError):
                repository.save(loaded)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["openai_api_key"], "recoverable-test-credential")
            self.assertEqual(payload["ui_language"], "de")

    def test_unexpected_backend_failure_is_sanitized_and_preserves_legacy(self):
        class ExplodingStore(MemorySecretStore):
            def get(self, _provider):
                raise RuntimeError("credential=must-not-escape")

            def set(self, _provider, _secret):
                raise RuntimeError("credential=must-not-escape")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "openai_api_key": "recoverable-test-credential",
                    }
                ),
                encoding="utf-8",
            )
            repository = LocalConfigRepository(path, secret_store=ExplodingStore())

            loaded = repository.load()
            self.assertEqual(loaded.openai.api_key, "recoverable-test-credential")
            with self.assertRaises(SecretStoreUnavailableError) as raised:
                repository.save(
                    {
                        "openai_api_key": "replacement-test-credential",
                    }
                )

            self.assertNotIn("must-not-escape", str(raised.exception))
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["openai_api_key"],
                "recoverable-test-credential",
            )

    def test_explicit_key_different_from_environment_persists_for_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            secrets = MemorySecretStore(
                {
                    "openai": "stored-test-credential",
                }
            )
            repository = LocalConfigRepository(
                path,
                environment={"OPENAI_API_KEY": "environment-test-credential"},
                secret_store=secrets,
            )
            submitted = repository.load().to_legacy_mapping()
            submitted["openai_api_key"] = "explicit-test-credential"

            repository.save(submitted)
            while_environment_is_present = repository.load()
            after_environment_removal = LocalConfigRepository(
                path, environment={}, secret_store=secrets
            ).load()

            self.assertEqual(secrets.get("openai"), "explicit-test-credential")
            self.assertEqual(
                while_environment_is_present.openai.api_key,
                "environment-test-credential",
            )
            self.assertEqual(
                after_environment_removal.openai.api_key,
                "explicit-test-credential",
            )
            self.assertNotIn(
                "openai_api_key",
                json.loads(path.read_text(encoding="utf-8")),
            )

    def test_failed_config_write_restores_previous_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            secrets = MemorySecretStore(
                {
                    "groq": "original-test-credential",
                }
            )
            repository = LocalConfigRepository(path, secret_store=secrets)

            with patch(
                "repositories._atomic_write_json",
                side_effect=OSError("simulated config write failure"),
            ):
                with self.assertRaises(OSError):
                    repository.save(
                        {
                            "groq_api_key": "replacement-test-credential",
                        }
                    )

            self.assertEqual(secrets.get("groq"), "original-test-credential")
            self.assertFalse(path.exists())

    def test_blank_mapping_value_clears_secure_and_legacy_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": CONFIG_SCHEMA_VERSION,
                        "openai_api_key": "legacy-test-credential",
                    }
                ),
                encoding="utf-8",
            )
            secrets = MemorySecretStore(
                {
                    "openai": "stored-test-credential",
                }
            )
            repository = LocalConfigRepository(path, secret_store=secrets)

            repository.save({"openai_api_key": ""})

            self.assertIsNone(secrets.get("openai"))
            self.assertNotIn(
                "openai_api_key",
                json.loads(path.read_text(encoding="utf-8")),
            )

    def test_legacy_flat_config_loads_and_unknown_fields_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "transcription_provider": "openai",
                        "openai_api_key": "secret",
                        "openai_audio_model": "whisper 1",
                        "unknown_future_setting": {"unsafe": True},
                    }
                ),
                encoding="utf-8",
            )

            config = LocalConfigRepository(path).load()

        self.assertEqual(config.selection.transcription_provider, "openai")
        self.assertEqual(config.openai.api_key, "secret")
        self.assertEqual(config.openai.audio_model, "whisper-1")
        self.assertEqual(config.gemini.text_model, "")
        self.assertFalse(hasattr(config, "unknown_future_setting"))

    def test_first_run_defaults_include_voice_hotkey(self):
        with tempfile.TemporaryDirectory() as directory:
            config = LocalConfigRepository(Path(directory) / "config.json").load()

        self.assertIn(HotkeyAction.VOICE_TRANSLATION, config.hotkeys.hotkeys)

    def test_invalid_values_fall_back_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "transcription_provider": {"not": "a string"},
                        "ui_language": 42,
                        "autostart": "yes",
                    }
                ),
                encoding="utf-8",
            )
            config = LocalConfigRepository(path).load()

        self.assertEqual(config.selection.transcription_provider, "gemini")
        self.assertEqual(config.ui.language, "en")
        self.assertFalse(config.startup.autostart)

    def test_save_round_trip_writes_explicit_schema_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            repository = LocalConfigRepository(path)
            repository.save(
                AppConfig.from_mapping(
                    {
                        "ui_mode": "transcription",
                        "ui_language": "pt",
                    }
                )
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            loaded = repository.load()

        self.assertEqual(payload["schema_version"], CONFIG_SCHEMA_VERSION)
        self.assertEqual(loaded.ui.mode, "prompt")
        self.assertEqual(loaded.ui.language, "pt")
        self.assertNotIn("unknown_future_setting", payload)

    def test_legacy_adapter_preserves_autostart_on_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = LocalConfigRepository(Path(directory) / "config.json")
            repository.save({"autostart": True})
            config = repository.load()
            legacy = config.to_legacy_mapping()
            repository.save(legacy)

            self.assertTrue(legacy["autostart"])
            self.assertTrue(repository.load().startup.autostart)


class ConfigurationMigrationTests(unittest.TestCase):
    def test_plaintext_keys_migrate_after_verified_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "gemini_api_key": "test-gemini-credential",
                        "openai_api_key": "test-openai-credential",
                        "groq_api_key": "test-groq-credential",
                        "ui_language": "de",
                    }
                ),
                encoding="utf-8",
            )
            secrets = MemorySecretStore()
            repository = LocalConfigRepository(path, secret_store=secrets)

            loaded = repository.load()
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(loaded.gemini.api_key, "test-gemini-credential")
            self.assertEqual(loaded.openai.api_key, "test-openai-credential")
            self.assertEqual(loaded.groq.api_key, "test-groq-credential")
            self.assertFalse(
                {
                    "gemini_api_key",
                    "openai_api_key",
                    "groq_api_key",
                }
                & payload.keys()
            )

    def test_failed_migration_leaves_plaintext_recoverable(self):
        class UnavailableStore(SecretStore):
            def get(self, _provider):
                raise SecretStoreUnavailableError("The credential store is unavailable")

            def set(self, _provider, _secret):
                raise SecretStoreUnavailableError("The credential store is unavailable")

            def delete(self, _provider):
                raise SecretStoreUnavailableError("The credential store is unavailable")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            original = {
                "openai_api_key": "recoverable-test-credential",
                "ui_language": "es",
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            repository = LocalConfigRepository(path, secret_store=UnavailableStore())

            loaded = repository.load()

            self.assertEqual(loaded.openai.api_key, "recoverable-test-credential")
            persisted = json.loads(path.read_text(encoding="utf-8"))
            for key, value in original.items():
                self.assertEqual(persisted[key], value)
            self.assertEqual(persisted["ui_mode"], "prompt")

            repository.save({"ui_language": "de"})
            after_partial_save = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                after_partial_save["openai_api_key"],
                "recoverable-test-credential",
            )
            self.assertEqual(after_partial_save["ui_language"], "de")
            with self.assertRaises(SecretStoreUnavailableError):
                repository.save(
                    {
                        "openai_api_key": "replacement-test-credential",
                    }
                )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                after_partial_save,
            )

    def test_mismatched_readback_does_not_remove_legacy_key(self):
        class MismatchedStore(MemorySecretStore):
            def get(self, provider):
                value = super().get(provider)
                return f"{value}-mismatch" if value else None

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "groq_api_key": "recoverable-test-credential",
                    }
                ),
                encoding="utf-8",
            )
            repository = LocalConfigRepository(path, secret_store=MismatchedStore())

            loaded = repository.load()

            self.assertEqual(loaded.groq.api_key, "recoverable-test-credential")
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["groq_api_key"],
                "recoverable-test-credential",
            )

    def test_failed_cleanup_write_keeps_legacy_key_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            original = {
                "openai_api_key": "recoverable-test-credential",
                "ui_language": "pt",
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            secrets = MemorySecretStore()
            repository = LocalConfigRepository(path, secret_store=secrets)

            with patch(
                "repositories._atomic_write_json",
                side_effect=OSError("simulated cleanup failure"),
            ):
                loaded = repository.load()

            self.assertEqual(loaded.openai.api_key, "recoverable-test-credential")
            persisted = json.loads(path.read_text(encoding="utf-8"))
            for key, value in original.items():
                self.assertEqual(persisted[key], value)
            self.assertEqual(persisted, original)
            self.assertEqual(secrets.get("openai"), "recoverable-test-credential")

    def test_corrupted_store_preserves_legacy_key(self):
        class CorruptedStore(MemorySecretStore):
            def get(self, _provider):
                raise SecretStoreCorruptedError("A credential-store entry is invalid")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "gemini_api_key": "recoverable-test-credential",
                    }
                ),
                encoding="utf-8",
            )
            repository = LocalConfigRepository(path, secret_store=CorruptedStore())

            loaded = repository.load()

            self.assertEqual(loaded.gemini.api_key, "recoverable-test-credential")
            self.assertIn(
                "gemini_api_key",
                json.loads(path.read_text(encoding="utf-8")),
            )

    def test_legacy_migration_is_ordered_and_idempotent(self):
        legacy = {"ui_language": "de"}
        migrated = migrate_config_payload(legacy)

        self.assertEqual(migrated["schema_version"], CONFIG_SCHEMA_VERSION)
        self.assertEqual(migrate_config_payload(migrated), migrated)

    def test_future_schema_is_read_compatibly(self):
        future = {
            "schema_version": CONFIG_SCHEMA_VERSION + 10,
            "ui_language": "es",
            "unknown": object(),
        }
        migrated = migrate_config_payload(future)

        self.assertEqual(migrated["schema_version"], CONFIG_SCHEMA_VERSION + 10)
        self.assertEqual(migrated["ui_language"], "es")

    def test_future_schema_loads_but_save_refuses_a_downgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": CONFIG_SCHEMA_VERSION + 1,
                        "ui_language": "es",
                        "future_setting": {"keep": "me"},
                    }
                ),
                encoding="utf-8",
            )
            original = path.read_bytes()
            repository = LocalConfigRepository(path)
            config = repository.load()

            self.assertEqual(config.ui.language, "es")
            with self.assertRaises(UnsupportedSchemaVersionError):
                repository.save(config)

            self.assertEqual(path.read_bytes(), original)

    def test_future_schema_save_is_refused_without_prior_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": CONFIG_SCHEMA_VERSION + 1,
                        "future_setting": {"keep": "me"},
                    }
                ),
                encoding="utf-8",
            )
            original = path.read_bytes()

            with self.assertRaises(UnsupportedSchemaVersionError):
                LocalConfigRepository(path).save({"ui_language": "pt"})

            self.assertEqual(path.read_bytes(), original)

    def test_future_schema_change_between_load_and_save_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"schema_version": CONFIG_SCHEMA_VERSION}), encoding="utf-8"
            )
            repository = LocalConfigRepository(path)
            config = repository.load()
            path.write_text(
                json.dumps(
                    {
                        "schema_version": CONFIG_SCHEMA_VERSION + 1,
                        "future_setting": {"keep": "me"},
                    }
                ),
                encoding="utf-8",
            )
            original = path.read_bytes()

            with self.assertRaises(UnsupportedSchemaVersionError):
                repository.save(config)

            self.assertEqual(path.read_bytes(), original)


class UsageStatisticsRepositoryTests(unittest.TestCase):
    def test_invalid_payload_and_unknown_events_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage_stats.json"
            path.write_text(
                json.dumps({"events": [{"type": "recording"}, "bad"]}), encoding="utf-8"
            )
            repository = LocalUsageStatsRepository(path)
            self.assertEqual(repository.load_events(), [{"type": "recording"}])

    def test_append_is_atomic_and_preserves_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage_stats.json"
            repository = LocalUsageStatsRepository(path)
            repository.append({"type": "recording", "models": []})
            repository.append({"type": "rewrite", "models": []})
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            [event["type"] for event in payload["events"]], ["recording", "rewrite"]
        )
        self.assertFalse(list(Path(directory).glob("*.tmp")))

    def test_future_schema_append_is_refused_without_rewriting_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage_stats.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "future_setting": {"keep": "me"},
                        "events": [],
                    }
                ),
                encoding="utf-8",
            )
            original = path.read_bytes()

            with self.assertRaises(UnsupportedSchemaVersionError):
                LocalUsageStatsRepository(path).append({"type": "recording"})

            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
