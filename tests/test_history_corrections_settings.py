"""Real Settings/history/library bridge with temporary profiles and fake sync."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from clarify_account import AccountDictionaryRepository, AccountService
from clarify.desktop.qml_settings import QmlSettingsController
from clarify.desktop.qml_web_settings import SettingsProtocol
from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippetService,
    LocalDictionarySnippetsRepository,
)
from history_store import HistoryRecord
from local_asr_product import LocalASRProductState
from microphone_controls import MicrophoneInventory
from secret_store import PlaintextFileSecretStore
from test_pyside6_qml_settings import _repositories


class FakeTimer:
    def __init__(self):
        self.active = False
        self.starts = []

    def isActive(self):
        return self.active

    def start(self, delay):
        self.active = True
        self.starts.append(delay)

    def stop(self):
        self.active = False


class HistoryCorrectionSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.request = Mock(side_effect=AssertionError("Unexpected network access"))
        self.account = AccountService(
            self.root,
            request=self.request,
            secrets=PlaintextFileSecretStore(self.root / "test-secrets.json"),
            default_endpoint="https://clarify.example",
        )
        self.guest = LocalDictionarySnippetsRepository(self.root / "dictionary.json")
        self.dictionary = DictionarySnippetService(
            AccountDictionaryRepository(self.account, self.guest)
        )
        self.settings = QmlSettingsController(
            _repositories(self.root),
            account_service=self.account,
            dictionary_service=self.dictionary,
            microphone_inventory_source=Mock(
                snapshot=Mock(return_value=MicrophoneInventory.unavailable("test"))
            ),
            local_product=Mock(state=LocalASRProductState("missing"), busy=False),
        )
        self.addCleanup(self.settings.shutdown)
        self.timer = FakeTimer()
        self.settings._history_correction_sync = self.timer
        self.protocol = SettingsProtocol(self.settings)

    def call(self, action, payload):
        reply = self.protocol.dispatch(
            {"id": 1, "method": "historyCorrection", "args": [action, payload]}
        )
        self.assertNotIn("error", reply)
        return reply["result"]

    def signed_in(self):
        self.account._state.update(
            user_id="00000000-0000-4000-8000-000000000001", sync=True
        )
        self.account._generation += 1
        self.account.secrets.set("clarify_account", "isolated-session")
        self.settings._dictionary_draft = self.dictionary.reload()
        self.settings._dictionary_baseline = self.dictionary.state
        self.settings._snippet_draft_context = self.account.snippet_context()

    def preview(self, corrected="Clarify"):
        record = HistoryRecord(raw_text="We use clear if eye.")
        if self.account.scope:
            self.settings._history.append(record, self.account.history_identity())
        else:
            self.settings._history.local.enabled = True
            self.settings._history.local.append(record)
        scope = self.settings.historyState
        row = self.settings.getHistoryPage(scope["context"], "")["entries"][0]
        return self.call(
            "preview",
            {
                **scope,
                "id": row["id"],
                "libraryContext": self.settings.snippetContext,
                "heard": "clear if eye",
                "corrected": corrected,
            },
        )

    def test_bridge_review_confirm_and_undo_preserve_unrelated_drafts(self):
        proposal = self.preview()
        self.assertEqual(proposal["status"], "preview")
        self.assertFalse(self.guest.path.exists())
        self.settings.setDictionaryEntries(
            [DictionaryEntry("unsaved draft").to_mapping()]
        )
        result = self.call("confirm", {"token": proposal["token"]})
        self.assertTrue(result["canUndo"])
        self.assertEqual(
            self.guest.load().dictionary,
            (DictionaryEntry("Clarify", aliases=("clear if eye",)),),
        )
        self.assertCountEqual(
            [x.term for x in self.settings._dictionary_draft.dictionary],
            ["Clarify", "unsaved draft"],
        )
        self.assertEqual(
            self.call("undo", {"token": result["receipt"]})["status"], "undone"
        )
        self.assertEqual(
            [x.term for x in self.settings._dictionary_draft.dictionary],
            ["unsaved draft"],
        )
        self.request.assert_not_called()

    def test_managed_window_starts_once_polls_do_not_restart_and_undo_syncs(self):
        self.signed_in()
        result = self.call("confirm", {"token": self.preview()["token"]})
        self.assertTrue(result["canUndo"])
        self.assertEqual(self.timer.starts, [5000])
        for _ in range(3):
            self.assertTrue(
                self.call("status", {"token": result["receipt"]})["canUndo"]
            )
        self.assertEqual(self.timer.starts, [5000])
        with patch.object(self.settings, "_sync_library_preferences") as sync:
            self.assertEqual(
                self.call("undo", {"token": result["receipt"]})["status"], "undone"
            )
            sync.assert_called_once_with()
        self.assertFalse(self.timer.active)
        self.assertFalse(self.guest.path.exists())

    def test_managed_immediate_normal_sync_invalidates_receipt_without_losing_addition(
        self,
    ):
        self.signed_in()
        result = self.call("confirm", {"token": self.preview()["token"]})
        words = [x.to_mapping() for x in self.dictionary.state.dictionary]
        response = Mock(status_code=200, content=b"json")
        response.json.return_value = {"revision": 1, "entries": words}
        self.request.side_effect = None
        self.request.return_value = response
        self.account.sync_dictionary(self.dictionary)
        self.assertFalse(self.call("status", {"token": result["receipt"]})["canUndo"])
        self.assertEqual(
            self.call("undo", {"token": result["receipt"]})["status"],
            "undo_unavailable",
        )
        self.assertEqual(
            [x.term for x in self.dictionary.state.dictionary], ["Clarify"]
        )
        self.assertFalse(self.guest.path.exists())

    def test_timer_after_relogin_or_account_change_never_syncs_new_scope(self):
        self.signed_in()
        self.call("confirm", {"token": self.preview()["token"]})
        owned_path = self.dictionary.repository.path
        self.account._generation += 2
        with patch.object(self.settings, "_sync_library_preferences") as sync:
            self.settings._finish_history_correction_window()
            sync.assert_not_called()
        self.assertEqual(
            [
                x.term
                for x in LocalDictionarySnippetsRepository(owned_path).load().dictionary
            ],
            ["Clarify"],
        )

    def test_shutdown_preserves_scoped_pending_addition_and_stops_window(self):
        self.signed_in()
        self.call("confirm", {"token": self.preview()["token"]})
        path = self.dictionary.repository.path
        self.settings.shutdown()
        self.assertFalse(self.timer.active)
        self.assertEqual(
            LocalDictionarySnippetsRepository(path).load().dictionary[0].term, "Clarify"
        )

    def test_invalid_rpc_is_sanitized_and_old_history_scope_cannot_save(self):
        for args in (("preview", []), ("preview",), ("secret-must-not-echo", {})):
            result = self.protocol.dispatch(
                {"id": 1, "method": "historyCorrection", "args": list(args)}
            )
            self.assertNotIn("secret-must-not-echo", str(result))
        proposal = self.preview()
        self.account._generation += 1
        result = self.call("confirm", {"token": proposal["token"]})
        self.assertIn("A conta mudou", result["error"])
        self.assertEqual(self.guest.load().dictionary, ())
