"""Regressions for optional action policy and nonblocking account catalogs."""

import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from provider_http import CancellationToken
from provider_types import TranscriptionResult
from tests import test_text_actions as fixtures


class CatalogResponsivenessTests(unittest.TestCase):
    setUp = fixtures.HostedServiceTests.setUp

    def test_projection_and_account_state_remain_free_during_get(self):
        entered, release, completed = (threading.Event() for _ in range(3))
        original = self.account.request

        def request(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3), "GET was not released")
            return original(*args, **kwargs)

        self.account.request = request
        worker = threading.Thread(
            target=lambda: self.service.refresh(apply_bindings=False)
        )
        worker.start()
        try:
            self.assertTrue(entered.wait(1))

            def probe():
                self.service.projection()
                self.account.snapshot()
                completed.set()

            reader = threading.Thread(target=probe)
            reader.start()
            self.assertTrue(completed.wait(0.5), "snapshot waited for remote GET")
        finally:
            release.set()
            worker.join(3)
            reader.join(3)

    def test_manual_cache_miss_does_not_fetch_on_caller(self):
        self.service._libraries.clear()
        self.account.text_actions_path(self.account.history_identity()).unlink()
        calls = len(self.server.calls)
        with self.assertRaises(Exception):
            self.service.resolve("rewrite")
        self.assertEqual(len(self.server.calls), calls)


class DictationPolicyRepairTests(unittest.TestCase):
    setUp = fixtures.LocalServiceTests.setUp
    save = fixtures.LocalServiceTests.save
    custom = fixtures.LocalServiceTests.custom
    provider = fixtures.LocalServiceTests.provider
    workflow = fixtures.WorkflowActionTests.workflow

    def configure_optional_action(
        self, *, level="preserve", local=False, invalid=False
    ):
        from workflow_config import WorkflowRoute

        self.save(self.custom())
        state = self.service.projection()
        self.service.set_after(
            "summary", "auto", state["textActionContext"], state["textActionsRevision"]
        )
        config = self.repo.load()
        from local_asr_catalog import MODELS

        routes = config.workflows.with_route(
            "transcription",
            WorkflowRoute(
                "local_asr" if local else "openai",
                next(iter(MODELS)) if local else "whisper-1",
            ),
        )
        routes = routes.with_route(
            "refinement",
            replace(
                config.workflow("refinement"),
                enabled=False,
                model_id="" if invalid else config.workflow("refinement").model_id,
            ),
        )
        self.repo.apply(
            replace(
                config,
                workflows=routes,
                dictation_cleanup_level=level,
                local_asr_cloud_refinement=False,
            )
        )
        provider, registry = self.provider()
        provider.dictionary_service.state = SimpleNamespace(snippets=())
        provider.dictionary_service.apply_context.side_effect = lambda r: r
        provider.dictionary_service.expand_spoken_trigger.return_value = None
        provider.dictionary_service.expand.side_effect = lambda s: s + " expanded"
        registry.transcribe.return_value = TranscriptionResult(
            "Original", "openai", "whisper-1"
        )
        return provider, registry

    def test_no_ai_policy_does_not_resolve_disabled_or_invalid_optional_profile(self):
        from workflows import RecordingSnapshot, StartDictation, WorkflowPhase

        for level, local, invalid in [
            ("preserve", False, False),
            ("light", False, True),
            ("clarity", True, False),
        ]:
            with self.subTest(level=level, local=local):
                provider, registry = self.configure_optional_action(
                    level=level, local=local, invalid=invalid
                )
                workflow = self.workflow(provider)
                workflow.dispatch(StartDictation(None, "prompt", "en"))
                self.assertEqual(workflow.state.phase, WorkflowPhase.RECORDING)
                snapshot = provider.snapshot_dictation()
                self.assertIsNone(snapshot.action)
                with patch("provider_registry.PROVIDER_HTTP.logger"):
                    result = provider.transcribe(
                        RecordingSnapshot(
                            Path("unused.wav"), b"fake", CancellationToken()
                        ),
                        "prompt",
                        "en",
                        dictation_snapshot=snapshot,
                    )
                self.assertEqual(result.text, "Original expanded")
                registry.rewrite.assert_not_called()
                with self.assertRaises(Exception):
                    provider.snapshot_text_action("summary")

    def test_unavailable_optional_action_recovers_expanded_text_and_standalone(self):
        from workflows import RecordingSnapshot

        provider, registry = self.configure_optional_action(level="clarity")
        config = self.repo.load()
        routes = config.workflows.with_route(
            "refinement", replace(config.workflow("refinement"), enabled=True)
        )
        routes = routes.with_route(
            "rewrite", replace(config.workflow("rewrite"), enabled=False)
        )
        self.repo.apply(replace(config, workflows=routes))
        self.save({**self.custom(), "processingProfileId": "legacy-rewrite"})
        audio = RecordingSnapshot(Path("unused.wav"), b"fake", CancellationToken())
        with patch("provider_registry.PROVIDER_HTTP.logger"):
            result = provider.transcribe(audio, "prompt", "en")
        self.assertEqual(result.text, "Original expanded")
        self.assertTrue(result.refinement_failed)
        provider.dictionary_service.expand_spoken_trigger.return_value = "Saved text"
        with patch("provider_registry.PROVIDER_HTTP.logger"):
            result = provider.transcribe(audio, "prompt", "en")
        self.assertEqual(result.text, "Saved text")
        self.assertFalse(result.refinement_failed)
        registry.rewrite.assert_not_called()

    def test_disabled_review_context_cannot_be_bypassed_by_another_action_profile(self):
        from workflows import RecordingSnapshot

        for local in (False, True):
            with self.subTest(local=local):
                provider, registry = self.configure_optional_action(
                    level="clarity", local=local
                )
                config = self.repo.load()
                scope = "local_asr_refinement" if local else "refinement"
                self.repo.apply(
                    replace(
                        config,
                        local_asr_cloud_refinement=True,
                        workflows=config.workflows.with_route(
                            scope, replace(config.workflow(scope), enabled=False)
                        ),
                    )
                )
                self.save({**self.custom(), "processingProfileId": "legacy-rewrite"})
                state = self.service.projection()
                self.service.set_after(
                    "summary",
                    "auto",
                    state["textActionContext"],
                    state["textActionsRevision"],
                )
                self.assertTrue(provider.snapshot_text_action("summary").route.enabled)
                snapshot = provider.snapshot_dictation()
                self.assertIsNone(snapshot.action)
                with patch("provider_registry.PROVIDER_HTTP.logger"):
                    result = provider.transcribe(
                        RecordingSnapshot(
                            Path("unused.wav"), b"fake", CancellationToken()
                        ),
                        "prompt",
                        "en",
                        dictation_snapshot=snapshot,
                    )
                self.assertEqual(result.text, "Original expanded")
                registry.rewrite.assert_not_called()

    def test_no_ai_gate_precedes_invalid_optional_profile_and_credentials(self):
        from workflow_config import WorkflowRoute
        from text_actions import TextActionProfile

        provider, registry = self.configure_optional_action(level="preserve")
        config = self.repo.load()
        invalid = replace(
            config,
            text_actions=replace(
                config.text_actions,
                profiles=tuple(
                    TextActionProfile(
                        "default", WorkflowRoute("unknown-provider", "unknown-model")
                    )
                    if p.id == "default"
                    else p
                    for p in config.text_actions.profiles
                ),
            ),
        )
        with patch.object(self.repo, "load", return_value=invalid):
            with patch.object(
                provider,
                "_connection",
                side_effect=AssertionError("optional credential lookup"),
            ):
                snapshot = provider.snapshot_dictation()
        self.assertIsNone(snapshot.action)
        registry.rewrite.assert_not_called()


class HostedOptionalActionRepairTests(unittest.TestCase):
    setUp = fixtures.HostedServiceTests.setUp

    def test_missing_cache_recovers_without_default_hosted_ai_or_sync_get(self):
        from workflow_provider import WorkflowProviderService
        from workflows import RecordingSnapshot

        state = self.service.projection()
        self.service.set_after(
            "rewrite", "auto", state["textActionContext"], state["textActionsRevision"]
        )
        config = self.repo.load()
        self.repo.apply(replace(config, dictation_cleanup_level="clarity"))
        self.service._libraries.clear()
        self.account.text_actions_path(self.account.history_identity()).unlink()
        calls = len(self.server.calls)
        provider = WorkflowProviderService(
            SimpleNamespace(current=self.repo.load),
            Mock(),
            account=self.account,
            text_actions=self.service,
        )
        snapshot = provider.snapshot_dictation()
        self.assertTrue(snapshot.action_error)
        self.assertEqual(len(self.server.calls), calls)
        with patch.object(
            self.account,
            "transcribe",
            return_value=TranscriptionResult("Expanded source", "clarify", "hosted"),
        ) as transcribe:
            result = provider.transcribe(
                RecordingSnapshot(Path("unused.wav"), b"fake", CancellationToken()),
                "prompt",
                "en",
                dictation_snapshot=snapshot,
            )
        self.assertEqual(transcribe.call_args.kwargs["cleanup_level"], "preserve")
        self.assertEqual(result.text, "Expanded source")
        self.account._state.pop("user_id")
        with self.assertRaises(Exception):
            provider.snapshot_dictation()
