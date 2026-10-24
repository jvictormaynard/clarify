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
        self.assertTrue(self.account.hosted)

    def test_device_language_is_sent_without_changing_the_auth_payload(self):
        self.account.ui_language = "es"
        self.request.return_value = self.response({}, 401)
        self.account.authenticate("login", "user@example.test")
        self.assertEqual(
            self.request.call_args.kwargs["headers"]["Accept-Language"], "es"
        )

    def test_late_account_refresh_cannot_undo_usage_returned_by_processing(self):
        user_id = self.signed_in()

        def respond(method, url, **kwargs):
            if method == "GET":
                self.account._request("POST", "/v1/text", json={})
                return self.response(
                    {
                        "id": user_id,
                        "email": "user@example.test",
                        "usage": {"used_ms": 10},
                    }
                )
            return self.response({"usage": {"used_ms": 500}})

        self.request.side_effect = respond
        self.account.refresh()
        self.assertEqual(self.account.snapshot()["usage"]["used_ms"], 500)

    def test_cancelled_result_still_updates_consumption_without_publishing(self):
        from provider_http import CancellationToken, ProviderCancelledError

        token = CancellationToken()

        def respond(*args, **kwargs):
            token.cancel()
            return self.response(
                {"usage": {"used_ms": 500}, "text": "Discard this result"}
            )

        self.request.side_effect = respond
        with self.assertRaises(ProviderCancelledError):
            self.account._request("POST", "/v1/text", cancel=token, json={})
        self.assertEqual(self.account.snapshot()["usage"]["used_ms"], 500)

    def test_signed_in_processing_is_ready_without_a_separate_activation(self):
        self.signed_in()
        self.assertTrue(self.account.signed_in)
        self.assertTrue(self.account.hosted)
        self.request.return_value = self.response({"text": "Processed text."})
        self.assertEqual(
            self.account.transform_text("Source text.", "rewrite"), "Processed text."
        )
        self.assertEqual(
            self.request.call_args.args[1], "https://clarify.example/v1/text"
        )

    def processing_failure(self, action, status, payload):
        from provider_http import CancellationToken
        from workflows import RecordingSnapshot

        self.signed_in()
        self.account._last_sync_attempt = self.account._clock()
        self.request.reset_mock()
        self.request.return_value = self.response(payload, status)
        with self.assertRaises(AccountError) as caught:
            if action == "dictation":
                self.account.transcribe(
                    RecordingSnapshot(
                        Path("unused.wav"), b"synthetic audio", CancellationToken()
                    ),
                    "pt",
                    self.service,
                )
            else:
                self.account.transform_text("Source text.", "rewrite")
        self.request.assert_called_once()
        return caught.exception

    def test_processing_errors_use_the_cause_and_keep_safe_diagnostics(self):
        cases = [
            (
                "dictation",
                422,
                "no_speech",
                "transcription",
                "Nenhuma fala foi reconhecida. Tente falar novamente.",
            ),
            (
                "dictation",
                502,
                "transcription_failed",
                "transcription",
                "Não foi possível transcrever o áudio. Tente novamente.",
            ),
            (
                "text",
                502,
                "text_processing_failed",
                "text",
                "Não foi possível processar o texto. Tente novamente.",
            ),
            (
                "dictation",
                502,
                "processing_failed",
                "processing",
                "Não foi possível concluir o processamento. Tente novamente.",
            ),
            (
                "dictation",
                429,
                "allowance_exhausted",
                "admission",
                "Sua cota foi atingida.",
            ),
            (
                "text",
                429,
                "rate_limited",
                "admission",
                "Muitas solicitações. Aguarde um momento.",
            ),
            (
                "dictation",
                429,
                "account_busy",
                "admission",
                "Já existe um processamento em andamento.",
            ),
            (
                "text",
                503,
                "service_busy",
                "admission",
                "O Clarify está ocupado. Aguarde um momento.",
            ),
            (
                "dictation",
                503,
                "service_budget_exhausted",
                "admission",
                "O processamento do Clarify está indisponível no momento.",
            ),
            (
                "dictation",
                400,
                "invalid_audio",
                "validation",
                "Grave um áudio válido de até 5 minutos.",
            ),
            (
                "text",
                400,
                "invalid_text_request",
                "validation",
                "Selecione um texto válido para processar.",
            ),
        ]
        operation_id = str(uuid.uuid4())
        for action, status, code, phase, message in cases:
            with self.subTest(action=action, code=code):
                error = self.processing_failure(
                    action,
                    status,
                    {
                        "code": code,
                        "phase": phase,
                        "operation_id": operation_id,
                        "detail": "private upstream body",
                        "usage": {"used_ms": 1000},
                    },
                )
                self.assertEqual(str(error), message)
                self.assertEqual(error.code, code)
                self.assertEqual(error.phase, phase)
                self.assertEqual(error.operation_id, operation_id)
                self.assertEqual(error.status, status)
                self.assertEqual(self.account.snapshot()["usage"]["used_ms"], 1000)
                self.assertNotIn("private upstream body", repr(vars(error)))

    def test_expired_or_pending_operations_do_not_automatically_retry(self):
        for action in ("dictation", "text"):
            for code in (
                "operation_conflict",
                "operation_expired",
                "operation_pending",
            ):
                with self.subTest(action=action, code=code):
                    error = self.processing_failure(action, 409, {"code": code})
                    expected = (
                        "Já existe um processamento em andamento."
                        if code == "operation_pending"
                        else "Esta solicitação já foi processada. Inicie uma nova gravação."
                        if action == "dictation"
                        else "Esta solicitação não pode ser repetida. Inicie uma nova ação."
                    )
                    self.assertEqual(str(error), expected)

    def test_processing_error_copy_uses_shared_ui_languages(self):
        from shared.localization import translate

        error = self.processing_failure("dictation", 422, {"code": "no_speech"})
        for locale, expected in [
            ("pt", "Nenhuma fala foi reconhecida. Tente falar novamente."),
            ("en", "No speech was recognized. Try speaking again."),
            ("es", "No se reconoció ninguna voz. Intenta hablar de nuevo."),
        ]:
            self.assertEqual(translate(str(error), locale), expected)

    def test_processing_errors_from_older_servers_use_safe_status_fallbacks(self):
        for action, status, expected in [
            (
                "dictation",
                502,
                "Não foi possível transcrever o áudio. Tente novamente.",
            ),
            ("text", 502, "Não foi possível processar o texto. Tente novamente."),
            (
                "dictation",
                503,
                "O processamento do Clarify está indisponível no momento.",
            ),
            ("text", 400, "Selecione um texto válido para processar."),
        ]:
            with self.subTest(action=action, status=status):
                error = self.processing_failure(action, status, {})
                self.assertEqual(str(error), expected)
                self.assertEqual(error.code, "")

    def test_processing_error_fields_cannot_inject_server_content(self):
        for bad in ([], {}, 1, None, "private upstream body", "x" * 10000):
            with self.subTest(value=type(bad).__name__):
                error = self.processing_failure(
                    "dictation",
                    502,
                    {"code": bad, "phase": bad, "operation_id": bad},
                )
                self.assertEqual(
                    str(error), "Não foi possível transcrever o áudio. Tente novamente."
                )
                self.assertEqual(
                    (error.code, error.phase, error.operation_id), ("", "", "")
                )

    def test_auth_status_overrides_payload_and_managed_mode_does_not_fall_back(self):
        for action in ("dictation", "text"):
            with self.subTest(action=action):
                error = self.processing_failure(action, 401, {"code": "no_speech"})
                self.assertEqual(str(error), "Entre na conta novamente.")
                self.assertEqual(error.code, "authentication_required")
                self.assertFalse(self.account.hosted)
                self.assertTrue(self.account.managed)
                self.assertIsNone(self.account.secrets.get("clarify_account"))

    def test_expired_processing_response_cannot_restore_session_or_usage(self):
        for action in ("dictation", "text"):
            for status in (401, 403):
                with self.subTest(action=action, status=status):
                    error = self.processing_failure(
                        action,
                        status,
                        {
                            "meta": {"session_token": "rejected-response-token"},
                            "usage": {"used_ms": 999},
                        },
                    )
                    self.assertEqual(str(error), "Entre na conta novamente.")
                    self.assertIsNone(self.account.secrets.get("clarify_account"))
                    self.assertEqual(self.account.snapshot()["usage"], {})
                    self.assertFalse(self.account.hosted)
                    self.assertTrue(self.account.managed)

    def test_malformed_processing_metadata_does_not_hide_error_or_usage(self):
        for meta in (None, [], "private upstream body", 1):
            with self.subTest(meta=meta):
                error = self.processing_failure(
                    "dictation",
                    422,
                    {"code": "no_speech", "meta": meta, "usage": {"used_ms": 1000}},
                )
                self.assertEqual(
                    str(error), "Nenhuma fala foi reconhecida. Tente falar novamente."
                )
                self.assertEqual(
                    self.account.secrets.get("clarify_account"), "test-session-only"
                )
                self.assertEqual(self.account.snapshot()["usage"], {"used_ms": 1000})

    def test_non_json_processing_errors_still_use_http_status_and_revoke_auth(self):
        for action, status, expected in [
            (
                "dictation",
                502,
                "Não foi possível transcrever o áudio. Tente novamente.",
            ),
            ("text", 503, "O processamento do Clarify está indisponível no momento."),
            ("text", 401, "Entre na conta novamente."),
        ]:
            with self.subTest(action=action, status=status):
                response = self.response({}, status)
                response.json.side_effect = ValueError("private upstream body")
                self.signed_in()
                self.account._last_sync_attempt = self.account._clock()
                self.request.reset_mock()
                self.request.return_value = response
                with self.assertRaises(AccountError) as caught:
                    if action == "dictation":
                        from provider_http import CancellationToken
                        from workflows import RecordingSnapshot

                        self.account.transcribe(
                            RecordingSnapshot(
                                Path("unused.wav"), b"synthetic", CancellationToken()
                            ),
                            "pt",
                            self.service,
                        )
                    else:
                        self.account.transform_text("Source", "rewrite")
                self.assertEqual(str(caught.exception), expected)
                self.request.assert_called_once()
                if status == 401:
                    self.assertFalse(self.account.hosted)
                    self.assertTrue(self.account.managed)

    def test_account_changed_during_failed_processing_discards_reply_and_usage(self):
        self.signed_in()
        previous = self.account.snapshot()["usage"]

        def respond(*args, **kwargs):
            self.account._generation += 1
            return self.response(
                {"code": "text_processing_failed", "usage": {"used_ms": 999}}, 502
            )

        self.request.side_effect = respond
        with self.assertRaisesRegex(AccountError, "A conta mudou"):
            self.account.transform_text("Source text.", "rewrite")
        self.assertEqual(self.account.snapshot()["usage"], previous)

    def test_existing_signed_in_profiles_process_without_activation_and_fail_closed(
        self,
    ):
        from provider_http import CancellationToken
        from workflows import RecordingSnapshot

        for mode in (None, "personal", "hosted"):
            with self.subTest(mode=mode):
                state = {"user_id": str(uuid.uuid4()), "email": "user@example.test"}
                if mode is not None:
                    state["mode"] = mode
                self.account.path.write_text(json.dumps(state), encoding="utf-8")
                account = AccountService(
                    self.root,
                    secrets=self.account.secrets,
                    request=self.request,
                    default_endpoint="https://clarify.example",
                )
                self.assertTrue(account.hosted)
                account._last_sync_attempt = account._clock()
                self.request.return_value = self.response(
                    {"transcript": "Source.", "text": "Processed.", "rewritten": True}
                )
                result = account.transcribe(
                    RecordingSnapshot(
                        Path("unused.wav"), b"fake audio", CancellationToken()
                    ),
                    "pt",
                    self.service,
                )
                self.assertEqual(result.provider_id, "clarify")
                self.assertEqual(
                    self.request.call_args.args[1],
                    "https://clarify.example/v1/dictations",
                )
                self.request.return_value = self.response({}, 403)
                with self.assertRaises(AccountError):
                    account.refresh()
                restored = AccountService(self.root, secrets=self.account.secrets)
                self.assertFalse(restored.hosted)
                self.assertTrue(restored.managed)

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
        self.assertTrue(self.account.hosted)
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
        self.assertTrue(self.account.managed)

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
