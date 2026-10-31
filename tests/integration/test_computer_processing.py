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
from text_actions import TextAction, TextActionProfile, TextActionSettings, settings_for
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
        for name in (
            "describe",
            "supports",
            "connection_for_route",
            "canonical_audio_model",
        ):
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

    def test_missing_action_key_is_rejected_before_provider_call(self):
        self.assertTrue(self.processor.action_readiness["rewrite"])
        self.current = replace(self.current, groq=ProviderConfig())
        with self.assertRaises(RuntimeError):
            self.processor.process_text("rewrite", "Source", "en", self.token)
        self.registry.rewrite.assert_not_called()

    def test_output_preferences_keep_recognition_auto_and_use_one_editor(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows, refinement=WorkflowRoute("groq", "cleanup")
            ),
        )
        result = self.processor.process_dictation(
            wav_bytes(),
            "auto",
            self.token,
            output_language="en",
            writing_style="formal",
        )
        self.assertEqual(self.registry.transcribe.call_args.args[1].language, "")
        request = self.registry.rewrite.call_args.args[1]
        self.assertIn("English", request.instruction)
        self.assertIn("Formal", request.instruction)
        self.assertEqual(result["transcript"], "Recognized words.")
        self.assertEqual(result["output_language_applied"], "en")
        self.assertEqual(result["writing_style_applied"], "formal")
        self.assertTrue(result["successful"])
        self.registry.transcribe.assert_called_once()
        self.registry.rewrite.assert_called_once()
        self.registry.translate.assert_not_called()

    def test_output_preferences_do_not_enable_disabled_refinement(self):
        result = self.processor.process_dictation(
            wav_bytes(),
            "auto",
            self.token,
            output_language="en",
            writing_style="casual",
        )
        self.assertEqual(result["text"], "Recognized words.")
        self.assertFalse(result["successful"])
        self.assertIsNone(result["output_language_applied"])
        self.assertEqual(result["output_language_status"], "refinement_not_allowed")
        self.assertEqual(result["writing_style_status"], "refinement_not_allowed")
        self.registry.rewrite.assert_not_called()

    def test_saved_action_freezes_requested_style(self):
        self.saved_actions()
        prepared = self.processor.prepare_text_action(
            "summary", 3, "Source", "auto", writing_style="very_casual"
        )
        result = self.processor.process_text_action(prepared, self.token)
        self.assertIn(
            "Very casual", self.registry.rewrite.call_args.args[1].instruction
        )
        self.assertEqual(result["writing_style_applied"], "very_casual")

    def test_standalone_output_preferences_keep_the_exact_snippet(self):
        dictionary = DictionarySnippetService(
            InMemoryDictionarySnippetsRepository(
                DictionarySnippets(snippets=(Snippet("assinatura", "EXACT 42"),))
            )
        )
        processor = ComputerProcessor(self.config, dictionary, registry=self.registry)
        self.registry.transcribe.return_value = TranscriptionResult(
            "assinatura", "openai", "whisper-1"
        )
        result = processor.process_dictation(
            wav_bytes(),
            "auto",
            self.token,
            output_language="en",
            writing_style="formal",
        )
        self.assertEqual(result["text"], "EXACT 42")
        self.assertTrue(result["successful"])
        for prefix in ("output_language", "writing_style"):
            self.assertEqual(result[prefix + "_status"], "standalone")
            self.assertIsNone(result[prefix + "_applied"])
        self.registry.rewrite.assert_not_called()

    def test_output_preferences_recover_the_source_after_editor_failure(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows, refinement=WorkflowRoute("groq", "cleanup")
            ),
        )
        self.registry.rewrite.side_effect = RuntimeError("private provider detail")
        result = self.processor.process_dictation(
            wav_bytes(),
            "auto",
            self.token,
            output_language="en",
            writing_style="formal",
        )
        self.assertEqual(result["text"], "Recognized words.")
        self.assertFalse(result["successful"])
        self.assertEqual(result["output_language_status"], "refinement_failed")
        self.assertNotIn("private", str(result))

    def test_output_preferences_reject_invalid_values_before_provider_work(self):
        for fields in (
            {"output_language": "en-US"},
            {"output_language": True},
            {"writing_style": "unknown"},
            {"writing_style": {"prompt": "run this"}},
        ):
            with self.assertRaises(ValueError):
                self.processor.process_dictation(
                    wav_bytes(), "auto", self.token, **fields
                )
        self.registry.transcribe.assert_not_called()

    def test_legacy_rewrite_keeps_the_existing_utf8_wire_limit(self):
        source = "é" * 16384
        result = self.processor.process_text("rewrite", source, "en", self.token)
        self.assertEqual(result["transcript"], source)
        self.assertEqual(self.registry.rewrite.call_args.args[1].text, source)
        self.registry.rewrite.reset_mock()
        with self.assertRaises(ValueError):
            self.processor.process_text("rewrite", source + "é", "en", self.token)
        self.registry.rewrite.assert_not_called()

    def test_legacy_translation_keeps_language_tags_and_wire_limit(self):
        source = "é" * 16384
        self.processor.process_text("translate", source, "fr", self.token)
        request = self.registry.translate.call_args.args[1]
        self.assertEqual(request.text, source)
        self.assertEqual(request.target_language, "fr")

    def test_saved_computer_action_uses_the_same_bounded_wire_input(self):
        self.saved_actions()
        source = "é" * 16384
        prepared = self.processor.prepare_text_action("summary", 3, source, "auto")
        self.processor.process_text_action(prepared, self.token)
        self.assertEqual(self.registry.rewrite.call_args.args[1].text, source)

    def saved_actions(self, *, kind="custom", enabled=True, route=None, after=None):
        action = TextAction(
            "summary",
            "Summary\n\u202e",
            "Summarize in two sentences.",
            kind,
            enabled,
            3,
        )
        self.current = replace(
            self.current,
            text_actions=TextActionSettings(
                actions=(action,),
                profiles=(
                    TextActionProfile(
                        "default", route or WorkflowRoute("groq", "saved-model")
                    ),
                ),
                after_dictation=after or {},
            ),
        )
        return action

    def test_discovery_exports_only_bounded_descriptors_without_provider_work(self):
        self.saved_actions()
        self.assertEqual(
            self.processor.text_actions,
            [
                {
                    "id": "summary",
                    "revision": 3,
                    "name": "Summary",
                    "kind": "custom",
                    "enabled": True,
                    "ready": True,
                }
            ],
        )
        self.registry.rewrite.assert_not_called()
        self.registry.translate.assert_not_called()
        self.registry.transcribe.assert_not_called()
        self.registry.validate.assert_not_called()
        self.registry.discover_models.assert_not_called()
        self.registry.adapter.assert_not_called()

    def test_saved_action_oauth_discovery_does_not_refresh_credentials(self):
        self.saved_actions(
            route=WorkflowRoute("chatgpt", "saved-model", account_id="bound-account")
        )
        session = Mock()
        session.snapshot.return_value = {
            "connected": True,
            "planEnabled": True,
            "accountId": "bound-account",
        }
        self.registry.adapter.return_value = PROVIDER_REGISTRY.with_chatgpt_session(
            session
        ).adapter("chatgpt")
        self.assertTrue(self.processor.text_actions[0]["ready"])
        session.snapshot.return_value = {
            "connected": True,
            "planEnabled": True,
            "accountId": "other-account",
        }
        self.assertFalse(self.processor.text_actions[0]["ready"])
        session.credential.assert_not_called()
        self.registry.rewrite.assert_not_called()

    def test_custom_action_uses_saved_prompt_profile_and_frozen_connection(self):
        self.saved_actions()
        prepared = self.processor.prepare_text_action("summary", 3, "Source", "auto")
        self.current = replace(
            self.current,
            groq=ProviderConfig(api_key="changed"),
            text_actions=TextActionSettings(),
        )
        result = self.processor.process_text_action(prepared, self.token)
        self.assertEqual(result["text"], "Edited words.")
        provider, request, connection, token = self.registry.rewrite.call_args.args
        self.assertEqual(
            (provider, request.model, connection.api_key),
            ("groq", "saved-model", "other"),
        )
        self.assertIn("Summarize in two sentences.", request.instruction)
        self.assertNotIn("Rewrite the selected", request.instruction)
        self.assertIs(token, self.token)

    def test_legacy_text_resolves_saved_stable_action_instead_of_workflow_prompt(self):
        settings = settings_for(self.current)
        self.current = replace(
            self.current,
            text_actions=replace(
                settings,
                actions=tuple(
                    replace(a, prompt="Use the saved rewrite instruction.", revision=2)
                    if a.id == "rewrite"
                    else a
                    for a in settings.actions
                ),
            ),
        )
        result = self.processor.process_text("rewrite", "Source", "en", self.token)
        self.assertIn(
            "Use the saved rewrite instruction.",
            self.registry.rewrite.call_args.args[1].instruction,
        )
        self.assertEqual(set(result), {"transcript", "text", "rewritten", "successful"})
        self.current = replace(
            self.current, text_actions=replace(self.current.text_actions, actions=())
        )
        self.assertFalse(self.processor.action_readiness["rewrite"])
        with self.assertRaises(RuntimeError):
            self.processor.process_text("rewrite", "Source", "en", self.token)
        self.assertEqual(self.registry.rewrite.call_count, 1)

    def test_saved_action_readiness_rejects_disabled_missing_key_and_local_asr_profiles(
        self,
    ):
        for enabled, route, key in (
            (False, WorkflowRoute("groq", "model"), "other"),
            (True, WorkflowRoute("groq", "model", enabled=False), "other"),
            (True, WorkflowRoute("groq", ""), "other"),
            (True, WorkflowRoute("groq", "model"), ""),
            (True, WorkflowRoute("local_asr", "ggml-base"), "other"),
        ):
            with self.subTest(enabled=enabled, route=route, key=key):
                self.saved_actions(enabled=enabled, route=route)
                self.current = replace(self.current, groq=ProviderConfig(api_key=key))
                self.assertFalse(self.processor.text_actions[0]["ready"])
                with self.assertRaises(RuntimeError):
                    self.processor.prepare_text_action("summary", 3, "Source", "auto")
        self.registry.rewrite.assert_not_called()
        self.registry.translate.assert_not_called()

    def test_saved_translation_requires_explicit_supported_language(self):
        self.saved_actions(kind="translation")
        for language in ("auto", "", "fr", "pt-BR"):
            with self.subTest(language=language), self.assertRaises(ValueError):
                self.processor.prepare_text_action("summary", 3, "Source", language)
        prepared = self.processor.prepare_text_action("summary", 3, "Source", "pt")
        self.processor.process_text_action(prepared, self.token)
        request = self.registry.translate.call_args.args[1]
        self.assertEqual(request.target_language, "pt")
        self.assertIn("Summarize in two sentences.", request.instruction)
        self.registry.rewrite.assert_not_called()

    def test_saved_action_cancellation_before_and_after_provider(self):
        self.saved_actions()
        prepared = self.processor.prepare_text_action("summary", 3, "Source", "auto")
        self.token.cancel()
        with self.assertRaises(ProviderCancelledError):
            self.processor.process_text_action(prepared, self.token)
        self.registry.rewrite.assert_not_called()
        self.token = CancellationToken()

        def late(*_args):
            self.token.cancel()
            return RewriteResult("Late", "groq", "saved-model")

        self.registry.rewrite.side_effect = late
        with self.assertRaises(ProviderCancelledError):
            self.processor.process_text_action(prepared, self.token)

    def test_dictation_uses_frozen_optional_saved_action_and_automatic_language(self):
        self.saved_actions(
            after={"personal": {"cloud": {"id": "summary", "language": "auto"}}}
        )
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows, refinement=WorkflowRoute("groq", "cleanup")
            ),
        )

        def recognize(*_args):
            self.current = replace(
                self.current,
                text_actions=TextActionSettings(),
                groq=ProviderConfig(api_key="changed"),
            )
            return TranscriptionResult("Recognized words.", "openai", "whisper-1")

        self.registry.transcribe.side_effect = recognize
        result = self.processor.process_dictation(wav_bytes(), "auto", self.token)
        self.assertEqual(self.registry.transcribe.call_args.args[1].language, "")
        self.assertIn(
            "Summarize in two sentences.",
            self.registry.rewrite.call_args.args[1].instruction,
        )
        self.assertEqual(self.registry.rewrite.call_args.args[2].api_key, "other")
        self.assertEqual(result["text"], "Edited words.")

    def test_optional_action_respects_cleanup_review_and_local_asr_gates(self):
        for cleanup, review, local, cloud in (
            ("preserve", True, False, False),
            ("light", True, False, False),
            ("clarity", False, False, False),
            ("clarity", True, True, False),
        ):
            with self.subTest(cleanup=cleanup, review=review, local=local):
                self.saved_actions(
                    after={
                        "personal": {
                            "cloud": {"id": "summary", "language": "auto"},
                            "local_asr": {"id": "summary", "language": "auto"},
                        }
                    }
                )
                self.current = replace(
                    self.current,
                    dictation_cleanup_level=cleanup,
                    local_asr_cloud_refinement=cloud,
                    workflows=replace(
                        self.current.workflows,
                        transcription=WorkflowRoute("local_asr", "ggml-base")
                        if local
                        else WorkflowRoute("openai", "whisper-1"),
                        refinement=WorkflowRoute("groq", "cleanup", enabled=review),
                        local_asr_refinement=WorkflowRoute(
                            "groq", "cleanup", enabled=review
                        ),
                    ),
                )
                result = self.processor.process_dictation(
                    wav_bytes(), "auto", self.token
                )
                self.assertEqual(result["text"], "Recognized words.")
        self.registry.rewrite.assert_not_called()

    def test_optional_action_can_use_explicit_local_asr_review_but_never_edit_standalone_snippet(
        self,
    ):
        self.saved_actions(
            after={"personal": {"local_asr": {"id": "summary", "language": "auto"}}}
        )
        self.current = replace(
            self.current,
            dictation_cleanup_level="clarity",
            local_asr_cloud_refinement=True,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute("local_asr", "ggml-base"),
                local_asr_refinement=WorkflowRoute("groq", "cleanup"),
            ),
        )
        self.assertEqual(
            self.processor.process_dictation(wav_bytes(), "auto", self.token)["text"],
            "Edited words.",
        )
        self.registry.rewrite.assert_called_once()
        self.dictionary.replace(
            DictionarySnippets(snippets=(Snippet("signature", "Exact saved text."),))
        )
        self.registry.transcribe.return_value = TranscriptionResult(
            "signature", "local_asr", "ggml-base"
        )
        result = self.processor.process_dictation(wav_bytes(), "auto", self.token)
        self.assertEqual(result["text"], "Exact saved text.")
        self.assertTrue(result["successful"])
        self.registry.rewrite.assert_called_once()

    def test_dictation_cancellation_before_or_after_provider_never_runs_optional_action(
        self,
    ):
        self.saved_actions(
            after={"personal": {"cloud": {"id": "summary", "language": "auto"}}}
        )
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows, refinement=WorkflowRoute("groq", "cleanup")
            ),
        )
        self.token.cancel()
        with self.assertRaises(ProviderCancelledError):
            self.processor.process_dictation(wav_bytes(), "auto", self.token)
        self.registry.transcribe.assert_not_called()
        self.token = CancellationToken()

        def cancelled(*_args):
            self.token.cancel()
            return TranscriptionResult("Late", "openai", "whisper-1")

        self.registry.transcribe.side_effect = cancelled
        with self.assertRaises(ProviderCancelledError):
            self.processor.process_dictation(wav_bytes(), "auto", self.token)
        self.registry.rewrite.assert_not_called()

    def test_unavailable_optional_action_keeps_transcript_without_default_ai(self):
        for enabled, key in ((False, "other"), (True, "")):
            self.saved_actions(
                enabled=enabled,
                after={"personal": {"cloud": {"id": "summary", "language": "auto"}}},
            )
            self.current = replace(
                self.current,
                groq=ProviderConfig(api_key=key),
                workflows=replace(
                    self.current.workflows, refinement=WorkflowRoute("groq", "cleanup")
                ),
            )
            result = self.processor.process_dictation(wav_bytes(), "auto", self.token)
            self.assertEqual(result["text"], "Recognized words.")
            self.assertFalse(result["successful"])
        self.registry.rewrite.assert_not_called()

    def test_independent_action_readiness_and_admission(self):
        for action, scope, provider_method in (
            ("rewrite", "rewrite", self.registry.rewrite),
            ("translate", "translation", self.registry.translate),
        ):
            with self.subTest(action=action):
                self.current = replace(
                    self.current,
                    openai=ProviderConfig(api_key="fake"),
                    groq=ProviderConfig(api_key="other"),
                    workflows=replace(
                        self.current.workflows,
                        transcription=WorkflowRoute(
                            "openai", "whisper-1", enabled=False
                        ),
                        rewrite=WorkflowRoute(
                            "groq", "editor", enabled=scope == "rewrite"
                        ),
                        translation=WorkflowRoute(
                            "openai", "translator", enabled=scope == "translation"
                        ),
                    ),
                )
                self.assertEqual(
                    self.processor.action_readiness,
                    {
                        "dictate": False,
                        "rewrite": action == "rewrite",
                        "translate": action == "translate",
                    },
                )
                self.assertFalse(self.processor.ready)
                self.processor.process_text(action, "Source", "pt", self.token)
                provider_method.assert_called()
                with self.assertRaises(RuntimeError):
                    self.processor.process_dictation(wav_bytes(), "en", self.token)
                self.registry.transcribe.assert_not_called()

    def test_readiness_rejects_missing_models_keys_and_invalid_routes_without_probes(
        self,
    ):
        for route in (
            WorkflowRoute("groq", "editor", enabled=False),
            WorkflowRoute("groq", ""),
            WorkflowRoute("local_asr", "ggml-base"),
            WorkflowRoute("unknown", "editor"),
            WorkflowRoute(
                "groq", "editor", custom_endpoint="https://user:secret@bad.invalid"
            ),
        ):
            with self.subTest(route=route):
                self.current = replace(
                    self.current,
                    workflows=replace(self.current.workflows, rewrite=route),
                )
                self.assertFalse(self.processor.action_readiness["rewrite"])
                with self.assertRaises(RuntimeError):
                    self.processor.process_text("rewrite", "Source", "en", self.token)
        self.current = replace(self.current, openai=ProviderConfig())
        self.assertFalse(self.processor.action_readiness["dictate"])
        self.assertFalse(self.processor.action_readiness["translate"])
        self.registry.transcribe.assert_not_called()
        self.registry.rewrite.assert_not_called()
        self.registry.translate.assert_not_called()
        self.registry.validate.assert_not_called()
        self.registry.discover_models.assert_not_called()

    def test_oauth_readiness_uses_bound_profile_and_selected_account_without_refresh(
        self,
    ):
        session = Mock()
        adapter = PROVIDER_REGISTRY.with_chatgpt_session(session).adapter("chatgpt")
        self.registry.adapter.return_value = adapter
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute("openai", "whisper-1", enabled=False),
                rewrite=WorkflowRoute(
                    "chatgpt", "personal-model", account_id="profile-account"
                ),
                translation=WorkflowRoute(
                    "chatgpt", "personal-model", account_id="profile-account"
                ),
            ),
        )
        for snapshot, expected in (
            (
                {
                    "connected": True,
                    "planEnabled": True,
                    "accountId": "profile-account",
                },
                True,
            ),
            (
                {
                    "connected": False,
                    "planEnabled": False,
                    "accountId": "profile-account",
                },
                False,
            ),
            (
                {
                    "connected": True,
                    "planEnabled": False,
                    "accountId": "profile-account",
                },
                False,
            ),
            (
                {"connected": True, "planEnabled": True, "accountId": "other-account"},
                False,
            ),
        ):
            session.snapshot.return_value = snapshot
            for action, provider_method in (
                ("rewrite", self.registry.rewrite),
                ("translate", self.registry.translate),
            ):
                self.assertEqual(self.processor.action_readiness[action], expected)
                if expected:
                    self.processor.process_text(action, "Source", "en", self.token)
                    connection = provider_method.call_args.args[2]
                    self.assertEqual(provider_method.call_args.args[0], "chatgpt")
                    self.assertEqual(connection.account_id, "profile-account")
                    self.assertEqual(connection.api_key, "")
                else:
                    with self.assertRaises(RuntimeError):
                        self.processor.process_text(action, "Source", "en", self.token)
        session.credential.assert_not_called()
        self.registry.validate.assert_not_called()
        self.registry.discover_models.assert_not_called()

    def test_local_asr_readiness_does_not_probe_installation(self):
        self.current = replace(
            self.current,
            workflows=replace(
                self.current.workflows,
                transcription=WorkflowRoute("local_asr", "ggml-base"),
            ),
        )
        self.assertTrue(self.processor.ready)
        self.registry.transcribe.assert_not_called()
        self.registry.adapter.assert_not_called()

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
                transcription=WorkflowRoute("local_asr", "ggml-base"),
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
                cwd=Path(__file__).resolve().parents[2],
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])
