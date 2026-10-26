"""Computer processing uses synthetic audio and a fake typed registry."""

from dataclasses import replace
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from computer_processing import ComputerProcessor
from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippetService,
    DictionarySnippets,
    InMemoryDictionarySnippetsRepository,
    Snippet,
)
from provider_http import CancellationToken, ProviderCancelledError
from provider_registry import PROVIDER_REGISTRY, ProviderRegistry
from provider_types import RewriteResult, TranscriptionResult, TranslationResult
from repositories import AppConfig, ProviderConfig
from workflow_config import WorkflowConfig, WorkflowRoute


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 160)
    return output.getvalue()


class ComputerProcessorTests(unittest.TestCase):
    def setUp(self):
        self.current = AppConfig(
            openai=ProviderConfig(api_key="fake", base_url="https://pc.invalid"),
            groq=ProviderConfig(api_key="other"),
            workflows=WorkflowConfig(
                transcription=WorkflowRoute("openai", "whisper-1"),
                refinement=WorkflowRoute("groq", "cleanup", enabled=False),
                rewrite=WorkflowRoute("groq", "editor"),
                translation=WorkflowRoute("openai", "translator"),
            ),
        )
        self.config = SimpleNamespace(current=lambda: self.current)
        self.dictionary = DictionarySnippetService(
            InMemoryDictionarySnippetsRepository(DictionarySnippets())
        )
        self.registry = Mock(spec=ProviderRegistry)
        for name in ("describe", "supports", "connection_for_route"):
            getattr(self.registry, name).side_effect = getattr(PROVIDER_REGISTRY, name)
        self.registry.transcribe.return_value = TranscriptionResult(
            "Recognized words.", "openai", "whisper-1"
        )
        self.registry.rewrite.return_value = RewriteResult(
            "Edited words.", "groq", "editor"
        )
        self.registry.translate.return_value = TranslationResult(
            "Palavras traduzidas.", "openai", "translator", "pt"
        )
        self.processor = ComputerProcessor(
            self.config, self.dictionary, registry=self.registry
        )
        self.token = CancellationToken()

    def test_dictation_uses_pc_route_language_and_cleans_temporary_audio(self):
        paths = []

        def transcribe(provider, request, connection, cancel_token):
            paths.append(Path(request.audio_path))
            self.assertTrue(paths[0].exists())
            self.assertEqual(paths[0].read_bytes(), wav_bytes())
            self.assertEqual(
                (provider, request.model, request.language),
                ("openai", "whisper-1", "pt"),
            )
            self.assertEqual(connection.api_key, "fake")
            self.assertIs(cancel_token, self.token)
            return TranscriptionResult("Recognized words.", "openai", "whisper-1")

        self.registry.transcribe.side_effect = transcribe
        result = self.processor.process_dictation(wav_bytes(), "pt-BR", self.token)
        self.assertEqual(
            result,
            {
                "transcript": "Recognized words.",
                "text": "Recognized words.",
                "rewritten": False,
                "successful": True,
            },
        )
        self.assertFalse(paths[0].exists())
        self.assertEqual(self.current.ui.language, "en")

    def test_text_uses_independent_routes_and_cancellation(self):
        result = self.processor.process_text("rewrite", "Source", "de", self.token)
        self.assertEqual(result["text"], "Edited words.")
        args = self.registry.rewrite.call_args.args
        self.assertEqual((args[0], args[1].model), ("groq", "editor"))
        self.assertIs(args[3], self.token)
        translated = self.processor.process_text(
            "translate", "Source", "pt", self.token
        )
        self.assertEqual(translated["text"], "Palavras traduzidas.")
        args = self.registry.translate.call_args.args
        self.assertEqual((args[0], args[1].target_language), ("openai", "pt"))
        self.assertIs(args[3], self.token)

    def test_snapshot_prevents_config_changes_during_provider_calls(self):
        def metadata(provider):
            self.current = replace(
                self.current, openai=ProviderConfig(api_key="changed")
            )
            return PROVIDER_REGISTRY.describe(provider)

        self.registry.describe.side_effect = metadata
        self.processor.process_dictation(wav_bytes(), "en", self.token)
        self.assertEqual(self.registry.transcribe.call_args.args[2].api_key, "fake")

    def test_cancelled_work_never_calls_provider(self):
        self.token.cancel()
        with self.assertRaises(ProviderCancelledError):
            self.processor.process_text("rewrite", "Source", "en", self.token)
        self.registry.rewrite.assert_not_called()

    def test_temporary_audio_removed_after_provider_failure(self):
        paths = []

        def fail(_provider, request, _connection, _token):
            paths.append(Path(request.audio_path))
            raise RuntimeError("private provider details")

        self.registry.transcribe.side_effect = fail
        with self.assertRaises(RuntimeError):
            self.processor.process_dictation(wav_bytes(), "en", self.token)
        self.assertFalse(paths[0].exists())

    def test_local_asr_has_no_implicit_cloud_refinement(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute("local_asr", "base"),
                local_asr_refinement=WorkflowRoute("openai", "cloud"),
            ),
        )
        self.processor.process_dictation(wav_bytes(), "en", self.token)
        self.assertEqual(self.registry.transcribe.call_args.args[0], "local_asr")
        self.registry.rewrite.assert_not_called()

    def test_pc_dictionary_snapshot_and_exact_standalone_snippet(self):
        self.dictionary.replace(
            DictionarySnippets(
                dictionary=(DictionaryEntry("Clarify"),),
                snippets=(Snippet("signature", "Regards, PC owner."),),
            )
        )

        def recognize(_provider, request, _connection, _token):
            self.assertIn("Clarify", request.dictionary_context)
            self.dictionary.replace(DictionarySnippets())
            return TranscriptionResult("signature", "openai", "whisper-1")

        self.registry.transcribe.side_effect = recognize
        result = self.processor.process_dictation(wav_bytes(), "en", self.token)
        self.assertEqual(result["transcript"], "signature")
        self.assertEqual(result["text"], "Regards, PC owner.")
        self.registry.rewrite.assert_not_called()

    def test_optional_refinement_failure_returns_usable_transcript(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                refinement=WorkflowRoute("groq", "cleanup"),
            ),
        )
        self.registry.rewrite.side_effect = RuntimeError("unavailable")
        with patch("provider_registry.PROVIDER_HTTP.logger"):
            result = self.processor.process_dictation(wav_bytes(), "en", self.token)
        self.assertEqual(
            result,
            {
                "transcript": "Recognized words.",
                "text": "Recognized words.",
                "rewritten": False,
                "successful": False,
            },
        )

    def test_text_cancellation_after_provider_return_rejects_result(self):
        def late(*_args):
            self.token.cancel()
            return RewriteResult("Late result", "groq", "editor")

        self.registry.rewrite.side_effect = late
        with self.assertRaises(ProviderCancelledError):
            self.processor.process_text("rewrite", "Source", "en", self.token)

    def test_imports_are_ui_free_and_do_not_read_profiles_or_start_network(self):
        code = """
from pathlib import Path
import os, socket, sqlite3, sys
from unittest.mock import patch
read_text = Path.read_text
def read_nonprofile(path, *args, **kwargs):
    assert not path.resolve().is_relative_to(Path(os.environ['APPDATA']).resolve())
    return read_text(path, *args, **kwargs)
with patch.object(Path, 'mkdir', side_effect=AssertionError('mkdir')), \\
     patch.object(Path, 'read_text', read_nonprofile), \\
     patch.object(socket.socket, 'bind', side_effect=AssertionError('bind')), \\
     patch.object(socket.socket, 'connect', side_effect=AssertionError('connect')), \\
     patch.object(sqlite3, 'connect', side_effect=AssertionError('database')):
    import computer_host, computer_processing
assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules)
assert 'app' not in sys.modules
"""
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(
                os.environ,
                APPDATA=directory,
                LOCALAPPDATA=directory,
                USERPROFILE=directory,
                HOME=directory,
            )
            for name in ("API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY"):
                environment.pop(name, None)
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])
