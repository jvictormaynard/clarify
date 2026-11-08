"""Reusable qml text actions fixtures. This module defines no test cases."""

from pathlib import Path

from tempfile import TemporaryDirectory


from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from clarify.desktop.qml_settings import QmlSettingsController

from clarify.desktop.qml_web_settings import SettingsProtocol

from clarify_account import AccountService

from local_asr_product import LocalASRProductState

from microphone_controls import MicrophoneInventory


from secret_store import MemorySecretStore


from tests.support.settings import _repositories


class QmlTextActionFixture:
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.capture = Mock()
        self.applier = Mock()
        account = AccountService(
            self.directory,
            secrets=MemorySecretStore(),
            request=Mock(side_effect=AssertionError("Unexpected HTTP")),
        )
        self.provider = Mock()
        self.settings = QmlSettingsController(
            _repositories(str(self.directory)),
            account_service=account,
            local_product=Mock(state=LocalASRProductState("missing"), busy=False),
            microphone_inventory_source=Mock(
                snapshot=Mock(return_value=MicrophoneInventory.unavailable("fixture"))
            ),
            hotkey_applier=self.applier,
            hotkey_capture_changed=self.capture,
            text_action_provider=self.provider,
        )
        self.addCleanup(self.settings.shutdown)
        self.protocol = SettingsProtocol(self.settings)

    def request(self, method, *args):
        return self.protocol.dispatch({"id": 1, "method": method, "args": list(args)})
