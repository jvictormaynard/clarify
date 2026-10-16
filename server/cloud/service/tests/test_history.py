import copy
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event
from unittest import mock, skipUnless

from allauth.account.models import EmailAddress
from django.apps import apps
from django.db import connection, connections, close_old_connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from .test_api import client_for


def entry(record_id="mobile-1", source="mobile", **values):
    return {
        "id": record_id,
        "createdAt": 1792067053.8,
        "transcript": "Vamos marcar quarta. Na verdade, quinta.",
        "text": "Vamos marcar quinta.",
        "rewritten": True,
        "sourceDevice": source,
        **values,
    }


class HistorySyncTests(TestCase):
    def setUp(self):
        self.a, self.ca = client_for("history-a@example.test")
        self.b, self.cb = client_for("history-b@example.test")

    def sync(self, *, client=None, cursor=0, upserts=None, deletes=None, **extra):
        return (client or self.ca).post(
            "/v1/history/sync",
            {
                "cursor": cursor,
                "upserts": upserts or [],
                "deletes": deletes or [],
                **extra,
            },
            format="json",
        )

    def ok(self, **kwargs):
        response = self.sync(**kwargs)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Cache-Control"], "no-store")
        return response.json()

    def test_two_devices_exchange_original_text_time_and_origin(self):
        first = entry()
        second = entry("desktop-1", "desktop", createdAt=1792067054.5)
        result = self.ok(upserts=[first])
        self.assertEqual(result["entries"], [first])
        other_device = APIClient()
        other_device.force_authenticate(self.a)
        self.ok(client=other_device, upserts=[second])
        result = self.ok(cursor=result["cursor"])
        self.assertEqual(result["entries"], [second])
        self.assertFalse(result["hasMore"])

    def test_retry_is_idempotent_and_does_not_advance_revision(self):
        first = self.ok(upserts=[entry()])
        retry = self.ok(upserts=[entry()])
        self.assertEqual(retry, first)
        self.assertEqual(self.ok(cursor=first["cursor"])["entries"], [])
        model = apps.get_model("service", "HistoryEntry")
        self.assertEqual(model.objects.filter(user=self.a).count(), 1)

    def test_conflicting_id_rejects_entire_batch(self):
        self.ok(upserts=[entry()])
        response = self.sync(upserts=[entry("new"), entry(text="Different text")])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"code": "history_conflict"})
        self.assertEqual(self.ok()["entries"], [entry()])

    def test_accounts_cannot_read_delete_or_clear_each_others_history(self):
        self.ok(upserts=[entry()])
        self.assertEqual(self.ok(client=self.cb)["entries"], [])
        self.ok(client=self.cb, deletes=["mobile-1"])
        self.ok(client=self.cb, clearID=str(uuid.uuid4()))
        self.assertEqual(self.ok()["entries"], [entry()])

    def test_session_verification_and_owner_controls_are_required(self):
        self.assertIn(self.sync(client=APIClient()).status_code, (401, 403))
        self.assertEqual(self.sync(user_id=str(self.b.pk)).status_code, 400)
        response = self.ca.post(
            "/v1/history/sync?user_id=" + str(self.b.pk),
            {"cursor": 0, "upserts": [], "deletes": []},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        EmailAddress.objects.filter(user=self.a).update(verified=False)
        self.assertEqual(self.sync().status_code, 403)

    def test_deletion_purges_text_and_stale_upload_cannot_resurrect_it(self):
        initial = self.ok(upserts=[entry()])
        removed = self.ok(cursor=initial["cursor"], deletes=["mobile-1"])
        self.assertEqual(removed["entries"], [])
        self.assertEqual(removed["deleted"], ["mobile-1"])
        self.assertEqual(self.ok(upserts=[entry()])["deleted"], ["mobile-1"])
        self.assertEqual(self.ok(cursor=removed["cursor"])["deleted"], [])
        model = apps.get_model("service", "HistoryEntry")
        self.assertIsNone(model.objects.get(user=self.a, record_id="mobile-1").payload)

    def test_unknown_delete_also_blocks_an_offline_stale_upload(self):
        self.ok(deletes=["mobile-1"])
        result = self.ok(upserts=[entry()])
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["deleted"], ["mobile-1"])

    def test_clear_is_retry_safe_and_keeps_newer_transcriptions(self):
        self.ok(upserts=[entry(), entry("desktop-1", "desktop")])
        clear_id = str(uuid.uuid4())
        result = self.ok(clearID=clear_id)
        self.assertEqual(result["entries"], [])
        self.assertEqual(set(result["deleted"]), {"mobile-1", "desktop-1"})
        newer = entry("after-clear")
        self.ok(upserts=[newer])
        retry = self.ok(clearID=clear_id)
        self.assertEqual(retry["entries"], [newer])
        self.assertEqual(set(retry["deleted"]), {"mobile-1", "desktop-1"})

    def test_pending_old_cursor_after_clear_never_receives_deleted_text(self):
        self.ok(upserts=[entry(str(i)) for i in range(45)])
        response = self.ok(clearID=str(uuid.uuid4()))
        self.assertEqual(response["entries"], [])
        seen = list(response["deleted"])
        while response["hasMore"]:
            response = self.ok(cursor=response["cursor"])
            self.assertEqual(response["entries"], [])
            seen.extend(response["deleted"])
        self.assertEqual(set(seen), {str(i) for i in range(45)})
        self.assertEqual(len(seen), 45)

    def test_pages_are_bounded_and_mutations_between_pages_are_not_lost(self):
        initial = [entry(str(i)) for i in range(45)]
        result = self.ok(upserts=initial)
        self.assertEqual(len(result["entries"]), 20)
        self.assertTrue(result["hasMore"])
        seen = result["entries"][:]
        # Delete an already seen record and add one while another device pages.
        self.ok(upserts=[entry("late")], deletes=["0"])
        removed = []
        while result["hasMore"]:
            result = self.ok(cursor=result["cursor"])
            seen.extend(result["entries"])
            removed.extend(result["deleted"])
        self.assertEqual(
            {item["id"] for item in seen}, {str(i) for i in range(45)} | {"late"}
        )
        self.assertEqual(removed, ["0"])
        self.assertEqual(self.ok(cursor=result["cursor"])["cursor"], result["cursor"])

    def test_page_json_stays_below_existing_transport_response_bound(self):
        for i in range(8):
            self.ok(upserts=[entry(str(i), text="x" * 32768, transcript="y" * 32768)])
        response = self.sync()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertLessEqual(len(response.content), 400 * 1024)
        self.assertTrue(response.json()["hasMore"])
        self.assertGreater(len(response.json()["entries"]), 0)

    def test_entry_and_request_validation_does_not_partially_save(self):
        invalid_entries = [
            entry(id=""),
            entry(id="../other"),
            entry(id="x" * 129),
            entry(id="á"),
            entry(createdAt=True),
            entry(createdAt=0),
            entry(createdAt=4102444800),
            entry(createdAt="NaN"),
            entry(text="  "),
            entry(text="é" * 16385),
            entry(transcript="x" * 32769),
            entry(rewritten=1),
            entry(sourceDevice="unknown"),
            entry(owner=str(self.b.pk)),
        ]
        for invalid in invalid_entries:
            with self.subTest(invalid=repr(invalid)[:100]):
                self.assertEqual(
                    self.sync(upserts=[entry("valid"), invalid]).status_code, 400
                )
        invalid_requests = [
            {"cursor": True},
            {"cursor": -1},
            {"cursor": 99},
            {"upserts": [entry(str(i)) for i in range(51)]},
            {"deletes": [str(i) for i in range(51)]},
            {"deletes": [False]},
            {"deletes": ["../other"]},
            {"upserts": [entry(), entry()]},
            {"upserts": [entry()], "deletes": ["mobile-1"]},
            {"clearID": "not-a-uuid"},
            {"clearID": str(uuid.uuid4()), "upserts": [entry()]},
        ]
        for invalid in invalid_requests:
            with self.subTest(request=repr(invalid)[:100]):
                payload = {"cursor": 0, "upserts": [], "deletes": [], **invalid}
                response = self.ca.post("/v1/history/sync", payload, format="json")
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.ok()["entries"], [])

    def test_invalid_json_nonfinite_timestamp_is_rejected(self):
        payload = copy.deepcopy(entry())
        payload["createdAt"] = float("inf")
        import json

        response = self.ca.post(
            "/v1/history/sync",
            json.dumps({"cursor": 0, "upserts": [payload], "deletes": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_encoded_request_bound_and_maximum_escaped_entry(self):
        maximum = entry(text="\x01" * 32768, transcript="\x02" * 32768)
        result = self.ok(upserts=[maximum])
        self.assertEqual(result["entries"], [maximum])
        # Two entries fit the HTTP guard but exceed the sync request budget.
        oversized = [
            entry(str(i), text="x" * 32768, transcript="y" * 32768) for i in range(7)
        ]
        self.assertEqual(self.sync(upserts=oversized).status_code, 400)

    def test_clear_operation_capacity_is_atomic_and_existing_retries_still_work(self):
        from cloud.service import history

        clear_id = str(uuid.uuid4())
        with mock.patch.object(history, "MAX_CLEAR_IDS", 1):
            self.ok(clearID=clear_id)
            self.ok(upserts=[entry()])
            self.assertEqual(self.sync(clearID=str(uuid.uuid4())).status_code, 507)
            self.assertEqual(self.ok(clearID=clear_id)["entries"], [entry()])

    def test_account_deletion_cascades_history_without_affecting_other_account(self):
        self.ok(upserts=[entry()])
        self.ok(client=self.cb, upserts=[entry("other")])
        self.ok(clearID=str(uuid.uuid4()))
        response = self.ca.delete("/v1/account", {"confirm": True}, format="json")
        self.assertEqual(response.status_code, 204, response.content)
        for name in ("HistoryEntry", "HistoryState", "HistoryClear"):
            model = apps.get_model("service", name)
            self.assertFalse(model.objects.filter(user_id=self.a.pk).exists())
        self.assertEqual(self.ok(client=self.cb)["entries"], [entry("other")])

    def test_storage_capacity_rejects_atomically_and_delete_frees_text_space(self):
        from cloud.service import history

        with mock.patch.object(history, "MAX_ACCOUNT_BYTES", 400):
            first = self.ok(upserts=[entry()])
            rejected = self.sync(upserts=[entry("new", text="x" * 400)])
            self.assertEqual(rejected.status_code, 507)
            self.assertEqual(rejected.json(), {"code": "history_full"})
            self.assertEqual(self.ok(), first)
            # Replacing space through an explicit deletion is allowed, and the
            # tombstone still prevents a later retry from restoring old text.
            self.ok(upserts=[entry("new")], deletes=["mobile-1"])

    def test_id_capacity_never_discards_existing_history_or_tombstones(self):
        from cloud.service import history

        with mock.patch.object(history, "MAX_ACCOUNT_IDS", 1):
            self.ok(upserts=[entry()])
            self.assertEqual(self.sync(upserts=[entry("other")]).status_code, 507)
            self.ok(deletes=["mobile-1"])
            self.assertEqual(self.ok(upserts=[entry()])["entries"], [])
            self.assertEqual(self.sync(deletes=["unknown"]).status_code, 507)


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL row locks")
class HistoryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user, self.client = client_for("history-concurrency@example.test")

    def concurrent(self, payloads):
        from cloud.service import history

        barrier = Barrier(len(payloads))

        def submit(payload):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return history.synchronize(self.user, payload)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
            return list(pool.map(submit, payloads))

    def payload(self, *, upserts=None, deletes=None):
        return {"cursor": 0, "upserts": upserts or [], "deletes": deletes or []}

    def test_concurrent_first_sync_and_retry_are_once_only(self):
        self.concurrent(
            [self.payload(upserts=[entry()]), self.payload(upserts=[entry()])]
        )
        model = apps.get_model("service", "HistoryEntry")
        self.assertEqual(model.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            apps.get_model("service", "HistoryState")
            .objects.get(user=self.user)
            .revision,
            1,
        )

    def test_concurrent_devices_do_not_lose_records_or_share_revisions(self):
        self.concurrent(
            [
                self.payload(upserts=[entry()]),
                self.payload(upserts=[entry("desktop-1", "desktop")]),
            ]
        )
        rows = list(
            apps.get_model("service", "HistoryEntry").objects.filter(user=self.user)
        )
        self.assertEqual({row.record_id for row in rows}, {"mobile-1", "desktop-1"})
        self.assertEqual({row.revision for row in rows}, {1, 2})

    def test_concurrent_delete_wins_over_upload_in_either_order(self):
        self.concurrent(
            [self.payload(upserts=[entry()]), self.payload(deletes=["mobile-1"])]
        )
        row = apps.get_model("service", "HistoryEntry").objects.get(
            user=self.user, record_id="mobile-1"
        )
        self.assertIsNone(row.payload)

    def test_account_delete_locks_parent_before_collecting_history_children(self):
        from django.db.models.query import QuerySet
        from rest_framework.exceptions import PermissionDenied
        from cloud.service import history
        from cloud.service.models import HistoryEntry

        children_removed, release_delete, sync_started = Event(), Event(), Event()
        original = QuerySet._raw_delete

        def pause_after_children(query, using):
            result = original(query, using)
            if query.model is HistoryEntry:
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

        def sync_during_delete():
            close_old_connections()
            try:
                sync_started.set()
                try:
                    history.synchronize(self.user, self.payload(upserts=[entry()]))
                    return "inserted"
                except PermissionDenied:
                    return "account_deleted"
            finally:
                connections.close_all()

        with (
            mock.patch.object(QuerySet, "_raw_delete", pause_after_children),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            removal = pool.submit(remove_account)
            try:
                self.assertTrue(children_removed.wait(timeout=5))
                syncing = pool.submit(sync_during_delete)
                self.assertTrue(sync_started.wait(timeout=5))
                # A previously verified request cannot insert children after
                # Django's deletion collector has passed them.
                with self.assertRaises(TimeoutError):
                    syncing.result(timeout=0.25)
            finally:
                release_delete.set()
            self.assertEqual(removal.result(timeout=5), 204)
            self.assertEqual(syncing.result(timeout=5), "account_deleted")
        self.assertFalse(HistoryEntry.objects.filter(user_id=self.user.pk).exists())
