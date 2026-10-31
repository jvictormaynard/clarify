"""Reusable workflows fixtures. This module defines no test cases."""

from __future__ import annotations


import threading


from collections.abc import Callable

from pathlib import Path


from provider_types import RewriteResult, TranscriptionResult, TranslationResult

from workflows import (
    NoUsableAudioError,
    RecordingSnapshot,
    SelectionCapture,
    SelectionDisposition,
    SelectionTarget,
    WorkflowService,
)


class ImmediateScheduler:
    def call_soon(self, callback: Callable[[], None]) -> None:
        callback()

    def run_in_background(self, callback: Callable[[], None]) -> None:
        callback()


class ManualScheduler:
    def __init__(self):
        self.soon: list[Callable[[], None]] = []
        self.background: list[Callable[[], None]] = []

    def call_soon(self, callback: Callable[[], None]) -> None:
        self.soon.append(callback)

    def run_in_background(self, callback: Callable[[], None]) -> None:
        self.background.append(callback)


class ThreadScheduler:
    def __init__(self):
        self.threads = []

    def call_soon(self, callback: Callable[[], None]) -> None:
        callback()

    def run_in_background(self, callback: Callable[[], None]) -> None:
        thread = threading.Thread(target=callback, daemon=True)
        self.threads.append(thread)
        thread.start()

    def join(self):
        index = 0
        while index < len(self.threads):
            self.threads[index].join(timeout=1.0)
            if self.threads[index].is_alive():
                raise AssertionError("background workflow did not finish")
            index += 1


class FakeClock:
    def __init__(self):
        self.now = 10.0

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeProvider:
    def __init__(self):
        self.transcription = "Transcribed"
        self.rewritten = "Rewritten"
        self.translated = "Translated"
        self.on_transcribe = None
        self.on_rewrite = None

    def transcribe(self, audio_source, mode, language, *, dictation_snapshot=None):
        self.transcription_request = (audio_source, mode, language)
        self.dictation_snapshot = dictation_snapshot
        if self.on_transcribe:
            self.on_transcribe()
        return TranscriptionResult(self.transcription, "gemini", "gemini-test")

    def rewrite(self, text):
        self.rewrite_request = text
        if self.on_rewrite:
            self.on_rewrite()
        return RewriteResult(self.rewritten, "openai", "gpt-test")

    def translate(self, text, target_language):
        self.translation_request = (text, target_language)
        return TranslationResult(self.translated, "openai", "gpt-test", target_language)


class FakeAudio:
    def __init__(self):
        self.available = True
        self.present = True
        self.started = 0
        self.stopped = 0
        self.cancelled = 0
        self.completed = 0
        self.failures = []
        self.startup_waits = 0

    def microphone_available(self):
        return self.available

    def create_session(self):
        return self

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1
        if not self.present:
            raise NoUsableAudioError("no audio")
        return RecordingSnapshot(Path("recording.wav"), b"audio")

    def wait_until_started(self):
        self.startup_waits += 1

    def cancel(self):
        self.cancelled += 1

    def complete(self):
        self.completed += 1

    def fail(self, error):
        self.failures.append(error)


class BlockingAudio(FakeAudio):
    def __init__(self, start_error=None):
        super().__init__()
        self.start_error = start_error
        self.start_entered = threading.Event()
        self.start_release = threading.Event()
        self.start_terminal = threading.Event()
        self.wait_entered = threading.Event()
        self.order = []

    def start(self):
        self.started += 1
        self.order.append("start_entered")
        self.start_entered.set()
        if not self.start_release.wait(timeout=1.0):
            raise AssertionError("test did not release recording startup")
        if self.cancelled and self.start_error is None:
            self.start_error = RuntimeError("recording startup cancelled")
        self.order.append("start_terminal")
        self.start_terminal.set()
        if self.start_error is not None:
            raise self.start_error

    def wait_until_started(self):
        self.startup_waits += 1
        self.order.append("wait_until_started")
        self.wait_entered.set()
        if not self.start_terminal.wait(timeout=1.0):
            raise AssertionError("recording startup did not become terminal")
        if self.start_error is not None:
            raise self.start_error

    def stop(self):
        self.order.append("stop")
        return super().stop()

    def cancel(self):
        self.order.append("cancel")
        super().cancel()
        self.start_release.set()


class FakeClipboard:
    def __init__(self):
        self.window = 77
        self.executable = "editor.exe"
        self.text = "previous"
        self.selected = "Original"
        self.alt_down = False
        self.writes = []
        self.applied = []
        self.auto_pastes = []
        self.activations = []
        self.restores = []
        self.captures = []
        self.current_text = self.text
        self.dictation_outputs = []

    def capture_target(self):
        if self.window is None:
            return None
        return SelectionTarget(self.window, self.executable)

    def is_target_current(self, target):
        return target.window == self.window

    def capture_selection(self, target):
        self.captures.append(target)
        if not self.selected:
            return None
        self.current_text = self.selected
        return SelectionCapture(target, self.selected, self.text)

    def restore(self, capture):
        self.restores.append(capture.context)
        self.current_text = capture.context

    def apply_result(self, capture, result):
        self.writes.append(result)
        self.applied.append((capture, result))
        if self.is_target_current(capture.target) and self.selected == capture.text:
            return SelectionDisposition.PASTED
        return SelectionDisposition.COPIED

    def write_dictation_result(self, target, text):
        self.writes.append(text)
        self.current_text = text
        disposition = SelectionDisposition.COPIED
        if target is not None and self.is_target_current(target):
            self.auto_pastes.append(text)
            disposition = SelectionDisposition.PASTED
        self.dictation_outputs.append((target, text, disposition))
        return disposition

    def activate(self, target):
        self.activations.append(target.window)

    def alt_pressed(self):
        return self.alt_down


class FakeConfig:
    def recording_usage_context(self, mode):
        return {"mode": mode, "provider": "gemini"}


class FakeStatistics:
    def __init__(self):
        self.dictations = []
        self.rewrites = []
        self.translations = []

    def record_dictation(self, context, duration_seconds, result):
        self.dictations.append((context, duration_seconds, result))

    def record_rewrite(self, provider, model, source, result):
        self.rewrites.append((provider, model, source, result))

    def record_translation(self, provider, model, source, result, target_language):
        self.translations.append((provider, model, source, result, target_language))


class WorkflowFixture:
    def setUp(self):
        self.provider = FakeProvider()
        self.audio = FakeAudio()
        self.clipboard = FakeClipboard()
        self.config = FakeConfig()
        self.statistics = FakeStatistics()
        self.clock = FakeClock()
        self.scheduler = ImmediateScheduler()
        self.service = self.make_service()
        self.states = []
        self.service.subscribe(self.states.append)

    def make_service(self, scheduler=None):
        return WorkflowService(
            self.provider,
            self.audio,
            self.clipboard,
            self.config,
            self.statistics,
            scheduler or self.scheduler,
            self.clock,
        )
