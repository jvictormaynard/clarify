"""Offline contracts for the ChatGPT Settings boundary."""

import json
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from clarify.desktop.qml_settings import QmlSettingsController
from clarify.desktop.qml_web_settings import SettingsProtocol
from local_asr_product import LocalASRProductState
from provider_registry import PROVIDER_REGISTRY
from provider_http import InvalidModelError
from provider_registry import build_provider_registry
from workflow_provider import WorkflowProviderService
from shared.localization import translate


from tests.support.chatgpt_settings import (
    FakeChatGPTSession,
    FakeChatGPTAdapter,
)
from tests.support.settings import _repositories, _MicrophoneBackend
from microphone_controls import MicrophoneInventory


class ChatGPTSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.session = FakeChatGPTSession()
        self.guard = True
        self.settings = QmlSettingsController(
            _repositories(self.directory.name),
            chatgpt_session=self.session,
            account_can_change=lambda: self.guard,
            microphone_backend=_MicrophoneBackend(
                MicrophoneInventory.unavailable("test")
            ),
            local_product=Mock(state=LocalASRProductState("missing"), busy=False),
        )
        self.addCleanup(self.settings.shutdown)
        self.protocol = SettingsProtocol(self.settings)

    def wait_idle(self):
        deadline = time.monotonic() + 3
        while self.settings.chatgptState["busy"] and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertFalse(self.settings.chatgptState["busy"])

    def command(self, action, value=""):
        return self.protocol.dispatch(
            dict(id=1, method="chatgptCommand", args=[action, value])
        )

    def test_connect_and_notice_are_separate_from_config_drafts_and_secrets(self):
        before = self.settings.repositories.config.load()
        self.assertIn("result", self.command("sign_in"))
        self.wait_idle()
        state = self.protocol.snapshot()
        self.assertTrue(state["chatgptState"]["connected"])
        self.assertTrue(state["chatgptState"]["planEnabled"])
        self.assertFalse(state["chatgptState"]["planNoticeSeen"])
        self.assertNotIn("must-never-cross-rpc", json.dumps(state))
        self.assertNotIn("access_token", json.dumps(state))
        self.command("dismiss_notice")
        self.wait_idle()
        self.assertTrue(self.settings.chatgptState["planNoticeSeen"])
        self.assertFalse(self.settings.dirty)
        self.assertEqual(self.settings.repositories.config.load(), before)

    def test_busy_guard_unknown_commands_and_usage_url(self):
        self.guard = False
        self.assertIn("error", self.command("sign_in"))
        self.assertFalse(self.session.calls)
        self.guard = True
        self.assertIn("error", self.command("credential"))
        self.assertIn("error", self.command("manage_usage", "https://evil.example"))
        with patch("webbrowser.open", return_value=True) as browser:
            self.assertIn("result", self.command("manage_usage"))
            self.wait_idle()
        browser.assert_called_once_with("https://chatgpt.com/settings/usage")

    def test_cancel_keeps_worker_bounded_and_shutdown_rejects_late_publication(self):
        self.session.wait = threading.Event()
        self.command("sign_in")
        self.assertTrue(self.settings.chatgptState["busy"])
        self.assertIn("error", self.command("add_account"))
        self.command("cancel")
        self.assertTrue(self.session.cancelled.wait(1))
        self.wait_idle()
        self.assertFalse(self.settings.chatgptState["connected"])
        self.session.wait = threading.Event()
        self.command("sign_in")
        self.settings.shutdown()
        self.session.wait.set()
        self.app.processEvents()
        self.assertFalse(self.settings.chatgptState["connected"])

    def install_fake_provider(self):
        self.adapter = FakeChatGPTAdapter(self.session)
        patcher = patch.dict(PROVIDER_REGISTRY._adapters, chatgpt=self.adapter)
        patcher.start()
        self.addCleanup(patcher.stop)
        return self.settings.repositories.config

    def wait_models(self):
        deadline = time.monotonic() + 3
        while (
            self.settings.providerBusy or self.settings.routeModelStatus == "loading"
        ) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    def test_account_catalog_keeps_labels_order_and_rejects_stale_model_choices(self):
        repository = self.install_fake_provider()
        self.settings.selectWorkflow("rewrite")
        self.settings.savePreference("setRouteProviderId", ["chatgpt"])
        self.settings._dirty = False
        self.command("sign_in")
        self.wait_idle()
        self.wait_models()
        self.assertEqual(
            self.settings.routeModelOptions,
            [
                {"id": "personal-z", "label": "First account model"},
                {"id": "personal-a", "label": "Second account model"},
            ],
        )
        catalog = self.settings.chatgptTextCatalog
        self.assertEqual(catalog["accountId"], "personal")
        self.assertEqual(catalog["generation"], self.session.state["generation"])
        self.assertEqual(catalog["models"], self.settings.routeModelOptions)
        self.assertTrue(self.settings.savePreference("setRouteModelId", ["personal-a"]))
        self.assertEqual(repository.load().workflow("rewrite").model_id, "personal-a")
        self.assertEqual(repository.load().workflow("rewrite").account_id, "personal")
        self.assertTrue(self.settings.selectProvider("chatgpt"))
        self.assertFalse(self.settings.setProviderApiKey("secret"))
        self.assertFalse(self.settings.setProviderBaseUrl("https://evil.example"))
        self.assertFalse(self.settings.setRouteCustomEndpoint("https://evil.example"))
        self.command("add_account")
        self.wait_idle()
        self.wait_models()
        self.assertEqual(self.settings.routeModelId, "")
        self.assertEqual(self.settings.chatgptTextCatalog["accountId"], "second")
        self.assertEqual(repository.load().workflow("rewrite").model_id, "")
        self.assertFalse(
            self.settings.savePreference("setRouteModelId", ["personal-a"])
        )
        self.assertTrue(self.settings.savePreference("setRouteModelId", ["second-z"]))
        self.command("select_account", "personal")
        self.wait_idle()
        self.wait_models()
        self.assertEqual(self.settings.routeModelOptions[0]["id"], "personal-z")
        self.command("sign_out")
        self.wait_idle()
        self.assertEqual(self.settings.routeModelOptions, [])
        self.assertEqual(self.settings.chatgptTextCatalog, {})
        self.assertEqual(self.settings.routeModelStatus, "not_configured")
        self.assertEqual(repository.load().workflow("rewrite").model_id, "")
        self.assertFalse(self.settings.dirty)
        self.assertTrue(
            all(
                c.api_key == "" and c.base_url == "https://api.openai.com/v1"
                for c in self.adapter.calls
            )
        )

    def test_failed_account_model_reset_stays_blocked_after_restart(self):
        repository = self.install_fake_provider()
        self.settings.selectWorkflow("rewrite")
        self.settings.savePreference("setRouteProviderId", ["chatgpt"])
        self.command("sign_in")
        self.wait_idle()
        self.wait_models()
        self.assertTrue(self.settings.savePreference("setRouteModelId", ["personal-a"]))
        with patch.object(repository, "apply", side_effect=OSError("disk unavailable")):
            self.command("add_account")
            self.wait_idle()
            self.wait_models()
        persisted = repository.load()
        self.assertEqual(persisted.workflow("rewrite").account_id, "personal")
        self.assertEqual(self.session.state["accountId"], "second")
        self.settings.shutdown()

        # A crash/restart retains the old disk route. Even if its slug exists
        # in the new catalog, the UI and runtime must reject its account ID.
        restarted = QmlSettingsController(
            self.settings.repositories,
            chatgpt_session=self.session,
            microphone_backend=_MicrophoneBackend(
                MicrophoneInventory.unavailable("test")
            ),
            local_product=Mock(state=LocalASRProductState("missing"), busy=False),
        )
        self.addCleanup(restarted.shutdown)
        restarted.selectWorkflow("rewrite")
        from provider_types import ModelCatalog

        key = restarted._model_connection_key()
        restarted._model_catalogs[key] = ModelCatalog(text_models=("personal-a",))
        self.assertEqual(restarted.routeModelId, "")
        http = Mock()
        session = SimpleNamespace(
            credential=lambda **kwargs: SimpleNamespace(
                access_token="synthetic", generation=1, account_id="second"
            ),
            check_current=lambda generation: None,
        )
        service = WorkflowProviderService(
            SimpleNamespace(current=repository.load, workflow=persisted.workflow),
            SimpleNamespace(),
            registry=build_provider_registry(http, chatgpt_session=session),
        )
        with self.assertRaises(InvalidModelError):
            service.rewrite("Keep all facts.")
        http.request.assert_not_called()

    def test_model_selection_never_binds_a_previous_catalog_to_a_new_account(self):
        from provider_types import ModelCatalog

        repository = self.install_fake_provider()
        self.settings.selectWorkflow("rewrite")
        self.settings.savePreference("setRouteProviderId", ["chatgpt"])
        self.command("sign_in")
        self.wait_idle()
        self.wait_models()
        for persisted in (False, True):
            for switch_after in (1, 2):
                with self.subTest(persisted=persisted, switch_after=switch_after):
                    self.session.select_account("personal")
                    self.settings._read_chatgpt_snapshot()
                    key = self.settings._model_connection_key()
                    self.settings._model_catalogs[key] = ModelCatalog(
                        text_models=("shared-model",)
                    )
                    snapshot = self.session.snapshot
                    reads = 0

                    def change_after_snapshot():
                        nonlocal reads
                        value = snapshot()
                        reads += 1
                        if reads == switch_after:
                            self.session.select_account("external-during-selection")
                        return value

                    with patch.object(
                        self.session, "snapshot", side_effect=change_after_snapshot
                    ):
                        accepted = (
                            self.settings.savePreference(
                                "setRouteModelId", ["shared-model"]
                            )
                            if persisted
                            else self.settings.setRouteModelId("shared-model")
                        )
                    self.assertEqual(
                        self.session.state["accountId"], "external-during-selection"
                    )
                    route = (
                        repository.load() if persisted else self.settings._config
                    ).workflow("rewrite")
                    if accepted:
                        self.assertEqual(route.model_id, "shared-model")
                        self.assertEqual(route.account_id, "personal")
                    else:
                        self.assertNotEqual(
                            route.account_id, "external-during-selection"
                        )

    def test_identity_without_plan_permission_has_no_catalog_and_provider_tests_block_mutation(
        self,
    ):
        self.install_fake_provider()
        self.settings.selectWorkflow("rewrite")
        self.settings.setRouteProviderId("chatgpt")
        self.session.state.update(connected=True, planEnabled=False)
        self.assertEqual(self.settings.routeModelStatus, "not_configured")
        self.assertFalse(self.settings.refreshRouteModels())
        self.settings._provider_tokens["groq"] = Mock()
        self.assertIn("error", self.command("sign_in"))
        self.assertFalse(self.adapter.calls)

    def test_identity_change_reserves_native_operation_guard_and_releases_once(self):
        self.session.wait = threading.Event()
        account = self.settings._account
        with patch.object(account, "end_change", wraps=account.end_change) as release:
            self.command("sign_in")
            self.assertTrue(account.busy)
            self.assertFalse(account.begin_change())
            self.command("cancel")
            self.wait_idle()
            self.assertFalse(account.busy)
            self.assertEqual(release.call_count, 1)
            self.session.wait = threading.Event()
            self.command("sign_in")
            self.assertTrue(account.busy)
            self.settings.shutdown()
            self.assertFalse(account.busy)
            self.assertEqual(release.call_count, 2)
            self.session.wait.set()
            self.app.processEvents()
            self.settings.shutdown()
            self.assertEqual(release.call_count, 2)

    def test_auth_errors_use_localized_code_groups_without_exception_text(self):
        class PlanError(Exception):
            def __init__(self, code):
                self.code = code
                super().__init__("secret-token-and-private-auth-url")

        cases = {
            "cancelled": "ChatGPT connection cancelled.",
            "network": "Could not connect to ChatGPT. Check your connection and try again.",
            "plan_disabled": "Allow Clarify to use your ChatGPT plan, then connect again.",
            "refresh_failed": "Could not validate the ChatGPT connection. Connect again.",
            "storage_invalid": "Could not access ChatGPT credentials. Check secure storage on this computer and try again.",
            "revocation_failed": "You signed out of ChatGPT on this computer. Remote revocation was not confirmed. Disconnect Clarify in ChatGPT settings.",
        }
        with patch.dict(
            sys.modules, chatgpt_auth=SimpleNamespace(ChatGPTPlanError=PlanError)
        ):
            for code, message in cases.items():
                with (
                    self.subTest(code=code),
                    patch.object(self.session, "sign_in", side_effect=PlanError(code)),
                ):
                    self.command("sign_in")
                    self.wait_idle()
                    state = self.protocol.snapshot()
                    self.assertNotIn("secret-token", json.dumps(state))
                    self.assertEqual(
                        translate(state["chatgptState"]["error"], "en"), message
                    )
                    self.assertFalse(self.settings._account.busy)

    def test_external_account_change_rejects_late_catalog_and_provider_validation(self):
        self.install_fake_provider()
        self.settings.selectWorkflow("rewrite")
        self.settings.savePreference("setRouteProviderId", ["chatgpt"])
        self.command("sign_in")
        self.wait_idle()
        self.wait_models()
        self.settings.selectProvider("chatgpt")
        for method in (
            self.settings.refreshRouteModels,
            self.settings.validateProvider,
        ):
            with self.subTest(method=method.__name__):
                started, release, finished = (threading.Event() for _ in range(3))
                original = self.adapter.discover_models

                def blocked(*args):
                    catalog = original(*args)
                    started.set()
                    release.wait(3)
                    finished.set()
                    return catalog

                with patch.object(self.adapter, "discover_models", side_effect=blocked):
                    self.assertTrue(method())
                    self.assertTrue(started.wait(1))
                    self.session.select_account("external-account")
                    release.set()
                    self.assertTrue(finished.wait(1))
                    deadline = time.monotonic() + 0.2
                    while time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(0.01)
                self.assertEqual(self.settings.routeModelOptions, [])
                self.assertFalse(self.settings.providerBusy)

        # A change after the first completion read must not relabel A's models
        # with B's identity if completion reads the session again.
        from provider_types import ModelCatalog

        self.session.select_account("personal")
        self.settings._read_chatgpt_snapshot()
        generation = self.settings._provider_generations["chatgpt"]
        snapshot = self.session.snapshot
        reads = 0

        def change_after_snapshot():
            nonlocal reads
            value = snapshot()
            reads += 1
            if reads == 1:
                self.session.select_account("external-during-completion")
            return value

        with patch.object(self.session, "snapshot", side_effect=change_after_snapshot):
            self.settings._finish_provider_validation(
                "chatgpt",
                generation,
                True,
                {
                    "models": [],
                    "text_models": ["personal-only-model"],
                    "catalog": ModelCatalog(text_models=("personal-only-model",)),
                },
            )
        self.assertEqual(self.settings.chatgptTextCatalog, {})
        self.assertEqual(self.settings.routeModelOptions, [])
        self.assertFalse(
            self.settings.savePreference("setRouteModelId", ["personal-only-model"])
        )


if __name__ == "__main__":
    unittest.main()
