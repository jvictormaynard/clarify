"""Qt-thread effects, pending RPCs and profile-specific model discovery."""

import threading
import time
import unittest
from dataclasses import replace
from contextlib import nullcontext
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from provider_types import ModelCatalog
from text_actions import TextAction
import tests.support.qml_text_actions as fixture
from tests.support.text_actions import HostedFixture
from tests.support.chatgpt_settings import FakeChatGPTSession


class QmlTextActionRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    setUp = fixture.QmlTextActionFixture.setUp
    request = fixture.QmlTextActionFixture.request

    def drain_until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.settings._drain_background_publications()
            self.app.processEvents()
        self.assertTrue(predicate(), "worker did not finish")

    def hosted(self):
        account = self.settings._account
        account._generation += 1
        self.server = HostedFixture()
        account.request = self.server
        account._state = {
            "endpoint": "https://account.invalid",
            "mode": "hosted",
            "user_id": "11111111-1111-4111-8111-111111111111",
        }
        account.secrets.set("clarify_account", "fixture-token")
        self.settings._text_actions.refresh()
        self.applier.reset_mock()

    def block_http(self, method):
        entered, release = threading.Event(), threading.Event()
        original = self.settings._account.request

        def request(verb, *args, **kwargs):
            if verb == method:
                entered.set()
                release.wait(
                    3
                )  # Safety bound; the assertion checks release has not run.
            return original(verb, *args, **kwargs)

        self.settings._account.request = request
        self.addCleanup(release.set)
        return entered, release

    def start_save(self):
        state = self.request("snapshot")["result"]
        return self.request(
            "saveTextAction",
            TextAction("new", "New", "Edit.").to_mapping(),
            state["textActionContext"],
            state["textActionsRevision"],
        )

    def test_hosted_put_acceptance_keeps_poll_callbacks_and_native_effects_on_qt(self):
        self.hosted()
        entered, release = self.block_http("PUT")
        saved, native_threads = [], []
        self.settings.saved.connect(lambda: saved.append(True))
        self.applier.side_effect = lambda _: native_threads.append(
            threading.get_ident()
        )
        callback = threading.Event()
        QTimer.singleShot(0, callback.set)
        reply = self.start_save()
        self.assertNotIn("error", reply)
        self.assertTrue(entered.wait(1))
        self.assertFalse(release.is_set())
        self.assertTrue(reply["result"]["textActionMutation"]["busy"])
        self.assertEqual(saved, [])
        self.assertFalse(self.applier.called)
        self.assertNotIn("error", self.request("poll"))
        self.app.processEvents()
        self.assertTrue(callback.is_set())
        release.set()
        self.drain_until(lambda: not self.settings.textActionMutation["busy"])
        self.assertEqual(self.settings.textActionMutation["status"], "succeeded")
        self.assertEqual(saved, [True])
        self.assertEqual(native_threads, [threading.get_ident()])

    def test_profile_catalog_uses_chatgpt_cache_without_selecting_workflow(self):
        state = {
            "connected": True,
            "planEnabled": True,
            "accountId": "account-a",
            "generation": 7,
        }
        session = Mock(snapshot=Mock(side_effect=lambda: dict(state)))
        self.settings._chatgpt_session = session
        self.settings._text_actions.chatgpt_session = session
        self.settings._model_catalogs[("chatgpt", "account-a", "7")] = ModelCatalog(
            text_models=("plan-one", "plan-two"),
            display_names={"plan-two": "Second model"},
        )
        self.settings.setRoutePrompt("Pending audio instruction")
        before = self.request("snapshot")["result"]
        reply = self.request(
            "loadTextActionProfileModels",
            "default",
            "chatgpt",
            "",
            before["textActionContext"],
            before["textActionsRevision"],
            "editor-1",
        )
        self.assertNotIn("error", reply)
        catalog = reply["result"]["textActionProfileModels"]
        self.assertEqual(catalog["status"], "ready")
        self.assertEqual(
            catalog["models"][1], {"id": "plan-two", "label": "Second model"}
        )
        profile = dict(
            before["textActionProfiles"][0], providerId="chatgpt", modelId="plan-two"
        )
        reply = self.request(
            "saveTextActionProfile",
            profile,
            before["textActionContext"],
            before["textActionsRevision"],
            catalog["requestKey"],
        )
        self.assertNotIn("error", reply)
        self.assertEqual(self.settings.selectedScope, "transcription")
        self.assertEqual(self.settings.routePrompt, "Pending audio instruction")
        self.assertEqual(
            self.settings.repositories.config.load().workflow("refinement").account_id,
            "account-a",
        )

    def test_hosted_get_leaves_qt_poll_and_callback_free_and_publishes_on_qt(self):
        self.hosted()
        entered, release = self.block_http("GET")
        threads = []
        self.applier.side_effect = lambda _: threads.append(threading.get_ident())
        self.assertTrue(self.settings.refreshTextActions())
        self.assertTrue(entered.wait(1))
        callback = threading.Event()
        QTimer.singleShot(0, callback.set)
        self.assertNotIn("error", self.request("poll"))
        self.app.processEvents()
        self.assertTrue(callback.is_set())
        self.assertFalse(release.is_set())
        self.assertEqual(threads, [])
        release.set()
        self.drain_until(lambda: bool(threads))
        self.assertEqual(threads, [threading.get_ident()])

    def test_refresh_publishes_recovery_job_and_clears_incomplete_state(self):
        self.hosted()
        self.settings._text_actions._incomplete = True
        self.settings._text_action_mutation.update(
            status="failed", restoreRequired=True
        )
        entered, release = self.block_http("GET")
        reply = self.request("refreshTextActions")["result"]
        self.assertTrue(entered.wait(1))
        job = reply["textActionRefresh"]
        self.assertTrue(job["busy"])
        self.assertEqual(job["status"], "pending")
        self.assertTrue(reply["textActionsBusy"])
        self.assertTrue(reply["textActionContext"])
        release.set()
        self.drain_until(lambda: not self.settings.textActionRefresh["busy"])
        after = self.request("snapshot")["result"]
        self.assertEqual(after["textActionRefresh"]["generation"], job["generation"])
        self.assertEqual(after["textActionRefresh"]["status"], "succeeded")
        self.assertEqual(after["textActionsError"], "")
        self.assertFalse(after["textActionsBusy"])
        self.assertFalse(after["textActionMutation"]["restoreRequired"])
        self.assertFalse(self.settings._text_actions._incomplete)

    def test_put_failure_local_failure_and_compensation_conflict_finish_once(self):
        for failure in ("network", "local", "conflict", "native", "restore"):
            with self.subTest(failure=failure):
                self.hosted()
                saved = Mock()
                self.settings.saved.connect(saved)
                original = self.server
                if failure == "network":

                    def request(verb, *args, **kwargs):
                        if verb == "PUT":
                            from clarify_account import AccountError

                            raise AccountError("Não foi possível acessar o Clarify.")
                        return original(verb, *args, **kwargs)

                    self.settings._account.request = request
                elif failure == "conflict":

                    def concurrent(body):
                        if body["expected_revision"] == 1:
                            self.server.revision = 2
                            self.server.actions[0]["name"] = "Newer client"

                    self.server.on_put = concurrent
                if failure in {"native", "restore"}:
                    attempts = []

                    def apply(_):
                        attempts.append(threading.get_ident())
                        if failure == "restore" or len(attempts) == 1:
                            raise OSError("fixture registration")

                    self.applier.side_effect = apply
                with (
                    patch.object(
                        self.settings.repositories.config,
                        "apply",
                        side_effect=OSError("fixture disk"),
                    )
                    if failure in {"local", "conflict"}
                    else nullcontext()
                ):
                    self.assertNotIn("error", self.start_save())
                    self.drain_until(
                        lambda: not self.settings.textActionMutation["busy"]
                    )
                saved.assert_not_called()
                self.settings.saved.disconnect(saved)
                self.assertEqual(self.settings.textActionMutation["status"], "failed")
                self.assertIsNone(
                    self.settings.repositories.config.load().text_actions.action("new")
                )
                if failure in {"local", "native", "restore"}:
                    self.assertEqual(
                        [
                            c[2]["json"]["expected_revision"]
                            for c in self.server.calls
                            if c[0] == "PUT"
                        ],
                        [0, 1],
                    )
                    self.assertEqual(len(self.server.actions), 1)
                if failure == "conflict":
                    self.assertEqual(self.server.actions[0]["name"], "Newer client")
                    self.assertEqual(
                        self.settings.textActionMutation["errorCode"], "restore_failed"
                    )
                self.applier.side_effect = None
                self.settings._text_actions._incomplete = False

    def test_config_cas_and_context_changes_during_put_cannot_publish_or_overwrite(
        self,
    ):
        for change in ("config", "account"):
            with self.subTest(change=change):
                self.hosted()
                entered, release = self.block_http("PUT")
                saved = Mock()
                self.settings.saved.connect(saved)
                self.assertNotIn("error", self.start_save())
                self.assertTrue(entered.wait(1))
                if change == "config":
                    repo = self.settings.repositories.config
                    config = repo.load()
                    repo.apply(replace(config, ui=replace(config.ui, language="es")))
                else:
                    self.settings._account._generation += 1
                    self.settings._account._state["user_id"] = (
                        "22222222-2222-4222-8222-222222222222"
                    )
                release.set()
                self.drain_until(lambda: not self.settings.textActionMutation["busy"])
                self.assertEqual(self.settings.textActionMutation["status"], "failed")
                saved.assert_not_called()
                self.settings.saved.disconnect(saved)
                self.applier.assert_not_called()
                if change == "config":
                    self.assertEqual(repo.load().ui.language, "es")
                    self.assertEqual(len(self.server.actions), 1)
                else:
                    self.assertEqual(self.settings.textActions, [])
                self.settings._text_actions._incomplete = False

    def test_shutdown_during_put_compensates_without_native_or_qt_publication(self):
        self.hosted()
        entered, release = self.block_http("PUT")
        saved, finished = Mock(), threading.Event()
        self.settings.saved.connect(saved)
        service = self.settings._text_actions
        finish = service.finish_mutation

        def complete(*args, **kwargs):
            try:
                return finish(*args, **kwargs)
            finally:
                finished.set()

        with patch.object(service, "finish_mutation", side_effect=complete):
            self.assertNotIn("error", self.start_save())
            self.assertTrue(entered.wait(1))
            self.settings.shutdown()
            release.set()
            self.assertTrue(finished.wait(2))
        self.assertEqual(len(self.server.actions), 1)
        self.applier.assert_not_called()
        saved.assert_not_called()

    def model_args(self, provider="openai", endpoint="", request_id="request"):
        state = self.request("snapshot")["result"]
        return (
            "default",
            provider,
            endpoint,
            state["textActionContext"],
            state["textActionsRevision"],
            request_id,
        )

    def test_profile_discovery_is_explicit_for_endpoint_drafts_and_rejects_late_requests(
        self,
    ):
        repo = self.settings.repositories.config
        config = repo.load()
        repo.apply(
            replace(config, openai=replace(config.openai, api_key="synthetic-key"))
        )
        entered, release, returned = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def discover(provider, connection, token):
            self.assertEqual(connection.base_url, "https://draft.invalid/v1")
            entered.set()
            self.assertTrue(release.wait(3))
            returned.set()
            return ModelCatalog(text_models=("stale-model",))

        with patch(
            "clarify.desktop.qml_settings.PROVIDER_REGISTRY.discover_models",
            side_effect=discover,
        ) as discovery:
            args = self.model_args(endpoint="https://draft.invalid/v1")
            reply = self.request("loadTextActionProfileModels", *args)
            self.assertEqual(
                reply["result"]["textActionProfileModels"]["status"], "refresh_required"
            )
            discovery.assert_not_called()
            reply = self.request("refreshTextActionProfileModels", *args)
            self.assertTrue(entered.wait(1))
            self.assertTrue(reply["result"]["textActionProfileModels"]["busy"])
            self.assertNotIn("error", self.request("poll"))
            # New provider/draft request cancels the old worker without waiting.
            new = self.model_args(provider="groq", request_id="new-request")
            self.assertNotIn("error", self.request("loadTextActionProfileModels", *new))
            release.set()
            self.assertTrue(returned.wait(1))
            self.settings._drain_background_publications()
            self.assertEqual(
                self.settings.textActionProfileModels["requestId"], "new-request"
            )
            self.assertEqual(self.settings.textActionProfileModels["models"], [])
            self.assertEqual(self.settings.selectedScope, "transcription")

    def test_profile_binding_survives_account_switch_and_blocks_other_accounts_catalog(
        self,
    ):
        from workflow_config import WorkflowRoute

        session = FakeChatGPTSession()
        session.state.update(
            connected=True, planEnabled=True, accountId="account-a", generation=1
        )
        self.settings._chatgpt_session = session
        self.settings._text_actions.chatgpt_session = session
        repo = self.settings.repositories.config
        config = repo.load()
        repo.apply(
            replace(
                config,
                workflows=config.workflows.with_route(
                    "refinement",
                    WorkflowRoute("chatgpt", "old-plan", account_id="account-a"),
                ),
            )
        )
        self.settings._read_chatgpt_snapshot()
        session.state.update(accountId="account-b", generation=2)
        self.settings._read_chatgpt_snapshot()
        route = repo.load().text_actions.profile("default").resolved(repo.load())
        self.assertEqual((route.model_id, route.account_id), ("old-plan", "account-a"))
        self.settings._model_catalogs[("chatgpt", "account-b", "2")] = ModelCatalog(
            text_models=("other-plan",)
        )
        reply = self.request(
            "loadTextActionProfileModels", *self.model_args(provider="chatgpt")
        )
        catalog = reply["result"]["textActionProfileModels"]
        self.assertEqual(catalog["status"], "account_mismatch")
        self.assertEqual(catalog["models"], [])
        state = self.request("snapshot")["result"]
        profile = dict(state["textActionProfiles"][0], modelId="other-plan")
        self.assertIn(
            "error",
            self.request(
                "saveTextActionProfile",
                profile,
                state["textActionContext"],
                state["textActionsRevision"],
                catalog["requestKey"],
            ),
        )

    def test_profile_catalog_context_permission_cancel_and_shutdown_reject_results(
        self,
    ):
        repo = self.settings.repositories.config
        config = repo.load()
        repo.apply(
            replace(config, openai=replace(config.openai, api_key="synthetic-key"))
        )
        for change in ("context", "endpoint", "credentials", "cancel", "shutdown"):
            with self.subTest(change=change):
                entered, release, completed = (
                    threading.Event(),
                    threading.Event(),
                    threading.Event(),
                )
                self.addCleanup(release.set)

                def discover(*args):
                    entered.set()
                    self.assertTrue(release.wait(3))
                    completed.set()
                    return ModelCatalog(text_models=("late-model",))

                with patch(
                    "clarify.desktop.qml_settings.PROVIDER_REGISTRY.discover_models",
                    side_effect=discover,
                ):
                    self.assertNotIn(
                        "error",
                        self.request(
                            "refreshTextActionProfileModels", *self.model_args()
                        ),
                    )
                    self.assertTrue(entered.wait(1))
                    if change == "context":
                        self.settings._account._generation += 1
                    elif change == "endpoint":
                        config = repo.load()
                        repo.apply(
                            replace(
                                config,
                                openai=replace(
                                    config.openai, base_url="https://new.invalid/v1"
                                ),
                            )
                        )
                    elif change == "credentials":
                        config = repo.load()
                        repo.apply(
                            replace(
                                config,
                                openai=replace(config.openai, api_key="new-synthetic"),
                            )
                        )
                    elif change == "cancel":
                        self.settings.cancelTextActionProfileModels()
                    else:
                        self.settings.shutdown()
                    release.set()
                    self.assertTrue(completed.wait(1))
                    self.settings._drain_background_publications()
                    self.assertEqual(
                        self.settings.textActionProfileModels["models"], []
                    )
                    self.assertFalse(self.settings.textActionProfileModels["busy"])

    def test_profile_save_rechecks_chatgpt_identity_at_local_commit(self):
        session = FakeChatGPTSession()
        session.state.update(
            connected=True, planEnabled=True, accountId="account-a", generation=1
        )
        self.settings._chatgpt_session = session
        self.settings._text_actions.chatgpt_session = session
        self.settings._model_catalogs[("chatgpt", "account-a", "1")] = ModelCatalog(
            text_models=("plan-one",)
        )
        reply = self.request(
            "loadTextActionProfileModels", *self.model_args(provider="chatgpt")
        )
        catalog = reply["result"]["textActionProfileModels"]
        before = self.request("snapshot")["result"]
        profile = dict(
            before["textActionProfiles"][0], providerId="chatgpt", modelId="plan-one"
        )
        service = self.settings._text_actions
        commit = service.commit_mutation

        def switch_then_commit(mutation):
            session.state.update(accountId="account-b", generation=2)
            commit(mutation)

        with patch.object(service, "commit_mutation", side_effect=switch_then_commit):
            reply = self.request(
                "saveTextActionProfile",
                profile,
                before["textActionContext"],
                before["textActionsRevision"],
                catalog["requestKey"],
            )
        self.assertIn("error", reply)
        self.assertNotEqual(
            self.settings.repositories.config.load().workflow("refinement").provider_id,
            "chatgpt",
        )

    def test_compensation_put_keeps_poll_free_until_the_same_job_fails(self):
        self.hosted()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = self.settings._account.request

        def request(verb, *args, **kwargs):
            if verb == "PUT" and kwargs["json"]["expected_revision"] == 1:
                entered.set()
                self.assertTrue(release.wait(3))
            return original(verb, *args, **kwargs)

        self.settings._account.request = request
        with patch.object(
            self.settings.repositories.config,
            "apply",
            side_effect=OSError("fixture local failure"),
        ):
            reply = self.start_save()
            generation = reply["result"]["textActionMutation"]["generation"]
            self.drain_until(entered.is_set)
            state = self.request("snapshot")["result"]
            self.assertEqual(state["textActionMutation"]["generation"], generation)
            self.assertEqual(state["textActionMutation"]["status"], "restoring")
            self.assertTrue(state["textActionMutation"]["busy"])
            callback = threading.Event()
            QTimer.singleShot(0, callback.set)
            self.assertNotIn("error", self.request("poll"))
            self.app.processEvents()
            self.assertTrue(callback.is_set())
            release.set()
            self.drain_until(lambda: not self.settings.textActionMutation["busy"])
        self.assertEqual(self.settings.textActionMutation["generation"], generation)
        self.assertEqual(self.settings.textActionMutation["status"], "failed")

    def test_profile_discovery_error_is_safe_and_plan_permission_is_required(self):
        session = FakeChatGPTSession()
        session.state.update(
            connected=True, planEnabled=False, accountId="account-a", generation=1
        )
        self.settings._chatgpt_session = session
        self.settings._text_actions.chatgpt_session = session
        reply = self.request(
            "refreshTextActionProfileModels", *self.model_args(provider="chatgpt")
        )
        self.assertEqual(
            reply["result"]["textActionProfileModels"]["status"], "not_configured"
        )
        self.assertEqual(reply["result"]["textActionProfileModels"]["models"], [])
        repo = self.settings.repositories.config
        config = repo.load()
        repo.apply(
            replace(config, openai=replace(config.openai, api_key="synthetic-key"))
        )
        with patch(
            "clarify.desktop.qml_settings.PROVIDER_REGISTRY.discover_models",
            side_effect=RuntimeError("synthetic-key private-endpoint"),
        ):
            self.assertNotIn(
                "error",
                self.request("refreshTextActionProfileModels", *self.model_args()),
            )
            self.drain_until(lambda: not self.settings.textActionProfileModels["busy"])
        self.assertEqual(self.settings.textActionProfileModels["status"], "error")
        self.assertNotIn("synthetic-key", str(self.settings.textActionProfileModels))
