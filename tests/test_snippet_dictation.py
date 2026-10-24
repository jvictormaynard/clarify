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
        return result, rewrite

    def assert_rewrite_source(self, rewrite, expected):
        request = rewrite.call_args.args[1]
        self.assertEqual(request.text, expected)
        self.assertIn(f"BEGIN_SOURCE_TRANSCRIPT\n{expected}\n", request.source_message)
        self.assertNotIn(self.saved_text, request.instruction)

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

    def test_inline_trigger_expands_before_refinement_and_keeps_edited_result(self):
        source = "Envie minha assinatura, por favor."
        result, rewrite = self.transcribe(
            source,
            RewriteResult("Por favor, envie a assinatura revisada.", "groq", "editor"),
        )
        self.assertEqual(result.text, "Por favor, envie a assinatura revisada.")
        self.assertEqual(result.raw_text, source)
        self.assertEqual(result.refined_text, result.text)
        self.assertFalse(result.refinement_failed)
        self.assertEqual(rewrite.call_count, 1)
        self.assert_rewrite_source(rewrite, f"Envie {self.saved_text}, por favor.")

    def test_inline_refinement_failure_keeps_expanded_source_and_raw_provenance(self):
        source = "Envie minha assinatura, por favor."
        result, rewrite = self.transcribe(source, RuntimeError("offline"))
        self.assertEqual(result.text, f"Envie {self.saved_text}, por favor.")
        self.assertEqual(result.raw_text, source)
        self.assertTrue(result.refinement_failed)
        self.assert_rewrite_source(rewrite, result.text)

    def test_replacements_are_not_recursive_and_model_triggers_are_not_expanded(self):
        self.service.replace(
            DictionarySnippets(
                snippets=(
                    Snippet("minha assinatura", "segunda frase"),
                    Snippet("segunda frase", "must not expand"),
                )
            )
        )
        with patch.object(self.service, "expand", wraps=self.service.expand) as expand:
            result, rewrite = self.transcribe(
                "Use minha assinatura.",
                RewriteResult(
                    "Agora use minha assinatura e segunda frase.", "groq", "editor"
                ),
            )
        self.assertEqual(result.text, "Agora use minha assinatura e segunda frase.")
        self.assert_rewrite_source(rewrite, "Use segunda frase.")
        expand.assert_called_once_with("Use minha assinatura.")

    def test_refinement_loss_guard_uses_expanded_source_and_preserves_it_on_failure(
        self,
    ):
        saved = "Preserve every independent requirement, name and quantity. " * 10
        self.service.replace(
            DictionarySnippets(snippets=(Snippet("minha assinatura", saved),))
        )
        source = "Use minha assinatura e confirme."
        result, rewrite = self.transcribe(
            source, RewriteResult("A short title.", "groq", "editor")
        )
        expected = "Use " + saved + " e confirme."
        self.assertEqual(result.text, expected)
        self.assertEqual(result.raw_text, source)
        self.assertTrue(result.refinement_failed)
        self.assert_rewrite_source(rewrite, expected)

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

    def test_multimodal_inline_rewrites_the_expanded_source_in_a_separate_stage(self):
        self.gemini()
        source = "Use minha assinatura."
        result, rewrite = self.transcribe(
            source,
            RewriteResult("Assinatura revisada pelo modelo.", "gemini", "editor"),
        )
        self.assertEqual(result.text, "Assinatura revisada pelo modelo.")
        self.assertEqual(rewrite.call_count, 1)
        self.assertIn(
            "Custom editing preference", rewrite.call_args.args[1].instruction
        )
        self.assert_rewrite_source(rewrite, "Use " + self.saved_text + ".")

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
