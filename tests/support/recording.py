"""Reusable recording fixtures. This module defines no test cases."""

from __future__ import annotations


import threading


from provider_types import TranscriptionResult

from workflows import (
    SelectionDisposition,
)


class ImmediateScheduler:
    def call_soon(self, callback):
        callback()

    def run_in_background(self, callback):
        callback()


class ThreadScheduler(ImmediateScheduler):
    def __init__(self):
        self.threads = []

    def run_in_background(self, callback):
        worker = threading.Thread(target=callback)
        self.threads.append(worker)
        worker.start()

    def join(self):
        for worker in self.threads:
            worker.join(timeout=2)
            if worker.is_alive():
                raise AssertionError("workflow worker did not finish")


class Provider:
    def __init__(self):
        self.audio_source = None
        self.path_existed_during_call = False

    def transcribe(self, audio_source, mode, language):
        self.audio_source = audio_source
        self.path_existed_during_call = audio_source.audio_path.exists()
        return TranscriptionResult("Transcribed", "gemini", "gemini-test")


class Clipboard:
    def __init__(self):
        self.outputs = []

    def write_dictation_result(self, target, text):
        self.outputs.append((target, text))
        return SelectionDisposition.PASTED


class Config:
    def recording_usage_context(self, mode):
        return {"mode": mode}


class Statistics:
    def __init__(self):
        self.dictations = []

    def record_dictation(self, context, duration_seconds, result):
        self.dictations.append((context, duration_seconds, result))


class Clock:
    def __init__(self):
        self.now = 10.0

    def time(self):
        return self.now

    def monotonic(self):
        return self.now


class Recorder:
    def __init__(self, *, block_start=False):
        self.block_start = block_start
        self.start_entered = threading.Event()
        self.start_release = threading.Event()
        self.order = []
        self.path = None

    def start(self, audio_path, cancel_event=None):
        self.path = audio_path
        self.order.append("start_entered")
        self.start_entered.set()
        if self.block_start and not self.start_release.wait(timeout=1):
            raise AssertionError("test did not release recording startup")
        audio_path.write_bytes(b"a" * 1200)
        self.order.append("start_terminal")

    def stop(self):
        self.order.append("stop")

    def cancel(self):
        self.order.append("cancel")
        self.start_release.set()
