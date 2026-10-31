"""Reusable provider registry fixtures. This module defines no test cases."""

import tempfile


from pathlib import Path


from provider_http import InvalidResponseError


from provider_types import (
    ProviderCapability,
    ProviderMetadata,
)

ROOT = Path(__file__).resolve().parents[2]


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.events = []

    def _request(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected {method} request to {url}")
        return self.responses.pop(0)

    def request(self, method, url, **kwargs):
        return self._request(method.upper(), url, kwargs)

    @staticmethod
    def json(response, **_kwargs):
        return response.json()

    def invalid_response(self, response, *, provider, operation):
        error = InvalidResponseError(
            provider=provider,
            operation=operation,
            status_code=response.status_code,
            operation_id=getattr(response, "_clarify_operation_id", None),
        )
        self.events.append(
            {
                "event": "provider_http_error",
                "provider": provider,
                "operation": operation,
                "operation_id": error.operation_id,
                "status_code": error.status_code,
                "error_type": error.code,
            }
        )
        return error


def compatible_metadata(provider_id="compatible", capabilities=None):
    return ProviderMetadata(
        provider_id=provider_id,
        display_name=provider_id.title(),
        capabilities=frozenset(
            capabilities
            or {
                ProviderCapability.AUDIO_TRANSCRIPTION,
                ProviderCapability.TEXT_GENERATION,
                ProviderCapability.MODEL_DISCOVERY,
                ProviderCapability.CUSTOM_BASE_URL,
            }
        ),
        default_base_url="https://compatible.example/v1",
        audio_model_key=f"{provider_id}_audio_model",
        text_model_key=f"{provider_id}_text_model",
        default_audio_model="whisper-compatible",
        default_text_model="chat-compatible",
    )


class ProviderRegistryFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.audio_path = Path(self.directory.name) / "sample.wav"
        self.audio_path.write_bytes(b"RIFFfake-wave")

    def tearDown(self):
        self.directory.cleanup()
