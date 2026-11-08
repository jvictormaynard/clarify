"""No external HTTP. Provider bodies and private identifiers must not survive."""

from datetime import datetime, timezone
import io
import json
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
import requests

from cloud.service import stripe_finance as stripe
from cloud.service.transparency_models import (
    PublicFinanceSnapshot,
    PublicStripeBalance,
    PublicStripeMovement,
)

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)
KEY = "rk_live_FAKEONLY"


def movement(identifier="txn_FAKE1", **changes):
    return {
        "object": "balance_transaction",
        "id": identifier,
        "created": 1792800000,
        "available_on": 1792800000,
        "type": "charge",
        "amount": 1000,
        "fee": 60,
        "net": 940,
        "currency": "usd",
        "status": "available",
        "description": '<script>alert("private@example.test")</script>',
        "source": "ch_PRIVATE",
        "customer": {"email": "private@example.test"},
        **changes,
    }


def balance(**changes):
    return {
        "object": "balance",
        "livemode": True,
        "available": [{"amount": 940, "currency": "usd"}],
        "pending": [{"amount": 200, "currency": "eur"}],
        **changes,
    }


def listing(rows=None, more=False):
    return {
        "object": "list",
        "data": [movement()] if rows is None else rows,
        "has_more": more,
        "url": "https://evil.example/private",
    }


def response(value, status=200):
    reply = Mock()
    reply.status_code = status
    reply.iter_content.return_value = [json.dumps(value).encode()]
    reply.__enter__ = Mock(return_value=reply)
    reply.__exit__ = Mock(return_value=False)
    return reply


def http(*values):
    return Mock(side_effect=[response(value) for value in values])


class StripeReaderTests(SimpleTestCase):
    def test_pagination_refunds_fees_and_mixed_currencies_are_allowlisted(self):
        get = http(
            balance(),
            listing(more=True),
            listing(
                [
                    movement(
                        "txn_FAKE2", type="refund", amount=-1000, fee=-60, net=-940
                    ),
                    movement("txn_FAKE3", type="payout", amount=-940, fee=0, net=-940),
                    movement(
                        "txn_FAKE4",
                        type="stripe_fee",
                        amount=-20,
                        fee=0,
                        net=-20,
                        currency="eur",
                    ),
                ]
            ),
        )
        balances, rows, complete = stripe.fetch_snapshot(KEY, get=get, now=NOW)
        self.assertTrue(complete)
        self.assertEqual(
            balances,
            [
                {"currency": "eur", "available_minor": 0, "pending_minor": 200},
                {"currency": "usd", "available_minor": 940, "pending_minor": 0},
            ],
        )
        self.assertEqual(
            [row["kind"] for row in rows], ["payment", "refund", "payout", "fee"]
        )
        self.assertEqual(rows[1]["net_minor"], -940)
        self.assertEqual(
            set(rows[0]),
            {
                "occurred_at",
                "available_on",
                "kind",
                "currency",
                "amount_minor",
                "fee_minor",
                "net_minor",
                "availability",
            },
        )
        self.assertNotIn("PRIVATE", str(rows))
        for call in get.call_args_list:
            self.assertTrue(call.args[0].startswith("https://api.stripe.com/v1/"))
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertEqual(call.kwargs["timeout"], (5, 20))
        self.assertEqual(
            get.call_args_list[2].kwargs["params"]["starting_after"], "txn_FAKE1"
        )

    def test_page_limit_is_explicit_partial_history(self):
        with patch.object(stripe, "MAX_PAGES", 1):
            _, rows, complete = stripe.fetch_snapshot(
                KEY, get=http(balance(), listing(more=True)), now=NOW
            )
        self.assertFalse(complete)
        self.assertEqual(len(rows), 1)

    def test_test_mode_and_nonrestricted_keys_never_publish(self):
        for key in (
            "rk_test_FAKE",
            "sk_test_FAKE",
            "sk_live_FAKE",
            "https://evil.example",
        ):
            get = Mock()
            with self.subTest(key=key), self.assertRaises(stripe.StripeSyncError):
                stripe.fetch_snapshot(key, get=get, now=NOW)
            get.assert_not_called()
        with self.assertRaisesRegex(stripe.StripeSyncError, "test_mode"):
            stripe.fetch_snapshot(KEY, get=http(balance(livemode=False)), now=NOW)
        with self.assertRaisesRegex(stripe.StripeSyncError, "test_mode"):
            stripe.fetch_snapshot(
                KEY, get=http(balance(), listing([movement(livemode=False)])), now=NOW
            )

    def test_provider_errors_are_bounded_and_do_not_leak(self):
        for failure in (
            requests.Timeout("rk_live_SECRET private@example.test"),
            requests.ConnectionError("secret"),
        ):
            with self.assertRaisesRegex(stripe.StripeSyncError, "^unavailable$"):
                stripe.fetch_snapshot(KEY, get=Mock(side_effect=failure), now=NOW)
        for status in (302, 401, 429, 500):
            with self.assertRaisesRegex(stripe.StripeSyncError, "^unavailable$"):
                stripe.fetch_snapshot(
                    KEY,
                    get=Mock(return_value=response({"secret": KEY}, status)),
                    now=NOW,
                )
        oversized = response({})
        oversized.iter_content.return_value = [b"x" * (stripe.MAX_BODY + 1)]
        with self.assertRaises(stripe.StripeSyncError):
            stripe.fetch_snapshot(KEY, get=Mock(return_value=oversized), now=NOW)

    def test_malformed_or_repeated_pages_fail_safely(self):
        values = [
            listing([], True),
            listing([movement(amount=True)]),
            listing([movement(net=99)]),
            listing([movement(currency="usd<script>")]),
            listing([movement(type={"email": "private"})]),
        ]
        for value in values:
            with self.subTest(value=value), self.assertRaises(stripe.StripeSyncError):
                stripe.fetch_snapshot(KEY, get=http(balance(), value), now=NOW)
        with self.assertRaisesRegex(stripe.StripeSyncError, "invalid_response"):
            stripe.fetch_snapshot(
                KEY, get=http(balance(), listing(more=True), listing()), now=NOW
            )


@override_settings(CLARIFY_STRIPE_READ_KEY=KEY)
class StripePersistenceTests(TestCase):
    def test_sync_is_persistent_sanitized_and_does_not_duplicate_movements(self):
        for _ in range(2):
            stripe.sync(get=http(balance(), listing()), now=NOW)
        self.assertEqual(PublicFinanceSnapshot.objects.count(), 1)
        self.assertEqual(PublicStripeMovement.objects.count(), 1)
        self.assertEqual(PublicStripeBalance.objects.count(), 2)
        dump = io.StringIO()
        call_command(
            "dumpdata",
            "service.PublicStripeMovement",
            "service.PublicStripeBalance",
            stdout=dump,
        )
        for private in (
            KEY,
            "PRIVATE",
            "private@example.test",
            "description",
            "source",
            "txn_FAKE",
        ):
            self.assertNotIn(private, dump.getvalue())

    def test_error_retains_last_good_snapshot_and_safe_status(self):
        stripe.sync(get=http(balance(), listing()), now=NOW)
        with self.assertRaises(stripe.StripeSyncError):
            stripe.sync(get=Mock(side_effect=requests.Timeout("private")), now=NOW)
        snapshot = PublicFinanceSnapshot.objects.get(pk=1)
        self.assertEqual(snapshot.synced_at, NOW)
        self.assertEqual(snapshot.error_code, "unavailable")
        self.assertEqual(PublicStripeMovement.objects.count(), 1)

    def test_new_credential_does_not_inherit_old_account_balances(self):
        stripe.sync(get=http(balance(), listing()), now=NOW)
        with override_settings(CLARIFY_STRIPE_READ_KEY="rk_live_OTHERFAKE"):
            with self.assertRaises(stripe.StripeSyncError):
                stripe.sync(get=Mock(side_effect=requests.Timeout()), now=NOW)
        self.assertFalse(PublicStripeMovement.objects.exists())
        self.assertFalse(PublicStripeBalance.objects.exists())
        self.assertIsNone(PublicFinanceSnapshot.objects.get(pk=1).synced_at)

    def test_operator_command_outputs_safe_error_only(self):
        output = io.StringIO()
        with patch.object(stripe.requests, "get", side_effect=requests.Timeout(KEY)):
            with self.assertRaisesRegex(
                CommandError, "^Stripe finance sync failed: unavailable$"
            ):
                call_command("sync_stripe_finance", stdout=output)
        self.assertNotIn(KEY, output.getvalue())


@override_settings(CLARIFY_STRIPE_READ_KEY=KEY)
class StripePublicationTests(TransactionTestCase):
    def test_provider_latency_does_not_hold_public_snapshot_row_lock(self):
        from django.db import connection

        fake = http(balance(), listing())

        def get(*args, **kwargs):
            self.assertFalse(
                connection.in_atomic_block,
                "External HTTP must not hold the public snapshot lock",
            )
            return fake(*args, **kwargs)

        stripe.sync(get=get, now=NOW)

    def test_newer_attempt_wins_if_an_older_sync_finishes_last(self):
        fake = http(balance(), listing())
        triggered = False

        def get(*args, **kwargs):
            nonlocal triggered
            if not triggered:
                triggered = True
                stripe.sync(
                    get=http(
                        balance(available=[{"amount": 1234, "currency": "usd"}]),
                        listing([]),
                    ),
                    now=NOW,
                )
            return fake(*args, **kwargs)

        with self.assertRaisesRegex(stripe.StripeSyncError, "superseded"):
            stripe.sync(get=get, now=NOW)
        self.assertEqual(
            PublicStripeBalance.objects.get(currency="usd").available_minor, 1234
        )
        self.assertFalse(PublicStripeMovement.objects.exists())
