import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from cloud.service import funding, ledger
from cloud.service.models import Allowance, Budget, Operation, Treasury, WeeklyQuota

from .test_api import client_for, fund_hosted


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class LedgerTests(TransactionTestCase):
    def setUp(self):
        self.a, _ = client_for("a@example.test")
        self.b, _ = client_for("b@example.test")
        fund_hosted(self.a, self.b)

    def reserve(self, user=None, key=None, fingerprint="a", duration=1000):
        return ledger.reserve(
            user or self.a, key or uuid.uuid4(), fingerprint, duration
        )

    def test_idempotency_is_scoped_to_account_and_content(self):
        key = uuid.uuid4()
        first, fresh = self.reserve(key=key)
        self.assertTrue(fresh)
        with self.assertRaises(ledger.Rejected) as rejected:
            self.reserve(key=key)
        self.assertEqual(rejected.exception.code, "operation_pending")
        result = {"transcript": "A", "text": "A.", "rewritten": True}
        ledger.settle(first, result=result, cost=Decimal("0.001"))
        cached, fresh = self.reserve(key=key)
        self.assertFalse(fresh)
        self.assertEqual(cached.result, result)
        with self.assertRaises(ledger.Rejected) as rejected:
            self.reserve(key=key, fingerprint="b")
        self.assertEqual(rejected.exception.code, "operation_conflict")
        other, fresh = self.reserve(user=self.b, key=key)
        self.assertTrue(fresh)
        self.assertNotEqual(first.pk, other.pk)
        self.assertGreater(ledger.usage(self.a)["used_percent"], 0)
        self.assertEqual(Treasury.objects.get().processing_spent, Decimal("0.001"))

    def test_failed_paid_work_keeps_uncertain_cost_and_debits_quota_once(self):
        operation, _ = self.reserve()
        ledger.authorize(operation, Decimal("0.003"))
        ledger.settle(operation)
        ledger.settle(operation)
        budget = Budget.objects.get(month=ledger.month_start())
        self.assertEqual(budget.spent, Decimal("0.003"))
        self.assertEqual(budget.reserved, 0)
        operation.refresh_from_db()
        self.assertEqual(operation.quota_debit, operation.cost)
        self.assertEqual(WeeklyQuota.objects.get(user=self.a).used_usd, operation.cost)
        self.assertEqual(Treasury.objects.get().processing_spent, operation.cost)

    def test_failure_before_paid_work_releases_reservation_without_cost(self):
        operation, _ = self.reserve()
        ledger.settle(operation)
        self.assertEqual(Treasury.objects.get().processing_spent, 0)
        self.assertEqual(WeeklyQuota.objects.get(user=self.a).used_usd, 0)
        self.assertEqual(ledger.usage(self.a)["remaining_percent"], 100)

    def test_monthly_operation_limit_does_not_reset_with_weekly_quota(self):
        Allowance.objects.create(
            user=self.a, month=ledger.month_start(), operations=2000
        )
        with self.assertRaises(ledger.Rejected) as rejected:
            self.reserve()
        self.assertEqual(rejected.exception.code, "allowance_exhausted")
        self.assertFalse(Operation.objects.exists())

    def test_processing_movement_survives_operation_retention_and_has_no_identity(self):
        operation, _ = self.reserve()
        ledger.authorize(operation, Decimal("0.001"))
        ledger.settle(operation, result={"text": "private text"}, cost=Decimal("0.001"))
        ledger.settle(operation, result={"text": "private text"}, cost=Decimal("0.001"))
        operation.delete()
        summary = funding.public_summary()
        costs = [
            entry
            for entry in summary["movements"]
            if entry["kind"] == "processing_cost"
        ]
        self.assertEqual(len(costs), 1)
        self.assertEqual(costs[0]["amount_usd"], "0.001000000")
        self.assertEqual(costs[0]["source"], "project")
        self.assertEqual(summary["processing_spent_usd"], "0.001000000")
        self.assertNotIn(str(operation.operation_id), str(summary))
        self.assertNotIn("private text", str(summary))
        self.assertNotIn(self.a.email, str(summary))

    def test_real_grants_protect_inflight_cost(self):
        first, _ = self.reserve()
        other, _ = self.reserve(user=self.b)
        self.assertEqual(
            Treasury.objects.get().processing_reserved,
            first.reserved_cost + other.reserved_cost,
        )
        summary = funding.public_summary()
        self.assertEqual(Decimal(summary["allocated_usd"]), Decimal("80"))
        with self.assertRaises(ValueError):
            funding.record_operating(
                kind="expense",
                amount_usd=Decimal("1"),
                reference="cannot-spend-grants",
                occurred_at=timezone.now(),
            )

    @override_settings(CLARIFY_MONTHLY_BUDGET_USD="0")
    def test_monthly_cap_remains_required_even_with_received_cash(self):
        with self.assertRaises(ledger.Rejected) as rejected:
            self.reserve()
        self.assertEqual(rejected.exception.code, "service_budget_exhausted")
        self.assertFalse(Operation.objects.exists())

    @override_settings(CLARIFY_MONTHLY_BUDGET_USD="0.003")
    def test_near_cap_request_reserves_only_affordable_work(self):
        Budget.objects.create(month=ledger.month_start(), spent=Decimal("0.0028"))
        operation, _ = self.reserve()
        self.assertEqual(operation.reserved_cost, Decimal("0.0002"))
        ledger.authorize(operation, ledger.asr_cost(1000))
        ledger.settle(operation, result={"text": "A"}, cost=ledger.asr_cost(1000))
        with self.assertRaises(ledger.Rejected) as rejected:
            self.reserve(user=self.b)
        self.assertEqual(rejected.exception.code, "service_budget_exhausted")

    @override_settings(CLARIFY_MONTHLY_BUDGET_USD="0.02")
    def test_running_old_month_reservation_counts_against_the_new_month_cap(self):
        from datetime import datetime
        from datetime import timezone as dt_timezone
        from unittest.mock import patch

        before = datetime(2026, 10, 31, 23, 59, 50, tzinfo=dt_timezone.utc)
        after = before + timedelta(seconds=20)
        with patch("django.utils.timezone.now", return_value=before):
            first, _ = self.reserve()
            ledger.authorize(first, Decimal("0.001"))
        with patch("django.utils.timezone.now", return_value=after):
            with self.assertRaises(ledger.Rejected) as rejected:
                self.reserve(user=self.b)
            self.assertEqual(rejected.exception.code, "service_budget_exhausted")
            ledger.settle(first, result={"text": "A"}, cost=Decimal("0.001"))
            second, _ = self.reserve(user=self.b)
        self.assertEqual(second.reserved_cost, Decimal("0.02"))
        self.assertNotEqual(first.month, second.month)

    @override_settings(CLARIFY_MONTHLY_BUDGET_USD="0.0002")
    def test_concurrent_admissions_cannot_exceed_a_tiny_monthly_cap(self):
        def admit(index):
            try:
                self.reserve(user=[self.a, self.b][index])
                return "accepted"
            except ledger.Rejected as error:
                return error.code

        results = self.parallel(admit)
        self.assertCountEqual(results, ["accepted", "service_budget_exhausted"])
        self.assertEqual(Treasury.objects.get().processing_reserved, Decimal("0.0002"))

    def test_abandoned_lease_is_charged_once_and_never_replayed(self):
        operation, _ = self.reserve()
        ledger.authorize(operation, ledger.MAX_COST)
        Operation.objects.filter(pk=operation.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        ledger.expire_leases()
        ledger.expire_leases()
        self.assertEqual(
            Budget.objects.get(month=ledger.month_start()).spent, ledger.MAX_COST
        )
        with self.assertRaises(ledger.Rejected) as rejected:
            self.reserve(key=operation.operation_id)
        self.assertEqual(rejected.exception.code, "operation_expired")
        self.reserve()  # The account is no longer permanently busy.

    @override_settings(CLARIFY_GLOBAL_CONCURRENCY=1)
    def test_parallel_admission_has_one_winner(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires actual PostgreSQL row locks")

        def attempt(user):
            close_old_connections()
            try:
                self.reserve(user=user)
                return "accepted"
            except ledger.Rejected as error:
                return error.code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [self.a, self.b]))
        self.assertCountEqual(results, ["accepted", "service_busy"])
        self.assertEqual(Operation.objects.count(), 1)

    def parallel(self, action):
        if connection.vendor != "postgresql":
            self.skipTest("Requires actual PostgreSQL row locks")

        def attempt(index):
            close_old_connections()
            try:
                return action(index)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(attempt, range(2)))

    def test_parallel_settlement_debits_provider_cost_only_once(self):
        operation, _ = self.reserve()
        ledger.authorize(operation, Decimal("0.001"))
        self.parallel(
            lambda _: ledger.settle(
                operation, result={"text": "A"}, cost=Decimal("0.001")
            )
        )
        self.assertEqual(Treasury.objects.get().processing_spent, Decimal("0.001"))
        self.assertEqual(Treasury.objects.get().processing_reserved, 0)
        self.assertEqual(
            WeeklyQuota.objects.get(user=self.a).used_usd, Decimal("0.001")
        )

    def test_parallel_receipt_retry_records_cash_only_once(self):
        at = timezone.now()
        results = self.parallel(
            lambda _: funding.record_contribution(
                amount_usd=Decimal("10"), reference="parallel", occurred_at=at
            )[1]
        )
        self.assertCountEqual(results, [True, False])
        self.assertEqual(funding.public_summary()["received_usd"], "110.000000000")

    def test_reset_does_not_release_unsettled_provider_reservations(self):
        operation, _ = self.reserve()
        ledger.authorize(operation, Decimal("0.001"))
        _, reset = funding.week_bounds()
        from unittest.mock import patch

        with patch("django.utils.timezone.now", return_value=reset):
            funding.distribute()
            before = Decimal(funding.public_summary()["available_usd"])
            ledger.expire_leases()
            after = Decimal(funding.public_summary()["available_usd"])
        self.assertEqual(after - before, operation.reserved_cost - Decimal("0.001"))
        self.assertEqual(Treasury.objects.get().processing_spent, Decimal("0.001"))
