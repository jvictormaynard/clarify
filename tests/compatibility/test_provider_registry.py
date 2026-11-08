import unittest
from pathlib import Path
from unittest.mock import patch

import app
from provider_registry import ProviderRegistry
from provider_types import (
    TranscriptionResult,
)


from tests.support.provider_registry import (
    FakeResponse,
    FakeHttp,
    compatible_metadata,
    ProviderRegistryFixture,
)

ROOT = Path(__file__).resolve().parents[2]


class ProviderRegistryContractTests(ProviderRegistryFixture, unittest.TestCase):
    def test_local_prompt_does_not_fallback_to_cloud_without_opt_in(self):
        original = app.APP_CONFIG.copy()
        try:
            app.APP_CONFIG["transcription_provider"] = "local_asr"
            app.APP_CONFIG["local_asr_model"] = "ggml-small"
            app.APP_CONFIG["local_asr_cloud_refinement"] = False
            with (
                patch.object(
                    app.PROVIDER_REGISTRY,
                    "transcribe",
                    return_value=TranscriptionResult(
                        "local transcript", "local_asr", "ggml-small"
                    ),
                ) as transcribe,
                patch.object(app, "_refine_transcript") as refine,
            ):
                result = app._call_provider_audio(
                    "local_asr", self.audio_path, "prompt", "pt-BR", audio_bytes=b"RIFF"
                )
            self.assertEqual(result, "local transcript")
            transcribe.assert_called_once()
            self.assertEqual(transcribe.call_args.args[1].language, "pt-BR")
            refine.assert_not_called()
        finally:
            app.APP_CONFIG.clear()
            app.APP_CONFIG.update(original)

    def test_desktop_workflow_routes_a_registered_compatible_provider(self):
        http = FakeHttp(FakeResponse({"text": "desktop transcript"}))
        registry = ProviderRegistry()
        registry.register_openai_compatible(compatible_metadata("acme"), http)
        config = {
            "transcription_provider": "acme",
            "acme_api_key": "key",
            "acme_base_url": "https://acme.example",
            "acme_audio_model": "whisper-acme",
        }

        with (
            patch.object(app, "PROVIDER_REGISTRY", registry),
            patch.dict(app.APP_CONFIG, config, clear=False),
        ):
            result = app.call_transcription_provider(
                self.audio_path, "transcription", "en"
            )

        self.assertEqual(result, "desktop transcript")
        self.assertEqual(
            http.calls[0][1], "https://acme.example/v1/audio/transcriptions"
        )


if __name__ == "__main__":
    unittest.main()
