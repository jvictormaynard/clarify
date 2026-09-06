import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from repositories import AppConfig, LocalConfigRepository
from secret_store import MemorySecretStore
from audio_file_batch import FileTranscriptionSelection
from provider_types import CancellationToken, ProviderConnection, TranscriptionResult
from spikes.pyside6.qml_runtime import QtAudioFileGateway, QtProviderGateway


class UnifiedDictationTests(unittest.TestCase):
    def test_old_config_migration_is_persisted_idempotent_and_preserves_preferences(
        self,
    ):
        for old_mode in ("transcription", "prompt", "unknown", None):
            with (
                self.subTest(mode=old_mode),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "config.json"
                original = {
                    "ui_mode": old_mode,
                    "ui_language": "pt",
                    "local_asr_cloud_refinement": False,
                    "custom_future_field": {"keep": True},
                }
                path.write_text(json.dumps(original), encoding="utf-8")
                repository = LocalConfigRepository(
                    path, secret_store=MemorySecretStore()
                )
                self.assertEqual(repository.load().ui.mode, "prompt")
                first = path.read_bytes()
                self.assertEqual(repository.load().ui.mode, "prompt")
                self.assertEqual(path.read_bytes(), first)
                stored = json.loads(first)
                self.assertEqual(stored["ui_mode"], "prompt")
                for key in original.keys() - {"ui_mode"}:
                    self.assertEqual(stored[key], original[key])

    def test_file_import_refines_with_selected_model_and_connection(self):
        config = AppConfig.from_mapping({"transcription_provider": "openai"})
        source = SimpleNamespace(current=lambda: config, workflow=config.workflow)
        dictionary = SimpleNamespace(
            apply_context=lambda value: value, expand=lambda value: value
        )
        provider = QtProviderGateway(source, dictionary)
        selection = FileTranscriptionSelection(
            "openai",
            "whisper-1",
            "pt",
            mode="transcription",
            connection=ProviderConnection(
                api_key="test-key", base_url="https://example.test/v1"
            ),
        )
        request = SimpleNamespace(audio_path=Path("audio.wav"), audio_bytes=b"audio")
        token = CancellationToken()
        with (
            patch(
                "spikes.pyside6.qml_runtime.PROVIDER_REGISTRY.transcribe",
                return_value=TranscriptionResult(
                    "quarta, na verdade quinta", "openai", "whisper-1"
                ),
            ) as transcribe,
            patch.object(
                provider,
                "_refine_transcript",
                return_value=SimpleNamespace(
                    text="quinta", provider_id="openai", model="editor"
                ),
            ) as refine,
        ):
            result = QtAudioFileGateway(provider).transcribe(request, selection, token)
        self.assertEqual(result.text, "quinta")
        self.assertEqual(result.raw_text, "quarta, na verdade quinta")
        self.assertEqual(transcribe.call_args.args[1].model, "whisper-1")
        self.assertEqual(transcribe.call_args.args[2], selection.connection)
        self.assertIs(transcribe.call_args.args[3], token)
        refine.assert_called_once()


if __name__ == "__main__":
    unittest.main()
