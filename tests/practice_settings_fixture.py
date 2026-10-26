"""Fake capture and provider for the real Settings practice bridge."""

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
        readiness=lambda: practice_readiness(settings, lambda: True),
    )
    settings.bindPractice(practice)
    return practice
