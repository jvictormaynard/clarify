"""Read a private Core Audio tap alongside microphone PCM."""

from __future__ import annotations

from ctypes import CDLL, POINTER, byref, c_int, c_int16, c_int32, c_size_t, c_void_p
from pathlib import Path
import platform
import sys
import time


class SystemAudioError(Exception):
    def __init__(self, code="system_audio_unavailable"):
        super().__init__(code)


class SystemAudioTap:
    def __init__(self, library):
        self._library = library
        status = c_int32()
        self._handle = library.clarify_meeting_tap_open(byref(status))
        if not self._handle:
            raise SystemAudioError()
        self._last_input = time.monotonic()

    def mix(self, pcm: bytes) -> tuple[bytes, bytes, int, bool]:
        frames = len(pcm) // 2
        samples = (c_int16 * frames).from_buffer_copy(pcm)
        system = (c_int16 * frames)()
        valid = c_size_t()
        result = self._library.clarify_meeting_tap_read(
            self._handle, samples, system, frames, byref(valid)
        )
        if result == -2:
            raise SystemAudioError("capture_overload")
        if result == -3 and time.monotonic() - self._last_input < 2:
            return pcm, bytes(system), 0, False
        if result < 0:
            raise SystemAudioError()
        self._last_input = time.monotonic()
        return bytes(samples), bytes(system), valid.value, bool(result)

    def close(self):
        if self._handle:
            self._library.clarify_meeting_tap_close(self._handle)
            self._handle = None


def load_system_audio():
    if sys.platform != "darwin":
        return None
    version = platform.mac_ver()[0].split(".")
    if len(version) < 2 or tuple(map(int, version[:2])) < (14, 2):
        return None
    bundle = getattr(sys, "_MEIPASS", None)
    root = (
        Path(bundle) if bundle else Path(__file__).resolve().parents[2] / "build/macos"
    )
    try:
        library = CDLL(str(root / "libclarify_meeting_audio.dylib"))
        library.clarify_meeting_tap_open.argtypes = [POINTER(c_int32)]
        library.clarify_meeting_tap_open.restype = c_void_p
        library.clarify_meeting_tap_read.argtypes = [
            c_void_p,
            POINTER(c_int16),
            POINTER(c_int16),
            c_size_t,
            POINTER(c_size_t),
        ]
        library.clarify_meeting_tap_read.restype = c_int
        library.clarify_meeting_tap_close.argtypes = [c_void_p]
        library.clarify_meeting_tap_close.restype = None
    except (OSError, AttributeError):
        return None
    return lambda: SystemAudioTap(library)
