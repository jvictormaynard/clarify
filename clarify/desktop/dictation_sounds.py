"""Play complete dictation cues through a reusable output stream."""

import sys
import threading
import wave
from pathlib import Path


class DictationCuePlayer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._stream = None
        self._device = None
        self._samples: dict[bool, bytes] = {}

    def _open(self) -> None:
        import sounddevice

        device = sounddevice.default.device[1]
        if self._stream is not None and self._device == device:
            return
        self._discard_stream()
        roots = []
        if root := getattr(sys, "_MEIPASS", None):
            roots.append(Path(root))
        if getattr(sys, "frozen", False):
            roots.append(Path(sys.executable).resolve().parent)
        roots.append(Path(__file__).resolve().parents[2])
        formats = []
        for starting, name in (
            (True, "dictation-start.wav"),
            (False, "dictation-stop.wav"),
        ):
            path = next(
                root / "assets" / "sounds" / name
                for root in roots
                if (root / "assets" / "sounds" / name).is_file()
            )
            with wave.open(str(path), "rb") as audio:
                formats.append(
                    (audio.getframerate(), audio.getnchannels(), audio.getsampwidth())
                )
                self._samples[starting] = audio.readframes(audio.getnframes())
        if formats[0] != formats[1] or formats[0][2] != 2:
            raise ValueError("Dictation cues require matching 16-bit PCM formats")
        rate, channels, _ = formats[0]
        # Opening the Windows output can take seconds. Keep it open, but stop
        # between cues so idle playback cannot underflow or record silence.
        self._stream = sounddevice.RawOutputStream(
            samplerate=rate,
            channels=channels,
            dtype="int16",
            device=device,
            latency="low",
        )
        self._device = device

    def prepare(self) -> None:
        """Open output on a startup worker; sound failure must not block startup."""
        with self._lock:
            if self._closed.is_set():
                return
            try:
                self._open()
            except Exception:
                self._discard_stream()

    def __call__(self, starting: bool) -> None:
        with self._lock:
            if self._closed.is_set():
                return
            try:
                self._open()
                self._stream.start()
                self._stream.write(self._samples[starting])
                # stop drains queued frames. close/abort would cut off the tail.
                self._stream.stop()
            except Exception:
                self._discard_stream()
                raise

    def _discard_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            self._discard_stream()
