import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from .test_api import client_for


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

    def test_account_delete_prevents_late_library_insertion(self):
        from cloud.service.models import Dictionary, SnippetLibrary

        for model, path, entries in (
            (SnippetLibrary, "/v1/snippets", [ENTRY]),
            (Dictionary, "/v1/dictionary", [{"term": "Clarify"}]),
        ):
            with self.subTest(path=path):
                self.user, self.client = client_for(
                    path.rsplit("/", 1)[-1] + "@example.test"
                )
                self._assert_delete_prevents_late_insertion(model, path, entries)

    def _assert_delete_prevents_late_insertion(self, model, path, entries):
        from django.db.models.query import QuerySet

        children_removed, release_delete, saving_started = Event(), Event(), Event()
        original = QuerySet._raw_delete

        def pause_after_children(query, using):
            result = original(query, using)
            if query.model is model:
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
                    path, {"revision": 0, "entries": entries}, format="json"
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
        self.assertFalse(model.objects.filter(user_id=self.user.pk).exists())
