"""Desktop social sign-in uses isolated HTTP, browser and secret-store doubles."""

import base64
import hashlib
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import uuid

from clarify_account import AccountError, AccountService, SECRET_ID
from secret_store import MemorySecretStore


class SocialAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.request = Mock()
        self.browser = Mock(return_value=True)
        self.secrets = MemorySecretStore()
        self.account = AccountService(
            self.temp.name,
            request=self.request,
            secrets=self.secrets,
            default_endpoint="https://clarify.example",
        )
        self.attempt = str(uuid.uuid4())
        self.user = str(uuid.uuid4())
        self.authorization = "https://clarify.example/auth/social/browser/ticket"
        self.start = self.response(
            {
                "attempt_id": self.attempt,
                "authorization_url": self.authorization,
                "expires_in": 300,
                "interval": 5,
            }
        )
        self.success = self.response(
            {
                "meta": {
                    "is_authenticated": True,
                    "session_token": "native-session-only",
                }
            }
        )
        self.identity = self.response({"id": self.user, "email": "user@example.test"})

    @staticmethod
    def response(payload=None, status=200):
        response = Mock(
            status_code=status, content=b"json" if payload is not None else b""
        )
        response.json.return_value = payload
        return response

    def authenticate(self, provider="google", **kwargs):
        return self.account.authenticate_social(
            provider, open_browser=self.browser, **kwargs
        )

    def assert_handed_session_revoked(self):
        self.assertTrue(
            any(
                call.args[1].endswith("/social/cancel")
                for call in self.request.call_args_list
            )
        )
        self.assertEqual(
            self.request.call_args.args,
            ("DELETE", "https://clarify.example/_allauth/app/v1/auth/session"),
        )
        self.assertEqual(
            self.request.call_args.kwargs["headers"]["X-Session-Token"],
            "native-session-only",
        )

    def test_all_providers_use_same_origin_browser_and_proof_bound_once_only_handoff(
        self,
    ):
        for provider in ("google", "microsoft", "github"):
            with self.subTest(provider=provider):
                self.account._state = {}
                self.secrets.delete(SECRET_ID)
                self.request.reset_mock()
                self.request.side_effect = [self.start, self.success, self.identity]
                self.authenticate(provider)
                self.assertTrue(self.account.signed_in)
                self.assertEqual(self.account.scope, self.user)
                start = self.request.call_args_list[0].kwargs["json"]
                poll = self.request.call_args_list[1].kwargs["json"]
                expected = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(poll["code_verifier"].encode()).digest()
                    )
                    .decode()
                    .rstrip("=")
                )
                self.assertEqual(
                    start,
                    {
                        "provider": provider,
                        "client": "desktop",
                        "code_challenge": expected,
                    },
                )
                self.assertEqual(poll["attempt_id"], self.attempt)
                self.browser.assert_called_with(self.authorization)
                self.assertEqual(self.secrets.get(SECRET_ID), "native-session-only")
                public = (
                    json.dumps(self.account.snapshot()) + self.account.path.read_text()
                )
                self.assertNotIn("native-session-only", public)
                self.assertNotIn(poll["code_verifier"], public)
                self.assertNotIn("code_verifier", self.browser.call_args.args[0])

    def test_unverified_social_email_continues_existing_email_confirmation(self):
        self.request.side_effect = [
            self.start,
            self.response(
                {
                    "meta": {
                        "is_authenticated": False,
                        "session_token": "pending-session",
                    },
                    "data": {"pending": "signup", "email": "user@example.test"},
                },
                401,
            ),
            self.success,
            self.identity,
        ]
        self.authenticate("microsoft")
        self.assertFalse(self.account.signed_in)
        self.assertEqual(self.account.snapshot()["pending"], "signup")
        self.account.authenticate("confirm", "123456")
        self.assertTrue(self.account.signed_in)
        self.assertTrue(
            self.request.call_args_list[2].args[1].endswith("/auth/email/verify")
        )

    def test_browser_failure_cancels_attempt_without_storing_a_session(self):
        self.browser.return_value = False
        self.request.side_effect = [self.start, self.response(status=204)]
        with self.assertRaises(AccountError):
            self.authenticate()
        self.assertTrue(self.request.call_args.args[1].endswith("/social/cancel"))
        self.assertIsNone(self.secrets.get(SECRET_ID))

    def test_cancellation_during_poll_revokes_result_without_adopting_it(self):
        cancel = threading.Event()

        def respond(method, url, **kwargs):
            if url.endswith("/start"):
                return self.start
            if url.endswith("/poll"):
                cancel.set()
                return self.success
            return self.response(status=204)

        self.request.side_effect = respond
        with self.assertRaises(AccountError):
            self.authenticate(cancel=cancel)
        self.assertFalse(self.account.signed_in)
        self.assertIsNone(self.secrets.get(SECRET_ID))
        self.assert_handed_session_revoked()

    def test_arbitrary_redirect_origins_and_credentials_are_rejected(self):
        for url in (
            "https://evil.example/start",
            "https://clarify.example.evil/start",
            "http://clarify.example/start",
            "https://user@clarify.example/start",
            "https://clarify.example:444/start",
        ):
            with self.subTest(url=url):
                self.browser.reset_mock()
                payload = self.start.json().copy()
                payload["authorization_url"] = url
                self.request.side_effect = [
                    self.response(payload),
                    self.response(status=204),
                ]
                with self.assertRaises(AccountError):
                    self.authenticate()
                self.browser.assert_not_called()

    def test_terminal_and_malformed_results_never_store_tokens(self):
        for status, result in (
            (400, {"code": "social_account_exists"}),
            (410, {}),
            (200, {"meta": {"is_authenticated": False, "session_token": "untrusted"}}),
            (
                401,
                {
                    "meta": {"is_authenticated": False, "session_token": "untrusted"},
                    "data": {"pending": "other"},
                },
            ),
        ):
            with self.subTest(status=status, result=result):
                self.request.side_effect = [
                    self.start,
                    self.response(result, status),
                    self.response(status=204),
                ]
                with self.assertRaises(AccountError):
                    self.authenticate()
                self.assertFalse(self.account.signed_in)
                self.assertIsNone(self.secrets.get(SECRET_ID))

    def test_account_transition_during_browser_launch_discards_late_result(self):
        self.browser.side_effect = lambda url: (
            self.account.configure("https://other.example") or True
        )
        self.request.side_effect = [self.start, self.response(status=204)]
        with self.assertRaises(AccountError):
            self.authenticate()
        self.assertFalse(self.account.signed_in)
        self.assertIsNone(self.secrets.get(SECRET_ID))
        self.assertFalse(
            any(call.args[1].endswith("/poll") for call in self.request.call_args_list)
        )

    def test_unknown_provider_and_signed_in_account_do_not_start_a_flow(self):
        with self.assertRaises(AccountError):
            self.authenticate("unknown")
        self.account._state["user_id"] = self.user
        with self.assertRaises(AccountError):
            self.authenticate()
        self.request.assert_not_called()
        self.browser.assert_not_called()

    def test_failed_identity_refresh_cancels_handoff_and_clears_new_credential(self):
        self.request.side_effect = [
            self.start,
            self.success,
            self.response({}, 503),
            self.response(status=204),
        ]
        with self.assertRaises(AccountError):
            self.authenticate()
        self.assertFalse(self.account.signed_in)
        self.assertIsNone(self.secrets.get(SECRET_ID))
        self.assert_handed_session_revoked()

    def test_secret_storage_failure_revokes_the_handoff(self):
        self.request.side_effect = [self.start, self.success, self.response(status=204)]
        self.secrets.set = Mock(side_effect=OSError("isolated secret-store failure"))
        with self.assertRaises(OSError):
            self.authenticate()
        self.assertFalse(self.account.signed_in)
        self.assertIsNone(self.secrets.get(SECRET_ID))
        self.assert_handed_session_revoked()

    def test_metadata_write_failure_preserves_previous_email_sign_in(self):
        self.account._state.update(pending="login", email="pending@example.test")
        self.secrets.set(SECRET_ID, "previous-email-session")
        self.request.side_effect = [
            self.start,
            self.success,
            self.identity,
            self.response(status=204),
        ]
        with patch(
            "clarify_account._atomic_write_json",
            side_effect=OSError("isolated write failure"),
        ):
            with self.assertRaises(OSError):
                self.authenticate()
        self.assertFalse(self.account.signed_in)
        self.assertEqual(self.account.snapshot()["pending"], "login")
        self.assertEqual(self.account.snapshot()["email"], "pending@example.test")
        self.assertEqual(self.secrets.get(SECRET_ID), "previous-email-session")
        self.assert_handed_session_revoked()

    def test_cancellation_during_identity_refresh_cannot_sign_in(self):
        cancel = threading.Event()

        def respond(method, url, **kwargs):
            if url.endswith("/start"):
                return self.start
            if url.endswith("/poll"):
                return self.success
            if url.endswith("/v1/account"):
                cancel.set()
                return self.identity
            return self.response(status=204)

        self.request.side_effect = respond
        with self.assertRaises(AccountError):
            self.authenticate(cancel=cancel)
        self.assertFalse(self.account.signed_in)
        self.assertIsNone(self.secrets.get(SECRET_ID))
        self.assert_handed_session_revoked()

    def test_expired_browser_wait_is_bounded_and_cancelled(self):
        from social_login import SocialLoginError, sign_in

        now = [0]

        class Wait:
            def is_set(self):
                return False

            def wait(self, seconds):
                now[0] += seconds

        self.start.json.return_value = {**self.start.json(), "expires_in": 11}
        calls = []

        def request(method, path, **kwargs):
            calls.append(path)
            return (200, self.start.json()) if path.endswith("/start") else (202, {})

        with self.assertRaisesRegex(SocialLoginError, "tempo"):
            sign_in(
                "github",
                endpoint="https://clarify.example",
                request=request,
                open_browser=self.browser,
                check_current=lambda: None,
                accept=Mock(),
                cancel=Wait(),
                clock=lambda: now[0],
            )
        self.assertEqual(now[0], 11)
        self.assertEqual(sum(path.endswith("/poll") for path in calls), 3)
        self.assertTrue(calls[-1].endswith("/cancel"))


if __name__ == "__main__":
    unittest.main()
