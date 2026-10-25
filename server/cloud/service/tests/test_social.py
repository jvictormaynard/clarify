"""Native contracts through real allauth redirects and fake provider HTTP."""

import base64
import hashlib
import json
import re
from html import unescape
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from smtplib import SMTPException
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core import mail
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.utils import timezone

from cloud.service.admin_auth import ScopedSessionTokenStrategy
from cloud.service.models import SocialAttempt
from cloud.service.social import expire_attempts


PROVIDERS = {
    name: {
        "APPS": [{"client_id": "test-client", "secret": "test-secret"}],
        "OAUTH_PKCE_ENABLED": True,
    }
    for name in ("google", "microsoft", "github")
}
BASE = "/_allauth/app/v1/auth/social/"
VERIFIER = "v" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
    .decode()
    .rstrip("=")
)


class SocialFlowMixin:
    def setUp(self):
        self.native = APIClient()
        self.browser = Client(enforce_csrf_checks=True)

    def start(self, provider="google", client="desktop"):
        response = self.native.post(
            BASE + "start",
            {
                "provider": provider,
                "client": client,
                "code_challenge": CHALLENGE,
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def authorize(self, provider="google", client="desktop"):
        attempt = self.start(provider, client)
        url = urlsplit(attempt["authorization_url"])
        page = self.browser.get(url.path, secure=True)
        self.assertEqual(page.status_code, 200, page.content)
        response = self.browser.post(
            url.path,
            {
                "csrfmiddlewaretoken": self.browser.cookies["csrftoken"].value,
            },
            secure=True,
            HTTP_ORIGIN="https://testserver",
        )
        self.assertEqual(response.status_code, 200, response.content)
        provider_url = unescape(
            re.search(r'href="([^"]+)"', response.content.decode()).group(1)
        )
        query = parse_qs(urlsplit(provider_url).query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotEqual(query["code_challenge"], [CHALLENGE])
        return attempt, query["state"][0]

    def callback(
        self, provider, state, email="new@example.test", verified=True, uid="identity-1"
    ):
        def fake_http(_session, method, url, **kwargs):
            if method.upper() == "POST":
                self.assertIn("code_verifier", kwargs["data"])
                payload = {"access_token": "provider-token", "token_type": "Bearer"}
            elif provider == "google":
                payload = {"id": uid, "email": email, "verified_email": verified}
            elif provider == "microsoft":
                payload = {"id": uid, "mail": email}
            elif url.endswith("/emails"):
                payload = (
                    [{"email": email, "primary": True, "verified": verified}]
                    if email
                    else []
                )
            else:
                payload = {"id": 1, "login": "identity-1", "email": email}
            response = requests.Response()
            response.status_code = 200
            response.headers["Content-Type"] = "application/json"
            response._content = json.dumps(payload).encode()
            return response

        with patch(
            "requests.sessions.Session.request", autospec=True, side_effect=fake_http
        ):
            response = self.browser.get(
                f"/accounts/{provider}/login/callback/",
                {
                    "code": "provider-code",
                    "state": state,
                },
                secure=True,
            )
        self.assertEqual(response.status_code, 302, response.content)
        self.assertNotIn("provider-token", response["Location"])
        return response

    def poll(self, attempt, verifier=VERIFIER):
        return self.native.post(
            BASE + "poll",
            {
                "attempt_id": attempt["attempt_id"],
                "code_verifier": verifier,
            },
            format="json",
            secure=True,
        )

    def cancel(self, attempt, verifier=VERIFIER):
        return self.native.post(
            BASE + "cancel",
            {
                "attempt_id": attempt["attempt_id"],
                "code_verifier": verifier,
            },
            format="json",
            secure=True,
        )

    def finish_callback(self, provider="google", **kwargs):
        attempt, state = self.authorize(provider, kwargs.pop("client", "desktop"))
        result = self.callback(provider, state, **kwargs)
        return attempt, result


@override_settings(CLARIFY_SIGNUP_ENABLED=True, SOCIALACCOUNT_PROVIDERS=PROVIDERS)
class SocialTests(SocialFlowMixin, TestCase):
    def test_browser_pages_follow_the_supported_request_language(self):
        for locale, title, warning, opening, completion in (
            (
                "pt",
                "Entrar no Clarify",
                "Não continue por um link enviado por outra pessoa.",
                "Abrindo o provedor de entrada.",
                "Seu aplicativo Clarify mostrará o resultado da entrada.",
            ),
            (
                "en",
                "Sign in to Clarify",
                "Do not continue from a link that someone sent you.",
                "Opening the sign-in provider.",
                "Your Clarify app will show the sign-in result.",
            ),
            (
                "es",
                "Entrar en Clarify",
                "No continúes desde un enlace enviado por otra persona.",
                "Abriendo el proveedor de acceso.",
                "Tu aplicación Clarify mostrará el resultado del acceso.",
            ),
        ):
            with self.subTest(locale=locale):
                self.native = APIClient()
                self.browser = Client(
                    enforce_csrf_checks=True, HTTP_ACCEPT_LANGUAGE=locale
                )
                attempt = self.start()
                path = urlsplit(attempt["authorization_url"]).path
                confirmation = self.browser.get(path, secure=True)
                self.assertContains(confirmation, f'lang="{locale}"')
                self.assertContains(confirmation, title)
                self.assertContains(confirmation, warning)
                navigation = self.browser.post(
                    path,
                    {"csrfmiddlewaretoken": self.browser.cookies["csrftoken"].value},
                    secure=True,
                    HTTP_ORIGIN="https://testserver",
                )
                self.assertContains(navigation, f'lang="{locale}"')
                self.assertContains(navigation, opening)
                self.assertContains(navigation, "accounts.google.com")
                complete = self.browser.get("/social/complete/desktop/", secure=True)
                self.assertContains(complete, f'lang="{locale}"')
                self.assertContains(complete, completion)

    def test_start_contract_and_pending(self):
        attempt = self.start()
        self.assertEqual(attempt["expires_in"], 300)
        self.assertEqual(attempt["interval"], 5)
        url = urlsplit(attempt["authorization_url"])
        self.assertEqual((url.scheme, url.netloc), ("https", "testserver"))
        self.assertNotIn(VERIFIER, attempt["authorization_url"])
        self.assertEqual(self.poll(attempt).status_code, 202)

    def test_each_provider_uses_allauth_and_hands_off_once(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.native = APIClient()
                self.browser = Client(enforce_csrf_checks=True)
                attempt, state = self.authorize(provider)
                self.callback(provider, state, f"{provider}@example.test")
                response = self.poll(attempt)
                expected = 401 if provider == "microsoft" else 200
                self.assertEqual(response.status_code, expected, response.content)
                token = response.json()["meta"]["session_token"]
                self.assertTrue(Session.objects.filter(session_key=token).exists())
                self.assertNotEqual(self.browser.cookies.get("sessionid").value, token)
                self.assertIn(
                    self.browser.get("/v1/account", secure=True).status_code, (401, 403)
                )
                self.native.credentials(HTTP_X_SESSION_TOKEN=token)
                account = self.native.get("/v1/account", secure=True)
                self.assertEqual(account.status_code, 200 if expected == 200 else 403)
                self.assertEqual(self.poll(attempt).status_code, 410)
                self.assertEqual(
                    SocialAccount.objects.filter(provider=provider).exists(),
                    expected == 200,
                )

    def test_collision_never_authenticates_or_links_by_email(self):
        user = get_user_model().objects.create_user("existing@example.test")
        EmailAddress.objects.create(
            user=user, email=user.email, verified=True, primary=True
        )
        attempt, state = self.authorize()
        self.callback("google", state, user.email)
        response = self.poll(attempt)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json(), {"code": "social_account_exists"})
        self.assertFalse(SocialAccount.objects.exists())

    def test_unverified_provider_email_continues_allauth_email_code(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.native = APIClient()
                self.browser = Client(enforce_csrf_checks=True)
                email = f"{provider}@example.test"
                attempt, result = self.finish_callback(
                    provider, email=email, verified=False, client="ios"
                )
                self.assertEqual(result["Location"], "/social/complete/ios/")
                finish = self.browser.get(result["Location"], secure=True)
                self.assertEqual(finish["Location"], "clarify://auth/complete")
                pending = self.poll(attempt)
                self.assertEqual(pending.status_code, 401, pending.content)
                self.assertEqual(
                    pending.json()["data"], {"pending": "signup", "email": email}
                )
                token = pending.json()["meta"]["session_token"]
                self.native.credentials(HTTP_X_SESSION_TOKEN=token)
                self.assertEqual(
                    self.native.get("/v1/account", secure=True).status_code, 403
                )
                code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group(0)
                verified = self.native.post(
                    "/_allauth/app/v1/auth/email/verify",
                    {"key": code},
                    format="json",
                    secure=True,
                )
                self.assertEqual(verified.status_code, 200, verified.content)
                self.native.credentials(
                    HTTP_X_SESSION_TOKEN=verified.json()
                    .get("meta", {})
                    .get("session_token", token)
                )
                self.assertEqual(
                    self.native.get("/v1/account", secure=True).status_code, 200
                )
                self.assertEqual(self.poll(attempt).status_code, 410)

                self.assertTrue(
                    SocialAccount.objects.filter(provider=provider).exists()
                )

    def test_independent_email_login_cannot_activate_an_abandoned_social_link(self):
        attempt, _ = self.finish_callback("microsoft", email="victim@example.test")
        self.cancel(attempt)
        mailbox_owner = APIClient()
        pending = mailbox_owner.post(
            "/_allauth/app/v1/auth/continue",
            {"email": "victim@example.test"},
            format="json",
            secure=True,
        )
        mailbox_owner.credentials(
            HTTP_X_SESSION_TOKEN=pending.json()["meta"]["session_token"]
        )
        code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group(0)
        verified = mailbox_owner.post(
            "/_allauth/app/v1/auth/code/confirm",
            {"code": code},
            format="json",
            secure=True,
        )
        self.assertEqual(verified.status_code, 200)
        self.assertFalse(SocialAccount.objects.exists())
        self.browser = Client(enforce_csrf_checks=True)
        attempt, _ = self.finish_callback("microsoft", email="victim@example.test")
        self.assertEqual(self.poll(attempt).json(), {"code": "social_account_exists"})

    def test_pending_email_session_does_not_persist_provider_credentials(self):
        attempt, _ = self.finish_callback("microsoft")
        key = SocialAttempt.objects.get(pk=attempt["attempt_id"]).session_key
        data = json.dumps(Session.objects.get(session_key=key).get_decoded())
        self.assertNotIn("provider-token", data)
        self.assertNotIn("pkce_code_verifier", data)
        self.assertFalse(SocialAccount.objects.exists())

    @override_settings(ACCOUNT_RATE_LIMITS={"confirm_email": "0/m/key"})
    def test_allauth_email_limit_returns_native_429(self):
        attempt, _ = self.finish_callback("microsoft")
        self.assertEqual(self.poll(attempt).status_code, 429)

    def test_smtp_failure_is_terminal_and_rolls_back_incomplete_signup(self):
        with patch(
            "django.core.mail.EmailMultiAlternatives.send",
            side_effect=SMTPException("private SMTP body"),
        ):
            attempt, _ = self.finish_callback("microsoft")
        self.assertEqual(self.poll(attempt).json(), {"code": "social_login_failed"})
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Session.objects.exists())

    def test_existing_social_identity_can_login_with_signup_closed(self):
        user = get_user_model().objects.create_user("existing@example.test")
        EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=True
        )
        SocialAccount.objects.create(user=user, provider="microsoft", uid="identity-1")
        with override_settings(CLARIFY_SIGNUP_ENABLED=False):
            attempt, _ = self.finish_callback("microsoft", email=user.email)
            result = self.poll(attempt)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertFalse(SocialToken.objects.exists())

    def test_new_social_identity_respects_signup_flag_at_callback(self):
        attempt, state = self.authorize()
        with override_settings(CLARIFY_SIGNUP_ENABLED=False):
            self.callback("google", state)
        result = self.poll(attempt)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.json(), {"code": "social_signup_closed"})
        self.assertFalse(get_user_model().objects.exists())

    def test_social_signup_uses_existing_account_limits(self):
        for index in range(4):
            self.native = APIClient()
            self.browser = Client(enforce_csrf_checks=True)
            attempt, _ = self.finish_callback(
                email=f"new{index}@example.test", uid=f"identity-{index}"
            )
            result = self.poll(attempt)
            self.assertEqual(
                result.status_code, 200 if index < 3 else 429, result.content
            )
        self.assertEqual(get_user_model().objects.count(), 3)

    def test_signup_email_budget_cannot_produce_an_authenticated_session(self):
        with override_settings(CLARIFY_DAILY_EMAIL_LIMIT=0):
            attempt, result = self.finish_callback("microsoft", client="ios")
        self.assertEqual(result["Location"], "/social/complete/ios/")
        self.assertEqual(self.poll(attempt).status_code, 429)
        self.assertFalse(
            Session.objects.filter(session_data__contains="_auth_user_id").exists()
        )
        self.assertFalse(mail.outbox)

    def test_missing_email_is_controlled_for_all_providers(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.native = APIClient()
                self.browser = Client(enforce_csrf_checks=True)
                attempt, _ = self.finish_callback(provider, email=None)
                result = self.poll(attempt)
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json(), {"code": "social_email_required"})
                self.assertFalse(get_user_model().objects.exists())

    def test_inactive_social_identity_never_receives_session(self):
        user = get_user_model().objects.create_user(
            "inactive@example.test", is_active=False
        )
        EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=True
        )
        SocialAccount.objects.create(user=user, provider="google", uid="identity-1")
        attempt, _ = self.finish_callback(email=user.email)
        self.assertEqual(self.poll(attempt).json(), {"code": "social_login_failed"})

    def test_deactivated_user_is_rechecked_before_claim(self):
        attempt, _ = self.finish_callback()
        get_user_model().objects.update(is_active=False)
        result = self.poll(attempt)
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Session.objects.exists())

    def test_wrong_verifier_does_not_consume_or_cancel(self):
        attempt = self.start()
        self.assertEqual(self.poll(attempt, "z" * 64).status_code, 400)
        self.assertEqual(self.cancel(attempt, "z" * 64).status_code, 400)
        self.assertEqual(self.poll(attempt).status_code, 202)
        self.assertEqual(self.cancel(attempt).status_code, 204)
        self.assertEqual(self.cancel(attempt).status_code, 204)
        self.assertEqual(self.poll(attempt).status_code, 410)

    def test_cancel_ready_result_revokes_session(self):
        attempt, _ = self.finish_callback()
        row = SocialAttempt.objects.get(pk=attempt["attempt_id"])
        key = row.session_key
        self.assertIsNone(ScopedSessionTokenStrategy().lookup_session(key))
        self.assertEqual(self.cancel(attempt).status_code, 204)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertEqual(self.poll(attempt).status_code, 410)

    def test_late_cancel_does_not_revoke_a_claimed_native_session(self):
        attempt, _ = self.finish_callback()
        result = self.poll(attempt)
        token = result.json()["meta"]["session_token"]
        self.assertEqual(self.cancel(attempt).status_code, 204)
        self.native.credentials(HTTP_X_SESSION_TOKEN=token)
        self.assertEqual(self.native.get("/v1/account", secure=True).status_code, 200)
        self.assertFalse(SocialToken.objects.exists())
        self.assertNotIn(
            "provider-token", str(Session.objects.get(session_key=token).get_decoded())
        )

    def test_expiry_revokes_ready_and_browser_sessions(self):
        for ready in (False, True):
            with self.subTest(ready=ready):
                self.native = APIClient()
                self.browser = Client(enforce_csrf_checks=True)
                attempt, state = self.authorize()
                if ready:
                    self.callback("google", state)
                row = SocialAttempt.objects.get(pk=attempt["attempt_id"])
                keys = [row.session_key, row.browser_session_key]
                SocialAttempt.objects.filter(pk=row.pk).update(
                    expires_at=timezone.now() - timedelta(seconds=1)
                )
                self.assertEqual(self.poll(attempt).status_code, 410)
                self.assertFalse(Session.objects.filter(session_key__in=keys).exists())

    def test_expiry_maintenance_revokes_abandoned_result(self):
        attempt, _ = self.finish_callback()
        key = SocialAttempt.objects.get(pk=attempt["attempt_id"]).session_key
        SocialAttempt.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        expire_attempts()
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertFalse(SocialAttempt.objects.exists())

    def test_cancel_and_expiry_before_callback_do_not_call_provider(self):
        for cancel in (True, False):
            self.native = APIClient()
            self.browser = Client(enforce_csrf_checks=True)
            attempt, state = self.authorize()
            if cancel:
                self.cancel(attempt)
            else:
                SocialAttempt.objects.filter(pk=attempt["attempt_id"]).update(
                    expires_at=timezone.now() - timedelta(seconds=1)
                )
            with patch("requests.sessions.Session.request") as http:
                self.browser.get(
                    "/accounts/google/login/callback/",
                    {"state": state, "code": "unused"},
                    secure=True,
                )
            http.assert_not_called()
            self.assertEqual(self.poll(attempt).status_code, 410)

    def test_provider_callback_requires_the_same_browser_and_valid_state(self):
        attempt, state = self.authorize()
        with patch("requests.sessions.Session.request") as http:
            result = Client().get(
                "/accounts/google/login/callback/",
                {"state": state, "code": "unused"},
                secure=True,
            )
            self.assertEqual(result.status_code, 400)
            result = self.browser.get(
                "/accounts/google/login/callback/",
                {"state": "bad-state", "code": "unused"},
                secure=True,
            )
            self.assertEqual(result.status_code, 302)
        http.assert_not_called()
        self.assertEqual(self.poll(attempt).json(), {"code": "social_login_failed"})
        self.assertFalse(get_user_model().objects.exists())

    def test_browser_referrer_policy_preserves_confirmation_and_provider_privacy(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.native = APIClient()
                self.browser = Client(enforce_csrf_checks=True)
                attempt = self.start(provider)
                path = urlsplit(attempt["authorization_url"]).path
                confirmation = self.browser.get(path, secure=True)
                self.assertEqual(confirmation.status_code, 200)
                # no-referrer makes Chromium send Origin: null on this form POST.
                self.assertEqual(confirmation["Referrer-Policy"], "same-origin")
                token = re.search(
                    r'name="csrfmiddlewaretoken" value="([^"]+)"',
                    confirmation.content.decode(),
                ).group(1)
                navigation = self.browser.post(
                    path,
                    {"csrfmiddlewaretoken": token},
                    secure=True,
                    HTTP_ORIGIN="https://testserver",
                )
                self.assertEqual(navigation.status_code, 200, navigation.content)
                provider_url = unescape(
                    re.search(r'href="([^"]+)"', navigation.content.decode()).group(1)
                )
                self.assertEqual(urlsplit(provider_url).scheme, "https")
                self.assertNotEqual(urlsplit(provider_url).netloc, "testserver")
                self.assertNotIn(path, provider_url)
                self.assertIn("&amp;", navigation.content.decode())
                self.assertContains(navigation, 'rel="noreferrer"')
                completion = self.browser.get("/social/complete/desktop/", secure=True)
                self.assertEqual(completion.status_code, 200)
                for page in (confirmation, navigation, completion):
                    # same-origin suppresses Referer on both provider navigations:
                    # the meta refresh and the fallback link.
                    self.assertEqual(page["Referrer-Policy"], "same-origin")
                    self.assertEqual(page["Cache-Control"], "no-store")
                    self.assertEqual(page["X-Frame-Options"], "DENY")
                    self.assertEqual(
                        page["Content-Security-Policy"],
                        "default-src 'none'; style-src 'self'; form-action 'self'; "
                        "base-uri 'none'; frame-ancestors 'none'",
                    )

    @override_settings(CSRF_TRUSTED_ORIGINS=[])
    def test_confirmation_requires_csrf_and_get_does_not_start_oauth(self):
        attempt = self.start()
        url = urlsplit(attempt["authorization_url"]).path
        confirmation = self.browser.get(url, secure=True)
        self.assertEqual(confirmation.status_code, 200)
        token = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"',
            confirmation.content.decode(),
        ).group(1)
        for origin, submitted_token in (
            ("null", token),
            ("https://evil.test", token),
            ("http://testserver", token),
            ("https://testserver:8443", token),
            (None, token),
            ("https://testserver", ""),
            ("https://testserver", "x" * 64),
        ):
            with self.subTest(origin=origin, valid_token=submitted_token == token):
                headers = {} if origin is None else {"HTTP_ORIGIN": origin}
                self.assertEqual(
                    self.browser.post(
                        url,
                        {"csrfmiddlewaretoken": submitted_token},
                        secure=True,
                        **headers,
                    ).status_code,
                    403,
                )
        stored = SocialAttempt.objects.get(pk=attempt["attempt_id"])
        self.assertEqual(stored.state, "created")
        self.assertTrue(stored.launch_digest)
        self.assertEqual(stored.browser_digest, "")
        self.assertEqual(stored.browser_session_key, "")
        self.assertFalse(Session.objects.exists())
        accepted = self.browser.post(
            url,
            {"csrfmiddlewaretoken": token},
            secure=True,
            HTTP_ORIGIN="https://testserver",
        )
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertEqual(
            SocialAttempt.objects.get(pk=attempt["attempt_id"]).state, "pending"
        )

    def test_disabled_provider_at_callback_is_a_controlled_terminal_failure(self):
        attempt, state = self.authorize()
        with override_settings(SOCIALACCOUNT_PROVIDERS={}):
            with patch("requests.sessions.Session.request") as http:
                result = self.browser.get(
                    "/accounts/google/login/callback/",
                    {"state": state, "code": "unused"},
                    secure=True,
                )
        http.assert_not_called()
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.poll(attempt).json(), {"code": "social_login_failed"})

    def test_browser_session_keys_and_oauth_state_do_not_survive_handoff(self):
        attempt, state = self.authorize()
        browser_key = self.browser.cookies["sessionid"].value
        self.assertIsNone(ScopedSessionTokenStrategy().lookup_session(browser_key))
        self.callback("google", state)
        self.assertFalse(Session.objects.filter(session_key=browser_key).exists())
        result = self.poll(attempt)
        token = result.json()["meta"]["session_token"]
        data = Session.objects.get(session_key=token).get_decoded()
        self.assertNotIn("clarify_social_browser", data)
        self.assertNotIn("clarify_social_handoff", data)
        self.assertNotIn("socialaccount_states", data)
        self.assertNotIn("socialaccount_sociallogin", data)
        with patch("requests.sessions.Session.request") as http:
            replay = self.browser.get(
                "/accounts/google/login/callback/",
                {"state": state, "code": "unused"},
                secure=True,
            )
        http.assert_not_called()
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(self.poll(attempt).status_code, 410)

    def test_expired_callback_cannot_create_an_account_or_native_session(self):
        attempt, state = self.authorize()
        SocialAttempt.objects.filter(pk=attempt["attempt_id"]).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        with patch("requests.sessions.Session.request") as http:
            result = self.browser.get(
                "/accounts/google/login/callback/",
                {"state": state, "code": "unused"},
                secure=True,
            )
        http.assert_not_called()
        self.assertEqual(result["Location"], "/social/complete/desktop/")
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Session.objects.exists())

    @override_settings(ALLOWED_HOSTS=["testserver", "other.example.test"])
    def test_attempt_cannot_move_to_another_allowed_host(self):
        attempt = self.start()
        result = self.native.post(
            BASE + "poll",
            {"attempt_id": attempt["attempt_id"], "code_verifier": VERIFIER},
            format="json",
            secure=True,
            HTTP_HOST="other.example.test",
        )
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.poll(attempt).status_code, 202)

    def test_provider_cancellation_and_http_failure_are_terminal(self):
        for denied in (True, False):
            self.browser = Client(enforce_csrf_checks=True)
            attempt, state = self.authorize()
            query = (
                {"state": state, "error": "access_denied"}
                if denied
                else {"state": state, "code": "bad-code"}
            )
            with patch(
                "requests.sessions.Session.request",
                side_effect=requests.RequestException("private provider body"),
            ):
                result = self.browser.get(
                    "/accounts/google/login/callback/", query, secure=True
                )
            self.assertEqual(result["Location"], "/social/complete/desktop/")
            self.assertNotIn("private", result.content.decode())
            self.assertEqual(self.poll(attempt).json(), {"code": "social_login_failed"})
            self.assertEqual(self.poll(attempt).status_code, 410)

    def test_poll_interval_and_poll_limiter_do_not_spend_email_auth_limit(self):
        attempt = self.start()
        now = timezone.now()
        for index in range(25):
            with patch(
                "cloud.service.social.timezone.now",
                return_value=now + timedelta(seconds=index * 5),
            ):
                self.assertEqual(self.poll(attempt).status_code, 202)
        self.assertEqual(self.poll(attempt).status_code, 429)
        user = get_user_model().objects.create_user("email@example.test")
        result = APIClient().post(
            "/_allauth/app/v1/auth/continue",
            {"email": user.email},
            format="json",
            secure=True,
        )
        self.assertEqual(result.status_code, 401)

    @override_settings(SOCIALACCOUNT_PROVIDERS={})
    def test_unconfigured_provider_fails_without_redirect_or_crash(self):
        for provider in PROVIDERS:
            result = self.native.post(
                BASE + "start",
                {
                    "provider": provider,
                    "client": "desktop",
                    "code_challenge": CHALLENGE,
                },
                format="json",
                secure=True,
            )
            self.assertEqual(result.status_code, 400)
        self.assertFalse(SocialAttempt.objects.exists())

    def test_strict_native_input_and_no_user_redirect(self):
        for data in (
            {"provider": "other", "client": "desktop", "code_challenge": CHALLENGE},
            {"provider": "google", "client": "web", "code_challenge": CHALLENGE},
            {"provider": "google", "client": "desktop", "code_challenge": "a" * 42},
            {
                "provider": "google",
                "client": "desktop",
                "code_challenge": CHALLENGE,
                "next": "https://evil.test",
            },
        ):
            self.assertEqual(
                self.native.post(
                    BASE + "start", data, format="json", secure=True
                ).status_code,
                400,
            )
        self.assertEqual(
            self.native.post(
                BASE + "start",
                {
                    "provider": "google",
                    "client": "desktop",
                    "code_challenge": CHALLENGE,
                },
                format="json",
            ).status_code,
            400,
        )
        self.assertFalse(SocialAttempt.objects.exists())

    @override_settings(
        CLARIFY_ADMIN_HOST="admin.example.test",
        ALLOWED_HOSTS=["testserver", "admin.example.test"],
    )
    def test_admin_host_rejects_all_social_routes_and_native_token_is_not_admin(self):
        attempt, _ = self.finish_callback()
        native_token = self.poll(attempt).json()["meta"]["session_token"]
        admin = Client(HTTP_HOST="admin.example.test")
        for path in (
            BASE + "start",
            BASE + "poll",
            "/accounts/google/login/callback/",
            "/social/complete/ios/",
        ):
            self.assertEqual(admin.get(path, secure=True).status_code, 404)
        admin.cookies["sessionid"] = native_token
        self.assertIn(
            admin.get("/admin/api/overview", secure=True).status_code, (401, 403)
        )


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
@override_settings(CLARIFY_SIGNUP_ENABLED=True, SOCIALACCOUNT_PROVIDERS=PROVIDERS)
class SocialConcurrencyTests(SocialFlowMixin, TransactionTestCase):
    def race(self, attempt, actions):
        barrier = Barrier(len(actions))

        def run(action):
            try:
                barrier.wait(timeout=10)
                result = APIClient().post(
                    BASE + action,
                    {
                        "attempt_id": attempt["attempt_id"],
                        "code_verifier": VERIFIER,
                    },
                    format="json",
                    secure=True,
                )
                return result.status_code, result.json() if result.content else None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(actions)) as executor:
            return list(executor.map(run, actions))

    def test_simultaneous_polls_publish_one_native_session(self):
        attempt, _ = self.finish_callback()
        results = self.race(attempt, ["poll", "poll"])
        self.assertEqual(sorted(code for code, _ in results), [200, 410])
        token = next(
            body["meta"]["session_token"] for code, body in results if code == 200
        )
        self.assertTrue(Session.objects.filter(session_key=token).exists())

    def test_cancel_and_claim_have_one_consistent_winner(self):
        attempt, _ = self.finish_callback()
        key = SocialAttempt.objects.get(pk=attempt["attempt_id"]).session_key
        results = self.race(attempt, ["poll", "cancel"])
        self.assertIn(results[0][0], (200, 410))
        self.assertEqual(results[1][0], 204)
        self.assertEqual(
            Session.objects.filter(session_key=key).exists(), results[0][0] == 200
        )
        self.assertEqual(self.poll(attempt).status_code, 410)
