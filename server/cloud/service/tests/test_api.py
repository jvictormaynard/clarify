import hashlib
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.headless.tokens.strategies.sessions import SessionTokenStrategy
from django.contrib.auth import get_user_model, login
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from cloud.service import funding
from cloud.service.models import Allowance, Operation


def client_for(email):
    user = get_user_model().objects.create_user(email=email)
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    request = RequestFactory().get("/")
    request.session = SessionStore()
    login(request, user, backend="allauth.account.auth_backends.AuthenticationBackend")
    request.session.save()
    token = SessionTokenStrategy().create_session_token(request)
    return user, APIClient(HTTP_X_SESSION_TOKEN=token)


def fund_hosted(*users, amount="100"):
    """Explicit test cash and activity, never inferred from an environment cap."""
    now = timezone.now()
    for user in users:
        user.hosted_requested_at = now - timedelta(days=14)
        user.hosted_last_active_at = now - timedelta(days=1)
        user.save(update_fields=["hosted_requested_at", "hosted_last_active_at"])
    funding.record_contribution(
        amount_usd=Decimal(amount),
        reference="test-cash",
        occurred_at=now - timedelta(days=32),
    )
    funding.approve_funding()


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

    def test_legacy_audio_allowances_cannot_masquerade_as_new_funded_quota(self):
        Allowance.objects.create(
            user=self.a, month=timezone.now().date().replace(day=1), used_ms=60000
        )
        self.a.monthly_audio_ms = 18000000
        self.a.save()
        usage = self.ca.get("/v1/account").json()["usage"]
        self.assertEqual(usage["schema_version"], 2)
        self.assertEqual(usage["allocation_status"], "unfunded")
        self.assertEqual(usage["remaining_percent"], 0)
        self.assertFalse(usage["hosted_available"])
        self.assertFalse({"month", "limit_ms", "used_ms", "reserved_ms"} & usage.keys())

    @patch("cloud.service.groq.perform")
    def test_legacy_cached_operation_returns_fresh_percent_usage_without_paid_replay(
        self, provider
    ):
        fund_hosted(self.a, self.b)
        operation_id = uuid.uuid4()
        payload = {
            "operation_id": str(operation_id),
            "action": "rewrite",
            "text": "Source.",
            "language": "auto",
        }
        digest = hashlib.sha256(
            json.dumps(
                ["text", "rewrite", "Source.", "auto"], ensure_ascii=False
            ).encode()
        ).hexdigest()
        Operation.objects.create(
            user=self.a,
            operation_id=operation_id,
            fingerprint=digest,
            state="complete",
            month=timezone.now().date().replace(day=1),
            audio_ms=0,
            reserved_cost=Decimal("0.02"),
            lease_until=timezone.now(),
            result_expires_at=timezone.now() + timedelta(minutes=5),
            result={
                "text": "Revised.",
                "usage": {"limit_ms": 18000000, "used_ms": 60000},
            },
        )
        response = self.ca.post("/v1/text", payload, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "Revised.")
        usage = response.json()["usage"]
        self.assertEqual(usage, self.ca.get("/v1/usage").json())
        self.assertEqual(usage["schema_version"], 2)
        self.assertFalse({"limit_ms", "used_ms"} & usage.keys())
        provider.assert_not_called()

    def test_no_general_purpose_proxy(self):
        for path in ("/v1/chat/completions", "/v1/responses", "/v1/models"):
            self.assertEqual(
                self.ca.post(path, {"prompt": "x"}, format="json").status_code, 404
            )
