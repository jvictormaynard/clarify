import json
import unittest
import uuid

from clarify_account import (
    AccountError,
    endpoint,
    merge_dictionary,
)
from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippets,
)


from tests.support.account import (
    entry,
    weekly_usage,
    AccountFixture,
)


class AccountTests(AccountFixture, unittest.TestCase):
    def test_construction_and_snapshot_make_no_network_calls_or_expose_session(self):
        self.assertFalse(self.account.snapshot()["signedIn"])
        self.request.assert_not_called()
        self.signed_in()
        self.assertNotIn("test-session-only", json.dumps(self.account.snapshot()))

    def test_device_language_is_sent_without_changing_the_auth_payload(self):
        self.account.ui_language = "es"
        self.request.return_value = self.response({}, 401)
        self.account.authenticate("login", "user@example.test")
        self.assertEqual(
            self.request.call_args.kwargs["headers"]["Accept-Language"], "es"
        )

    def test_weekly_usage_envelope_passes_through_without_duration_inference(self):
        user_id = self.signed_in()
        for status in ("available", "waiting", "unfunded", "inactive"):
            with self.subTest(status=status):
                usage = weekly_usage(allocation_status=status)
                self.request.return_value = self.response(
                    {"id": user_id, "email": "user@example.test", "usage": usage}
                )
                self.account.refresh()
                self.assertEqual(self.account.snapshot()["usage"], usage)
                self.assertNotIn("limit_ms", self.account.snapshot()["usage"])
                self.assertTrue(self.account.signed_in)

    def test_automatic_refresh_has_a_network_cooldown(self):
        self.signed_in()
        self.request.side_effect = [
            self.response({"revision": 0, "entries": [entry("Local")]}),
            self.response({"revision": 0, "entries": []}),
        ]
        self.account.refresh_if_due(self.service)
        self.request.reset_mock()
        self.account.refresh_if_due(self.service)
        self.request.assert_not_called()

    def test_email_entry_uses_unified_passwordless_flow_and_existing_confirmation(self):
        self.request.return_value = self.response(
            {"meta": {"session_token": "pending-session"}}, 401
        )
        self.account.authenticate("login", " user@example.test ")
        self.assertEqual(
            self.request.call_args.args[1],
            "https://clarify.example/_allauth/app/v1/auth/continue",
        )
        self.assertEqual(
            self.request.call_args.kwargs["json"], {"email": "user@example.test"}
        )
        self.assertEqual(self.account.snapshot()["pending"], "login")
        self.assertFalse(self.account.snapshot()["signedIn"])
        user_id = str(uuid.uuid4())
        self.request.side_effect = [
            self.response({"meta": {"is_authenticated": True}}),
            self.response({"id": user_id, "email": "user@example.test"}),
        ]
        self.account.authenticate("confirm", "123456")
        self.assertFalse(self.account.hosted)
        confirm = self.request.call_args_list[-2]
        self.assertEqual(
            confirm.args[1], "https://clarify.example/_allauth/app/v1/auth/code/confirm"
        )
        self.assertEqual(confirm.kwargs["json"], {"code": "123456"})
        self.assertTrue(self.account.snapshot()["signedIn"])

    def test_endpoint_rejects_credentials_paths_queries_and_insecure_hosts(self):
        for value in (
            "http://public.test",
            "https://u:p@host",
            "https://host/path",
            "https://host?token=x",
            "file:///x",
        ):
            with self.assertRaises(AccountError):
                endpoint(value)
        self.assertEqual(endpoint("http://127.0.0.1:8000/"), "http://127.0.0.1:8000")

    def test_settings_change_excludes_another_change_until_reload_finishes(self):
        self.assertFalse(self.account.busy)
        self.assertTrue(self.account.begin_change())
        self.assertTrue(self.account.busy)
        self.assertFalse(self.account.begin_change())
        self.account.end_change()
        self.assertTrue(self.account.begin_change())
        self.account.end_change()

    def test_merge_combines_independent_changes_and_preserves_deletions(self):
        base = [entry("A"), entry("B")]
        local = [entry("B"), entry("Local")]
        remote = base + [entry("Remote")]
        merged = merge_dictionary(base, local, remote)
        self.assertEqual({item["term"] for item in merged}, {"B", "Local", "Remote"})

    def test_same_term_conflict_does_not_silently_overwrite(self):
        with self.assertRaises(AccountError):
            merge_dictionary(
                [entry("A")],
                [entry("A", pronunciation="ours")],
                [entry("A", pronunciation="theirs")],
            )

    def test_sync_is_explicit_namespaced_and_logout_restores_local_and_snippets(self):
        user_id = self.signed_in()
        self.assertEqual([e.term for e in self.service.state.dictionary], ["Local"])
        self.request.side_effect = [
            self.response({"revision": 0, "entries": [entry("Remote")]}),
            self.response(
                {"revision": 1, "entries": [entry("Remote"), entry("Local")]}
            ),
        ]
        self.account.sync_dictionary(self.service)
        self.assertEqual(self.account.scope, user_id)
        self.assertEqual(
            {e.term for e in self.service.state.dictionary}, {"Remote", "Local"}
        )
        self.assertEqual([e.term for e in self.local.load().dictionary], ["Local"])
        self.assertEqual(self.service.expand("sig"), "sig")
        self.request.side_effect = None
        self.request.return_value = self.response({}, 200)
        self.account.logout()
        self.service.reload()
        self.assertFalse(self.account.snapshot()["signedIn"])
        self.assertIsNone(self.account.scope)
        self.assertEqual([e.term for e in self.service.state.dictionary], ["Local"])

    def test_conflict_preserves_local_cache_and_server_is_not_overwritten(self):
        self.signed_in()
        self.request.return_value = self.response(
            {"revision": 1, "entries": [entry("Local", pronunciation="different")]}
        )
        with self.assertRaises(AccountError):
            self.account.sync_dictionary(self.service)
        self.assertEqual(self.service.state.dictionary[0].pronunciation, "")
        self.assertFalse(self.account.snapshot()["syncEnabled"])

    def test_expired_session_restores_local_scope_and_keeps_managed_processing(self):
        self.signed_in()
        self.request.return_value = self.response({}, 403)
        with self.assertRaises(AccountError):
            self.account.refresh()
        self.assertFalse(self.account.snapshot()["signedIn"])
        self.assertIsNone(self.account.secrets.get("clarify_account"))
        self.assertFalse(self.account.hosted)
        self.assertFalse(self.account.managed)

    def test_conflict_choice_preserves_other_independent_changes(self):
        base = [entry("A")]
        local = [entry("A", pronunciation="ours"), entry("Local")]
        remote = [entry("A", pronunciation="theirs"), entry("Remote")]
        merged = merge_dictionary(base, local, remote, prefer="remote")
        self.assertEqual({item["term"] for item in merged}, {"A", "Local", "Remote"})
        self.assertEqual(merged[0]["pronunciation"], "theirs")

    def test_failed_first_sync_does_not_drop_words_changed_during_request(self):
        self.signed_in()
        self.service.reload()

        def answer(method, url, **kwargs):
            if method == "PUT":
                self.service.repository.save(
                    DictionarySnippets(
                        (DictionaryEntry("Local"), DictionaryEntry("New"))
                    )
                )
                self.service.reload()
                return self.response({"revision": 1, "entries": [entry("Local")]})
            return self.response({"revision": 0, "entries": []})

        self.request.side_effect = answer
        with self.assertRaises(AccountError):
            self.account.sync_dictionary(self.service)
        self.assertEqual([e.term for e in self.local.load().dictionary], ["Local"])
        self.assertEqual(
            {e.term for e in self.service.state.dictionary}, {"Local", "New"}
        )
