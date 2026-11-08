"""Verify the real public routes against the quota ledger and private host."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.test import Client, TestCase, override_settings

from cloud.service import funding, ledger
from cloud.service.models import FundingEntry, Operation
from .test_api import client_for


NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


@override_settings(
    ROOT_URLCONF="cloud.urls",
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="10",
    CLARIFY_STRIPE_READ_KEY="",
    CLARIFY_STRIPE_PAYMENT_LINK="",
    CLARIFY_STRIPE_PAYMENT_LINK_VERIFIED=False,
    CLARIFY_ADMIN_HOST="admin.example.test",
    ALLOWED_HOSTS=["testserver", "admin.example.test"],
)
class FinancialIntegrationTests(TestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.user, self.account = client_for("member@example.test")
        self.user.hosted_requested_at = NOW - timedelta(days=7)
        self.user.hosted_last_active_at = NOW - timedelta(days=1)
        self.user.save()
        funding.record_contribution(
            amount_usd=Decimal("10"),
            reference="donor-private@example.test",
            occurred_at=NOW,
        )
        funding.record_operating(
            kind="reserve",
            amount_usd=Decimal("2"),
            reference="private-hosting-reference",
            occurred_at=NOW,
        )
        funding.approve_funding()
        self.public = Client()

    def test_public_finances_and_private_percentages_use_the_same_funded_ledger(self):
        usage = self.account.get("/v1/usage")
        self.assertEqual(usage.status_code, 200)
        self.assertEqual(usage.json()["remaining_percent"], 100)
        self.assertNotIn("usd", str(usage.json()).lower())
        self.assertNotIn("audio", str(usage.json()).lower())

        operation, fresh = ledger.reserve(
            self.user, uuid.uuid4(), "private-content-hash", 1000
        )
        self.assertTrue(fresh)
        ledger.authorize(operation, Decimal("0.001"))
        ledger.settle(
            operation, result={"text": "PRIVATE TRANSCRIPT"}, cost=Decimal("0.001")
        )
        ledger.settle(
            operation, result={"text": "PRIVATE TRANSCRIPT"}, cost=Decimal("0.001")
        )
        # Public accounting outlives the short-lived operation metadata.
        Operation.objects.all().delete()

        response = self.public.get("/v1/public/finances")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["stripe"]["state"], "not_configured")
        budget = data["project_budget"]
        self.assertEqual(budget["state"], "ready")
        self.assertEqual(Decimal(budget["received_usd"]), Decimal("10"))
        self.assertEqual(Decimal(budget["operating_reserved_usd"]), Decimal("2"))
        self.assertEqual(Decimal(budget["processing_spent_usd"]), Decimal("0.001"))
        self.assertEqual(
            [row["kind"] for row in budget["movements"]].count("processing_cost"), 1
        )
        page = self.public.get("/transparency/?lang=pt")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Para onde vai o dinheiro")
        for private in (
            "member@example.test",
            "donor-private@example.test",
            "private-hosting-reference",
            "PRIVATE TRANSCRIPT",
            "private-content-hash",
            str(operation.operation_id),
        ):
            self.assertNotIn(private, response.content.decode())
            self.assertNotIn(private, page.content.decode())
        self.assertIsNone(data["sponsorship"]["payment_link"])

    def test_real_host_boundary_keeps_public_finances_off_the_administrator_host(self):
        for path in (
            "/transparency/",
            "/v1/public/finances",
            "/transparency/assets/transparency.css",
        ):
            self.assertEqual(self.public.get(path).status_code, 200)
            self.assertEqual(
                self.public.get(path, HTTP_HOST="admin.example.test").status_code, 404
            )

    def test_project_history_reads_one_bounded_page_from_the_ledger(self):
        FundingEntry.objects.bulk_create(
            [
                FundingEntry(
                    kind="operating_reserve",
                    amount_usd=Decimal("0.001"),
                    source="test",
                    reference=f"provision-{index}",
                    occurred_at=NOW - timedelta(seconds=index + 1),
                )
                for index in range(125)
            ]
        )
        raw = funding.public_summary()
        self.assertEqual(len(raw["movements"]), 50)
        self.assertEqual(raw["movements_total"], 127)
        pages = [
            self.public.get(f"/v1/public/finances?budget_page={page}")
            for page in (1, 2, 3)
        ]
        self.assertEqual([response.status_code for response in pages], [200, 200, 200])
        budgets = [response.json()["project_budget"] for response in pages]
        self.assertEqual([len(budget["movements"]) for budget in budgets], [50, 50, 27])
        self.assertEqual(budgets[2]["pagination"]["total"], 127)
        self.assertIsNone(budgets[2]["pagination"]["next"])
        rows = [row for budget in budgets for row in budget["movements"]]
        self.assertEqual(sum(row["kind"] == "contribution" for row in rows), 1)
        self.assertEqual(len({row["occurred_at"] for row in rows}), 126)
