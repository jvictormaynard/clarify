import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings

from cloud.service import ledger
from cloud.service.models import Allowance, Operation
from .test_api import client_for


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class TextTests(TestCase):
    def setUp(self):
        self.user, self.client = client_for("text@example.test")

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

    @override_settings(CLARIFY_MONTHLY_BUDGET_USD="0")
    @patch("cloud.service.groq.perform")
    def test_global_budget_blocks_text_before_provider_work(self, provider):
        self.assertEqual(self.send(uuid.uuid4()).status_code, 503)
        provider.assert_not_called()
