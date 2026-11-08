import unittest
from pathlib import Path

from provider_adapters import OpenAICompatibleAdapter
from provider_http import InvalidResponseError
from provider_registry import ProviderRegistry, build_provider_registry
from provider_types import (
    ModelCatalog,
    ProviderCapability,
    ProviderConfigurationError,
    ProviderConnection,
    RewriteRequest,
    TranscriptionRequest,
    TranslationRequest,
    UnsupportedCapabilityError,
)


from tests.support.provider_registry import (
    FakeResponse,
    FakeHttp,
    compatible_metadata,
    ProviderRegistryFixture,
)

ROOT = Path(__file__).resolve().parents[2]


class ProviderRegistryContractTests(ProviderRegistryFixture, unittest.TestCase):
    def test_groq_transcription_uses_only_canonical_vocabulary(self):
        for endpoint in (
            "https://api.groq.com/openai/v1",
            "https://groq-proxy.example/v1",
        ):
            with self.subTest(endpoint=endpoint):
                http = FakeHttp(FakeResponse({"text": "complete transcript"}))
                registry = build_provider_registry(http)
                request = TranscriptionRequest(
                    self.audio_path,
                    "whisper-large-v3-turbo",
                    "pt",
                    "Rewrite as a clear message.",
                    "Custom chat instructions must not guide Whisper decoding.",
                    0.1,
                    dictionary_context="Vocabulary instructions, aliases and pronunciation.",
                    vocabulary_prompt="Clarify, Subaúma",
                )

                result = registry.transcribe(
                    "groq", request, ProviderConnection("fixture", endpoint)
                )

                self.assertEqual(result.text, "complete transcript")
                self.assertEqual(len(http.calls), 1)
                self.assertEqual(
                    http.calls[0][2]["data"],
                    {
                        "model": "whisper-large-v3-turbo",
                        "response_format": "json",
                        "prompt": "Clarify, Subaúma",
                        "language": "pt",
                    },
                )
                self.assertFalse(http.calls[0][2]["safe_to_retry"])

    def test_groq_transcription_omits_empty_vocabulary_instead_of_using_chat_prompt(
        self,
    ):
        for vocabulary in ("", "   "):
            with self.subTest(vocabulary=vocabulary):
                http = FakeHttp(FakeResponse({"text": "short transcript"}))
                registry = build_provider_registry(http)

                registry.transcribe(
                    "groq",
                    TranscriptionRequest(
                        self.audio_path,
                        "whisper-large-v3-turbo",
                        "",
                        "Rewrite this dictation.",
                        "Custom instructions.",
                        0.1,
                        dictionary_context="Vocabulary instructions without canonical terms.",
                        vocabulary_prompt=vocabulary,
                    ),
                    ProviderConnection("fixture", "https://api.groq.com/openai/v1"),
                )

                self.assertNotIn("prompt", http.calls[0][2]["data"])
                self.assertNotIn("language", http.calls[0][2]["data"])

    def test_groq_rejects_overlong_vocabulary_before_sending_audio(self):
        http = FakeHttp()
        registry = build_provider_registry(http)

        with self.assertRaisesRegex(ValueError, "896-character limit"):
            registry.transcribe(
                "groq",
                TranscriptionRequest(
                    self.audio_path,
                    "whisper-large-v3-turbo",
                    "en",
                    "instruction",
                    "prompt",
                    0.0,
                    vocabulary_prompt="x" * 897,
                ),
                ProviderConnection("fixture", "https://api.groq.com/openai/v1"),
            )

        self.assertEqual(http.calls, [])

    def test_cleanup_reasoning_budget_is_sent_only_to_supported_groq_models(self):
        for provider, endpoint, model, expected in (
            ("groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-20b", "low"),
            ("groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "low"),
            ("groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", None),
            ("groq", "https://fixture.example/v1", "openai/gpt-oss-20b", None),
            (
                "groq",
                "https://api.groq.com.fixture.example/v1",
                "openai/gpt-oss-20b",
                None,
            ),
            ("compatible", "https://fixture.example/v1", "openai/gpt-oss-20b", None),
        ):
            with self.subTest(provider=provider, model=model):
                http = FakeHttp(
                    FakeResponse({"choices": [{"message": {"content": "edited"}}]})
                )
                adapter = OpenAICompatibleAdapter(
                    compatible_metadata(provider), http, official_host="api.groq.com"
                )
                result = adapter.rewrite(
                    RewriteRequest(
                        text="source",
                        model=model,
                        language="en",
                        instruction="Clean the text.",
                        source_message="source",
                        reasoning_effort="low",
                    ),
                    ProviderConnection("fixture", endpoint),
                )
                self.assertEqual(result.text, "edited")
                payload = http.calls[0][2]["json"]
                self.assertEqual(payload.get("reasoning_effort"), expected)
                self.assertEqual(
                    payload.get("max_completion_tokens"), 4096 if expected else None
                )
                self.assertEqual(payload["messages"][1]["content"], "source")

    def test_incomplete_text_is_rejected_even_when_content_is_present(self):
        http = FakeHttp(
            FakeResponse(
                {
                    "choices": [
                        {
                            "message": {"content": "only the first point"},
                            "finish_reason": "length",
                        }
                    ]
                }
            )
        )
        adapter = OpenAICompatibleAdapter(compatible_metadata(), http)
        with self.assertRaises(InvalidResponseError):
            adapter.rewrite(
                RewriteRequest("all points", "editor", "en", "Clean.", "all points"),
                ProviderConnection("fixture", "https://fixture.example/v1"),
            )

    def test_default_registry_is_authoritative_for_ids_metadata_and_capabilities(self):
        http = FakeHttp()
        registry = build_provider_registry(http)

        self.assertEqual(
            registry.provider_ids, ("gemini", "openai", "groq", "local_asr", "chatgpt")
        )
        self.assertEqual(registry.describe("openai").display_name, "OpenAI")
        self.assertEqual(registry.describe("groq").audio_model_key, "groq_audio_model")
        self.assertTrue(
            registry.supports("gemini", ProviderCapability.MULTIMODAL_AUDIO)
        )
        self.assertFalse(registry.supports("groq", ProviderCapability.MULTIMODAL_AUDIO))
        self.assertTrue(
            registry.supports("local_asr", ProviderCapability.AUDIO_TRANSCRIPTION)
        )
        self.assertFalse(
            registry.supports("local_asr", ProviderCapability.TEXT_GENERATION)
        )
        for provider_id in registry.provider_ids:
            with self.subTest(provider_id=provider_id):
                adapter = registry.adapter(provider_id)
                if provider_id == "local_asr":
                    self.assertEqual(adapter.metadata.provider_id, provider_id)
                else:
                    self.assertIs(adapter.http, http)

    def test_gemini_contract_discovers_canonical_ids_and_uses_custom_proxy_auth(self):
        http = FakeHttp(
            FakeResponse(
                {
                    "models": [
                        {
                            "name": "models/gemini-3-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/embed-1",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                    ]
                }
            ),
            FakeResponse(
                {
                    "candidates": [{"content": {"parts": [{"text": "hello"}]}}],
                }
            ),
        )
        registry = build_provider_registry(http)
        connection = ProviderConnection("proxy-key", "https://proxy.example")

        catalog = registry.discover_models("gemini", connection)
        result = registry.transcribe(
            "gemini",
            TranscriptionRequest(
                audio_path=self.audio_path,
                model="models/gemini-3-flash",
                language="en",
                instruction="Transcribe faithfully.",
                prompt="Transcribe this audio.",
                temperature=0.0,
            ),
            connection,
        )

        self.assertEqual(
            catalog, ModelCatalog(("gemini-3-flash",), ("gemini-3-flash",))
        )
        self.assertEqual(result.text, "hello")
        self.assertEqual(result.model, "gemini-3-flash")
        self.assertEqual(http.calls[0][1], "https://proxy.example/v1beta/models")
        self.assertEqual(
            http.calls[0][2]["headers"],
            {
                "x-goog-api-key": "proxy-key",
                "Authorization": "Bearer proxy-key",
            },
        )
        self.assertEqual(
            http.calls[1][1],
            "https://proxy.example/v1beta/models/gemini-3-flash:generateContent",
        )
        self.assertEqual(http.calls[0][2]["operation"], "model_discovery")
        self.assertEqual(http.calls[1][2]["operation"], "transcription")
        self.assertFalse(http.calls[1][2]["safe_to_retry"])
        self.assertNotIn("timeout", http.calls[0][2])
        self.assertNotIn("timeout", http.calls[1][2])

    def test_openai_compatible_contract_filters_catalog_and_uses_api_ids(self):
        http = FakeHttp(
            FakeResponse(
                {
                    "data": [
                        {"id": "whisper-compatible", "name": "Pretty Whisper"},
                        {"id": "chat-compatible", "name": "Pretty Chat"},
                        {"id": "text-embedding-compatible"},
                    ]
                }
            ),
            FakeResponse({"text": "raw transcript"}),
            FakeResponse({"choices": [{"message": {"content": "rewritten"}}]}),
        )
        registry = ProviderRegistry()
        registry.register_openai_compatible(
            compatible_metadata(),
            http,
            audio_model_aliases={"Pretty Whisper": "whisper-compatible"},
        )
        connection = ProviderConnection("key", "https://proxy.example/v1")

        catalog = registry.discover_models("compatible", connection)
        transcript = registry.transcribe(
            "compatible",
            TranscriptionRequest(
                self.audio_path,
                "Pretty Whisper",
                "pt",
                "unused",
                "unused",
                0.0,
            ),
            connection,
        )
        rewrite = registry.rewrite(
            "compatible",
            RewriteRequest(
                "raw transcript",
                "chat-compatible",
                "pt",
                "Rewrite.",
                "SOURCE",
                0.1,
            ),
            connection,
        )

        self.assertEqual(catalog.audio_models, ("whisper-compatible",))
        self.assertEqual(catalog.text_models, ("chat-compatible",))
        self.assertEqual(transcript.model, "whisper-compatible")
        self.assertEqual(rewrite.text, "rewritten")
        self.assertEqual(
            http.calls[1][1], "https://proxy.example/v1/audio/transcriptions"
        )
        self.assertEqual(http.calls[1][2]["data"]["model"], "whisper-compatible")
        self.assertEqual(http.calls[2][1], "https://proxy.example/v1/chat/completions")
        self.assertEqual(http.calls[0][2]["operation"], "model_discovery")
        self.assertEqual(http.calls[1][2]["operation"], "transcription")
        self.assertEqual(http.calls[2][2]["operation"], "text_generation")
        self.assertFalse(http.calls[1][2]["safe_to_retry"])
        self.assertFalse(http.calls[2][2]["safe_to_retry"])
        for _method, _url, kwargs in http.calls:
            self.assertNotIn("timeout", kwargs)

    def test_openai_compatible_contract_accepts_models_catalog_key(self):
        http = FakeHttp(
            FakeResponse(
                {
                    "models": [
                        {"id": "whisper-compatible"},
                        {"id": "chat-compatible"},
                    ]
                }
            )
        )
        registry = ProviderRegistry()
        registry.register_openai_compatible(compatible_metadata(), http)

        catalog = registry.discover_models(
            "compatible",
            ProviderConnection("key", "https://proxy.example/v1"),
        )

        self.assertEqual(catalog.audio_models, ("whisper-compatible",))
        self.assertEqual(catalog.text_models, ("chat-compatible",))

    def test_audio_upload_uses_snapshot_without_opening_recording_path(self):
        http = FakeHttp(FakeResponse({"text": "snapshot transcript"}))
        uploaded = []
        original_request = http.request

        def capture_request(method, url, **kwargs):
            uploaded.append(kwargs["files"]["file"][1].read())
            return original_request(method, url, **kwargs)

        http.request = capture_request
        registry = ProviderRegistry()
        registry.register_openai_compatible(compatible_metadata(), http)
        request = TranscriptionRequest(
            self.audio_path,
            "whisper-compatible",
            "en",
            "unused",
            "unused",
            0.0,
            audio_bytes=b"snapshot-bytes",
        )
        self.audio_path.unlink()

        result = registry.transcribe(
            "compatible", request, ProviderConnection("key", "https://proxy.example/v1")
        )

        self.assertEqual(result.text, "snapshot transcript")
        self.assertEqual(uploaded, [b"snapshot-bytes"])

    def test_compatible_provider_routes_without_changes_to_workflow_code(self):
        http = FakeHttp(
            FakeResponse({"text": "transcribed"}),
            FakeResponse({"choices": [{"message": {"content": "translated"}}]}),
        )
        registry = ProviderRegistry()
        registry.register_openai_compatible(compatible_metadata("acme"), http)
        connection = ProviderConnection("key", "https://acme.example")

        transcription = registry.transcribe(
            "acme",
            TranscriptionRequest(
                self.audio_path,
                "whisper-acme",
                "en",
                "unused",
                "unused",
                0.0,
            ),
            connection,
        )
        translation = registry.translate(
            "acme",
            TranslationRequest(
                "Hello",
                "chat-acme",
                "de",
                "Translate to German.",
                "SOURCE",
                0.0,
            ),
            connection,
        )

        self.assertEqual(transcription.text, "transcribed")
        self.assertEqual(translation.text, "translated")
        self.assertEqual(translation.target_language, "de")

    def test_openai_compatible_text_operations_accept_non_empty_strings(self):
        http = FakeHttp(
            FakeResponse(
                {
                    "choices": [{"message": {"content": "  rewritten  "}}],
                }
            ),
            FakeResponse(
                {
                    "choices": [{"message": {"content": "  translated  "}}],
                }
            ),
        )
        registry = ProviderRegistry()
        registry.register_openai_compatible(compatible_metadata(), http)
        connection = ProviderConnection("key", "https://compatible.example/v1")

        rewrite = registry.rewrite(
            "compatible",
            RewriteRequest(
                "Raw",
                "chat-compatible",
                "en",
                "Rewrite.",
                "SOURCE",
                0.1,
            ),
            connection,
        )
        translation = registry.translate(
            "compatible",
            TranslationRequest(
                "Hello",
                "chat-compatible",
                "de",
                "Translate.",
                "SOURCE",
                0.0,
            ),
            connection,
        )

        self.assertEqual(rewrite.text, "rewritten")
        self.assertEqual(translation.text, "translated")

    def test_openai_compatible_text_operations_reject_invalid_content(self):
        requests = (
            (
                "rewrite",
                RewriteRequest(
                    "Raw",
                    "chat-compatible",
                    "en",
                    "Rewrite.",
                    "SOURCE",
                    0.1,
                ),
            ),
            (
                "translate",
                TranslationRequest(
                    "Hello",
                    "chat-compatible",
                    "de",
                    "Translate.",
                    "SOURCE",
                    0.0,
                ),
            ),
        )

        for operation, request in requests:
            for content in (None, [], {}, "   "):
                with self.subTest(operation=operation, content=content):
                    http = FakeHttp(
                        FakeResponse(
                            {
                                "choices": [{"message": {"content": content}}],
                            }
                        )
                    )
                    registry = ProviderRegistry()
                    registry.register_openai_compatible(compatible_metadata(), http)

                    with self.assertRaises(InvalidResponseError) as raised:
                        getattr(registry, operation)(
                            "compatible",
                            request,
                            ProviderConnection("key", "https://compatible.example/v1"),
                        )

                    self.assertEqual(
                        raised.exception.capability,
                        ProviderCapability.TEXT_GENERATION,
                    )

    def test_malformed_success_responses_keep_ids_and_emit_diagnostic_events(self):
        connection = ProviderConnection("key", "https://compatible.example/v1")

        cases = (
            (
                "transcription",
                {"text": "   "},
                lambda registry: registry.transcribe(
                    "compatible",
                    TranscriptionRequest(
                        self.audio_path,
                        "whisper-compatible",
                        "en",
                        "unused",
                        "unused",
                        0.0,
                    ),
                    connection,
                ),
            ),
            (
                "text_generation",
                {"choices": [{"message": {"content": "   "}}]},
                lambda registry: registry.rewrite(
                    "compatible",
                    RewriteRequest(
                        "Raw", "chat-compatible", "en", "Rewrite.", "SOURCE", 0.1
                    ),
                    connection,
                ),
            ),
            (
                "model_discovery",
                {"data": {"not": "a list"}},
                lambda registry: registry.discover_models("compatible", connection),
            ),
        )

        for operation, payload, invoke in cases:
            with self.subTest(operation=operation):
                response = FakeResponse(payload)
                response._clarify_operation_id = f"{operation}-123"
                http = FakeHttp(response)
                registry = ProviderRegistry()
                registry.register_openai_compatible(compatible_metadata(), http)

                with self.assertRaises(InvalidResponseError) as raised:
                    invoke(registry)

                self.assertEqual(raised.exception.operation_id, f"{operation}-123")
                self.assertEqual(len(http.events), 1)
                self.assertEqual(
                    http.events[0],
                    {
                        "event": "provider_http_error",
                        "provider": "compatible",
                        "operation": operation,
                        "operation_id": f"{operation}-123",
                        "status_code": 200,
                        "error_type": "invalid_response",
                    },
                )

    def test_unsupported_capability_is_typed_and_actionable(self):
        registry = ProviderRegistry()
        metadata = compatible_metadata("textonly", {ProviderCapability.TEXT_GENERATION})
        registry.register(OpenAICompatibleAdapter(metadata, FakeHttp()))

        with self.assertRaises(UnsupportedCapabilityError) as raised:
            registry.transcribe(
                "textonly",
                TranscriptionRequest(
                    self.audio_path,
                    "model",
                    "en",
                    "unused",
                    "unused",
                    0.0,
                ),
                ProviderConnection("key", "https://text.example"),
            )

        self.assertEqual(
            raised.exception.capability,
            ProviderCapability.AUDIO_TRANSCRIPTION,
        )
        self.assertIn("does not support audio transcription", str(raised.exception))
        self.assertIn("Choose a provider", str(raised.exception))

    def test_missing_credentials_raise_typed_configuration_error(self):
        registry = build_provider_registry(FakeHttp())

        with self.assertRaises(ProviderConfigurationError) as raised:
            registry.validate(
                "gemini",
                ProviderConnection(
                    "", "https://generativelanguage.googleapis.com/v1beta"
                ),
            )

        self.assertEqual(raised.exception.provider_id, "gemini")
        self.assertIn("API key", str(raised.exception))

    def test_provider_layer_never_imports_tk_or_ui_modules(self):
        for filename in (
            "provider_types.py",
            "provider_adapters.py",
            "provider_registry.py",
        ):
            source = (ROOT / filename).read_text(encoding="utf-8").lower()
            self.assertNotIn("tkinter", source, filename)
            self.assertNotIn("customtkinter", source, filename)
            self.assertNotIn("from app", source, filename)


if __name__ == "__main__":
    unittest.main()
