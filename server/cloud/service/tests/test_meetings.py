import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from cloud.service import groq
from cloud.service.models import Allowance, Operation, FundingEntry
from shared.meeting_contract import SUMMARY_INSTRUCTION
from .test_api import client_for, fund_hosted


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="fixture-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class MeetingApiTests(TestCase):
    def setUp(self):
        self.user, self.client = client_for("meetings@example.test")
        fund_hosted(self.user)

    def summary(self, operation=None, **changes):
        return self.client.post(
            "/v1/meetings/summary",
            {
                "operation_id": str(operation or uuid.uuid4()),
                "source": "TRANSCRIPT\nWe agreed to test.\nPERSONAL NOTES\nCheck result.",
                "language": "auto",
                **changes,
            },
            format="json",
        )

    def audio(self, operation=None, **changes):
        return self.client.post(
            "/v1/meetings/transcriptions",
            {
                "operation_id": str(operation or uuid.uuid4()),
                "language": "pt",
                "audio": SimpleUploadedFile(
                    "fixture.wav", b"synthetic-audio", "audio/wav"
                ),
                **changes,
            },
            format="multipart",
        )

    @patch("cloud.service.groq.perform")
    def test_summary_is_separate_fixed_budgeted_and_idempotent(self, provider):
        provider.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "## Summary\nTest the result."},
                }
            ],
            "usage": {"prompt_tokens": 500, "completion_tokens": 40},
        }
        op = uuid.uuid4()
        first = self.summary(op)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(self.summary(op).json(), first.json())
        provider.assert_called_once()
        payload = provider.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "openai/gpt-oss-20b")
        self.assertTrue(
            payload["messages"][0]["content"].startswith(SUMMARY_INSTRUCTION)
        )
        self.assertEqual(Allowance.objects.get(user=self.user).used_ms, 0)
        operation = Operation.objects.get(user=self.user)
        self.assertGreater(operation.cost, Decimal(0))
        self.assertEqual(operation.quota_debit, operation.cost)
        self.assertEqual(self.summary(op, source="Changed source").status_code, 409)

    @patch("cloud.service.groq.perform")
    def test_audio_has_no_cleanup_or_snippet_step_and_charges_once(self, provider):
        provider.return_value = {"text": "Literal source"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.wav"
            path.write_bytes(b"synthetic PCM")
            with patch(
                "cloud.service.meetings.audio.decode", return_value=(path, 1000)
            ):
                op = uuid.uuid4()
                first = self.audio(op)
                self.assertEqual(first.status_code, 200, first.content)
                self.assertEqual(first.json()["transcript"], "Literal source")
                self.assertEqual(self.audio(op).json(), first.json())
        provider.assert_called_once()
        self.assertEqual(provider.call_args.args, ("audio/transcriptions",))
        self.assertNotIn("prompt", provider.call_args.kwargs["data"])
        self.assertEqual(Allowance.objects.get(user=self.user).used_ms, 1000)
        self.assertEqual(Operation.objects.count(), 1)

    @patch("cloud.service.groq.perform")
    def test_provider_failure_is_sanitized_replayed_and_never_charged_twice(
        self, provider
    ):
        provider.side_effect = groq.ProviderFailure("PRIVATE", cost=Decimal("0.000001"))
        op = uuid.uuid4()
        first = self.summary(op)
        self.assertEqual(first.status_code, 502)
        self.assertNotIn(b"PRIVATE", first.content)
        self.assertTrue(first.json()["retry_operation"])
        self.assertEqual(self.summary(op).json(), first.json())
        provider.assert_called_once()
        self.assertEqual(Operation.objects.get().cost, Decimal("0.000001"))
        self.assertEqual(
            FundingEntry.objects.filter(reference__startswith="cost:").count(), 1
        )

    @patch("cloud.service.groq.perform")
    def test_bounds_controls_auth_and_quota_fail_before_provider(self, provider):
        for change in (
            {"model": "other"},
            {"prompt": "override"},
            {"source": "X" * 64001},
            {"language": "xx"},
        ):
            self.assertEqual(self.summary(**change).status_code, 400)
        with patch(
            "cloud.service.meetings.audio.decode", return_value=(Path("unused"), 30001)
        ):
            self.assertEqual(self.audio().status_code, 400)
        FundingEntry.objects.all().delete()
        self.assertEqual(self.summary().status_code, 503)
        self.client.logout()
        self.client.credentials()
        self.assertIn(self.summary().status_code, {401, 403})
        provider.assert_not_called()
