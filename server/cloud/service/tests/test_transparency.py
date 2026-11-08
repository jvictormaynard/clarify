"""Anonymous finance schema, privacy, same-origin controls and page states."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.db import DatabaseError
from django.urls import path

from cloud.service import transparency as public
from cloud.service import stripe_finance as stripe
from cloud.service.tests.test_stripe_finance import (
    NOW,
    KEY,
    balance,
    http,
    listing,
    movement,
)
from cloud.service.transparency_models import PublicFinanceSnapshot

urlpatterns = [
    path("transparency/", public.page),
    path("transparency/assets/<str:name>", public.asset),
    path("v1/public/finances", public.summary),
]


def budget(rows=1, **changes):
    data = {
        "currency": "usd",
        "received_usd": "10.00",
        "operating_spent_usd": "1.00",
        "operating_reserved_usd": "2.00",
        "processing_spent_usd": "0.05",
        "allocated_usd": "5.60",
        "available_usd": "6.95",
        "newcomers_reserved_usd": "1.40",
        "updated_at": NOW.isoformat(),
        "movements": [
            {
                "occurred_at": NOW.isoformat(),
                "kind": "contribution",
                "amount_usd": "10.00",
                "source": "private@example.test",
                "label": '<script>alert("donor")</script>',
                "customer": "cus_PRIVATE",
            }
            for _ in range(rows)
        ],
        **changes,
    }
    data.setdefault("movements_total", len(data["movements"]))
    return data


@override_settings(
    ROOT_URLCONF=__name__,
    CLARIFY_STRIPE_READ_KEY="",
    CLARIFY_STRIPE_PAYMENT_LINK="",
    CLARIFY_STRIPE_PAYMENT_LINK_VERIFIED=False,
    CLARIFY_ADMIN_HOST="admin.example.test",
    ALLOWED_HOSTS=["testserver", "admin.example.test"],
)
class PublicFinanceTests(TestCase):
    def setUp(self):
        self.project = patch.object(public, "project_summary", return_value=budget())
        self.project.start()
        self.addCleanup(self.project.stop)
        self.clock = patch.object(public.timezone, "now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.network = patch.object(
            stripe.requests,
            "get",
            side_effect=AssertionError("Public views must not fetch Stripe"),
        )
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_unconfigured_page_is_honest_localized_and_public_without_session(self):
        for language, title in (
            ("pt", "Para onde vai o dinheiro"),
            ("en", "Where the money goes"),
            ("es", "Adónde va el dinero"),
        ):
            response = self.client.get("/transparency/", {"lang": language})
            self.assertContains(response, title)
            self.assertContains(response, '<html lang="' + language + '">')
            self.assertNotContains(response, "buy.stripe.com")
            self.assertFalse(response.cookies)
        data = self.client.get("/v1/public/finances").json()
        self.assertEqual(data["stripe"]["state"], "not_configured")
        self.assertEqual(data["stripe"]["balances"], [])
        self.assertIsNone(data["sponsorship"]["payment_link"])
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(
            set(data), {"schema_version", "stripe", "project_budget", "sponsorship"}
        )

    def test_public_projection_discards_private_prose_and_injection(self):
        for url in ("/transparency/?lang=en", "/v1/public/finances"):
            response = self.client.get(url)
            for private in (
                "private@example.test",
                "cus_PRIVATE",
                "<script>",
                "alert(",
                "customer",
                "donor",
            ):
                self.assertNotIn(private, response.content.decode())
        row = self.client.get("/v1/public/finances").json()["project_budget"][
            "movements"
        ][0]
        self.assertEqual(row["label"], "Contribution")
        self.assertEqual(row["source"], "project")
        self.assertEqual(
            set(row), {"occurred_at", "kind", "amount", "currency", "label", "source"}
        )
        with patch.object(
            public,
            "project_summary",
            return_value=budget(
                movements=[
                    {
                        "occurred_at": NOW.isoformat(),
                        "kind": {"name": "PRIVATE"},
                        "amount_usd": "10",
                        "label": "PRIVATE",
                    }
                ]
            ),
        ):
            response = self.client.get("/v1/public/finances")
        self.assertEqual(
            response.json()["project_budget"]["movements"][0]["kind"], "adjustment"
        )
        self.assertNotIn("PRIVATE", response.content.decode())

    def test_invalid_budget_is_unavailable_and_never_converted_between_currencies(self):
        for changes in (
            {"currency": "eur"},
            {"received_usd": "NaN"},
            {"received_usd": "<script>"},
            {"updated_at": "bad@private.example"},
        ):
            with patch.object(
                public, "project_summary", return_value=budget(**changes)
            ):
                result = self.client.get("/v1/public/finances").json()["project_budget"]
                self.assertEqual(result["state"], "unavailable")
                self.assertNotIn("received_usd", result)
        with patch.object(public, "project_summary", side_effect=ImportError):
            self.assertContains(
                self.client.get("/transparency/?lang=en"), "not available yet"
            )

    @override_settings(CLARIFY_STRIPE_READ_KEY=KEY)
    def test_live_balances_remain_separate_from_budget_and_no_ids_are_public(self):
        stripe.sync(
            get=http(
                balance(),
                listing(
                    [
                        movement(),
                        movement(
                            "txn_FAKE2", type="payout", amount=-940, fee=0, net=-940
                        ),
                    ]
                ),
            ),
            now=NOW,
        )
        data = self.client.get("/v1/public/finances").json()
        self.assertEqual(data["stripe"]["state"], "ready")
        self.assertEqual(
            data["stripe"]["balances"],
            [
                {"currency": "eur", "available": "0.00", "pending": "2.00"},
                {"currency": "usd", "available": "9.40", "pending": "0.00"},
            ],
        )
        self.assertEqual(data["project_budget"]["received_usd"], "10.000000000")
        for text in (
            KEY,
            "txn_FAKE",
            "ch_PRIVATE",
            "private@example.test",
            "description",
            "customer",
        ):
            self.assertNotIn(text, str(data))
        self.assertEqual(data["stripe"]["movements"][1]["kind"], "payout")
        self.assertEqual(data["stripe"]["movements"][1]["label"], "Payout transfer")
        self.assertContains(
            self.client.get("/transparency/?lang=en"),
            "transfers, not operating expenses",
        )
        self.assertEqual(
            set(data["stripe"]["movements"][0]),
            {
                "occurred_at",
                "available_on",
                "kind",
                "label",
                "currency",
                "amount",
                "fee",
                "net",
                "availability",
            },
        )

    @override_settings(CLARIFY_STRIPE_READ_KEY=KEY)
    def test_all_pages_are_discoverable_bounded_and_last_page_is_reachable(self):
        stripe.sync(
            get=http(
                balance(), listing([movement("txn_FAKE" + str(n)) for n in range(75)])
            ),
            now=NOW,
        )

        def page_budget(*, page=1):
            data = budget(rows=75)
            data["movements"] = data["movements"][(page - 1) * 50 : page * 50]
            return data

        with patch.object(public, "project_summary", side_effect=page_budget):
            first = self.client.get("/v1/public/finances").json()
            second = self.client.get("/v1/public/finances?stripe_page=2&budget_page=2")
            self.assertEqual(second.status_code, 200)
            second = second.json()
            for section in ("stripe", "project_budget"):
                self.assertEqual(len(first[section]["movements"]), 50)
                self.assertEqual(first[section]["pagination"]["next"], 2)
                self.assertEqual(len(second[section]["movements"]), 25)
                self.assertIsNone(second[section]["pagination"]["next"])
            self.assertContains(
                self.client.get("/transparency/?lang=en"), "stripe_page=2"
            )
            self.assertEqual(
                self.client.get("/v1/public/finances?stripe_page=3").status_code, 400
            )

    @override_settings(CLARIFY_STRIPE_READ_KEY=KEY)
    def test_not_synced_failed_stale_empty_partial_and_rotated_key_states(self):
        self.assertEqual(
            self.client.get("/v1/public/finances").json()["stripe"]["state"],
            "not_synced",
        )
        stripe.sync(get=http(balance(), listing()), now=NOW)
        PublicFinanceSnapshot.objects.filter(pk=1).update(
            synced_at=NOW - timedelta(days=2)
        )
        data = self.client.get("/v1/public/finances").json()["stripe"]
        self.assertTrue(data["stale"])
        self.assertEqual(data["state"], "stale")
        self.assertEqual(
            data["last_successful_sync"], (NOW - timedelta(days=2)).isoformat()
        )
        with override_settings(CLARIFY_STRIPE_READ_KEY="rk_live_OTHERFAKE"):
            self.assertEqual(
                self.client.get("/v1/public/finances").json()["stripe"]["balances"], []
            )
        with patch.object(stripe, "MAX_PAGES", 1):
            stripe.sync(get=http(balance(), listing(more=True)), now=NOW)
        self.assertContains(
            self.client.get("/transparency/?lang=en"), "History is incomplete"
        )
        stripe.sync(get=http(balance(available=[], pending=[]), listing([])), now=NOW)
        self.assertEqual(
            self.client.get("/v1/public/finances").json()["stripe"]["state"], "empty"
        )
        PublicFinanceSnapshot.objects.filter(pk=1).update(error_code="unavailable")
        self.assertTrue(
            self.client.get("/v1/public/finances").json()["stripe"]["sync_failed"]
        )

    def test_testmode_cannot_enable_sponsorship(self):
        with override_settings(
            CLARIFY_STRIPE_READ_KEY="rk_test_FAKE",
            CLARIFY_STRIPE_PAYMENT_LINK_VERIFIED=True,
            CLARIFY_STRIPE_PAYMENT_LINK="https://buy.stripe.com/FAKE",
        ):
            data = self.client.get("/v1/public/finances").json()
        self.assertEqual(data["stripe"]["state"], "test_mode")
        self.assertIsNone(data["sponsorship"]["payment_link"])

    @override_settings(
        CLARIFY_STRIPE_READ_KEY=KEY, CLARIFY_STRIPE_PAYMENT_LINK_VERIFIED=True
    )
    def test_sponsorship_accepts_only_verified_live_stripe_link_after_sync(self):
        stripe.sync(get=http(balance(), listing()), now=NOW)
        for url in (
            "https://buy.stripe.com.evil.example/FAKE",
            "https://buy.stripe.com@evil.example/FAKE",
            "javascript:alert(1)",
            "https://buy.stripe.com/test_FAKE",
            "https://buy.stripe.com/FAKE?email=private",
            "https://buy.stripe.com/FAKE#private",
            'https://buy.stripe.com/FAKE"onclick="alert(1)',
        ):
            with override_settings(CLARIFY_STRIPE_PAYMENT_LINK=url):
                self.assertIsNone(
                    self.client.get("/v1/public/finances").json()["sponsorship"][
                        "payment_link"
                    ]
                )
        with override_settings(
            CLARIFY_STRIPE_PAYMENT_LINK="https://buy.stripe.com/FAKEONLY"
        ):
            self.assertContains(
                self.client.get("/transparency/?lang=en"),
                'href="https://buy.stripe.com/FAKEONLY"',
            )
            with override_settings(CLARIFY_STRIPE_PAYMENT_LINK_VERIFIED=False):
                self.assertNotContains(
                    self.client.get("/transparency/"), "buy.stripe.com"
                )

    def test_headers_host_isolation_readonly_assets_and_no_session_changes(self):
        for url in (
            "/transparency/",
            "/v1/public/finances",
            "/transparency/assets/transparency.css",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertEqual(response["X-Frame-Options"], "DENY")
            self.assertEqual(response["Cross-Origin-Resource-Policy"], "same-origin")
            self.assertIn("default-src 'none'", response["Content-Security-Policy"])
            self.assertIn("form-action 'none'", response["Content-Security-Policy"])
            self.assertNotIn("Access-Control-Allow-Origin", response)
            self.assertEqual(self.client.post(url).status_code, 405)
            self.assertEqual(
                self.client.get(url, HTTP_HOST="admin.example.test").status_code, 404
            )
            if response.streaming:
                b"".join(response.streaming_content)
        for name in ("transparency.py", "admin.css", "..%2Fmodels.py"):
            self.assertEqual(
                self.client.get("/transparency/assets/" + name).status_code, 404
            )
        self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_query_schema_and_locales_are_complete(self):
        for query in (
            "stripe_page=0",
            "stripe_page=-1",
            "stripe_page=999999999",
            "stripe_page=1&stripe_page=1",
            "source=https://evil.example",
            "budget_page=100",
        ):
            self.assertEqual(
                self.client.get("/v1/public/finances?" + query).status_code, 400
            )
        self.assertEqual(set(public.COPY["pt"]), set(public.COPY["en"]))
        self.assertEqual(set(public.COPY["es"]), set(public.COPY["en"]))
        self.assertContains(
            self.client.get("/transparency/", HTTP_ACCEPT_LANGUAGE="es-ES,pt;q=0.8"),
            "Adónde va el dinero",
        )
        self.assertContains(
            self.client.get("/transparency/?lang=%3Cscript%3E"), "Where the money goes"
        )

    def test_storage_failure_is_safe_and_not_cached(self):
        for url in ("/transparency/", "/v1/public/finances"):
            with patch.object(
                public,
                "_data",
                side_effect=DatabaseError("rk_live_PRIVATE private@example.test"),
            ):
                response = self.client.get(url)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"code": "finance_unavailable"})
            self.assertEqual(response["Cache-Control"], "no-store")

    def test_operating_reserve_release_keeps_its_neutral_localized_meaning(self):
        entry = {
            "occurred_at": NOW.isoformat(),
            "kind": "operating_release",
            "amount_usd": "2.00",
            "label": "private@example.test",
        }
        with patch.object(
            public, "project_summary", return_value=budget(movements=[entry])
        ):
            row = self.client.get("/v1/public/finances").json()["project_budget"][
                "movements"
            ][0]
            self.assertEqual(row["kind"], "operating_release")
            self.assertEqual(row["label"], "Operating reserve released")
            for language, label in (
                ("pt", "Reserva de operação liberada"),
                ("en", "Operating reserve released"),
                ("es", "Reserva de operación liberada"),
            ):
                response = self.client.get("/transparency/", {"lang": language})
                self.assertContains(response, label)
                self.assertNotContains(response, "private@example.test")

    def test_currency_minor_units_do_not_assume_usd_for_other_currencies(self):
        self.assertEqual(public._minor(1234, "usd"), "12.34")
        self.assertEqual(public._minor(1234, "jpy"), "1234")
        self.assertEqual(public._minor(1234, "kwd"), "1.234")
        self.assertEqual(public._minor(123400, "isk"), "1234.00")

    def test_processing_costs_and_undated_history_remain_available_and_localized(self):
        rows = [
            {
                "occurred_at": NOW.isoformat(),
                "kind": "processing_cost",
                "amount_usd": "0.01",
            },
            {
                "occurred_at": NOW.isoformat(),
                "kind": "processing_estimate",
                "amount_usd": "0.02",
            },
            {
                "occurred_at": None,
                "kind": "historical_processing_cost",
                "amount_usd": "0.02",
            },
        ]
        with patch.object(
            public, "project_summary", return_value=budget(movements=rows)
        ):
            result = self.client.get("/v1/public/finances").json()["project_budget"]
            self.assertEqual(result["state"], "ready")
            self.assertEqual(
                [row["kind"] for row in result["movements"]],
                [
                    "processing_cost",
                    "processing_estimate",
                    "historical_processing_cost",
                ],
            )
            self.assertIsNone(result["movements"][-1]["occurred_at"])
            for language, expected in (
                (
                    "en",
                    (
                        "Processing cost",
                        "Estimated processing cost",
                        "Historical processing cost",
                        "Before weekly accounting",
                        "Processing costs (including estimates)",
                    ),
                ),
                (
                    "pt",
                    (
                        "Custo de processamento",
                        "Custo de processamento estimado",
                        "Custo histórico de processamento",
                        "Anterior ao controle semanal",
                        "Custos de processamento (incluindo estimativas)",
                    ),
                ),
                (
                    "es",
                    (
                        "Costo de procesamiento",
                        "Costo estimado de procesamiento",
                        "Costo histórico de procesamiento",
                        "Anterior al control semanal",
                        "Costos de procesamiento (incluidas las estimaciones)",
                    ),
                ),
            ):
                response = self.client.get("/transparency/", {"lang": language})
                for text in expected:
                    self.assertContains(response, text)
                self.assertNotContains(response, 'datetime="None"')

    def test_only_historical_processing_cost_can_omit_its_date(self):
        for kind in (
            "processing_cost",
            "processing_estimate",
            "operating_release",
            "contribution",
            "unknown",
        ):
            rows = [{"occurred_at": None, "kind": kind, "amount_usd": "0.02"}]
            with (
                self.subTest(kind=kind),
                patch.object(
                    public, "project_summary", return_value=budget(movements=rows)
                ),
            ):
                result = self.client.get("/v1/public/finances").json()["project_budget"]
                self.assertEqual(result["state"], "unavailable")
