from dataclasses import replace
from pathlib import Path
import unittest
import json
from unittest.mock import patch

from clarify_account import AccountError, merge_snippets
from dictionary_snippets import Snippet
from workflows import RecordingSnapshot
import tests.support.account as fixture


class AccountSnippetTests(unittest.TestCase):
    setUp = fixture.AccountFixture.setUp
    response = fixture.AccountFixture.response
    signed_in = fixture.AccountFixture.signed_in

    def test_cleanup_is_optional_and_preserve_has_no_false_failure_or_model(self):
        self.signed_in()
        self.account._last_sync_attempt = self.account._clock()
        self.request.return_value = self.response(
            {
                "transcript": "Não  envie 42.",
                "text": "Não  envie 42.",
                "rewritten": False,
                "cleanup_level_requested": "preserve",
                "cleanup_level_applied": "preserve",
                "refinement_attempted": False,
                "refinement_failed": False,
            }
        )
        result = self.account.transcribe(
            RecordingSnapshot(Path("unused"), b"fake"),
            "pt",
            self.service,
            cleanup_level="preserve",
        )
        self.assertEqual(
            self.request.call_args.kwargs["data"]["cleanup_level"], "preserve"
        )
        self.assertEqual(result.cleanup_level_requested, "preserve")
        self.assertEqual(result.cleanup_level_applied, "preserve")
        self.assertFalse(result.refinement_failed)
        self.assertIsNone(result.refinement_model)
        self.assertEqual(result.raw_text, "Não  envie 42.")

    def test_explicit_cleanup_rejects_missing_or_mismatched_response_policy(self):
        self.signed_in()
        self.account._last_sync_attempt = self.account._clock()
        self.request.reset_mock()
        self.request.return_value = self.response(
            {"transcript": "Source", "text": "Changed", "rewritten": True}
        )
        with self.assertRaises(AccountError):
            self.account.transcribe(
                RecordingSnapshot(Path("unused"), b"fake"),
                "pt",
                self.service,
                cleanup_level="preserve",
            )
        self.request.assert_called_once()

    def test_explicit_cleanup_rejects_account_switch_and_cancelled_reply(self):
        from provider_http import CancellationToken, ProviderCancelledError

        for switched in (True, False):
            with self.subTest(switched=switched):
                self.signed_in()
                self.account._last_sync_attempt = self.account._clock()
                self.request.reset_mock()
                token = CancellationToken()

                def respond(*args, **kwargs):
                    if switched:
                        self.account._generation += 1
                    else:
                        token.cancel()
                    return self.response(
                        {
                            "transcript": "Source",
                            "text": "Source",
                            "rewritten": False,
                            "cleanup_level_requested": "preserve",
                            "cleanup_level_applied": "preserve",
                        }
                    )

                self.request.side_effect = respond
                with self.assertRaises(
                    AccountError if switched else ProviderCancelledError
                ):
                    self.account.transcribe(
                        RecordingSnapshot(Path("unused"), b"fake", token),
                        "pt",
                        self.service,
                        cleanup_level="preserve",
                    )
                self.request.assert_called_once()
                self.request.side_effect = None

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

    def test_failed_snippet_write_rolls_back_simultaneous_dictionary_change(self):
        from dictionary_snippets import (
            DictionaryEntry,
            LocalDictionarySnippetsRepository,
        )

        self.signed_in()
        self.service.reload()
        before = self.service.state
        original_save = LocalDictionarySnippetsRepository.save

        def persist(repository, state):
            if repository.path.name == "snippets.json":
                raise OSError("isolated storage failure")
            return original_save(repository, state)

        with patch.object(LocalDictionarySnippetsRepository, "save", persist):
            with self.assertRaises(OSError):
                self.service.replace(
                    replace(
                        before,
                        dictionary=(DictionaryEntry("new"),),
                        snippets=(Snippet("sig", "saved"),),
                    )
                )
        self.assertEqual(self.service.state, before)
        self.assertEqual(self.service.repository.load(), before)
        self.assertEqual(self.local.load().snippets, (Snippet("sig", "signature"),))

    def test_snippet_only_save_does_not_rewrite_account_dictionary(self):
        from dictionary_snippets import LocalDictionarySnippetsRepository

        self.signed_in()
        self.service.reload()
        before = self.service.state
        writes = []
        original_save = LocalDictionarySnippetsRepository.save

        def persist(repository, state):
            writes.append(repository.path.name)
            return original_save(repository, state)

        with patch.object(LocalDictionarySnippetsRepository, "save", persist):
            self.service.replace(replace(before, snippets=(Snippet("sig", "saved"),)))
        self.assertEqual(writes, ["snippets.json"])

    def test_library_operations_acquire_owner_guard_before_service_lock(self):
        import threading

        for operation in ("replace", "reload", "import"):
            with self.subTest(operation=operation):
                self.signed_in()
                self.service.reload()
                target = replace(
                    self.service.state, snippets=(Snippet("new", "Account text"),)
                )
                attempted = threading.Event()
                errors = []
                original_transaction = self.service.repository.transaction

                def guarded(**kwargs):
                    if threading.current_thread() is worker:
                        attempted.set()
                    return original_transaction(**kwargs)

                def change():
                    try:
                        if operation == "replace":
                            self.service.replace(target)
                        elif operation == "reload":
                            self.service.reload()
                        else:
                            self.service.import_json(target.to_mapping())
                    except Exception as error:
                        errors.append(error)

                worker = threading.Thread(target=change)
                try:
                    with patch.object(
                        self.service.repository, "transaction", side_effect=guarded
                    ):
                        with self.account._lock:
                            worker.start()
                            self.assertTrue(attempted.wait(3))
                            acquired = self.service._lock.acquire(timeout=0.5)
                            try:
                                self.assertTrue(
                                    acquired,
                                    "Owner wait must not hold the service lock",
                                )
                            finally:
                                if acquired:
                                    self.service._lock.release()
                            self.service.reload()
                finally:
                    worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
