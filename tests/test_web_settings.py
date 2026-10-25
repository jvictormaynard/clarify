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

    def test_preference_rpc_persists_controls_without_a_global_save(self):
        from dataclasses import replace

        cases = (
            ("setMode", ["transcription"], "mode", "prompt"),
            ("setLanguage", ["pt"], "language", "pt"),
            ("setAutostart", [True], "autostart", True),
            ("setHistoryEnabled", [True], "historyEnabled", True),
            ("setAutomaticUpdates", [True], "automaticUpdates", True),
            ("selectMicrophone", [None], "selectedMicrophoneId", None),
            ("setLocalStreaming", [True], "localStreaming", True),
            ("setLocalAsrCloudRefinement", [True], "localAsrCloudRefinement", True),
        )
        for method, args, key, expected in cases:
            with self.subTest(method=method):
                if method == "selectMicrophone":
                    repo = self.settings.repositories.config
                    config = repo.load()
                    repo.apply(
                        replace(
                            config,
                            microphone=replace(config.microphone, selected_id="old"),
                        )
                    )
                reply = self.request("savePreference", method, args)
                self.assertNotIn("error", reply)
                self.assertEqual(reply["result"][key], expected)
                self.assertFalse(reply["result"]["dirty"])
                self.assertEqual(self.request("load")["result"][key], expected)

    def test_preference_rpc_preserves_all_unrelated_drafts_and_context(self):
        repo = self.settings.repositories.config
        original = repo.load()
        self.request("selectWorkflow", "rewrite")
        self.request("setRoutePrompt", "Uncommitted prompt")
        self.request("setRouteCustomEndpoint", "not a valid endpoint draft")
        self.request("setHistoryRetentionDays", 77)
        self.request("setDictionaryEntries", [{"term": "Draft term"}])
        self.request("setSnippets", [{"trigger": "draft", "replacement": "Draft text"}])
        self.request("selectProvider", "openai")
        self.request("setProviderApiKey", "private-pending-key")
        self.request("setProviderBaseUrl", "https://draft.example/v1")
        context = self.settings._snippet_draft_context
        account_before = self.settings.accountState

        reply = self.request("savePreference", "setAutomaticUpdates", [True])

        self.assertNotIn("error", reply)
        state = reply["result"]
        self.assertTrue(state["automaticUpdates"])
        self.assertTrue(state["dirty"])
        self.assertTrue(state["providerDirty"])
        self.assertEqual(state["routePrompt"], "Uncommitted prompt")
        self.assertEqual(state["routeCustomEndpoint"], "not a valid endpoint draft")
        self.assertEqual(state["historyRetentionDays"], 77)
        self.assertEqual(state["snippets"][0]["replacement"], "Draft text")
        self.assertEqual(state["dictionaryEntries"][0]["term"], "Draft term")
        self.assertEqual(self.settings.providerApiKey, "private-pending-key")
        self.assertEqual(state["providerBaseUrl"], "https://draft.example/v1")
        self.assertEqual(self.settings._snippet_draft_context, context)
        self.assertEqual(self.settings.accountState, account_before)
        from dataclasses import replace

        self.assertEqual(repo.load(), replace(original, automatic_updates=True))
        self.assertEqual(self.settings._dictionary_service.state.snippets, ())
        self.assertNotIn("private-pending-key", json.dumps(reply))
        self.assertTrue(self.request("load")["result"]["automaticUpdates"])

    def test_preference_rpc_changes_only_selected_route_fields(self):
        self.request("selectWorkflow", "rewrite")
        repo = self.settings.repositories.config
        original = repo.load()
        self.request("setRoutePrompt", "Pending rewrite prompt")
        self.request("setRouteCustomEndpoint", "https://pending.example/v1")
        self.request("setRouteModelId", "draft-only-model")
        state = self.request("savePreference", "setRouteEnabled", [False])["result"]
        self.assertFalse(state["routeEnabled"])
        route = repo.load().workflow("rewrite")
        self.assertEqual(route.prompt, original.workflow("rewrite").prompt)
        self.assertEqual(
            route.custom_endpoint, original.workflow("rewrite").custom_endpoint
        )
        self.assertEqual(route.model_id, original.workflow("rewrite").model_id)
        self.assertEqual(state["routeModelId"], "draft-only-model")
        state = self.request("savePreference", "setRouteProviderId", ["groq"])["result"]
        self.assertEqual(repo.load().workflow("rewrite").provider_id, "groq")
        self.assertNotEqual(
            repo.load().workflow("rewrite").model_id, "draft-only-model"
        )
        self.assertEqual(state["routePrompt"], "Pending rewrite prompt")
        self.assertEqual(state["routeCustomEndpoint"], "https://pending.example/v1")
        state = self.request("savePreference", "setRouteModelId", ["custom-model"])[
            "result"
        ]
        self.assertEqual(repo.load().workflow("rewrite").model_id, "custom-model")
        self.assertEqual(state["routePrompt"], "Pending rewrite prompt")
        self.assertTrue(state["dirty"])
        self.assertTrue(repo.load().workflow("rewrite").independent)
        self.assertEqual(
            repo.load().workflow("translation"), original.workflow("translation")
        )

    def test_preference_rpc_vad_switch_keeps_numeric_recording_draft(self):
        original = self.settings.repositories.config.load().recording_controls
        self.request(
            "setRecordingControls",
            {
                "max_duration_seconds": 120,
                "vad": {"enabled": False, "silence_duration_seconds": 1.5},
            },
        )
        state = self.request("savePreference", "setRecordingVadEnabled", [True])[
            "result"
        ]
        saved = self.settings.repositories.config.load().recording_controls
        self.assertTrue(saved.vad.enabled)
        self.assertEqual(saved.max_duration_seconds, original.max_duration_seconds)
        self.assertEqual(
            saved.vad.silence_duration_seconds, original.vad.silence_duration_seconds
        )
        self.assertEqual(state["recordingControls"]["max_duration_seconds"], 120)
        self.assertEqual(
            state["recordingControls"]["vad"]["silence_duration_seconds"], 1.5
        )
        self.assertTrue(state["dirty"])
        self.assertTrue(
            self.request("load")["result"]["recordingControls"]["vad"]["enabled"]
        )

    def test_preference_rpc_recomputes_dirty_and_uses_current_persisted_config(self):
        from dataclasses import replace

        repo = self.settings.repositories.config
        self.request("setLanguage", "pt")
        persisted = repo.load()
        repo.apply(replace(persisted, history_enabled=True))
        state = self.request("savePreference", "setLanguage", ["pt"])["result"]
        self.assertEqual(repo.load().ui.language, "pt")
        self.assertTrue(repo.load().history_enabled)
        self.request("load")
        self.request("setLanguage", "en")
        state = self.request("savePreference", "setLanguage", ["en"])["result"]
        self.assertFalse(state["dirty"])

    def test_preference_rpc_blocks_managed_personal_routes_but_allows_general_controls(
        self,
    ):
        self.settings._account._state["mode"] = "hosted"
        original = self.settings.repositories.config.load()
        for method, args in (
            ("setRouteProviderId", ["openai"]),
            ("setRouteModelId", ["custom"]),
            ("setRouteEnabled", [False]),
            ("setLocalStreaming", [True]),
            ("setLocalAsrCloudRefinement", [True]),
            ("useLocalAsr", []),
        ):
            with self.subTest(method=method):
                self.assertIn("error", self.request("savePreference", method, args))
                self.assertEqual(self.settings.repositories.config.load(), original)
        self.assertNotIn("error", self.request("savePreference", "setLanguage", ["pt"]))
        self.assertTrue(self.settings._account.managed)

    def test_preference_rpc_requires_an_explicit_method_and_typed_arguments(self):
        original = self.settings.repositories.config.load()
        for method, args in (
            ("save", []),
            ("load", []),
            ("deleteLater", []),
            ("setRoutePrompt", ["private-invalid-value"]),
            ("setProviderApiKey", ["private-invalid-value"]),
            ("setRecordingControls", [{}]),
            ("savePreference", ["save", []]),
            ("setLanguage", "pt"),
            ("setLanguage", ["pt", "extra"]),
            ("setLanguage", [{"private-invalid-value": True}]),
            ("setAutostart", ["private-invalid-value"]),
            ("setRecordingVadEnabled", [1]),
        ):
            with self.subTest(method=method, args=args):
                reply = self.request("savePreference", method, args)
                self.assertIn("error", reply)
                self.assertNotIn("private-invalid-value", json.dumps(reply))
                self.assertEqual(self.settings.repositories.config.load(), original)

    def test_library_preference_persists_only_flag_and_preserves_text_drafts(self):
        self.request("setDictionaryEntries", [{"term": "Saved term"}])
        self.request("setSnippets", [{"trigger": "saved", "replacement": "Saved text"}])
        saved = self.request("save")["result"]
        word, snippet = saved["dictionaryEntries"][0], saved["snippets"][0]
        self.request("setSnippets", [{**snippet, "replacement": "Pending text"}])
        self.request(
            "setDictionaryEntries", [{**word, "pronunciation": "Pending pronunciation"}]
        )
        self.request("setLanguage", "pt")
        self.request("selectProvider", "openai")
        self.request("setProviderApiKey", "private-pending-key")
        config_before = self.settings.repositories.config.load()
        context = saved["snippetContext"]
        self.assertEqual(saved["dictionaryContext"], context)

        for library, identity, field in (
            ("dictionary", word, "enabled"),
            ("snippets", snippet, "case_sensitive"),
        ):
            value = field == "case_sensitive"
            reply = self.request(
                "saveLibraryPreference", library, identity, field, value, context
            )
            self.assertNotIn("error", reply)
            self.assertNotIn("private-pending-key", json.dumps(reply))
        persisted = self.settings._dictionary_service.state
        self.assertFalse(persisted.dictionary[0].enabled)
        self.assertEqual(persisted.dictionary[0].pronunciation, "")
        self.assertTrue(persisted.snippets[0].case_sensitive)
        self.assertEqual(persisted.snippets[0].replacement, "Saved text")
        self.assertEqual(
            self.settings.dictionaryEntries[0]["pronunciation"], "Pending pronunciation"
        )
        self.assertEqual(self.settings.snippets[0]["replacement"], "Pending text")
        self.assertEqual(self.settings.providerApiKey, "private-pending-key")
        self.assertEqual(self.settings.language, "pt")
        self.assertEqual(self.settings.repositories.config.load(), config_before)
        self.assertTrue(self.settings.dirty)
        self.request("load")
        self.assertFalse(self.settings.dictionaryEntries[0]["enabled"])
        self.assertTrue(self.settings.snippets[0]["case_sensitive"])

    def test_library_preference_rejects_stale_partial_new_and_invalid_identities(self):
        self.request("setSnippets", [{"trigger": "saved", "replacement": "Saved text"}])
        saved = self.request("save")["result"]
        identity, context = saved["snippets"][0], saved["snippetContext"]
        original = self.settings._dictionary_service.state
        for library, item, field, value, owner in (
            ("snippets", {"trigger": "saved"}, "enabled", False, context),
            (
                "snippets",
                {**identity, "replacement": "Pending text"},
                "enabled",
                False,
                context,
            ),
            ("snippets", {**identity, "trigger": "new"}, "enabled", False, context),
            ("snippets", identity, "replacement", False, context),
            ("dictionary", identity, "case_sensitive", True, context),
            ("snippets", identity, "enabled", "private-invalid-value", context),
            ("snippets", identity, "enabled", False, "other-account"),
            ("other", identity, "enabled", False, context),
        ):
            with self.subTest(library=library, field=field, item=item):
                reply = self.request(
                    "saveLibraryPreference", library, item, field, value, owner
                )
                self.assertIn("error", reply)
                self.assertNotIn("private-invalid-value", json.dumps(reply))
                self.assertEqual(self.settings._dictionary_service.state, original)
        self.assertIn(
            "result",
            self.request(
                "saveLibraryPreference", "snippets", identity, "enabled", False, context
            ),
        )
        # A repeated identity from before the flag change is stale too.
        self.assertIn(
            "error",
            self.request(
                "saveLibraryPreference", "snippets", identity, "enabled", True, context
            ),
        )

    def test_library_preference_failure_preserves_saved_state_and_retry(self):
        self.request("setDictionaryEntries", [{"term": "Saved term"}])
        state = self.request("save")["result"]
        word, context = state["dictionaryEntries"][0], state["dictionaryContext"]
        with patch.object(
            self.settings._dictionary_service.repository,
            "save",
            side_effect=OSError("disk full"),
        ):
            self.assertIn(
                "error",
                self.request(
                    "saveLibraryPreference",
                    "dictionary",
                    word,
                    "enabled",
                    False,
                    context,
                ),
            )
        self.assertTrue(self.settings._dictionary_service.state.dictionary[0].enabled)
        self.assertTrue(self.settings.dictionaryEntries[0]["enabled"])
        self.assertFalse(self.settings.dirty)
        state = self.request(
            "saveLibraryPreference", "dictionary", word, "enabled", False, context
        )["result"]
        self.assertFalse(state["dirty"])
        self.assertFalse(state["dictionaryEntries"][0]["enabled"])

    def test_library_preference_account_sync_keeps_drafts_and_guest_storage(self):
        import time
        from dictionary_snippets import DictionarySnippets, DictionaryEntry, Snippet

        account, service, guest = self.account_library()
        guest_before = guest.load()
        service.replace(
            DictionarySnippets(
                dictionary=(DictionaryEntry("Account term"),),
                snippets=(Snippet("account", "Account text"),),
            ),
            expected_context=self.settings.snippetContext,
        )
        self.request("load")
        identity = self.settings.snippets[0]
        context = self.settings.snippetContext
        self.request(
            "setSnippets", [{**identity, "replacement": "Pending account text"}]
        )
        self.request("setProviderApiKey", "private-pending-key")
        self.request("setLanguage", "pt")
        with patch.object(account, "sync_library") as sync:
            reply = self.request(
                "saveLibraryPreference", "snippets", identity, "enabled", False, context
            )
            self.assertIn("result", reply)
            deadline = time.monotonic() + 3
            while self.settings._account_busy and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.001)
            self.assertFalse(self.settings._account_busy)
            sync.assert_called_once_with(service)
        self.assertEqual(guest.load(), guest_before)
        self.assertFalse(service.state.snippets[0].enabled)
        self.assertEqual(service.state.snippets[0].replacement, "Account text")
        self.assertEqual(
            self.settings.snippets[0]["replacement"], "Pending account text"
        )
        self.assertEqual(self.settings.providerApiKey, "private-pending-key")
        self.assertEqual(self.settings.language, "pt")
        self.assertEqual(self.settings.snippetContext, context)
        self.assertEqual(self.settings.dictionaryContext, context)
        with account._lock:
            account._state["endpoint"] = "https://second.example"
        self.assertIn(
            "error",
            self.request(
                "saveLibraryPreference",
                "snippets",
                service.state.snippets[0].to_mapping(),
                "enabled",
                True,
                context,
            ),
        )
        self.assertEqual(guest.load(), guest_before)

    def test_library_preference_rejects_duplicate_persisted_identity(self):
        from types import SimpleNamespace
        from dictionary_snippets import Snippet

        item = Snippet("same", "Same text")
        with (
            patch.object(
                self.settings._dictionary_service,
                "reload",
                return_value=SimpleNamespace(snippets=(item, item)),
            ),
            patch.object(self.settings._dictionary_service, "replace") as persist,
        ):
            reply = self.request(
                "saveLibraryPreference",
                "snippets",
                item.to_mapping(),
                "enabled",
                False,
                self.settings.snippetContext,
            )
            self.assertIn("error", reply)
            persist.assert_not_called()

    def test_library_preference_defers_account_sync_until_workflow_finishes(self):
        import time
        from dictionary_snippets import DictionarySnippets, Snippet

        account, service, _ = self.account_library()
        service.replace(
            DictionarySnippets(snippets=(Snippet("account", "Account text"),)),
            expected_context=self.settings.snippetContext,
        )
        self.request("load")
        identity, context = self.settings.snippets[0], self.settings.snippetContext
        with (
            patch.object(account, "sync_library") as sync,
            patch.object(self.settings, "_account_can_change", return_value=False),
        ):
            self.assertIn(
                "result",
                self.request(
                    "saveLibraryPreference",
                    "snippets",
                    identity,
                    "enabled",
                    False,
                    context,
                ),
            )
            sync.assert_not_called()
            self.assertFalse(service.state.snippets[0].enabled)
        with patch.object(account, "sync_library") as sync:
            self.settings._library_sync_timer.setInterval(1)
            self.settings._library_sync_timer.start()
            deadline = time.monotonic() + 3
            while (
                self.settings._library_sync_pending or self.settings._account_busy
            ) and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.001)
            sync.assert_called_once_with(service)
            self.assertFalse(self.settings._account_busy)

    def test_preference_routes_remain_clean_after_canonical_storage(self):
        for scope in ("transcription", "refinement", "local_asr_refinement"):
            with self.subTest(scope=scope):
                self.request("selectWorkflow", scope)
                for method, args in (
                    ("setRouteProviderId", ["openai"]),
                    ("setRouteModelId", ["custom-model"]),
                    ("setRouteEnabled", [False]),
                ):
                    state = self.request("savePreference", method, args)["result"]
                    self.assertFalse(state["dirty"])
                self.request("load")

    def test_preference_model_default_and_alias_use_canonical_snapshot(self):
        self.request("savePreference", "setRouteProviderId", ["groq"])
        for value in ("Whisper Large V3", ""):
            with self.subTest(value=value):
                reply = self.request("savePreference", "setRouteModelId", [value])
                self.assertIn("result", reply)
                state = reply["result"]
                self.assertFalse(state["dirty"])
                saved = self.settings.repositories.config.load().workflow(
                    "transcription"
                )
                self.assertEqual(state["routeModelId"], saved.model_id)
                self.assertNotEqual(state["routeModelId"], value)

    def test_first_poll_is_full_and_unchanged_polls_are_empty(self):
        initial = self.request("snapshot")["result"]
        self.assertEqual(self.request("poll")["result"], initial)
        for _ in range(3):
            self.assertEqual(self.request("poll"), {"id": 7, "result": {}})
        # Explicit snapshots stay full and do not change the poll contract.
        self.assertEqual(self.request("snapshot")["result"], initial)

    def test_poll_reports_scalar_change_after_full_command_response(self):
        self.request("poll")
        choice = "pt" if self.settings.language != "pt" else "en"
        command = self.request("setLanguage", choice)["result"]
        self.assertIn("snippets", command)
        self.assertEqual(
            self.request("poll")["result"], {"language": choice, "dirty": True}
        )
        self.assertEqual(self.request("poll")["result"], {})

    def test_level_only_poll_excludes_large_libraries(self):
        entries = [
            {"trigger": f"phrase {index}", "replacement": "x" * 4096}
            for index in range(512)
        ]
        self.assertIn("result", self.request("setSnippets", entries))
        self.assertIn(
            "result", self.request("setDictionaryEntries", [{"term": "Clarify"}])
        )
        first = self.request("poll")["result"]
        self.assertEqual(len(first["snippets"]), 512)
        self.assertGreater(len(json.dumps(first)), 2_000_000)
        for level in (0.25, 0.5, 0.0):
            self.settings._microphone_test_level = level
            reply = self.request("poll")
            self.assertEqual(reply["result"], {"microphoneTestLevel": level})
            self.assertLess(len(json.dumps(reply)), 100)
        self.assertEqual(self.request("poll")["result"], {})

    def test_poll_propagates_library_drafts_and_discard(self):
        initial = self.request("poll")["result"]
        self.request("setSnippets", [{"trigger": "sig", "replacement": "Text"}])
        self.request("setDictionaryEntries", [{"term": "Clarify"}])
        current = self.request("snapshot")["result"]
        self.assertEqual(
            self.request("poll")["result"],
            {key: current[key] for key in ("snippets", "dictionaryEntries", "dirty")},
        )
        self.assertEqual(self.request("poll")["result"], {})
        self.request("load")
        self.assertEqual(
            self.request("poll")["result"],
            {key: initial[key] for key in ("snippets", "dictionaryEntries", "dirty")},
        )

    def test_poll_propagates_account_identity_and_context_changes(self):
        guest = self.request("poll")["result"]
        account, _, _ = self.account_library()
        signed_in = self.request("poll")["result"]
        self.assertNotEqual(signed_in["accountState"], guest["accountState"])
        self.assertNotEqual(signed_in["snippetContext"], guest["snippetContext"])
        with account._lock:
            account._state["endpoint"] = "https://second.example"
            account._generation += 1
        changed = self.request("poll")["result"]
        self.assertEqual(changed["accountState"]["endpoint"], "https://second.example")
        self.assertNotEqual(changed["snippetContext"], signed_in["snippetContext"])
        self.assertEqual(self.request("poll")["result"], {})

    def test_ignored_command_response_cannot_consume_future_poll_delta(self):
        self.request("poll")
        self.settings._microphone_test_level = 0.75
        self.assertIn("snippets", self.request("loadRouteModels")["result"])
        self.assertEqual(self.request("poll")["result"], {"microphoneTestLevel": 0.75})

    def test_poll_restores_values_that_revert_after_a_full_reply(self):
        # A command can expose transient state (for example account busy).
        # Its completion must reach React even when it matches the last poll.
        for method in ("snapshot", "loadRouteModels"):
            with self.subTest(method=method):
                self.request("poll")
                self.settings._microphone_test_level = 0.75
                full = self.request(method)["result"]
                self.assertEqual(full["microphoneTestLevel"], 0.75)
                self.settings._microphone_test_level = 0.0
                self.assertEqual(
                    self.request("poll")["result"], {"microphoneTestLevel": 0.0}
                )
                self.assertEqual(self.request("poll")["result"], {})

    def test_poll_includes_computed_provider_list_when_scope_changes(self):
        initial = self.request("poll")["result"]
        self.assertIn("result", self.request("selectWorkflow", "refinement"))
        delta = self.request("poll")["result"]
        self.assertEqual(delta["selectedScope"], "refinement")
        self.assertNotEqual(delta["routeProviders"], initial["routeProviders"])
        self.assertIn("local_asr", [item["id"] for item in initial["routeProviders"]])
        self.assertNotIn("local_asr", [item["id"] for item in delta["routeProviders"]])

    def test_poll_retains_only_one_previous_snapshot(self):
        import gc
        import weakref

        class TrackedSnapshot(dict):
            pass

        references = []

        def snapshot():
            state = TrackedSnapshot(microphoneTestLevel=len(references) / 10)
            references.append(weakref.ref(state))
            return state

        # This private resource invariant cannot be proved from JSON replies.
        with patch.object(self.protocol, "snapshot", side_effect=snapshot):
            for _ in range(20):
                self.assertIn("result", self.request("poll"))
        gc.collect()
        self.assertEqual(sum(reference() is not None for reference in references), 1)
        self.assertIsNotNone(references[-1]())

    def test_failed_poll_does_not_advance_baseline(self):
        self.request("poll")
        self.settings._microphone_test_level = 0.5
        with patch.object(self.protocol, "snapshot", side_effect=RuntimeError()):
            self.assertIn("error", self.request("poll"))
        self.assertEqual(self.request("poll")["result"], {"microphoneTestLevel": 0.5})

    def test_poll_rejects_arguments_and_keeps_property_allowlist(self):
        self.request("poll")
        self.settings._microphone_test_level = 0.5
        for request in (
            {"method": "poll", "args": ["secret-must-not-echo"]},
            {"method": "poll", "args": {}},
            {"method": "poll", "args": [None] * 9},
            {"method": "snapshot", "args": ["providerApiKey"]},
            {"method": "__getattribute__", "args": ["providerApiKey"]},
        ):
            reply = self.protocol.dispatch(request)
            self.assertIn("error", reply)
            self.assertNotIn("secret-must-not-echo", json.dumps(reply))
        delta = self.request("poll")["result"]
        self.assertEqual(delta, {"microphoneTestLevel": 0.5})
        self.assertNotIn("providerApiKey", self.request("snapshot")["result"])

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
        self.settings._dictionary_baseline = service.state
        self.settings._snippet_draft_context = self.settings.snippetContext
        return account, service, guest

    def wait_for_account(self):
        import time

        deadline = time.monotonic() + 3
        while self.settings._account_busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertFalse(self.settings._account_busy)

    def test_library_context_rejects_dictionary_stage_during_and_after_logout(self):
        import threading

        account, service, guest = self.account_library()
        context, before = self.settings.snippetContext, guest.load()
        entered, release, finished = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def logout(**_kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("logout gate timed out")
            with account._lock:
                account._state.pop("user_id", None)
                account._generation += 1
            finished.set()

        with patch.object(account, "logout", side_effect=logout):
            self.assertIn("result", self.request("accountCommand", "logout", ""))
            try:
                self.assertTrue(entered.wait(3))
                for method, args in (
                    ("setDictionaryEntries", ([{"term": "Account only"}], context)),
                    (
                        "setSnippets",
                        ([{"trigger": "private", "replacement": "Text"}], context),
                    ),
                    ("save", (context,)),
                ):
                    self.assertIn("error", self.request(method, *args))
                release.set()
                self.assertTrue(finished.wait(3))
                # The worker changed scope but its queued Qt completion has
                # not yet reset the backend draft/context.
                self.assertIn("error", self.request("save", context))
                self.wait_for_account()
            finally:
                release.set()
                self.wait_for_account()
        self.assertEqual(self.settings.snippetContext, "local")
        self.assertIn(
            "error",
            self.request("setDictionaryEntries", [{"term": "Account only"}], context),
        )
        self.request("setLanguage", "pt")
        config = self.settings.repositories.config.load()
        self.assertIn("error", self.request("save", context))
        self.assertEqual(self.settings.repositories.config.load(), config)
        self.assertEqual(service.state, before)
        self.assertEqual(guest.load(), before)

    def test_library_context_commit_keeps_captured_token_after_draft_reset(self):
        account, _service, guest = self.account_library()
        context, before = self.settings.snippetContext, guest.load()
        config = self.settings.repositories.config.load()

        def finish_logout():
            with account._lock:
                account._state.pop("user_id", None)
                account._generation += 1
            self.settings._finish_account("")
            return True

        with patch.object(
            self.settings, "cancelHotkeyCapture", side_effect=finish_logout
        ):
            self.assertIn("error", self.request("save", context))
        self.assertEqual(guest.load(), before)
        self.assertEqual(self.settings.repositories.config.load(), config)

    def test_library_context_rpc_optional_arguments_are_typed(self):
        context = self.settings.snippetContext
        self.assertIn(
            "result", self.request("setDictionaryEntries", [{"term": "word"}], context)
        )
        self.assertIn("result", self.request("save", context))
        for method, args in (
            ("setDictionaryEntries", ([], None)),
            ("setDictionaryEntries", ([], 7)),
            ("setDictionaryEntries", ([], "local", "extra")),
            ("save", (None,)),
            ("save", (False,)),
            ("save", ("local", "extra")),
        ):
            with self.subTest(method=method, args=args):
                self.assertIn("error", self.request(method, *args))
        self.assertEqual(
            self.settings._dictionary_service.state.dictionary[0].term, "word"
        )

    def test_library_context_load_uses_current_owner_storage_after_expiry(self):
        from dictionary_snippets import DictionarySnippets, DictionaryEntry

        account, service, guest = self.account_library()
        service.replace(
            DictionarySnippets(dictionary=(DictionaryEntry("Account only"),)),
            expected_context=self.settings.snippetContext,
        )
        self.request("load")
        with account._lock:
            account._state.pop("user_id", None)
            account._state["mode"] = "hosted"
            account._generation += 1
        before_guest = guest.load()
        self.assertTrue(account.managed)
        self.assertIn("result", self.request("load"))
        self.assertIn("result", self.request("save", "local"))
        self.assertEqual(service.state, before_guest)
        self.assertEqual(guest.load(), before_guest)

    def test_library_context_expected_rows_reject_sync_between_snapshot_and_stage(self):
        import threading
        from dataclasses import replace
        from dictionary_snippets import DictionarySnippets, DictionaryEntry, Snippet

        account, service, guest = self.account_library()
        guest_before = guest.load()
        context = self.settings.snippetContext
        for method, key, field in (
            ("setDictionaryEntries", "dictionaryEntries", "pronunciation"),
            ("setSnippets", "snippets", "replacement"),
        ):
            with self.subTest(method=method):
                service.replace(
                    DictionarySnippets(
                        dictionary=(DictionaryEntry("A"),),
                        snippets=(Snippet("a", "A"),),
                    ),
                    expected_context=context,
                )
                self.request("load")
                entered, release, imported, finish = (
                    threading.Event(),
                    threading.Event(),
                    threading.Event(),
                    threading.Event(),
                )

                def sync(library):
                    entered.set()
                    if not release.wait(3):
                        raise AssertionError("sync gate timed out")
                    library.replace(
                        replace(
                            library.state,
                            dictionary=(
                                *library.state.dictionary,
                                DictionaryEntry("B"),
                            ),
                            snippets=(*library.state.snippets, Snippet("b", "B")),
                        ),
                        expected_context=context,
                    )
                    library.reload()
                    imported.set()
                    if not finish.wait(3):
                        raise AssertionError("completion gate timed out")

                with patch.object(account, "sync_library", side_effect=sync):
                    self.settings._sync_library_preferences()
                    try:
                        self.assertTrue(entered.wait(3))
                        snapshot = self.request("snapshot")["result"]
                        expected = snapshot[key]
                        self.assertIn(
                            "result",
                            self.request(
                                method,
                                [{**expected[0], field: "Earlier pending draft"}],
                                context,
                            ),
                        )
                        draft_before = self.settings._dictionary_draft
                        baseline_before = self.settings._dictionary_baseline
                        release.set()
                        self.assertTrue(imported.wait(3))
                        reply = self.request(
                            method,
                            [{**expected[0], field: "Attempted stale edit"}],
                            context,
                            expected,
                        )
                        self.assertEqual(
                            reply.get("error"),
                            "A biblioteca mudou. Atualize e tente novamente.",
                        )
                        self.assertEqual(self.settings._dictionary_draft, draft_before)
                        self.assertEqual(
                            self.settings._dictionary_baseline, baseline_before
                        )
                        self.assertEqual(len(service.state.dictionary), 2)
                        self.assertEqual(len(service.state.snippets), 2)
                    finally:
                        release.set()
                        finish.set()
                        self.wait_for_account()
                # A fresh comparison stages the complete merged rows normally.
                fresh = self.request("load")["result"][key]
                updated = [{**fresh[0], field: "Fresh pending edit"}, fresh[1]]
                self.assertIn("result", self.request(method, updated, context, fresh))
                with patch.object(self.settings, "accountCommand", return_value=True):
                    self.assertIn("result", self.request("save", context))
                self.assertEqual(len(service.reload().dictionary), 2)
                self.assertEqual(len(service.state.snippets), 2)
        self.assertEqual(guest.load(), guest_before)

    def test_library_context_expected_rows_malformed_rpc_and_direct_values_are_rejected(
        self,
    ):
        for method, key, entries in (
            ("setDictionaryEntries", "dictionaryEntries", [{"term": "A"}]),
            ("setSnippets", "snippets", [{"trigger": "a", "replacement": "A"}]),
        ):
            with self.subTest(method=method):
                self.assertIn("result", self.request(method, entries, "local", []))
                self.assertIn("result", self.request("save", "local"))
                expected = self.request("snapshot")["result"][key]
                malformed_values = (
                    None,
                    {},
                    "private-invalid-value",
                    [None],
                    [{**expected[0], "enabled": 1}],
                    [{**expected[0], "unexpected": True}],
                    [expected[0], expected[0]],
                )
                before = self.settings._dictionary_draft
                for malformed in malformed_values:
                    with self.subTest(expected=malformed):
                        reply = self.request(method, [], "local", malformed)
                        self.assertIn("error", reply)
                        self.assertNotIn("private-invalid-value", json.dumps(reply))
                        self.assertFalse(
                            getattr(self.settings, method)([], "local", malformed)
                        )
                        self.assertEqual(self.settings._dictionary_draft, before)
                self.assertIn("error", self.request(method, [], "local", expected, []))
                # Omission of the third argument keeps the original API.
                self.assertIn("result", self.request(method, [], "local"))
                self.request("load")

    def test_library_context_snapshot_does_not_label_stale_account_rows_as_guest(self):
        from dictionary_snippets import DictionarySnippets, DictionaryEntry, Snippet

        account, service, _guest = self.account_library()
        service.replace(
            DictionarySnippets(
                dictionary=(DictionaryEntry("Account only"),),
                snippets=(Snippet("private", "Account only"),),
            ),
            expected_context=self.settings.snippetContext,
        )
        self.request("load")
        with account._lock:
            account._state.pop("user_id", None)
            account._generation += 1
        # Expiry and logout can change the owner before a queued completion
        # reloads storage. Do not give these old rows a usable guest token.
        reply = self.request("snapshot")["result"]
        self.assertEqual(reply["snippetContext"], "local")
        self.assertEqual(reply["dictionaryEntries"], [])
        self.assertEqual(reply["snippets"], [])
        self.assertEqual(self.settings.dictionaryEntries[0]["term"], "Account only")

    def test_library_context_save_reply_keeps_row_order_before_late_sync(self):
        import threading
        from dataclasses import replace
        from dictionary_snippets import DictionaryEntry, Snippet

        account, service, _guest = self.account_library()
        context = self.settings.snippetContext
        self.request(
            "setDictionaryEntries", [{"term": "Zebra"}, {"term": "Alpha"}], context
        )
        self.request(
            "setSnippets",
            [
                {"trigger": "zebra", "replacement": "Z"},
                {"trigger": "alpha", "replacement": "A"},
            ],
            context,
        )
        entered, release = threading.Event(), threading.Event()

        def sync(library, **_kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("sync gate timed out")
            library.replace(
                replace(
                    library.state,
                    dictionary=(*library.state.dictionary, DictionaryEntry("B")),
                    snippets=(*library.state.snippets, Snippet("b", "B")),
                ),
                expected_context=context,
            )
            library.reload()

        with patch.object(account, "sync_library", side_effect=sync):
            try:
                reply = self.request("save", context)["result"]
                self.assertTrue(entered.wait(3))
                self.assertEqual(
                    [row["term"] for row in reply["dictionaryEntries"]],
                    ["Zebra", "Alpha"],
                )
                self.assertEqual(
                    [row["trigger"] for row in reply["snippets"]], ["zebra", "alpha"]
                )
                self.assertFalse(reply["dirty"])
            finally:
                release.set()
                self.wait_for_account()
        self.assertEqual(
            [row.term for row in service.state.dictionary], ["Zebra", "Alpha", "B"]
        )
        self.assertFalse(self.settings.dirty)

    def test_library_preference_sync_import_is_clean_and_survives_general_save(self):
        from dataclasses import replace
        from dictionary_snippets import DictionarySnippets, DictionaryEntry, Snippet

        account, service, guest = self.account_library()
        before_guest = guest.load()
        context = self.settings.snippetContext
        service.replace(
            DictionarySnippets(
                dictionary=(DictionaryEntry("A"),), snippets=(Snippet("a", "A"),)
            ),
            expected_context=context,
        )
        self.request("load")

        def sync(library):
            current = library.state
            library.replace(
                replace(
                    current,
                    dictionary=(*current.dictionary, DictionaryEntry("B")),
                    snippets=(*current.snippets, Snippet("b", "B")),
                ),
                expected_context=context,
            )
            library.reload()

        with patch.object(account, "sync_library", side_effect=sync):
            immediate = self.request(
                "saveLibraryPreference",
                "dictionary",
                self.settings.dictionaryEntries[0],
                "enabled",
                False,
                context,
            )["result"]
            self.assertEqual(
                [row["term"] for row in immediate["dictionaryEntries"]], ["A"]
            )
            self.wait_for_account()
        self.assertEqual(
            [row["term"] for row in self.settings.dictionaryEntries], ["A", "B"]
        )
        self.assertEqual([row["trigger"] for row in self.settings.snippets], ["a", "b"])
        self.assertFalse(self.settings.dirty)
        self.request("setLanguage", "pt")
        with patch.object(self.settings, "accountCommand", return_value=True):
            reply = self.request("save", context)
        self.assertIn("result", reply)
        self.assertFalse(reply["result"]["dirty"])
        self.assertEqual([row.term for row in service.reload().dictionary], ["A", "B"])
        self.assertEqual([row.trigger for row in service.state.snippets], ["a", "b"])
        self.assertEqual(guest.load(), before_guest)

    def test_library_preference_sync_merges_pending_rows_fields_and_late_flags(self):
        import threading
        from dictionary_snippets import DictionarySnippets, DictionaryEntry, Snippet

        account, service, _guest = self.account_library()
        context = self.settings.snippetContext
        service.replace(
            DictionarySnippets(
                dictionary=tuple(
                    DictionaryEntry(key) for key in ("A", "deleted", "remote-deleted")
                ),
                snippets=tuple(
                    Snippet(key, key) for key in ("a", "deleted", "remote-deleted")
                ),
            ),
            expected_context=context,
        )
        self.request("load")
        entered, release = threading.Event(), threading.Event()

        def sync(library):
            entered.set()
            if not release.wait(3):
                raise AssertionError("sync gate timed out")
            library.replace(
                DictionarySnippets(
                    dictionary=(
                        DictionaryEntry("A", aliases=("remote alias",), enabled=False),
                        DictionaryEntry("deleted"),
                        DictionaryEntry("B"),
                    ),
                    snippets=(
                        Snippet("a", "remote text", enabled=False, case_sensitive=True),
                        Snippet("deleted", "deleted"),
                        Snippet("b", "B"),
                    ),
                ),
                expected_context=context,
            )
            library.reload()

        with patch.object(account, "sync_library", side_effect=sync):
            self.assertIn(
                "result",
                self.request(
                    "saveLibraryPreference",
                    "dictionary",
                    self.settings.dictionaryEntries[0],
                    "enabled",
                    False,
                    context,
                ),
            )
            try:
                self.assertTrue(entered.wait(3))
                self.assertIn(
                    "result",
                    self.request(
                        "setDictionaryEntries",
                        [
                            {
                                **self.settings.dictionaryEntries[0],
                                "pronunciation": "pending",
                            },
                            self.settings.dictionaryEntries[2],
                            {"term": "new"},
                        ],
                        context,
                    ),
                )
                self.assertIn(
                    "result",
                    self.request(
                        "setSnippets",
                        [
                            {**self.settings.snippets[0], "replacement": "pending"},
                            self.settings.snippets[2],
                            {"trigger": "new", "replacement": "new"},
                        ],
                        context,
                    ),
                )
            finally:
                release.set()
                self.wait_for_account()
        words, snippets = self.settings.dictionaryEntries, self.settings.snippets
        self.assertEqual([row["term"] for row in words], ["A", "new", "B"])
        self.assertEqual(words[0]["pronunciation"], "pending")
        self.assertEqual(words[0]["aliases"], ["remote alias"])
        self.assertFalse(words[0]["enabled"])
        self.assertEqual([row["trigger"] for row in snippets], ["a", "new", "b"])
        self.assertEqual(snippets[0]["replacement"], "pending")
        self.assertFalse(snippets[0]["enabled"])
        self.assertTrue(snippets[0]["case_sensitive"])
        self.assertTrue(self.settings.dirty)
        with patch.object(self.settings, "accountCommand", return_value=True):
            self.assertIn("result", self.request("save", context))
        self.assertEqual(service.state.dictionary[0].pronunciation, "pending")
        self.assertEqual(service.state.snippets[0].replacement, "pending")
        self.assertFalse(self.settings.dirty)

    def test_library_preference_sync_completion_keeps_newer_saved_flags(self):
        import threading
        from dataclasses import replace
        from dictionary_snippets import DictionarySnippets, DictionaryEntry, Snippet

        account, service, _guest = self.account_library()
        context = self.settings.snippetContext
        service.replace(
            DictionarySnippets(
                dictionary=(DictionaryEntry("A"),), snippets=(Snippet("a", "A"),)
            ),
            expected_context=context,
        )
        self.request("load")
        imported, release = threading.Event(), threading.Event()

        def sync(library):
            if imported.is_set():
                return
            library.replace(
                replace(
                    library.state,
                    dictionary=(*library.state.dictionary, DictionaryEntry("B")),
                    snippets=(
                        Snippet("a", "remote", enabled=False, case_sensitive=True),
                    ),
                ),
                expected_context=context,
            )
            imported.set()
            if not release.wait(3):
                raise AssertionError("sync gate timed out")

        with patch.object(account, "sync_library", side_effect=sync):
            self.assertIn(
                "result",
                self.request(
                    "saveLibraryPreference",
                    "dictionary",
                    self.settings.dictionaryEntries[0],
                    "enabled",
                    False,
                    context,
                ),
            )
            try:
                self.assertTrue(imported.wait(3))
                identity = service.state.snippets[0].to_mapping()
                self.assertIn(
                    "result",
                    self.request(
                        "saveLibraryPreference",
                        "snippets",
                        identity,
                        "enabled",
                        True,
                        context,
                    ),
                )
            finally:
                release.set()
                self.wait_for_account()
        self.assertTrue(self.settings.snippets[0]["enabled"])
        self.assertTrue(self.settings.snippets[0]["case_sensitive"])
        self.assertEqual(self.settings.snippets[0]["replacement"], "remote")
        self.assertEqual(
            [row["term"] for row in self.settings.dictionaryEntries], ["A", "B"]
        )
        self.assertFalse(self.settings.dirty)

    def test_library_preference_partial_sync_error_reconciles_durable_import(self):
        from dataclasses import replace
        from clarify_account import AccountError
        from dictionary_snippets import DictionarySnippets, DictionaryEntry

        account, service, _guest = self.account_library()
        context = self.settings.snippetContext
        service.replace(
            DictionarySnippets(dictionary=(DictionaryEntry("A"),)),
            expected_context=context,
        )
        self.request("load")

        def sync(library):
            library.replace(
                replace(
                    library.state,
                    dictionary=(*library.state.dictionary, DictionaryEntry("B")),
                ),
                expected_context=context,
            )
            library.reload()
            raise AccountError("isolated snippets sync failure")

        with patch.object(account, "sync_library", side_effect=sync):
            self.assertIn(
                "result",
                self.request(
                    "saveLibraryPreference",
                    "dictionary",
                    self.settings.dictionaryEntries[0],
                    "enabled",
                    False,
                    context,
                ),
            )
            self.wait_for_account()
        self.assertEqual(
            [row["term"] for row in self.settings.dictionaryEntries], ["A", "B"]
        )
        self.assertIn(
            "isolated snippets sync failure", self.settings.accountState["error"]
        )
        self.assertFalse(self.settings.dirty)
        with patch.object(self.settings, "accountCommand", return_value=True):
            self.assertIn("result", self.request("save", context))
        self.assertEqual([row.term for row in service.reload().dictionary], ["A", "B"])

    def test_library_preference_sync_context_change_does_not_rebase_into_guest(self):
        from dictionary_snippets import DictionarySnippets, DictionaryEntry

        account, service, guest = self.account_library()
        context, guest_before = self.settings.snippetContext, guest.load()
        service.replace(
            DictionarySnippets(dictionary=(DictionaryEntry("Account only"),)),
            expected_context=context,
        )
        self.request("load")

        def sync(library):
            with account._lock:
                account._state.pop("user_id", None)
                account._generation += 1
                library.reload()

        with patch.object(account, "sync_library", side_effect=sync):
            self.assertIn(
                "result",
                self.request(
                    "saveLibraryPreference",
                    "dictionary",
                    self.settings.dictionaryEntries[0],
                    "enabled",
                    False,
                    context,
                ),
            )
            self.wait_for_account()
        self.assertEqual(self.settings.dictionaryEntries[0]["term"], "Account only")
        self.assertIn("error", self.request("save", context))
        self.assertEqual(guest.load(), guest_before)
        self.assertEqual(service.state, guest_before)
        self.request("load")
        self.assertFalse(self.settings.dirty)

    def test_library_preference_sync_merge_limit_preserves_both_copies(self):
        from dictionary_snippets import DictionarySnippets, DictionaryEntry, Snippet

        account, service, guest = self.account_library()
        context, guest_before = self.settings.snippetContext, guest.load()
        service.replace(
            DictionarySnippets(
                dictionary=(DictionaryEntry("A"),), snippets=(Snippet("a", "A"),)
            ),
            expected_context=context,
        )
        self.request("load")
        self.request(
            "setDictionaryEntries",
            [{"term": "A"}, {"term": "Pending local term"}],
            context,
        )
        self.request(
            "setSnippets",
            [
                {"trigger": "a", "replacement": "A"},
                {"trigger": "pending", "replacement": "Pending local text"},
            ],
            context,
        )

        def sync(library):
            library.replace(
                DictionarySnippets(
                    dictionary=(
                        DictionaryEntry("A", enabled=False),
                        *(DictionaryEntry(f"Remote {index}") for index in range(511)),
                    ),
                    snippets=(
                        Snippet("a", "A"),
                        *(Snippet(f"remote {index}", "Remote") for index in range(511)),
                    ),
                ),
                expected_context=context,
            )
            library.reload()

        with patch.object(account, "sync_library", side_effect=sync):
            self.assertIn(
                "result",
                self.request(
                    "saveLibraryPreference",
                    "dictionary",
                    service.state.dictionary[0].to_mapping(),
                    "enabled",
                    False,
                    context,
                ),
            )
            self.wait_for_account()
        persisted = service.state
        self.assertEqual(len(persisted.dictionary), 512)
        self.assertEqual(len(persisted.snippets), 512)
        self.assertEqual(
            self.settings.dictionaryEntries[-1]["term"], "Pending local term"
        )
        self.assertEqual(
            self.settings.snippets[-1]["replacement"], "Pending local text"
        )
        config = self.settings.repositories.config.load()
        self.assertIn("error", self.request("save", context))
        self.assertEqual(service.reload(), persisted)
        self.assertEqual(guest.load(), guest_before)
        self.assertEqual(self.settings.repositories.config.load(), config)

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
