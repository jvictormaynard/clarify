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
    def test_completed_summary_cannot_replace_long_rewrite_or_translation(
        self, provider
    ):
        source = "\n".join(
            f"Requirement {i}: Send {i + 2} signed copies to recipient {i}; keep audit record {i}."
            for i in range(1, 65)
        )
        provider.return_value = {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "Send the documents."}}
            ],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 10},
        }
        for action in ("rewrite", "translate"):
            with self.subTest(action=action):
                response = self.send(
                    uuid.uuid4(), action=action, text=source, language="en"
                )
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["code"], "text_processing_failed")
                operation = Operation.objects.get(
                    operation_id=response.json()["operation_id"]
                )
                self.assertEqual(
                    operation.cost,
                    groq.money(1000 * groq.INPUT_RATE + 10 * groq.OUTPUT_RATE, up=True),
                )

        catalog = self.client.get("/v1/text-actions").json()
        for action_id in ("rewrite", "translation"):
            with self.subTest(saved_action=action_id):
                response = self.client.post(
                    "/v1/text-actions/execute",
                    {
                        "operation_id": str(uuid.uuid4()),
                        "action_id": action_id,
                        "action_revision": 1,
                        "text": source,
                        "language": "en",
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 502)
        summary = {
            "id": "summary",
            "name": "Summary",
            "kind": "custom",
            "enabled": True,
            "prompt": "Summarize in one sentence.",
        }
        actions = [
            {key: value for key, value in action.items() if key != "revision"}
            for action in catalog["actions"]
        ]
        response = self.client.put(
            "/v1/text-actions",
            {"expected_revision": catalog["revision"], "actions": [*actions, summary]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            "/v1/text-actions/execute",
            {
                "operation_id": str(uuid.uuid4()),
                "action_id": "summary",
                "action_revision": 1,
                "text": source,
                "language": "en",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Send the documents.")

    @patch("cloud.service.groq.perform")
    def test_saved_translation_validates_selection_without_request_metadata(
        self, provider
    ):
        self.client.get("/v1/text-actions")
        sentence = "Keep the delivery address and the confirmation number."
        provider.return_value = {
            "choices": [
                {"finish_reason": "stop", "message": {"content": sentence.lower()}}
            ],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 10},
        }
        response = self.client.post(
            "/v1/text-actions/execute",
            {
                "operation_id": str(uuid.uuid4()),
                "action_id": "translation",
                "action_revision": 1,
                "text": " ".join([sentence] * 12),
                "language": "en",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], sentence.lower())

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

        translated = self.send(
            uuid.uuid4(), action="translate", language="auto", text="Hello. Hola."
        )
        self.assertEqual(translated.status_code, 200)
        self.assertEqual(translated.json()["output_language_status"], "unchanged")
        self.assertIn(
            "multiple languages",
            provider.call_args.kwargs["json"]["messages"][0]["content"],
        )

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
