import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings

from cloud.service import groq, ledger
from cloud.service.models import Allowance, Operation
from .test_api import client_for, fund_hosted
from cloud.service.models import FundingEntry


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class TextTests(TestCase):
    def setUp(self):
        self.user, self.client = client_for("text@example.test")
        fund_hosted(self.user)

    def send(self, operation_id, **changes):
        return self.client.post(
            "/v1/text",
            {
                "operation_id": str(operation_id),
                "action": "rewrite",
                "text": "Source text.",
                "language": "auto",
                **changes,
            },
            format="json",
        )

    @patch("cloud.service.groq.perform")
    def test_provider_failure_has_safe_text_diagnostics(self, provider):
        provider.side_effect = groq.ProviderFailure("private provider response")
        operation_id = uuid.uuid4()
        response = self.send(operation_id)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "text_processing_failed")
        self.assertEqual(response.json()["phase"], "text")
        self.assertEqual(response.json()["operation_id"], str(operation_id))
        self.assertNotIn("private provider response", response.content.decode())
        operation = Operation.objects.get(user=self.user)
        self.assertEqual(operation.cost, operation.authorized_cost)
        self.assertLess(operation.cost, operation.reserved_cost)
        self.assertEqual(self.send(operation_id).status_code, 410)
        provider.assert_called_once()

    @patch("cloud.service.groq.perform")
    def test_malformed_provider_text_is_not_an_unexpected_server_failure(
        self, provider
    ):
        provider.return_value = {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        response = self.send(uuid.uuid4())
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "text_processing_failed")
        self.assertEqual(response.json()["phase"], "text")

    @patch("cloud.service.groq.perform")
    def test_managed_text_is_fixed_idempotent_and_budgeted_without_audio_minutes(
        self, provider
    ):
        provider.return_value = {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "Revised text."}}
            ],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
        }
        operation_id = uuid.uuid4()
        first = self.send(operation_id)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["text"], "Revised text.")
        self.assertEqual(self.send(operation_id).json(), first.json())
        provider.assert_called_once()
        self.assertEqual(
            provider.call_args.kwargs["json"]["model"], "openai/gpt-oss-20b"
        )
        self.assertEqual(Allowance.objects.get(user=self.user).used_ms, 0)
        operation = Operation.objects.get(user=self.user)
        self.assertGreater(operation.cost, 0)
        self.assertLess(operation.cost, ledger.MAX_COST)

    @patch("cloud.service.groq.perform")
    def test_rejects_provider_controls_invalid_language_and_large_source(
        self, provider
    ):
        for fields in (
            {"model": "other"},
            {"prompt": "override"},
            {"language": "xx"},
            {"text": "x" * 16001},
            {"action": "chat"},
        ):
            self.assertEqual(self.send(uuid.uuid4(), **fields).status_code, 400)
        provider.assert_not_called()

    @patch("cloud.service.groq.perform")
    def test_missing_cash_blocks_text_before_provider_work(self, provider):
        FundingEntry.objects.all().delete()
        self.assertEqual(self.send(uuid.uuid4()).status_code, 503)
        provider.assert_not_called()
