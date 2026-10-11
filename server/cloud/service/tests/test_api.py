from allauth.account.models import EmailAddress
from allauth.headless.tokens.strategies.sessions import SessionTokenStrategy
from django.contrib.auth import get_user_model, login
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient


def client_for(email):
    user = get_user_model().objects.create_user(email=email)
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    request = RequestFactory().get("/")
    request.session = SessionStore()
    login(request, user, backend="allauth.account.auth_backends.AuthenticationBackend")
    request.session.save()
    token = SessionTokenStrategy().create_session_token(request)
    return user, APIClient(HTTP_X_SESSION_TOKEN=token)


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class AccountIsolationTests(TestCase):
    def setUp(self):
        self.a, self.ca = client_for("a@example.test")
        self.b, self.cb = client_for("b@example.test")

    def test_session_required_and_no_owner_query(self):
        self.assertIn(APIClient().get("/v1/dictionary").status_code, (401, 403))
        self.assertEqual(
            self.ca.get("/v1/dictionary?user_id=" + str(self.b.pk)).status_code, 400
        )

    def test_dictionary_is_private_and_revision_prevents_lost_update(self):
        entry = {"term": "Clarify", "pronunciation": "", "aliases": [], "enabled": True}
        payload = {"revision": 0, "entries": [entry]}
        first = self.ca.put("/v1/dictionary", payload, format="json")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["revision"], 1)
        self.assertEqual(self.cb.get("/v1/dictionary").json()["entries"], [])
        self.assertEqual(
            self.ca.put("/v1/dictionary", payload, format="json").status_code, 409
        )
        self.assertEqual(self.ca.get("/v1/dictionary").json()["entries"], [entry])

    def test_rejects_extra_controls_and_invalid_dictionary(self):
        for payload in (
            {"revision": 0, "entries": [], "user_id": self.b.pk},
            {"revision": 0, "entries": [{"term": "bad\nterm"}]},
        ):
            self.assertEqual(
                self.ca.put("/v1/dictionary", payload, format="json").status_code, 400
            )

    def test_logout_revokes_session(self):
        self.assertEqual(self.ca.get("/v1/account").status_code, 200)
        self.ca.delete("/_allauth/app/v1/auth/session")
        self.assertIn(self.ca.get("/v1/account").status_code, (401, 403))

    def test_account_delete_requires_confirmation_and_preserves_other_user(self):
        self.assertEqual(
            self.ca.delete("/v1/account", {}, format="json").status_code, 400
        )
        self.assertEqual(
            self.ca.delete("/v1/account", {"confirm": True}, format="json").status_code,
            204,
        )
        self.assertFalse(get_user_model().objects.filter(pk=self.a.pk).exists())
        self.assertEqual(self.cb.get("/v1/account").status_code, 200)

    def test_unverified_user_cannot_use_service(self):
        EmailAddress.objects.filter(user=self.a).update(verified=False)
        self.assertEqual(self.ca.get("/v1/usage").status_code, 403)

    def test_no_general_purpose_proxy(self):
        for path in ("/v1/chat/completions", "/v1/responses", "/v1/models"):
            self.assertEqual(
                self.ca.post(path, {"prompt": "x"}, format="json").status_code, 404
            )
