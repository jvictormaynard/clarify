import io
import tempfile
import uuid
import wave
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from cloud.service import audio, groq, ledger, maintenance
from cloud.service.models import Allowance, Operation
from .test_api import client_for


def clip(milliseconds=1000):
    data = io.BytesIO()
    with wave.open(data, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * (milliseconds * 16))
    return data.getvalue()


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class DictationTests(TestCase):
    def setUp(self):
        self.user, self.client = client_for("dictation@example.test")

    def send(self, op, **fields):
        return self.client.post(
            "/v1/dictations",
            {
                "operation_id": str(op),
                "audio": SimpleUploadedFile(
                    "untrusted.extension", clip(), "application/octet-stream"
                ),
                **fields,
            },
            format="multipart",
        )

    @patch("cloud.service.groq.perform")
    def test_pipeline_and_duplicate_deliver_once_and_charge_real_usage(self, provider):
        provider.side_effect = [
            {"text": "Vamos marcar na quarta. Na verdade na quinta."},
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Vamos marcar na quinta."},
                    }
                ],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 300},
            },
        ]
        op = uuid.uuid4()
        first = self.send(op, language="pt")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertTrue(first.json()["rewritten"])
        self.assertEqual(self.send(op, language="pt").json(), first.json())
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(
            provider.call_args_list[0].kwargs["data"]["model"], "whisper-large-v3-turbo"
        )
        rewrite = provider.call_args_list[1].kwargs["json"]
        self.assertEqual(rewrite["model"], "openai/gpt-oss-20b")
        self.assertEqual(rewrite["messages"][0]["content"], groq.SYSTEM)
        self.assertIn("BEGIN_SOURCE_TRANSCRIPT", rewrite["messages"][1]["content"])
        operation = Operation.objects.get(user=self.user, operation_id=op)
        self.assertEqual(operation.output_tokens, 300)  # Includes reasoning tokens.
        self.assertEqual(Allowance.objects.get(user=self.user).used_ms, 1000)
        self.assertLess(operation.cost, ledger.MAX_COST)

    @patch("cloud.service.groq.perform")
    def test_rewrite_timeout_keeps_transcript_and_reserves_uncertain_cost(
        self, provider
    ):
        provider.side_effect = [{"text": "Original."}, groq.ProviderFailure()]
        result = self.send(uuid.uuid4())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.json(),
            {"text": "Original.", "transcript": "Original.", "rewritten": False},
        )
        self.assertEqual(Operation.objects.get(user=self.user).cost, ledger.MAX_COST)

    @patch("cloud.service.groq.perform")
    def test_arbitrary_provider_controls_are_rejected(self, provider):
        self.assertEqual(
            self.send(uuid.uuid4(), model="expensive", prompt="override").status_code,
            400,
        )
        provider.assert_not_called()

    @override_settings(CLARIFY_FUNDED_ENABLED=False)
    @patch("cloud.service.audio.decode")
    @patch("cloud.service.groq.perform")
    def test_disabled_service_does_no_decode_or_provider_work(self, provider, decode):
        self.assertEqual(self.send(uuid.uuid4()).status_code, 503)
        provider.assert_not_called()
        decode.assert_not_called()

    @patch("cloud.service.groq.perform")
    def test_maintenance_removes_text_and_never_replays_expired_operation(
        self, provider
    ):
        provider.side_effect = [{"text": "Original."}, groq.ProviderFailure()]
        op = uuid.uuid4()
        self.send(op)
        Operation.objects.filter(user=self.user).update(
            result_expires_at=timezone.now()
        )
        maintenance.maintain()
        self.assertEqual(Operation.objects.get(user=self.user).result, {})
        self.assertEqual(self.send(op).status_code, 410)
        self.assertEqual(provider.call_count, 2)

    def test_decoder_uses_actual_duration_and_rejects_playlists(self):
        with tempfile.TemporaryDirectory() as directory:
            _, duration = audio.decode(
                SimpleUploadedFile("lie.mp3", clip(1250)), directory
            )
            self.assertEqual(duration, 1250)
            for invalid in (
                b"invalid",
                b"#EXTM3U\nhttps://example.test/audio.mp3\n",
                clip(100),
            ):
                with self.assertRaises(ledger.Rejected):
                    audio.decode(SimpleUploadedFile("audio.wav", invalid), directory)
