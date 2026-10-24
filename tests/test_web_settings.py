"""The new frontend reuses the real settings controller, without exposing secrets."""

import json
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

try:
    from .test_pyside6_qml_settings import _repositories
except ImportError:  # unittest discovery imports test files as top-level modules.
    from test_pyside6_qml_settings import _repositories
from local_asr_product import LocalASRProductState
from clarify.desktop.qml_settings import QmlSettingsController
from clarify.desktop.qml_web_settings import SettingsProtocol


class WebSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.windows = patch(
            "clarify.desktop.qml_settings._is_windows", return_value=False
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
        if method == "setSnippets" and len(args) == 1:
            args = (*args, self.settings.snippetContext)
        return self.protocol.dispatch({"id": 7, "method": method, "args": list(args)})

    def test_snippet_draft_round_trip_and_invalid_edits_preserve_saved_text(self):
        entry = {
            "trigger": "minha assinatura",
            "replacement": "Nome\n  Equipe\n",
            "enabled": True,
            "case_sensitive": False,
        }
        self.assertEqual(self.request("snapshot")["result"]["snippets"], [])
        self.assertIn("result", self.request("setSnippets", [entry]))
        self.assertTrue(self.settings.dirty)
        self.assertEqual(self.settings._dictionary_service.state.snippets, ())
        self.assertIn("result", self.request("save"))
        self.assertEqual(
            self.settings._dictionary_service.expand("Minha assinatura."),
            entry["replacement"],
        )
        self.assertIn("error", self.request("setSnippets", [entry, entry]))
        self.assertEqual(self.request("snapshot")["result"]["snippets"], [entry])
        self.assertIn("result", self.request("setSnippets", []))
        self.assertIn("result", self.request("load"))
        self.assertEqual(self.request("snapshot")["result"]["snippets"], [entry])

    def test_snippet_draft_from_another_account_cannot_be_saved_to_guest(self):
        entry = {"trigger": "sig", "replacement": "Account only"}
        self.assertIn(
            "error", self.request("setSnippets", [entry], "stale-account-context")
        )
        self.assertEqual(self.settings._dictionary_service.state.snippets, ())
        self.assertFalse(self.settings.dirty)

    def test_native_pipe_accepts_full_guest_snippet_library_and_still_bounds_frames(
        self,
    ):
        from types import SimpleNamespace
        from clarify.desktop.qml_web_settings import WebSettingsProcess

        entries = [
            {"trigger": f"phrase {index}", "replacement": "é" * 4096}
            for index in range(256)
        ]
        payload = (
            json.dumps(
                {"id": 8, "method": "setSnippets", "args": [entries, "local"]},
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        self.assertGreater(len(payload), 1_048_576)
        process = Mock()
        process.readAllStandardOutput.return_value = payload
        host = SimpleNamespace(
            buffer=bytearray(),
            process=process,
            startup_timer=Mock(),
            protocol=self.protocol,
        )
        WebSettingsProcess._read(host)
        process.kill.assert_not_called()
        reply = json.loads(process.write.call_args.args[0])
        self.assertEqual(len(reply["result"]["snippets"]), 256)
        self.assertEqual(reply["result"]["snippets"][255]["replacement"], "é" * 4096)
        process.reset_mock()
        process.readAllStandardOutput.return_value = b"x" * 1025
        with patch("clarify.desktop.qml_web_settings.MAX_SETTINGS_MESSAGE_BYTES", 1024):
            WebSettingsProcess._read(host)
        process.kill.assert_called_once()
        process.write.assert_not_called()

    def account_library(self):
        import uuid
        from clarify_account import AccountDictionaryRepository
        from dictionary_snippets import (
            DictionarySnippetService,
            DictionarySnippets,
            Snippet,
        )

        guest = self.settings._dictionary_service.repository
        guest.save(DictionarySnippets(snippets=(Snippet("guest", "Guest text"),)))
        account = self.settings._account
        with account._lock:
            account._state.update(
                user_id=str(uuid.uuid4()), endpoint="https://first.example"
            )
            account._generation += 1
        service = DictionarySnippetService(AccountDictionaryRepository(account, guest))
        self.settings._dictionary_service = service
        self.settings._dictionary_draft = service.state
        self.settings._snippet_draft_context = self.settings.snippetContext
        return account, service, guest

    def test_revocation_after_initial_context_check_cannot_save_account_draft_as_guest(
        self,
    ):
        import threading

        account, service, guest = self.account_library()
        before_guest = guest.load()
        account_cache = account.snippet_path()
        before_config = self.settings.repositories.config.load()
        saved = Mock()
        self.settings.saved.connect(saved)
        self.assertIn(
            "result",
            self.request(
                "setSnippets", [{"trigger": "private", "replacement": "Account draft"}]
            ),
        )
        changed_language = "en" if self.settings.language != "en" else "pt"
        self.request("setLanguage", changed_language)
        checked, revoked = threading.Event(), threading.Event()

        def revoke():
            if not checked.wait(3):
                return
            with account._lock:
                account._state.pop("user_id", None)
                account._generation += 1
            revoked.set()

        worker = threading.Thread(target=revoke)
        worker.start()

        def after_initial_check():
            checked.set()
            self.assertTrue(revoked.wait(3))
            return True

        try:
            with patch.object(
                self.settings, "cancelHotkeyCapture", side_effect=after_initial_check
            ):
                self.assertFalse(self.settings.save())
        finally:
            checked.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(guest.load(), before_guest)
        self.assertFalse(account_cache.exists())
        self.assertEqual(self.settings.repositories.config.load(), before_config)
        saved.assert_not_called()

    def test_revocation_waits_until_failed_library_save_and_config_rollback_finish(
        self,
    ):
        import threading
        from dictionary_snippets import LocalDictionarySnippetsRepository
        import clarify.desktop.qml_settings as qml_settings

        account, service, guest = self.account_library()
        before_guest, before_library = guest.load(), service.state
        account_words = service.repository.path
        before_config = self.settings.repositories.config.load()
        self.request(
            "setSnippets", [{"trigger": "private", "replacement": "Account draft"}]
        )
        self.request("setDictionaryEntries", [{"term": "New word", "enabled": True}])
        self.request("setLanguage", "en" if self.settings.language != "en" else "pt")
        writing, revoke_attempted, revoked = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        rollback_had_account = []
        original_save = LocalDictionarySnippetsRepository.save
        original_apply = qml_settings._apply_config_with_autostart_transaction

        def persist(repository, state):
            if repository.path.name == "snippets.json":
                writing.set()
                self.assertTrue(revoke_attempted.wait(3))
                raise OSError("isolated persistence failure")
            return original_save(repository, state)

        def apply(config, *args):
            if config == before_config:
                rollback_had_account.append(
                    bool(account.scope) and not revoked.is_set()
                )
            return original_apply(config, *args)

        def revoke():
            if not writing.wait(3):
                return
            revoke_attempted.set()
            with account._lock:
                account._state.pop("user_id", None)
                account._generation += 1
            revoked.set()

        worker = threading.Thread(target=revoke)
        worker.start()
        saved = Mock()
        self.settings.saved.connect(saved)
        try:
            with (
                patch.object(LocalDictionarySnippetsRepository, "save", persist),
                patch.object(
                    qml_settings,
                    "_apply_config_with_autostart_transaction",
                    side_effect=apply,
                ),
            ):
                self.assertFalse(self.settings.save())
        finally:
            writing.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(rollback_had_account, [True])
        self.assertEqual(guest.load(), before_guest)
        self.assertEqual(self.settings.repositories.config.load(), before_config)
        self.assertEqual(service.state, before_library)
        self.assertEqual(
            LocalDictionarySnippetsRepository(account_words).load().dictionary,
            before_library.dictionary,
        )
        saved.assert_not_called()

    def test_reentrant_revocation_during_config_write_is_rechecked_before_library_save(
        self,
    ):
        import clarify.desktop.qml_settings as qml_settings

        account, service, guest = self.account_library()
        before_guest = guest.load()
        account_cache = account.snippet_path()
        before_config = self.settings.repositories.config.load()
        self.request(
            "setSnippets", [{"trigger": "private", "replacement": "Account draft"}]
        )
        self.request("setLanguage", "en" if self.settings.language != "en" else "pt")
        original_apply = qml_settings._apply_config_with_autostart_transaction

        def apply(config, *args):
            result = original_apply(config, *args)
            if config != before_config:
                with account._lock:
                    account._state.pop("user_id", None)
                    account._generation += 1
            return result

        saved = Mock()
        self.settings.saved.connect(saved)
        with patch.object(
            qml_settings, "_apply_config_with_autostart_transaction", side_effect=apply
        ):
            self.assertFalse(self.settings.save())
        self.assertEqual(guest.load(), before_guest)
        self.assertFalse(account_cache.exists())
        self.assertEqual(self.settings.repositories.config.load(), before_config)
        saved.assert_not_called()

    def test_snapshot_is_json_and_does_not_include_key(self):
        self.settings.selectProvider("openai")
        self.settings.setProviderApiKey("test-secret-never-render")
        response = self.request("snapshot")
        self.assertIn("result", response)
        serialized = json.dumps(response)
        self.assertNotIn("test-secret-never-render", serialized)
        self.assertNotIn("providerApiKey", serialized)
        self.assertEqual(response["id"], 7)

    def test_existing_history_is_visible_with_disabled_recording_and_delete_stays_local(
        self,
    ):
        from history_store import HistoryRecord, HistoryStore

        store = HistoryStore(
            self.settings._history.local.path, enabled=True, retention_days=None
        )
        record = HistoryRecord(raw_text="Isolated legacy record.")
        store.append(record)
        snapshot = self.request("snapshot")["result"]
        self.assertFalse(snapshot["historyEnabled"])
        context = snapshot["historyState"]["context"]
        page = self.request("getHistoryPage", context, "")["result"]
        self.assertEqual(page["entries"][0]["text"], "Isolated legacy record.")
        self.assertIn(
            "result",
            self.request("deleteHistoryEntry", page["entries"][0]["id"], context),
        )
        self.assertEqual(
            self.request("getHistoryPage", context, "")["result"]["entries"], []
        )

    def test_history_clear_removes_only_local_records_in_guest_mode(self):
        from history_store import HistoryRecord, HistoryStore

        store = HistoryStore(self.settings._history.local.path, enabled=True)
        store.append(HistoryRecord(raw_text="Local only."))
        with patch.object(self.settings._account, "request") as request:
            context = self.settings.historyState["context"]
            self.assertIn("result", self.request("clearHistory", context))
            self.assertEqual(
                self.request("getHistoryPage", context, "")["result"]["entries"], []
            )
            request.assert_not_called()

    def test_large_history_keeps_snapshots_small_and_pages_complete_without_duplicates(
        self,
    ):
        from history_store import HistoryRecord

        records = [
            HistoryRecord(raw_text=str(index) + "é" * 12000) for index in range(70)
        ]
        path = self.settings._history.local.path
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "records": [record.to_mapping() for record in records],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.assertGreater(path.stat().st_size, 1_048_576)
        with patch.object(
            self.settings._history,
            "list_items",
            side_effect=AssertionError("general snapshots must not load history"),
        ):
            snapshot = self.request("snapshot")
            self.assertLess(len(json.dumps(snapshot).encode()), 65536)
            self.assertNotIn("historyEntries", snapshot["result"])
        context = snapshot["result"]["historyState"]["context"]
        cursor, ids = "", []
        while True:
            reply = self.request("getHistoryPage", context, cursor)
            self.assertLess(len(json.dumps(reply).encode()), 128 * 1024)
            page = reply["result"]
            ids.extend(entry["id"] for entry in page["entries"])
            self.assertTrue(all(len(entry["text"]) <= 500 for entry in page["entries"]))
            if not page["hasMore"]:
                break
            cursor = page["cursor"]
        self.assertEqual(len(ids), 70)
        self.assertEqual(len(set(ids)), 70)

    def test_giant_legacy_text_is_preserved_and_available_in_bounded_parts(self):
        from history_store import HistoryRecord, HistoryStore

        original = "😀é" * 220000
        store = HistoryStore(
            self.settings._history.local.path, enabled=True, retention_days=None
        )
        store.append(HistoryRecord(raw_text=original))
        context = self.settings.historyState["context"]
        page = self.request("getHistoryPage", context, "")["result"]
        self.assertTrue(page["entries"][0]["truncated"])
        token, offset, parts = page["entries"][0]["id"], 0, []
        while True:
            reply = self.request("getHistoryTextPart", context, token, offset, "text")
            self.assertLess(len(json.dumps(reply).encode()), 65536)
            part = reply["result"]
            parts.append(part["text"])
            offset = part["nextOffset"]
            if not part["hasMore"]:
                break
        self.assertEqual("".join(parts), original)
        self.assertEqual(store.list_records()[0].raw_text, original)

    def test_history_rpc_rejects_malformed_values_and_stale_account_actions(self):
        from history_store import HistoryRecord, HistoryStore
        import uuid

        store = HistoryStore(self.settings._history.local.path, enabled=True)
        store.append(HistoryRecord(raw_text="Preserve guest."))
        context = self.settings.historyState["context"]
        page = self.request("getHistoryPage", context, "")["result"]
        token = page["entries"][0]["id"]
        for args in (
            (context,),
            (context, 0),
            (context, "../unsafe"),
            ("secret-must-not-echo", ""),
        ):
            reply = self.request("getHistoryPage", *args)
            self.assertIn("error", reply)
            self.assertNotIn("secret-must-not-echo", json.dumps(reply))
        self.assertIn(
            "error", self.request("getHistoryTextPart", context, token, True, "text")
        )
        self.settings._account._state["user_id"] = str(uuid.uuid4())
        self.settings._account._generation += 1
        self.assertIn("error", self.request("deleteHistoryEntry", token, context))
        self.assertIn("error", self.request("clearHistory", context))
        self.assertEqual(store.list_records()[0].raw_text, "Preserve guest.")

    def test_automatic_update_flag_is_an_optional_saved_draft(self):
        self.assertFalse(self.request("snapshot")["result"]["automaticUpdates"])
        state = self.request("setAutomaticUpdates", True)["result"]
        self.assertTrue(state["automaticUpdates"])
        self.assertTrue(state["dirty"])
        self.assertFalse(self.settings.repositories.config.load().automatic_updates)
        self.assertFalse(self.request("load")["result"]["automaticUpdates"])
        self.request("setAutomaticUpdates", True)
        self.assertFalse(self.request("save")["result"]["dirty"])
        self.assertTrue(self.settings.repositories.config.load().automatic_updates)
        self.assertIn("error", self.request("setAutomaticUpdates", "false"))
        self.assertTrue(self.settings.repositories.config.load().automatic_updates)

    def test_dictionary_draft_save_discard_and_validation(self):
        entry = {
            "term": "Eva Desktop",
            "aliases": ["Eva"],
            "pronunciation": "",
            "enabled": True,
        }
        state = self.request("setDictionaryEntries", [entry])["result"]
        self.assertTrue(state["dirty"])
        self.assertEqual(self.settings._dictionary_service.state.dictionary, ())
        self.assertEqual(self.request("load")["result"]["dictionaryEntries"], [])
        self.request("setDictionaryEntries", [entry])
        self.assertFalse(self.request("save")["result"]["dirty"])
        self.assertEqual(
            self.settings._dictionary_service.reload().dictionary[0].term, "Eva Desktop"
        )
        self.assertIn("error", self.request("setDictionaryEntries", [entry, entry]))
        self.assertEqual(
            self.request("snapshot")["result"]["dictionaryEntries"], [entry]
        )
        self.request("setDictionaryEntries", [])
        self.request("save")
        self.assertEqual(self.settings._dictionary_service.reload().dictionary, ())

    def test_failed_dictionary_save_keeps_draft_and_rolls_back_config(self):
        original = self.settings.repositories.config.load()
        self.request("setLanguage", "pt" if original.ui.language != "pt" else "en")
        self.request("setDictionaryEntries", [{"term": "Railway"}])
        with patch.object(
            self.settings._dictionary_service.repository,
            "save",
            side_effect=OSError("disk full"),
        ):
            self.assertIn("error", self.request("save"))
        self.assertTrue(self.settings.dirty)
        self.assertEqual(
            self.settings.repositories.config.load().ui.language, original.ui.language
        )
        self.assertEqual(self.settings._dictionary_service.state.dictionary, ())

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

    def test_advanced_recording_validates_and_persists_only_on_save(self):
        original = self.settings.repositories.config.load().recording_controls
        controls = self.settings.recordingControls
        controls["max_duration_seconds"] = 120
        controls["vad"]["enabled"] = True
        controls["vad"]["silence_duration_seconds"] = 1.5
        self.assertIn("result", self.request("setRecordingControls", controls))
        self.assertEqual(
            self.settings.repositories.config.load().recording_controls, original
        )
        self.assertIn("result", self.request("save"))
        persisted = self.settings.repositories.config.load().recording_controls
        self.assertEqual(persisted.max_duration_seconds, 120)
        self.assertEqual(persisted.vad.silence_duration_seconds, 1.5)
        controls["max_duration_seconds"] = -1
        self.assertIn("error", self.request("setRecordingControls", controls))
        self.assertEqual(self.settings.recordingControls["max_duration_seconds"], 120)

    def test_local_maintenance_uses_existing_controller(self):
        self.assertIn("result", self.request("removeLocalAsr"))
        self.settings._local_product.remove_async.assert_called_once()
        self.assertIn("result", self.request("setLocalStreaming", True))
        self.assertIn("result", self.request("resetAllHotkeys"))

    def test_window_close_does_not_open_legacy_settings(self):
        from types import SimpleNamespace
        from clarify.desktop.qml_web_settings import WebSettingsProcess

        bridge = SimpleNamespace(surface="settings", closeSettings=Mock())
        fallback = Mock()
        host = WebSettingsProcess(self.settings, bridge, fallback)
        capture_changed = Mock()
        self.settings._hotkey_capture_changed = capture_changed
        self.request("beginHotkeyCapture", "recording_hotkey")
        host._finished(0, None)
        self.assertEqual(self.settings.hotkeyCaptureAction, "")
        self.assertEqual(capture_changed.call_args_list, [((True,),), ((False,),)])
        fallback.assert_not_called()
        self.assertIn("error", self.request("openLegacy"))
        bridge.closeSettings.assert_called_once()
        host._failed(None)
        self.assertTrue(host.failed)
        self.assertFalse(host.show())

    def test_settings_request_only_activates_on_explicit_open(self):
        from types import SimpleNamespace
        from workflows import WorkflowState
        from clarify.desktop.qml_bridge import QmlWorkflowBridge

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
