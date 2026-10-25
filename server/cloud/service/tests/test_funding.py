import io
import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from cloud.service import funding, groq, ledger
from cloud.service.models import FundingEntry, Operation, Treasury, User, WeeklyQuota

from . import test_dictation
from .test_api import client_for


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="10",
)
class FundingContractTests(TestCase):
    def setUp(self):
        self.user, self.client = client_for("funding@example.test")

    def test_an_environment_cap_is_not_received_cash(self):
        usage = self.client.get("/v1/usage").json()
        self.assertFalse(usage["hosted_available"])
        self.assertEqual(usage["allocation_status"], "unfunded")

    def test_usage_contains_only_weekly_percent_contract(self):
        usage = ledger.usage(self.user)
        self.assertEqual(
            set(usage),
            {
                "schema_version",
                "period_start",
                "reset_at",
                "used_percent",
                "remaining_percent",
                "reserved_percent",
                "allocation_status",
                "hosted_available",
            },
        )
        self.assertEqual(usage["schema_version"], 2)
        self.assertEqual(usage["used_percent"], 0)
        self.assertEqual(usage["remaining_percent"], 0)
        self.assertEqual(usage["reserved_percent"], 0)


NOW = datetime(2026, 10, 26, tzinfo=dt_timezone.utc)


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="100",
)
class WeeklyFundingTests(TestCase):
    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.user, self.client = client_for("weekly@example.test")
        self.activate(self.user)

    def activate(self, user, *, last=None):
        user.hosted_requested_at = NOW - timedelta(days=14)
        user.hosted_last_active_at = last or NOW - timedelta(days=1)
        user.save(update_fields=["hosted_requested_at", "hosted_last_active_at"])

    def contribute(self, amount="10", *, reference="receipt", at=NOW):
        result = funding.record_contribution(
            amount_usd=Decimal(amount), reference=reference, occurred_at=at
        )
        funding.approve_funding()
        return result

    def test_only_confirmed_cash_is_recorded_once_without_publishing_private_reference(
        self,
    ):
        entry, created = self.contribute(reference="private-payer@example.test")
        self.assertTrue(created)
        again, created = self.contribute(reference="private-payer@example.test")
        self.assertFalse(created)
        self.assertEqual(again.pk, entry.pk)
        with self.assertRaises(ValueError):
            self.contribute("11", reference="private-payer@example.test")
        summary = funding.public_summary()
        self.assertEqual(summary["received_usd"], "10.000000000")
        self.assertEqual(summary["allocated_usd"], "0.000000000")
        self.assertNotIn("private-payer", str(summary))
        self.assertEqual(summary["movements"][0]["label"], "Contribution")
        self.assertEqual(FundingEntry.objects.count(), 1)

    def test_operating_costs_are_provisioned_before_a_paced_equal_distribution(self):
        other, _ = client_for("other@example.test")
        self.activate(other)
        self.contribute()
        funding.record_operating(
            kind="reserve",
            amount_usd=Decimal("4"),
            reference="server-month",
            occurred_at=NOW,
        )
        period = funding.distribute()
        self.assertEqual(period.released_usd, Decimal("1.354838709"))  # 6 * 7/31
        quotas = list(WeeklyQuota.objects.values_list("allocated_usd", flat=True))
        self.assertEqual(quotas, [Decimal("0.541935483")] * 2)
        self.assertEqual(period.newcomers_remaining_usd, Decimal("0.270967741"))
        funding.record_operating(
            kind="expense",
            amount_usd=Decimal("1"),
            reference="server-paid",
            occurred_at=NOW,
        )
        summary = funding.public_summary()
        self.assertEqual(summary["operating_spent_usd"], "1.000000000")
        self.assertEqual(summary["operating_reserved_usd"], "3.000000000")
        # The expense uses the provision and cannot reduce granted quotas.
        self.assertEqual(funding.distribute().pk, period.pk)
        self.assertEqual(
            list(WeeklyQuota.objects.values_list("allocated_usd", flat=True)), quotas
        )
        with self.assertRaises(ValueError):
            funding.record_operating(
                kind="reserve",
                amount_usd=Decimal("6"),
                reference="too-much",
                occurred_at=NOW,
            )

    def test_active_verified_eligible_population_only(self):
        self.contribute()
        for name, changes in (
            ("inactive", {"is_active": False}),
            ("disabled", {"funded_access": False}),
            ("unverified", {}),
            ("dormant", {}),
        ):
            user, _ = client_for(name + "@example.test")
            self.activate(
                user, last=NOW - timedelta(days=29) if name == "dormant" else None
            )
            User.objects.filter(pk=user.pk).update(**changes)
            if name == "unverified":
                EmailAddress.objects.filter(user=user).update(verified=False)
        period = funding.distribute()
        self.assertEqual(period.population, 1)
        self.assertEqual(WeeklyQuota.objects.get().user_id, self.user.pk)

    def test_receipt_waits_for_cost_review_despite_an_interleaved_distribution(self):
        funding.record_contribution(
            amount_usd=Decimal("10"), reference="pending", occurred_at=NOW
        )
        self.assertIsNone(funding.distribute())
        self.assertEqual(ledger.usage(self.user)["allocation_status"], "unfunded")
        funding.record_operating(
            kind="reserve",
            amount_usd=Decimal("9"),
            reference="required-hosting",
            occurred_at=NOW,
        )
        funding.approve_funding()
        period = funding.distribute()
        self.assertEqual(period.released_usd, Decimal("0.225806451"))

    def test_new_receipt_does_not_reassign_operating_costs_from_a_mature_receipt(self):
        funding.record_contribution(
            amount_usd=Decimal("10"),
            reference="old-cash",
            occurred_at=NOW - timedelta(days=40),
        )
        funding.record_operating(
            kind="expense",
            amount_usd=Decimal("10"),
            reference="old-hosting",
            occurred_at=NOW - timedelta(days=1),
        )
        funding.record_contribution(
            amount_usd=Decimal("10"), reference="new-cash", occurred_at=NOW
        )
        funding.approve_funding()
        period = funding.distribute()
        self.assertEqual(period.released_usd, Decimal("2.258064516"))

    def test_new_operating_provision_keeps_the_old_receipts_processing_schedule(self):
        previous_week = NOW - timedelta(days=7)
        with patch("django.utils.timezone.now", return_value=previous_week):
            self.contribute("0.01", reference="old", at=NOW - timedelta(days=40))
            funding.record_operating(
                kind="expense",
                amount_usd=Decimal("0.004"),
                reference="old-hosting",
                occurred_at=previous_week,
            )
            funding.distribute()
            operation, _ = ledger.reserve(self.user, uuid.uuid4(), "old-work", 1000)
            ledger.authorize(operation, Decimal("0.004"))
            ledger.settle(operation, cost=Decimal("0.004"))
        funding.record_contribution(
            amount_usd=Decimal("0.01"), reference="new", occurred_at=NOW
        )
        funding.record_operating(
            kind="reserve",
            amount_usd=Decimal("0.004"),
            reference="new-hosting",
            occurred_at=NOW,
        )
        funding.approve_funding()
        period = funding.distribute()
        # Old net 0.006 + new net 0.006 * 7/31 - paid processing 0.004.
        self.assertEqual(period.released_usd, Decimal("0.003354838"))

    def test_operating_release_and_payment_do_not_charge_processing_twice(self):
        self.contribute()
        reserve = dict(
            kind="reserve",
            amount_usd=Decimal("4"),
            reference="hosting",
            occurred_at=NOW,
        )
        funding.record_operating(**reserve)
        funding.record_operating(**reserve)
        funding.record_operating(
            kind="expense",
            amount_usd=Decimal("2"),
            reference="paid",
            occurred_at=NOW,
        )
        release = dict(
            kind="release",
            amount_usd=Decimal("1"),
            reference="unused",
            occurred_at=NOW,
        )
        funding.record_operating(**release)
        funding.record_operating(**release)
        self.assertEqual(funding.distribute().released_usd, Decimal("1.580645161"))

    def test_newcomer_receives_time_proportional_share_bounded_by_reserve(self):
        self.contribute()
        period = funding.distribute()
        before = period.newcomers_remaining_usd
        newcomer, _ = client_for("new@example.test")
        middle = NOW + timedelta(days=3, hours=12)
        with patch("django.utils.timezone.now", return_value=middle):
            usage = ledger.usage(newcomer)
        quota = WeeklyQuota.objects.get(user=newcomer)
        self.assertEqual(
            quota.allocated_usd, before
        )  # half a regular share exceeds 20% pool
        self.assertEqual(usage["allocation_status"], "available")
        waiter, _ = client_for("wait@example.test")
        with patch("django.utils.timezone.now", return_value=middle):
            waiting = ledger.usage(waiter)
        self.assertEqual(waiting["allocation_status"], "waiting")
        self.assertEqual(waiting["remaining_percent"], 0)
        self.assertFalse(waiting["hosted_available"])
        self.assertFalse(WeeklyQuota.objects.filter(user=waiter).exists())
        # No borrowing a future donation or altering existing shares.
        with patch("django.utils.timezone.now", return_value=middle):
            self.contribute("10", reference="later", at=middle)
            self.assertEqual(ledger.usage(waiter)["allocation_status"], "waiting")
        self.assertEqual(
            WeeklyQuota.objects.get(user=self.user).allocated_usd,
            period.regular_share_usd,
        )
        with patch("django.utils.timezone.now", return_value=period.reset_at):
            self.assertEqual(ledger.usage(waiter)["allocation_status"], "available")

    def test_individual_quota_expires_but_real_unused_cash_remains(self):
        self.contribute()
        first = funding.distribute()
        old = WeeklyQuota.objects.get(user=self.user)
        with patch("django.utils.timezone.now", return_value=first.reset_at):
            second = funding.distribute()
            new = WeeklyQuota.objects.get(user=self.user, period=second)
            # With no actual processing cost the second allocation is the total
            # released cash to date, not last week's personal quota plus it.
            self.assertEqual(second.released_usd, Decimal("4.516129032"))  # 14/31 * 10
            self.assertEqual(new.used_usd, 0)
            self.assertEqual(new.allocated_usd, second.regular_share_usd)
            self.assertEqual(funding.public_summary()["received_usd"], "10.000000000")
        old.refresh_from_db()
        self.assertEqual(old.allocated_usd, first.regular_share_usd)
        self.assertNotEqual(new.pk, old.pk)

    def test_monday_boundary_is_utc_even_across_month_and_timezone(self):
        now = datetime(2026, 11, 2, 2, tzinfo=dt_timezone(timedelta(hours=2)))
        start, reset = funding.week_bounds(now)
        self.assertEqual(start.isoformat(), "2026-11-02T00:00:00+00:00")
        self.assertEqual(reset.isoformat(), "2026-11-09T00:00:00+00:00")

    def test_manual_finance_command_is_idempotent_and_releases_unspent_provision(self):
        out = io.StringIO()
        args = [
            "contribution",
            "10",
            "--reference",
            "cli-receipt",
            "--occurred-at",
            NOW.isoformat(),
        ]
        call_command("record_finance", *args, stdout=out)
        call_command("record_finance", *args, stdout=out)
        self.assertIn("Already recorded", out.getvalue())
        funding.record_operating(
            kind="reserve",
            amount_usd=Decimal("2"),
            reference="cli-reserve",
            occurred_at=NOW,
        )
        funding.record_operating(
            kind="release",
            amount_usd=Decimal("1"),
            reference="cli-release",
            occurred_at=NOW,
        )
        self.assertEqual(
            funding.public_summary()["operating_reserved_usd"], "1.000000000"
        )

    @patch("cloud.service.groq.perform")
    def test_500_active_users_can_afford_work_below_the_old_two_cent_reservation(
        self, provider
    ):
        users = [
            User(
                email=f"person{index}@example.test",
                hosted_requested_at=NOW - timedelta(days=7),
                hosted_last_active_at=NOW - timedelta(days=1),
            )
            for index in range(499)
        ]
        User.objects.bulk_create(users)
        EmailAddress.objects.bulk_create(
            [
                EmailAddress(user=user, email=user.email, primary=True, verified=True)
                for user in users
            ]
        )
        self.contribute()
        funding.record_operating(
            kind="reserve",
            amount_usd=Decimal("4"),
            reference="server-month",
            occurred_at=NOW,
        )
        provider.side_effect = [{"text": "Original."}, groq.ProviderFailure()]
        operation_id = uuid.uuid4()
        response = test_dictation.DictationTests.send(self, operation_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "Original.")
        operation = Operation.objects.get(operation_id=operation_id)
        self.assertLess(operation.reserved_cost, ledger.MAX_COST)
        self.assertGreater(operation.cost, 0)
        self.assertLessEqual(operation.cost, operation.reserved_cost)
        payload = provider.call_args_list[1].kwargs["json"]
        messages = payload["messages"]
        bound = sum(len(message["content"].encode()) for message in messages) + 256
        provider_bound = ledger.asr_cost(1000) + funding.money(
            bound * groq.INPUT_RATE
            + payload["max_completion_tokens"] * groq.OUTPUT_RATE,
            up=True,
        )
        self.assertLessEqual(provider_bound, operation.reserved_cost)
        self.assertLess(payload["max_completion_tokens"], 8192)
        self.assertEqual(self.client.get("/v1/usage").json()["schema_version"], 2)

    @patch("cloud.service.groq.perform")
    def test_asr_only_quota_returns_text_without_unfunded_rewrite(self, provider):
        # A fully released receipt can fund ASR, with too little for chat input.
        self.contribute("0.0002", at=NOW - timedelta(days=32))
        funding.distribute()
        provider.return_value = {"text": "Original."}
        response = test_dictation.DictationTests.send(self, uuid.uuid4())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["rewritten"])
        provider.assert_called_once()
        self.assertEqual(Operation.objects.get().cost, ledger.asr_cost(1000))
        self.assertEqual(Treasury.objects.get().processing_spent, ledger.asr_cost(1000))

    @patch("cloud.service.groq.perform")
    def test_insufficient_quota_rejects_audio_before_any_provider_charge(
        self, provider
    ):
        self.contribute("0.0001", at=NOW - timedelta(days=32))
        response = test_dictation.DictationTests.send(self, uuid.uuid4())
        self.assertEqual(response.status_code, 429)
        provider.assert_not_called()
        self.assertEqual(Treasury.objects.get().processing_spent, 0)


class FundingMigrationTests(TransactionTestCase):
    def test_cost_review_upgrade_preserves_net_cash_and_requires_confirmation(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes("service")
        previous = [("service", "0005_public_finance_snapshot")]
        try:
            executor.migrate(previous)
            apps = executor.loader.project_state(previous).apps
            Entry = apps.get_model("service", "FundingEntry")
            for reference, at in (("old", NOW - timedelta(days=40)), ("new", NOW)):
                Entry.objects.create(
                    kind="contribution",
                    amount_usd=Decimal("10"),
                    source="manual",
                    reference=reference,
                    occurred_at=at,
                    release_until=at + timedelta(days=31),
                )
            for kind, amount, consumed in (
                ("expense", "4", "0"),
                ("reserve", "4", "0"),
                ("expense", "1", "1"),
                ("release", "1", "0"),
            ):
                Entry.objects.create(
                    kind="operating_" + kind,
                    amount_usd=Decimal(amount),
                    source="manual",
                    reference=kind + amount,
                    occurred_at=NOW,
                    reserve_consumed_usd=Decimal(consumed),
                )
            apps.get_model("service", "Treasury").objects.create(
                pk=1, processing_spent=Decimal("2")
            )
            MigrationExecutor(connection).migrate(latest)
            receipts = FundingEntry.objects.filter(kind="contribution").order_by(
                "occurred_at"
            )
            self.assertEqual(
                list(receipts.values_list("processing_basis_usd", flat=True)),
                [Decimal("3"), Decimal("10")],
            )
            self.assertFalse(receipts.exclude(processing_ready_at=None).exists())
            self.assertEqual(Treasury.objects.get().processing_spent, Decimal("2"))
        finally:
            MigrationExecutor(connection).migrate(latest)

    def test_upgrade_preserves_historical_costs_and_uncertain_inflight_charges(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes("service")
        previous = [("service", "0003_snippetlibrary")]
        try:
            executor.migrate(previous)
            apps = executor.loader.project_state(previous).apps
            old_user = apps.get_model("service", "User").objects.create(
                email="historical@example.test", last_login=timezone.now()
            )
            old_budget = apps.get_model("service", "Budget")
            old_budget.objects.create(
                month="2026-09-01", spent=Decimal("1.25"), reserved=Decimal("0.02")
            )
            old_budget.objects.create(month="1970-01-01", spent=Decimal("999"))
            apps.get_model("service", "Operation").objects.create(
                user=old_user,
                operation_id=uuid.uuid4(),
                month="2026-09-01",
                fingerprint="old",
                audio_ms=1000,
                reserved_cost=Decimal("0.02"),
                lease_until=timezone.now() - timedelta(days=1),
            )
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            treasury = Treasury.objects.get()
            self.assertEqual(treasury.processing_spent, Decimal("1.25"))
            self.assertEqual(treasury.processing_reserved, Decimal("0.02"))
            self.assertEqual(funding.public_summary()["received_usd"], "0.000000000")
            historical = [
                entry
                for entry in funding.public_summary()["movements"]
                if entry["kind"] == "historical_processing_cost"
            ]
            self.assertEqual(len(historical), 1)
            self.assertIsNone(historical[0]["occurred_at"])
            self.assertEqual(historical[0]["amount_usd"], "1.250000000")
            self.assertIsNotNone(User.objects.get(pk=old_user.pk).hosted_requested_at)
            ledger.expire_leases()
            ledger.expire_leases()
            treasury.refresh_from_db()
            self.assertEqual(treasury.processing_spent, Decimal("1.27"))
            self.assertEqual(treasury.processing_reserved, 0)
            Operation.objects.all().delete()
            self.assertEqual(
                funding.public_summary()["processing_spent_usd"], "1.270000000"
            )
        finally:
            MigrationExecutor(connection).migrate(latest)
