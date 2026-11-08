"""Public financial reads must not hold up private financial writes."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import threading
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from cloud.service import funding
from cloud.service.models import Treasury


@override_settings(CLARIFY_STRIPE_READ_KEY="", ROOT_URLCONF="cloud.urls")
class PublicFinancialReadTests(TransactionTestCase):
    def setUp(self):
        funding.record_contribution(
            amount_usd=Decimal("10"), reference="cash", occurred_at=timezone.now()
        )

    @patch("cloud.service.middleware.time.time", return_value=1792961000)
    def test_public_html_is_rate_limited_before_unbounded_reads(self, clock):
        client = Client()
        for _ in range(60):
            self.assertEqual(client.get("/transparency/").status_code, 200)
        self.assertEqual(client.get("/transparency/").status_code, 429)
        self.assertEqual(client.get("/v1/public/finances").status_code, 429)
        self.assertEqual(
            client.get("/transparency/assets/transparency.css").status_code, 200
        )

    def test_public_page_does_not_wait_for_the_treasury_write_mutex(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locks")
        locked, release = threading.Event(), threading.Event()

        def hold_treasury():
            close_old_connections()
            try:
                with transaction.atomic():
                    Treasury.objects.select_for_update().get(pk=1)
                    locked.set()
                    release.wait(10)
            finally:
                connections.close_all()

        def read_page():
            close_old_connections()
            try:
                return Client().get("/transparency/").status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(hold_treasury)
            self.assertTrue(locked.wait(5))
            reader = pool.submit(read_page)
            try:
                self.assertEqual(reader.result(timeout=5), 200)
            finally:
                release.set()
            writer.result(timeout=5)

    def test_public_totals_and_movements_share_one_snapshot_during_a_write(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL snapshot isolation")
        read_started, written = threading.Event(), threading.Event()
        main_thread = threading.get_ident()
        original = funding._commitments
        triggered = False

        def writer():
            close_old_connections()
            try:
                if not read_started.wait(5):
                    raise AssertionError("Reader did not start")
                funding.record_operating(
                    kind="reserve",
                    amount_usd=Decimal("1"),
                    reference="concurrent-hosting",
                    occurred_at=timezone.now(),
                )
            finally:
                written.set()
                connections.close_all()

        def interleave(now):
            nonlocal triggered
            if threading.get_ident() == main_thread and not triggered:
                triggered = True
                read_started.set()
                self.assertTrue(written.wait(5))
            return original(now)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(writer)
            with patch.object(funding, "_commitments", side_effect=interleave):
                summary = funding.public_summary()
            future.result(timeout=5)
        self.assertEqual(Decimal(summary["operating_reserved_usd"]), Decimal("0"))
        self.assertEqual(Decimal(summary["available_usd"]), Decimal("10"))
        self.assertEqual(
            [row["kind"] for row in summary["movements"]], ["contribution"]
        )
        after = funding.public_summary()
        self.assertEqual(Decimal(after["operating_reserved_usd"]), Decimal("1"))
        self.assertEqual(Decimal(after["available_usd"]), Decimal("9"))
