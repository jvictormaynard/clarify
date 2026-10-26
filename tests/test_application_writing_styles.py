"""Style integration contracts use fake providers and temporary profiles."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from repositories import AppConfig, LocalConfigRepository, migrate_config_payload
from secret_store import MemorySecretStore
from writing_styles import ApplicationWritingStyles, WritingStyle
from tests import test_workflow_provider as provider_fixture
from tests import test_workflows as workflow_fixture
from tests import test_clarify_account as account_fixture
from workflows import StartDictation, StopDictation, SelectionTarget, RecordingSnapshot
from clarify_account import AccountError


EDITOR = r"C:\Apps\Editor.exe"


class ApplicationStyleConfigTests(unittest.TestCase):
    def test_v3_reader_can_read_but_cannot_erase_v4_rules(self):
        from unittest.mock import patch
        from repositories import UnsupportedSchemaVersionError

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            repository = LocalConfigRepository(path, secret_store=MemorySecretStore())
            repository.apply(
                replace(
                    repository.load(),
                    application_writing_styles=ApplicationWritingStyles().with_rule(
                        EDITOR, WritingStyle.NATURAL
                    ),
                )
            )
            original = path.read_bytes()
            with patch("repositories.CONFIG_SCHEMA_VERSION", 3):
                repository.load()
                with self.assertRaises(UnsupportedSchemaVersionError):
                    repository.apply({"history_enabled": True})
            self.assertEqual(path.read_bytes(), original)

    def test_v3_migration_preserves_personal_prompts_and_has_no_style_override(self):
        original = {
            "schema_version": 3,
            "dictation_cleanup_level": "clarity",
            "workflows": {"refinement": {"prompt": "Keep my personal wording."}},
        }
        migrated = migrate_config_payload(original)
        self.assertEqual(migrated["schema_version"], 4)
        self.assertEqual(migrate_config_payload(migrated), migrated)
        config = AppConfig.from_mapping(migrated)
        self.assertEqual(
            config.workflow("refinement").prompt, "Keep my personal wording."
        )
        self.assertIsNone(
            config.application_writing_styles.resolve(EDITOR).requested_style
        )

    def test_rules_round_trip_and_partial_saves_keep_prompts_and_other_preferences(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            repository = LocalConfigRepository(path, secret_store=MemorySecretStore())
            config = replace(
                repository.load(),
                application_writing_styles=ApplicationWritingStyles().with_rule(
                    EDITOR, WritingStyle.INFORMAL
                ),
            )
            repository.apply(config)
            repository.apply({"history_enabled": True})
            loaded = repository.load()
            self.assertIs(
                loaded.application_writing_styles.resolve(EDITOR).requested_style,
                WritingStyle.INFORMAL,
            )
            self.assertTrue(loaded.history_enabled)
            self.assertEqual(json.loads(path.read_text())["schema_version"], 4)


class ApplicationStyleProviderTests(unittest.TestCase):
    setUp = provider_fixture.WorkflowProviderTests.setUp
    set_cleanup = provider_fixture.WorkflowProviderTests.set_cleanup

    def test_style_keeps_route_and_connection_from_before_asr(self):
        original = self.current

        def recognize(*args):
            self.current = replace(
                original,
                openai=replace(
                    original.openai,
                    api_key="changed-key",
                    base_url="https://changed.invalid",
                ),
            )
            return provider_fixture.TranscriptionResult(self.raw, "openai", "whisper-1")

        self.registry.transcribe.side_effect = recognize
        self.service.transcribe(self.audio, "prompt", "pt", writing_style="natural")
        connection = self.registry.rewrite.call_args.args[2]
        self.assertEqual(connection.api_key, "test-only")
        self.assertEqual(connection.base_url, "https://base.invalid")

    def test_style_does_not_bypass_invalid_refinement_model(self):
        self.current = replace(
            self.current,
            workflows=self.current.workflows.with_route(
                "refinement", replace(self.current.workflow("refinement"), model_id="")
            ),
        )
        result = self.service.transcribe(
            self.audio, "prompt", "pt", writing_style="natural"
        )
        self.registry.rewrite.assert_not_called()
        self.assertTrue(result.refinement_failed)
        self.assertIsNone(result.writing_style_applied)

    def test_style_uses_existing_refinement_and_preserves_raw_numbers_and_prompt(self):
        self.current = replace(
            self.current,
            workflows=self.current.workflows.with_route(
                "refinement",
                replace(
                    self.current.workflow("refinement"),
                    prompt="Keep all technical identifiers.",
                ),
            ),
        )
        result = self.service.transcribe(
            self.audio, "prompt", "pt", writing_style="informal"
        )
        request = self.registry.rewrite.call_args.args[1]
        self.assertIn("Keep all technical identifiers.", request.instruction)
        self.assertIn("informal", request.instruction.lower())
        self.assertIn("42", request.text)
        self.assertEqual(result.raw_text, self.raw)
        self.assertEqual(result.writing_style_requested, "informal")
        self.assertEqual(result.writing_style_applied, "informal")
        self.assertEqual(result.writing_style_status, "applied")

    def test_preserve_and_light_never_enable_generative_style(self):
        for level in ("preserve", "light"):
            with self.subTest(level=level):
                self.set_cleanup(level)
                result = self.service.transcribe(
                    self.audio, "prompt", "pt", writing_style="organized"
                )
                self.registry.rewrite.assert_not_called()
                self.assertIsNone(result.writing_style_applied)
                self.assertEqual(result.writing_style_status, "refinement_not_allowed")

    def test_disabled_local_refinement_does_not_activate_cloud(self):
        self.current = AppConfig.from_mapping(
            {
                **self.current.to_mapping(),
                "workflows": {
                    **self.current.workflows.to_mapping(),
                    "transcription": {
                        "provider_id": "local_asr",
                        "model_id": "ggml-small",
                    },
                },
                "local_asr_cloud_refinement": False,
            }
        )
        result = self.service.transcribe(
            self.audio, "prompt", "pt", writing_style="natural"
        )
        self.registry.rewrite.assert_not_called()
        self.assertIsNone(result.writing_style_applied)
        self.assertEqual(result.writing_style_status, "refinement_not_allowed")

    def test_refinement_failure_returns_source_and_does_not_claim_style(self):
        self.registry.rewrite.side_effect = RuntimeError("fake failure")
        result = self.service.transcribe(
            self.audio, "prompt", "pt", writing_style="organized"
        )
        self.assertEqual(result.text, self.raw + " expanded")
        self.assertEqual(result.raw_text, self.raw)
        self.assertTrue(result.refinement_failed)
        self.assertIsNone(result.writing_style_applied)
        self.assertEqual(result.writing_style_status, "refinement_failed")

    def test_standalone_snippet_remains_exact_without_style(self):
        self.dictionary.expand_spoken_trigger.return_value = (
            "  Saved 42.\nDo not change.  "
        )
        result = self.service.transcribe(
            self.audio, "prompt", "pt", writing_style="informal"
        )
        self.assertEqual(result.text, "  Saved 42.\nDo not change.  ")
        self.registry.rewrite.assert_not_called()
        self.assertIsNone(result.writing_style_applied)
        self.assertEqual(result.writing_style_status, "standalone")

    def test_expired_managed_account_never_uses_personal_provider(self):
        from unittest.mock import Mock

        self.service.account = Mock(managed=True, signed_in=False, hosted=False)
        self.service.account.transcribe.side_effect = AccountError("Session expired")
        with self.assertRaises(AccountError):
            self.service.transcribe(self.audio, "prompt", "pt", writing_style="natural")
        self.registry.transcribe.assert_not_called()
        self.registry.rewrite.assert_not_called()


class ApplicationStyleWorkflowTests(unittest.TestCase):
    setUp = workflow_fixture.WorkflowServiceTests.setUp
    make_service = workflow_fixture.WorkflowServiceTests.make_service

    def configure_style(self):
        self.rules = ApplicationWritingStyles().with_rule(EDITOR, WritingStyle.INFORMAL)
        self.config.dictation_writing_style = lambda executable: self.rules.resolve(
            executable
        )
        self.styles = []
        original = self.provider.transcribe

        def transcribe(*args, writing_style=None):
            self.styles.append(writing_style)
            return replace(
                original(*args),
                writing_style_requested=writing_style,
                writing_style_applied=writing_style,
                writing_style_status="applied",
            )

        self.provider.transcribe = transcribe

    def test_style_is_fixed_at_start_and_focus_change_only_copies(self):
        self.configure_style()
        self.service.dispatch(
            StartDictation(SelectionTarget(77, EDITOR), "prompt", "pt")
        )
        self.assertEqual(self.service.state.writing_style_requested, "informal")
        self.rules = self.rules.with_rule(EDITOR, WritingStyle.ORGANIZED)
        self.clipboard.window = 88
        self.service.dispatch(StopDictation())
        self.assertEqual(self.styles, ["informal"])
        self.assertEqual(self.service.state.writing_style_applied, "informal")
        self.assertEqual(self.clipboard.auto_pastes, [])
        self.assertEqual(len(self.statistics.dictations), 1)

    def test_cancelled_late_result_cannot_apply_style_or_publish(self):
        self.configure_style()
        self.provider.on_transcribe = self.service.cancel_active
        self.service.dispatch(
            StartDictation(SelectionTarget(77, EDITOR), "prompt", "pt")
        )
        self.service.dispatch(StopDictation())
        self.assertIsNone(self.service.state.writing_style_applied)
        self.assertEqual(self.clipboard.auto_pastes, [])
        self.assertEqual(self.statistics.dictations, [])


class ApplicationStyleAccountTests(unittest.TestCase):
    setUp = account_fixture.AccountTests.setUp
    response = account_fixture.AccountTests.response
    signed_in = account_fixture.AccountTests.signed_in

    def test_managed_sends_only_enum_and_requires_confirmed_style(self):
        self.signed_in()
        self.account._last_sync_attempt = self.account._clock()
        self.request.return_value = self.response(
            {
                "transcript": "Não envie 42.",
                "text": "Não envie 42.",
                "rewritten": True,
                "writing_style_requested": "natural",
                "writing_style_applied": "natural",
                "writing_style_status": "applied",
                "refinement_attempted": True,
                "refinement_failed": False,
            }
        )
        result = self.account.transcribe(
            RecordingSnapshot(Path("unused"), b"fake"),
            "pt",
            self.service,
            writing_style="natural",
        )
        self.assertEqual(result.writing_style_applied, "natural")
        fields = self.request.call_args.kwargs["data"]
        self.assertEqual(set(fields), {"operation_id", "language", "writing_style"})
        self.assertEqual(fields["writing_style"], "natural")
        self.request.return_value = self.response(
            {"transcript": "Source", "text": "Source", "rewritten": True}
        )
        self.request.reset_mock()
        with self.assertRaises(AccountError):
            self.account.transcribe(
                RecordingSnapshot(Path("unused"), b"fake"),
                "pt",
                self.service,
                writing_style="natural",
            )
        self.request.assert_called_once()
