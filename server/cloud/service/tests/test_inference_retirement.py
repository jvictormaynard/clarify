"""Retired routes reject input without entering funded processing."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .test_api import client_for
from cloud.service.models import Operation


class InferenceRetirementTests(TestCase):
    def test_retirement_precedes_parsing_authentication_and_funded_admission(self):
        _, signed_in = client_for("retired@example.test")
        for funded in (False, True):
            with (
                override_settings(
                    CLARIFY_FUNDED_ENABLED=funded, CLARIFY_GROQ_KEY="fixture-only"
                ),
                patch("cloud.service.groq.perform") as provider,
                patch("cloud.service.ledger.reserve") as reserve,
                patch("cloud.service.audio.decode") as decode,
            ):
                for client in (APIClient(), signed_in):
                    for route in (
                        "/v1/dictations",
                        "/v1/text",
                        "/v1/text-actions/execute",
                        "/v1/usage",
                    ):
                        with self.subTest(funded=funded, route=route):
                            response = client.generic(
                                "GET" if route.endswith("usage") else "POST",
                                route,
                                b"malformed-body",
                                CONTENT_LENGTH="invalid",
                                content_type="multipart/form-data; boundary=missing",
                            )
                            self.assertEqual(response.status_code, 410)
                            self.assertEqual(
                                response.json(),
                                {"code": "inference_retired", "update_required": True},
                            )
                provider.assert_not_called()
                reserve.assert_not_called()
                decode.assert_not_called()
        self.assertFalse(Operation.objects.exists())
