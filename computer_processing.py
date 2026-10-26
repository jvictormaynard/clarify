"""Personal provider processing for the opt-in computer host.

No account, capture, clipboard, Qt, or persisted setting is owned here. Each
request freezes the PC configuration and dictionary before it calls providers.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any, cast

from dictionary_snippets import (
    DictionarySnippetService,
    InMemoryDictionarySnippetsRepository,
)
from provider_http import CancellationToken
from provider_registry import PROVIDER_REGISTRY, ProviderRegistry
from provider_types import ProviderCapability
from repositories import AppConfig
from workflow_config import WorkflowScope
from workflow_provider import WorkflowProviderConfig, WorkflowProviderService
from workflows import RecordingSnapshot


@dataclass(frozen=True)
class _ConfigSnapshot:
    value: AppConfig

    def current(self) -> AppConfig:
        return self.value

    def workflow(self, scope: WorkflowScope):
        return self.value.workflow(scope)


class _OperationRegistry:
    """Add a request token to the existing text workflow calls."""

    def __init__(self, registry: ProviderRegistry, token: CancellationToken):
        self.registry = registry
        self.token = token

    def __getattr__(self, name: str):
        return getattr(self.registry, name)

    def _call(self, action: str, provider, request, connection):
        self.token.raise_if_cancelled()
        result = getattr(self.registry, action)(
            provider, request, connection, self.token
        )
        self.token.raise_if_cancelled()
        return result

    def transcribe(self, provider, request, connection, cancel_token=None):
        return self._call("transcribe", provider, request, connection)

    def rewrite(self, provider, request, connection, cancel_token=None):
        return self._call("rewrite", provider, request, connection)

    def translate(self, provider, request, connection, cancel_token=None):
        return self._call("translate", provider, request, connection)


class ComputerProcessor:
    """Adapt remote input onto PC-owned local/BYOK workflow routes.

    ``config`` is an AppConfig or the current()/workflow() config boundary.
    AppConfig is immutable; current() must return one coherent settings snapshot.
    The registry is reused, including its Local ASR instance serialization.
    """

    def __init__(
        self,
        config: AppConfig | WorkflowProviderConfig,
        dictionary_service: DictionarySnippetService,
        *,
        registry: ProviderRegistry | None = None,
    ):
        self.config = config
        self.dictionary_service = dictionary_service
        self.registry = registry if registry is not None else PROVIDER_REGISTRY

    def _current(self) -> AppConfig:
        value = (
            self.config if isinstance(self.config, AppConfig) else self.config.current()
        )
        if not isinstance(value, AppConfig):
            raise TypeError("Computer processing requires AppConfig")
        return copy.deepcopy(value)

    @property
    def ready(self) -> bool:
        """Configuration readiness only; this does not probe a provider."""
        try:
            current = self._current()
            route = current.workflow(WorkflowScope.TRANSCRIPTION)
            return bool(
                route.enabled
                and route.model_id
                and self.registry.supports(
                    route.provider_id, ProviderCapability.AUDIO_TRANSCRIPTION
                )
                and (
                    route.provider_id == "local_asr"
                    or getattr(current, route.provider_id).api_key
                )
            )
        except (ValueError, TypeError, AttributeError):
            return False

    def _service(self, token: CancellationToken) -> WorkflowProviderService:
        token.raise_if_cancelled()
        config = _ConfigSnapshot(self._current())
        dictionary = DictionarySnippetService(
            InMemoryDictionarySnippetsRepository(self.dictionary_service.state),
            max_expansion_chars=self.dictionary_service.max_expansion_chars,
        )
        return WorkflowProviderService(
            config,
            dictionary,
            registry=cast(ProviderRegistry, _OperationRegistry(self.registry, token)),
            account=None,
        )

    def process_text(
        self, action: str, text: str, language: str, cancel_token: CancellationToken
    ) -> dict[str, Any]:
        service = self._service(cancel_token)
        if action == "rewrite":
            result = service.rewrite(text)
        elif action == "translate":
            result = service.translate(text, language)
        else:
            raise ValueError("Unsupported computer action")
        cancel_token.raise_if_cancelled()
        return {
            "transcript": text,
            "text": result.text,
            "rewritten": result.text != text,
            "successful": True,
        }

    def process_dictation(
        self, audio_wav: bytes, language: str, cancel_token: CancellationToken
    ) -> dict[str, Any]:
        service = self._service(cancel_token)
        # The adapter owns this file until the synchronous provider call ends.
        # The bytes snapshot also supports adapters that do not open the file.
        with tempfile.TemporaryDirectory(prefix="clarify-computer-") as directory:
            path = Path(directory) / "dictation.wav"
            path.write_bytes(audio_wav)
            result = service.transcribe(
                RecordingSnapshot(path, audio_wav, cancel_token), "prompt", language
            )
            cancel_token.raise_if_cancelled()
            transcript = result.raw_text if result.raw_text is not None else result.text
            return {
                "transcript": transcript,
                "text": result.text,
                "rewritten": transcript != result.text,
                "successful": not result.refinement_failed,
            }
