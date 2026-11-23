"""Write a CoreAudio input stream to the desktop recording WAV."""

from __future__ import annotations

import math
import queue
import threading
import wave
from pathlib import Path
from typing import Any, BinaryIO, Callable


def pcm_level(indata: Any) -> float:
    raw = memoryview(indata)
    samples = (
        raw
        if raw.format in {"h", "<h", "=h", "@h"} and raw.ndim == 1
        else memoryview(raw.tobytes()).cast("h")
    )
    if not samples:
        return 0.0
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    return min(1.0, rms / 32768.0 * 16)


class CoreAudioCapture:
    """Own one PortAudio input and its WAV writer until capture stops."""

    def __init__(
        self,
        backend: Any,
        path: Path,
        device: int | None,
        on_level: Callable[[float], None],
    ) -> None:
        self._path = path
        self._on_level = on_level
        self._finished = threading.Event()
        self._interrupted = threading.Event()
        self._stream_lock = threading.Lock()
        self._blocks: queue.Queue[bytes] = queue.Queue(maxsize=256)
        self._writer: threading.Thread | None = None

        def receive(indata, _frames, _time_info, status):
            if getattr(status, "input_overflow", False):
                self._interrupted.set()
                raise backend.CallbackAbort
            block = bytes(indata)
            if block:
                try:
                    self._blocks.put_nowait(block)
                except queue.Full as error:
                    self._interrupted.set()
                    raise backend.CallbackAbort from error

        self._stream = backend.RawInputStream(
            device=device,
            channels=1,
            samplerate=16000,
            blocksize=256,
            dtype="int16",
            callback=receive,
        )

    def start(self) -> None:
        sink = self._path.open("wb", buffering=0)
        writer = threading.Thread(
            target=self._write_wav,
            args=(sink,),
            name="ClarifyCoreAudioWav",
            daemon=True,
        )
        try:
            writer.start()
        except Exception:
            sink.close()
            raise
        self._writer = writer
        self._stream.start()

    @property
    def active(self) -> bool:
        try:
            with self._stream_lock:
                return bool(
                    self._writer
                    and self._writer.is_alive()
                    and self._stream is not None
                    and self._stream.active
                )
        except Exception:
            return False

    @property
    def interrupted(self) -> bool:
        return self._interrupted.is_set()

    def _write_wav(self, sink: BinaryIO) -> None:
        # Keep file I/O and level calculation off PortAudio's callback thread.
        try:
            with sink, wave.open(sink, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                while True:
                    try:
                        block = self._blocks.get(timeout=0.05)
                    except queue.Empty:
                        if self._finished.is_set():
                            return
                        continue
                    wav.writeframesraw(block)
                    self._on_level(pcm_level(block))
        except OSError:
            self._interrupted.set()

    def close(self) -> None:
        with self._stream_lock:
            stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            if self._writer is not None:
                if not stream.active:
                    self._interrupted.set()
                stream.stop()
        except Exception:
            self._interrupted.set()
        try:
            stream.close()
        except Exception:
            pass
        finally:
            self._finished.set()
            if self._writer is not None:
                self._writer.join()
