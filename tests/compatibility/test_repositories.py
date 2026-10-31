import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hotkey_config import HotkeyAction
from repositories import (
    LocalConfigRepository,
    LocalUsageStatsRepository,
)
from secret_store import (
    MemorySecretStore,
    SecretStoreUnavailableError,
)


class DeleteUnavailableStore(MemorySecretStore):
    def delete(self, _provider):
        raise SecretStoreUnavailableError("The credential store could not be updated")


class DeleteReadbackStore(MemorySecretStore):
    def delete(self, _provider):
        # Simulate a backend that reports success without removing the entry.
        return None


class ConfigurationRepositoryTests(unittest.TestCase):
    def test_blank_provider_input_preserves_loaded_credential(self):
        import app

        original = app.APP_CONFIG.copy()
        try:
            app.APP_CONFIG["openai_api_key"] = "stored-test-credential"
            self.assertEqual(
                app._provider_key_candidate("openai", ""),
                "stored-test-credential",
            )
            self.assertEqual(
                app._provider_key_candidate("openai", "replacement-test-credential"),
                "replacement-test-credential",
            )
        finally:
            app.APP_CONFIG.clear()
            app.APP_CONFIG.update(original)

    def test_deactivate_rolls_back_on_delete_unavailable_or_failed_readback(self):
        import app
        from repositories import ApplicationRepositories

        for store_type in (DeleteUnavailableStore, DeleteReadbackStore):
            with (
                self.subTest(store=store_type.__name__),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "config.json"
                secrets = store_type({"openai": "stored-test-credential"})
                repository = LocalConfigRepository(
                    path, environment={}, secret_store=secrets
                )
                bundle = ApplicationRepositories(
                    config=repository,
                    usage_stats=LocalUsageStatsRepository(
                        Path(directory) / "stats.json"
                    ),
                )
                original = app.APP_CONFIG.copy()
                try:
                    app._activate_repositories(bundle)
                    before = app.APP_CONFIG.copy()

                    provider_state = {
                        "status": "active",
                        "models": ["whisper-1"],
                        "text_models": ["gpt-4o-mini"],
                        "error": "",
                        "feedback": "",
                        "generation": 4,
                    }
                    before_state = provider_state.copy()
                    feedback = "Could not update credentials. Try again."

                    succeeded = app._deactivate_provider_for_ui(
                        "openai",
                        "https://api.openai.com/v1",
                        provider_state,
                        feedback,
                        bundle,
                    )

                    self.assertFalse(succeeded)
                    self.assertEqual(app.APP_CONFIG, before)
                    self.assertEqual(
                        {
                            key: value
                            for key, value in provider_state.items()
                            if key != "feedback"
                        },
                        {
                            key: value
                            for key, value in before_state.items()
                            if key != "feedback"
                        },
                    )
                    self.assertEqual(provider_state["feedback"], feedback)
                    self.assertEqual(secrets.get("openai"), "stored-test-credential")
                    self.assertEqual(
                        LocalConfigRepository(
                            path,
                            environment={},
                            secret_store=secrets,
                        )
                        .load()
                        .openai.api_key,
                        "stored-test-credential",
                    )
                finally:
                    app.APP_CONFIG.clear()
                    app.APP_CONFIG.update(original)

    def test_legacy_config_does_not_gain_voice_hotkey_on_upgrade(self):
        import app

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "transcription_provider": "openai",
                        "ui_language": "en",
                    }
                ),
                encoding="utf-8",
            )

            config = LocalConfigRepository(path, defaults=app.DEFAULT_CONFIG).load()

        self.assertNotIn(HotkeyAction.VOICE_TRANSLATION, config.hotkeys.hotkeys)

    def test_injected_repository_becomes_the_app_compatibility_source(self):
        import app
        from repositories import ApplicationRepositories

        with tempfile.TemporaryDirectory() as directory:
            default_path = Path(directory) / "default.json"
            injected_path = Path(directory) / "injected.json"
            default = LocalConfigRepository(default_path)
            injected = LocalConfigRepository(injected_path)
            default.save({"transcription_provider": "gemini", "ui_mode": "prompt"})
            injected.save(
                {
                    "transcription_provider": "openai",
                    "openai_api_key": "injected-key",
                    "ui_mode": "transcription",
                }
            )
            bundle = ApplicationRepositories(
                config=injected,
                usage_stats=LocalUsageStatsRepository(Path(directory) / "stats.json"),
            )
            default_bundle = ApplicationRepositories(
                config=default,
                usage_stats=LocalUsageStatsRepository(
                    Path(directory) / "default-stats.json"
                ),
            )
            original = app.APP_CONFIG.copy()
            try:
                with patch.object(app, "APP_REPOSITORIES", default_bundle):
                    app._activate_repositories(bundle)
                    self.assertEqual(app.APP_CONFIG["transcription_provider"], "openai")
                    self.assertEqual(app.APP_CONFIG["openai_api_key"], "injected-key")
                    self.assertEqual(app.APP_CONFIG["ui_mode"], "prompt")
                    app._save_app_config(bundle)
                    self.assertEqual(
                        injected.load().selection.transcription_provider, "openai"
                    )

                    # This is the lifecycle used by a later App() with no
                    # explicit bundle: the default repository must be loaded
                    # again instead of retaining injected compatibility state.
                    app._activate_repositories(None)
                    self.assertEqual(app.APP_CONFIG["transcription_provider"], "gemini")
                    self.assertEqual(app.APP_CONFIG["ui_mode"], "prompt")
                    self.assertEqual(app.APP_CONFIG["openai_api_key"], "")
                    self.assertEqual(
                        default.load().selection.transcription_provider, "gemini"
                    )
            finally:
                app.APP_CONFIG.clear()
                app.APP_CONFIG.update(original)

    def test_autostart_apply_updates_registry_and_repository_together(self):
        import app
        from repositories import ApplicationRepositories

        class Key:
            def __init__(self, registry):
                self.registry = registry

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Registry:
            HKEY_CURRENT_USER = 1
            REG_SZ = 1

            def __init__(self):
                self.values = {}
                self.types = {}

            def CreateKey(self, *_args):
                return Key(self)

            def OpenKey(self, *_args):
                return Key(self)

            def SetValueEx(self, _key, name, _reserved, _kind, value):
                self.values[name] = value
                self.types[name] = _kind

            def QueryValueEx(self, _key, name):
                if name not in self.values:
                    raise FileNotFoundError(name)
                return self.values[name], self.types.get(name, self.REG_SZ)

            def DeleteValue(self, _key, name):
                if name not in self.values:
                    raise FileNotFoundError(name)
                del self.values[name]

        class FailingConfigRepository(LocalConfigRepository):
            def save(self, _config):
                raise OSError("simulated config write failure")

        with tempfile.TemporaryDirectory() as directory:
            config_repository = LocalConfigRepository(Path(directory) / "config.json")
            config_repository.save({"autostart": True})
            bundle = ApplicationRepositories(
                config=config_repository,
                usage_stats=LocalUsageStatsRepository(Path(directory) / "stats.json"),
            )
            registry = Registry()
            original = app.APP_CONFIG.copy()
            try:
                app._activate_repositories(bundle)
                failing_bundle = ApplicationRepositories(
                    config=FailingConfigRepository(config_repository.path),
                    usage_stats=bundle.usage_stats,
                )
                # The persisted value is true while the Registry entry is
                # absent. A failed Apply must preserve that divergence.
                with patch.object(app, "IS_WIN", True):
                    with self.assertRaises(OSError):
                        app._persist_autostart_preference(
                            False, failing_bundle, registry
                        )
                self.assertTrue(app.APP_CONFIG["autostart"])
                self.assertNotIn("Clarify", registry.values)
                self.assertTrue(config_repository.load().startup.autostart)

                with patch.object(app, "IS_WIN", True):
                    app._persist_autostart_preference(False, bundle, registry)
                self.assertFalse(app.APP_CONFIG["autostart"])
                self.assertNotIn("Clarify", registry.values)
                self.assertFalse(config_repository.load().startup.autostart)

                with patch.object(app, "IS_WIN", True):
                    app._persist_autostart_preference(True, bundle, registry)
                self.assertTrue(app.APP_CONFIG["autostart"])
                self.assertIn("Clarify", registry.values)
                self.assertTrue(config_repository.load().startup.autostart)

                custom_command = r"C:\Legacy\Clarify.exe --custom-start"
                registry.values["Clarify"] = custom_command
                registry.types["Clarify"] = 42
                with patch.object(app, "IS_WIN", True):
                    with self.assertRaises(OSError):
                        app._persist_autostart_preference(
                            False, failing_bundle, registry
                        )
                self.assertEqual(registry.values["Clarify"], custom_command)
                self.assertEqual(registry.types["Clarify"], 42)
            finally:
                app.APP_CONFIG.clear()
                app.APP_CONFIG.update(original)

    def test_settings_transaction_rolls_back_model_changes_on_save_failure(self):
        import app
        from repositories import ApplicationRepositories

        class FailingConfigRepository(LocalConfigRepository):
            def save(self, _config):
                raise OSError("simulated config write failure")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            seed = LocalConfigRepository(path)
            seed.save(
                {
                    "transcription_provider": "gemini",
                    "gemini_model": "gemini-2.5-flash",
                    "refinement_provider": "openai",
                    "refinement_model": "gpt-4o-mini",
                    "autostart": False,
                }
            )
            repository = FailingConfigRepository(path)
            bundle = ApplicationRepositories(
                config=repository,
                usage_stats=LocalUsageStatsRepository(Path(directory) / "stats.json"),
            )
            original = app.APP_CONFIG.copy()
            try:
                app._activate_repositories(bundle)
                before = app.APP_CONFIG.copy()
                with self.assertRaises(OSError):
                    app._apply_settings_transaction(
                        {"provider": "openai", "model": "whisper-1"},
                        {"provider": "groq", "model": "llama-3.3-70b-versatile"},
                        [("openai", "whisper-1")],
                        [("groq", "llama-3.3-70b-versatile")],
                        {"openai": "openai_audio_model"},
                        False,
                        bundle,
                    )
                self.assertEqual(app.APP_CONFIG, before)
                self.assertEqual(seed.load().selection.transcription_provider, "gemini")
                self.assertEqual(seed.load().gemini.audio_model, "gemini-2.5-flash")
            finally:
                app.APP_CONFIG.clear()
                app.APP_CONFIG.update(original)


if __name__ == "__main__":
    unittest.main()
