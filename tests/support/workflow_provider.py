"""Reusable workflow provider fixtures. This module defines no test cases."""

from pathlib import Path


from types import SimpleNamespace


from unittest.mock import Mock, patch


from provider_http import CancellationToken

from provider_registry import PROVIDER_REGISTRY, ProviderRegistry

from provider_types import (
    RewriteResult,
    TranscriptionResult,
)

from repositories import AppConfig, ProviderConfig

from workflow_config import WorkflowConfig, WorkflowRoute

from workflow_provider import WorkflowProviderService

from workflows import RecordingSnapshot


class WorkflowProviderFixture:
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
