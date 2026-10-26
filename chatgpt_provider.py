"""Text-only Responses adapter for the user's authorized ChatGPT plan."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping

import requests

from provider_adapters import ProviderAdapter, _invalid_response_error
from provider_http import (
    ChatGPTPermissionError,
    InvalidModelError,
    NetworkError,
    ProviderCancelledError,
    ProviderTimeoutError,
    chatgpt_response_error,
)
from provider_types import (
    ModelCatalog,
    ProviderCapability,
    ProviderConfigurationError,
    ProviderMetadata,
    ProviderError,
    RewriteResult,
    TranslationResult,
)


CHATGPT_BASE_URL = "https://api.openai.com/v1"
MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = 1024 * 1024
MAX_STREAM_SECONDS = 120.0


class ChatGPTPlanAdapter(ProviderAdapter):
    def __init__(self, http, *, session=None):
        super().__init__(
            ProviderMetadata(
                provider_id="chatgpt",
                display_name="ChatGPT (subscription)",
                capabilities=frozenset(
                    {
                        ProviderCapability.TEXT_GENERATION,
                        ProviderCapability.MODEL_DISCOVERY,
                    }
                ),
                default_base_url=CHATGPT_BASE_URL,
                audio_model_key="chatgpt_audio_model",
                text_model_key="chatgpt_text_model",
                default_audio_model="",
                default_text_model="",
                authentication="oauth",
            ),
            http,
        )
        self._session = session

    @property
    def session(self):
        if self._session is not None:
            return self._session
        # Import and credential access stay lazy. Importing the registry must
        # not open a profile or attempt authentication.
        from chatgpt_auth import get_chatgpt_session

        return get_chatgpt_session()

    def with_session(self, session):
        if self._session is session:
            return self
        return ChatGPTPlanAdapter(self.http, session=session)

    def _require_connection(self, connection):
        if connection.base_url.rstrip("/") != CHATGPT_BASE_URL:
            raise ProviderConfigurationError(
                "chatgpt", "ChatGPT plan requests require the official OpenAI endpoint."
            )

    @staticmethod
    def _session_call(callback, *args, operation="text_generation", **kwargs):
        try:
            return callback(*args, **kwargs)
        except ProviderError:
            raise
        except RuntimeError as error:
            # Session errors have safe machine codes. Cancellation must retain
            # its type so optional refinement cannot publish a stale result.
            code = getattr(error, "code", None)
            error_type = {
                "cancelled": ProviderCancelledError,
                "stale_session": ProviderCancelledError,
                "network": NetworkError,
                "timeout": ProviderTimeoutError,
                "plan_disabled": ChatGPTPermissionError,
                "sign_in_required": ChatGPTPermissionError,
                "refresh_failed": ChatGPTPermissionError,
            }.get(code)
            if error_type is None:
                raise
            raise error_type(provider="chatgpt", operation=operation) from None

    def parse_audio_models(self, payload):
        return ()

    def parse_text_models(self, payload):
        return tuple(
            dict.fromkeys(
                entry["slug"]
                for entry in payload.get("models", [])
                if isinstance(entry, Mapping)
                and entry.get("visibility") == "list"
                and isinstance(entry.get("slug"), str)
                and entry["slug"].strip()
            )
        )

    def validate(self, connection, cancel_token=None, *, operation="validation"):
        self._require_connection(connection)
        session = self.session
        credential = self._session_call(
            session.credential, cancel_token=cancel_token, operation=operation
        )
        response = self.http.request(
            "GET",
            f"{CHATGPT_BASE_URL}/models",
            provider="chatgpt",
            operation=operation,
            cancel_token=cancel_token,
            headers={"Authorization": f"Bearer {credential.access_token}"},
            allow_redirects=False,
        )
        try:
            payload = self.http.json(response, provider="chatgpt", operation=operation)
            self._session_call(
                session.check_current, credential.generation, operation=operation
            )
            if not isinstance(payload, Mapping) or not isinstance(
                payload.get("models"), list
            ):
                raise _invalid_response_error(self.http, response, "chatgpt", operation)
            return payload
        finally:
            response.close()

    def discover_models(self, connection, cancel_token=None):
        payload = self.validate(connection, cancel_token, operation="model_discovery")
        models = self.parse_text_models(payload)
        names = {
            entry["slug"]: entry["display_name"]
            for entry in payload["models"]
            if isinstance(entry, Mapping)
            and entry.get("slug") in models
            and isinstance(entry.get("display_name"), str)
        }
        return ModelCatalog(text_models=models, display_names=names)

    @staticmethod
    def _completed_text(event, streamed_output=()):
        response = event.get("response")
        if not isinstance(response, Mapping) or response.get("status") != "completed":
            return ""
        output = response.get("output")
        if "output" not in response or output == []:
            output = list(streamed_output)
        if not isinstance(output, list):
            return ""
        parts = []
        for item in output:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, Mapping) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        return "".join(parts).strip()

    def _generate_text(self, request, connection, cancel_token):
        self._require_connection(connection)
        model = str(request.model or "").strip()
        if not model:
            raise ProviderConfigurationError(
                "chatgpt", "Choose a model available to your ChatGPT account."
            )
        session = self.session
        credential = self._session_call(session.credential, cancel_token=cancel_token)
        if not connection.account_id or connection.account_id != credential.account_id:
            raise InvalidModelError(provider="chatgpt", operation="text_generation")
        response = self.http.request(
            "POST",
            f"{CHATGPT_BASE_URL}/responses",
            provider="chatgpt",
            operation="text_generation",
            cancel_token=cancel_token,
            safe_to_retry=False,
            headers={
                "Authorization": f"Bearer {credential.access_token}",
                "Accept": "text/event-stream",
            },
            json={
                "model": model,
                "instructions": request.instruction,
                "input": [{"role": "user", "content": request.source_message}],
                "store": False,
                "stream": True,
            },
            stream=True,
            allow_redirects=False,
        )
        started, total, event_size = time.monotonic(), 0, 0
        last_session_check = started
        data = []
        # These finalized items are still provisional until response.completed.
        # The existing total-stream byte limit also bounds this collection.
        streamed_items = {}

        def check(*, force_session=True):
            nonlocal last_session_check
            if cancel_token:
                cancel_token.raise_if_cancelled("chatgpt", "text_generation")
            now = time.monotonic()
            if now - started > MAX_STREAM_SECONDS:
                raise ProviderTimeoutError(
                    provider="chatgpt", operation="text_generation"
                )
            if force_session or now - last_session_check >= 0.05:
                self._session_call(session.check_current, credential.generation)
                last_session_check = now

        def invalid():
            return _invalid_response_error(
                self.http, response, "chatgpt", "text_generation"
            )

        def bounded_lines():
            nonlocal total
            pending = bytearray()
            # A one-byte read returns even when a peer drips bytes without a
            # newline. Larger iter_content reads can wait for a complete chunk.
            for chunk in response.iter_content(chunk_size=1):
                check(force_session=False)
                if not isinstance(chunk, bytes):
                    raise invalid()
                total += len(chunk)
                if total > MAX_STREAM_BYTES:
                    raise invalid()
                for byte in chunk:
                    if byte == 10:
                        yield pending.rstrip(b"\r").decode("utf-8")
                        pending.clear()
                    else:
                        pending.append(byte)
                        if len(pending) > MAX_EVENT_BYTES:
                            raise invalid()
            if pending:
                yield pending.rstrip(b"\r").decode("utf-8")

        try:
            for line in bounded_lines():
                check()
                if line:
                    if line.startswith("data:"):
                        value = line[5:].lstrip(" ")
                        event_size += len(value.encode("utf-8"))
                        if event_size > MAX_EVENT_BYTES:
                            raise invalid()
                        data.append(value)
                    continue
                if not data:
                    continue
                event = json.loads("\n".join(data))
                data, event_size = [], 0
                if not isinstance(event, Mapping):
                    raise invalid()
                kind = event.get("type")
                if kind == "response.output_item.done":
                    item, index = event.get("item"), event.get("output_index")
                    if not isinstance(item, Mapping):
                        raise invalid()
                    if item.get("type") == "message":
                        if (
                            item.get("role") != "assistant"
                            or item.get("status") != "completed"
                            or not isinstance(index, int)
                            or isinstance(index, bool)
                            or index < 0
                            or (
                                index in streamed_items
                                and streamed_items[index] != item
                            )
                        ):
                            raise invalid()
                        streamed_items[index] = item
                    continue
                if kind == "response.completed":
                    text = self._completed_text(
                        event,
                        (streamed_items[index] for index in sorted(streamed_items)),
                    )
                    if not text:
                        raise invalid()
                    check()
                    return text
                if kind in {"response.failed", "error"}:
                    body = event.get("response", event)
                    error = body.get("error", body) if isinstance(body, Mapping) else {}
                    code = error.get("code", "") if isinstance(error, Mapping) else ""
                    raise chatgpt_response_error(
                        code,
                        operation="text_generation",
                        status_code=response.status_code,
                        operation_id=getattr(response, "_clarify_operation_id", None),
                        request_id=response.headers.get("x-request-id")
                        or response.headers.get("openai-request-id"),
                    )
                if kind == "response.incomplete":
                    raise invalid()
            raise invalid()
        except (ValueError, UnicodeError) as error:
            raise invalid() from error
        except requests.Timeout as error:
            raise ProviderTimeoutError(
                provider="chatgpt", operation="text_generation"
            ) from error
        except requests.RequestException as error:
            raise NetworkError(
                provider="chatgpt", operation="text_generation"
            ) from error
        finally:
            response.close()

    def rewrite(self, request, connection, cancel_token=None):
        text = self._generate_text(request, connection, cancel_token)
        return RewriteResult(text, "chatgpt", request.model)

    def translate(self, request, connection, cancel_token=None):
        text = self._generate_text(request, connection, cancel_token)
        return TranslationResult(
            text, "chatgpt", request.model, request.target_language
        )
