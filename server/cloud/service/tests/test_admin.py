"""Admin authorization, browser login and host isolation with fake accounts."""

import re
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient


@override_settings(
    CLARIFY_ADMIN_HOST="admin.example.test",
    CLARIFY_ADMIN_EMAILS=frozenset({"owner@example.test"}),
    ALLOWED_HOSTS=["testserver", "admin.example.test", "api.example.test"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AdminAccessTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("owner@example.test")
        self.address = EmailAddress.objects.create(
            user=self.owner, email=self.owner.email, primary=True, verified=True
        )
        self.client = Client(HTTP_HOST="admin.example.test")

    def admin_login(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["clarify_admin_authenticated_at"] = timezone.now().timestamp()
        session.save()

    def request_code(self, client=None):
        client = client or self.client
        return client.post(
            "/_allauth/browser/v1/auth/code/request",
            {"email": self.owner.email},
            content_type="application/json",
        )

    def test_data_requires_authentication_and_never_caches(self):
        response = self.client.get("/admin/api/overview")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_native_owner_session_cannot_be_promoted_to_admin(self):
        native = APIClient(HTTP_HOST="api.example.test")
        response = native.post(
            "/_allauth/app/v1/auth/code/request",
            {"email": self.owner.email},
            format="json",
        )
        token = response.json()["meta"]["session_token"]
        native.credentials(HTTP_X_SESSION_TOKEN=token)
        code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group(0)
        response = native.post(
            "/_allauth/app/v1/auth/code/confirm", {"code": code}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.client.cookies["sessionid"] = (
            response.json().get("meta", {}).get("session_token", token)
        )
        self.assertEqual(self.client.get("/admin/api/session").status_code, 401)

    def test_native_pending_code_cannot_replace_admin_challenge(self):
        self.assertEqual(self.request_code().status_code, 401)
        code = re.search(r"\b\d{8}\b", mail.outbox[-1].body).group(0)
        key = self.client.cookies["sessionid"].value
        native = APIClient(HTTP_HOST="api.example.test", HTTP_X_SESSION_TOKEN=key)
        response = native.post(
            "/_allauth/app/v1/auth/code/request",
            {"email": self.owner.email},
            format="json",
        )
        self.assertIn(response.status_code, (401, 410))
        self.assertEqual(len(mail.outbox), 1)
        response = native.post(
            "/_allauth/app/v1/auth/code/confirm", {"code": code}, format="json"
        )
        self.assertIn(response.status_code, (401, 410))
        response = self.client.post(
            "/_allauth/browser/v1/auth/code/confirm",
            {"code": code},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        native.credentials(HTTP_X_SESSION_TOKEN=self.client.cookies["sessionid"].value)
        self.assertIn(native.get("/v1/account").status_code, (401, 403, 410))

    def test_confirmation_proves_exact_admin_challenge(self):
        self.assertEqual(self.request_code().status_code, 401)
        code = re.search(r"\b\d{8}\b", mail.outbox[-1].body).group(0)
        session = self.client.session
        pending = session["clarify_admin_pending"]
        pending["digest"] = "0" * 40
        session["clarify_admin_pending"] = pending
        session.save()
        response = self.client.post(
            "/_allauth/browser/v1/auth/code/confirm",
            {"code": code},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/admin/api/session").status_code, 401)

    @override_settings(ACCOUNT_RATE_LIMITS={"request_login_code": False})
    def test_email_limit_survives_fresh_sessions(self):
        for _ in range(3):
            self.assertEqual(
                self.request_code(Client(HTTP_HOST="admin.example.test")).status_code,
                401,
            )
        self.assertEqual(
            self.request_code(Client(HTTP_HOST="admin.example.test")).status_code, 429
        )
        self.assertEqual(len(mail.outbox), 3)

    def test_confirmation_has_atomic_attempt_limit(self):
        self.assertEqual(self.request_code().status_code, 401)
        code = re.search(r"\b\d{8}\b", mail.outbox[-1].body).group(0)
        wrong = "00000000" if code != "00000000" else "11111111"
        for _ in range(5):
            response = self.client.post(
                "/_allauth/browser/v1/auth/code/confirm",
                {"code": wrong},
                content_type="application/json",
            )
            self.assertNotEqual(response.status_code, 200)
        response = self.client.post(
            "/_allauth/browser/v1/auth/code/confirm",
            {"code": code},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.client.get("/admin/api/session").status_code, 401)

    def test_admin_proof_expires_without_renewal_by_polling(self):
        self.admin_login()
        session = self.client.session
        authenticated_at = timezone.now().timestamp() - 8 * 60 * 60 - 1
        session["clarify_admin_authenticated_at"] = authenticated_at
        session.save()
        self.assertEqual(self.client.get("/admin/api/users").status_code, 401)
        self.assertEqual(
            self.client.session["clarify_admin_authenticated_at"], authenticated_at
        )

    def test_expired_code_cannot_grant_admin_scope(self):
        self.request_code()
        code = re.search(r"\b\d{8}\b", mail.outbox[-1].body).group(0)
        session = self.client.session
        pending = session["clarify_admin_pending"]
        pending["issued_at"] -= 601
        session["clarify_admin_pending"] = pending
        session.save()
        response = self.client.post(
            "/_allauth/browser/v1/auth/code/confirm",
            {"code": code},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_normal_account_and_staff_flag_do_not_grant_access(self):
        user = get_user_model().objects.create_user("other@example.test", is_staff=True)
        EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=True
        )
        self.client.force_login(user)
        for path in ("/admin/api/session", "/admin/api/overview", "/admin/api/users"):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_verified_owner_can_access_metadata(self):
        self.admin_login()
        response = self.client.get("/admin/api/session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"email": self.owner.email})
        self.assertEqual(self.client.get("/admin/api/users").status_code, 200)

    def test_unverified_or_revoked_owner_is_rejected_each_request(self):
        self.admin_login()
        self.address.verified = False
        self.address.save()
        self.assertEqual(self.client.get("/admin/api/session").status_code, 403)
        self.address.verified = True
        self.address.save()
        with override_settings(CLARIFY_ADMIN_EMAILS=frozenset()):
            self.assertEqual(self.client.get("/admin/api/session").status_code, 403)

    def test_admin_is_hidden_on_api_host_and_disabled_without_configuration(self):
        self.admin_login()
        for path in (
            "/admin/",
            "/admin/api/users",
            "/_allauth/browser/v1/auth/code/request",
        ):
            self.assertEqual(
                self.client.get(path, HTTP_HOST="api.example.test").status_code, 404
            )
        with override_settings(CLARIFY_ADMIN_HOST=""):
            self.assertEqual(self.client.get("/admin/api/session").status_code, 404)

    def test_native_api_is_not_available_on_admin_host(self):
        self.assertEqual(self.client.get("/v1/account").status_code, 404)
        self.assertEqual(
            self.client.get("/_allauth/app/v1/auth/session").status_code, 404
        )
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_admin_api_is_read_only_and_query_validation_is_bounded(self):
        self.admin_login()
        self.assertEqual(self.client.post("/admin/api/users").status_code, 405)
        for query in (
            "days=365",
            "days=abc",
            "page=-1",
            "segment=unknown",
            "owner=other",
        ):
            self.assertEqual(
                self.client.get("/admin/api/users?" + query).status_code, 400
            )
        self.assertEqual(
            self.client.get(
                "/admin/api/users/00000000-0000-0000-0000-000000000000"
            ).status_code,
            404,
        )

    def test_browser_uses_csrf_and_logout_revokes_session(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="admin.example.test")
        client.force_login(self.owner)
        self.assertEqual(client.post("/admin/api/logout").status_code, 403)
        # The HTML page supplies a CSRF cookie without embedding private data.
        with patch("cloud.service.admin_views.render") as render:
            from django.http import HttpResponse

            render.return_value = HttpResponse("Admin")
            page = client.get("/admin/")
        csrf = page.cookies["csrftoken"].value
        response = client.post("/admin/api/logout", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/admin/api/session").status_code, 401)

    def test_browser_code_flow_authenticates_owner_without_token_storage(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="admin.example.test")
        with patch("cloud.service.admin_views.render") as render:
            from django.http import HttpResponse

            render.return_value = HttpResponse("Admin")
            page = client.get("/admin/")
        csrf = page.cookies["csrftoken"].value
        response = client.post(
            "/_allauth/browser/v1/auth/code/request",
            {"email": self.owner.email},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 401, response.content)
        code = re.search(r"\b\d{8}\b", mail.outbox[-1].body).group(0)
        response = client.post(
            "/_allauth/browser/v1/auth/code/confirm",
            {"code": code},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn("session_token", response.content.decode())
        self.assertTrue(client.cookies["sessionid"]["httponly"])
        self.assertEqual(client.get("/admin/api/session").status_code, 200)

    def test_non_owner_cannot_consume_admin_email_quota_or_create_account(self):
        response = self.client.post(
            "/_allauth/browser/v1/auth/code/request",
            {"email": "unknown@example.test"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_no_other_browser_auth_mutations_are_exposed(self):
        for route in ("signup", "password/change", "email", "session"):
            self.assertEqual(
                self.client.post("/_allauth/browser/v1/auth/" + route).status_code, 404
            )


@skipUnless(connection.vendor == "postgresql", "Atomic concurrency needs PostgreSQL")
class AdminConcurrencyTests(TransactionTestCase):
    def test_parallel_guesses_cannot_exceed_five_attempts(self):
        from cloud.service.admin_auth import take_confirmation_attempt

        pending = {
            "nonce": "isolated-test-challenge",
            "issued_at": timezone.now().timestamp(),
        }

        def guess(_):
            try:
                return take_confirmation_attempt(pending)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(guess, range(8)))
        self.assertEqual(sum(results), 5)
