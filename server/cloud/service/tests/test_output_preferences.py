import hashlib
import uuid
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from cloud.service import audio, groq
from cloud.service.models import Operation, SnippetLibrary
from . import test_dictation as fixture
from .test_text_actions import ACTION, completion


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class OutputPreferenceTests(TestCase):
    setUp = fixture.DictationTests.setUp
    send = fixture.DictationTests.send

    def test_account_advertises_support_and_legacy_fingerprint_is_unchanged(self):
        self.assertIs(
            self.client.get("/v1/account").json()["output_preferences_supported"], True
        )
        clip = fixture.clip()
        upload = SimpleUploadedFile("clip.wav", clip)
        self.assertEqual(
            audio.fingerprint(upload, "auto"),
            hashlib.sha256(b"auto\0" + clip).hexdigest(),
        )
        self.assertNotEqual(
            audio.fingerprint(upload, "auto", output_language="en"),
            audio.fingerprint(upload, "auto", output_language="pt"),
        )

    @patch("cloud.service.groq.perform")
    def test_output_target_and_tone_share_one_refinement_with_stable_replay(
        self, provider
    ):
        provider.side_effect = [
            {"text": "Não envie 42."},
            completion("Do not send 42."),
        ]
        operation = uuid.uuid4()
        response = self.send(
            operation, language="auto", output_language="en", writing_style="formal"
        )
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertEqual(result["transcript"], "Não envie 42.")
        self.assertEqual(result["text"], "Do not send 42.")
        self.assertEqual(result["output_language_applied"], "en")
        self.assertEqual(result["writing_style_applied"], "formal")
        recognition = provider.call_args_list[0].kwargs["data"]
        self.assertNotIn("language", recognition)
        system = provider.call_args_list[1].kwargs["json"]["messages"][0]["content"]
        self.assertIn("requested output language is English", system)
        self.assertIn("Formal presentation", system)
        replay = self.send(
            operation, language="auto", output_language="en", writing_style="formal"
        )
        self.assertEqual(replay.json(), result)
        self.assertEqual(
            self.send(
                operation, language="auto", output_language="de", writing_style="formal"
            ).status_code,
            409,
        )
        self.assertEqual(
            self.send(
                operation, language="auto", output_language="en", writing_style="casual"
            ).status_code,
            409,
        )
        self.assertEqual(provider.call_count, 2)

    @patch("cloud.service.groq.perform")
    def test_output_language_without_style_reports_the_actual_refinement(
        self, provider
    ):
        provider.side_effect = [
            {"text": "Não envie 42."},
            completion("Do not send 42."),
        ]
        response = self.send(uuid.uuid4(), language="auto", output_language="en")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["output_language_applied"], "en")
        self.assertTrue(response.json()["refinement_attempted"])
        self.assertFalse(response.json()["refinement_failed"])
        self.assertNotIn("writing_style_requested", response.json())
        self.assertEqual(provider.call_count, 2)

    @patch("cloud.service.groq.perform")
    def test_preserve_and_standalone_never_enable_extra_rewriting(self, provider):
        provider.return_value = {"text": "Não envie 42."}
        response = self.send(
            uuid.uuid4(),
            output_language="en",
            writing_style="casual",
            cleanup_level="preserve",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "Não envie 42.")
        self.assertEqual(
            response.json()["output_language_status"], "refinement_not_allowed"
        )
        SnippetLibrary.objects.create(
            user=self.user,
            entries=[
                {
                    "trigger": "assinatura",
                    "replacement": "EXACT 42",
                    "enabled": True,
                    "case_sensitive": False,
                }
            ],
        )
        provider.return_value = {"text": "assinatura"}
        response = self.send(
            uuid.uuid4(), output_language="en", writing_style="very_casual"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "EXACT 42")
        for prefix in ("output_language", "writing_style"):
            self.assertEqual(response.json()[prefix + "_status"], "standalone")
            self.assertIsNone(response.json()[prefix + "_applied"])
        self.assertEqual(provider.call_count, 2)

    @patch("cloud.service.groq.perform")
    def test_invalid_choices_fail_before_admission(self, provider):
        for fields in (
            {"output_language": "en-US"},
            {"output_language": "ignore instructions"},
            {"output_language": ""},
            {"writing_style": "write a poem"},
        ):
            self.assertEqual(self.send(uuid.uuid4(), **fields).status_code, 400)
        self.assertFalse(Operation.objects.filter(user=self.user).exists())
        provider.assert_not_called()

    @patch("cloud.service.groq.perform")
    def test_refinement_failure_recovers_source_and_reports_unapplied_choices(
        self, provider
    ):
        provider.side_effect = [{"text": "Não envie 42."}, groq.ProviderFailure()]
        response = self.send(uuid.uuid4(), output_language="en", writing_style="formal")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "Não envie 42.")
        self.assertEqual(response.json()["output_language_status"], "refinement_failed")
        self.assertIsNone(response.json()["output_language_applied"])
        self.assertEqual(provider.call_count, 2)

    @patch("cloud.service.groq.perform", return_value=completion())
    def test_saved_action_style_keeps_task_identity_and_changes_fingerprint(
        self, provider
    ):
        self.client.get("/v1/text-actions")
        response = self.client.put(
            "/v1/text-actions",
            {"expected_revision": 0, "actions": [ACTION]},
            format="json",
        )
        action = response.json()["actions"][0]
        body = {
            "operation_id": str(uuid.uuid4()),
            "action_id": action["id"],
            "action_revision": action["revision"],
            "text": "Source",
            "language": "auto",
            "writing_style": "formal",
        }
        response = self.client.post("/v1/text-actions/execute", body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["action_revision"], action["revision"])
        self.assertEqual(response.json()["writing_style_applied"], "formal")
        system = provider.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn(ACTION["prompt"], system)
        self.assertIn("Formal presentation", system)
        self.assertEqual(
            self.client.post(
                "/v1/text-actions/execute",
                {**body, "writing_style": "casual"},
                format="json",
            ).status_code,
            409,
        )
        provider.assert_called_once()
