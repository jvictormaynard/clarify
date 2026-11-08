"""Qt voice translation keeps its processing profile and account identity."""

import unittest
from repositories import AppConfig
from provider_registry import build_provider_registry
from tests.support.chatgpt_provider import Http, Response, completed, Session


class ChatGPTWorkflowIntegrationTests(unittest.TestCase):
    def test_voice_translation_preserves_the_profile_account_binding(self):
        from clarify.desktop.qml_voice_translation import QmlVoiceTranslationProvider
        from voice_translation import VoiceTranslationRequest

        config = AppConfig.from_mapping(
            {
                "voice_translation": {
                    "route": {
                        "provider_id": "chatgpt",
                        "model_id": "available-model",
                        "account_id": "synthetic-account",
                    }
                },
            }
        )
        config = AppConfig.from_mapping(config.to_mapping())
        http = Http(Response([completed("Translated text.")]))
        provider = QmlVoiceTranslationProvider(
            lambda: config,
            registry=build_provider_registry(http, chatgpt_session=Session()),
        )
        request = VoiceTranslationRequest(
            "Original.", "pt", "en", config.voice_translation.route
        )
        self.assertEqual(provider.translate(request).text, "Translated text.")
        self.assertEqual(len(http.calls), 1)
