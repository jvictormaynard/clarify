import io
import tempfile
import uuid
import wave
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from cloud.service import audio, groq, ledger, maintenance
from cloud.service.models import Allowance, Dictionary, Operation
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

    def send(self, op, *, milliseconds=1000, content=None, **fields):
        return self.client.post(
            "/v1/dictations",
            {
                "operation_id": str(op),
                "audio": SimpleUploadedFile(
                    "untrusted.extension",
                    clip(milliseconds) if content is None else content,
                    "application/octet-stream",
                ),
                **fields,
            },
            format="multipart",
        )

    @patch("cloud.service.groq.perform")
    def test_short_audio_uses_only_enabled_canonical_spellings(self, provider):
        Dictionary.objects.create(
            user=self.user,
            entries=[
                {
                    "term": "Clarify",
                    "aliases": ["clarifai"],
                    "pronunciation": "kla ri fai",
                },
                {"term": "Subaúma"},
                {"term": "Disabled", "enabled": False},
            ],
        )
        for milliseconds in (300, 1000):
            with self.subTest(milliseconds=milliseconds):
                provider.reset_mock()
                provider.side_effect = [{"text": "Oi."}, groq.ProviderFailure()]
                response = self.send(uuid.uuid4(), milliseconds=milliseconds)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["transcript"], "Oi.")
                self.assertFalse(response.json()["rewritten"])
                fields = provider.call_args_list[0].kwargs["data"]
                self.assertEqual(fields["prompt"], "Clarify, Subaúma")
                self.assertEqual(provider.call_count, 2)
        self.assertEqual(Allowance.objects.get(user=self.user).used_ms, 1300)

    @patch("cloud.service.groq.perform")
    def test_speech_context_is_bounded_without_partial_terms(self, provider):
        terms = [f"term{index:03d}" + "a" * 40 for index in range(30)]
        Dictionary.objects.create(
            user=self.user, entries=[{"term": term} for term in terms]
        )
        provider.side_effect = [{"text": "Oi."}, groq.ProviderFailure()]
        self.assertEqual(self.send(uuid.uuid4()).status_code, 200)
        prompt = provider.call_args_list[0].kwargs["data"]["prompt"]
        self.assertLessEqual(len(prompt), 896)
        self.assertEqual(prompt.split(", "), terms[: len(prompt.split(", "))])
        self.assertGreater(len(prompt + ", " + terms[len(prompt.split(", "))]), 896)

    @patch("cloud.service.groq.perform")
    def test_no_dictionary_does_not_send_a_speech_prompt(self, provider):
        provider.side_effect = [{"text": "Oi."}, groq.ProviderFailure()]
        self.assertEqual(self.send(uuid.uuid4()).status_code, 200)
        self.assertNotIn("prompt", provider.call_args_list[0].kwargs["data"])

    @patch("cloud.service.groq.perform")
    def test_empty_speech_is_identified_without_retrying_or_double_charging(
        self, provider
    ):
        provider.return_value = {"text": "  \n"}
        operation_id = uuid.uuid4()
        response = self.send(operation_id)
        self.assertEqual(response.status_code, 422, response.content)
        result = response.json()
        self.assertEqual(result["code"], "no_speech")
        self.assertEqual(result["phase"], "transcription")
        self.assertEqual(result["operation_id"], str(operation_id))
        self.assertEqual(result["usage"]["used_ms"], 1000)
        self.assertEqual(result["usage"]["reserved_ms"], 0)
        self.assertEqual(self.send(operation_id).status_code, 410)
        provider.assert_called_once()
        operation = Operation.objects.get(user=self.user)
        self.assertEqual(operation.state, "uncertain")
        self.assertEqual(operation.cost, ledger.MAX_COST)
        self.assertEqual(Allowance.objects.get(user=self.user).used_ms, 1000)

    @patch("cloud.service.groq.perform")
    def test_transcription_failure_keeps_safe_diagnostics_only(self, provider):
        for answer in ({}, {"text": None}, {"text": 42}, {"text": "x" * 64001}, []):
            with self.subTest(answer_type=type(answer).__name__):
                provider.return_value = answer
                operation_id = uuid.uuid4()
                response = self.send(operation_id)
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["code"], "transcription_failed")
                self.assertEqual(response.json()["phase"], "transcription")
                self.assertEqual(response.json()["operation_id"], str(operation_id))
                self.assertNotIn("text", response.json())
        provider.side_effect = groq.ProviderFailure("private provider details")
        operation_id = uuid.uuid4()
        with self.assertLogs("cloud.service.api", level="WARNING") as logs:
            response = self.send(operation_id)
        self.assertEqual(response.json()["code"], "transcription_failed")
        self.assertNotIn("private provider details", " ".join(logs.output))
        self.assertNotIn("private provider details", response.content.decode())
        self.assertIn(str(operation_id), " ".join(logs.output))

    @patch("cloud.service.groq.dictation", side_effect=RuntimeError("private text"))
    def test_unexpected_processing_failure_is_distinct(self, provider):
        response = self.send(uuid.uuid4())
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "processing_failed")
        self.assertEqual(response.json()["phase"], "processing")
        self.assertNotIn("private text", response.content.decode())

    @patch("cloud.service.groq.perform")
    def test_invalid_audio_is_validation_failure_before_paid_work(self, provider):
        operation_id = uuid.uuid4()
        response = self.send(operation_id, content=b"invalid audio")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_audio")
        self.assertEqual(response.json()["phase"], "validation")
        self.assertEqual(response.json()["operation_id"], str(operation_id))
        provider.assert_not_called()
        self.assertFalse(Operation.objects.filter(user=self.user).exists())

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
            {key: value for key, value in result.json().items() if key != "usage"},
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
