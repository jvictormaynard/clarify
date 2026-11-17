"""Setup verifies assets before it saves a personal route, without signing out."""

import json
import time
import unittest
from unittest.mock import Mock, patch

from tests.support.qml_text_actions import QmlTextActionFixture


class PersonalSetupTests(QmlTextActionFixture, unittest.TestCase):
    def test_cpu_only_models_cannot_select_gpu_or_run_gpu_measurement(self):
        settings = self.settings
        settings._local_devices = [
            {"id": "auto", "label": "Automatic"},
            {"id": "cpu", "label": "CPU"},
            {"id": "cuda:0", "label": "Fixture GPU"},
        ]
        for model in (
            "parakeet-v3-int8",
            "granite-5-turboctc",
            "nemotron-3.5-streaming",
        ):
            with self.subTest(model=model):
                settings._local_profile = model
                settings._local_device = "cpu"
                self.assertEqual(settings.localDevices, ["CPU"])
                self.assertEqual(settings.localDeviceIndex, 0)
                self.assertFalse(settings.selectLocalDevice(1))
                self.assertFalse(settings.measureLocalDevice())
        settings._local_profile = "ggml-turbo-q5"
        self.assertTrue(settings.localSupportsGpu)
        self.assertEqual(settings.localDevices, ["Automatic", "CPU", "Fixture GPU"])

    def test_recommendation_does_not_promote_unaccepted_models_or_rewrite_saved_route(
        self,
    ):
        settings = self.settings
        before = settings._config_repository.load()
        installer = Mock()
        installer.requirements.return_value = {"download_bytes": 123}
        installer.status.return_value = {"state": "missing"}
        with (
            patch("local_asr_catalog.installer_for", return_value=installer),
            patch("os.cpu_count", return_value=16),
        ):
            self.assertTrue(settings.personalSetupCommand("recommend"))
            self.wait_setup()
        recommendation = settings.personalSetupState["recommendation"]
        self.assertEqual(recommendation["modelId"], "ggml-base")
        self.assertEqual(
            recommendation["requirementsList"][0], "123 B maximum download"
        )
        self.assertEqual(settings._config_repository.load(), before)

    def test_switching_setup_service_clears_error_without_changing_saved_choices(self):
        settings = self.settings
        original = settings._config_repository.load()
        settings._personal_setup["error"] = "Previous service failed."
        settings.selectProvider("openai")
        settings.setProviderApiKey("fixture-unsaved-key")
        settings.setProviderBaseUrl("https://fixture.invalid/v1")
        self.assertTrue(settings.providerDirty)
        self.assertTrue(settings.personalSetupCommand("reset_text_choice"))
        self.assertEqual(settings.personalSetupState["error"], "")
        self.assertFalse(settings.providerDirty)
        self.assertEqual(settings._config_repository.load(), original)

    def wait_setup(self):
        deadline = time.monotonic() + 3
        while self.settings._personal_setup["busy"] and time.monotonic() < deadline:
            self.app.processEvents()
            self.settings._drain_background_publications()
            time.sleep(0.005)
        self.assertFalse(self.settings._personal_setup["busy"])

    def test_setup_reports_errors_and_completion_preserves_account(self):
        settings = self.settings
        original = settings._config_repository.load()
        options = {
            "language": "pt",
            "speechModelId": "ggml-base",
            "textProvider": "none",
            "textModelId": "",
        }
        installer = Mock()
        installer.status.return_value = {"state": "missing"}
        self.assertIn("personalSetupState", self.request("snapshot")["result"])
        self.assertFalse(
            settings.personalSetupCommand("complete", '{"textProvider":"clarify"}')
        )
        with patch("local_asr_catalog.installer_for", return_value=installer):
            self.assertTrue(
                settings.personalSetupCommand("complete", json.dumps(options))
            )
            self.wait_setup()
            self.assertIn("Install", settings.personalSetupState["error"])
            self.assertEqual(settings._config_repository.load(), original)
            installer.status.return_value = {"state": "installed"}
            with patch.object(settings._account, "logout") as sign_out:
                self.assertTrue(
                    settings.personalSetupCommand("complete", json.dumps(options))
                )
                self.wait_setup()
                self.assertEqual(settings.personalSetupState["error"], "")
                sign_out.assert_not_called()
        saved = settings._config_repository.load()
        self.assertEqual(saved.ui.language, original.ui.language)
        self.assertEqual(saved.recognition_language, "pt")
        self.assertEqual(
            type(saved).from_mapping(saved.to_mapping()).recognition_language, "pt"
        )
        self.assertTrue(saved.onboarding_completed)
        self.assertEqual(saved.workflow("transcription").model_id, "ggml-base")
        for scope in ("refinement", "local_asr_refinement", "rewrite", "translation"):
            self.assertFalse(saved.workflow(scope).enabled)

    def test_cancel_discards_late_discovery_and_exposes_personal_routes(self):
        settings = self.settings
        before = settings._config_repository.load()
        settings._personal_setup_generation = 1
        self.assertTrue(settings.personalSetupCommand("cancel"))
        settings._finish_personal_setup(1, ("recommend", {"modelId": "stale"}, ""))
        self.assertNotEqual(
            settings.personalSetupState["recommendation"]["modelId"], "stale"
        )
        self.assertEqual(settings._config_repository.load(), before)
        self.assertTrue(
            {"none", "chatgpt", "opencode"}
            <= {x["id"] for x in settings.personalSetupState["textOptions"]}
        )

    def test_configure_waits_for_browse_verification_before_install(self):
        import threading

        settings = self.settings
        entered = threading.Event()
        released = threading.Event()

        class Product:
            started = False
            cancel = Mock()
            unsubscribe = Mock()
            shutdown = Mock()

            @property
            def busy(self):
                if not self.started:
                    return False
                entered.set()
                return not released.is_set()

            install_async = Mock()

        product = Product()
        settings._local_product = product

        def browse(*args):
            product.started = True
            return True

        with patch.object(settings, "_browse_local", side_effect=browse):
            self.assertTrue(
                settings.personalSetupCommand(
                    "configure", '{"speechModelId":"ggml-base"}'
                )
            )
            self.assertTrue(entered.wait(1))
            product.install_async.assert_not_called()
            self.assertFalse(settings.personalSetupCommand("recommend"))
            released.set()
            self.wait_setup()
            product.install_async.assert_called_once()

    def test_local_endpoint_is_explicit_and_catalog_keeps_selected_model(self):
        settings = self.settings
        for endpoint, allowed in [
            ("http://127.0.0.1:8080/v1", True),
            ("http://[::1]:8080/v1", True),
            ("http://localhost:8080/v1", True),
            ("https://api.openai.com/v1", False),
            ("http://192.168.1.1/v1", False),
            ("http://localhost.evil/v1", False),
            ("http://user@localhost/v1", False),
        ]:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(settings._personal_local_endpoint(endpoint), allowed)
        from dataclasses import replace

        settings._config = replace(
            settings._config,
            openai=replace(
                settings._config.openai, api_key="", base_url="http://127.0.0.1:8080/v1"
            ),
        )
        state = settings.providerStates["openai"]
        self.assertTrue(state["configured"])
        self.assertFalse(state["hasApiKey"])
        settings._config = replace(
            settings._config,
            openai=replace(
                settings._config.openai, base_url="https://api.openai.com/v1"
            ),
        )
        self.assertFalse(settings.providerStates["openai"]["configured"])
        settings._opencode_models = ("opencode/z-free", "opencode/a-free")
        option = next(
            o
            for o in settings.personalSetupState["textOptions"]
            if o["id"] == "opencode"
        )
        self.assertEqual(
            [m["id"] for m in option["models"]], list(settings._opencode_models)
        )
        self.assertEqual(option["modelId"], settings._config.opencode.text_model)
