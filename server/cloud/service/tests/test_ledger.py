from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import uuid

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from cloud.service import ledger
from cloud.service.models import Budget, Operation, User


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class LedgerTests(TransactionTestCase):
    def setUp(self):
        self.a = User.objects.create_user("a@example.test")
        self.b = User.objects.create_user("b@example.test")

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
        self.assertEqual(ledger.usage(self.a)["used_ms"], 1000)

    @override_settings(CLARIFY_MONTHLY_AUDIO_MS=1500)
    def test_failed_request_keeps_uncertain_provider_cost_and_consumes_audio(self):
        operation, _ = self.reserve()
        ledger.settle(operation)
        budget = Budget.objects.get(month=ledger.month_start())
        self.assertEqual(budget.spent, ledger.MAX_COST)
        self.assertEqual(budget.reserved, 0)
        with self.assertRaises(ledger.Rejected) as rejected:
            self.reserve()
        self.assertEqual(rejected.exception.code, "allowance_exhausted")

    @override_settings(CLARIFY_MONTHLY_BUDGET_USD="0.03")
    def test_inflight_cost_counts_against_global_budget(self):
        self.reserve()
        with self.assertRaises(ledger.Rejected) as rejected:
            self.reserve(user=self.b)
        self.assertEqual(rejected.exception.code, "service_budget_exhausted")

    def test_abandoned_lease_is_charged_once_and_never_replayed(self):
        operation, _ = self.reserve()
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
