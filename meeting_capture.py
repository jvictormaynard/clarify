"""Two independently owned capture workers and durable, bounded WAV chunks."""

import math
import os
import threading
import time
import wave
from array import array

from shared.meeting_contract import CHUNK_SECONDS, MAX_MEETING_SECONDS, MeetingError


class MeetingCapture:
    def __init__(
        self,
        store,
        owner,
        meeting_id,
        *,
        source_factory,
        notify=lambda: None,
        clock=time.monotonic,
    ):
        self.store, self.owner, self.meeting_id = store, owner, meeting_id
        self.source_factory, self.notify, self.clock = source_factory, notify, clock
        self.stop_event = threading.Event()
        self.started = clock()
        self._lock = threading.RLock()
        self._threads = []
        self.sources = {
            name: {"state": "starting", "level": 0.0, "warning": ""}
            for name in ("microphone", "system")
        }

    def start(self):
        for source in self.sources:
            thread = threading.Thread(
                target=self._run, args=(source,), name="meeting-" + source, daemon=True
            )
            self._threads.append(thread)
            thread.start()

    def snapshot(self):
        with self._lock:
            return {name: dict(value) for name, value in self.sources.items()}

    def _state(self, source, **values):
        with self._lock:
            self.sources[source].update(values)
        self.notify()

    def _run(self, source):
        writer = None
        chunk_id = None
        frames = 0
        rate = 0
        chunk_start = 0

        def finish():
            nonlocal writer, frames, chunk_id
            if writer is None:
                return
            writer._file.flush()
            os.fsync(writer._file.fileno())
            writer.close()
            writer = None
            self.store.finish_chunk(
                self.owner, self.meeting_id, chunk_id, frames * 1000 // rate
            )
            frames = 0
            chunk_id = None
            self.notify()

        def packet(pcm, sample_rate):
            nonlocal writer, frames, rate, chunk_id, chunk_start
            if self.stop_event.is_set():
                return
            if self.clock() - self.started >= MAX_MEETING_SECONDS:
                self.stop_event.set()
                self._state(source, warning="meeting.duration_limit")
                return
            if not pcm:
                return
            if sample_rate <= 0 or len(pcm) % 2:
                raise MeetingError("meeting.capture_error")
            if writer is not None and rate != sample_rate:
                raise MeetingError("meeting.device_changed")
            samples = array("h", pcm)
            level = min(
                1.0,
                math.sqrt(sum(float(x) * x for x in samples) / max(1, len(samples)))
                / 32768,
            )
            self._state(source, state="recording", level=level)
            offset = 0
            packet_start = max(
                0,
                int((self.clock() - self.started) * 1000)
                - len(pcm) * 500 // sample_rate,
            )
            while offset < len(pcm):
                if writer is None:
                    rate = sample_rate
                    chunk_start = packet_start + offset * 500 // sample_rate
                    chunk_id, path = self.store.open_chunk(
                        self.owner, self.meeting_id, source, chunk_start
                    )
                    writer = wave.open(str(path), "wb")
                    writer.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                count = min(len(pcm) - offset, (CHUNK_SECONDS * rate - frames) * 2)
                writer.writeframes(pcm[offset : offset + count])
                # WAV headers are updated for every packet. Flush audio before
                # advertising a completed chunk, and periodically for recovery.
                writer._file.flush()
                offset += count
                frames += count // 2
                if frames == CHUNK_SECONDS * rate:
                    os.fsync(writer._file.fileno())
                    finish()

        try:
            self._state(source, state="recording")
            self.source_factory(source).run(
                self.stop_event, packet, lambda key: self._state(source, warning=key)
            )
            self._state(source, state="stopped", level=0.0)
        except Exception as error:
            self._state(
                source,
                state="failed",
                level=0.0,
                warning=error.code
                if isinstance(error, MeetingError)
                else "meeting.capture_error",
            )
        finally:
            try:
                finish()
            except Exception:
                if writer is not None:
                    writer.close()
                self._state(
                    source, state="failed", level=0.0, warning="meeting.store_error"
                )

    def stop(self):
        self.stop_event.set()
        # The platform reader is polling and owns all COM objects. Joining here
        # guarantees capture closes before processing, cancellation, or shutdown.
        for thread in self._threads:
            thread.join()

    @property
    def alive(self):
        return any(thread.is_alive() for thread in self._threads)
