"""Personal provider processing for the opt-in computer host.

No account, capture, clipboard, Qt, or persisted setting is owned here. Each
request freezes the PC configuration and dictionary before it calls providers.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from pathlib import Path
import tempfile
from typing import Any, cast
import unicodedata

from dictionary_snippets import (
    DictionarySnippetService,
    InMemoryDictionarySnippetsRepository,
)
from provider_http import CancellationToken
from provider_registry import PROVIDER_REGISTRY, ProviderRegistry
from provider_types import ProviderError
from repositories import AppConfig
from shared.output_preferences import output_language as parse_output_language
from shared.writing_style_policy import (
    WritingStyle,
    writing_style as parse_writing_style,
    style_outcome,
)
from text_action_service import TextActionService
from text_actions import (
    TextActionInputPolicy,
    TEXT_LANGUAGES,
    MAX_REVISION,
    TextActionSnapshot,
    identity,
    settings_for,
    validate_input,
)
from workflow_config import WorkflowScope, validate_workflow_route
from workflow_provider import WorkflowProviderConfig, WorkflowProviderService
from workflows import RecordingSnapshot


_ACTION_SCOPES = {
    "dictate": WorkflowScope.TRANSCRIPTION,
    "rewrite": WorkflowScope.REWRITE,
    "translate": WorkflowScope.TRANSLATION,
}
_LEGACY_ACTIONS = {"rewrite": "rewrite", "translate": "translation"}


class ComputerActionChanged(RuntimeError):
    """The requested saved definition is missing or has another revision."""


class ComputerActionNotReady(RuntimeError):
    """The personal action or its processing profile is unavailable."""


@dataclass(frozen=True)
class _ConfigSnapshot:
    value: AppConfig

    def current(self) -> AppConfig:
        return self.value

    def load(self) -> AppConfig:
        return self.value

    def workflow(self, scope: WorkflowScope):
        return self.value.workflow(scope)


@dataclass(frozen=True)
class PreparedTextAction:
    snapshot: TextActionSnapshot
    dictionary: DictionarySnippetService
    text: str
    language: str
    writing_style: WritingStyle | None = None


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
    output_preferences_supported = True
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
        """Legacy dictation readiness; no provider or installation probe."""
        try:
            return self._ready_for(self._current(), "dictate")
        except (ValueError, TypeError, AttributeError):
            return False

    @property
    def action_readiness(self) -> dict[str, bool]:
        """Check each personal workflow against one configuration snapshot."""
        try:
            current = self._current()
        except (ValueError, TypeError, AttributeError):
            return dict.fromkeys(_ACTION_SCOPES, False)
        return {action: self._ready_for(current, action) for action in _ACTION_SCOPES}

    @property
    def text_actions(self) -> list[dict[str, Any]]:
        """Export only public descriptors from one personal catalog snapshot."""
        try:
            current = self._current()
            actions = settings_for(current).actions
        except (ValueError, TypeError, AttributeError):
            return []
        return [
            {
                "id": action.id,
                "revision": action.revision,
                "name": "".join(
                    char
                    for char in action.name
                    if not unicodedata.category(char).startswith("C")
                ).strip()[:80]
                or action.id,
                "kind": action.kind,
                "enabled": action.enabled,
                "ready": self._action_ready(current, action.id),
            }
            for action in actions
        ]

    def _action_ready(self, current: AppConfig, action_id: str) -> bool:
        try:
            settings = settings_for(current)
            action = settings.action(action_id)
            if action is None or not action.enabled:
                return False
            profile = settings.profile(action.processing_profile_id)
            route = (
                current.workflow(profile.source_scope)
                if profile.source_scope
                else profile.route
            )
            # Domain route validation can fill in a default model. Discovery
            # must report the owner's unconfigured profile as unavailable.
            if not route.enabled or not route.model_id.strip():
                return False
            snapshot = TextActionService(_ConfigSnapshot(current)).resolve(action_id)
            return self._route_ready(current, snapshot.route, WorkflowScope.REWRITE)
        except (ValueError, TypeError, AttributeError, RuntimeError, ProviderError):
            return False

    def _ready_for(self, current: AppConfig, action: str) -> bool:
        if action in _LEGACY_ACTIONS:
            return self._action_ready(current, _LEGACY_ACTIONS[action])
        scope = _ACTION_SCOPES.get(action)
        if scope is None:
            return False
        return self._route_ready(current, current.workflow(scope), scope)

    def _route_ready(self, current: AppConfig, route, scope: WorkflowScope) -> bool:
        try:
            if not route.enabled or not route.model_id.strip():
                return False
            validate_workflow_route(route, scope, registry=self.registry)
            if route.provider_id == "local_asr":
                return True
            metadata = self.registry.describe(route.provider_id)
            provider = getattr(current, route.provider_id)
            if metadata.authentication == "oauth":
                # Read only the bound profile's local session state. credential()
                # can refresh tokens and belongs to actual provider processing.
                snapshot = self.registry.adapter(route.provider_id).session.snapshot()
                return bool(
                    snapshot.get("connected") is True
                    and snapshot.get("planEnabled") is True
                    and route.account_id
                    and route.account_id == snapshot.get("accountId")
                    and (provider.base_url or metadata.default_base_url).rstrip("/")
                    == metadata.default_base_url
                )
            return metadata.authentication == "api_key" and bool(
                provider.api_key.strip()
            )
        except (ValueError, TypeError, AttributeError, RuntimeError, ProviderError):
            return False

    def _service(
        self, token: CancellationToken, action: str
    ) -> WorkflowProviderService:
        token.raise_if_cancelled()
        config = _ConfigSnapshot(self._current())
        if not self._ready_for(config.value, action):
            raise ComputerActionNotReady("Computer action is not configured")
        token.raise_if_cancelled()
        return self._workflow_service(config.value, self._dictionary(), token)

    def _dictionary(self) -> DictionarySnippetService:
        return DictionarySnippetService(
            InMemoryDictionarySnippetsRepository(
                copy.deepcopy(self.dictionary_service.state)
            ),
            max_expansion_chars=self.dictionary_service.max_expansion_chars,
        )

    def _workflow_service(
        self,
        current: AppConfig,
        dictionary: DictionarySnippetService,
        token: CancellationToken | None = None,
    ) -> WorkflowProviderService:
        config = _ConfigSnapshot(current)
        return WorkflowProviderService(
            config,
            dictionary,
            registry=cast(ProviderRegistry, _OperationRegistry(self.registry, token))
            if token is not None
            else self.registry,
            account=None,
            text_actions=TextActionService(config, account=None),
            text_action_input_policy=TextActionInputPolicy.PAIRED_COMPUTER,
        )

    def prepare_text_action(
        self,
        action_id: str,
        action_revision: int,
        text: str,
        language: str,
        *,
        writing_style: str | None = None,
    ) -> PreparedTextAction:
        """Resolve once before admission, without provider calls or token refresh."""
        identity(action_id)
        style = parse_writing_style(writing_style)
        if type(action_revision) is not int or not 1 <= action_revision <= MAX_REVISION:
            raise ValueError("Invalid text action revision")
        current = self._current()
        action = settings_for(current).action(action_id)
        if action is None or action.revision != action_revision:
            raise ComputerActionChanged("Saved action changed")
        validate_input(text, language, policy=TextActionInputPolicy.PAIRED_COMPUTER)
        if language not in TEXT_LANGUAGES:
            raise ValueError("Invalid saved computer action language")
        if action.kind == "translation" and language == "auto":
            raise ValueError("Select a translation language")
        if not self._action_ready(current, action_id):
            raise ComputerActionNotReady("Computer action is not configured")
        dictionary = self._dictionary()
        service = self._workflow_service(current, dictionary)
        return PreparedTextAction(
            service.snapshot_text_action(action_id), dictionary, text, language, style
        )

    def process_text_action(
        self, prepared: PreparedTextAction, cancel_token: CancellationToken
    ) -> dict[str, Any]:
        cancel_token.raise_if_cancelled()
        service = self._workflow_service(
            prepared.snapshot.config, prepared.dictionary, cancel_token
        )
        result = service.transform_text_action(
            prepared.snapshot,
            prepared.text,
            prepared.language,
            cancel=cancel_token,
            writing_style=prepared.writing_style,
        )
        cancel_token.raise_if_cancelled()
        return {
            "transcript": prepared.text,
            "text": result.text,
            "rewritten": result.text != prepared.text,
            "successful": True,
            **style_outcome(prepared.writing_style, refined=True),
        }

    def process_text(
        self,
        action: str,
        text: str,
        language: str,
        cancel_token: CancellationToken,
        *,
        writing_style: str | None = None,
    ) -> dict[str, Any]:
        if action not in ("rewrite", "translate"):
            raise ValueError("Unsupported computer action")
        style = parse_writing_style(writing_style)
        service = self._service(cancel_token, action)
        result = service.transform_text_action(
            service.snapshot_text_action(_LEGACY_ACTIONS[action]),
            text,
            language if action == "translate" else "auto",
            cancel=cancel_token,
            writing_style=style,
        )
        cancel_token.raise_if_cancelled()
        return {
            "transcript": text,
            "text": result.text,
            "rewritten": result.text != text,
            "successful": True,
            **style_outcome(style, refined=True),
        }

    def process_dictation(
        self,
        audio_wav: bytes,
        language: str,
        cancel_token: CancellationToken,
        *,
        writing_style: str | None = None,
        output_language: str | None = None,
    ) -> dict[str, Any]:
        style = parse_writing_style(writing_style)
        target = parse_output_language(output_language)
        service = self._service(cancel_token, "dictate")
        snapshot = service.snapshot_dictation()
        if snapshot.action is not None and not self._action_ready(
            snapshot.config, snapshot.action.action.id
        ):
            snapshot = replace(snapshot, action=None, action_error="not_ready")
        # The adapter owns this file until the synchronous provider call ends.
        # The bytes snapshot also supports adapters that do not open the file.
        with tempfile.TemporaryDirectory(prefix="clarify-computer-") as directory:
            path = Path(directory) / "dictation.wav"
            path.write_bytes(audio_wav)
            result = service.transcribe(
                RecordingSnapshot(path, audio_wav, cancel_token),
                "prompt",
                language,
                dictation_snapshot=snapshot,
                writing_style=style,
                output_language=target,
            )
            cancel_token.raise_if_cancelled()
            transcript = result.raw_text if result.raw_text is not None else result.text
            provenance = {
                prefix + suffix: getattr(result, prefix + suffix)
                for prefix, requested in (
                    ("writing_style", style),
                    ("output_language", target),
                )
                if requested is not None
                for suffix in ("_requested", "_applied", "_status")
            }
            applied = all(
                provenance[prefix + "_status"] in ("applied", "unchanged", "standalone")
                for prefix, requested in (
                    ("writing_style", style),
                    ("output_language", target),
                )
                if requested is not None
            )
            return {
                "transcript": transcript,
                "text": result.text,
                "rewritten": transcript != result.text,
                "successful": not result.refinement_failed and applied,
                **provenance,
            }
