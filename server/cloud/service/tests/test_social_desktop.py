"""Exercise the desktop client against Django and real allauth OAuth flows."""

import json
from html import unescape
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Event
from urllib.parse import parse_qs, urlsplit

from django.core import mail
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient
import requests

from clarify_account import AccountError, AccountService
from secret_store import MemorySecretStore
from .test_social import PROVIDERS, SocialFlowMixin


@override_settings(CLARIFY_SIGNUP_ENABLED=True, SOCIALACCOUNT_PROVIDERS=PROVIDERS)
class DesktopSocialTests(SocialFlowMixin, TestCase):
    def account(self, directory, provider, *, cancel_after_poll=None):
        self.claimed = []

        def transport(method, url, *, headers, **kwargs):
            arguments = {
                "HTTP_" + key.upper().replace("-", "_"): value
                for key, value in headers.items()
            }
            response = self.native.generic(
                method,
                urlsplit(url).path,
                data=json.dumps(kwargs["json"]) if "json" in kwargs else "",
                content_type="application/json",
                secure=True,
                **arguments,
            )
            if url.endswith("/social/poll") and response.status_code in {200, 401}:
                self.claimed.append(response.json()["meta"]["session_token"])
                if cancel_after_poll:
                    cancel_after_poll.set()
            result = requests.Response()
            result.status_code = response.status_code
            result._content = response.content
            return result

        def browser(url):
            path = urlsplit(url).path
            page = self.browser.get(path, secure=True)
            self.assertEqual(page.status_code, 200)
            redirect = self.browser.post(
                path,
                {
                    "csrfmiddlewaretoken": self.browser.cookies["csrftoken"].value,
                },
                secure=True,
                HTTP_ORIGIN="https://testserver",
            )
            self.assertEqual(redirect.status_code, 200, redirect.content)
            provider_url = unescape(
                re.search(r'href="([^"]+)"', redirect.content.decode()).group(1)
            )
            state = parse_qs(urlsplit(provider_url).query)["state"][0]
            self.callback(provider, state, f"{provider}@example.test")
            return True

        return AccountService(
            directory,
            secrets=MemorySecretStore(),
            request=transport,
            default_endpoint="https://testserver",
        ), browser

    def test_desktop_can_register_and_sign_in_again_with_every_provider(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider), TemporaryDirectory() as directory:
                self.native = APIClient()
                self.browser = Client(enforce_csrf_checks=True)
                account, browser = self.account(directory, provider)
                account.authenticate_social(provider, open_browser=browser)
                if provider == "microsoft":
                    self.assertFalse(account.signed_in)
                    self.assertEqual(account.snapshot()["pending"], "signup")
                    code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group(0)
                    account.authenticate("confirm", code)
                self.assertTrue(account.signed_in)
                identity = account.scope
                self.assertEqual(
                    account.snapshot()["email"], f"{provider}@example.test"
                )
                for token in self.claimed:
                    self.assertNotIn(
                        token, (Path(directory) / "account.json").read_text()
                    )
                account.logout()
                account.authenticate_social(provider, open_browser=browser)
                self.assertTrue(account.signed_in)
                self.assertEqual(account.scope, identity)
                account.logout()

    def test_desktop_cancel_after_claim_revokes_the_native_allauth_session(self):
        cancel = Event()
        with TemporaryDirectory() as directory:
            account, browser = self.account(
                directory, "google", cancel_after_poll=cancel
            )
            with self.assertRaises(AccountError):
                account.authenticate_social(
                    "google", open_browser=browser, cancel=cancel
                )
            self.assertFalse(account.signed_in)
            self.assertEqual(len(self.claimed), 1)
            response = APIClient().get(
                "/v1/account", secure=True, HTTP_X_SESSION_TOKEN=self.claimed[0]
            )
            self.assertIn(response.status_code, {401, 403})
