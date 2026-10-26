import json
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from cloud.service import admin_analytics
from cloud.service.models import (
    Allowance,
    Budget,
    FundingPeriod,
    Operation,
    WeeklyQuota,
)


@override_settings(CLARIFY_MONTHLY_BUDGET_USD="10", CLARIFY_MONTHLY_AUDIO_MS=18000000)
class AdminAnalyticsTests(TestCase):
    now = datetime(2026, 10, 24, 12, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def user(self, email, *, days=1, verified=True, **kwargs):
        user = get_user_model().objects.create_user(email, **kwargs)
        get_user_model().objects.filter(pk=user.pk).update(
            date_joined=self.now - timedelta(days=days)
        )
        EmailAddress.objects.create(
            user=user, email=email, verified=verified, primary=True
        )
        return user

    def operation(
        self, user, *, days=0, state="complete", audio_ms=60000, cost="0.01", **kwargs
    ):
        operation = Operation.objects.create(
            user=user,
            operation_id=uuid.uuid4(),
            month=self.now.date().replace(day=1),
            fingerprint="x" * 64,
            state=state,
            lease_until=self.now + timedelta(minutes=1),
            audio_ms=audio_ms,
            reserved_cost=Decimal("0.02"),
            cost=Decimal(cost),
            result={"text": "PRIVATE TRANSCRIPT MUST NOT BE READ"},
            **kwargs,
        )
        Operation.objects.filter(pk=operation.pk).update(
            created_at=self.now - timedelta(days=days)
        )
        return operation

    def funding_period(self, start=None):
        start = start or datetime(2026, 10, 19, tzinfo=dt_timezone.utc)
        return FundingPeriod.objects.create(
            start=start,
            reset_at=start + timedelta(days=7),
            released_usd="10",
            regular_share_usd="1",
            newcomers_remaining_usd="2",
            population=8,
        )

    def test_cohort_activity_quality_and_cost_have_distinct_meanings(self):
        old = self.user("old@example.test", days=20)
        new = self.user("new@example.test", days=2)
        self.user("unverified@example.test", days=1, verified=False)
        self.operation(old, days=3)
        self.operation(new, days=1)
        self.operation(new, days=0)
        self.operation(new, days=0, state="uncertain", cost="0.02")
        self.operation(old, days=0, state="running", cost="0")
        result = admin_analytics.overview(7)
        self.assertEqual(result["metrics"]["total_users"], 3)
        self.assertEqual(result["metrics"]["new_users"], 2)
        self.assertEqual(result["metrics"]["active_users"], 2)
        self.assertEqual(result["metrics"]["returning_users"], 1)
        self.assertEqual(result["metrics"]["operations"], 5)
        self.assertEqual(result["metrics"]["audio_minutes"], 3)
        self.assertEqual(Decimal(result["metrics"]["cost_usd"]), Decimal("0.05"))
        self.assertEqual(result["metrics"]["success_rate"], 75)
        self.assertEqual(
            result["funnel"],
            {"registered": 2, "verified": 1, "activated": 1, "returning": 1},
        )
        self.assertEqual(
            result["health"], {"complete": 3, "uncertain": 1, "running": 1}
        )
        self.assertEqual(len(result["trend"]), 7)
        self.assertEqual(sum(day["operations"] for day in result["trend"]), 5)

    def test_empty_period_has_unknown_rate_and_zero_filled_dates(self):
        result = admin_analytics.overview("7")
        self.assertIsNone(result["metrics"]["success_rate"])
        self.assertEqual(result["trend"][0]["date"], "2026-10-18")
        self.assertEqual(result["trend"][-1]["date"], "2026-10-24")
        self.assertEqual(result["metrics"]["operations"], 0)
        self.assertIsNone(result["budget"]["projected_usd"])
        self.assertFalse(result["coverage"]["revenue_available"])
        json.dumps(result)

    def test_previous_period_is_unavailable_when_metadata_retention_cannot_cover_it(
        self,
    ):
        self.assertIsNone(admin_analytics.overview(30)["metrics"]["previous"])
        self.assertIsNotNone(admin_analytics.overview(14)["metrics"]["previous"])

    def test_calendar_window_excludes_old_and_future_operations(self):
        user = self.user("date@example.test", days=20)
        before = self.operation(user, days=7)
        boundary = self.operation(user)
        future = self.operation(user)
        Operation.objects.filter(pk=boundary.pk).update(
            created_at=datetime(2026, 10, 18, tzinfo=dt_timezone.utc)
        )
        Operation.objects.filter(pk=future.pk).update(
            created_at=self.now + timedelta(hours=1)
        )
        result = admin_analytics.overview(7)
        self.assertEqual(result["metrics"]["operations"], 1)
        self.assertEqual(result["metrics"]["previous"]["operations"], 1)
        self.assertEqual(before.state, "complete")

    def test_budget_uses_monthly_ledger_instead_of_retained_operation_sum(self):
        Budget.objects.create(
            month=self.now.date().replace(day=1), spent="4.2", reserved="0.3"
        )
        result = admin_analytics.overview(7)
        self.assertEqual(Decimal(result["budget"]["spent_usd"]), Decimal("4.2"))
        self.assertEqual(Decimal(result["budget"]["reserved_usd"]), Decimal("0.3"))
        self.assertEqual(Decimal(result["budget"]["remaining_usd"]), Decimal("5.5"))
        self.assertEqual(Decimal(result["metrics"]["cost_usd"]), 0)
        self.assertGreater(Decimal(result["budget"]["projected_usd"]), Decimal("4.2"))

    def test_search_segments_and_current_week_quota(self):
        active = self.user(
            "active@example.test", hosted_requested_at=self.now - timedelta(days=10)
        )
        self.user("inactive@example.test")
        unverified = self.user("pending@example.test", verified=False)
        self.operation(active, days=2)
        self.operation(unverified, days=1)
        Allowance.objects.create(
            user=active,
            month=self.now.date().replace(day=1),
            used_ms=60000,
            reserved_ms=1000,
        )
        period = self.funding_period()
        WeeklyQuota.objects.create(
            user=active,
            period=period,
            allocated_usd="0.5",
            used_usd="0.1",
            reserved_usd="0.05",
        )
        WeeklyQuota.objects.create(
            user=active,
            period=self.funding_period(period.start - timedelta(days=7)),
            allocated_usd="1",
            used_usd="1",
        )
        result = admin_analytics.users(7, search="ACTIVE@", segment="active", page="1")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["email"], active.email)
        self.assertEqual(
            result["results"][0]["quota"],
            {
                "schema_version": 2,
                "period_start": "2026-10-19T00:00:00+00:00",
                "reset_at": "2026-10-26T00:00:00+00:00",
                "used_percent": 20,
                "reserved_percent": 10,
                "remaining_percent": 70,
                "allocation_status": "available",
            },
        )
        for days in (7, 14, 30):
            self.assertEqual(
                admin_analytics.user_detail(active.pk, days)["user"]["quota"],
                result["results"][0]["quota"],
            )
        self.assertEqual(admin_analytics.users(7, segment="inactive")["count"], 1)
        self.assertEqual(admin_analytics.users(7, segment="unverified")["count"], 1)

    def test_weekly_quota_survives_month_boundary_and_expires_at_monday_utc(self):
        user = self.user("boundary@example.test", hosted_requested_at=self.now)
        start = datetime(2026, 10, 26, tzinfo=dt_timezone.utc)
        WeeklyQuota.objects.create(
            user=user,
            period=self.funding_period(start),
            allocated_usd="1",
            used_usd="0.25",
            reserved_usd="0.5",
        )
        with patch(
            "django.utils.timezone.now",
            return_value=datetime(2026, 11, 1, 23, 59, 59, tzinfo=dt_timezone.utc),
        ):
            quota = admin_analytics.user_detail(user.pk)["user"]["quota"]
        self.assertEqual(quota["remaining_percent"], 25)
        self.assertEqual(quota["reset_at"], "2026-11-02T00:00:00+00:00")
        with patch(
            "django.utils.timezone.now",
            return_value=datetime(2026, 11, 2, tzinfo=dt_timezone.utc),
        ):
            quota = admin_analytics.user_detail(user.pk)["user"]["quota"]
        self.assertEqual(quota["allocation_status"], "not_distributed")
        self.assertEqual(quota["used_percent"], 0)
        self.assertEqual(quota["remaining_percent"], 0)

    def test_weekly_allocation_states_do_not_claim_hosted_availability(self):
        requested = self.user("requested@example.test", hosted_requested_at=self.now)
        self.user("not-requested@example.test")
        self.user("disabled@example.test", is_active=False)
        self.user("not-funded@example.test", funded_access=False)
        self.user("not-verified@example.test", verified=False)
        mismatch = self.user("changed@example.test")
        EmailAddress.objects.filter(user=mismatch).update(email="old@example.test")

        def states():
            return {
                row["email"]: row["quota"]["allocation_status"]
                for row in admin_analytics.users()["results"]
            }

        self.assertEqual(
            states(),
            {
                requested.email: "not_distributed",
                "not-requested@example.test": "not_requested",
                "disabled@example.test": "inactive",
                "not-funded@example.test": "inactive",
                "not-verified@example.test": "inactive",
                mismatch.email: "inactive",
            },
        )
        period = self.funding_period()
        self.assertEqual(states()[requested.email], "waiting")
        quota = WeeklyQuota.objects.create(
            user=requested, period=period, allocated_usd="0"
        )
        self.assertEqual(states()[requested.email], "waiting")
        quota.allocated_usd = Decimal("1")
        quota.used_usd = Decimal("1.1")
        quota.reserved_usd = Decimal("0.1")
        quota.save()
        snapshot = admin_analytics.user_detail(requested.pk)["user"]["quota"]
        self.assertEqual(snapshot["allocation_status"], "available")
        self.assertEqual(snapshot["used_percent"], 100)
        self.assertEqual(snapshot["reserved_percent"], 0)
        self.assertEqual(snapshot["remaining_percent"], 0)
        quota.used_usd = Decimal("0.4")
        quota.reserved_usd = Decimal("0.8")
        quota.save()
        get_user_model().objects.filter(pk=requested.pk).update(funded_access=False)
        snapshot = admin_analytics.user_detail(requested.pk)["user"]["quota"]
        self.assertEqual(snapshot["allocation_status"], "inactive")
        self.assertEqual(snapshot["used_percent"], 40)
        self.assertEqual(snapshot["reserved_percent"], 60)
        self.assertEqual(snapshot["remaining_percent"], 0)

    def test_reading_weekly_quota_does_not_request_access_or_distribute_funds(self):
        user = self.user("read-weekly@example.test")
        with CaptureQueriesContext(connection) as queries:
            admin_analytics.users()
            admin_analytics.user_detail(user.pk)
        self.assertTrue(
            all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries)
        )
        user.refresh_from_db()
        self.assertIsNone(user.hosted_requested_at)
        self.assertIsNone(user.hosted_last_active_at)
        self.assertFalse(FundingPeriod.objects.exists())
        self.assertFalse(WeeklyQuota.objects.exists())

    def test_detail_has_no_processing_text_or_account_secrets(self):
        user = self.user("detail@example.test")
        self.operation(user, days=2)
        with CaptureQueriesContext(connection) as queries:
            result = admin_analytics.user_detail(str(user.pk), 7)
        self.assertEqual(result["user"]["id"], str(user.pk))
        self.assertEqual(result["health"]["complete"], 1)
        serialized = json.dumps(result)
        self.assertNotIn("PRIVATE TRANSCRIPT", serialized)
        self.assertNotIn("password", serialized)
        self.assertFalse(
            any(
                '"result"' in query["sql"] or '"password"' in query["sql"]
                for query in queries
            )
        )

    def test_list_query_count_does_not_grow_with_page_rows(self):
        for index in range(28):
            self.user(f"person{index:02d}@example.test")
        with self.assertNumQueries(6):
            first = admin_analytics.users(7)
        self.assertEqual(len(first["results"]), 25)
        self.assertEqual(first["pages"], 2)
        self.assertEqual(len(admin_analytics.users(7, page=2)["results"]), 3)
        self.assertEqual(admin_analytics.users(7, page=999999)["page"], 2)

    def test_deleted_users_do_not_count_as_active_accounts_but_cost_is_preserved(self):
        self.operation(None, days=1, cost="0.02")
        result = admin_analytics.overview(7)
        self.assertEqual(result["metrics"]["active_users"], 0)
        self.assertEqual(result["metrics"]["operations"], 1)
        self.assertEqual(Decimal(result["metrics"]["cost_usd"]), Decimal("0.02"))

    def test_reads_never_clean_up_or_settle_operations(self):
        user = self.user("read-only@example.test", days=50)
        old = self.operation(user, days=40, state="uncertain")
        with CaptureQueriesContext(connection) as queries:
            admin_analytics.overview(30)
            admin_analytics.users(30)
            detail = admin_analytics.user_detail(user.pk, 30)
        self.assertTrue(
            all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries)
        )
        self.assertIsNone(detail["user"]["last_active_at"])
        self.assertEqual(detail["user"]["operations"], 0)
        self.assertTrue(Operation.objects.filter(pk=old.pk).exists())
        self.assertIn(
            "PRIVATE TRANSCRIPT", Operation.objects.get(pk=old.pk).result["text"]
        )

    def test_trend_uses_utc_dates_even_with_another_active_timezone(self):
        from django.utils import timezone

        user = self.user("utc@example.test", days=20)
        operation = self.operation(user)
        Operation.objects.filter(pk=operation.pk).update(
            created_at=datetime(2026, 10, 18, 1, tzinfo=dt_timezone.utc)
        )
        with timezone.override("America/Sao_Paulo"):
            result = admin_analytics.overview(7)
        self.assertEqual(result["trend"][0]["date"], "2026-10-18")
        self.assertEqual(result["trend"][0]["operations"], 1)

    def test_inputs_are_bounded_and_invalid_values_fail(self):
        for days in (0, 1, 8, 31, "bad", None, True):
            with self.subTest(days=days), self.assertRaises(ValueError):
                admin_analytics.overview(days)
        for kwargs in (
            {"search": "a" * 255},
            {"segment": "staff"},
            {"page": 0},
            {"page": "bad"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                admin_analytics.users(**kwargs)
        with self.assertRaises(ValueError):
            admin_analytics.user_detail("not-a-uuid")
        with self.assertRaises(get_user_model().DoesNotExist):
            admin_analytics.user_detail(uuid.uuid4())
