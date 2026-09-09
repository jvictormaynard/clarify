"""The new frontend reuses the real settings controller, without exposing secrets."""

import json
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication

try:
    from .test_pyside6_qml_settings import _repositories
except ImportError:  # unittest discovery imports test files as top-level modules.
    from test_pyside6_qml_settings import _repositories
from local_asr_product import LocalASRProductState
from spikes.pyside6.qml_settings import QmlSettingsController
from spikes.pyside6.qml_web_settings import SettingsProtocol


class WebSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.windows = patch(
            "spikes.pyside6.qml_settings._is_windows", return_value=False
        )
        self.windows.start()
        self.addCleanup(self.windows.stop)
        self.directory = TemporaryDirectory()
        self.settings = QmlSettingsController(
            _repositories(self.directory.name),
            local_product=Mock(state=LocalASRProductState("missing"), busy=False),
        )
        self.protocol = SettingsProtocol(self.settings)

    def tearDown(self):
        self.settings.shutdown()
        self.directory.cleanup()

    def request(self, method, *args):
        return self.protocol.dispatch({"id": 7, "method": method, "args": list(args)})

    def test_snapshot_is_json_and_does_not_include_key(self):
        self.settings.selectProvider("openai")
        self.settings.setProviderApiKey("test-secret-never-render")
        response = self.request("snapshot")
        self.assertIn("result", response)
        serialized = json.dumps(response)
        self.assertNotIn("test-secret-never-render", serialized)
        self.assertNotIn("providerApiKey", serialized)
        self.assertEqual(response["id"], 7)

    def test_draft_save_and_discard_use_repository(self):
        original = self.settings.language
        choice = "pt" if original != "pt" else "en"
        self.assertTrue(self.request("setLanguage", choice)["result"]["dirty"])
        self.assertEqual(self.settings.repositories.config.load().ui.language, original)
        self.assertFalse(self.request("load")["result"]["dirty"])
        self.assertEqual(self.settings.language, original)
        self.request("setLanguage", choice)
        self.assertFalse(self.request("save")["result"]["dirty"])
        self.assertEqual(self.settings.repositories.config.load().ui.language, choice)

    def test_rejects_reflection_malformed_values_and_provider_draft_save(self):
        for method in (
            "shutdown",
            "deleteLater",
            "repositories",
            "providerApiKey",
            "__getattribute__",
        ):
            self.assertIn("error", self.request(method))
        self.assertIn("error", self.protocol.dispatch([]))
        self.assertIn("error", self.request("setLanguage", "not-a-language"))
        self.settings.selectProvider("openai")
        self.settings.setProviderApiKey("test-secret")
        self.assertIn("error", self.request("save"))

    def test_route_changes_do_not_download_models(self):
        self.request("selectWorkflow", "transcription")
        self.request("setRouteProviderId", "local_asr")
        result = self.request("setRouteModelId", "ggml-medium")
        self.assertEqual(result["result"]["routeModelId"], "ggml-medium")
        self.settings._local_product.install.assert_not_called()

    def test_cached_or_unconfigured_catalog_is_not_an_rpc_error(self):
        self.assertIn("result", self.request("loadRouteModels"))
        self.assertIn("result", self.request("refreshRouteModels"))

    def test_window_fallback_and_advanced_handoff_keep_bridge_consistent(self):
        from types import SimpleNamespace
        from spikes.pyside6.qml_web_settings import WebSettingsProcess

        bridge = SimpleNamespace(surface="settings", closeSettings=Mock())
        fallback = Mock()
        host = WebSettingsProcess(self.settings, bridge, fallback)
        host.handoff = True
        host._finished(0, None)
        fallback.assert_called_once()
        bridge.closeSettings.assert_not_called()
        host.handoff = False
        host._finished(0, None)
        bridge.closeSettings.assert_called_once()
        host._failed(None)
        self.assertTrue(host.failed)
        self.assertFalse(host.show())

    def test_settings_request_only_activates_on_explicit_open(self):
        from types import SimpleNamespace
        from workflows import WorkflowState
        from spikes.pyside6.qml_bridge import QmlWorkflowBridge

        bridge = QmlWorkflowBridge(
            SimpleNamespace(state=WorkflowState(), subscribe=lambda cb: None)
        )
        requested = Mock()
        bridge.settingsRequested.connect(requested)
        bridge.openSettings()
        bridge._notify_all()
        requested.assert_called_once()
        bridge.openSettings()
        self.assertEqual(requested.call_count, 2)


if __name__ == "__main__":
    unittest.main()
