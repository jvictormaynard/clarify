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

    def test_success_keeps_routes_provenance_dictionary_and_timing(self):
        result = self.service.transcribe(self.audio, "transcription", "pt-BR")
        self.assertEqual(result.raw_text, self.raw)
        self.assertEqual(
            result.text, "João, use 42 unidades. Não envie ainda. expanded"
        )
        self.assertEqual(result.refined_text, result.text)
        self.assertFalse(result.refinement_failed)
        self.assertEqual((result.provider_id, result.model), ("openai", "whisper-1"))
        self.assertEqual(result.refinement_model, "gpt-4o-mini")
        request = self.registry.transcribe.call_args.args[1]
        self.assertEqual(request.language, "pt")
        self.assertEqual(request.audio_bytes, b"fake-audio")
        self.dictionary.apply_context.assert_called_once()
        refinement = self.registry.rewrite.call_args.args[1]
        self.assertEqual(refinement.text, self.raw)
        self.assertIn("BEGIN_SOURCE_TRANSCRIPT", refinement.source_message)
        self.assertIn("Brazilian Portuguese", refinement.instruction)
        self.assertEqual(refinement.reasoning_effort, "low")
        self.assertTrue(
            {"asr_ms", "refinement_ms", "text_cleanup_ms"} <= result.timings_ms.keys()
        )
        self.assertNotIn(self.raw, str(self.logger.write.call_args))

    def test_refinement_failure_keeps_exact_raw_and_skips_expansion(self):
        self.registry.rewrite.side_effect = RuntimeError("private provider payload")
        result = self.service.transcribe(self.audio, "prompt", "pt")
        self.assertEqual(result.text, self.raw)
        self.assertEqual(result.raw_text, self.raw)
        self.assertIsNone(result.refined_text)
        self.assertTrue(result.refinement_failed)
        self.dictionary.expand.assert_not_called()
        self.registry.transcribe.assert_called_once()
        self.assertNotIn("private provider payload", str(self.logger.write.call_args))

    def test_cancellation_wins_over_refinement_failure(self):
        def cancel_then_fail(*args):
            self.token.cancel()
            raise RuntimeError("failed after cancel")

        self.registry.rewrite.side_effect = cancel_then_fail
        with self.assertRaises(ProviderCancelledError):
            self.service.transcribe(self.audio, "prompt", "pt")
        self.dictionary.expand.assert_not_called()

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
        sentence = "Preserve every independent requirement, name and quantity."
        self.registry.transcribe.return_value = TranscriptionResult(
            (sentence + " ") * 10, "openai", "whisper-1"
        )
        self.registry.rewrite.return_value = RewriteResult(sentence, "openai", "editor")
        result = self.service.transcribe(self.audio, "prompt", "en")
        self.assertEqual(result.text, sentence + " expanded")
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
