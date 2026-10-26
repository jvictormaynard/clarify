"""ChatGPT plan contracts with synthetic tokens and offline HTTP streams."""

import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from provider_http import (
    CancellationToken,
    InvalidResponseError,
    InvalidModelError,
    ProviderCancelledError,
    ProviderTimeoutError,
    QuotaError,
    _http_error,
    localized_error_message,
)
from provider_registry import build_provider_registry
from provider_types import (
    ProviderCapability,
    ProviderConfigurationError,
    ProviderConnection,
    RewriteRequest,
    TranslationRequest,
    TranscriptionResult,
    UnsupportedCapabilityError,
)
from repositories import AppConfig, LocalConfigRepository
from secret_store import MemorySecretStore
from workflow_config import (
    WorkflowConfigurationError,
    WorkflowRoute,
    validate_workflow_route,
)
from workflow_provider import WorkflowProviderService
from workflows import RecordingSnapshot


class SessionChanged(RuntimeError):
    code = "stale_session"


class Session:
    def __init__(self):
        self.generation = 1

    def credential(self, *, cancel_token=None):
        if cancel_token:
            cancel_token.raise_if_cancelled()
        return SimpleNamespace(
            access_token="synthetic-oauth-token",
            generation=self.generation,
            account_id="synthetic-account",
        )

    def check_current(self, generation):
        if generation != self.generation:
            raise SessionChanged("The selected ChatGPT session changed.")


class Response:
    status_code = 200
    headers = {"Content-Type": "text/event-stream", "x-request-id": "synthetic-request"}

    def __init__(self, events=(), *, payload=None, before_event=None):
        self.events = list(events)
        self.payload = payload
        self.before_event = before_event
        self.closed = False

    def json(self):
        return self.payload

    def iter_lines(self, **kwargs):
        for event in self.events:
            if self.before_event:
                self.before_event(event)
            yield ("data: " + json.dumps(event)).encode()
            yield b""

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size):
        for event in self.events:
            if self.before_event:
                self.before_event(event)
            content = ("data: " + json.dumps(event) + "\n\n").encode()
            for offset in range(0, len(content), chunk_size):
                yield content[offset : offset + chunk_size]


class Http:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def json(self, response, **kwargs):
        return response.json()


def completed(text):
    return {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}
            ],
        },
    }


class ChatGPTProviderTests(unittest.TestCase):
    connection = ProviderConnection(
        "", "https://api.openai.com/v1", "synthetic-account"
    )
    rewrite = RewriteRequest(
        "source", "available-model", "pt", "Keep all facts.", "source"
    )

    def adapter(self, *responses, session=None):
        http = Http(*responses)
        session = session or Session()
        registry = build_provider_registry(http, chatgpt_session=session)
        return registry.adapter("chatgpt"), http

    def test_previous_account_model_is_rejected_before_inference(self):
        for account_id in ("previous-account", ""):
            with self.subTest(account_id=account_id):
                adapter, http = self.adapter(Response([completed("wrong account")]))
                connection = SimpleNamespace(
                    base_url=self.connection.base_url, api_key="", account_id=account_id
                )
                with self.assertRaises(InvalidModelError):
                    adapter.rewrite(self.rewrite, connection)
                self.assertFalse(http.calls)

    def test_unterminated_stream_checks_limits_during_read(self):
        class DripResponse(Response):
            def __init__(self, on_chunk=None):
                super().__init__()
                self.consumed = 0
                self.on_chunk = on_chunk

            def chunks(self):
                for _ in range(40):
                    self.consumed += 1
                    if self.on_chunk:
                        self.on_chunk()
                    yield b"x"

            def iter_lines(self, **kwargs):
                yield b"".join(self.chunks())

            def iter_content(self, chunk_size):
                yield from self.chunks()

        for mode, expected, limit in (
            ("size", InvalidResponseError, 17),
            ("deadline", ProviderTimeoutError, 2),
            ("cancel", ProviderCancelledError, 1),
        ):
            with self.subTest(mode=mode):
                token = CancellationToken()
                now = [0.0]

                def on_chunk():
                    if mode == "cancel":
                        token.cancel()
                    if mode == "deadline":
                        now[0] += 70.0

                response = DripResponse(on_chunk)
                adapter, _ = self.adapter(response)
                with (
                    patch("chatgpt_provider.MAX_EVENT_BYTES", 16),
                    patch(
                        "chatgpt_provider.time.monotonic", side_effect=lambda: now[0]
                    ),
                    self.assertRaises(expected),
                ):
                    adapter.rewrite(self.rewrite, self.connection, token)
                self.assertLessEqual(response.consumed, limit)
                self.assertTrue(response.closed)

    def test_registered_only_for_text_and_model_discovery(self):
        metadata = build_provider_registry().describe("chatgpt")
        self.assertEqual(metadata.authentication, "oauth")
        self.assertEqual(
            metadata.capabilities,
            frozenset(
                {
                    ProviderCapability.TEXT_GENERATION,
                    ProviderCapability.MODEL_DISCOVERY,
                }
            ),
        )

    def test_catalog_uses_visible_slugs_and_server_order_with_display_names(self):
        adapter, http = self.adapter(
            Response(
                payload={
                    "models": [
                        {
                            "slug": "second-model",
                            "display_name": "Second model",
                            "visibility": "list",
                        },
                        {
                            "slug": "hidden",
                            "display_name": "Hidden",
                            "visibility": "hide",
                        },
                        {
                            "slug": "first-model",
                            "display_name": "First model",
                            "visibility": "list",
                        },
                    ]
                }
            )
        )
        catalog = adapter.discover_models(self.connection)
        self.assertEqual(catalog.text_models, ("second-model", "first-model"))
        self.assertEqual(catalog.audio_models, ())
        self.assertEqual(catalog.display_names["first-model"], "First model")
        method, url, kwargs = http.calls[0]
        self.assertEqual((method, url), ("GET", "https://api.openai.com/v1/models"))
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Bearer synthetic-oauth-token"
        )
        self.assertFalse(kwargs["allow_redirects"])

    def test_rewrite_uses_supported_responses_body_and_completed_output(self):
        response = Response(
            [
                {"type": "response.output_text.delta", "delta": "Edited "},
                {"type": "response.output_text.delta", "delta": "source."},
                completed("Edited source."),
            ]
        )
        adapter, http = self.adapter(response)
        result = adapter.rewrite(self.rewrite, self.connection)
        self.assertEqual(
            (result.text, result.provider_id), ("Edited source.", "chatgpt")
        )
        method, url, kwargs = http.calls[0]
        self.assertEqual((method, url), ("POST", "https://api.openai.com/v1/responses"))
        self.assertEqual(
            kwargs["json"],
            {
                "model": "available-model",
                "instructions": "Keep all facts.",
                "input": [{"role": "user", "content": "source"}],
                "store": False,
                "stream": True,
            },
        )
        self.assertTrue(kwargs["stream"])
        self.assertFalse(kwargs["safe_to_retry"])
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(response.closed)

    def test_translation_preserves_target_and_uses_same_text_boundary(self):
        adapter, _ = self.adapter(Response([completed("Olá.")]))
        result = adapter.translate(
            TranslationRequest(
                "Hello.", "available-model", "pt", "Translate to Portuguese.", "Hello."
            ),
            self.connection,
        )
        self.assertEqual((result.text, result.target_language), ("Olá.", "pt"))

    def test_truncated_incomplete_or_refused_stream_never_returns_partial_text(self):
        for terminal in (None, {"type": "response.incomplete"}, completed("")):
            with self.subTest(terminal=terminal):
                events = [{"type": "response.output_text.delta", "delta": "partial"}]
                if terminal:
                    events.append(terminal)
                response = Response(events)
                adapter, _ = self.adapter(response)
                with self.assertRaises(InvalidResponseError):
                    adapter.rewrite(self.rewrite, self.connection)
                self.assertTrue(response.closed)

    def test_usage_limit_after_first_delta_is_a_terminal_quota_error(self):
        response = Response(
            [
                {"type": "response.output_text.delta", "delta": "partial"},
                {
                    "type": "response.failed",
                    "response": {
                        "error": {
                            "code": "subscription_sharing_usage_limit_exceeded",
                            "message": "private content",
                        }
                    },
                },
            ]
        )
        adapter, http = self.adapter(response)
        with self.assertRaises(QuotaError) as caught:
            adapter.rewrite(self.rewrite, self.connection)
        self.assertEqual(caught.exception.code, "chatgpt_plan_limit")
        self.assertEqual(
            caught.exception.response_code, "subscription_sharing_usage_limit_exceeded"
        )
        self.assertNotIn("private content", str(caught.exception))
        self.assertTrue(response.closed)
        self.assertEqual(len(http.calls), 1)

    def test_http_admission_preserves_machine_code_and_request_id_without_content(self):
        response = Response(
            payload={
                "error": {
                    "code": "subscription_sharing_usage_limit_exceeded",
                    "message": "private source",
                }
            }
        )
        response.status_code = 429
        error = _http_error(response, "chatgpt", "text_generation", "operation-id")
        self.assertIsInstance(error, QuotaError)
        self.assertEqual(error.request_id, "synthetic-request")
        self.assertEqual(
            error.response_code, "subscription_sharing_usage_limit_exceeded"
        )
        self.assertIn("ChatGPT", localized_error_message(error, "pt"))
        self.assertNotIn("private source", str(error))

    def test_freeform_admission_error_is_safe_and_does_not_invent_a_server_code(self):
        response = Response(payload={"detail": "private policy explanation"})
        response.status_code = 403
        error = _http_error(response, "chatgpt", "validation", "operation-id")
        self.assertEqual(error.code, "chatgpt_plan_ineligible")
        self.assertEqual(error.response_code, "")
        self.assertEqual(error.status_code, 403)
        self.assertEqual(error.request_id, "synthetic-request")
        self.assertNotIn("private policy", str(error))

    def test_cancellation_and_account_switch_reject_output_and_close_stream(self):
        for switch in (False, True):
            with self.subTest(switch=switch):
                session, token = Session(), CancellationToken()

                def interrupt(event):
                    if switch:
                        session.generation += 1
                    else:
                        token.cancel()

                response = Response([completed("stale")], before_event=interrupt)
                adapter, _ = self.adapter(response, session=session)
                with self.assertRaises(ProviderCancelledError):
                    adapter.rewrite(self.rewrite, self.connection, token)
                self.assertTrue(response.closed)

    def test_custom_endpoint_cannot_receive_oauth_token(self):
        adapter, http = self.adapter()
        with self.assertRaises(ProviderConfigurationError):
            adapter.rewrite(
                self.rewrite, ProviderConnection("", "https://other.example/v1")
            )
        self.assertEqual(http.calls, [])

    def test_audio_and_custom_workflow_endpoint_are_rejected(self):
        registry = build_provider_registry()
        with self.assertRaises(UnsupportedCapabilityError):
            registry.adapter("chatgpt", ProviderCapability.AUDIO_TRANSCRIPTION)
        with self.assertRaises(WorkflowConfigurationError):
            validate_workflow_route(
                WorkflowRoute("chatgpt", "available-model"), "transcription"
            )
        with self.assertRaises(WorkflowConfigurationError):
            validate_workflow_route(
                WorkflowRoute(
                    "chatgpt",
                    "available-model",
                    custom_endpoint="https://other.example",
                ),
                "rewrite",
            )

    def test_configuration_round_trip_preserves_independent_chatgpt_route_without_tokens(
        self,
    ):
        config = AppConfig.from_mapping(
            {
                "workflows": {
                    "rewrite": {
                        "provider_id": "chatgpt",
                        "model_id": "available-model",
                        "account_id": "synthetic-account",
                    },
                }
            }
        )
        loaded = AppConfig.from_mapping(config.to_mapping())
        self.assertEqual(loaded.workflow("rewrite").provider_id, "chatgpt")
        self.assertEqual(loaded.workflow("rewrite").model_id, "available-model")
        self.assertEqual(loaded.workflow("rewrite").account_id, "synthetic-account")
        self.assertEqual(loaded.selection.transcription_provider, "gemini")
        self.assertEqual(loaded.chatgpt.api_key, "")
        self.assertNotIn("chatgpt_api_key", loaded.to_mapping())
        self.assertEqual(
            replace(loaded, history_enabled=True).workflow("rewrite"),
            loaded.workflow("rewrite"),
        )


class ChatGPTWorkflowIntegrationTests(unittest.TestCase):
    def test_voice_translation_preserves_the_profile_account_binding(self):
        from clarify.desktop.qml_voice_translation import QmlVoiceTranslationProvider
        from voice_translation import VoiceTranslationRequest

        config = AppConfig.from_mapping(
            {
                "voice_translation": {
                    "route": {
                        "provider_id": "chatgpt",
                        "model_id": "available-model",
                        "account_id": "synthetic-account",
                    }
                },
            }
        )
        config = AppConfig.from_mapping(config.to_mapping())
        http = Http(Response([completed("Translated text.")]))
        provider = QmlVoiceTranslationProvider(
            lambda: config,
            registry=build_provider_registry(http, chatgpt_session=Session()),
        )
        request = VoiceTranslationRequest(
            "Original.", "pt", "en", config.voice_translation.route
        )
        self.assertEqual(provider.translate(request).text, "Translated text.")
        self.assertEqual(len(http.calls), 1)

    def test_pending_model_selection_persists_and_cannot_start_inference(self):
        with TemporaryDirectory() as directory:
            repository = LocalConfigRepository(
                Path(directory) / "config.json",
                environment={},
                secret_store=MemorySecretStore(),
            )
            config = repository.load()
            config = replace(
                config,
                workflows=config.workflows.with_route(
                    "rewrite",
                    WorkflowRoute("chatgpt", ""),
                ),
            )
            repository.apply(config)
            loaded = repository.load()
            self.assertEqual(loaded.workflow("rewrite").model_id, "")
            http = Http()
            service = WorkflowProviderService(
                SimpleNamespace(current=lambda: loaded, workflow=loaded.workflow),
                SimpleNamespace(),
                registry=build_provider_registry(http, chatgpt_session=Session()),
            )
            with self.assertRaisesRegex(RuntimeError, "No model configured"):
                service.rewrite("Keep this text.")
            self.assertEqual(http.calls, [])

    def test_profile_registry_reuses_existing_adapters_without_replacing_global_session(
        self,
    ):
        session_a, session_b = Session(), Session()
        registry = build_provider_registry(Http(), chatgpt_session=session_a)
        scoped = registry.with_chatgpt_session(session_b)
        self.assertIs(scoped.adapter("chatgpt").session, session_b)
        self.assertIs(registry.adapter("chatgpt").session, session_a)
        self.assertIs(scoped.adapter("local_asr"), registry.adapter("local_asr"))
        self.assertIs(scoped.adapter("openai"), registry.adapter("openai"))

    def test_local_transcript_refines_with_plan_and_preserves_original(self):
        raw = "Olá, use 42 unidades."
        config = AppConfig.from_mapping(
            {
                "local_asr_cloud_refinement": True,
                "workflows": {
                    "transcription": {
                        "provider_id": "local_asr",
                        "model_id": "ggml-small",
                    },
                    "local_asr_refinement": {
                        "provider_id": "chatgpt",
                        "model_id": "available-model",
                        "account_id": "synthetic-account",
                        "enabled": True,
                    },
                },
            }
        )
        settings = SimpleNamespace(current=lambda: config, workflow=config.workflow)
        dictionary = SimpleNamespace(
            expand_spoken_trigger=lambda text: None,
            expand=lambda text: text,
            refinement_context=lambda: "",
            apply_context=lambda request: request,
        )
        response = Response([completed("Olá. Use 42 unidades.")])
        http = Http(response)
        registry = build_provider_registry(http, chatgpt_session=Session())
        service = WorkflowProviderService(settings, dictionary, registry=registry)
        audio = RecordingSnapshot(
            Path("not-read.wav"),
            b"synthetic-audio",
            CancellationToken(),
            pretranscribed=TranscriptionResult(raw, "local_asr", "ggml-small"),
        )
        with patch("provider_registry.PROVIDER_HTTP.logger", Mock()):
            result = service.transcribe(audio, "prompt", "pt")
        self.assertEqual(result.text, "Olá. Use 42 unidades.")
        self.assertEqual(result.raw_text, raw)
        self.assertEqual(result.refinement_provider_id, "chatgpt")
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(http.calls[0][1], "https://api.openai.com/v1/responses")
        self.assertNotIn("audio", http.calls[0][2]["json"])


if __name__ == "__main__":
    unittest.main()
