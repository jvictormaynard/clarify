"""Reusable account fixtures. This module defines no test cases."""

from pathlib import Path

import tempfile


from unittest.mock import Mock

import uuid

from clarify_account import (
    AccountDictionaryRepository,
    AccountError,
    AccountService,
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


def weekly_usage(**changes):
    usage = dict(
        schema_version=2,
        period_start="2026-10-19T00:00:00Z",
        reset_at="2026-10-26T00:00:00Z",
        used_percent=12.5,
        remaining_percent=82.5,
        reserved_percent=5,
        allocation_status="available",
        hosted_available=True,
    )
    usage.update(changes)
    return usage


class AccountFixture:
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
