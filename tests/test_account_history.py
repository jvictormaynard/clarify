"""Isolated account history ownership, durability and wire contracts."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import uuid

from clarify_account import AccountService, AccountError
from history_store import HistoryRecord, HistoryStore
from secret_store import PlaintextFileSecretStore


class AccountHistoryTests(unittest.TestCase):
    def setUp(self):
        from account_history import AccountHistory

        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.http = Mock()
        self.now = 0
        self.account = AccountService(
            self.root,
            secrets=PlaintextFileSecretStore(self.root / "secrets.json"),
            request=self.http,
            default_endpoint="https://clarify.example",
        )
        self.local = HistoryStore(
            self.root / "history.json", enabled=True, retention_days=None
        )
        self.history = AccountHistory(self.account, self.local, clock=lambda: self.now)

    def response(self, payload, status=200):
        response = Mock(status_code=status, content=b"json")
        response.json.return_value = payload
        return response

    def sign_in(self, user=None):
        self.http.return_value = self.response(
            {"id": user or str(uuid.uuid4()), "email": "test@example.test"}
        )
        self.account.secrets.set("clarify_account", "isolated-session")
        self.account.refresh()
        self.http.reset_mock()
        return self.account.history_identity()

    def record(self, value="Revised.", record_id=None):
        return HistoryRecord(
            raw_text="Original.",
            refined_text=value,
            provider="clarify",
            model="asr",
            refinement_model="text-model",
            timestamp=datetime(2026, 10, 16, tzinfo=timezone.utc),
            record_id=record_id or uuid.uuid4().hex,
        )

    def page(self, entries=(), deleted=(), cursor=1, more=False):
        self.http.return_value = self.response(
            {
                "cursor": cursor,
                "entries": list(entries),
                "deleted": list(deleted),
                "hasMore": more,
            }
        )

    def test_guest_and_legacy_never_upload_account_records_persist_without_guest_toggle(
        self,
    ):
        legacy = self.record("Legacy.")
        self.local.append(legacy)
        self.history.sync(force=True)
        self.http.assert_not_called()
        owner = self.sign_in()
        self.history.append(self.record(), owner)
        self.assertEqual(len(self.history.list_records()), 2)
        self.page()
        self.history.sync(force=True)
        submitted = self.http.call_args.kwargs["json"]["upserts"]
        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0]["text"], "Revised.")
        self.assertEqual(submitted[0]["sourceDevice"], "desktop")
        self.assertEqual(self.history.list_records()[0].refinement_model, "text-model")
        self.http.return_value = self.response({}, 204)
        self.account.logout()
        self.assertEqual([r.id for r in self.history.list_records()], [legacy.id])

    def test_failure_restart_duplicate_retry_and_mobile_origin(self):
        from account_history import AccountHistory

        owner = self.sign_in()
        record = self.record()
        self.history.append(record, owner)
        self.http.side_effect = OSError("offline")
        with self.assertRaises(OSError):
            self.history.sync(force=True)
        self.http.side_effect = None
        self.history = AccountHistory(self.account, self.local, clock=lambda: self.now)
        mobile = {
            "id": "mobile-1",
            "createdAt": record.timestamp.timestamp(),
            "transcript": "Said.",
            "text": "Written.",
            "rewritten": True,
            "sourceDevice": "mobile",
        }
        self.page([mobile], cursor=1)
        self.history.sync(force=True)
        self.assertEqual(len(self.http.call_args.kwargs["json"]["upserts"]), 1)
        self.page([mobile], cursor=2)
        self.history.sync(force=True)
        self.assertEqual(self.http.call_args.kwargs["json"]["upserts"], [])
        self.assertEqual(len(self.history.list_records()), 2)
        self.assertEqual(
            next(
                r for r in self.history.list_records() if r.id == "mobile-1"
            ).source_device,
            "mobile",
        )

    def test_stale_owner_rejected_and_endpoint_is_part_of_scope(self):
        owner = self.sign_in()
        record = self.record()
        self.http.return_value = self.response({}, 204)
        self.account.logout()
        other = self.sign_in()
        self.assertFalse(self.history.append(record, owner))
        self.assertEqual(self.history.list_records(), [])
        self.history.append(record, other)
        self.http.return_value = self.response({}, 204)
        self.account.logout()
        self.account.configure("https://other.example")
        self.sign_in(other.user_id)
        self.assertEqual(self.history.list_records(), [])

    def test_late_response_and_expiry_cannot_apply_to_another_account_or_guest(self):
        owner = self.sign_in()
        self.history.append(self.record(), owner)

        def change(*args, **kwargs):
            self.account._generation += 1
            self.account._state["user_id"] = str(uuid.uuid4())
            return self.response(
                {"cursor": 1, "entries": [], "deleted": [], "hasMore": False}
            )

        self.http.side_effect = change
        with self.assertRaises(AccountError):
            self.history.sync(force=True)
        self.assertEqual(self.history.list_records(), [])
        self.http.side_effect = None
        self.http.return_value = self.response({}, 401)
        with self.assertRaises(AccountError):
            self.history.sync(force=True)
        self.assertTrue(self.account.managed)
        self.assertFalse(self.history.append(self.record(), owner))
        self.assertEqual(self.local.list_records(), [])

    def test_delete_tombstone_clear_retry_and_new_record_after_clear(self):
        owner = self.sign_in()
        record = self.record()
        self.history.append(record, owner)
        self.page(cursor=1)
        self.history.sync(force=True)
        self.history.delete(record.id)
        self.page(cursor=2)
        self.history.sync(force=True)
        self.assertEqual(self.http.call_args.kwargs["json"]["deletes"], [record.id])
        self.history.append(self.record("Before clear."), owner)
        self.history.clear()
        self.history.append(self.record("After clear."), owner)
        self.http.return_value = self.response({}, 503)
        with self.assertRaises(AccountError):
            self.history.sync(force=True)
        clear_id = self.http.call_args.kwargs["json"]["clearID"]
        self.now += 60
        self.page(cursor=3)
        self.history.sync(force=True)
        calls = [c.kwargs["json"] for c in self.http.call_args_list]
        self.assertTrue(any(c.get("clearID") == clear_id for c in calls))
        self.assertEqual(calls[-1]["upserts"][0]["text"], "After clear.")
        self.assertNotIn("clearID", calls[-1])

    def test_bad_page_or_atomic_failure_preserves_cursor_and_outbox(self):
        owner = self.sign_in()
        self.history.append(self.record(), owner)
        self.page(cursor=-1)
        with self.assertRaises(ValueError):
            self.history.sync(force=True)
        self.now += 60
        self.page(cursor=1)
        with patch("account_history._atomic_write_text", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.history.sync(force=True)
        self.now += 60
        self.history.sync(force=True)
        self.assertEqual(len(self.http.call_args.kwargs["json"]["upserts"]), 1)
        self.assertEqual(self.http.call_args.kwargs["json"]["cursor"], 0)

    def test_coalesces_polling_and_drains_bounded_pages_without_dropping_work(self):
        self.sign_in()
        pages = iter(range(1, 30))
        self.http.side_effect = lambda *a, **k: self.response(
            {"cursor": next(pages), "entries": [], "deleted": [], "hasMore": True}
        )
        self.history.sync()
        self.assertLessEqual(self.http.call_count, 5)
        before = self.http.call_count
        self.history.sync()
        self.assertEqual(before, self.http.call_count)
        self.now += 60
        self.page(cursor=before + 1)
        self.http.side_effect = None
        self.history.sync()
        self.assertEqual(self.http.call_args.kwargs["json"]["cursor"], before)

    def test_native_metadata_survives_restart_and_legacy_id_collision_is_local(self):
        from account_history import AccountHistory

        owner = self.sign_in()
        record = self.record()
        self.history.append(record, owner)
        self.local.append(record)
        self.history = AccountHistory(self.account, self.local)
        self.history.delete("local:" + record.id)
        self.assertEqual(self.local.list_records(), [])
        self.assertEqual(len(self.history.list_records()), 1)
        self.assertEqual(self.history.list_records()[0].refinement_model, "text-model")
        self.page()
        self.history.sync(force=True)
        self.assertEqual(self.http.call_args.kwargs["json"]["deletes"], [])

    def test_browsing_and_deleting_old_local_data_does_not_prune_other_legacy_rows(
        self,
    ):
        from dataclasses import replace

        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        first, second = (
            replace(self.record("First."), timestamp=old),
            replace(self.record("Second."), timestamp=old),
        )
        self.local.append(first)
        self.local.append(second)
        self.local.enabled = False
        self.local.retention_days = 30
        self.assertEqual(len(self.history.list_records()), 2)
        self.history.delete("local:" + first.id)
        self.assertEqual(
            [record.id for record in self.history.list_records()], [second.id]
        )

    def test_delete_unknown_and_remote_tombstone_never_resurrect_pending_entry(self):
        owner = self.sign_in()
        record = self.record()
        self.history.append(record, owner)
        wire = self.history._read(owner)["pending"][record.id]
        self.page(deleted=[record.id], cursor=1)
        self.history.sync(force=True)
        self.assertEqual(self.history.list_records(), [])
        self.page(entries=[wire], cursor=2)
        self.history.sync(force=True)
        self.assertEqual(self.history.list_records(), [])

    def test_conflict_or_old_schema_does_not_lose_pending_records(self):
        owner = self.sign_in()
        record = self.record()
        self.history.append(record, owner)
        before = self.history._path(owner).read_bytes()
        self.http.return_value = self.response({"code": "history_conflict"}, 409)
        with self.assertRaises(AccountError):
            self.history.sync(force=True)
        self.assertEqual(before, self.history._path(owner).read_bytes())
        self.now += 60
        self.http.return_value = self.response({}, 404)
        with self.assertRaises(AccountError):
            self.history.sync(force=True)
        self.assertEqual(before, self.history._path(owner).read_bytes())

    def test_large_unicode_batches_fit_actual_request_encoding(self):
        import json

        owner = self.sign_in()
        for _ in range(10):
            self.history.append(self.record("é" * 16000), owner)
        self.page(cursor=1)
        self.history.sync(force=True)
        self.assertGreater(self.http.call_count, 1)
        self.assertTrue(
            all(
                len(json.dumps(call.kwargs["json"]).encode()) <= 400 * 1024
                for call in self.http.call_args_list
            )
        )

    def test_account_delete_removes_only_current_scope_cache(self):
        owner = self.sign_in()
        self.history.append(self.record(), owner)
        old_path = self.history._path(owner)
        self.http.return_value = self.response({}, 204)
        self.account.logout()
        current = self.sign_in()
        self.history.append(self.record(), current)
        self.account.history = self.history
        self.http.return_value = self.response({}, 204)
        self.account.logout(delete=True)
        self.assertTrue(old_path.is_file())
        self.assertFalse(self.history._path(current).exists())

    def test_clear_remote_page_keeps_new_local_records_and_no_stale_repopulation(self):
        owner = self.sign_in()
        first = self.record()
        self.history.append(first, owner)
        old_wire = self.history._read(owner)["pending"][first.id]
        self.history.clear()
        after = self.record("After.")
        self.history.append(after, owner)
        self.http.side_effect = [
            self.response(
                {"cursor": 1, "entries": [], "deleted": [first.id], "hasMore": True}
            ),
            self.response(
                {"cursor": 2, "entries": [old_wire], "deleted": [], "hasMore": False}
            ),
        ]
        self.history.sync(force=True)
        self.assertEqual(
            [record.id for record in self.history.list_records()], [after.id]
        )

    def test_unchanged_remote_poll_does_not_rewrite_the_local_snapshot(self):
        self.sign_in()
        self.page(cursor=0)
        with patch("account_history._atomic_write_text") as write:
            self.history.sync(force=True)
            write.assert_not_called()
