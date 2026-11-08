"""Exercise the production desktop cache against the actual account API.

The mobile side sends the documented native wire format. All sessions, text,
profiles and databases are synthetic; there is no HTTP server or provider call.
"""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import urlsplit
import json

import requests
from django.test import TestCase
from rest_framework.test import APIClient

from account_history import AccountHistory
from clarify_account import AccountError, AccountService
from history_store import HistoryRecord, HistoryStore
from secret_store import PlaintextFileSecretStore

from .test_api import client_for
from .test_history import entry


class HistoryClientIntegrationTests(TestCase):
    def setUp(self):
        self.user, self.mobile = client_for("history-integration@example.test")
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.now = 0
        self.drop_history_response = False
        self.calls = []
        self.account = AccountService(
            self.directory,
            secrets=PlaintextFileSecretStore(self.directory / "secrets.json"),
            request=self.transport,
            default_endpoint="https://clarify.example.test",
            clock=lambda: self.now,
        )
        self.local = HistoryStore(
            self.directory / "history.json", enabled=True, retention_days=None
        )
        self.history = AccountHistory(self.account, self.local, clock=lambda: self.now)
        self.account.history = self.history

    def transport(self, method, url, **kwargs):
        path = urlsplit(url).path
        self.calls.append(path)
        self.assertFalse(kwargs["allow_redirects"])
        token = kwargs["headers"].get("X-Session-Token", "")
        client = APIClient(HTTP_X_SESSION_TOKEN=token)
        response = client.generic(
            method,
            path,
            data=json.dumps(kwargs.get("json", {})),
            content_type="application/json",
        )
        if path == "/v1/history/sync" and self.drop_history_response:
            raise requests.ConnectionError(
                "Synthetic lost response after server commit"
            )
        payload = response.json() if response.content else {}
        return SimpleNamespace(
            status_code=response.status_code,
            content=response.content,
            json=lambda: payload,
        )

    def sign_in(self):
        # This is a real isolated allauth session created by client_for.
        self.account.secrets.set(
            "clarify_account", self.mobile.defaults["HTTP_X_SESSION_TOKEN"]
        )
        self.account.refresh()
        return self.account.history_identity()

    def record(self, record_id, *, text="Desktop revised text"):
        return HistoryRecord(
            raw_text="Desktop original text",
            refined_text=text,
            timestamp=datetime(2026, 10, 16, tzinfo=timezone.utc),
            record_id=record_id,
            provider="clarify",
            model="managed",
        )

    def mobile_sync(self, *, cursor=0, upserts=None, deletes=None):
        response = self.mobile.post(
            "/v1/history/sync",
            {"cursor": cursor, "upserts": upserts or [], "deletes": deletes or []},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_both_device_origins_and_deletions_round_trip_without_uploading_legacy(
        self,
    ):
        legacy = self.record("legacy-local")
        self.local.append(legacy)
        owner = self.sign_in()
        self.history.append(self.record("desktop-new"), owner)
        self.history.sync(force=True)
        mobile_result = self.mobile_sync(upserts=[entry("mobile-new")])
        self.assertEqual(
            {item["id"] for item in mobile_result["entries"]},
            {"desktop-new", "mobile-new"},
        )
        self.assertEqual(
            {item["sourceDevice"] for item in mobile_result["entries"]},
            {"desktop", "mobile"},
        )
        self.history.sync(force=True)
        records = {record.id: record for record in self.history.list_records()}
        self.assertEqual(set(records), {"legacy-local", "desktop-new", "mobile-new"})
        self.assertEqual(records["mobile-new"].source_device, "mobile")
        self.assertEqual(records["desktop-new"].provider, "clarify")
        self.history.delete("account:desktop-new")
        self.history.sync(force=True)
        self.assertEqual(
            self.mobile_sync(cursor=mobile_result["cursor"])["deleted"], ["desktop-new"]
        )
        self.mobile_sync(deletes=["mobile-new"])
        self.history.sync(force=True)
        self.assertEqual(
            [item.id for item in self.history.list_records()], ["legacy-local"]
        )
        self.assertEqual(self.mobile_sync()["entries"], [])

    def test_lost_http_response_then_retry_does_not_duplicate_a_record(self):
        from cloud.service.models import HistoryEntry

        owner = self.sign_in()
        self.history.append(self.record("retry-record"), owner)
        self.drop_history_response = True
        with self.assertRaises(AccountError):
            self.history.sync(force=True)
        self.assertEqual(HistoryEntry.objects.filter(user=self.user).count(), 1)
        self.drop_history_response = False
        self.now = 61
        self.history.sync(force=True)
        self.assertEqual(HistoryEntry.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            [item["id"] for item in self.mobile_sync()["entries"]], ["retry-record"]
        )

    def test_guest_never_contacts_account_service_and_account_delete_keeps_legacy(self):
        legacy = self.record("guest-local")
        self.local.append(legacy)
        self.history.sync(force=True)
        self.assertEqual(self.calls, [])
        owner = self.sign_in()
        self.history.append(self.record("account-new"), owner)
        self.history.sync(force=True)
        self.assertEqual(
            len(list((self.directory / "account-history").glob("*/history.json"))), 1
        )
        self.account.logout(delete=True)
        self.assertEqual(
            list((self.directory / "account-history").glob("*/history.json")), []
        )
        self.assertEqual(
            [record.id for record in self.history.list_records()], [legacy.id]
        )
        self.assertEqual(self.local.list_records(), [legacy])
