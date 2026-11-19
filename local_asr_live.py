"""Native incremental recognition. PCM input is mono, 16 kHz, signed LE16.

A session has one bounded queue and one native owner. Callbacks run on that
owner and must return promptly. Partials are display-only; finish returns the
raw transcript for the existing once-only workflow publication path.
"""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import queue
import struct
import threading
import time
import wave

from local_asr import LocalASRCancelledError, LocalASRSidecarError

MODEL_ID = "nemotron-3.5-streaming"
RATE = 16000
MAX_CHUNK = 2560  # 80 ms
MAX_PENDING = 100  # eight seconds, including cold load; never drop speech


class Load(C.Structure):
    _fields_ = [
        ("size", C.c_uint64),
        ("backend", C.c_int),
        ("device", C.c_void_p),
        ("no_mmap", C.c_bool),
    ]


class SessionParams(C.Structure):
    _fields_ = [
        ("size", C.c_uint64),
        ("threads", C.c_int),
        ("kv", C.c_int),
        ("ctx", C.c_int32),
    ]


class Run(C.Structure):
    _fields_ = [
        ("size", C.c_uint64),
        ("task", C.c_int),
        ("timestamps", C.c_int),
        ("pnc", C.c_int),
        ("itn", C.c_int),
        ("diarize", C.c_int),
        ("language", C.c_char_p),
        ("target", C.c_char_p),
        ("tags", C.c_bool),
        ("family", C.c_void_p),
        ("drafts", C.c_int32),
        ("vocabulary", C.c_void_p),
        ("n_vocabulary", C.c_int32),
        ("prompt", C.c_char_p),
        ("prefix", C.c_char_p),
    ]


class StreamParams(C.Structure):
    _fields_ = [
        ("size", C.c_uint64),
        ("family", C.c_void_p),
        ("policy", C.c_int),
        ("agreement", C.c_uint32),
    ]


class Update(C.Structure):
    _fields_ = [
        ("size", C.c_uint64),
        ("changed", C.c_bool),
        ("final", C.c_bool),
        ("revision", C.c_int32),
        ("received", C.c_int64),
        ("committed", C.c_int64),
        ("buffered", C.c_int64),
        ("committed_changed", C.c_bool),
        ("tentative_changed", C.c_bool),
    ]


class Text(C.Structure):
    _fields_ = [
        ("size", C.c_uint64),
        ("full", C.c_char_p),
        ("full_bytes", C.c_uint64),
        ("committed", C.c_char_p),
        ("committed_bytes", C.c_uint64),
        ("tentative", C.c_char_p),
        ("tentative_bytes", C.c_uint64),
        ("raw_start", C.c_uint64),
    ]


@dataclass(frozen=True)
class LiveResult:
    text: str
    committed: str
    final: bool
    received_seconds: float


def _check(status):
    if status:
        raise LocalASRSidecarError(f"Native recognition failed ({status})")


class NativeEngine:
    """One warm model, serialized compute, three CPU threads, explicit shutdown.

    The installer verifies every library and model before the first native load.
    No network access or automatic installation occurs here.
    """

    compute_device = "cpu"
    native_streaming = True

    def __init__(self, installer, idle_seconds=120):
        self.installer = installer
        self.idle_seconds = idle_seconds
        self._lock = threading.Lock()
        self._state = threading.Lock()
        self._sessions = set()
        self._timer = None
        self._model = C.c_void_p()
        self._lib = None
        self._dll_directory = None
        self._closed = False

    def _load(self):
        if self._model.value:
            return
        self.installer.verify()
        path = self.installer.executable_path
        if os.name == "nt":
            self._dll_directory = os.add_dll_directory(str(path.parent))
        lib = C.CDLL(str(path))
        signatures = {
            "version": ([], C.c_char_p),
            "init_backends_default": ([], C.c_int),
            "model_load_params_init": ([C.POINTER(Load)], None),
            "model_load_file": (
                [C.c_char_p, C.POINTER(Load), C.POINTER(C.c_void_p)],
                C.c_int,
            ),
            "model_free": ([C.c_void_p], None),
            "session_params_init": ([C.POINTER(SessionParams)], None),
            "session_init": (
                [C.c_void_p, C.POINTER(SessionParams), C.POINTER(C.c_void_p)],
                C.c_int,
            ),
            "session_free": ([C.c_void_p], None),
            "run_params_init": ([C.POINTER(Run)], None),
            "stream_params_init": ([C.POINTER(StreamParams)], None),
            "stream_update_init": ([C.POINTER(Update)], None),
            "stream_text_init": ([C.POINTER(Text)], None),
            "stream_begin": (
                [C.c_void_p, C.POINTER(Run), C.POINTER(StreamParams)],
                C.c_int,
            ),
            "stream_feed": (
                [C.c_void_p, C.POINTER(C.c_float), C.c_int, C.POINTER(Update)],
                C.c_int,
            ),
            "stream_finalize": ([C.c_void_p, C.POINTER(Update)], C.c_int),
            "stream_get_text": ([C.c_void_p, C.POINTER(Text)], C.c_int),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(lib, "transcribe_" + name)
            fn.argtypes, fn.restype = args, result
        if lib.transcribe_version() != b"0.4.2":
            raise LocalASRSidecarError("Native runtime ABI does not match 0.4.2")
        _check(lib.transcribe_init_backends_default())
        params = Load()
        lib.transcribe_model_load_params_init(C.byref(params))
        params.backend = 4  # CPU_ACCEL; never auto-select a GPU
        _check(
            lib.transcribe_model_load_file(
                os.fsencode(self.installer.model_path),
                C.byref(params),
                C.byref(self._model),
            )
        )
        self._lib = lib

    def open_live_session(self, language="en", on_result=None):
        with self._state:
            if self._closed:
                raise LocalASRSidecarError("Recognition engine is closed")
            if self._sessions:
                raise LocalASRSidecarError("Recognition is already active")
            if self._timer:
                self._timer.cancel()
            session = LiveSession(self, language, on_result)
            self._sessions.add(session)
            session.worker.start()
            return session

    def _released(self, session):
        with self._state:
            self._sessions.discard(session)
            if not self._closed:
                self._timer = threading.Timer(self.idle_seconds, self._unload)
                self._timer.daemon = True
                self._timer.start()

    def _unload(self):
        with self._lock:
            with self._state:
                if self._sessions:
                    return
            if self._model.value:
                self._lib.transcribe_model_free(self._model)
                self._model = C.c_void_p()
            if self._dll_directory:
                self._dll_directory.close()
                self._dll_directory = None

    def prepare(self, *args):
        # Loading belongs to the live owner; no competing preparation worker.
        return None

    def transcribe(
        self,
        audio_path,
        language="en",
        cancel_event=None,
        *,
        audio_bytes=None,
        **kwargs,
    ):
        live = self.open_live_session(language)
        try:
            with wave.open(
                io.BytesIO(audio_bytes) if audio_bytes is not None else str(audio_path),
                "rb",
            ) as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (
                    1,
                    2,
                    RATE,
                ):
                    raise LocalASRSidecarError("Recognition requires PCM16 mono 16 kHz")
                while chunk := wav.readframes(MAX_CHUNK // 2):
                    live.feed(chunk, timeout=30, cancel_event=cancel_event)
            return live.finish(cancel_event=cancel_event).text
        finally:
            live.cancel()

    def cancel(self):
        with self._state:
            sessions = tuple(self._sessions)
        for session in sessions:
            session.cancel()

    def shutdown(self):
        with self._state:
            self._closed = True
            if self._timer:
                self._timer.cancel()
            sessions = tuple(self._sessions)
        for session in sessions:
            session.cancel()
        # Native compute owns its memory until it returns. Never free it early.
        for session in sessions:
            session.worker.join()
        self._unload()

    stop = shutdown


class LiveSession:
    def __init__(self, engine, language, callback):
        self.engine, self.callback = engine, callback
        language = str(language or "auto").replace("_", "-")
        defaults = {
            "en": "en-US",
            "es": "es-US",
            "fr": "fr-FR",
            "it": "it-IT",
            "pt": "pt-BR",
            "nl": "nl-NL",
            "de": "de-DE",
            "tr": "tr-TR",
            "ru": "ru-RU",
            "ar": "ar-AR",
            "hi": "hi-IN",
            "ja": "ja-JP",
            "ko": "ko-KR",
            "vi": "vi-VN",
            "uk": "uk-UA",
            "pl": "pl-PL",
            "sv": "sv-SE",
            "cs": "cs-CZ",
            "nb": "nb-NO",
            "da": "da-DK",
            "bg": "bg-BG",
            "fi": "fi-FI",
            "hr": "hr-HR",
            "sk": "sk-SK",
            "zh": "zh-CN",
            "hu": "hu-HU",
            "ro": "ro-RO",
            "et": "et-EE",
        }
        parts = language.split("-")
        self.language = (
            (parts[0].lower() + "-" + parts[1].upper())
            if len(parts) == 2
            else defaults.get(language.lower(), language)
        )
        self.queue = queue.Queue(MAX_PENDING)
        self.abort, self.done, self.ready = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self._input_lock = threading.Lock()
        self._publication_lock = threading.RLock()
        self._finishing = False
        self._samples = 0
        self.error = None
        self.result = None
        self.compute_seconds = 0.0
        self.worker = threading.Thread(target=self._run, name="NativeASR", daemon=True)

    def _check(self, external=None):
        if self.abort.is_set() or (external is not None and external.is_set()):
            raise LocalASRCancelledError("Recognition was cancelled")
        if self.error:
            raise self.error

    def _put(self, value, timeout, external=None):
        deadline = time.monotonic() + timeout
        while True:
            self._check(external)
            try:
                self.queue.put(
                    value, timeout=min(0.05, max(0, deadline - time.monotonic()))
                )
                return
            except queue.Full:
                if time.monotonic() >= deadline:
                    self.cancel()
                    raise LocalASRSidecarError("Recognition queue is full")

    def feed(self, pcm: bytes, *, timeout=0.0, cancel_event=None):
        if not pcm or len(pcm) > MAX_CHUNK or len(pcm) % 2:
            raise ValueError("Feed 1 to 1280 PCM16 samples per call")
        with self._input_lock:
            if self._finishing:
                raise LocalASRSidecarError("Recognition input is closed")
            if self._samples + len(pcm) // 2 > RATE * 60 * 30:
                self.cancel()
                raise LocalASRSidecarError("Recognition exceeded thirty minutes")
            self._put(bytes(pcm), timeout, cancel_event)
            self._samples += len(pcm) // 2

    def finish(self, *, timeout=30.0, cancel_event=None):
        deadline = time.monotonic() + timeout
        with self._input_lock:
            if not self._finishing:
                self._finishing = True
                self._put(None, timeout, cancel_event)
        while not self.done.wait(0.05):
            self._check(cancel_event)
            if time.monotonic() >= deadline:
                self.cancel()
                raise LocalASRSidecarError("Recognition finalization timed out")
        self._check(cancel_event)
        return self.result

    def cancel(self):
        # After this returns, no callback from this session can publish.
        with self._publication_lock:
            self.abort.set()

    def _publish(self, result):
        with self._publication_lock:
            self._check()
            if self.callback:
                self.callback(result)

    def _run(self):
        session = C.c_void_p()
        try:
            with self.engine._lock:
                self._check()
                self.engine._load()
                lib = self.engine._lib
                sp = SessionParams()
                lib.transcribe_session_params_init(C.byref(sp))
                sp.threads = 3
                _check(
                    lib.transcribe_session_init(
                        self.engine._model, C.byref(sp), C.byref(session)
                    )
                )
                rp = Run()
                lib.transcribe_run_params_init(C.byref(rp))
                rp.language = (
                    None if self.language == "auto" else self.language.encode("utf8")
                )
                st = StreamParams()
                lib.transcribe_stream_params_init(C.byref(st))
                _check(lib.transcribe_stream_begin(session, C.byref(rp), C.byref(st)))
                self.ready.set()
                previous = ""
                while True:
                    self._check()
                    try:
                        chunk = self.queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    u = Update()
                    lib.transcribe_stream_update_init(C.byref(u))
                    started = time.perf_counter()
                    if chunk is None:
                        _check(lib.transcribe_stream_finalize(session, C.byref(u)))
                    else:
                        values = struct.unpack("<" + "h" * (len(chunk) // 2), chunk)
                        samples = (C.c_float * len(values))(
                            *(v / 32768 for v in values)
                        )
                        _check(
                            lib.transcribe_stream_feed(
                                session, samples, len(values), C.byref(u)
                            )
                        )
                    self.compute_seconds += time.perf_counter() - started
                    tx = Text()
                    lib.transcribe_stream_text_init(C.byref(tx))
                    _check(lib.transcribe_stream_get_text(session, C.byref(tx)))
                    result = LiveResult(
                        (tx.full or b"").decode("utf8"),
                        (tx.committed or b"").decode("utf8"),
                        chunk is None,
                        u.received / 1000,
                    )
                    self._check()
                    if result.final or result.text != previous:
                        self._publish(result)
                    previous = result.text
                    if result.final:
                        self.result = result
                        break
        except Exception as error:
            self.error = error
        finally:
            if session.value:
                self.engine._lib.transcribe_session_free(session)
            self.engine._released(self)
            self.done.set()


class CaptureStream:
    """Tail only recorded bytes from the sole recorder's growing WAV."""

    def __init__(self, path, backend, model, language, cancel_token, on_result=None):
        self.path, self.backend, self.model = Path(path), backend, model
        self.language, self.cancel_token = language, cancel_token
        self.on_result = on_result
        self.latest_text = ""
        self.done, self.abort = threading.Event(), threading.Event()
        self.on_finished = lambda: None
        self.live = None
        self.result = None
        self.error = None
        self._digest = hashlib.sha256()
        self._count = 0
        self.worker = threading.Thread(
            target=self._run, name="NativeASRCapture", daemon=True
        )

    def start(self):
        self.worker.start()

    def _run(self):
        from local_asr_streaming import pcm_offset

        try:

            def publish(result):
                if not self.abort.is_set() and not self.cancel_token.cancelled:
                    self.latest_text = result.text.encode("utf-8")[:32768].decode(
                        "utf-8", errors="ignore"
                    )
                if (
                    not self.abort.is_set()
                    and not self.cancel_token.cancelled
                    and self.on_result
                ):
                    self.on_result(result)

            self.live = self.backend.open_live_session(self.language, publish)
            offset = None
            while not self.abort.is_set() and not self.cancel_token.cancelled:
                if getattr(self.live, "error", None):
                    raise self.live.error
                if self.path.exists():
                    with self.path.open("rb") as source:
                        if offset is None:
                            try:
                                offset = pcm_offset(source.read(4096))
                            except ValueError:
                                if self.done.is_set():
                                    raise
                                self.abort.wait(0.02)
                                continue
                        backlog = self.path.stat().st_size - offset - self._count
                        if backlog > MAX_PENDING * MAX_CHUNK:
                            raise LocalASRSidecarError(
                                "Capture recognition backlog exceeded eight seconds"
                            )
                        source.seek(offset + self._count)
                        chunk = source.read(MAX_CHUNK)
                    chunk = chunk[: len(chunk) // 2 * 2]
                    if chunk:
                        self.live.feed(chunk)
                        self._digest.update(chunk)
                        self._count += len(chunk)
                        continue
                if self.done.is_set():
                    self.result = self.live.finish(cancel_event=self.abort)
                    return
                self.abort.wait(0.02)
        except Exception as error:
            self.error = error
        finally:
            if self.live:
                self.live.cancel()
                self.live.worker.join()
            self.on_finished()

    def finish(self, audio):
        from provider_types import TranscriptionResult

        self.done.set()
        deadline = time.monotonic() + 30
        while self.worker.is_alive():
            if self.cancel_token.cancelled or time.monotonic() > deadline:
                self.cancel()
                raise LocalASRCancelledError(
                    "Capture recognition was cancelled or timed out"
                )
            self.worker.join(0.05)
        if self.error:
            raise self.error
        with wave.open(io.BytesIO(audio), "rb") as wav:
            pcm = wav.readframes(wav.getnframes())
        if self.abort.is_set() or self.cancel_token.cancelled:
            raise LocalASRCancelledError("Capture recognition was cancelled")
        if (
            len(pcm) != self._count
            or hashlib.sha256(pcm).digest() != self._digest.digest()
        ):
            raise LocalASRSidecarError("Capture audio changed during recognition")
        return TranscriptionResult(self.result.text, "local_asr", self.model)

    def cancel(self):
        self.abort.set()
        if self.live:
            self.live.cancel()
