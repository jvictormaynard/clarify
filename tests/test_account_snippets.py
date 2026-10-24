from dataclasses import replace
from pathlib import Path
import unittest
import json

from clarify_account import AccountError, merge_snippets
from dictionary_snippets import Snippet
from workflows import RecordingSnapshot
from tests import test_clarify_account as fixture


class AccountSnippetTests(unittest.TestCase):
    setUp = fixture.AccountTests.setUp
    response = fixture.AccountTests.response
    signed_in = fixture.AccountTests.signed_in

    def test_cloud_result_is_not_expanded_again_or_replaced_with_raw_text(self):
        self.signed_in()
        self.account._last_sync_attempt = self.account._clock()
        self.request.return_value = self.response(
            {
                "transcript": "minha assinatura",
                "text": "sig",
                "rewritten": False,
                "snippet_expanded": True,
            }
        )
        result = self.account.transcribe(
            RecordingSnapshot(Path("unused"), b"fake"), "pt", self.service
        )
        self.assertEqual(result.text, "sig")
        self.assertFalse(result.refinement_failed)
        self.assertEqual(result.raw_text, "minha assinatura")
        self.assertEqual(result.refined_text, "sig")

    def test_account_cache_is_separate_from_guest_and_other_accounts(self):
        first = self.signed_in()
        self.service.reload()
        self.assertEqual(self.service.state.snippets, ())
        self.service.replace(
            replace(self.service.state, snippets=(Snippet("cloud", "account text"),))
        )
        self.assertEqual(self.local.load().snippets, (Snippet("sig", "signature"),))
        self.signed_in()
        self.service.reload()
        self.assertEqual(self.service.state.snippets, ())
        self.signed_in(first)
        self.service.reload()
        self.assertEqual(self.service.expand("cloud"), "account text")

    def test_sync_uploads_local_edits_and_downloads_remote_without_changing_guest(self):
        self.signed_in()
        self.service.reload()
        self.service.replace(
            replace(self.service.state, snippets=(Snippet("ours", "Ours"),))
        )
        remote = Snippet("theirs", "Theirs").to_mapping()
        merged = [remote, Snippet("ours", "Ours").to_mapping()]
        self.request.side_effect = [
            self.response({"revision": 3, "entries": [remote]}),
            self.response({"revision": 4, "entries": merged}),
        ]
        self.account.sync_snippets(self.service)
        self.assertEqual(
            [item.trigger for item in self.service.state.snippets], ["theirs", "ours"]
        )
        self.assertEqual(
            json.loads(self.request.call_args.kwargs["data"]),
            {"revision": 3, "entries": merged},
        )
        self.assertEqual(self.local.load().snippets[0].replacement, "signature")

    def test_conflict_does_not_overwrite_cache_or_server(self):
        before = Snippet("sig", "before").to_mapping()
        ours = Snippet("sig", "ours").to_mapping()
        theirs = Snippet("sig", "theirs").to_mapping()
        with self.assertRaises(AccountError):
            merge_snippets([before], [ours], [theirs])
        self.assertEqual(
            merge_snippets([before], [ours], [theirs], prefer="remote"), [theirs]
        )
        self.assertEqual(merge_snippets([before], [], [before]), [])

    def test_edits_during_sync_are_preserved(self):
        self.signed_in()
        self.service.reload()

        def respond(*args, **kwargs):
            self.service.replace(
                replace(self.service.state, snippets=(Snippet("new", "local edit"),))
            )
            return self.response({"revision": 0, "entries": []})

        self.request.side_effect = respond
        with self.assertRaises(AccountError):
            self.account.sync_snippets(self.service)
        self.assertEqual(self.service.state.snippets[0].replacement, "local edit")

    def test_invalid_server_library_preserves_local_edits(self):
        self.signed_in()
        self.service.reload()
        self.service.replace(
            replace(self.service.state, snippets=(Snippet("local", "Saved"),))
        )
        for remote in (
            {"revision": True, "entries": []},
            {"revision": -1, "entries": []},
            {
                "revision": 0,
                "entries": [{"trigger": "bad", "replacement": "x", "enabled": "yes"}],
            },
        ):
            self.request.return_value = self.response(remote)
            with self.assertRaises(AccountError):
                self.account.sync_snippets(self.service)
            self.assertEqual(self.service.state.snippets, (Snippet("local", "Saved"),))

    def test_same_user_on_another_endpoint_gets_a_separate_snippet_cache(self):
        identity = self.signed_in()
        self.service.reload()
        self.service.replace(
            replace(self.service.state, snippets=(Snippet("cloud", "first server"),))
        )
        self.request.return_value = self.response({}, 204)
        self.account.logout()
        self.account.configure("https://second.example")
        self.signed_in(identity)
        self.service.reload()
        self.assertEqual(self.service.state.snippets, ())
        self.assertEqual(self.local.load().snippets, (Snippet("sig", "signature"),))

    def test_revoked_session_during_sync_does_not_publish_into_guest_cache(self):
        self.signed_in()
        self.service.reload()
        self.service.replace(
            replace(self.service.state, snippets=(Snippet("local", "pending"),))
        )
        self.request.return_value = self.response({}, 403)
        with self.assertRaises(AccountError):
            self.account.sync_snippets(self.service)
        self.assertFalse(self.account.signed_in)
        self.assertEqual(self.local.load().snippets, (Snippet("sig", "signature"),))
        self.service.reload()
        self.assertEqual(self.service.state.snippets, (Snippet("sig", "signature"),))

    def test_old_server_dictation_result_remains_usable_without_recursive_expansion(
        self,
    ):
        self.signed_in()
        self.account._last_sync_attempt = self.account._clock()
        self.service.reload()
        self.service.replace(
            replace(self.service.state, snippets=(Snippet("sig", "second expansion"),))
        )
        self.request.return_value = self.response(
            {"transcript": "source", "text": "sig", "rewritten": True}
        )
        result = self.account.transcribe(
            RecordingSnapshot(Path("unused"), b"fake"), "pt", self.service
        )
        self.assertEqual(result.text, "sig")
        self.assertFalse(result.refinement_failed)

    def test_account_transport_limit_preserves_previous_cache_and_guest_can_still_save(
        self,
    ):
        from dictionary_snippets import DictionarySnippetsError

        self.signed_in()
        self.service.reload()
        before = self.service.state
        oversized = tuple(Snippet(f"phrase {index}", "é" * 4096) for index in range(33))
        with self.assertRaises(DictionarySnippetsError):
            self.service.replace(replace(before, snippets=oversized))
        self.assertEqual(self.service.state, before)
        self.assertEqual(self.local.load().snippets, (Snippet("sig", "signature"),))
        self.local.save(replace(self.local.load(), snippets=oversized))
        self.assertEqual(len(self.local.load().snippets), 33)

    def test_snippet_sync_sends_utf8_json_without_ascii_expansion(self):
        self.signed_in()
        self.service.reload()
        entries = [Snippet("minha assinatura", "É" * 4096).to_mapping()]
        self.service.replace(
            replace(self.service.state, snippets=(Snippet.from_mapping(entries[0]),))
        )
        self.request.side_effect = [
            self.response({"revision": 0, "entries": []}),
            self.response({"revision": 1, "entries": entries}),
        ]
        self.account.sync_snippets(self.service)
        self.assertIn("É".encode("utf-8"), self.request.call_args.kwargs["data"])
        self.assertEqual(
            self.request.call_args.kwargs["headers"]["Content-Type"], "application/json"
        )

    def test_oversized_hosted_result_has_a_clear_failure_and_no_text_result(self):
        self.signed_in()
        self.account._last_sync_attempt = self.account._clock()
        self.request.return_value = self.response(
            {"code": "snippet_result_too_large", "phase": "processing"}, 422
        )
        with self.assertRaises(AccountError) as caught:
            self.account.transcribe(
                RecordingSnapshot(Path("unused"), b"fake"), "pt", self.service
            )
        self.assertEqual(caught.exception.code, "snippet_result_too_large")
        self.assertEqual(
            str(caught.exception),
            "O texto dos snippets excede o limite. Use menos frases de ativação.",
        )
