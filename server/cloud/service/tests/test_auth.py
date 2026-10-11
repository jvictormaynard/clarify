import re

from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient


@override_settings(
    CLARIFY_SIGNUP_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EmailAccountTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def accept_token(self, response):
        token = response.json().get("meta", {}).get("session_token")
        if token:
            self.client.credentials(HTTP_X_SESSION_TOKEN=token)

    def email_code(self):
        self.assertTrue(mail.outbox)
        message = mail.outbox[-1]
        self.assertTrue(message.subject.startswith("[Clarify] "))
        self.assertNotIn("testserver", message.subject + message.body)
        self.assertIn("10 minutos", message.body)
        match = re.search(r"\b\d{6}\b", message.body)
        self.assertIsNotNone(match, "Verification email must contain a six digit code")
        return match.group(0)

    def test_signup_verification_logout_and_login_code(self):
        response = self.client.post(
            "/_allauth/app/v1/auth/signup", {"email": "new@example.test"}, format="json"
        )
        self.assertEqual(response.status_code, 401, response.content)
        self.accept_token(response)
        self.assertIn(self.client.get("/v1/dictionary").status_code, (401, 403))
        response = self.client.post(
            "/_allauth/app/v1/auth/email/verify",
            {"key": self.email_code()},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.accept_token(response)
        self.assertTrue(response.json()["meta"]["is_authenticated"])
        self.assertEqual(self.client.get("/v1/account").status_code, 200)
        self.client.delete("/_allauth/app/v1/auth/session")
        self.client.credentials()
        response = self.client.post(
            "/_allauth/app/v1/auth/code/request",
            {"email": "new@example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 401, response.content)
        self.accept_token(response)
        response = self.client.post(
            "/_allauth/app/v1/auth/code/confirm",
            {"code": self.email_code()},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.accept_token(response)
        self.assertEqual(
            self.client.get("/v1/account").json()["email"], "new@example.test"
        )

    @override_settings(CLARIFY_SIGNUP_ENABLED=False)
    def test_closed_beta_rejects_public_signup(self):
        response = self.client.post(
            "/_allauth/app/v1/auth/signup",
            {"email": "closed@example.test"},
            format="json",
        )
        self.assertIn(response.status_code, (400, 403))

    def test_wrong_code_does_not_authorize_account(self):
        response = self.client.post(
            "/_allauth/app/v1/auth/signup",
            {"email": "wrong@example.test"},
            format="json",
        )
        self.accept_token(response)
        response = self.client.post(
            "/_allauth/app/v1/auth/email/verify", {"key": "000000"}, format="json"
        )
        self.assertNotEqual(response.status_code, 200)
        self.assertIn(self.client.get("/v1/usage").status_code, (401, 403))

    @override_settings(CLARIFY_DAILY_EMAIL_LIMIT=1)
    def test_daily_send_limit_blocks_codes_for_another_address(self):
        first = self.client.post(
            "/_allauth/app/v1/auth/signup",
            {"email": "first@example.test"},
            format="json",
        )
        self.assertEqual(first.status_code, 401)
        self.assertEqual(len(mail.outbox), 1)
        second = APIClient().post(
            "/_allauth/app/v1/auth/signup",
            {"email": "second@example.test"},
            format="json",
        )
        self.assertEqual(second.status_code, 429)
        self.assertEqual(len(mail.outbox), 1)
