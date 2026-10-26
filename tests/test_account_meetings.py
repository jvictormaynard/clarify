import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

from account_meetings import identity
from clarify_account import AccountError, AccountService
from provider_http import CancellationToken, ProviderCancelledError
from secret_store import PlaintextFileSecretStore
from shared.meeting_contract import MeetingError


class AccountMeetingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.request = Mock()
        self.account = AccountService(
            root,
            secrets=PlaintextFileSecretStore(root / "secrets.json"),
            request=self.request,
            default_endpoint="https://clarify.example",
        )
        self.account._state.update(user_id=str(uuid.uuid4()), mode="hosted")
        self.account.secrets.set("clarify_account", "fixture-only-session")
        self.identity = identity(self.account)
        self.operation = str(uuid.uuid4())
        self.audio = root / "fixture.wav"
        self.audio.write_bytes(b"synthetic WAV fixture")

    def response(self, data, status=200):
        result = Mock(status_code=status, content=b"json")
        result.json.return_value = data
        return result

    def test_routes_reuse_identity_uuid_timeout_and_usage(self):
        self.request.return_value = self.response(
            {"transcript": "source", "usage": {"used_percent": 12}}
        )
        for _ in range(2):
            self.assertEqual(
                self.account.transcribe_meeting(
                    self.identity, self.operation, self.audio, "es"
                ),
                "source",
            )
        self.assertEqual(
            self.request.call_args.args,
            ("POST", "https://clarify.example/v1/meetings/transcriptions"),
        )
        self.assertEqual(self.request.call_args.kwargs["timeout"], (5, 100))
        self.assertEqual(
            self.request.call_args.kwargs["data"],
            {"operation_id": self.operation, "language": "es"},
        )
        self.assertEqual(self.account.snapshot()["usage"], {"used_percent": 12})
        self.request.return_value = self.response({"summary": "summary"})
        self.account.summarize_meeting(
            self.identity, self.operation, "Source only", "auto"
        )
        self.assertEqual(
            self.request.call_args.kwargs["json"],
            {
                "operation_id": self.operation,
                "source": "Source only",
                "language": "auto",
            },
        )
        self.assertEqual(self.request.call_args.kwargs["timeout"], (5, 100))

    def test_cancel_before_send_and_late_session_change_cannot_publish(self):
        token = CancellationToken()
        token.cancel()
        with self.assertRaises(ProviderCancelledError):
            self.account.transcribe_meeting(
                self.identity, self.operation, self.audio, "pt", cancel=token
            )
        self.request.assert_not_called()

        def changed(*args, **kwargs):
            self.account._generation += 1
            return self.response({"summary": "late"})

        self.request.side_effect = changed
        with self.assertRaises(AccountError):
            self.account.summarize_meeting(
                self.identity, self.operation, "source", "pt"
            )
        calls = self.request.call_count
        with self.assertRaises(MeetingError):
            self.account.summarize_meeting(
                self.identity, self.operation, "source", "pt"
            )
        self.assertEqual(self.request.call_count, calls)

    def test_expiry_keeps_managed_and_blocks_personal_fallback(self):
        self.request.return_value = self.response(
            {"code": "authentication_required"}, 401
        )
        with self.assertRaises(MeetingError):
            self.account.transcribe_meeting(
                self.identity, self.operation, self.audio, "pt"
            )
        self.assertTrue(self.account.managed)
        self.assertFalse(self.account.signed_in)
        self.assertEqual(identity(self.account).owner, "unavailable")
        with self.assertRaises(MeetingError):
            self.account.transcribe_meeting(
                identity(self.account), self.operation, self.audio, "pt"
            )
        self.assertEqual(self.request.call_count, 1)

    def test_quota_and_malformed_error_do_not_expose_provider_text(self):
        self.request.return_value = self.response(
            {"code": "allowance_exhausted", "private": "SECRET"}, 429
        )
        with self.assertRaises(MeetingError) as caught:
            self.account.summarize_meeting(
                self.identity, self.operation, "source", "pt"
            )
        self.assertEqual(caught.exception.code, "meeting.allowance")
        bad = self.response({}, 502)
        bad.json.side_effect = ValueError("PRIVATE PROVIDER RESPONSE")
        self.request.return_value = bad
        with self.assertRaises(MeetingError) as caught:
            self.account.summarize_meeting(
                self.identity, self.operation, "source", "pt"
            )
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_legacy_timeout_and_transform_payload_are_unchanged(self):
        self.request.return_value = self.response({"text": "edited"})
        self.assertEqual(
            self.account.transform_text("source", "rewrite", "pt"), "edited"
        )
        self.assertEqual(self.request.call_args.kwargs["timeout"], (5, 100))
        self.assertEqual(self.request.call_args.kwargs["json"]["action"], "rewrite")
        self.account._request("GET", "/v1/usage")
        self.assertEqual(self.request.call_args.kwargs["timeout"], (5, 15))
