"""Opt-in, device-only audio fixtures for the Groq streaming experiment.

This archive is deliberately separate from transcription history and account
sync. Startup and archive access prune recordings older than seven days.
Nothing in this module sends recordings or reads credentials. It cannot remove
files while the app is closed.
"""

from __future__ import annotations

import io
import os
import re
import struct
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path

RETENTION_SECONDS = 7 * 24 * 60 * 60
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_CLIP_BYTES = 64 * 1024 * 1024
_OWNED_NAME = re.compile(r"clarify-benchmark-[0-9a-f]{32}\.wav\Z")
_TEMP_NAME = re.compile(r"\.benchmark-[a-z0-9_]{8}\Z")
_LOCK = threading.Lock()
# Pinned SoX 14.4.2 writes this PCM16/mono/16k header during Windows capture.
# TerminateProcess cannot finalize its sizes. Keep the exact snapshot for
# diagnosis; do not repair/re-encode it or alter the provider's recording.
_SOX_OPEN_HEADER = struct.pack(
    "<4sI4s4sIHHIIHH4sI",
    b"RIFF",
    0x7FFFF024,
    b"WAVE",
    b"fmt ",
    16,
    1,
    1,
    16000,
    32000,
    2,
    16,
    b"data",
    0x7FFFF000,
)


def _redirected(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _owned_files(directory: Path) -> list[tuple[Path, os.stat_result]]:
    result = []
    for path in directory.iterdir():
        if not (
            _OWNED_NAME.fullmatch(path.name) or _TEMP_NAME.fullmatch(path.name)
        ) or _redirected(path):
            continue
        stat = path.stat(follow_symlinks=False)
        if path.is_file():
            result.append((path, stat))
    return result


def _prune(directory: Path, now: float, incoming: int = 0) -> None:
    files = sorted(_owned_files(directory), key=lambda item: item[1].st_mtime)
    total = sum(stat.st_size for _, stat in files)
    for path, stat in files:
        if (
            now - stat.st_mtime < RETENTION_SECONDS
            and total + incoming <= MAX_TOTAL_BYTES
        ):
            continue
        path.unlink()
        total -= stat.st_size


def prune_audio_history(profile: Path) -> None:
    """Best-effort expiry even when collection is disabled. Never creates a dir."""
    try:
        with _LOCK:
            directory = Path(profile) / "experimental-audio"
            if _redirected(directory) or not directory.is_dir():
                return
            _prune(directory, time.time())
    except (OSError, ValueError):
        # Optional benchmark data must never prevent startup or dictation.
        return


def archive_audio(profile: Path, audio: bytes) -> Path | None:
    """Atomically retain one valid WAV. Caller owns explicit consent/once-only.

    Limits include owned WAV files and interrupted-write temporaries. Foreign
    files and symlinks are never removed. Failure leaves the original recording
    and provider flow intact.
    """
    temporary = None
    try:
        if not isinstance(audio, bytes) or not audio or len(audio) > MAX_CLIP_BYTES:
            return None
        with wave.open(io.BytesIO(audio), "rb") as stream:
            if stream.getnframes() <= 0 or stream.getcomptype() != "NONE":
                return None
            expected = (
                stream.getnframes() * stream.getnchannels() * stream.getsampwidth()
            )
            if len(stream.readframes(stream.getnframes())) != expected:
                if not (
                    audio[:44] == _SOX_OPEN_HEADER
                    and len(audio) > 44
                    and (len(audio) - 44) % 2 == 0
                ):
                    return None
        with _LOCK:
            directory = Path(profile) / "experimental-audio"
            if _redirected(directory):
                return None
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            _prune(directory, time.time(), len(audio))
            descriptor, raw_path = tempfile.mkstemp(prefix=".benchmark-", dir=directory)
            temporary = Path(raw_path)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(audio)
                stream.flush()
                os.fsync(stream.fileno())
            target = directory / f"clarify-benchmark-{uuid.uuid4().hex}.wav"
            os.replace(temporary, target)
            temporary = None
            return target
    except (OSError, ValueError, EOFError, wave.Error):
        return None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
