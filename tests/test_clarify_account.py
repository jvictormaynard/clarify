import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import uuid

from clarify_account import (
    AccountDictionaryRepository,
    AccountError,
    AccountService,
    endpoint,
    merge_dictionary,
)
from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippets,
    DictionarySnippetService,
    LocalDictionarySnippetsRepository,
    Snippet,
)
from secret_store import PlaintextFileSecretStore


def entry(term, **kwargs):
    return DictionaryEntry(term, **kwargs).to_mapping()


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = Mock()
        self.account = AccountService(
            self.root,
            secrets=PlaintextFileSecretStore(self.root / "test-secrets.json"),
            request=self.request,
            default_endpoint="https://clarify.example",
        )
        self.local = LocalDictionarySnippetsRepository(self.root / "dictionary.json")
        self.local.save(
            DictionarySnippets(
                (DictionaryEntry("Local"),), (Snippet("sig", "signature"),)
            )
        )
        self.service = DictionarySnippetService(
            AccountDictionaryRepository(self.account, self.local)
        )

    def response(self, payload, status=200):
        result = Mock(status_code=status, content=b"json")
        result.json.return_value = payload
        return result

    def signed_in(self, user_id=None):
        user_id = user_id or str(uuid.uuid4())
        self.account.secrets.set("clarify_account", "test-session-only")
        self.request.return_value = self.response(
            {"id": user_id, "email": "user@example.test", "usage": {"used_ms": 1}}
        )
        self.account.refresh()
        return user_id

    def test_construction_and_snapshot_make_no_network_calls_or_expose_session(self):
        self.assertFalse(self.account.snapshot()["signedIn"])
        self.request.assert_not_called()
        self.signed_in()
        self.assertNotIn("test-session-only", json.dumps(self.account.snapshot()))
        self.assertNotIn("test-session-only", self.account.path.read_text())
        self.assertFalse(self.account.hosted)

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
        self.assertEqual(self.service.expand("sig"), "signature")
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

    def test_expired_session_restores_local_scope_and_preserves_hosted_choice(self):
        self.signed_in()
        self.account.set_hosted(True)
        self.request.return_value = self.response({}, 403)
        with self.assertRaises(AccountError):
            self.account.refresh()
        self.assertFalse(self.account.snapshot()["signedIn"])
        self.assertIsNone(self.account.secrets.get("clarify_account"))
        self.assertTrue(self.account.hosted)

    def test_conflict_choice_preserves_other_independent_changes(self):
        base = [entry("A")]
        local = [entry("A", pronunciation="ours"), entry("Local")]
        remote = [entry("A", pronunciation="theirs"), entry("Remote")]
        merged = merge_dictionary(base, local, remote, prefer="remote")
        self.assertEqual({item["term"] for item in merged}, {"A", "Local", "Remote"})
        self.assertEqual(merged[0]["pronunciation"], "theirs")

    def test_failed_first_sync_does_not_drop_words_changed_during_request(self):
        user_id = self.signed_in()

        def answer(method, url, **kwargs):
            if method == "PUT":
                self.local.save(
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
        self.assertFalse((self.root / "account-data" / user_id / "sync.json").exists())
        self.assertEqual(
            {e.term for e in self.service.state.dictionary}, {"Local", "New"}
        )
