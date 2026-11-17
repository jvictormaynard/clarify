"""CPU-only final transcription, with bounded and cancellable native compute.

Frozen application entry points must call multiprocessing.freeze_support() before
starting the desktop app. Granite uses spawn so cancellation can stop native code
without freeing memory that is still in use.
"""

import ctypes as C
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import wave

from local_asr import (
    LocalASRCancelledError,
    LocalASRIntegrityError,
    LocalASRSidecarError,
)
from local_asr_batch_assets import MODELS
from local_asr_live import Load, SessionParams, Run, _check

MAX_SAMPLES = 16000 * 60 * 30
MAX_OUTPUT = 1024 * 1024


def _granite_worker(library, model, wav_path, language, result_path):
    """Spawn target: owns all native pointers until exit or process termination."""
    session = C.c_void_p()
    dll_directory = None
    try:
        if os.name == "nt":
            dll_directory = os.add_dll_directory(str(Path(library).parent))
        lib = C.CDLL(library)
        signatures = {
            "version": ([], C.c_char_p),
            "init_backends_default": ([], C.c_int),
            "model_load_params_init": ([C.POINTER(Load)], None),
            "session_params_init": ([C.POINTER(SessionParams)], None),
            "run_params_init": ([C.POINTER(Run)], None),
            "open": (
                [
                    C.c_char_p,
                    C.POINTER(Load),
                    C.POINTER(SessionParams),
                    C.POINTER(C.c_void_p),
                ],
                C.c_int,
            ),
            "run": (
                [C.c_void_p, C.POINTER(C.c_float), C.c_int, C.POINTER(Run)],
                C.c_int,
            ),
            "full_text": ([C.c_void_p], C.c_char_p),
            "was_truncated": ([C.c_void_p], C.c_bool),
            "session_free": ([C.c_void_p], None),
        }
        for name, (args, result) in signatures.items():
            function = getattr(lib, "transcribe_" + name)
            function.argtypes, function.restype = args, result
        if lib.transcribe_version() != b"0.4.2":
            raise LocalASRSidecarError("Native runtime ABI does not match 0.4.2")
        _check(lib.transcribe_init_backends_default())
        lp, sp, rp = Load(), SessionParams(), Run()
        lib.transcribe_model_load_params_init(C.byref(lp))
        lp.backend = 4  # CPU_ACCEL, never automatic GPU selection.
        lib.transcribe_session_params_init(C.byref(sp))
        sp.threads = 3
        _check(
            lib.transcribe_open(
                os.fsencode(model), C.byref(lp), C.byref(sp), C.byref(session)
            )
        )
        lib.transcribe_run_params_init(C.byref(rp))
        rp.language = None if language == "auto" else language.encode("utf8")
        with wave.open(wav_path, "rb") as source:
            pcm = source.readframes(MAX_SAMPLES)
        count = max(1120, len(pcm) // 2)
        integers = (C.c_int16 * (len(pcm) // 2)).from_buffer_copy(pcm)
        samples = (C.c_float * count)()
        for index, value in enumerate(integers):
            samples[index] = value / 32768
        _check(lib.transcribe_run(session, samples, count, C.byref(rp)))
        if lib.transcribe_was_truncated(session):
            raise LocalASRSidecarError("Native recognition truncated the audio")
        text = (lib.transcribe_full_text(session) or b"").decode("utf8")
        payload = {"text": text}
    except Exception as error:
        payload = {"error": str(error)[:4096]}
    finally:
        if session.value:
            lib.transcribe_session_free(session)
        if dll_directory:
            dll_directory.close()
    Path(result_path).write_text(json.dumps(payload), encoding="utf8")


def _language(model, language):
    language = str(language or "auto").replace("_", "-").split("-")[0].lower()
    supported = (
        "en fr de es pt it ja"
        if model == "granite-5-turboctc"
        else "bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro sk sl es sv ru uk"
    ).split()
    if language != "auto" and language not in supported:
        raise LocalASRSidecarError(
            "The selected batch model does not support this language"
        )
    # Parakeet detects language itself; sherpa exposes no language selector.
    return language


class BatchEngine:
    compute_device = "cpu"
    native_streaming = False

    def __init__(self, model, installer, timeout=600):
        if (
            model not in MODELS
            or installer.manifest["recommended_model"]["id"] != model
        ):
            raise LocalASRIntegrityError("Batch model and installation do not match")
        self.model, self.installer, self.timeout = model, installer, timeout
        self._state = threading.RLock()
        self._busy = threading.Lock()
        self._abort = None
        self._closed = False

    def prepare(self, *args):
        # Preparation must never install or download optional assets.
        return None

    def _check(self, abort, external):
        if abort.is_set() or (external is not None and external.is_set()):
            raise LocalASRCancelledError("Batch recognition was cancelled")

    def transcribe(
        self,
        audio_path,
        language="en",
        cancel_event=None,
        *,
        audio_bytes=None,
        **kwargs,
    ):
        if not self._busy.acquire(blocking=False):
            raise LocalASRSidecarError("Batch recognition is already active")
        abort = threading.Event()
        process = None
        temporary = None
        try:
            with self._state:
                if self._closed:
                    raise LocalASRSidecarError("Batch recognition engine is closed")
                self._abort = abort
            self._check(abort, cancel_event)
            language = _language(self.model, language)
            self.installer.verify(
                cancel_check=lambda: (
                    abort.is_set()
                    or (cancel_event is not None and cancel_event.is_set())
                )
            )
            self._check(abort, cancel_event)
            temporary = tempfile.TemporaryDirectory(prefix="clarify-batch-")
            directory = temporary.name
            wav_path = Path(directory) / "input.wav"
            try:
                with wave.open(
                    io.BytesIO(audio_bytes)
                    if audio_bytes is not None
                    else str(audio_path),
                    "rb",
                ) as source:
                    if (
                        source.getnchannels(),
                        source.getsampwidth(),
                        source.getframerate(),
                        source.getcomptype(),
                    ) != (1, 2, 16000, "NONE"):
                        raise LocalASRSidecarError(
                            "Recognition requires PCM16 mono 16 kHz"
                        )
                    count = source.getnframes()
                    if count <= 0 or count > MAX_SAMPLES:
                        raise LocalASRSidecarError(
                            "Batch audio must be between one sample and thirty minutes"
                        )
                    pcm = source.readframes(count)
                    if len(pcm) != count * 2:
                        raise LocalASRSidecarError("Batch WAV data is incomplete")
                with wave.open(str(wav_path), "wb") as destination:
                    destination.setparams(
                        (1, 2, 16000, count, "NONE", "not compressed")
                    )
                    destination.writeframes(pcm)
            except (OSError, EOFError, wave.Error) as error:
                raise LocalASRSidecarError(
                    "Cannot read batch recognition audio"
                ) from error
            self._check(abort, cancel_event)
            result_path = Path(directory) / "result.json"
            log_path = Path(directory) / "native.log"
            with result_path.open("wb") as output, log_path.open("wb") as errors:
                if self.model == "parakeet-v3-int8":
                    # Narrow-argv Windows CLIs cannot open arbitrary Unicode paths.
                    # Stage links under a Unicode cwd passed through CreateProcessW;
                    # every model/audio argument itself stays ASCII.
                    self._stage_sherpa_models(Path(directory), abort, cancel_event)
                    command = [
                        str(self.installer.executable_path),
                        "--encoder=encoder.int8.onnx",
                        "--decoder=decoder.int8.onnx",
                        "--joiner=joiner.int8.onnx",
                        "--tokens=tokens.txt",
                        "--model-type=nemo_transducer",
                        "--provider=cpu",
                        "--num-threads=3",
                        "input.wav",
                    ]
                    environment = os.environ.copy()
                    runtime_lib = str(
                        self.installer.executable_path.parent.parent / "lib"
                    )
                    environment["LD_LIBRARY_PATH"] = runtime_lib
                    process = subprocess.Popen(
                        command,
                        stdout=output,
                        stderr=errors,
                        stdin=subprocess.DEVNULL,
                        env=environment,
                        cwd=directory,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                else:
                    candidate = multiprocessing.get_context("spawn").Process(
                        target=_granite_worker,
                        args=(
                            str(self.installer.executable_path),
                            str(self.installer.model_path),
                            str(wav_path),
                            language,
                            str(result_path),
                        ),
                        daemon=True,
                    )
                    candidate.start()
                    process = candidate
                deadline = time.monotonic() + self.timeout
                while self._running(process):
                    self._check(abort, cancel_event)
                    if time.monotonic() >= deadline:
                        raise LocalASRSidecarError("Batch recognition timed out")
                    if (
                        max(result_path.stat().st_size, log_path.stat().st_size)
                        > MAX_OUTPUT
                    ):
                        raise LocalASRSidecarError(
                            "Batch runtime output exceeded its limit"
                        )
                    abort.wait(0.05)
            self._check(abort, cancel_event)
            code = (
                process.returncode
                if isinstance(process, subprocess.Popen)
                else process.exitcode
            )
            if code:
                raise LocalASRSidecarError(f"Batch runtime failed ({code})")
            if max(result_path.stat().st_size, log_path.stat().st_size) > MAX_OUTPUT:
                raise LocalASRSidecarError("Batch runtime output exceeded its limit")
            try:
                if self.model == "parakeet-v3-int8":
                    # The pinned CLI emits one JSON line after its ASCII filename.
                    # Diagnostics before/after it can use a Windows code page.
                    raw = log_path.read_bytes().replace(b"\r\n", b"\n")
                    line = raw.rsplit(b"input.wav\n", 1)[1].lstrip().split(b"\n", 1)[0]
                    payload = json.loads(line)
                else:
                    payload = json.loads(result_path.read_bytes())
                if "error" in payload:
                    raise LocalASRSidecarError(payload["error"])
                text = payload["text"]
                if not isinstance(text, str):
                    raise ValueError("Invalid text")
            except (ValueError, KeyError, TypeError, IndexError) as error:
                raise LocalASRSidecarError("Invalid batch runtime result") from error
            self._check(abort, cancel_event)
            return text
        except OSError as error:
            raise LocalASRSidecarError(
                "Cannot start batch recognition runtime"
            ) from error
        finally:
            try:
                if process is not None:
                    self._stop_process(process)
            finally:
                try:
                    if temporary is not None:
                        temporary.cleanup()
                finally:
                    with self._state:
                        self._abort = None
                    self._busy.release()

    def _stage_sherpa_models(self, directory, abort, external):
        for name in (
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
            "tokens.txt",
        ):
            self._check(abort, external)
            source = self.installer.model_path.parent / name
            destination = directory / name
            try:
                os.link(source, destination)
            except OSError:
                # Different volumes or filesystems can require a cancellable copy.
                with source.open("rb") as reader, destination.open("xb") as writer:
                    while chunk := reader.read(1024 * 1024):
                        self._check(abort, external)
                        writer.write(chunk)

    @staticmethod
    def _stop_process(process):
        if BatchEngine._running(process):
            process.terminate()
        if isinstance(process, subprocess.Popen):
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        else:
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()

    @staticmethod
    def _running(process):
        return (
            process.poll() is None
            if isinstance(process, subprocess.Popen)
            else process.is_alive()
        )

    def cancel(self):
        with self._state:
            if self._abort is not None:
                self._abort.set()

    def shutdown(self):
        with self._state:
            self._closed = True
            self.cancel()
        with self._busy:
            pass

    stop = shutdown


def create_engine(model, installer):
    return BatchEngine(model, installer)
