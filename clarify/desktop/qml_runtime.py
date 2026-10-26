"""UI-free runtime composition for the Qt Quick frontend.

The QML process owns the desktop surface; this module owns only the concrete
adapters required by :mod:`workflows`.  It deliberately does not import the
legacy frontend or any Tk/CustomTkinter module.
"""

from __future__ import annotations

import math
import io
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from transcription_performance import safe_timings
from pathlib import Path
from typing import Any, BinaryIO, Callable
from clarify_account import AccountService, AccountDictionaryRepository
from account_history import AccountHistory
from cloud_defaults import DEFAULT_CLOUD_URL
from experimental_audio_history import archive_audio, prune_audio_history

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Qt, Signal, Slot
from workflow_provider import (
    WorkflowProviderService as WorkflowProviderService,
    FAITHFUL_REWRITE_INSTRUCTION as FAITHFUL_REWRITE_INSTRUCTION,
    TRANSFORMATION_BOUNDARY_INSTRUCTION as TRANSFORMATION_BOUNDARY_INSTRUCTION,
    DICTATION_EDIT_INSTRUCTION as DICTATION_EDIT_INSTRUCTION,
    PROMPT_INSTRUCTION as PROMPT_INSTRUCTION,
    TRANSCRIPT_REWRITE_INSTRUCTION as TRANSCRIPT_REWRITE_INSTRUCTION,
    SELECTED_TEXT_REWRITE_INSTRUCTION as SELECTED_TEXT_REWRITE_INSTRUCTION,
    SELECTED_TEXT_TRANSLATION_INSTRUCTION as SELECTED_TEXT_TRANSLATION_INSTRUCTION,
    TRANSCRIPTION_INSTRUCTION as TRANSCRIPTION_INSTRUCTION,
    LANGUAGE_NAMES as LANGUAGE_NAMES,
    _language_display_name as _language_display_name,
    _workflow_instruction as _workflow_instruction,
    _is_exact_duplicate_removal as _is_exact_duplicate_removal,
)


_SOUNDDEVICE_UNLOADED = object()
_sounddevice: Any = _SOUNDDEVICE_UNLOADED
_sounddevice_lock = threading.Lock()


def _load_sounddevice() -> Any:
    """Initialize PortAudio once, on an inventory/test/meter worker.

    Keep ``_sounddevice`` replaceable with an injected backend or ``None``.
    Cache an unavailable backend as well, so concurrent callers do not retry
    native initialization. Neither module import nor recorder construction
    calls this boundary.
    """

    global _sounddevice
    if _sounddevice is _SOUNDDEVICE_UNLOADED:
        with _sounddevice_lock:
            if _sounddevice is _SOUNDDEVICE_UNLOADED:
                try:
                    import sounddevice
                except (ImportError, OSError):
                    _sounddevice = None
                else:
                    _sounddevice = sounddevice
    return _sounddevice


try:
    from audio_file_batch import (
        AudioFileBatchService,
        FileTranscriptionSelection,
        SoxAudioConverter,
    )
    from dictionary_snippets import (
        DictionarySnippetService,
        LocalDictionarySnippetsRepository,
    )
    from history_store import HistoryRecord, HistoryStore, HistoryStoreError
    from provider_registry import PROVIDER_REGISTRY
    from provider_http import CancellationToken
    from provider_types import (
        ProviderCapability,
        ProviderConnection,
    )
    from local_asr import PROVIDER_ID as LOCAL_ASR_PROVIDER_ID
    from microphone_controls import (
        MicrophoneInventory,
        MicrophoneSelectionState,
        RecordingBoundaryPolicy,
        RecordingBoundaryReason,
        RecordingControls,
        SoundDeviceMicrophoneInventory,
    )
    from repositories import (
        ApplicationRepositories,
        LocalConfigRepository,
        LocalUsageStatsRepository,
        environment_defaults,
    )
    from workflow_config import WorkflowScope
    from workflows import (
        MicrophoneUnavailableError,
        NoUsableAudioError,
        RecordingSessionGateway,
        RecordingSnapshot,
        SelectionDisposition,
        WorkflowKind,
        WorkflowPhase,
        WorkflowService,
    )
except ImportError:  # PyInstaller analyzes this file as a standalone entry point.
    from ...audio_file_batch import (  # type: ignore[no-redef]
        AudioFileBatchService,
        FileTranscriptionSelection,
        SoxAudioConverter,
    )
    from ...dictionary_snippets import (  # type: ignore[no-redef]
        DictionarySnippetService,
        LocalDictionarySnippetsRepository,
    )
    from ...history_store import HistoryRecord, HistoryStore, HistoryStoreError  # type: ignore[no-redef]
    from ...provider_registry import PROVIDER_REGISTRY  # type: ignore[no-redef]
    from ...provider_http import CancellationToken  # type: ignore[no-redef]
    from ...local_asr import PROVIDER_ID as LOCAL_ASR_PROVIDER_ID  # type: ignore[no-redef]
    from ...microphone_controls import (  # type: ignore[no-redef]
        MicrophoneInventory,
        MicrophoneSelectionState,
        RecordingBoundaryPolicy,
        RecordingBoundaryReason,
        RecordingControls,
        SoundDeviceMicrophoneInventory,
    )
    from ...provider_types import (  # type: ignore[no-redef]
        ProviderCapability,
        ProviderConnection,
    )
    from ...repositories import (  # type: ignore[no-redef]
        ApplicationRepositories,
        LocalConfigRepository,
        LocalUsageStatsRepository,
        environment_defaults,
    )
    from ...workflow_config import WorkflowScope  # type: ignore[no-redef]
    from ...workflows import (  # type: ignore[no-redef]
        MicrophoneUnavailableError,
        NoUsableAudioError,
        RecordingSessionGateway,
        RecordingSnapshot,
        SelectionDisposition,
        WorkflowKind,
        WorkflowPhase,
        WorkflowService,
    )

try:
    from .qml_clipboard import QmlClipboardGateway
except ImportError:  # PyInstaller analyzes this module as top-level source.
    from qml_clipboard import QmlClipboardGateway


class QtRuntimeError(RuntimeError):
    """The real Qt runtime cannot start with the current local installation."""


class QtWorkflowScheduler(QObject):
    """Run workflow callbacks on Qt's GUI thread and workers off it."""

    _callback_ready = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._callback_ready.connect(
            self._run_callback,
            Qt.ConnectionType.QueuedConnection,
        )
        self._worker_condition = threading.Condition()
        self._accepting_workers = True
        self._dispatch_workers: set[threading.Thread] = set()
        self._background_workers: set[threading.Thread] = set()

    @Slot(object)
    def _run_callback(self, callback: Callable[[], None]) -> None:
        callback()

    def call_soon(self, callback: Callable[[], None]) -> None:
        self._callback_ready.emit(callback)

    def run_in_background(self, callback: Callable[[], None]) -> None:
        self._start_worker(
            callback,
            self._background_workers,
            "ClarifyQmlWorkflow",
        )

    def run_dispatch(self, callback: Callable[[], None]) -> None:
        """Submit a QML command while the application accepts new work."""

        self._start_worker(
            callback,
            self._dispatch_workers,
            "ClarifyQmlDispatch",
        )

    def begin_shutdown(self) -> None:
        """Reject queued QML/background callbacks before teardown begins."""

        with self._worker_condition:
            self._accepting_workers = False

    def wait_for_dispatches(self, timeout_seconds: float) -> bool:
        """Drain command dispatch workers within the shutdown budget."""

        return self._wait_for_workers(self._dispatch_workers, timeout_seconds)

    def wait_for_background(self, timeout_seconds: float) -> bool:
        """Drain already-running workflow workers within the shutdown budget."""

        return self._wait_for_workers(self._background_workers, timeout_seconds)

    def _start_worker(
        self,
        callback: Callable[[], None],
        workers: set[threading.Thread],
        name: str,
    ) -> None:
        def run() -> None:
            try:
                with self._worker_condition:
                    if not self._accepting_workers:
                        return
                callback()
            finally:
                with self._worker_condition:
                    workers.discard(threading.current_thread())
                    self._worker_condition.notify_all()

        with self._worker_condition:
            if not self._accepting_workers:
                return
            worker = threading.Thread(target=run, name=name, daemon=True)
            workers.add(worker)
        worker.start()

    def _wait_for_workers(
        self,
        workers: set[threading.Thread],
        timeout_seconds: float,
    ) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._worker_condition:
            while workers:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._worker_condition.wait(timeout=remaining)
        return True

    def run_recording(
        self,
        recording: RecordingSessionGateway,
        callback: Callable[[], None],
    ) -> None:
        def run() -> None:
            try:
                callback()
            finally:
                recording.detach_worker(threading.current_thread())

        worker = threading.Thread(
            target=run,
            name="ClarifyQmlRecording",
            daemon=True,
        )
        attach = getattr(
            recording,
            "attach_workflow_worker",
            recording.attach_worker,
        )
        attach(worker)
        worker.start()


def _data_directory() -> Path:
    configured = os.environ.get("CLARIFY_DATA_DIR", "").strip()
    if configured:
        path = Path(configured)
    elif platform.system() == "Windows":
        path = Path(os.environ.get("APPDATA", Path.home())) / "Clarify"
    else:
        path = Path.home() / ".clarify"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_runtime_repositories() -> ApplicationRepositories:
    data_dir = _data_directory()
    return ApplicationRepositories(
        config=LocalConfigRepository(
            data_dir / "config.json",
            defaults=environment_defaults(),
        ),
        usage_stats=LocalUsageStatsRepository(data_dir / "usage_stats.json"),
    )


class QtWorkflowConfig:
    """Read the typed route/configuration boundary for one operation."""

    def __init__(self, repositories: ApplicationRepositories, account=None) -> None:
        self.repositories = repositories
        self.account = account

    def current(self):
        return self.repositories.config.load()

    def workflow(self, scope: WorkflowScope):
        return self.current().workflow(scope)

    def dictation_writing_style(self, executable):
        return self.current().application_writing_styles.resolve(executable)

    def recording_usage_context(self, mode: str) -> dict[str, Any]:
        if self.account is not None and self.account.hosted:
            return {
                "provider": "clarify",
                "model": "whisper-large-v3-turbo",
                "mode": str(mode),
            }
        route = self.current().workflow(WorkflowScope.TRANSCRIPTION)
        return {
            "provider": route.provider_id,
            "model": route.model_id,
            "mode": str(mode),
        }


class QtAudioFileGateway:
    """Use the dictation refinement pipeline for imported audio as well."""

    def __init__(self, provider):
        self.provider = provider
        self._account_lock = threading.Lock()

    def transcribe(self, request, selection, cancel_token):
        account = getattr(self.provider, "account", None)
        managed = account is not None and getattr(account, "managed", False) is True
        if managed:
            # One hosted operation per account; keep guest batch concurrency.
            while not self._account_lock.acquire(timeout=0.05):
                cancel_token.raise_if_cancelled()
        try:
            return self.provider.transcribe(
                RecordingSnapshot(
                    request.audio_path, request.audio_bytes, cancel_token
                ),
                "prompt",
                selection.language,
                selection=selection,
            )
        finally:
            if managed:
                self._account_lock.release()


class QtProviderGateway(WorkflowProviderService):
    """Compose shared provider policy with Qt-owned recording preparation."""

    @property
    def registry(self):
        # Resolve the desktop dependency here, preserving its existing seam.
        return self._registry if self._registry is not None else PROVIDER_REGISTRY

    def prepare_dictation(self, recording) -> None:
        """Best-effort local preparation; never contact a cloud provider."""
        try:
            if self.account is not None and self.account.managed:
                return
            with recording._lock:
                if recording.preparation_done.is_set():
                    return
                preparation_token = recording.provider_cancel_token
            route = self._route(WorkflowScope.TRANSCRIPTION)
            if route.provider_id != LOCAL_ASR_PROVIDER_ID:
                return
            adapter = PROVIDER_REGISTRY.adapter(LOCAL_ASR_PROVIDER_ID)
            backend = adapter.select_backend(
                route.model_id, self.config.current().local_asr_device
            )
            if self.config.current().local_asr_streaming and getattr(
                backend, "compute_device", "cpu"
            ).startswith("cuda:"):
                from local_asr_streaming import PauseStream

                language = (
                    str(getattr(recording, "transcription_language", "auto") or "auto")
                    .lower()
                    .split("-")[0]
                )
                stream = PauseStream(
                    recording.audio_path,
                    backend,
                    route.model_id,
                    language,
                    preparation_token,
                    initial_prompt=self.dictionary_service.vocabulary_prompt(),
                )
                with recording._lock:
                    if not recording.preparation_done.is_set():
                        recording.local_stream = stream
                        recording.attach_worker(stream.worker)
                        stream.on_finished = lambda: recording.detach_worker(
                            stream.worker
                        )
                        stream.start()
            backend.prepare(recording.preparation_done, preparation_token)
        except Exception:
            # The real request owns user-visible errors and explicit retries.
            return


SOX_WAVE_AUDIO_NAME_MAX_CHARS = 31


def _sox_microphone_name_key(name: str, system: str) -> str:
    """Normalize a microphone name using the active SoX device rules."""

    normalized = name.casefold()
    if system == "Windows" and not normalized.isdigit():
        return normalized[:SOX_WAVE_AUDIO_NAME_MAX_CHARS]
    return normalized


def _sox_microphone_name_is_unambiguous(
    inventory: Any,
    device: Any,
    system: str,
) -> bool:
    """Avoid WaveAudio's 31-character prefix collision for selected inputs."""

    device_key = _sox_microphone_name_key(device.name, system)
    matching = sum(
        _sox_microphone_name_key(candidate.name, system) == device_key
        for candidate in inventory.available_devices
    )
    return matching == 1


def _open_readiness_file(path: Path) -> BinaryIO:
    """Do not let an optional Windows reader prevent session-owned deletion.

    Python's normal Windows read handle does not share delete access. A cancel
    must be able to unlink this WAV while the worker finishes its bounded read.
    Windows completes a pending deletion when the worker closes the handle.
    """

    if os.name != "nt":
        return path.open("rb")

    def opener(name: str, _flags: int) -> int:
        import ctypes
        from ctypes import wintypes
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        generic_read, share_read_write_delete = 0x80000000, 0x1 | 0x2 | 0x4
        open_existing, normal_attributes = 3, 0x80
        handle = create_file(
            name,
            generic_read,
            share_read_write_delete,
            None,
            open_existing,
            normal_attributes,
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            # The CRT descriptor owns the Win32 handle after this succeeds;
            # io.open then owns the descriptor and closes it on context exit.
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            close_handle(handle)
            raise

    return io.open(path, "rb", opener=opener)


@dataclass(eq=False)
class _RecorderCapture:
    """Identity and worker signals for one authoritative SoX capture."""

    path: Path
    cancel_event: threading.Event
    stopped: threading.Event = field(default_factory=threading.Event)
    ready: threading.Event = field(default_factory=threading.Event)
    meter_ready: threading.Event = field(default_factory=threading.Event)
    meter_finished: threading.Event = field(default_factory=threading.Event)
    process: Any = None
    meter_device: Any = None
    started: bool = False


class QtRecorder:
    """Minimal SoX owner for the Qt recording session."""

    def __init__(
        self,
        config: QtWorkflowConfig | None = None,
        microphone_inventory_source: Any | None = None,
    ) -> None:
        roots: list[Path] = []
        bundled_root = getattr(sys, "_MEIPASS", None)
        if bundled_root:
            roots.append(Path(bundled_root))
        if getattr(sys, "frozen", False):
            roots.append(Path(sys.executable).resolve().parent)
        roots.append(Path(__file__).resolve().parents[2])
        sox_name = "sox.exe" if platform.system() == "Windows" else "sox"
        bundled = next(
            (
                root / "extra" / "sox-14.4.2" / sox_name
                for root in roots
                if (root / "extra" / "sox-14.4.2" / sox_name).is_file()
            ),
            None,
        )
        self.sox = str(bundled or shutil.which("sox") or "")
        self.config = config
        self.microphone_inventory_source = microphone_inventory_source
        self.process: subprocess.Popen[bytes] | None = None
        self.mic_stream: Any | None = None
        self.mic_level = 0.0
        self._capture: _RecorderCapture | None = None
        self._readiness_worker: threading.Thread | None = None
        self._meter_worker: threading.Thread | None = None
        self._lock = threading.RLock()

    @property
    def capture_active(self) -> bool:
        """Read cached PCM readiness without locks, process calls, or file I/O."""
        capture = self._capture
        return bool(
            capture is not None
            and capture.ready.is_set()
            and not capture.stopped.is_set()
            and not capture.cancel_event.is_set()
        )

    @staticmethod
    def _has_pcm_frames(path: Path) -> bool:
        try:
            with _open_readiness_file(path) as source:
                header = source.read(4096)
            if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                return False
            offset = 12
            while offset + 8 <= len(header):
                size = int.from_bytes(header[offset + 4 : offset + 8], "little")
                if header[offset : offset + 4] == b"data":
                    return len(header) >= offset + 10
                offset += 8 + size + (size % 2)
        except OSError:
            pass
        return False

    def _monitor_capture(self) -> None:
        while True:
            with self._lock:
                capture = self._capture
                if capture is None:
                    self._readiness_worker = None
                    return
            process = capture.process
            active = process is not None and process.poll() is None
            ready = active and (
                capture.ready.is_set() or self._has_pcm_frames(capture.path)
            )
            with self._lock:
                if self._capture is capture and not capture.stopped.is_set():
                    if ready:
                        capture.ready.set()
                    else:
                        capture.ready.clear()
            capture.stopped.wait(0.016)

    def _microphone_input_name(self, system: str, capture: _RecorderCapture) -> str:
        selected_id = None
        if self.config is not None:
            selected_id = self.config.current().microphone.selected_id
        if not selected_id:
            return "default"
        inventory = self.microphone_inventory()
        selection = inventory.resolve(selected_id)
        if not selection.can_record:
            raise MicrophoneUnavailableError("The configured microphone is unavailable")
        if selection.state is not MicrophoneSelectionState.SELECTED:
            return "default"
        device = selection.device
        if device is None or not _sox_microphone_name_is_unambiguous(
            inventory, device, system
        ):
            raise MicrophoneUnavailableError(
                "Selected microphone has no unambiguous backend name"
            )
        if system not in {"Windows", "Darwin"}:
            is_default = device.is_default or inventory.default_id == device.stable_id
            if not is_default:
                raise MicrophoneUnavailableError(
                    "Explicit microphone selection is unavailable with SoX PulseAudio"
                )
            return "default"
        capture.meter_device = (
            device.backend_index if device.backend_index is not None else device.name
        )
        return device.name

    @staticmethod
    def _close_level_stream(stream: Any | None) -> None:
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def _start_level_meter(self, capture: _RecorderCapture) -> None:
        """Own one optional stream from open through asynchronous close."""

        if capture.stopped.is_set() or capture.cancel_event.is_set():
            return
        backend = _load_sounddevice()
        if backend is None or capture.stopped.is_set() or capture.cancel_event.is_set():
            return

        def callback(indata, _frames, _time_info, _status):
            raw_samples = memoryview(indata)
            samples = (
                raw_samples
                if raw_samples.format in {"h", "<h", "=h", "@h"}
                and raw_samples.ndim == 1
                else memoryview(raw_samples.tobytes()).cast("h")
            )
            if not samples:
                return
            mean_square = sum(sample * sample for sample in samples) / len(samples)
            level = min(
                1.0,
                math.sqrt(mean_square) / 32768.0 * 16,
            )
            with self._lock:
                if (
                    self._capture is capture
                    and not capture.stopped.is_set()
                    and not capture.cancel_event.is_set()
                ):
                    self.mic_level = level

        stream = None
        try:
            stream_options: dict[str, Any] = {
                "channels": 1,
                "samplerate": 16000,
                "blocksize": 256,
                "dtype": "int16",
                "callback": callback,
            }
            if capture.meter_device is not None:
                stream_options["device"] = capture.meter_device
            stream = backend.RawInputStream(**stream_options)
            if capture.stopped.is_set() or capture.cancel_event.is_set():
                return
            stream.start()
            with self._lock:
                if (
                    self._capture is capture
                    and not capture.stopped.is_set()
                    and not capture.cancel_event.is_set()
                    and self.mic_stream is None
                ):
                    self.mic_stream = stream
                    capture.meter_ready.set()
            if capture.meter_ready.is_set():
                while not capture.stopped.wait(0.05):
                    if (
                        capture.cancel_event.is_set()
                        or capture.process.poll() is not None
                    ):
                        break
        except Exception:
            # The meter is presentation-only; SoX remains authoritative.
            pass
        finally:
            with self._lock:
                if self.mic_stream is stream:
                    self.mic_stream = None
                if self._capture is capture:
                    self.mic_level = 0.0
            self._close_level_stream(stream)

    def _run_level_meter(self, capture: _RecorderCapture) -> None:
        """Serialize native stream work, including across rapid restarts."""
        while True:
            try:
                self._start_level_meter(capture)
            except Exception:
                # Optional backend initialization must not retain a dead owner.
                pass
            finally:
                capture.meter_finished.set()
            with self._lock:
                following = self._capture
                if following is None or following is capture or not following.started:
                    self._meter_worker = None
                    return
                capture = following

    def microphone_inventory(self) -> Any:
        """Return the same safe inventory boundary used by recording.

        Settings must be able to recover a stale saved identity without
        reaching into PortAudio directly.  Keep enumeration owned by the
        recorder's injected source so the QML surface and a recording session
        observe the same backend snapshot contract.
        """

        source = self.microphone_inventory_source
        if source is None:
            backend = _load_sounddevice()
            if backend is not None:
                source = SoundDeviceMicrophoneInventory(backend)
        if source is None:
            return MicrophoneInventory.unavailable("portaudio_unavailable")
        return source.snapshot()

    @staticmethod
    def supports_explicit_microphone_selection(system: str | None = None) -> bool:
        """Return whether the active SoX driver can honor an input name."""

        return (system or platform.system()) in {"Windows", "Darwin"}

    def selectable_microphone_devices(self, inventory: Any) -> tuple[Any, ...]:
        """Expose only endpoint names the active SoX route can disambiguate."""

        if not self.supports_explicit_microphone_selection():
            return ()
        return tuple(
            device
            for device in inventory.available_devices
            if _sox_microphone_name_is_unambiguous(inventory, device, platform.system())
        )

    def test_microphone(
        self,
        selection: Any,
        inventory: Any,
        *,
        on_level: Callable[[float], None] | None = None,
        cancel_event: threading.Event | None = None,
        duration: float = 0.25,
    ) -> float:
        """Measure live input locally. Retain levels only, never audio buffers."""

        backend = _load_sounddevice()
        if backend is None:
            raise QtRuntimeError("Input test unavailable without PortAudio")
        if selection is None or not selection.can_record:
            raise MicrophoneUnavailableError("No safe microphone to test")

        system = platform.system()
        stream_device = None
        if selection.state is MicrophoneSelectionState.SELECTED:
            device = selection.device
            if device is None:
                raise MicrophoneUnavailableError("No safe microphone to test")
            if not self.supports_explicit_microphone_selection(system):
                is_default = (
                    device.is_default or inventory.default_id == device.stable_id
                )
                if not is_default:
                    raise MicrophoneUnavailableError(
                        "Explicit microphone selection is unavailable with SoX PulseAudio"
                    )
            elif device not in self.selectable_microphone_devices(inventory):
                raise MicrophoneUnavailableError(
                    "Selected microphone has no unambiguous backend name"
                )
            else:
                stream_device = (
                    device.backend_index
                    if device.backend_index is not None
                    else device.name
                )

        peak = 0.0
        stream = None
        last_level_at = float("-inf")

        def callback(indata, _frames, _time_info, _status):
            nonlocal peak, last_level_at
            if cancel_event is not None and cancel_event.is_set():
                return
            raw_samples = memoryview(indata)
            samples = (
                raw_samples
                if raw_samples.format in {"h", "<h", "=h", "@h"}
                and raw_samples.ndim == 1
                else memoryview(raw_samples.tobytes()).cast("h")
            )
            if samples:
                rms = math.sqrt(
                    sum(sample * sample for sample in samples) / len(samples)
                )
                level = min(1.0, rms / 32768.0 * 16)
                peak = max(peak, level)
                now = time.monotonic()
                if on_level is not None and now - last_level_at >= 0.04:
                    last_level_at = now
                    on_level(level)

        try:
            kwargs = {
                "channels": 1,
                "samplerate": 16000,
                "blocksize": 256,
                "dtype": "int16",
                "callback": callback,
            }
            if stream_device is not None:
                kwargs["device"] = stream_device
            stream = backend.RawInputStream(**kwargs)
            if cancel_event is not None and cancel_event.is_set():
                return peak
            stream.start()
            if cancel_event is None:
                time.sleep(min(30.0, max(0.0, duration)))
            else:
                deadline = time.monotonic() + min(30.0, max(0.0, duration))
                while not cancel_event.wait(0.05):
                    if not getattr(stream, "active", True):
                        raise MicrophoneUnavailableError(
                            "Microphone disconnected or input stopped"
                        )
                    if time.monotonic() >= deadline:
                        break
        finally:
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                finally:
                    stream.close()
        return peak

    def start(self, path: Path, cancel_event: threading.Event) -> None:
        capture = _RecorderCapture(path, cancel_event)
        with self._lock:
            if self._capture is not None:
                raise QtRuntimeError("A recording is already active")
            self._capture = capture
        try:
            self._start_capture(capture)
        except Exception:
            self._stop_capture(capture)
            raise

    def _start_capture(self, capture: _RecorderCapture) -> None:
        if not self.sox:
            raise QtRuntimeError("SoX was not found in the Clarify runtime")
        if capture.cancel_event.is_set() or capture.stopped.is_set():
            raise RuntimeError("Recording cancelled before startup")
        system = platform.system()
        microphone_input_name = self._microphone_input_name(system, capture)
        if system == "Windows":
            source = ["-t", "waveaudio", microphone_input_name]
        elif system == "Darwin":
            source = ["-t", "coreaudio", microphone_input_name]
        else:
            source = ["-t", "pulseaudio", microphone_input_name]
        args = [
            self.sox,
            *source,
            "-r",
            "16000",
            "-c",
            "1",
            "-b",
            "16",
            "-e",
            "signed-integer",
            str(capture.path),
        ]
        kwargs: dict[str, Any] = {"stderr": subprocess.DEVNULL}
        if system == "Windows":
            kwargs["creationflags"] = 0x08000000
            kwargs["cwd"] = str(Path(self.sox).parent)
        if capture.cancel_event.is_set() or capture.stopped.is_set():
            raise RuntimeError("Recording cancelled before startup")
        # Launch may wait on native Windows audio. Retain local ownership until
        # publication, so stop/restart cannot inherit a late process.
        process = subprocess.Popen(args, **kwargs)
        with self._lock:
            published = (
                self._capture is capture
                and not capture.stopped.is_set()
                and not capture.cancel_event.is_set()
            )
            if published:
                capture.process = process
                self.process = process
        if not published:
            self._terminate_process(process)
            raise RuntimeError("Recording cancelled during startup")
        if capture.stopped.wait(0.18) or capture.cancel_event.is_set():
            raise RuntimeError("Recording cancelled during startup")
        if process.poll() is not None:
            raise MicrophoneUnavailableError("No active microphone")
        with self._lock:
            if self._capture is not capture or capture.stopped.is_set():
                raise RuntimeError("Recording cancelled during startup")
            capture.started = True
            # At most one readiness reader and one native meter owner per
            # recorder. A slow old open/close cannot create unbounded workers.
            if self._readiness_worker is None:
                self._readiness_worker = threading.Thread(
                    target=self._monitor_capture,
                    name="ClarifyCaptureReadiness",
                    daemon=True,
                )
                self._readiness_worker.start()
            if self._meter_worker is None:
                self._meter_worker = threading.Thread(
                    target=self._run_level_meter,
                    args=(capture,),
                    name="ClarifyCaptureMeter",
                    daemon=True,
                )
                self._meter_worker.start()

    def stop(self) -> None:
        with self._lock:
            capture = self._capture
        if capture is not None:
            self._stop_capture(capture)

    def _stop_capture(self, capture: _RecorderCapture) -> None:
        with self._lock:
            capture.stopped.set()
            capture.ready.clear()
            if self._capture is not capture:
                return
            self._capture = None
            # The meter worker retains sole close ownership. Do not wait for
            # optional native open/start/stop/close during audio finalization.
            self.mic_stream = None
            self.mic_level = 0.0
            process = capture.process
            self.process = None
        self._terminate_process(process)

    @staticmethod
    def _terminate_process(process: Any) -> None:
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    def cancel(self) -> None:
        self.stop()


class QtRecordingSession(RecordingSessionGateway):
    """Own one temporary recording until the provider has its snapshot."""

    def __init__(
        self,
        recorder: QtRecorder,
        config: QtWorkflowConfig | None = None,
    ) -> None:
        self.recorder = recorder
        self.config = (
            config if config is not None else getattr(recorder, "config", None)
        )
        descriptor, raw_path = tempfile.mkstemp(
            prefix="clarify-recording-",
            suffix=".wav",
            dir=str(_data_directory()),
        )
        os.close(descriptor)
        self.audio_path = Path(raw_path)
        self.audio_path.unlink(missing_ok=True)
        self.cancel_event = threading.Event()
        self.provider_cancel_token = CancellationToken()
        self.start_finished = threading.Event()
        self.shutdown_complete = threading.Event()
        self._shutdown_callbacks: list[Callable[[], None]] = []
        self._workers: set[threading.Thread] = set()
        self._lock = threading.RLock()
        self._started = False
        self._started_at: float | None = None
        self._experimental_audio_saved = False
        self._terminal = False
        self._error: Exception | None = None
        self._boundary_callback: Callable[[Any], None] | None = None
        self._boundary_stop = threading.Event()
        self.preparation_done = threading.Event()
        self._boundary_worker: threading.Thread | None = None
        self._boundary_policy: RecordingBoundaryPolicy | None = None
        self.boundary_reason = RecordingBoundaryReason.NONE

    def set_boundary_callback(self, callback: Callable[[Any], None] | None) -> None:
        """Register the workflow stop callback for a hard duration boundary."""

        if callback is not None and not callable(callback):
            raise TypeError("recording boundary callback must be callable")
        with self._lock:
            self._boundary_callback = callback

    def _recording_controls(self) -> RecordingControls:
        config = self.config
        if config is None:
            return RecordingControls.defaults()
        current = config.current()
        controls = getattr(current, "recording_controls", None)
        if isinstance(controls, RecordingControls):
            return controls
        return RecordingControls.from_mapping(controls)

    def _prepare_boundary_policy(self) -> RecordingControls:
        controls = self._recording_controls()
        policy = RecordingBoundaryPolicy(controls)
        policy.start(time.monotonic())
        with self._lock:
            self._boundary_policy = policy
            self.boundary_reason = RecordingBoundaryReason.NONE
        return controls

    def _start_boundary_monitor(self, controls: RecordingControls) -> None:
        with self._lock:
            policy = self._boundary_policy
            callback = self._boundary_callback
        if policy is None:
            return
        if controls.max_duration_seconds is None or callback is None:
            return

        self._boundary_stop.clear()

        def monitor() -> None:
            try:
                while not self._boundary_stop.wait(0.1):
                    decision = policy.observe_duration(time.monotonic())
                    if not decision.should_stop:
                        continue
                    with self._lock:
                        callback = self._boundary_callback
                        self.boundary_reason = decision.reason
                    if not self._boundary_stop.is_set() and callback is not None:
                        callback(decision.reason)
                    return
            except Exception:
                # The recording lifecycle remains authoritative if a clock or
                # policy callback is invalidated during shutdown.
                return
            finally:
                with self._lock:
                    if self._boundary_worker is threading.current_thread():
                        self._boundary_worker = None

        worker = threading.Thread(
            target=monitor,
            name="ClarifyQmlRecordingBoundary",
            daemon=True,
        )
        with self._lock:
            self._boundary_worker = worker
        worker.start()

    def _stop_boundary_monitor(self) -> None:
        self.preparation_done.set()
        self._boundary_stop.set()
        with self._lock:
            worker = self._boundary_worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1.0)
        with self._lock:
            if self._boundary_worker is worker:
                self._boundary_worker = None

    def attach_worker(self, worker: Any) -> None:
        with self._lock:
            self._workers.add(worker)

    attach_workflow_worker = attach_worker

    def detach_worker(self, worker: Any) -> None:
        callbacks = []
        with self._lock:
            self._workers.discard(worker)
            if self._terminal and not self._workers:
                self.shutdown_complete.set()
                callbacks, self._shutdown_callbacks = self._shutdown_callbacks, []
        for callback in callbacks:
            callback()

    def when_shutdown_complete(self, callback: Callable[[], None]) -> None:
        """Publish availability after the audio owner releases every worker."""
        with self._lock:
            if not self.shutdown_complete.is_set():
                self._shutdown_callbacks.append(callback)
                return
        callback()

    def start(self) -> None:
        try:
            controls = self._prepare_boundary_policy()
            self.recorder.start(self.audio_path, self.cancel_event)
            with self._lock:
                self._started = True
                self._started_at = time.monotonic()
            self._start_boundary_monitor(controls)
        except Exception as error:
            with self._lock:
                self._error = error
            if self.cancel_event.is_set():
                # A cancelled native launch can return after cancel's first
                # cleanup. The recorder has now terminated that late process.
                self._cleanup()
            raise
        finally:
            self.start_finished.set()

    def wait_until_started(self) -> None:
        self.start_finished.wait()
        if self._error is not None:
            raise self._error

    def stop_for_cancel(self) -> RecordingSnapshot:
        """Retain audio for Undo without waiting for speculative ASR results."""
        with self._lock:
            self.preparation_done.set()
            self.provider_cancel_token.cancel()
            # Undo is a new explicit request. It must not inherit cancellation
            # from speculative inference that was running during capture.
            self.provider_cancel_token = CancellationToken()
            stream = getattr(self, "local_stream", None)
        if stream is not None:
            stream.cancel()
        return self._snapshot(finalize_stream=False)

    def stop(self) -> RecordingSnapshot:
        return self._snapshot(finalize_stream=True)

    def _snapshot(self, *, finalize_stream: bool) -> RecordingSnapshot:
        self.wait_until_started()
        self._stop_boundary_monitor()
        self.recorder.stop()
        stopped_at = time.monotonic()
        try:
            audio_bytes = self.audio_path.read_bytes()
        except OSError as error:
            self.fail(error)
            raise NoUsableAudioError("Recording produced no audio") from error
        if len(audio_bytes) < 1000:
            self.fail(NoUsableAudioError("Recording produced no audio"))
            raise NoUsableAudioError("Recording produced no audio")
        with self._lock:
            started_at = self._started_at
        duration_seconds = (
            max(0.0, stopped_at - started_at) if started_at is not None else 0.0
        )
        if finalize_stream and not self._experimental_audio_saved:
            self._experimental_audio_saved = True
            try:
                if (
                    self.config is not None
                    and self.config.current().experimental_audio_history
                    and not self.cancel_event.is_set()
                    and not self.provider_cancel_token.cancelled
                ):
                    archive_audio(self.audio_path.parent, audio_bytes)
            except Exception:
                # Optional local benchmark fixtures cannot break dictation.
                pass
        return RecordingSnapshot(
            self.audio_path,
            audio_bytes,
            cancel_token=self.provider_cancel_token,
            duration_seconds=duration_seconds,
            pretranscribed=(
                self.local_stream.finish(audio_bytes)
                if finalize_stream and getattr(self, "local_stream", None) is not None
                else None
            ),
        )

    def cancel(self) -> None:
        self.cancel_event.set()
        self.provider_cancel_token.cancel()
        self._stop_boundary_monitor()
        self.recorder.cancel()
        self._cleanup()
        self._mark_terminal()

    def complete(self) -> bool:
        self._stop_boundary_monitor()
        self._cleanup()
        self._mark_terminal()
        return True

    def fail(self, error: Exception) -> None:
        with self._lock:
            self._error = error
        self._stop_boundary_monitor()
        self._cleanup()
        self._mark_terminal()

    def _cleanup(self) -> None:
        stream = getattr(self, "local_stream", None)
        if stream is not None:
            stream.cancel()
        self.audio_path.unlink(missing_ok=True)

    def _mark_terminal(self) -> None:
        callbacks = []
        with self._lock:
            self._terminal = True
            if not self._workers:
                self.shutdown_complete.set()
                callbacks, self._shutdown_callbacks = self._shutdown_callbacks, []
        for callback in callbacks:
            callback()


class QtRecordingAudioGateway:
    def __init__(
        self,
        recorder: QtRecorder,
        config: QtWorkflowConfig | None = None,
    ) -> None:
        self.recorder = recorder
        self.config = (
            config if config is not None else getattr(recorder, "config", None)
        )
        self._active: QtRecordingSession | None = None
        self._lock = threading.Lock()

    def microphone_available(self) -> bool | None:
        return bool(self.recorder.sox)

    def create_session(self) -> QtRecordingSession | None:
        with self._lock:
            account = getattr(self.config, "account", None)
            if account is not None and account.busy:
                return None
            if self._active is not None and not self._active.shutdown_complete.is_set():
                return None
            self._active = QtRecordingSession(self.recorder, self.config)
            return self._active

    def wait_for_shutdown(self, timeout_seconds: float) -> bool:
        """Wait for the active recording owner to release its workers."""

        with self._lock:
            active = self._active
        if active is None:
            return True
        return active.shutdown_complete.wait(timeout=max(0.0, float(timeout_seconds)))


class QtClipboardGateway(QmlClipboardGateway):
    """Runtime-named facade over the concrete QML clipboard transaction."""


_QT_AUDIO_COST_USD_PER_MINUTE = {
    ("openai", "whisper-1"): 0.006,
    ("openai", "gpt-4o-mini-transcribe"): 0.003,
    ("openai", "gpt-4o-transcribe"): 0.006,
    ("openai", "gpt-4o-transcribe-diarize"): 0.006,
    ("groq", "whisper-large-v3-turbo"): 0.04 / 60,
    ("groq", "whisper-large-v3"): 0.111 / 60,
    # Gemini audio is token-priced; this uses the same 32 audio tokens/sec
    # approximation as the production statistics implementation.
    ("gemini", "gemini-2.5-flash"): 1.00 * 32 * 60 / 1_000_000,
    ("gemini", "gemini-2.5-flash-lite"): 0.30 * 32 * 60 / 1_000_000,
}

_QT_TEXT_COST_USD_PER_MILLION_TOKENS = {
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("groq", "llama-3.3-70b-versatile"): (0.59, 0.79),
    ("gemini", "gemini-2.5-flash"): (0.30, 2.50),
    ("gemini", "gemini-2.5-flash-lite"): (0.10, 0.40),
}


def _qt_word_count(text: str) -> int:
    return len(str(text or "").split())


def _qt_estimated_text_cost(
    provider: str,
    model: str,
    input_characters: int,
    output_characters: int,
) -> tuple[float, bool]:
    rates = _QT_TEXT_COST_USD_PER_MILLION_TOKENS.get((provider, model))
    if rates is None:
        return 0.0, False
    input_tokens = max(0, input_characters) / 4
    output_tokens = max(0, output_characters) / 4
    return (
        (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000,
        True,
    )


def _build_qt_recording_usage_event(
    context: dict[str, Any],
    duration_seconds: float,
    result: str,
) -> dict[str, Any]:
    """Build the production usage event for a completed dictation."""

    context = dict(context or {})
    provider = str(context.get("provider", "") or "")
    model = str(context.get("model", "") or "")
    result = str(result or "")
    duration = max(0.0, float(duration_seconds))
    models = [{"provider": provider, "model": model, "purpose": "transcription"}]
    audio_rate = _QT_AUDIO_COST_USD_PER_MINUTE.get((provider, model))
    cost = 0.0 if audio_rate is None else audio_rate * duration / 60
    cost_complete = audio_rate is not None

    output_characters = len(result)
    refinement_provider = str(context.get("refinement_provider", "") or "")
    refinement_model = str(context.get("refinement_model", "") or "")
    if refinement_provider and refinement_model:
        models.append(
            {
                "provider": refinement_provider,
                "model": refinement_model,
                "purpose": "refinement",
            }
        )
        text_cost, text_complete = _qt_estimated_text_cost(
            refinement_provider,
            refinement_model,
            output_characters,
            output_characters,
        )
        cost += text_cost
        cost_complete = cost_complete and text_complete
    elif PROVIDER_REGISTRY.supports(provider, ProviderCapability.MULTIMODAL_AUDIO):
        text_cost, text_complete = _qt_estimated_text_cost(
            provider,
            model,
            0,
            output_characters,
        )
        cost += text_cost
        cost_complete = cost_complete and text_complete

    return {
        "timestamp": time.time(),
        "type": "recording",
        "duration_seconds": round(duration, 3),
        "latency_ms": safe_timings(context.get("latency_ms")),
        "mode": str(context.get("mode", "transcription") or "transcription"),
        "execution": str(context.get("execution", "cloud") or "cloud"),
        "refinement_execution": str(context.get("refinement_execution", "") or ""),
        "models": models,
        "word_count": _qt_word_count(result),
        "character_count": output_characters,
        "estimated_cost_usd": round(cost, 8),
        "cost_complete": cost_complete,
    }


def _build_qt_rewrite_usage_event(
    provider: str,
    model: str,
    source: str,
    result: str,
) -> dict[str, Any]:
    """Build the production usage event for a rewrite operation."""

    provider = str(provider or "")
    model = str(model or "")
    source = str(source or "")
    result = str(result or "")
    cost, cost_complete = _qt_estimated_text_cost(
        provider,
        model,
        len(source),
        len(result),
    )
    return {
        "timestamp": time.time(),
        "type": "rewrite",
        "duration_seconds": 0.0,
        "mode": "rewrite",
        "models": [{"provider": provider, "model": model, "purpose": "refinement"}],
        "word_count": _qt_word_count(result),
        "character_count": len(result),
        "estimated_cost_usd": round(cost, 8),
        "cost_complete": cost_complete,
    }


def _build_qt_translation_usage_event(
    provider: str,
    model: str,
    source: str,
    result: str,
    target_language: str,
) -> dict[str, Any]:
    """Build the production usage event for a text translation."""

    event = _build_qt_rewrite_usage_event(provider, model, source, result)
    event.update(
        {
            "type": "translation",
            "mode": "translation",
            "target_language": str(target_language or ""),
        }
    )
    return event


def _build_qt_voice_translation_usage_event(
    transcription_provider: str,
    transcription_model: str,
    translation_provider: str,
    translation_model: str,
    duration_seconds: float,
    source: str,
    result: str,
    target_language: str,
) -> dict[str, Any]:
    """Build the production-compatible anonymous voice-translation event."""

    transcription_provider = str(transcription_provider or "")
    transcription_model = str(transcription_model or "")
    translation_provider = str(translation_provider or "")
    translation_model = str(translation_model or "")
    source = str(source or "")
    result = str(result or "")
    target_language = str(target_language or "")
    duration = max(0.0, float(duration_seconds))

    transcription_cost = _QT_AUDIO_COST_USD_PER_MINUTE.get(
        (transcription_provider, transcription_model)
    )
    cost = 0.0 if transcription_cost is None else transcription_cost * duration / 60
    cost_complete = transcription_cost is not None
    if PROVIDER_REGISTRY.supports(
        transcription_provider, ProviderCapability.MULTIMODAL_AUDIO
    ):
        multimodal_cost, multimodal_complete = _qt_estimated_text_cost(
            transcription_provider, transcription_model, 0, len(source)
        )
        cost += multimodal_cost
        cost_complete = cost_complete and multimodal_complete

    translation_cost, translation_complete = _qt_estimated_text_cost(
        translation_provider,
        translation_model,
        len(source),
        len(result),
    )
    cost += translation_cost
    cost_complete = cost_complete and translation_complete

    return {
        "timestamp": time.time(),
        "type": "voice_translation",
        "mode": "voice_translation",
        "workflow": "voice_translation",
        "duration_seconds": round(duration, 3),
        "transcription_provider": transcription_provider,
        "transcription_model": transcription_model,
        "translation_provider": translation_provider,
        "translation_model": translation_model,
        "target_language": target_language,
        "models": [
            {
                "provider": transcription_provider,
                "model": transcription_model,
                "purpose": "transcription",
            },
            {
                "provider": translation_provider,
                "model": translation_model,
                "purpose": "translation",
            },
        ],
        "word_count": _qt_word_count(source),
        "character_count": len(source),
        "translation_character_count": len(result),
        "estimated_cost_usd": round(cost, 8),
        "cost_complete": cost_complete,
    }


class QtStatisticsGateway:
    def __init__(self, repositories: ApplicationRepositories) -> None:
        self.repositories = repositories

    def _record(self, event: dict[str, Any]) -> None:
        self.repositories.usage_stats.append(event)

    def record_dictation(
        self,
        context: dict[str, Any],
        duration_seconds: float,
        result: str,
    ) -> None:
        self._record(_build_qt_recording_usage_event(context, duration_seconds, result))

    def record_rewrite(
        self, provider: str, model: str, source: str, result: str
    ) -> None:
        self._record(_build_qt_rewrite_usage_event(provider, model, source, result))

    def record_translation(
        self,
        provider: str,
        model: str,
        source: str,
        result: str,
        target_language: str,
    ) -> None:
        self._record(
            _build_qt_translation_usage_event(
                provider,
                model,
                source,
                result,
                target_language,
            )
        )

    def record_voice_translation(
        self,
        config: Any,
        state: Any,
        duration_seconds: float,
    ) -> None:
        """Persist one production-schema event containing both provider legs."""

        route = getattr(config, "route", None)
        event = _build_qt_voice_translation_usage_event(
            getattr(state, "transcription_provider", ""),
            getattr(state, "transcription_model", ""),
            getattr(route, "provider_id", ""),
            getattr(route, "model_id", ""),
            duration_seconds,
            getattr(state, "raw_transcript", ""),
            getattr(state, "translated_text", ""),
            getattr(config, "target_language", ""),
        )
        self._record(event)


def _history_path_for_repositories(repositories: ApplicationRepositories) -> Path:
    explicit_path = getattr(repositories, "history_path", None)
    if explicit_path is not None:
        return Path(explicit_path)
    config_path = getattr(repositories.config, "path", None)
    if config_path is None:
        raise QtRuntimeError(
            "The QML history store requires a repository history_path or config path"
        )
    return Path(config_path).with_name("history.json")


class QtHistoryRecorder:
    """Persist terminal states with the owner captured when work starts."""

    def __init__(
        self,
        repositories: ApplicationRepositories,
        scheduler: QtWorkflowScheduler,
        account=None,
    ) -> None:
        self.repositories = repositories
        self.scheduler = scheduler
        self.account = account
        self._owners = {}
        self._recorded = set()
        current = repositories.config.load()
        self.store = HistoryStore(
            _history_path_for_repositories(repositories),
            enabled=bool(current.history_enabled),
            retention_days=current.history_retention_days,
        )

    def on_state(self, state: Any) -> None:
        if state.operation_id and state.operation_id not in self._owners:
            # A terminal event cannot infer ownership from the current login.
            self._owners[state.operation_id] = (
                self.account.history_identity()
                if self.account is not None
                and state.phase not in (WorkflowPhase.COMPLETED, WorkflowPhase.FAILED)
                else None
            )
        if state.phase not in (WorkflowPhase.COMPLETED, WorkflowPhase.FAILED):
            return
        terminal_key = (state.operation_id, state.phase, state.result_text)
        if state.operation_id and terminal_key in self._recorded:
            return
        if state.operation_id:
            self._recorded.add(terminal_key)
            # Workflow operation IDs are monotonic; keep recent retry owners.
            self._owners = {
                key: value
                for key, value in self._owners.items()
                if key >= state.operation_id - 32
            }
            self._recorded = {
                key for key in self._recorded if key[0] >= state.operation_id - 32
            }
        owner = self._owners.get(state.operation_id)
        managed = self.account is not None and self.account.managed
        self.scheduler.run_in_background(
            lambda: self.record_state(state, owner, managed)
        )

    def capture_operation(self, operation_id: int) -> None:
        self._owners[operation_id] = (
            self.account.history_identity() if self.account is not None else None
        )

    def record_state(self, state: Any, owner=None, managed=False) -> None:
        try:
            current = self.repositories.config.load()
            self.store.enabled = bool(current.history_enabled)
            self.store.retention_days = current.history_retention_days
            kind = (
                state.kind.value
                if isinstance(state.kind, WorkflowKind)
                else "transcription"
            )
            provider = str(state.provider_id or "unknown")
            model = str(state.model or "unknown")
            if state.phase is WorkflowPhase.COMPLETED:
                if state.kind is WorkflowKind.DICTATION:
                    raw_text = (
                        state.source_text
                        if state.source_text is not None
                        else state.result_text
                    )
                    refined_text = state.refined_text
                else:
                    raw_text = state.source_text
                    refined_text = state.result_text
                record = HistoryRecord(
                    raw_text=raw_text,
                    refined_text=refined_text,
                    workflow=kind,
                    provider=provider,
                    model=model,
                    refinement_provider=getattr(state, "refinement_provider_id", None),
                    refinement_model=getattr(state, "refinement_model", None),
                    status="partial"
                    if state.status_key == "refinement_failed"
                    else "success",
                    error="refinement_failed"
                    if state.status_key == "refinement_failed"
                    else None,
                )
                if self.account is not None and (managed or owner is not None):
                    if owner is not None and self.account.history.append(
                        record, owner, final_text=state.result_text
                    ):
                        self.account.history.sync_safely(force=True)
                elif self.account is None or not self.account.managed:
                    self.store.append(record)
            else:
                if (
                    managed
                    or owner is not None
                    or (self.account is not None and self.account.managed)
                ):
                    return
                self.store.add(
                    workflow=kind,
                    provider=provider,
                    model=model,
                    refinement_provider=getattr(state, "refinement_provider_id", None),
                    refinement_model=getattr(state, "refinement_model", None),
                    status="error",
                    error=state.status_key or "error",
                )
        except (HistoryStoreError, OSError, ValueError):
            # History is explicitly opt-in and must never change workflow UX.
            return


class QtWorkflowRuntime:
    """Own the concrete QML workflow and its application shutdown boundary."""

    def __init__(
        self,
        workflow_service: WorkflowService,
        recording_audio: QtRecordingAudioGateway,
        scheduler: QtWorkflowScheduler,
        clipboard: QtClipboardGateway,
        *,
        repositories: ApplicationRepositories | None = None,
        provider_registry=PROVIDER_REGISTRY,
        history_recorder: QtHistoryRecorder | None = None,
        audio_batch_service: AudioFileBatchService | None = None,
        dictionary_service: DictionarySnippetService | None = None,
        account=None,
    ) -> None:
        self.workflow_service = workflow_service
        self.recording_audio = recording_audio
        self.scheduler = scheduler
        self.clipboard = clipboard
        self.repositories = repositories
        self.provider_registry = provider_registry
        self.history_recorder = history_recorder
        self.audio_batch_service = audio_batch_service
        self.dictionary_service = dictionary_service
        self.account = account
        self._shutdown = False
        self._history_timer = None
        if (
            account is not None
            and getattr(account, "history", None) is not None
            and QCoreApplication.instance() is not None
        ):
            self._history_timer = QTimer()
            self._history_timer.setInterval(60000)
            self._history_timer.timeout.connect(self.request_history_sync)
            self._history_timer.start()
            self.request_history_sync()

    def request_history_sync(self) -> None:
        if (
            not self._shutdown
            and self.account is not None
            and getattr(self.account, "signed_in", False) is True
            and getattr(self.account, "history", None) is not None
        ):
            self.scheduler.run_in_background(self.account.history.sync_safely)

    def audio_file_selection(
        self,
        provider_id: str = "",
        model: str = "",
        language: str = "",
        mode: str = "prompt",
    ) -> FileTranscriptionSelection:
        """Build the current persisted transcription route for file imports."""

        if self.repositories is None:
            raise QtRuntimeError("The QML audio import route requires repositories")
        current = self.repositories.config.load()
        if self.account is not None and self.account.managed:
            return FileTranscriptionSelection(
                provider_id="clarify",
                model="whisper-large-v3-turbo",
                language=str(language or current.ui.language or "auto"),
            )
        route = current.workflow(WorkflowScope.TRANSCRIPTION)
        if not route.enabled:
            raise RuntimeError("transcription workflow is disabled")
        selected_provider = str(provider_id or route.provider_id).strip().lower()
        selected_model = str(model or route.model_id).strip()
        selected_language = (
            str(language or getattr(current.ui, "language", "en") or "en")
            .strip()
            .lower()
        )
        selected_mode = "prompt"
        metadata = self.provider_registry.describe(selected_provider)
        provider_config = getattr(current, selected_provider)
        connection = ProviderConnection(
            api_key=str(getattr(provider_config, "api_key", "") or "").strip(),
            base_url=(
                str(getattr(provider_config, "base_url", "") or "").strip()
                or str(metadata.default_base_url or "").strip()
            ),
        )
        custom_endpoint = (
            route.custom_endpoint if selected_provider == route.provider_id else ""
        )
        connection = self.provider_registry.connection_for_route(
            selected_provider,
            connection,
            custom_endpoint,
        )
        language_label = _language_display_name(selected_language)
        instruction = (
            TRANSCRIPTION_INSTRUCTION
            if selected_mode == "transcription"
            else PROMPT_INSTRUCTION
        ).format(lang=language_label)
        return FileTranscriptionSelection(
            provider_id=selected_provider,
            model=selected_model,
            language=selected_language,
            mode=selected_mode,
            connection=connection,
            instruction=instruction,
            prompt=route.prompt or instruction,
            temperature=0.0 if selected_mode == "transcription" else 0.1,
        )

    def copy_result(self, text: str) -> SelectionDisposition:
        """Copy a visible QML result through the real clipboard adapter."""

        return self.clipboard.write_dictation_result(None, str(text))

    def shutdown(self, timeout_seconds: float = 3.0) -> None:
        """Cancel active work, wait briefly for recording, then close providers."""

        if self._shutdown:
            return
        self._shutdown = True
        if self._history_timer is not None:
            self._history_timer.stop()
        timeout_seconds = max(0.0, float(timeout_seconds))
        deadline = time.monotonic() + timeout_seconds
        self.scheduler.begin_shutdown()
        self.scheduler.wait_for_dispatches(max(0.0, deadline - time.monotonic()))
        self.workflow_service.cancel_active()
        self.provider_registry.cancel()
        self.scheduler.wait_for_dispatches(max(0.0, deadline - time.monotonic()))
        self.workflow_service.cancel_active()
        self.recording_audio.wait_for_shutdown(max(0.0, deadline - time.monotonic()))
        self.scheduler.wait_for_background(max(0.0, deadline - time.monotonic()))
        self.provider_registry.shutdown()


def create_real_workflow_runtime(
    scheduler: QtWorkflowScheduler,
    *,
    repositories: ApplicationRepositories | None = None,
) -> QtWorkflowRuntime:
    """Create the production workflow and shutdown boundary for QML."""

    active = repositories or create_runtime_repositories()
    # Prune already collected fixtures even after collection is turned off.
    prune_audio_history(Path(active.config.path).parent)
    account = AccountService(
        Path(active.config.path).parent,
        default_endpoint=os.environ.get("CLARIFY_CLOUD_URL", DEFAULT_CLOUD_URL),
    )
    config = QtWorkflowConfig(active, account)
    dictionary_service = DictionarySnippetService(
        AccountDictionaryRepository(
            account,
            LocalDictionarySnippetsRepository(
                Path(active.config.path).parent / "dictionary.json"
            ),
        )
    )
    recording_audio = QtRecordingAudioGateway(QtRecorder(config), config)
    clipboard = QtClipboardGateway()
    provider = QtProviderGateway(config, dictionary_service, account=account)
    audio_batch_gateway = QtAudioFileGateway(provider)
    audio_batch_service = AudioFileBatchService(
        audio_batch_gateway,
        SoxAudioConverter(),
    )
    history_recorder = QtHistoryRecorder(active, scheduler, account=account)
    account.history = AccountHistory(account, history_recorder.store)
    service = WorkflowService(
        provider,
        recording_audio,
        clipboard,
        config,
        QtStatisticsGateway(active),
        scheduler,
        operation_started=history_recorder.capture_operation,
    )
    service.subscribe(history_recorder.on_state)
    return QtWorkflowRuntime(
        service,
        recording_audio,
        scheduler,
        clipboard,
        repositories=active,
        history_recorder=history_recorder,
        audio_batch_service=audio_batch_service,
        dictionary_service=dictionary_service,
        account=account,
    )


__all__ = [
    "QtRuntimeError",
    "QtWorkflowScheduler",
    "QtWorkflowConfig",
    "QtProviderGateway",
    "QtRecordingSession",
    "QtRecordingAudioGateway",
    "QtWorkflowRuntime",
    "QtClipboardGateway",
    "QtStatisticsGateway",
    "QtHistoryRecorder",
    "create_runtime_repositories",
    "create_real_workflow_runtime",
]
