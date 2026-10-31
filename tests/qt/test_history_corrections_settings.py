"""Real Settings/history/library bridge with temporary profiles and fake sync."""

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from clarify_account import AccountDictionaryRepository, AccountService
from clarify.desktop.qml_settings import QmlSettingsController
from clarify.desktop.qml_updates import QmlUpdateController
from clarify.desktop.qml_web_settings import SettingsProtocol
from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippetService,
    LocalDictionarySnippetsRepository,
    Snippet,
)
from history_store import HistoryRecord
from local_asr_product import LocalASRProductState
from microphone_controls import MicrophoneInventory
from secret_store import PlaintextFileSecretStore
from tests.support.settings import _repositories


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
            sync.assert_called_once_with(
                expected_identity=self.settings._history_correction_identity()
            )
        self.assertFalse(self.timer.active)
        self.assertFalse(self.guest.path.exists())

    def test_undo_releases_account_guard_before_processing_preflight(self):
        self.signed_in()
        result = self.call("confirm", {"token": self.preview()["token"]})
        processing_lock = threading.RLock()
        processing_locked = threading.Event()
        preflight_entered = threading.Event()
        publication_acquired = []

        def publish():
            # A processing callback can hold its own lock before taking the
            # account guard. The bounded probe detects an inverse lock order.
            with processing_lock:
                processing_locked.set()
                if not preflight_entered.wait(3):
                    return
                acquired = self.account._lock.acquire(timeout=1)
                publication_acquired.append(acquired)
                if acquired:
                    self.account._lock.release()

        def can_change():
            preflight_entered.set()
            with processing_lock:
                return False  # Active processing defers library synchronization.

        worker = threading.Thread(target=publish, daemon=True)
        worker.start()
        self.assertTrue(processing_locked.wait(3))
        self.settings._account_can_change = can_change
        try:
            undone = self.call("undo", {"token": result["receipt"]})
        finally:
            preflight_entered.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(undone["status"], "undone")
        self.assertEqual(
            publication_acquired,
            [True],
            "Publication must acquire the account guard during preflight",
        )
        self.request.assert_not_called()

    def test_undo_does_not_reserve_sync_after_preflight_changes_session(self):
        self.signed_in()
        result = self.call("confirm", {"token": self.preview()["token"]})

        def changed_session():
            self.account._generation += 1
            return True

        self.settings._account_can_change = changed_session
        with patch.object(self.account, "begin_change", return_value=False) as begin:
            undone = self.call("undo", {"token": result["receipt"]})
        self.assertEqual(undone["status"], "undone")
        begin.assert_not_called()
        self.request.assert_not_called()

    def test_normal_save_releases_account_guard_before_processing_preflight(self):
        self.signed_in()
        context = self.settings.snippetContext
        self.settings.setDictionaryEntries([DictionaryEntry("Saved term").to_mapping()])
        self.settings.setSnippets(
            [Snippet("saved", "Saved text").to_mapping()], context
        )
        processing_lock = threading.RLock()
        processing_locked = threading.Event()
        preflight_entered = threading.Event()
        publication_acquired = []

        def publish():
            with processing_lock:
                processing_locked.set()
                if not preflight_entered.wait(3):
                    return
                acquired = self.account._lock.acquire(timeout=1)
                publication_acquired.append(acquired)
                if acquired:
                    self.account._lock.release()

        def can_change():
            preflight_entered.set()
            with processing_lock:
                return False

        worker = threading.Thread(target=publish, daemon=True)
        worker.start()
        self.assertTrue(processing_locked.wait(3))
        self.settings._account_can_change = can_change
        try:
            saved = self.settings.save(context)
        finally:
            preflight_entered.set()
            worker.join(3)
        self.assertTrue(saved)
        self.assertFalse(worker.is_alive())
        self.assertEqual(publication_acquired, [True])
        self.assertEqual(
            self.dictionary.state.dictionary, (DictionaryEntry("Saved term"),)
        )
        self.assertEqual(
            self.dictionary.state.snippets, (Snippet("saved", "Saved text"),)
        )
        self.request.assert_not_called()

    def test_normal_save_revalidates_session_after_processing_preflight(self):
        self.signed_in()
        context = self.settings.snippetContext
        self.settings.setDictionaryEntries([DictionaryEntry("Saved term").to_mapping()])

        def changed_session():
            self.account._generation += 1
            return True

        self.settings._account_can_change = changed_session
        with patch.object(self.account, "begin_change", return_value=False) as begin:
            self.assertTrue(self.settings.save(context))
        begin.assert_not_called()
        self.assertEqual(
            self.dictionary.state.dictionary, (DictionaryEntry("Saved term"),)
        )
        self.request.assert_not_called()

    def test_preference_save_releases_account_guard_before_update_notification(self):
        self.signed_in()
        updates = QmlUpdateController(supported=False, automatic=True)
        self.addCleanup(updates.shutdown)
        updates._phase = "downloading"  # No transport or download worker is started.
        processing_lock = threading.RLock()
        processing_locked = threading.Event()
        notification_entered = threading.Event()
        publication_acquired = []
        config = self.settings.repositories.config

        def publish():
            with processing_lock:
                processing_locked.set()
                if not notification_entered.wait(3):
                    return
                acquired = self.account._lock.acquire(timeout=1)
                publication_acquired.append(acquired)
                if acquired:
                    self.account._lock.release()

        def refresh_processing():
            notification_entered.set()
            with processing_lock:
                pass

        def sync_updates():
            updates.setAutomatic(config.load().automatic_updates)

        updates.changed.connect(refresh_processing)
        self.settings.saved.connect(sync_updates)
        worker = threading.Thread(target=publish, daemon=True)
        worker.start()
        self.assertTrue(processing_locked.wait(3))
        try:
            saved = self.settings.savePreference("setAutomaticUpdates", [False])
        finally:
            notification_entered.set()
            worker.join(3)
            self.settings.saved.disconnect(sync_updates)
            updates.changed.disconnect(refresh_processing)
        self.assertTrue(saved)
        self.assertFalse(worker.is_alive())
        self.assertTrue(updates._cancel.is_set())
        self.assertEqual(publication_acquired, [True])
        self.request.assert_not_called()

    def test_deferred_undo_sync_cannot_follow_a_relogin_to_the_same_account(self):
        self.signed_in()
        result = self.call("confirm", {"token": self.preview()["token"]})
        self.settings._account_can_change = lambda: False
        self.assertEqual(
            self.call("undo", {"token": result["receipt"]})["status"], "undone"
        )
        self.assertTrue(self.settings._library_sync_pending)
        self.account._generation += 1
        self.settings._account_can_change = lambda: True
        with patch.object(self.account, "begin_change", return_value=False) as begin:
            self.settings._library_sync_timer.timeout.emit()
        begin.assert_not_called()
        self.assertFalse(self.settings._library_sync_pending)
        self.request.assert_not_called()

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

    def test_new_session_gets_its_own_window_while_old_timer_is_active(self):
        self.signed_in()
        self.call("confirm", {"token": self.preview()["token"]})
        old_identity = self.settings._history_correction_sync_context
        self.account._generation += 2
        self.call("confirm", {"token": self.preview("Second Term")["token"]})
        self.assertEqual(self.timer.starts, [5000, 5000])
        self.assertNotEqual(
            self.settings._history_correction_sync_context, old_identity
        )
        with patch.object(self.settings, "_sync_library_preferences") as sync:
            self.settings._finish_history_correction_window()
            sync.assert_called_once_with(
                expected_identity=self.settings._history_correction_identity()
            )

    def test_combined_draft_limit_is_checked_before_persistence(self):
        self.dictionary.replace(
            {"dictionary": [{"term": str(i)} for i in range(511)], "snippets": []}
        )
        self.settings._dictionary_draft = self.dictionary.state
        self.settings._dictionary_baseline = self.dictionary.state
        self.settings.setDictionaryEntries(
            [*self.settings.dictionaryEntries, DictionaryEntry("unsaved").to_mapping()]
        )
        proposal = self.preview()
        before = self.dictionary.repository.path.read_bytes()
        result = self.call("confirm", {"token": proposal["token"]})
        self.assertIn("alterações pendentes", result["error"])
        self.assertEqual(self.dictionary.repository.path.read_bytes(), before)
        self.assertEqual(len(self.settings.dictionaryEntries), 512)
        self.assertFalse(self.timer.active)

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
