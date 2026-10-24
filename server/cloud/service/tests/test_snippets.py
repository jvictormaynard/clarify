import json
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from cloud.service import api, groq, ledger
from cloud.service.models import Allowance, Operation
from .test_api import client_for
from . import test_dictation


ENTRY = {
    "trigger": "minha assinatura",
    "replacement": "João Victor\nEngenharia",
    "enabled": True,
    "case_sensitive": False,
}


class SnippetLibraryTests(TestCase):
    def setUp(self):
        self.a, self.ca = client_for("a@example.test")
        self.b, self.cb = client_for("b@example.test")

    def test_session_verification_and_session_ownership_are_required(self):
        self.assertIn(APIClient().get("/v1/snippets").status_code, (401, 403))
        self.assertEqual(
            self.ca.get("/v1/snippets?user_id=" + str(self.b.pk)).status_code, 400
        )
        EmailAddress.objects.filter(user=self.a).update(verified=False)
        self.assertEqual(self.ca.get("/v1/snippets").status_code, 403)

    def test_library_is_scoped_revisioned_and_validated(self):
        self.assertEqual(
            self.ca.get("/v1/snippets").json(), {"revision": 0, "entries": []}
        )
        payload = {"revision": 0, "entries": [ENTRY]}
        saved = self.ca.put("/v1/snippets", payload, format="json")
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json(), {"revision": 1, "entries": [ENTRY]})
        self.assertEqual(self.cb.get("/v1/snippets").json()["entries"], [])
        self.assertEqual(
            self.ca.put("/v1/snippets", payload, format="json").status_code, 409
        )
        for invalid in (
            {**payload, "user_id": str(self.b.pk)},
            {"revision": True, "entries": []},
            {"revision": -1, "entries": []},
            {"revision": 1, "entries": [ENTRY, ENTRY]},
            {"revision": 1, "entries": [{**ENTRY, "replacement": "x" * 4097}]},
            {"revision": 1, "entries": [{**ENTRY, "enabled": "yes"}]},
            {"revision": 1, "entries": [{**ENTRY, "replacement": " "}]},
            {"revision": 1, "entries": [{**ENTRY, "extra": "unsupported"}]},
            {"revision": 1, "entries": "unsupported"},
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(
                    self.ca.put("/v1/snippets", invalid, format="json").status_code, 400
                )
        self.assertEqual(self.ca.get("/v1/snippets").json()["entries"], [ENTRY])

    def test_old_dictionary_clients_do_not_erase_snippets_and_deletion_cascades(self):
        self.ca.put("/v1/snippets", {"revision": 0, "entries": [ENTRY]}, format="json")
        self.ca.put("/v1/dictionary", {"revision": 0, "entries": []}, format="json")
        self.assertEqual(self.ca.get("/v1/snippets").json()["entries"], [ENTRY])
        self.assertEqual(
            self.ca.delete("/v1/account", {"confirm": True}, format="json").status_code,
            204,
        )
        from cloud.service.models import SnippetLibrary

        self.assertFalse(SnippetLibrary.objects.filter(user_id=self.a.pk).exists())
        self.assertEqual(self.cb.get("/v1/snippets").status_code, 200)

    def test_account_library_utf8_limit_preserves_last_valid_revision(self):
        entries = [
            {**ENTRY, "trigger": f"trecho {index}", "replacement": "文" * 4096}
            for index in range(21)
        ]

        def encoded_size(values):
            return len(
                json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )

        self.assertLess(encoded_size(entries), 262144)
        accepted = self.ca.put(
            "/v1/snippets", {"revision": 0, "entries": entries}, format="json"
        )
        self.assertEqual(accepted.status_code, 200, accepted.content)
        too_large = [
            *entries,
            {**ENTRY, "trigger": "outro trecho", "replacement": "文" * 4096},
        ]
        self.assertGreater(encoded_size(too_large), 262144)
        rejected = self.ca.put(
            "/v1/snippets", {"revision": 1, "entries": too_large}, format="json"
        )
        self.assertEqual(rejected.status_code, 400, rejected.content)
        self.assertEqual(rejected.json(), {"code": "snippets_too_large"})
        self.assertEqual(
            self.ca.get("/v1/snippets").json(), {"revision": 1, "entries": entries}
        )


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class HostedSnippetTests(TestCase):
    def setUp(self):
        self.user, self.client = client_for("dictation@example.test")
        self.assertEqual(
            self.client.put(
                "/v1/snippets", {"revision": 0, "entries": [ENTRY]}, format="json"
            ).status_code,
            200,
        )

    def send(self, operation):
        return test_dictation.DictationTests.send(self, operation)

    @patch("cloud.service.groq.perform")
    def test_standalone_expands_once_without_rewrite_and_replays_saved_result(
        self, provider
    ):
        provider.return_value = {"text": "Minha assinatura."}
        operation = uuid.uuid4()
        response = self.send(operation)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], ENTRY["replacement"])
        self.assertEqual(response.json()["transcript"], "Minha assinatura.")
        self.assertFalse(response.json()["rewritten"])
        self.assertTrue(response.json()["snippet_expanded"])
        self.assertEqual(self.send(operation).json(), response.json())
        self.assertEqual(provider.call_count, 1)
        self.assertIn(ENTRY["trigger"], provider.call_args.kwargs["data"]["prompt"])
        self.assertNotIn(ENTRY["replacement"], str(provider.call_args))

    @patch("cloud.service.groq.perform")
    def test_inline_expands_when_rewrite_fails_without_sending_saved_content(
        self, provider
    ):
        provider.side_effect = [
            {"text": "Atenciosamente, minha assinatura."},
            groq.ProviderFailure(),
        ]
        response = self.send(uuid.uuid4())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()["text"], "Atenciosamente, " + ENTRY["replacement"] + "."
        )
        self.assertFalse(response.json()["rewritten"])
        self.assertTrue(response.json()["snippet_expanded"])
        self.assertNotIn(ENTRY["replacement"], str(provider.call_args_list))

    @patch("cloud.service.groq.perform")
    def test_refined_inline_text_expands_once_and_preserves_saved_content(
        self, provider
    ):
        provider.side_effect = [
            {"text": "atenciosamente minha assinatura"},
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Atenciosamente, minha assinatura."},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        ]
        response = self.send(uuid.uuid4())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()["text"], "Atenciosamente, " + ENTRY["replacement"] + "."
        )
        self.assertTrue(response.json()["rewritten"])
        self.assertNotIn(ENTRY["replacement"], str(provider.call_args_list))

    @patch("cloud.service.groq.perform")
    def test_disabled_snippets_and_other_accounts_do_not_expand(self, provider):
        self.client.put(
            "/v1/snippets",
            {"revision": 1, "entries": [{**ENTRY, "enabled": False}]},
            format="json",
        )
        provider.side_effect = [{"text": "Minha assinatura."}, groq.ProviderFailure()]
        response = self.send(uuid.uuid4())
        self.assertEqual(response.json()["text"], "Minha assinatura.")
        self.assertFalse(response.json().get("snippet_expanded", False))
        self.assertNotIn("prompt", provider.call_args_list[0].kwargs["data"])
        _, self.client = client_for("other@example.test")
        provider.side_effect = [{"text": "Minha assinatura."}, groq.ProviderFailure()]
        self.assertEqual(self.send(uuid.uuid4()).json()["text"], "Minha assinatura.")

    @patch("cloud.service.groq.perform")
    def test_exact_result_boundary_and_replayed_size_error_charge_once(self, provider):
        provider.return_value = {"text": "Minha assinatura."}
        usage = {**ledger.usage(self.user), "used_ms": 1000}
        expected = {
            "transcript": "Minha assinatura.",
            "text": ENTRY["replacement"],
            "rewritten": False,
            "snippet_expanded": True,
            "usage": usage,
        }
        size = len(
            json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        with patch.object(api, "MAX_DICTATION_RESULT_BYTES", size):
            accepted = self.send(uuid.uuid4())
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertEqual(accepted.json(), expected)
        operation_id = uuid.uuid4()
        with (
            patch.object(api, "MAX_DICTATION_RESULT_BYTES", size - 1),
            self.assertLogs("cloud.service.api", level="WARNING") as logs,
        ):
            rejected = self.send(operation_id)
        self.assertEqual(rejected.status_code, 422, rejected.content)
        self.assertEqual(rejected.json()["code"], "snippet_result_too_large")
        self.assertEqual(rejected.json()["phase"], "processing")
        self.assertNotIn(ENTRY["replacement"], " ".join(logs.output))
        self.assertNotIn("text", rejected.json())
        replay = self.send(operation_id)
        self.assertEqual(replay.status_code, 422)
        self.assertEqual(replay.json(), rejected.json())
        self.assertEqual(provider.call_count, 2)
        saved = Operation.objects.get(operation_id=operation_id)
        self.assertEqual(saved.cost, ledger.MAX_COST)
        self.assertNotIn("text", saved.result)
        allowance = Allowance.objects.get(user=self.user)
        self.assertEqual(
            (allowance.used_ms, allowance.reserved_ms, allowance.operations),
            (2000, 0, 2),
        )

    @patch("cloud.service.groq.perform")
    def test_actual_large_expansion_fails_without_partial_saved_text(self, provider):
        long_entry = {**ENTRY, "replacement": "文" * 4096}
        self.client.put(
            "/v1/snippets", {"revision": 1, "entries": [long_entry]}, format="json"
        )
        provider.side_effect = [
            {"text": ", ".join([ENTRY["trigger"]] * 256)},
            groq.ProviderFailure(),
        ]
        operation_id = uuid.uuid4()
        response = self.send(operation_id)
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()["code"], "snippet_result_too_large")
        self.assertNotIn("text", response.json())
        self.assertNotIn(long_entry["replacement"], str(provider.call_args_list))
        self.assertEqual(self.send(operation_id).status_code, 422)
        self.assertEqual(provider.call_count, 2)


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL row locks")
class SnippetConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user, self.client = client_for("snippet-concurrency@example.test")

    def concurrent(self, requests):
        barrier = Barrier(len(requests))

        def submit(item):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.user)
                barrier.wait(timeout=5)
                path, payload = item
                return client.put(path, payload, format="json").status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(submit, requests))

    def test_concurrent_first_write_has_one_winner(self):
        first = {"revision": 0, "entries": [ENTRY]}
        other = {
            "revision": 0,
            "entries": [{**ENTRY, "replacement": "Outra assinatura"}],
        }
        statuses = self.concurrent([("/v1/snippets", first), ("/v1/snippets", other)])
        self.assertCountEqual(statuses, [200, 409])
        saved = self.client.get("/v1/snippets").json()
        self.assertEqual(saved["revision"], 1)
        self.assertIn(saved["entries"], [first["entries"], other["entries"]])

    def test_old_dictionary_write_and_snippet_write_are_independent(self):
        self.assertEqual(
            self.concurrent(
                [
                    (
                        "/v1/dictionary",
                        {"revision": 0, "entries": [{"term": "Clarify"}]},
                    ),
                    ("/v1/snippets", {"revision": 0, "entries": [ENTRY]}),
                ]
            ),
            [200, 200],
        )
        self.assertEqual(self.client.get("/v1/snippets").json()["entries"], [ENTRY])
        self.assertEqual(
            self.client.get("/v1/dictionary").json()["entries"][0]["term"], "Clarify"
        )

    def test_account_delete_prevents_late_snippet_insertion(self):
        from django.db.models.query import QuerySet
        from cloud.service.models import SnippetLibrary

        children_removed, release_delete, saving_started = Event(), Event(), Event()
        original = QuerySet._raw_delete

        def pause_after_children(query, using):
            result = original(query, using)
            if query.model is SnippetLibrary:
                children_removed.set()
                if not release_delete.wait(timeout=5):
                    raise RuntimeError("Test deletion release timed out")
            return result

        def remove_account():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.user)
                return client.delete(
                    "/v1/account", {"confirm": True}, format="json"
                ).status_code
            finally:
                connections.close_all()

        def save_during_delete():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.user)
                saving_started.set()
                return client.put(
                    "/v1/snippets", {"revision": 0, "entries": [ENTRY]}, format="json"
                ).status_code
            finally:
                connections.close_all()

        with (
            patch.object(QuerySet, "_raw_delete", pause_after_children),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            removal = pool.submit(remove_account)
            try:
                self.assertTrue(children_removed.wait(timeout=5))
                saving = pool.submit(save_during_delete)
                self.assertTrue(saving_started.wait(timeout=5))
                with self.assertRaises(TimeoutError):
                    saving.result(timeout=0.25)
            finally:
                release_delete.set()
            self.assertEqual(removal.result(timeout=5), 204)
            self.assertIn(saving.result(timeout=5), (401, 403))
        self.assertFalse(SnippetLibrary.objects.filter(user_id=self.user.pk).exists())
