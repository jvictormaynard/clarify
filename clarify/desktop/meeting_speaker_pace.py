"""Portable admission and feedback for Windows meeting speaker windows."""

from dataclasses import dataclass
from threading import Condition
from time import monotonic


@dataclass(frozen=True)
class SpeakerJob:
    window: object
    admitted: float
    generation: int


class SpeakerPace:
    """One native owner and at most one unclaimed window."""

    strides = (6.0, 4.0, 2.5, 1.5, 0.8)
    promotion_windows = 3
    max_queue_wait = 0.4

    def __init__(self, *, stopped=lambda: False, clock=monotonic):
        self._stopped, self._clock = stopped, clock
        self._condition = Condition()
        self._level = self._healthy = self._generation = 0
        self._audio_end = 0.0
        self._due = self.strides[0]
        self._pending = self._running = None
        self._closed = False

    @property
    def stride(self):
        with self._condition:
            return self.strides[self._level]

    def is_set(self):
        return self._closed or self._stopped()

    def _back_off(self, level):
        self._level, self._healthy = level, 0
        self._generation += 1
        self._pending = None
        self._due = round(self._audio_end + self.strides[level], 6)

    def offer(self, audio_end, snapshot, *, pressured=False):
        """Sample the newest PCM only if the optional worker can accept it."""
        with self._condition:
            if self.is_set():
                return False
            self._audio_end = audio_end
            if pressured:
                self._back_off(0)
                return False
            now = self._clock()
            if self._pending is not None:
                admitted = self._pending.admitted
                if audio_end >= self._due or now - admitted >= self.max_queue_wait:
                    self._back_off(0)
                    return False
                self._pending = SpeakerJob(snapshot(), admitted, self._generation)
                self._due = round(audio_end + self.strides[self._level], 6)
                return True
            if audio_end < self._due:
                return False
            if self._running is not None:
                self._back_off(0)
                return False
            self._pending = SpeakerJob(snapshot(), now, self._generation)
            self._due = round(audio_end + self.strides[self._level], 6)
            self._condition.notify()
            return True

    def take(self, *, timeout=0.05):
        with self._condition:
            self._condition.wait_for(
                lambda: self._pending is not None or self.is_set(), timeout
            )
            if self.is_set() or self._running is not None:
                return None
            if (
                self._pending is not None
                and self._clock() - self._pending.admitted >= self.max_queue_wait
            ):
                self._back_off(0)
                return None
            self._running, self._pending = self._pending, None
            return self._running

    def accepts(self, job):
        with self._condition:
            return (
                not self.is_set()
                and job is self._running
                and job.generation == self._generation
            )

    def complete(self, job, *, measured=True, timed_out=False):
        """Use elapsed wall time from admission through completed inference."""
        with self._condition:
            if job is not self._running:
                return
            self._running = None
            if self.is_set() or job.generation != self._generation:
                return
            elapsed = self._clock() - job.admitted
            stride = self.strides[self._level]
            if timed_out or (measured and elapsed >= stride):
                self._back_off(0)
            elif measured and elapsed >= stride * 0.75:
                self._back_off(max(0, self._level - 1))
            elif (
                measured
                and self._level + 1 < len(self.strides)
                and elapsed <= self.strides[self._level + 1] * 0.5
            ):
                self._healthy += 1
                if self._healthy >= self.promotion_windows:
                    self._level += 1
                    self._healthy = 0
                    self._due = round(self._due - stride + self.strides[self._level], 6)
            else:
                self._healthy = 0

    def close(self):
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify_all()
