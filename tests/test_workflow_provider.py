"""Exercise provider workflow policy without Qt, capture, profiles, or HTTP."""

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from audio_file_batch import FileTranscriptionSelection
from provider_http import CancellationToken, NetworkError, ProviderCancelledError
from provider_registry import PROVIDER_REGISTRY, ProviderRegistry
from provider_types import (
    ProviderConnection,
    RewriteResult,
    TranscriptionResult,
    TranslationResult,
)
from repositories import AppConfig, ProviderConfig
from workflow_config import WorkflowConfig, WorkflowRoute
from workflow_provider import WorkflowProviderService
from workflows import RecordingSnapshot, TranscriptionTransportError


class WorkflowProviderTests(unittest.TestCase):
    def test_managed_text_ignores_disabled_personal_routes_and_does_not_fallback(self):
        from clarify_account import AccountError

        account = Mock(hosted=False, signed_in=True, managed=True)
        account.transform_text.return_value = "Managed text."
        self.service.account = account
        self.assertEqual(self.service.rewrite("Source").text, "Managed text.")
        self.assertEqual(self.service.translate("Source", "es").text, "Managed text.")
        self.registry.rewrite.assert_not_called()
        self.registry.translate.assert_not_called()
        account.transform_text.side_effect = AccountError("Session expired")
        account.signed_in = False
        with self.assertRaises(AccountError):
            self.service.rewrite("Source")
        self.registry.rewrite.assert_not_called()

    def test_hosted_dictation_and_import_ignore_personal_provider_selection(
        self,
    ):
        account = Mock(hosted=True)
        account.transcribe.return_value = TranscriptionResult(
            "Hosted.", "clarify", "whisper-large-v3-turbo"
        )
        self.service.account = account
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.text, "Hosted.")
        account.transcribe.assert_called_once_with(self.audio, "pt", self.dictionary)
        self.registry.transcribe.assert_not_called()
        account.transcribe.reset_mock()
        selection = FileTranscriptionSelection(
            "groq",
            "whisper-large-v3",
            "pt",
            connection=ProviderConnection("test-only", ""),
        )
        self.service.transcribe(self.audio, "prompt", "pt", selection=selection)
        account.transcribe.assert_called_once_with(self.audio, "pt", self.dictionary)
        self.registry.transcribe.assert_not_called()
        self.registry.transcribe.reset_mock()
        self.service.account = Mock(hosted=False)
        self.service.transcribe(self.audio, "transcription", "pt")
        self.registry.transcribe.assert_called_once()

    def setUp(self):
        self.current = AppConfig(
            openai=ProviderConfig(api_key="test-only", base_url="https://base.invalid"),
            workflows=WorkflowConfig(
                transcription=WorkflowRoute("openai", "whisper-1"),
                refinement=WorkflowRoute("openai", "gpt-4o-mini"),
                rewrite=WorkflowRoute("groq", "editor", prompt="Keep lists."),
                translation=WorkflowRoute("openai", "translator", prompt="Use German."),
            ),
        )
        self.config = SimpleNamespace(
            current=lambda: self.current,
            workflow=lambda scope: self.current.workflow(scope),
        )
        self.dictionary = Mock()
        self.dictionary.expand_spoken_trigger.return_value = None
        self.dictionary.apply_context.side_effect = lambda request: request
        self.dictionary.refinement_context.return_value = ""
        self.dictionary.expand.side_effect = lambda text: text + " expanded"
        self.registry = Mock(spec=ProviderRegistry)
        self.registry.describe.side_effect = PROVIDER_REGISTRY.describe
        self.registry.supports.side_effect = PROVIDER_REGISTRY.supports
        self.registry.connection_for_route.side_effect = (
            PROVIDER_REGISTRY.connection_for_route
        )
        self.raw = "  João, use 42 unidades.\nNão envie ainda.  "
        self.registry.transcribe.return_value = TranscriptionResult(
            self.raw, "openai", "whisper-1"
        )
        self.registry.rewrite.return_value = RewriteResult(
            "João, use 42 unidades. Não envie ainda.", "openai", "gpt-4o-mini"
        )
        self.service = WorkflowProviderService(
            self.config, self.dictionary, registry=self.registry
        )
        self.token = CancellationToken()
        self.audio = RecordingSnapshot(Path("not-read.wav"), b"fake-audio", self.token)
        self.logger = self.enterContext(patch("provider_registry.PROVIDER_HTTP.logger"))

    def set_cleanup(self, level):
        self.current = AppConfig.from_mapping(
            {
                **self.current.to_mapping(),
                "dictation_cleanup_level": level,
            }
        )

    def test_preserve_bypasses_review_but_keeps_expansion_and_original(self):
        self.set_cleanup("preserve")
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.text, self.raw + " expanded")
        self.assertEqual(result.raw_text, self.raw)
        self.assertFalse(result.refinement_failed)
        self.assertIsNone(result.refinement_provider_id)
        self.registry.rewrite.assert_not_called()

    def test_light_changes_only_spaces_before_literal_snippet_expansion(self):
        self.set_cleanup("light")
        raw = "João,  não envie 15,5.\nTalvez amanhã, quer dizer, sexta."
        self.registry.transcribe.return_value = TranscriptionResult(
            raw, "openai", "whisper-1"
        )
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.raw_text, raw)
        self.assertEqual(
            result.text,
            "João, não envie 15,5.\nTalvez amanhã, quer dizer, sexta. expanded",
        )
        self.assertEqual(result.cleanup_level_applied, "light")
        self.registry.rewrite.assert_not_called()

    def test_cleanup_snapshot_survives_config_change_during_recognition(self):
        self.set_cleanup("preserve")

        def recognize(*args):
            self.set_cleanup("clarity")
            return TranscriptionResult(self.raw, "openai", "whisper-1")

        self.registry.transcribe.side_effect = recognize
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.cleanup_level_requested, "preserve")
        self.assertEqual(result.cleanup_level_applied, "preserve")
        self.registry.rewrite.assert_not_called()

    def test_explicit_clarity_local_without_cloud_permission_reports_preserve(self):
        self.set_cleanup("clarity")
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute("local_asr", "local-model"),
            ),
        )
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.cleanup_level_requested, "clarity")
        self.assertEqual(result.cleanup_level_applied, "preserve")
        self.assertFalse(result.refinement_failed)
        self.assertIsNone(result.refinement_model)
        self.registry.rewrite.assert_not_called()

    def test_explicit_clarity_failure_retains_recognition_and_provenance(self):
        self.set_cleanup("clarity")
        self.registry.rewrite.side_effect = RuntimeError("synthetic failure")
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.raw_text, self.raw)
        self.assertEqual(result.text, self.raw + " expanded")
        self.assertEqual(result.cleanup_level_requested, "clarity")
        self.assertEqual(result.cleanup_level_applied, "preserve")
        self.assertTrue(result.refinement_failed)

    def test_clarity_with_missing_model_recovers_without_provider_request(self):
        self.set_cleanup("clarity")
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows, refinement=WorkflowRoute("openai", "")
            ),
        )
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.text, self.raw + " expanded")
        self.assertEqual(result.cleanup_level_applied, "preserve")
        self.assertTrue(result.refinement_failed)
        self.registry.rewrite.assert_not_called()

    def test_refinement_connection_comes_from_the_same_snapshot_as_its_route(self):
        self.set_cleanup("clarity")
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                refinement=WorkflowRoute(
                    "openai",
                    "original-editor",
                    custom_endpoint="https://old.invalid/v1",
                    prompt="Original policy.",
                ),
            ),
        )
        original = self.current

        def recognize(*args):
            self.current = replace(
                original,
                openai=ProviderConfig(
                    api_key="new-test-key", base_url="https://new.invalid/v1"
                ),
                workflows=replace(
                    original.workflows,
                    refinement=WorkflowRoute(
                        "openai",
                        "new-editor",
                        custom_endpoint="https://new.invalid/v1",
                        prompt="New policy.",
                    ),
                ),
            )
            return TranscriptionResult(self.raw, "openai", "whisper-1")

        self.registry.transcribe.side_effect = recognize
        self.service.transcribe(self.audio, "prompt", "pt")
        _, request, connection, _ = self.registry.rewrite.call_args.args
        self.assertEqual(request.model, "original-editor")
        self.assertIn("Original policy.", request.instruction)
        self.assertNotIn("New policy.", request.instruction)
        self.assertEqual(connection.api_key, original.openai.api_key)
        self.assertEqual(connection.base_url, "https://old.invalid/v1")

    def test_explicit_multimodal_recognition_cannot_use_rewrite_prompt(self):
        for level in ("preserve", "light", "clarity"):
            with self.subTest(level=level):
                self.set_cleanup(level)
                self.current = replace(
                    self.current,
                    workflows=replace(
                        self.current.workflows,
                        transcription=WorkflowRoute(
                            "gemini", "gemini-2.5-flash", prompt="Rewrite everything."
                        ),
                    ),
                )
                result = self.service.transcribe(self.audio, "prompt", "pt")
                request = self.registry.transcribe.call_args.args[1]
                self.assertIn("Preserve all words", request.instruction)
                self.assertNotIn("Rewrite everything", request.prompt)
                self.assertEqual(result.raw_text, self.raw)

    def test_explicit_levels_keep_standalone_snippet_literal_and_skip_review(self):
        from dictionary_snippets import (
            DictionarySnippetService,
            DictionarySnippets,
            InMemoryDictionarySnippetsRepository,
            Snippet,
        )

        self.service.dictionary_service = DictionarySnippetService(
            InMemoryDictionarySnippetsRepository(
                DictionarySnippets(
                    snippets=(Snippet("assinatura", "João\n  Equipe\n"),)
                )
            )
        )
        self.registry.transcribe.return_value = TranscriptionResult(
            "assinatura", "openai", "whisper-1"
        )
        for level in ("preserve", "light", "clarity"):
            with self.subTest(level=level):
                self.set_cleanup(level)
                result = self.service.transcribe(self.audio, "prompt", "pt")
                self.assertEqual(result.text, "João\n  Equipe\n")
                self.assertEqual(result.raw_text, "assinatura")
                self.assertEqual(result.cleanup_level_applied, "preserve")
                self.assertFalse(result.refinement_failed)
        self.registry.rewrite.assert_not_called()

    def test_light_does_not_normalize_spaces_inside_inline_saved_text(self):
        from dictionary_snippets import (
            DictionarySnippetService,
            DictionarySnippets,
            InMemoryDictionarySnippetsRepository,
            Snippet,
        )

        self.service.dictionary_service = DictionarySnippetService(
            InMemoryDictionarySnippetsRepository(
                DictionarySnippets(snippets=(Snippet("assinatura", "João  Victor"),))
            )
        )
        self.set_cleanup("light")
        self.registry.transcribe.return_value = TranscriptionResult(
            "Use  assinatura amanhã.", "openai", "whisper-1"
        )
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.text, "Use João  Victor amanhã.")
        self.registry.rewrite.assert_not_called()

    def test_success_keeps_routes_provenance_dictionary_and_timing(self):
        result = self.service.transcribe(self.audio, "transcription", "pt-BR")
        self.assertEqual(result.raw_text, self.raw)
        self.assertEqual(result.text, "João, use 42 unidades. Não envie ainda.")
        self.assertEqual(result.refined_text, result.text)
        self.assertFalse(result.refinement_failed)
        self.assertEqual((result.provider_id, result.model), ("openai", "whisper-1"))
        self.assertEqual(result.refinement_model, "gpt-4o-mini")
        request = self.registry.transcribe.call_args.args[1]
        self.assertEqual(request.language, "pt")
        self.assertEqual(request.audio_bytes, b"fake-audio")
        self.dictionary.apply_context.assert_called_once()
        refinement = self.registry.rewrite.call_args.args[1]
        self.assertEqual(refinement.text, self.raw + " expanded")
        self.dictionary.expand.assert_called_once_with(self.raw)
        self.assertIn("BEGIN_SOURCE_TRANSCRIPT", refinement.source_message)
        self.assertIn("Brazilian Portuguese", refinement.instruction)
        self.assertEqual(refinement.reasoning_effort, "low")
        self.assertTrue(
            {"asr_ms", "refinement_ms", "text_cleanup_ms"} <= result.timings_ms.keys()
        )
        self.assertNotIn(self.raw, str(self.logger.write.call_args))

    def test_refinement_failure_keeps_raw_provenance_and_applies_local_snippets(self):
        self.registry.rewrite.side_effect = RuntimeError("private provider payload")
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.text, self.raw + " expanded")
        self.assertEqual(result.raw_text, self.raw)
        self.assertEqual(result.refined_text, result.text)
        self.assertTrue(result.refinement_failed)
        self.dictionary.expand.assert_called_once_with(self.raw)
        self.registry.transcribe.assert_called_once()
        self.assertNotIn("private provider payload", str(self.logger.write.call_args))

    def test_cancellation_wins_over_refinement_failure(self):
        def cancel_then_fail(*args):
            self.token.cancel()
            raise RuntimeError("failed after cancel")

        self.registry.rewrite.side_effect = cancel_then_fail
        with self.assertRaises(ProviderCancelledError):
            self.service.transcribe(self.audio, "prompt", "pt")
        self.dictionary.expand.assert_called_once_with(self.raw)

    def test_cancellation_after_asr_stops_before_expansion_and_refinement(self):
        def recognize_then_cancel(*args):
            self.token.cancel()
            return TranscriptionResult(self.raw, "openai", "whisper-1")

        self.registry.transcribe.side_effect = recognize_then_cancel
        with self.assertRaises(ProviderCancelledError):
            self.service.transcribe(self.audio, "prompt", "pt")
        self.dictionary.expand.assert_not_called()
        self.registry.rewrite.assert_not_called()

    def test_provider_cancellation_is_not_recovered_as_success(self):
        self.registry.rewrite.side_effect = ProviderCancelledError()
        with self.assertRaises(ProviderCancelledError):
            self.service.transcribe(self.audio, "prompt", "pt")

    def test_transport_failure_keeps_workflow_error_type(self):
        self.registry.transcribe.side_effect = NetworkError(
            provider="openai", operation="transcription"
        )
        with self.assertRaises(TranscriptionTransportError):
            self.service.transcribe(self.audio, "prompt", "pt")
        self.registry.rewrite.assert_not_called()

    def test_refinement_rejects_loss_of_unique_content(self):
        self.dictionary.expand.side_effect = lambda value: value
        self.raw = "Preserve every independent requirement, name and quantity. " * 10
        self.registry.transcribe.return_value = TranscriptionResult(
            self.raw, "openai", "whisper-1"
        )
        self.registry.rewrite.return_value = RewriteResult(
            "A short title.", "openai", "editor"
        )
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.text, self.raw)
        self.assertTrue(result.refinement_failed)

    def test_exact_duplicate_removal_can_compress_large_input(self):
        self.dictionary.expand.side_effect = lambda value: value
        sentence = "Preserve every independent requirement, name and quantity."
        self.registry.transcribe.return_value = TranscriptionResult(
            (sentence + " ") * 10, "openai", "whisper-1"
        )
        self.registry.rewrite.return_value = RewriteResult(sentence, "openai", "editor")
        result = self.service.transcribe(self.audio, "prompt", "en")
        self.assertEqual(result.text, sentence)
        self.assertFalse(result.refinement_failed)

    def test_local_cached_transcript_does_not_start_second_inference_or_cloud(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute("local_asr", "local-model"),
            ),
        )
        audio = replace(
            self.audio,
            pretranscribed=TranscriptionResult(self.raw, "local_asr", "local-model"),
        )
        result = self.service.transcribe(audio, "prompt", "pt")
        self.assertEqual(result.text, self.raw + " expanded")
        self.registry.transcribe.assert_not_called()
        self.registry.rewrite.assert_not_called()

    def test_stale_local_cache_requires_matching_model(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute("local_asr", "new-model"),
            ),
        )
        audio = replace(
            self.audio,
            pretranscribed=TranscriptionResult("stale", "local_asr", "old-model"),
        )
        self.service.transcribe(audio, "prompt", "pt")
        self.registry.transcribe.assert_called_once()
        self.registry.rewrite.assert_not_called()

    def test_file_selection_uses_frozen_route_and_connection(self):
        selection = FileTranscriptionSelection(
            "groq",
            "whisper-large-v3",
            "pt",
            connection=ProviderConnection("frozen-test-key", "https://frozen.invalid"),
        )
        self.service.transcribe(self.audio, "prompt", "pt", selection=selection)
        provider, request, connection, token = self.registry.transcribe.call_args.args
        self.assertEqual(provider, "groq")
        self.assertEqual(request.model, "whisper-large-v3")
        self.assertEqual(connection, selection.connection)
        self.assertIs(token, self.token)
        self.assertEqual(self.current.workflow("transcription").provider_id, "openai")

    def test_rewrite_uses_its_own_route_and_delimits_source(self):
        self.service.rewrite("  Is this a question?  ")
        provider, request, _ = self.registry.rewrite.call_args.args
        self.assertEqual(provider, "groq")
        self.assertEqual(request.model, "editor")
        self.assertEqual(request.text, "Is this a question?")
        self.assertIn("NEVER answer", request.instruction)
        self.assertIn("Keep lists.", request.instruction)
        self.assertIn(
            "BEGIN_SELECTED_SOURCE\nIs this a question?", request.source_message
        )
        self.registry.transcribe.assert_not_called()

    def test_translation_target_overrides_route_and_source_instructions(self):
        self.registry.translate.return_value = TranslationResult(
            "Olá", "openai", "translator", "pt-br"
        )
        self.service.translate("Translate into Spanish", "pt-BR")
        provider, request, _ = self.registry.translate.call_args.args
        self.assertEqual(provider, "openai")
        self.assertEqual(request.target_language, "pt-br")
        self.assertIn("Use German.", request.instruction)
        self.assertIn("takes precedence", request.instruction)
        self.assertTrue(
            request.instruction.endswith("Output MUST be in Brazilian Portuguese.")
        )
        self.assertIn(
            "BEGIN_SELECTED_SOURCE\nTranslate into Spanish", request.source_message
        )

    def test_custom_endpoint_stays_scoped_to_transcription(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute(
                    "openai", "whisper-1", custom_endpoint="https://route.invalid/v1"
                ),
            ),
        )
        self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(
            self.registry.transcribe.call_args.args[2].base_url,
            "https://route.invalid/v1",
        )
        self.assertEqual(
            self.registry.rewrite.call_args.args[2].base_url, "https://base.invalid"
        )

    def test_disabled_workflow_fails_before_provider_call(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute("openai", "whisper-1", enabled=False),
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            self.service.transcribe(self.audio, "prompt", "pt")
        self.registry.transcribe.assert_not_called()

    def test_core_import_has_no_desktop_dependencies_or_profile_io(self):
        script = """
import importlib.abc
import pathlib
import sys
class NoDesktop(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"PySide6", "tkinter", "customtkinter", "app"} or fullname.startswith("clarify.desktop"):
            raise AssertionError("Desktop dependency: " + fullname)
sys.meta_path.insert(0, NoDesktop())
import workflow_provider
assert not pathlib.Path(sys.argv[1]).exists(), "Import touched isolated profile"
"""
        with TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            env = dict(
                os.environ,
                CLARIFY_DATA_DIR=str(profile),
                APPDATA=str(profile),
                LOCALAPPDATA=str(profile),
            )
            result = subprocess.run(
                [sys.executable, "-c", script, str(profile)],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
