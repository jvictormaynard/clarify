"""Speculative full-recording recognition at pauses in the PCM WAV.

No partial text is delivered. Invalid/changed audio or processing failures discard
all segments and leave the original full recording for normal transcription.
"""

from __future__ import annotations
from array import array
import hashlib
import io
from pathlib import Path
import struct
import sys
import threading
import time
import wave

RATE = 16000
FRAME = 640  # 20 ms, mono signed 16-bit
MAX_PENDING = RATE * 2 * 60
MAX_RECORDING = RATE * 2 * 60 * 30


def pcm_offset(header):
    if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("Unsupported WAV")
    pos, valid = 12, False
    while pos + 8 <= len(header):
        kind = header[pos : pos + 4]
        size = struct.unpack_from("<I", header, pos + 4)[0]
        if kind == b"fmt " and size >= 16:
            fmt, channels, rate, _, _, bits = struct.unpack_from(
                "<HHIIHH", header, pos + 8
            )
            valid = (fmt, channels, rate, bits) == (1, 1, RATE, 16)
        if kind == b"data":
            if not valid:
                raise ValueError("Streaming requires PCM16 mono 16 kHz")
            return pos + 8
        pos += 8 + size + size % 2
    raise ValueError("Incomplete WAV header")


def wav_bytes(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)
    return output.getvalue()


def quiet_tail(pcm):
    """Skip only near-silent trailing samples, below the pause threshold."""
    samples = array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return bool(samples) and (
        max(abs(value) for value in samples) <= 100
        and sum(value * value for value in samples) / len(samples) < 25 * 25
    )


class PauseStream:
    def __init__(
        self,
        path,
        backend,
        model,
        language,
        cancel_token,
        *,
        initial_prompt="",
        worker_wait_seconds=8.0,
        finalize_seconds=8.0,
    ):
        self.path, self.backend = Path(path), backend
        self.model, self.language, self.cancel_token = model, language, cancel_token
        self.initial_prompt = initial_prompt
        self.worker_wait_seconds = max(0.0, float(worker_wait_seconds))
        self.finalize_seconds = max(0.0, float(finalize_seconds))
        self.done = threading.Event()
        self.abort = threading.Event()
        self.on_finished = lambda: None
        self.failed = False
        self.parts = []
        self.completed_snapshots = 0
        self.committed = 0
        self.digest = hashlib.sha256()
        self.worker = threading.Thread(
            target=self._run, daemon=True, name="LocalASRPauseStream"
        )

    def start(self):
        self.worker.start()

    def _decode(self, pcm):
        from local_asr import _CancellationView

        kwargs = {"initial_prompt": self.initial_prompt} if self.initial_prompt else {}
        return self.backend.transcribe(
            self.path,
            self.language,
            audio_bytes=wav_bytes(pcm),
            cancel_event=_CancellationView(self.cancel_token, self.abort),
            **kwargs,
        ).strip()

    def _run(self):
        pending = bytearray()
        prefix = bytearray()
        scanned = silent = 0
        speech = False
        offset = None
        read_count = 0
        try:
            while not self.done.wait(0.2):
                if self.cancel_token.cancelled or self.abort.is_set():
                    return
                with self.path.open("rb") as source:
                    if offset is None:
                        try:
                            offset = pcm_offset(source.read(4096))
                        except ValueError:
                            continue
                    if self.path.stat().st_size - offset - read_count > MAX_PENDING:
                        raise ValueError("Streaming backlog exceeded")
                    source.seek(offset + read_count)
                    chunk = source.read(MAX_PENDING)
                read_count += len(chunk)
                pending.extend(chunk)
                if len(pending) > MAX_PENDING:
                    raise ValueError("No safe pause within buffer limit")
                while scanned + FRAME <= len(pending):
                    samples = array("h", pending[scanned : scanned + FRAME])
                    if sys.byteorder != "little":
                        samples.byteswap()
                    quiet = sum(v * v for v in samples) / len(samples) < 100 * 100
                    silent = silent + FRAME if quiet else 0
                    speech = speech or not quiet
                    scanned += FRAME
                    if speech and silent >= RATE * 2 and scanned >= RATE * 2 * 3:
                        cut = scanned - RATE  # preserve half a second on each side
                        part = bytes(pending[:cut])
                        if len(prefix) + len(part) > MAX_RECORDING:
                            raise ValueError("Background recording limit exceeded")
                        # Re-decode the full prefix. Independent chunks change
                        # names and can lose quiet speech when context resets.
                        text = self._decode(bytes(prefix) + part)
                        if not text:
                            raise ValueError("Empty snapshot")
                        prefix.extend(part)
                        self.parts[:] = [text]
                        self.completed_snapshots += 1
                        self.digest.update(part)
                        self.committed += cut
                        del pending[:cut]
                        scanned, silent, speech = 0, 0, False
                        if self.done.is_set():
                            return
        except Exception:
            self.failed = True
        finally:
            self.on_finished()

    def finish(self, audio):
        self.done.set()
        deadline = time.monotonic() + self.finalize_seconds
        worker_deadline = min(deadline, time.monotonic() + self.worker_wait_seconds)
        while self.worker.is_alive():
            remaining = worker_deadline - time.monotonic()
            if self.cancel_token.cancelled or remaining <= 0:
                self.abort.set()
                return None
            self.worker.join(timeout=min(0.05, remaining))
        if self.failed or not self.parts or self.abort.is_set():
            return None
        if self.cancel_token.cancelled:
            return None
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (
                    1,
                    2,
                    RATE,
                ):
                    return None
                pcm = wav.readframes(wav.getnframes())
            if (
                len(pcm) < self.committed
                or hashlib.sha256(pcm[: self.committed]).digest()
                != self.digest.digest()
            ):
                return None
            tail = pcm[self.committed :]
            # Never join separately decoded speech. A voiced tail requires the
            # normal full-recording request, with its original decoder context.
            if tail and not quiet_tail(tail):
                return None
            if (
                self.abort.is_set()
                or self.cancel_token.cancelled
                or time.monotonic() >= deadline
            ):
                return None
            from provider_types import TranscriptionResult

            return TranscriptionResult(self.parts[0], "local_asr", self.model)
        except Exception:
            return None

    def cancel(self):
        self.abort.set()
        self.done.set()
