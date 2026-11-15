"""Device-only recordings retained until the user deletes them from History."""

from __future__ import annotations

import os
import base64
import hashlib
import json
import struct
import threading
import wave
import re
import tempfile
import uuid
from pathlib import Path

_ACTIVE: set[Path] = set()
_LOCK = threading.RLock()
_PROCESSING: set[Path] = set()
_GENERATION = 0
_WORKING_NAME = re.compile(r"clarify-recording-[a-z0-9_]{8}\.wav\Z")
_NAME = re.compile(r"[0-9a-f]{32}\.wav\Z")


class RecordingRecovery:
    def __init__(self, profile: Path):
        self.directory = Path(profile) / "recording-recovery"

    @staticmethod
    def active(path: Path, value: bool) -> None:
        global _GENERATION
        _GENERATION += 1
        if value:
            _ACTIVE.add(path)
        else:
            _ACTIVE.discard(path)

    def _directory(self) -> Path:
        if (
            self.directory.is_symlink()
            or getattr(self.directory, "is_junction", lambda: False)()
        ):
            raise ValueError("Invalid recovery directory")
        return self.directory

    def path(self, token: str) -> Path:
        if not isinstance(token, str) or not (
            _NAME.fullmatch(token) or _WORKING_NAME.fullmatch(token)
        ):
            raise ValueError("Invalid recording")
        path = (
            self.directory.parent
            if _WORKING_NAME.fullmatch(token)
            else self._directory()
        ) / token
        if path in _ACTIVE or path.is_symlink() or not path.is_file():
            raise ValueError("Recording unavailable")
        return path

    def save(self, audio: bytes) -> str:
        directory = self._directory()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".recording-", dir=directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(audio)
                stream.flush()
                os.fsync(stream.fileno())
            token = f"{uuid.uuid4().hex}.wav"
            os.replace(temporary, directory / token)
            return token
        finally:
            temporary.unlink(missing_ok=True)

    def revision(self) -> str:
        try:
            archived = self.directory.stat().st_mtime_ns
        except OSError:
            archived = 0
        # Profile changes include unrelated settings saves. Only stranded
        # recording files can change the recovery list outside its archive.
        remaining = []
        try:
            for path in self.directory.parent.glob("clarify-recording-*.wav"):
                if not _WORKING_NAME.fullmatch(path.name):
                    continue
                try:
                    stamp = path.lstat()
                    remaining.append((path.name, stamp.st_mtime_ns, stamp.st_size))
                except OSError:
                    continue
        except OSError:
            pass
        return str((archived, sorted(remaining), _GENERATION))

    def metadata(self, token: str) -> dict:
        path = self.path(token).with_suffix(".json")
        try:
            if path.is_symlink() or path.stat().st_size > 8192:
                return {}
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1:
                return {}
            result = {"version": 1}
            if (
                isinstance(value.get("history_id"), str)
                and len(value["history_id"]) <= 512
            ):
                result["history_id"] = value["history_id"]
            if value.get("status") in ("saved", "processing", "failed", "complete"):
                result["status"] = value["status"]
            duration = value.get("duration")
            if type(duration) in (int, float) and 0 <= duration < float("inf"):
                result["duration"] = duration
            if type(value.get("use_original")) is bool:
                result["use_original"] = value["use_original"]
            return result
        except (OSError, ValueError):
            return {}

    def update(self, token: str, **changes) -> None:
        global _GENERATION
        _GENERATION += 1
        if set(changes) - {"history_id", "status", "duration", "use_original"}:
            raise ValueError("Invalid recording metadata")
        with _LOCK:
            audio = self.path(token)
            if "status" in changes:
                if changes["status"] == "processing":
                    _PROCESSING.add(audio)
                else:
                    _PROCESSING.discard(audio)
            path = audio.with_suffix(".json")
            if path.is_symlink():
                raise ValueError("Invalid recording metadata")
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(existing, dict) or existing.get("version") != 1:
                    raise ValueError("Unsupported recording metadata")
            value = {"version": 1, **self.metadata(token), **changes}
            descriptor, name = tempfile.mkstemp(prefix=".metadata-", dir=path.parent)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(value, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)

    def linked(self) -> dict[str, dict]:
        return {
            row["history_id"]: row for row in self.entries() if row.get("history_id")
        }

    def audio_chunk(self, token: str, offset: int) -> dict:
        if type(offset) is not int or offset < 0:
            raise ValueError("Invalid audio offset")
        path = self.path(token)
        with path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            if offset > stat.st_size:
                raise ValueError("Invalid audio offset")
            stream.seek(offset)
            data = stream.read(192 * 1024)
        if (
            offset == 0
            and len(data) >= 44
            and data[:4] == b"RIFF"
            and data[8:12] == b"WAVE"
            and data[36:40] == b"data"
        ):
            # SoX termination can leave its open PCM stream length in the header.
            # Repair sizes for playback/export without changing stored samples.
            if data[4:8] == struct.pack("<I", 0x7FFFF024) and data[
                40:44
            ] == struct.pack("<I", 0x7FFFF000):
                data = (
                    data[:4]
                    + struct.pack("<I", stat.st_size - 8)
                    + data[8:40]
                    + struct.pack("<I", stat.st_size - 44)
                    + data[44:]
                )
        signature = hashlib.sha256(
            str((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)).encode()
        ).hexdigest()
        return {
            "data": base64.b64encode(data).decode("ascii"),
            "offset": offset,
            "total": stat.st_size,
            "signature": signature,
        }

    def entries(self) -> list[dict]:
        try:
            directory = self._directory()
            paths = list(directory.iterdir()) if directory.exists() else []
        except (OSError, ValueError):
            paths = []
        paths.extend(self.directory.parent.glob("clarify-recording-*.wav"))
        rows = []
        for path in paths:
            if not (_NAME.fullmatch(path.name) or _WORKING_NAME.fullmatch(path.name)):
                continue
            try:
                self.path(path.name)
                stat = path.stat()
            except (OSError, ValueError):
                continue
            if stat.st_size < 1000:
                continue
            meta = self.metadata(path.name)
            duration = meta.get("duration", 0)
            if not isinstance(duration, (int, float)) or duration <= 0:
                try:
                    with wave.open(str(path), "rb") as stream:
                        frames = min(
                            stream.getnframes(),
                            max(0, stat.st_size - 44)
                            // (stream.getnchannels() * stream.getsampwidth()),
                        )
                        duration = frames / stream.getframerate()
                except (OSError, ValueError, EOFError, wave.Error):
                    duration = 0
            rows.append(
                {
                    "id": path.name,
                    "timestamp": stat.st_mtime,
                    "bytes": stat.st_size,
                    "status": (
                        "processing"
                        if path in _PROCESSING
                        else "saved"
                        if meta.get("status") == "processing"
                        else meta.get("status", "saved")
                    ),
                    "duration": duration,
                    "history_id": meta.get("history_id", ""),
                    "use_original": bool(meta.get("use_original", False)),
                }
            )
        return sorted(rows, key=lambda row: row["timestamp"], reverse=True)

    def release_processing(self, token: str) -> None:
        global _GENERATION
        if not isinstance(token, str) or not (
            _NAME.fullmatch(token) or _WORKING_NAME.fullmatch(token)
        ):
            raise ValueError("Invalid recording")
        path = (
            self.directory.parent if _WORKING_NAME.fullmatch(token) else self.directory
        ) / token
        with _LOCK:
            _PROCESSING.discard(path)
            _GENERATION += 1

    def delete(self, token: str) -> None:
        path = self.path(token)
        if path in _PROCESSING:
            raise ValueError("Recording is processing")
        path.unlink()
        path.with_suffix(".json").unlink(missing_ok=True)
