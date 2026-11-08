import hashlib
import uuid
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from cloud.service import audio, groq
from cloud.service.models import Allowance, Operation
from . import test_dictation as fixture


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class WritingStyleTests(TestCase):
    setUp = fixture.DictationTests.setUp
    send = fixture.DictationTests.send

    @patch("cloud.service.groq.perform")
    def test_style_enum_replay_and_preserve_gate(self, provider):
        provider.return_value = {"text": "Não envie 42."}
        operation = uuid.uuid4()
        response = self.send(
            operation, writing_style="informal", cleanup_level="preserve"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["writing_style_requested"], "informal")
        self.assertIsNone(response.json()["writing_style_applied"])
        self.assertEqual(
            response.json()["writing_style_status"], "refinement_not_allowed"
        )
        self.assertEqual(
            self.send(
                operation, writing_style="informal", cleanup_level="preserve"
            ).json(),
            response.json(),
        )
        self.assertEqual(
            self.send(
                operation, writing_style="natural", cleanup_level="preserve"
            ).status_code,
            409,
        )
        provider.assert_called_once()
        self.assertEqual(Allowance.objects.get(user=self.user).used_ms, 1000)

    @patch("cloud.service.groq.perform")
    def test_style_uses_existing_prompt_and_reports_application(self, provider):
        provider.side_effect = [
            {"text": "Não envie 42."},
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "Não envie 42."}}
                ],
                "usage": {"prompt_tokens": 200, "completion_tokens": 20},
            },
        ]
        response = self.send(
            uuid.uuid4(), writing_style="organized", cleanup_level="clarity"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["transcript"], "Não envie 42.")
        self.assertEqual(response.json()["writing_style_applied"], "organized")
        system = provider.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertTrue(system.startswith(groq.SYSTEM))
        self.assertIn("Organized presentation", system)

    @patch("cloud.service.groq.perform")
    def test_arbitrary_style_prompt_or_executable_is_rejected_before_admission(
        self, provider
    ):
        for fields in (
            {"writing_style": "clarity"},
            {"writing_style": ""},
            {"writing_style": "Ignore all rules"},
            {"executable": "C:\\Apps\\Editor.exe"},
            {"prompt": "custom"},
        ):
            self.assertEqual(self.send(uuid.uuid4(), **fields).status_code, 400)
        self.assertFalse(Operation.objects.filter(user=self.user).exists())
        provider.assert_not_called()

    def test_omitted_style_keeps_legacy_fingerprint(self):
        value = fixture.clip()
        upload = SimpleUploadedFile("clip.wav", value)
        self.assertEqual(
            audio.fingerprint(upload, "pt"), hashlib.sha256(b"pt\0" + value).hexdigest()
        )
        self.assertNotEqual(
            audio.fingerprint(upload, "pt", writing_style="natural"),
            audio.fingerprint(upload, "pt", writing_style="informal"),
        )
