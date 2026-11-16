"""Injected live-ASR adapter. Construction requires an already admitted claim.

The host owner must reserve the UUIDv7 in its durable operation registry before
calling this adapter. A failed or disconnected claim is never opened again.
This module does not select a model, acquire a microphone, or publish text.
"""

import hashlib
import threading


class LiveRecognition:
    def __init__(self, engine, language, *, admitted, cancel_event, on_partial):
        if admitted is not True or not isinstance(cancel_event, threading.Event):
            raise ValueError("A durable admission and cancellation event are required")
        self.cancel_event = cancel_event
        self.digest = hashlib.sha256()
        self.total_bytes = 0
        self.sequence = 0
        self.lock = threading.RLock()
        self.finishing = False
        self.final = None

        def partial(result):
            # Native callbacks are cumulative display snapshots only. The event
            # owner must marshal them to its UI; no paste or final publication.
            if not self.cancel_event.is_set() and not result.final:
                if len(result.text.encode("utf-8")) > 32768:
                    raise ValueError("partial_too_large")
                on_partial(result)

        self.session = engine.open_live_session(language=language, on_result=partial)

    def feed(self, sequence, pcm16):
        with self.lock:
            if (
                self.cancel_event.is_set()
                or self.finishing
                or sequence != self.sequence
            ):
                raise ValueError("invalid_live_state")
            if (
                not isinstance(pcm16, bytes)
                or not 0 < len(pcm16) <= 2560
                or len(pcm16) % 2
                or self.total_bytes + len(pcm16) > 9600000
            ):
                raise ValueError("invalid_pcm_frame")
            try:
                self.session.feed(pcm16)
            except Exception:
                self.cancel()
                raise
            self.digest.update(pcm16)
            self.total_bytes += len(pcm16)
            self.sequence += 1

    def finish(self):
        with self.lock:
            if self.cancel_event.is_set():
                raise ValueError("cancelled")
            if self.final is not None:
                return self.final
            if self.finishing or not self.total_bytes:
                raise ValueError("finish_unavailable")
            self.finishing = True
        try:
            result = self.session.finish(timeout=30, cancel_event=self.cancel_event)
            with self.lock:
                if self.cancel_event.is_set():
                    raise ValueError("cancelled")
                if len(result.text.encode("utf-8")) > 32768:
                    raise ValueError("result_too_large")
                self.final = result
                return result
        except Exception:
            self.cancel()
            raise

    def cancel(self):
        self.cancel_event.set()
        self.session.cancel()
