import re

from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from allauth.account.models import EmailAddress


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

    def test_continue_creates_passwordless_account_and_requires_its_code(self):
        response = self.client.post(
            "/_allauth/app/v1/auth/continue",
            {"email": "New@Example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 401, response.content)
        self.accept_token(response)
        user = get_user_model().objects.get(email="new@example.test")
        self.assertFalse(user.has_usable_password())
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.client.get("/v1/account").status_code, (401, 403))
        code = self.email_code()
        wrong = "000000" if code != "000000" else "111111"
        response = self.client.post(
            "/_allauth/app/v1/auth/code/confirm", {"code": wrong}, format="json"
        )
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        response = self.client.post(
            "/_allauth/app/v1/auth/code/confirm", {"code": code}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.accept_token(response)
        self.assertTrue(EmailAddress.objects.get(user=user).verified)
        self.assertEqual(self.client.get("/v1/account").json()["id"], str(user.pk))

    def test_continue_enters_existing_account_without_creating_another(self):
        user = get_user_model().objects.create_user("existing@example.test")
        EmailAddress.objects.create(
            user=user, email=user.email, verified=True, primary=True
        )
        response = self.client.post(
            "/_allauth/app/v1/auth/continue",
            {"email": "EXISTING@EXAMPLE.TEST"},
            format="json",
        )
        self.assertEqual(response.status_code, 401, response.content)
        self.accept_token(response)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        response = self.client.post(
            "/_allauth/app/v1/auth/code/confirm",
            {"code": self.email_code()},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.accept_token(response)
        self.assertEqual(self.client.get("/v1/account").json()["id"], str(user.pk))

    @override_settings(CLARIFY_SIGNUP_ENABLED=False)
    def test_continue_respects_closed_signup_but_allows_existing_login(self):
        response = self.client.post(
            "/_allauth/app/v1/auth/continue",
            {"email": "closed@example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.exists())
        self.assertEqual(len(mail.outbox), 0)
        user = get_user_model().objects.create_user("existing@example.test")
        EmailAddress.objects.create(
            user=user, email=user.email, verified=True, primary=True
        )
        response = APIClient().post(
            "/_allauth/app/v1/auth/continue", {"email": user.email}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(mail.outbox), 1)

    def test_continue_does_not_create_account_for_invalid_email(self):
        response = self.client.post(
            "/_allauth/app/v1/auth/continue", {"email": "invalid"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(get_user_model().objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(CLARIFY_DAILY_EMAIL_LIMIT=0)
    def test_continue_respects_daily_email_budget(self):
        response = self.client.post(
            "/_allauth/app/v1/auth/continue",
            {"email": "limited@example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(mail.outbox), 0)

    def test_continue_cannot_bypass_new_account_rate_limit(self):
        for index in range(3):
            response = APIClient().post(
                "/_allauth/app/v1/auth/continue",
                {"email": f"new{index}@example.test"},
                format="json",
            )
            self.assertEqual(response.status_code, 401, response.content)
        response = APIClient().post(
            "/_allauth/app/v1/auth/continue",
            {"email": "extra@example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(get_user_model().objects.count(), 3)
        self.assertEqual(len(mail.outbox), 3)

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

    def test_existing_account_email_directs_to_app_login(self):
        user = get_user_model().objects.create_user("existing@example.test")
        EmailAddress.objects.create(
            user=user, email=user.email, verified=True, primary=True
        )
        response = self.client.post(
            "/_allauth/app/v1/auth/signup", {"email": user.email}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        self.assertTrue(mail.outbox)
        self.assertIn("Entrar", mail.outbox[-1].body)
        self.assertNotIn("testserver", mail.outbox[-1].body)
        self.assertNotIn("http", mail.outbox[-1].body)
        self.accept_token(response)
        response = self.client.post(
            "/_allauth/app/v1/auth/code/request", {"email": user.email}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        self.accept_token(response)
        response = self.client.post(
            "/_allauth/app/v1/auth/code/confirm",
            {"code": self.email_code()},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.accept_token(response)
        self.assertEqual(self.client.get("/v1/account").status_code, 200)

    def test_unknown_account_email_directs_to_app_signup(self):
        response = self.client.post(
            "/_allauth/app/v1/auth/code/request",
            {"email": "unknown@example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertTrue(mail.outbox)
        self.assertIn("Criar conta", mail.outbox[-1].body)
        self.assertNotIn("testserver", mail.outbox[-1].body)
        self.assertNotIn("http", mail.outbox[-1].body)
        self.accept_token(response)
        response = self.client.post(
            "/_allauth/app/v1/auth/signup",
            {"email": "unknown@example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
        self.accept_token(response)
        response = self.client.post(
            "/_allauth/app/v1/auth/email/verify",
            {"key": self.email_code()},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.accept_token(response)
        self.assertEqual(self.client.get("/v1/account").status_code, 200)

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
