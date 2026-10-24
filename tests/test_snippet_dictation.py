"""Snippets through the production dictation gateway, without audio or HTTP."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from clarify.desktop.qml_runtime import QtProviderGateway
from dictionary_snippets import (
    DictionarySnippetService,
    DictionarySnippets,
    LocalDictionarySnippetsRepository,
    Snippet,
)
from provider_types import RewriteResult, TranscriptionResult
from repositories import AppConfig
from workflows import RecordingSnapshot


class SnippetDictationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = DictionarySnippetService(
            LocalDictionarySnippetsRepository(
                Path(self.directory.name) / "dictionary.json"
            )
        )
        self.saved_text = "João Victor\n\n<contact@example.test>"
        self.service.replace(
            DictionarySnippets(snippets=(Snippet("minha assinatura", self.saved_text),))
        )
        config = AppConfig.from_mapping(
            {
                "groq_api_key": "isolated-fixture",
                "local_asr_cloud_refinement": True,
                "workflows": {
                    "transcription": {
                        "provider_id": "local_asr",
                        "model_id": "ggml-small",
                    },
                    "local_asr_refinement": {
                        "provider_id": "groq",
                        "model_id": "editor",
                    },
                },
            }
        )
        self.gateway = QtProviderGateway(
            SimpleNamespace(current=lambda: config, workflow=config.workflow),
            self.service,
        )

    def transcribe(self, source, edited):
        with (
            patch(
                "clarify.desktop.qml_runtime.PROVIDER_REGISTRY.transcribe",
                return_value=TranscriptionResult(source, "local_asr", "ggml-small"),
            ) as asr,
            patch(
                "clarify.desktop.qml_runtime.PROVIDER_REGISTRY.rewrite",
                side_effect=[edited],
            ) as rewrite,
            patch("provider_registry.PROVIDER_HTTP.logger.write"),
        ):
            result = self.gateway.transcribe(
                RecordingSnapshot(Path("unused.wav"), b"fixture"), "prompt", "pt"
            )
        self.asr_request = asr.call_args.args[1]
        self.assertNotIn(self.saved_text, repr(asr.call_args))
        self.assertNotIn(self.saved_text, repr(rewrite.call_args))
        return result, rewrite

    def test_standalone_trigger_bypasses_refinement_and_does_not_expand_saved_text_again(
        self,
    ):
        self.service.replace(
            DictionarySnippets(
                snippets=(
                    Snippet("minha assinatura", self.saved_text),
                    Snippet("João Victor", "must not expand"),
                )
            )
        )
        result, rewrite = self.transcribe(
            "Minha assinatura.", RewriteResult("A different phrase", "groq", "editor")
        )
        self.assertEqual(result.text, self.saved_text)
        self.assertEqual(result.raw_text, "Minha assinatura.")
        self.assertEqual(result.refined_text, self.saved_text)
        rewrite.assert_not_called()

    def test_inline_trigger_expands_after_refinement_or_on_refinement_failure(self):
        source = "Envie minha assinatura, por favor."
        for edited in (
            RewriteResult(source, "groq", "editor"),
            RuntimeError("offline"),
        ):
            with self.subTest(edited=type(edited).__name__):
                result, rewrite = self.transcribe(source, edited)
                self.assertEqual(result.text, f"Envie {self.saved_text}, por favor.")
                self.assertEqual(result.raw_text, source)
                self.assertEqual(
                    result.refinement_failed, isinstance(edited, RuntimeError)
                )
                self.assertEqual(rewrite.call_count, 1)

    def gemini(self, *, refinement=True):
        config = AppConfig.from_mapping(
            {
                "gemini_api_key": "isolated-fixture",
                "workflows": {
                    "transcription": {
                        "provider_id": "gemini",
                        "model_id": "gemini-2.5-flash",
                        "prompt": "Custom recognition preference",
                    },
                    "refinement": {
                        "provider_id": "gemini",
                        "model_id": "gemini-2.5-flash",
                        "enabled": refinement,
                        "prompt": "Custom editing preference",
                    },
                },
            }
        )
        self.gateway = QtProviderGateway(
            SimpleNamespace(current=lambda: config, workflow=config.workflow),
            self.service,
        )

    def test_multimodal_standalone_trigger_uses_recognition_and_skips_editing(self):
        self.gemini()
        result, rewrite = self.transcribe(
            "Minha assinatura.", RewriteResult("wrong", "gemini", "editor")
        )
        self.assertEqual(result.text, self.saved_text)
        rewrite.assert_not_called()

        self.assertIn("Transcribe the audio directly", self.asr_request.instruction)
        self.assertEqual(self.asr_request.prompt, "Custom recognition preference")

    def test_multimodal_inline_uses_two_stages_without_sending_saved_text(self):
        self.gemini()
        source = "Use minha assinatura."
        result, rewrite = self.transcribe(
            source, RewriteResult(source, "gemini", "editor")
        )
        self.assertEqual(result.text, "Use " + self.saved_text + ".")
        self.assertEqual(rewrite.call_count, 1)
        self.assertIn(
            "Custom editing preference", rewrite.call_args.args[1].instruction
        )
        self.assertNotIn(self.saved_text, repr(rewrite.call_args))

    def test_multimodal_disabled_refinement_stays_disabled_with_snippets(self):
        self.gemini(refinement=False)
        result, rewrite = self.transcribe(
            "Use minha assinatura.", RewriteResult("wrong", "gemini", "editor")
        )
        self.assertEqual(result.text, "Use " + self.saved_text + ".")
        rewrite.assert_not_called()

    def test_multimodal_without_enabled_snippets_keeps_existing_combined_request(self):
        self.gemini()
        self.service.replace(
            DictionarySnippets(
                snippets=(Snippet("minha assinatura", self.saved_text, enabled=False),)
            )
        )
        with (
            patch(
                "clarify.desktop.qml_runtime.PROVIDER_REGISTRY.transcribe",
                return_value=TranscriptionResult(
                    "Already edited", "gemini", "gemini-2.5-flash"
                ),
            ) as asr,
            patch("clarify.desktop.qml_runtime.PROVIDER_REGISTRY.rewrite") as rewrite,
        ):
            result = self.gateway.transcribe(
                RecordingSnapshot(Path("unused.wav"), b"fixture"), "prompt", "pt"
            )
        self.assertEqual(result.text, "Already edited")
        self.assertIn("Transcribe the audio first", asr.call_args.args[1].instruction)
        self.assertEqual(asr.call_args.args[1].prompt, "Custom recognition preference")
        rewrite.assert_not_called()
