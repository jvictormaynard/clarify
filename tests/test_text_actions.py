"""Text action contracts use temporary profiles and fake provider boundaries."""

import unittest
import threading
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from repositories import AppConfig, LocalConfigRepository, UnsupportedSchemaVersionError
from secret_store import MemorySecretStore
from text_actions import TextAction
from text_action_service import TextActionService
from workflow_config import WorkflowRoute
from hotkey_config import HotkeyConflictError, HotkeyDefinition
from provider_registry import PROVIDER_REGISTRY, ProviderRegistry
from provider_http import CancellationToken, ProviderCancelledError
from provider_types import RewriteResult, TranslationResult, TranscriptionResult
from workflow_provider import WorkflowProviderService
from clarify_account import AccountService, AccountError


class HostedFixture:
    def __init__(self):
        self.revision = 0
        self.actions = [
            TextAction(
                "rewrite", "Account rewrite", "Account instruction.", "rewrite"
            ).definition()
            | {"revision": 1}
        ]
        self.calls = []
        self.accepted = {}
        self.on_put = None

    def library(self):
        return {"revision": self.revision, "actions": [dict(a) for a in self.actions]}

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        status, result = 200, self.library()
        if method == "PUT":
            body = kwargs["json"]
            if self.on_put:
                self.on_put(body)
            if body["expected_revision"] != self.revision:
                status, result = (
                    409,
                    {"code": "text_actions_conflict", **self.library()},
                )
            else:
                old = {a["id"]: a for a in self.actions}
                self.actions = [
                    dict(
                        a,
                        revision=old[a["id"]]["revision"]
                        + (
                            a
                            != {
                                k: v for k, v in old[a["id"]].items() if k != "revision"
                            }
                        )
                        if a["id"] in old
                        else 1,
                    )
                    for a in body["actions"]
                ]
                self.revision += 1
                result = self.library()
        elif method == "POST":
            body = kwargs["json"]
            previous = self.accepted.get(body["operation_id"])
            if previous is not None:
                result = previous
            else:
                action = next(
                    (a for a in self.actions if a["id"] == body["action_id"]), None
                )
                if action is None or action["revision"] != body["action_revision"]:
                    status, result = 409, {"code": "text_action_stale"}
                else:
                    result = {
                        "text": "Hosted result",
                        "action_id": action["id"],
                        "action_name": action["name"],
                        "action_revision": action["revision"],
                        "usage": {},
                    }
                    self.accepted[body["operation_id"]] = result
        return SimpleNamespace(
            status_code=status, content=b"fixture", json=lambda: result
        )


class HostedServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.repo = LocalConfigRepository(
            self.directory / "config.json",
            environment={},
            secret_store=MemorySecretStore(),
        )
        self.server = HostedFixture()
        self.account = AccountService(
            self.directory, secrets=MemorySecretStore(), request=self.server
        )
        self.account._state = {
            "endpoint": "https://account.invalid",
            "user_id": "11111111-1111-4111-8111-111111111111",
            "mode": "hosted",
        }
        self.account.secrets.set("clarify_account", "fixture-token")
        self.applier = Mock()
        self.service = TextActionService(
            self.repo, self.account, apply_bindings=self.applier
        )
        self.service.refresh()

    def save(self, value):
        state = self.service.projection()
        return self.service.save(
            value, state["textActionContext"], state["textActionsRevision"]
        )

    def test_account_catalog_never_uploads_personal_actions_and_logout_restores_them(
        self,
    ):
        self.assertEqual(
            [a["id"] for a in self.service.projection()["textActions"]], ["rewrite"]
        )
        self.assertEqual([call[0] for call in self.server.calls], ["GET"])
        self.assertEqual(
            self.service.projection()["textActionProfiles"][0]["providerId"], "clarify"
        )
        before = self.service.projection()
        self.account._generation += 1
        self.account._state = {}
        self.assertEqual(len(self.service.projection()["textActions"]), 2)
        with self.assertRaises(ValueError):
            self.service.save(
                TextAction("new", "New", "Edit.").to_mapping(),
                before["textActionContext"],
                before["textActionsRevision"],
            )

    def test_local_failure_compensates_with_accepted_revision(self):
        old = self.server.library()
        with patch.object(self.repo, "apply", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                self.save(TextAction("new", "New", "Edit.").to_mapping())
        self.assertEqual(self.server.actions, old["actions"])
        puts = [call[2]["json"] for call in self.server.calls if call[0] == "PUT"]
        self.assertEqual([body["expected_revision"] for body in puts], [0, 1])
        self.assertEqual(self.server.revision, 2)
        self.assertEqual(
            self.service.projection()["textActions"][0]["name"], "Account rewrite"
        )

    def test_conflict_adopts_current_definition_and_removes_disabled_binding(self):
        state = self.service.projection()
        action = {
            **state["textActions"][0],
            "shortcut": {"modifiers": ["ctrl", "alt"], "key": "K"},
        }
        self.service.save(
            action, state["textActionContext"], state["textActionsRevision"]
        )
        self.server.actions[0]["enabled"] = False
        self.server.actions[0]["revision"] += 1
        self.server.revision += 1
        with self.assertRaises(Exception) as failure:
            self.save(TextAction("new", "New", "Edit.").to_mapping())
        self.assertEqual(
            getattr(failure.exception, "code", ""), "text_actions_conflict"
        )
        self.assertFalse(self.service.projection()["textActions"][0]["enabled"])
        self.assertNotIn("text_action:rewrite", self.applier.call_args.args[0].hotkeys)

    def test_failed_compensation_never_overwrites_another_client(self):
        def concurrent_write(body):
            if body["expected_revision"] == 1:
                self.server.revision = 2
                self.server.actions[0]["name"] = "Other client"

        self.server.on_put = concurrent_write
        with patch.object(self.repo, "apply", side_effect=OSError("fixture")):
            with self.assertRaisesRegex(RuntimeError, "restaurar"):
                self.save(TextAction("new", "New", "Edit.").to_mapping())
        self.assertEqual(self.server.actions[0]["name"], "Other client")
        with self.assertRaises(ValueError):
            self.save(TextAction("new", "New", "Edit.").to_mapping())

    def test_snapshot_context_execute_idempotency_and_no_personal_fallback(self):
        registry = Mock(spec=ProviderRegistry)
        provider = WorkflowProviderService(
            SimpleNamespace(current=self.repo.load),
            Mock(),
            registry=registry,
            account=self.account,
            text_actions=self.service,
        )
        snapshot = provider.snapshot_text_action("rewrite")
        self.assertEqual(
            provider.transform_text_action(snapshot, "Source").text, "Hosted result"
        )
        self.server.actions = []
        self.assertEqual(
            provider.transform_text_action(snapshot, "Source").text, "Hosted result"
        )
        post = next(call[2]["json"] for call in self.server.calls if call[0] == "POST")
        self.assertEqual(
            set(post),
            {"operation_id", "action_id", "action_revision", "text", "language"},
        )
        self.account._generation += 1
        with self.assertRaises(RuntimeError):
            provider.transform_text_action(snapshot, "Source")
        registry.rewrite.assert_not_called()

    def test_managed_expired_context_rejects_without_personal_route(self):
        self.account._state.pop("user_id")
        self.account._generation += 1
        with self.assertRaises(AccountError):
            self.service.resolve("rewrite")

    def test_context_changes_during_get_do_not_cache_results(self):
        original = self.account.request

        def change(*args, **kwargs):
            self.account._generation += 1
            return original(*args, **kwargs)

        self.account.request = change
        with self.assertRaises(AccountError):
            self.service.refresh()

    def test_projection_pins_account_while_pairing_catalog_and_context(self):
        started, release, changing, changed = (threading.Event() for _ in range(4))
        before = self.service.context()
        load = self.repo.load
        results, errors = [], []

        def blocked_load():
            started.set()
            if not release.wait(2):
                raise AssertionError("Projection was not released")
            return load()

        def project():
            try:
                results.append(self.service.projection())
            except Exception as error:
                errors.append(error)

        def change_owner():
            changing.set()
            with self.account._lock:
                self.account._state["user_id"] = "22222222-2222-4222-8222-222222222222"
                self.account._generation += 1
            changed.set()

        with patch.object(self.repo, "load", side_effect=blocked_load):
            reader = threading.Thread(target=project)
            reader.start()
            self.assertTrue(started.wait(1))
            changer = threading.Thread(target=change_owner)
            changer.start()
            self.assertTrue(changing.wait(1))
            try:
                self.assertFalse(changed.wait(0.03))
            finally:
                release.set()
                reader.join(2)
                changer.join(2)
        self.assertFalse(errors)
        self.assertFalse(reader.is_alive())
        self.assertFalse(changer.is_alive())
        self.assertEqual(results[0]["textActionContext"], before)
        self.assertEqual(results[0]["textActions"][0]["name"], "Account rewrite")
        self.assertNotEqual(self.service.context(), before)

    def test_hosted_dictation_fields_and_response_identity_are_validated(self):
        from workflows import RecordingSnapshot

        snapshot = self.service.resolve("rewrite")
        self.account._last_sync_attempt = self.account._clock()
        response = {
            "transcript": "Original",
            "text": "Account result",
            "rewritten": True,
            "text_action_id": "rewrite",
            "text_action_name": "Account rewrite",
            "text_action_revision": 1,
        }
        request = Mock(
            return_value=SimpleNamespace(
                status_code=200, content=b"fixture", json=lambda: response
            )
        )
        self.account.request = request
        audio = RecordingSnapshot(
            Path("fixture-not-read.wav"), b"fake-audio", CancellationToken()
        )
        result = self.account.transcribe(audio, "en", Mock(), text_action=snapshot)
        self.assertEqual(result.raw_text, "Original")
        self.assertEqual(result.text_action_name, "Account rewrite")
        body = request.call_args.kwargs["data"]
        self.assertEqual(
            set(body),
            {"operation_id", "language", "text_action_id", "text_action_revision"},
        )
        self.assertEqual(body["text_action_revision"], "1")
        response["text_action_revision"] = 2
        with self.assertRaises(AccountError):
            self.account.transcribe(audio, "en", Mock(), text_action=snapshot)

    def test_library_bounds_and_unknown_fields_do_not_reach_http(self):
        count = len(self.server.calls)
        for value in (
            TextAction("new", "New", "Edit.").to_mapping() | {"api_key": "fixture"},
            {**TextAction("new", "New", "Edit.").to_mapping(), "prompt": "é" * 4097},
        ):
            with self.assertRaises(ValueError):
                self.save(value)
        self.assertEqual(len(self.server.calls), count)


class MigrationTests(unittest.TestCase):
    def test_equal_routes_keep_independence_and_chatgpt_binding(self):
        route = {
            "provider_id": "chatgpt",
            "model_id": "plan-test",
            "account_id": "registration-a",
            "prompt": "Keep requirements.",
        }
        config = AppConfig.from_mapping(
            {
                "schema_version": 4,
                "workflows": {
                    "rewrite": {**route, "independent": True},
                    "translation": {**route, "independent": False},
                },
            }
        )
        profiles = config.text_actions
        self.assertTrue(profiles.profile("legacy-rewrite").route.independent)
        self.assertFalse(profiles.profile("legacy-translation").route.independent)
        self.assertEqual(
            profiles.profile("legacy-rewrite").route.account_id, "registration-a"
        )
        self.assertEqual(
            profiles.profile("legacy-translation").route.account_id, "registration-a"
        )

    def test_effective_legacy_routes_and_shortcuts_survive(self):
        config = AppConfig.from_mapping(
            {
                "schema_version": 4,
                "workflows": {
                    "rewrite": {
                        "provider_id": "groq",
                        "model_id": "llama-3.3-70b-versatile",
                        "prompt": "Keep numbers.",
                        "enabled": False,
                        "independent": True,
                        "custom_endpoint": "https://proxy.invalid/v1",
                    },
                    "translation": {
                        "provider_id": "openai",
                        "model_id": "gpt-4o-mini",
                        "prompt": "Translate lists.",
                    },
                },
                "hotkeys": {"bindings": {"rewrite_hotkey": "Ctrl+Alt+K"}},
            }
        )
        actions = config.text_actions
        rewrite = actions.action("rewrite")
        self.assertEqual(rewrite.prompt, "Keep numbers.")
        self.assertFalse(rewrite.enabled)
        self.assertEqual(rewrite.shortcut.display, "Ctrl+Alt+K")
        self.assertEqual(
            actions.profile(rewrite.processing_profile_id).route,
            config.workflow("rewrite"),
        )
        self.assertEqual(
            AppConfig.from_mapping(config.to_mapping()).text_actions, actions
        )

    def test_empty_catalog_is_not_reseeded(self):
        config = AppConfig.from_mapping({})
        config = replace(config, text_actions=replace(config.text_actions, actions=()))
        self.assertEqual(
            AppConfig.from_mapping(config.to_mapping()).text_actions.actions, ()
        )

    def test_blank_legacy_prompt_uses_its_effective_builtin_policy(self):
        config = AppConfig.from_mapping(
            {"schema_version": 4, "workflows": {"translation": {"prompt": ""}}}
        )
        self.assertTrue(config.text_actions.action("translation").prompt.strip())

    def test_future_action_representation_remains_readable_and_read_only(self):
        import json

        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            value = {
                "schema_version": 99,
                "text_actions": {"actions": [{"unknown": True}]},
            }
            path.write_text(json.dumps(value), encoding="utf-8")
            repo = LocalConfigRepository(
                path, environment={}, secret_store=MemorySecretStore()
            )
            config = repo.load()
            self.assertIsNotNone(config.text_actions.action("rewrite"))
            with self.assertRaises(UnsupportedSchemaVersionError):
                repo.apply(config)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), value)


class LocalServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.repo = LocalConfigRepository(
            Path(self.directory) / "config.json",
            environment={},
            secret_store=MemorySecretStore(),
        )
        self.applier = Mock()
        self.service = TextActionService(self.repo, apply_bindings=self.applier)

    def save(self, action):
        state = self.service.projection()
        return self.service.save(
            action, state["textActionContext"], state["textActionsRevision"]
        )

    def custom(self, **changes):
        return TextAction(
            "summary", "Summary", "Summarize this text.", **changes
        ).to_mapping()

    def test_save_duplicate_disable_delete_and_stale_guard(self):
        first = self.service.projection()
        state = self.save(
            self.custom(shortcut=HotkeyDefinition.from_mapping("Ctrl+Alt+S"))
        )
        self.assertEqual(len(state["textActions"]), 3)
        self.assertEqual(
            self.repo.load().text_actions.action("summary").processing_profile_id,
            "default",
        )
        with self.assertRaises(ValueError):
            self.service.save(
                self.custom(), first["textActionContext"], first["textActionsRevision"]
            )
        state = self.service.duplicate(
            "summary", state["textActionContext"], state["textActionsRevision"]
        )
        copy = next(
            a
            for a in state["textActions"]
            if a["id"] not in {"rewrite", "translation", "summary"}
        )
        self.assertIsNone(copy["shortcut"])
        self.save(
            self.custom(
                enabled=False, shortcut=HotkeyDefinition.from_mapping("Ctrl+Alt+S")
            )
        )
        self.assertNotIn("text_action:summary", self.service.bindings().hotkeys)
        state = self.service.projection()
        self.service.delete(
            "rewrite", state["textActionContext"], state["textActionsRevision"]
        )
        self.assertNotIn("rewrite_hotkey", self.service.bindings().hotkeys)
        self.assertNotIn("text_action:rewrite", self.service.bindings().hotkeys)

    def test_conflict_validation_has_no_effects(self):
        with self.assertRaises(HotkeyConflictError):
            self.save(self.custom(shortcut=HotkeyDefinition.from_mapping("Alt+L")))
        self.applier.assert_not_called()
        self.assertFalse(self.repo.path.exists())

    def test_definition_edit_retains_omitted_device_preferences(self):
        self.save(
            self.custom(
                processing_profile_id="legacy-rewrite",
                shortcut=HotkeyDefinition.from_mapping("Ctrl+Alt+S"),
            )
        )
        value = self.custom()
        value.pop("processingProfileId")
        value.pop("shortcut")
        value["name"] = "Short summary"
        self.save(value)
        saved = self.repo.load().text_actions.action("summary")
        self.assertEqual(saved.processing_profile_id, "legacy-rewrite")
        self.assertEqual(saved.shortcut.display, "Ctrl+Alt+S")

    def test_persist_failure_restores_bindings(self):
        old = self.service.bindings()
        with patch.object(
            self.repo, "apply", side_effect=OSError("fixture write failure")
        ):
            with self.assertRaises(OSError):
                self.save(
                    self.custom(shortcut=HotkeyDefinition.from_mapping("Ctrl+Alt+S"))
                )
        self.assertEqual(self.applier.call_args.args[0], old)
        self.assertIsNone(self.repo.load().text_actions.action("summary"))

    def test_native_failure_keeps_config_and_restores_previous_set(self):
        self.applier.side_effect = [RuntimeError("fixture registration failure"), None]
        with self.assertRaises(RuntimeError):
            self.save(self.custom())
        self.assertFalse(self.repo.path.exists())
        self.assertEqual(self.applier.call_count, 2)

    def test_dynamic_native_ids_and_strict_registration_rollback(self):
        from tests.test_hotkey_configuration import _User32
        from windows_hotkeys import (
            register_global_hotkeys,
            action_for_hotkey_id,
            HotkeyRegistrationError,
        )

        self.save(self.custom(shortcut=HotkeyDefinition.from_mapping("Ctrl+Alt+X")))
        bindings = self.service.bindings()
        native = _User32()
        identifiers = register_global_hotkeys(native, 1, bindings, strict=True)
        actions = {action_for_hotkey_id(key) for key in identifiers}
        self.assertIn("text_action:summary", actions)
        self.assertIn("text_action:rewrite", actions)
        self.assertNotIn("rewrite_hotkey", actions)
        rejected = _User32(fail_keys={ord("X")})
        with self.assertRaises(HotkeyRegistrationError):
            register_global_hotkeys(rejected, 1, bindings, strict=True)
        self.assertEqual(rejected.registered, [])
        self.assertTrue(rejected.unregistered)

    def test_future_schema_stays_read_only(self):
        self.repo.path.write_text('{"schema_version":99}', encoding="utf-8")
        with self.assertRaises(UnsupportedSchemaVersionError):
            self.save(self.custom())
        self.assertEqual(
            self.repo.path.read_text(encoding="utf-8"), '{"schema_version":99}'
        )
        self.applier.assert_not_called()

    def test_profiles_reject_audio_and_do_not_store_credentials(self):
        state = self.service.projection()
        value = {
            "id": "legacy-rewrite",
            "providerId": "local_asr",
            "modelId": "ggml-small",
            "customEndpoint": "",
            "enabled": True,
        }
        with self.assertRaises(ValueError):
            self.service.save_profile(
                value, state["textActionContext"], state["textActionsRevision"]
            )
        value.update(providerId="openai", modelId="gpt-4.1-mini")
        state = self.service.save_profile(
            value, state["textActionContext"], state["textActionsRevision"]
        )
        self.assertEqual(self.repo.load().workflow("rewrite").model_id, "gpt-4.1-mini")
        self.assertEqual(len(state["textActionProfiles"]), 3)
        self.assertNotIn("api_key", str(self.repo.load().text_actions.to_mapping()))

    def test_profile_edit_keeps_chatgpt_binding_and_independence_without_provider_change(
        self,
    ):
        config = AppConfig.from_mapping(
            {
                "schema_version": 4,
                "workflows": {
                    "rewrite": {
                        "provider_id": "chatgpt",
                        "model_id": "plan-old",
                        "account_id": "bound-account",
                        "independent": True,
                    }
                },
            }
        )
        self.repo.apply(config)
        self.service.chatgpt_session = Mock(
            snapshot=Mock(
                return_value={
                    "connected": True,
                    "planEnabled": True,
                    "accountId": "other-account",
                }
            )
        )
        state = self.service.projection()
        profile = next(
            p for p in state["textActionProfiles"] if p["id"] == "legacy-rewrite"
        )
        self.assertFalse(profile["available"])
        profile["modelId"] = "plan-new"
        with self.assertRaisesRegex(ValueError, "catálogo"):
            self.service.save_profile(
                profile, state["textActionContext"], state["textActionsRevision"]
            )
        profile["modelId"] = "plan-old"
        state = self.service.save_profile(
            profile, state["textActionContext"], state["textActionsRevision"]
        )
        route = self.repo.load().workflow("rewrite")
        self.assertEqual(route.account_id, "bound-account")
        self.assertTrue(route.independent)
        self.assertEqual(route.model_id, "plan-old")
        profile = next(
            p for p in state["textActionProfiles"] if p["id"] == "legacy-rewrite"
        )
        profile.update(providerId="openai", modelId="gpt-4.1-mini")
        self.service.save_profile(
            profile, state["textActionContext"], state["textActionsRevision"]
        )
        self.assertEqual(self.repo.load().workflow("rewrite").account_id, "")

    def test_deleted_id_does_not_reset_its_revision_sequence(self):
        self.save(self.custom())
        state = self.save({**self.custom(), "prompt": "Return a title."})
        state = self.service.delete(
            "summary", state["textActionContext"], state["textActionsRevision"]
        )
        restored = self.save(self.custom())
        self.assertEqual(
            next(a for a in restored["textActions"] if a["id"] == "summary")[
                "revision"
            ],
            3,
        )

    def provider(self):
        registry = Mock(spec=ProviderRegistry)
        registry.describe.side_effect = PROVIDER_REGISTRY.describe
        registry.connection_for_route.side_effect = (
            PROVIDER_REGISTRY.connection_for_route
        )
        registry.rewrite.return_value = RewriteResult(
            "Summary result", "openai", "gpt-4o-mini"
        )
        config = SimpleNamespace(
            current=self.repo.load,
            workflow=lambda scope: self.repo.load().workflow(scope),
        )
        provider = WorkflowProviderService(
            config, Mock(), registry=registry, text_actions=self.service
        )
        return provider, registry

    def test_custom_snapshot_uses_neutral_policy_and_propagates_cancel(self):
        self.save(self.custom())
        provider, registry = self.provider()
        snapshot = provider.snapshot_text_action("summary")
        self.save({**self.custom(), "prompt": "Return a title."})
        token = CancellationToken()
        self.assertEqual(
            provider.transform_text_action(
                snapshot, "Original", cancel=token, writing_style="organized"
            ).text,
            "Summary result",
        )
        request = registry.rewrite.call_args.args[1]
        self.assertIn("Summarize this text.", request.instruction)
        self.assertNotIn("not summarization", request.instruction)
        self.assertNotIn("Do not invent information, summarize", request.instruction)
        self.assertIn("saved action's result", request.instruction)
        self.assertIs(registry.rewrite.call_args.args[3], token)
        token.cancel()
        with self.assertRaises(ProviderCancelledError):
            provider.transform_text_action(snapshot, "Original", cancel=token)
        self.assertEqual(registry.rewrite.call_count, 1)

    def test_post_dictation_preferences_have_distinct_cloud_and_local_contexts(self):
        self.save(self.custom())
        state = self.service.projection()
        self.service.set_after(
            "summary", "auto", state["textActionContext"], state["textActionsRevision"]
        )
        config = self.repo.load()
        self.repo.apply(
            replace(
                config,
                workflows=config.workflows.with_route(
                    "transcription", WorkflowRoute("local_asr", "ggml-small")
                ),
            )
        )
        self.assertEqual(self.service.projection()["afterDictationTextActionId"], "")
        config = self.repo.load()
        self.repo.apply(
            replace(
                config,
                workflows=config.workflows.with_route(
                    "transcription", WorkflowRoute("openai", "whisper-1")
                ),
            )
        )
        self.assertEqual(
            self.service.projection()["afterDictationTextActionId"], "summary"
        )


class WorkflowActionTests(unittest.TestCase):
    setUp = LocalServiceTests.setUp
    save = LocalServiceTests.save
    custom = LocalServiceTests.custom
    provider = LocalServiceTests.provider

    def workflow(self, provider):
        from tests.test_workflows import (
            FakeAudio,
            FakeClipboard,
            FakeConfig,
            FakeStatistics,
            FakeClock,
            ManualScheduler,
        )
        from workflows import WorkflowService

        self.scheduler = ManualScheduler()
        self.clipboard = FakeClipboard()
        self.statistics = FakeStatistics()
        self.workflow_service = WorkflowService(
            provider,
            FakeAudio(),
            self.clipboard,
            FakeConfig(),
            self.statistics,
            self.scheduler,
            FakeClock(),
        )
        return self.workflow_service

    def drain(self):
        for _ in range(15):
            if not self.scheduler.soon and not self.scheduler.background:
                return
            while self.scheduler.soon:
                self.scheduler.soon.pop(0)()
            if self.scheduler.background:
                self.scheduler.background.pop(0)()
        self.fail("Workflow did not finish")

    def test_run_by_id_snapshots_before_capture_and_publishes_once(self):
        from workflows import RunTextAction, WorkflowPhase

        self.save(self.custom())
        provider, registry = self.provider()
        workflow = self.workflow(provider)
        self.assertTrue(workflow.dispatch(RunTextAction("summary")))
        self.save({**self.custom(), "prompt": "Return a title."})
        self.drain()
        self.assertEqual(workflow.state.phase, WorkflowPhase.COMPLETED)
        self.assertEqual(self.clipboard.writes, ["Summary result"])
        self.assertEqual(workflow.state.source_text, "Original")
        self.assertEqual(workflow.state.text_action_id, "summary")
        self.assertEqual(workflow.state.text_action_revision, 1)
        self.assertEqual(len(self.statistics.rewrites), 1)
        self.assertIn(
            "Summarize this text.", registry.rewrite.call_args.args[1].instruction
        )

    def test_provider_cancellation_and_queued_stale_result_never_publish(self):
        from workflows import RunTextAction

        self.save(self.custom())
        provider, registry = self.provider()
        workflow = self.workflow(provider)

        def cancelled(*args):
            workflow.cancel_active()
            return RewriteResult("Late", "openai", "gpt-4o-mini")

        registry.rewrite.side_effect = cancelled
        workflow.dispatch(RunTextAction("summary"))
        self.drain()
        self.assertTrue(registry.rewrite.call_args.args[3].cancelled)
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.statistics.rewrites, [])

    def test_account_change_after_provider_before_publication_rejects_result(self):
        from workflows import RunTextAction, WorkflowPhase

        self.save(self.custom())
        account = AccountService(
            self.directory,
            secrets=MemorySecretStore(),
            request=Mock(side_effect=AssertionError("Unexpected HTTP")),
        )
        self.service.account = account
        provider, _registry = self.provider()
        provider.account = account
        workflow = self.workflow(provider)
        workflow.dispatch(RunTextAction("summary"))
        self.scheduler.background.pop(0)()
        self.assertEqual(workflow.state.phase, WorkflowPhase.PUBLISHING)
        account._generation += 1
        self.drain()
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.statistics.rewrites, [])
        self.assertEqual(workflow.state.phase, WorkflowPhase.FAILED)

    def test_translation_kind_keeps_picker_for_arbitrary_id(self):
        from workflows import RunTextAction, WorkflowPhase, ChooseTranslationLanguage

        self.save(
            TextAction(
                "translate-custom",
                "Translation template",
                "Use German. Target {lang}. Keep {literal}.",
                "translation",
            ).to_mapping()
        )
        provider, registry = self.provider()
        registry.translate.return_value = TranslationResult(
            "Translated", "openai", "gpt-4o-mini", "en"
        )
        workflow = self.workflow(provider)
        workflow.dispatch(RunTextAction("translate-custom"))
        self.drain()
        self.assertEqual(workflow.state.phase, WorkflowPhase.TRANSLATION_PICKER)
        registry.translate.assert_not_called()
        workflow.dispatch(ChooseTranslationLanguage("en"))
        self.drain()
        self.assertIn(
            "Output MUST be in English",
            registry.translate.call_args.args[1].instruction,
        )
        self.assertIn(
            "Target English. Keep {literal}.",
            registry.translate.call_args.args[1].instruction,
        )
        self.assertEqual(self.clipboard.writes, ["Translated"])

    def test_post_dictation_expands_once_then_runs_only_selected_action(self):
        from workflows import RecordingSnapshot

        self.save(self.custom())
        state = self.service.projection()
        self.service.set_after(
            "summary", "auto", state["textActionContext"], state["textActionsRevision"]
        )
        config = self.repo.load()
        self.repo.apply(
            replace(
                config,
                workflows=config.workflows.with_route(
                    "transcription", WorkflowRoute("openai", "whisper-1")
                ),
            )
        )
        provider, registry = self.provider()
        order = []
        provider.dictionary_service.state = SimpleNamespace(snippets=())
        provider.dictionary_service.apply_context.side_effect = lambda r: r
        provider.dictionary_service.expand_spoken_trigger.return_value = None
        provider.dictionary_service.expand.side_effect = lambda text: (
            order.append("expand") or text + " expanded"
        )
        registry.transcribe.side_effect = lambda *args: (
            order.append("recognize")
            or TranscriptionResult("Original", "openai", "whisper-1")
        )
        registry.rewrite.side_effect = lambda *args: (
            order.append("action") or RewriteResult("Summary", "openai", "gpt-4o-mini")
        )
        audio = RecordingSnapshot(
            Path("fixture-not-read.wav"), b"fake-audio", CancellationToken()
        )
        with patch("provider_registry.PROVIDER_HTTP.logger"):
            result = provider.transcribe(audio, "prompt", "en")
        self.assertEqual(order, ["recognize", "expand", "action"])
        self.assertEqual(registry.rewrite.call_count, 1)
        self.assertEqual(registry.rewrite.call_args.args[1].text, "Original expanded")
        self.assertEqual(result.raw_text, "Original")
        self.assertEqual(result.text_action_id, "summary")
        registry.rewrite.side_effect = RuntimeError("fixture failure")
        with patch("provider_registry.PROVIDER_HTTP.logger"):
            recovered = provider.transcribe(audio, "prompt", "en")
        self.assertEqual(recovered.text, "Original expanded")
        self.assertTrue(recovered.refinement_failed)
        provider.dictionary_service.expand_spoken_trigger.return_value = "Saved snippet"
        registry.rewrite.reset_mock()
        with patch("provider_registry.PROVIDER_HTTP.logger"):
            bypassed = provider.transcribe(audio, "prompt", "en")
        self.assertEqual(bypassed.text, "Saved snippet")
        registry.rewrite.assert_not_called()

    def test_input_and_output_bounds_use_utf8_bytes(self):
        self.save(self.custom())
        provider, registry = self.provider()
        snapshot = provider.snapshot_text_action("summary")
        with self.assertRaises(ValueError):
            provider.transform_text_action(snapshot, "é" * 8001)
        registry.rewrite.assert_not_called()
        registry.rewrite.return_value = RewriteResult(
            "é" * 32001, "openai", "gpt-4o-mini"
        )
        with self.assertRaises(ValueError):
            provider.transform_text_action(snapshot, "Source")

    def test_paired_input_policy_cannot_expand_hosted_or_default_requests(self):
        from text_actions import TextActionInputPolicy

        self.save(self.custom())
        provider, registry = self.provider()
        snapshot = provider.snapshot_text_action("summary")
        with self.assertRaises(ValueError):
            provider.transform_text_action(snapshot, "Source", "fr")
        provider.text_action_input_policy = TextActionInputPolicy.PAIRED_COMPUTER
        with self.assertRaises(ValueError):
            provider.transform_text_action(
                replace(snapshot, account_context=object()), "Source"
            )
        registry.rewrite.assert_not_called()

    def test_dictation_action_snapshot_precedes_recording_and_queued_publication(self):
        from workflows import StartDictation, StopDictation

        self.save(self.custom())
        state = self.service.projection()
        self.service.set_after(
            "summary", "auto", state["textActionContext"], state["textActionsRevision"]
        )
        provider, registry = self.provider()
        workflow = self.workflow(provider)
        provider.dictionary_service.apply_context.side_effect = lambda r: r
        provider.dictionary_service.state = SimpleNamespace(snippets=())
        provider.dictionary_service.expand_spoken_trigger.return_value = None
        provider.dictionary_service.expand.side_effect = lambda text: text
        registry.transcribe.return_value = TranscriptionResult(
            "Original", "gemini", "gemini-2.5-flash"
        )
        workflow.dispatch(
            StartDictation(self.clipboard.capture_target(), "prompt", "en")
        )
        self.save({**self.custom(), "prompt": "Return a title."})
        self.drain()
        with patch("provider_registry.PROVIDER_HTTP.logger"):
            workflow.dispatch(StopDictation())
            self.drain()
        self.assertIn(
            "Summarize this text.", registry.rewrite.call_args.args[1].instruction
        )
        self.assertEqual(workflow.state.text_action_revision, 1)


if __name__ == "__main__":
    unittest.main()
