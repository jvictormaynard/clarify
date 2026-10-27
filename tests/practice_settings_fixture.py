"""Fake capture and provider for the real Settings practice bridge."""

import sys

from provider_types import TranscriptionResult
from test_workflows import FakeAudio, FakeConfig, FakeStatistics, FakeClock
from workflows import WorkflowService
from clarify.desktop.dictation_practice import (
    PracticeController,
    PracticeDestination,
    practice_readiness,
)
from clarify.desktop.qml_runtime import QtWorkflowScheduler


def bind_practice(settings, app):
    class Audio(FakeAudio):
        def attach_worker(self, worker):
            pass

        def detach_worker(self, worker):
            pass

    class Provider:
        def transcribe(self, audio, mode, language):
            if "--practice-account-error" in sys.argv:
                from clarify_account import AccountError

                raise AccountError("fixture", code="allowance_exhausted")
            if (
                "--practice-auth-error" in sys.argv
                or "--practice-provider-quota" in sys.argv
            ):
                from provider_types import ProviderError

                error = ProviderError("groq", "fixture")
                error.code = (
                    "quota"
                    if "--practice-provider-quota" in sys.argv
                    else "authentication"
                )
                raise error
            return TranscriptionResult(
                "Hoje vou escrever com o Clarify.", "groq", "fixture"
            )

    scheduler = QtWorkflowScheduler(app)
    workflow = WorkflowService(
        Provider(),
        Audio(),
        PracticeDestination(),
        FakeConfig(),
        FakeStatistics(),
        scheduler,
        FakeClock(),
    )
    practice = PracticeController(
        workflow,
        language=lambda: settings.language,
        readiness=lambda: practice_readiness(
            settings, lambda: True, lambda _model, _device: True
        ),
        stop_microphone_test=settings.stopMicrophoneTest,
    )
    settings.bindPractice(practice)
    return practice
