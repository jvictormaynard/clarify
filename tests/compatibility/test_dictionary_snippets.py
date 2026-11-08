from pathlib import Path
import unittest
from unittest.mock import patch

import app
from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippetService,
    DictionarySnippets,
    Snippet,
)


from tests.support.dictionary import (
    DictionaryFixture,
)


class DictionarySnippetTests(DictionaryFixture, unittest.TestCase):
    def test_recording_path_applies_context_and_expands_result_after_provider_work(
        self,
    ):
        service = DictionarySnippetService(self.repository)
        service.replace(
            DictionarySnippets(
                dictionary=(DictionaryEntry("Clarify"),),
                snippets=(Snippet("brb", "be right back"),),
            )
        )
        original_config = app.APP_CONFIG.copy()
        try:
            app.APP_CONFIG.update(
                {
                    "transcription_provider": "gemini",
                    "gemini_api_key": "test-key",
                    "gemini_base_url": "https://proxy.example",
                    "gemini_model": "gemini-2.5-flash",
                }
            )
            request_seen = []

            def transcribe(_provider, request, _connection, _cancel_token):
                request_seen.append(request)
                return type(
                    "Result",
                    (),
                    {
                        "text": "brb",
                    },
                )()

            with (
                patch.object(app, "DICTIONARY_SERVICE", service),
                patch.object(app.PROVIDER_REGISTRY, "transcribe", transcribe),
            ):
                result = app._call_provider_audio(
                    "gemini", Path(self.directory.name) / "audio.wav", "transcription"
                )

            self.assertEqual(result, "be right back")
            self.assertEqual(len(request_seen), 1)
            self.assertIn("Clarify", request_seen[0].dictionary_context)
        finally:
            app.APP_CONFIG.clear()
            app.APP_CONFIG.update(original_config)

    def test_recording_path_does_not_expand_refinement_error_sentinel(self):
        service = DictionarySnippetService(self.repository)
        service.replace(DictionarySnippets(snippets=(Snippet("Error", "success"),)))
        original_config = app.APP_CONFIG.copy()
        try:
            app.APP_CONFIG.update(
                {
                    "transcription_provider": "openai",
                    "openai_api_key": "test-key",
                    "openai_base_url": "https://proxy.example/v1",
                    "openai_audio_model": "whisper-1",
                    "refinement_provider": "openai",
                    "refinement_model": "gpt-4o-mini",
                }
            )
            with (
                patch.object(app, "DICTIONARY_SERVICE", service),
                patch.object(
                    app.PROVIDER_REGISTRY,
                    "transcribe",
                    return_value=type("Result", (), {"text": "raw"})(),
                ),
                patch.object(app, "_refine_transcript", return_value="[Error: failed]"),
            ):
                result = app._call_provider_audio(
                    "openai", Path(self.directory.name) / "audio.wav", "prompt"
                )

            self.assertEqual(result, "[Error: failed]")
        finally:
            app.APP_CONFIG.clear()
            app.APP_CONFIG.update(original_config)


if __name__ == "__main__":
    unittest.main()
