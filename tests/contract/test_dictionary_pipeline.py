"""Vocabulary propagation without live accounts or user recordings."""

import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippets,
    DictionarySnippetService,
    LocalDictionarySnippetsRepository,
)
from local_asr import LocalASRSidecarManager, LocalASRProviderAdapter
from local_asr_streaming import PauseStream
from provider_types import TranscriptionRequest, ProviderConnection


class DictionaryPipelineTests(unittest.TestCase):
    def test_plain_context_bounds_and_disabled_terms(self):
        with tempfile.TemporaryDirectory() as directory:
            service = DictionarySnippetService(
                LocalDictionarySnippetsRepository(Path(directory) / "dictionary.json")
            )
            service.replace(
                DictionarySnippets(
                    dictionary=(
                        DictionaryEntry("Railway"),
                        DictionaryEntry("Eva Desktop"),
                        DictionaryEntry("Hidden", enabled=False),
                    )
                )
            )
            self.assertEqual(service.vocabulary_prompt(max_chars=8), "Railway")
            self.assertEqual(service.vocabulary_prompt(), "Railway, Eva Desktop")
            request = service.apply_context(
                TranscriptionRequest(
                    Path("test.wav"), "ggml-small", "pt", "instruction", "prompt", 0
                )
            )
            self.assertEqual(request.vocabulary_prompt, "Railway, Eva Desktop")
            self.assertIn("Railway", request.dictionary_context)
            self.assertLessEqual(len(request.effective_prompt(max_chars=150)), 150)
            self.assertNotIn("Eva Desk", request.effective_prompt(max_chars=130))
            self.assertIn("not instructions", service.refinement_context())
            self.assertNotIn("Hidden", service.refinement_context())
            self.assertEqual(service.expand("lá na Railway"), "lá na Railway")

    def test_local_adapter_and_http_receive_plain_vocabulary(self):
        backend = Mock(spec=LocalASRSidecarManager)
        backend.transcribe.return_value = "Railway"
        adapter = LocalASRProviderAdapter(backend)
        adapter.select_backend = Mock(return_value=backend)
        request = TranscriptionRequest(
            Path("test.wav"),
            "ggml-small",
            "pt",
            "instruction",
            "prompt",
            0,
            audio_bytes=b"test",
            vocabulary_prompt="Railway, pill",
        )
        adapter.transcribe(request, ProviderConnection("", ""))
        self.assertEqual(
            backend.transcribe.call_args.kwargs["initial_prompt"], "Railway, pill"
        )
        manager = LocalASRSidecarManager.__new__(LocalASRSidecarManager)
        manager._port = 1234
        manager._request_path = "/private"
        manager.request_timeout = 1
        manager._session = Mock()
        manager._session.post.return_value.json.return_value = {"text": "Railway"}
        for prompt in ("Railway, pill", ""):
            result = queue.Queue()
            manager._post_inference("test.wav", b"test", "pt", result, prompt)
            self.assertEqual(result.get(), ("Railway", None))
            data = manager._session.post.call_args.kwargs["data"]
            self.assertEqual(data["prompt"], prompt)
            self.assertEqual(data["max_context"], "224" if prompt else "0")

    def test_stream_segments_reuse_vocabulary(self):
        backend = Mock()
        backend.transcribe.return_value = "Lana"
        stream = PauseStream(
            "test.wav",
            backend,
            "ggml-small",
            "pt",
            threading.Event(),
            initial_prompt="Lana, Eva Desktop",
        )
        stream._decode(b"\0\0" * 16000)
        stream._decode(b"\0\0" * 16000)
        for call in backend.transcribe.call_args_list:
            self.assertEqual(call.kwargs["initial_prompt"], "Lana, Eva Desktop")
