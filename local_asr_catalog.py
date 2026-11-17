"""Pinned offline profiles and explicit compute selection. No downloads on use."""

from __future__ import annotations
import csv
import io
import json
import platform
import statistics
import time
import os
from pathlib import Path
import re
import subprocess
import threading

MODELS = (
    "ggml-base",
    "parakeet-v3-int8",
    "granite-5-turboctc",
    "ggml-turbo-q5",
    "nemotron-3.5-streaming",
    "ggml-small",
    "ggml-medium",
)
PROFILE_LABELS = (
    "Whisper Base (small-memory fallback)",
    "Parakeet v3 INT8 (CPU, provisional)",
    "Granite TurboCTC multilingual (CPU, provisional)",
    "Whisper Turbo q5 (NVIDIA GPU candidate)",
    "Nemotron 3.5 Streaming (provisional)",
    "Whisper Small (compatibility)",
    "Whisper Medium (compatibility)",
)
BATCH_MODELS = frozenset({"parakeet-v3-int8", "granite-5-turboctc"})
CPU_ONLY_MODELS = BATCH_MODELS | {"nemotron-3.5-streaming"}
PROFILE_DESCRIPTIONS = {
    "ggml-base": "Small-memory fallback. Recognition finishes after recording stops; accuracy can be lower.",
    "parakeet-v3-int8": "Accuracy-focused CPU candidate. Transcribes after recording stops. Native acceptance is pending.",
    "granite-5-turboctc": "Lower-memory multilingual CPU candidate. Transcribes after recording stops. Native acceptance is pending.",
    "ggml-turbo-q5": "Quantized Whisper candidate for NVIDIA GPUs. Native acceptance is pending. Processing during recording is a separate experiment.",
    "nemotron-3.5-streaming": "Provisional native streaming on CPU. Shows text during recording. Native acceptance is pending.",
    "ggml-small": "Compatibility model. Existing selections remain available; this is no longer a main recommendation.",
    "ggml-medium": "Compatibility model. Existing selections remain available; this is no longer a main recommendation.",
}


def model_device(model, device):
    return "cpu" if model in CPU_ONLY_MODELS else normalize_device(device)


def normalize_device(value):
    value = str(value or "auto").strip().lower()
    return (
        value
        if value in ("auto", "cpu") or re.fullmatch(r"cuda:[0-9]{1,2}", value)
        else "auto"
    )


def devices():
    """Bounded NVIDIA inventory. Availability is not proof of working offload."""
    result = [{"id": "auto", "label": "Automatic"}, {"id": "cpu", "label": "CPU"}]
    executable = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "nvidia-smi.exe"
    )
    if not executable.is_file():
        return result
    try:
        output = subprocess.run(
            [
                str(executable),
                "--query-gpu=index,name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=0x08000000,
            check=True,
        ).stdout
        for row in csv.reader(io.StringIO(output)):
            if len(row) == 4 and re.fullmatch(r"[0-9]{1,2}", row[0].strip()):
                result.append(
                    {
                        "id": "cuda:" + row[0].strip(),
                        "label": row[1].strip(),
                        "memory_mb": int(row[2]),
                        "driver": row[3].strip(),
                    }
                )
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return result


def installer_for(model, device="cpu"):
    from local_asr import LocalASRInstaller, default_install_root, default_manifest_path

    if model in BATCH_MODELS:
        from local_asr_batch_assets import installer_for_batch

        return installer_for_batch(model)
    if model == "nemotron-3.5-streaming":
        from local_asr_live_assets import installer_for_native

        return installer_for_native()
    if model not in MODELS:
        raise ValueError("Unknown local model")
    backend = "cuda" if normalize_device(device).startswith("cuda:") else "cpu"

    def make(kind):
        if model == "ggml-small" and kind == "cpu":
            return LocalASRInstaller()
        return LocalASRInstaller(
            root=default_install_root().parent
            / "local-asr-profiles"
            / f"{model}-{kind}",
            manifest_path=default_manifest_path().parent
            / "local_asr_manifests"
            / f"{model}-{kind}.json",
        )

    installer = make(backend)
    installer.model_sources = (make("cpu" if backend == "cuda" else "cuda").model_path,)
    return installer


class ModelInstaller:
    """One user installation prepares CPU and detected NVIDIA GPUs, then measures."""

    def __init__(self, model, pool, inventory=None):
        self.inventory = (
            inventory if inventory is not None else [{"id": "auto"}, {"id": "cpu"}]
        )
        self.model = model
        self.pool = pool
        self.cpu = installer_for(model, "cpu")

    def __getattr__(self, name):
        return getattr(self.cpu, name)

    def requirements(self):
        result = self.cpu.requirements()
        if self.model in CPU_ONLY_MODELS:
            return result
        gpu = len(self.inventory) > 2
        if gpu and self.model not in CPU_ONLY_MODELS:
            extra = installer_for(self.model, "cuda:0").requirements()
            result["download_bytes"] += max(
                0, extra.get("download_bytes", 0) - self.cpu.asset("model").size
            )
            result["disk_bytes"] += extra.get("disk_bytes", 0)
            result["memory_bytes"] = max(
                result.get("memory_bytes", 0), extra.get("memory_bytes", 0)
            )
        result["compute"] = (
            "CPU and detected NVIDIA GPU; fastest measured device in Automatic mode"
            if gpu
            else "CPU; no compatible NVIDIA GPU detected"
        )
        return result

    def status(self, **kwargs):
        self.inventory = devices()
        result = self.cpu.status(**kwargs)
        if self.model in CPU_ONLY_MODELS:
            result["requirements"] = self.cpu.requirements()
            return result
        if result["state"] == "installed":
            gpu = installer_for(self.model, "cuda:0")
            if len(self.inventory) > 2 and not gpu.model_path.exists():
                result["detail"] = (
                    "Model installed. Optimize CPU/GPU to add GPU support without downloading the model again."
                )
            else:
                result["detail"] = (
                    "Model installed. Automatic uses the fastest measured device."
                )
        result["requirements"] = self.requirements()
        return result

    def install(self, callback=None, cancel_event=None):
        from local_asr import (
            LocalASRCancelledError,
            LocalASRError,
            default_manifest_path,
        )

        event = cancel_event if cancel_event is not None else threading.Event()

        class Token:
            def cancel(self):
                event.set()

            def is_set(self):
                return event.is_set()

            def raise_if_cancelled(self):
                if event.is_set():
                    raise LocalASRCancelledError("Local setup was cancelled")

        token = Token()
        self.inventory = devices()
        self.cpu.install(callback, event)
        warning = ""
        if len(self.inventory) > 2 and self.model not in CPU_ONLY_MODELS:
            token.raise_if_cancelled()
            try:
                installer_for(self.model, "cuda:0").install(callback, event)
            except LocalASRCancelledError:
                raise
            except (LocalASRError, OSError):
                warning = " GPU setup failed; CPU remains available. Use Optimize CPU/GPU to retry."
        token.raise_if_cancelled()
        if self.model in CPU_ONLY_MODELS:
            status = self.cpu.status()
            status["detail"] = (
                "Installed provisional CPU model. Native acceptance is pending; no automatic default selection."
            )
            return status
        if callback:
            callback("Measuring CPU/GPU speed", 0, 0)
        try:
            result = calibrate(
                self.pool,
                self.model,
                default_manifest_path().parent / "assets" / "asr-benchmark.wav",
                token,
            )
            detail = "Ready. Automatic selected " + result["selected"] + "." + warning
        except LocalASRCancelledError:
            raise
        except Exception:
            detail = (
                "Model installed. Speed measurement did not finish; use Optimize CPU/GPU to retry."
                + warning
            )
        status = self.cpu.status()
        status["detail"] = detail
        status["requirements"] = self.requirements()
        return status

    def remove(self, cancel_event=None):
        # Each root retains its own guards. Removing one hard link leaves the other valid.
        self.pool.cancel()
        self.pool.shutdown()
        if self.model not in CPU_ONLY_MODELS:
            installer_for(self.model, "cuda:0").remove(cancel_event)
        return self.cpu.remove(cancel_event)


class EnginePool:
    def __init__(self, default):
        self.default = default
        self._lock = threading.RLock()
        self._measurement = None
        self._engines = {("ggml-small", "cpu"): default}

    def get(self, model, device="auto"):
        from local_asr import LocalASRSidecarManager, LocalASRSidecarError

        with self._lock:
            measurement = self._measurement
        if measurement is not None and measurement[0] != threading.get_ident():
            measurement[1].cancel()
            if not measurement[2].wait(5.0):
                raise LocalASRSidecarError(
                    "Local measurement is stopping. Try again shortly."
                )
        device = model_device(model, device)
        if device == "auto":
            device = measured_device(model)
        key = (model, device)
        with self._lock:
            for other_key, engine in self._engines.items():
                if other_key != key and isinstance(engine, LocalASRSidecarManager):
                    with engine._lock:
                        if (
                            not engine._active_cancellations
                            and engine._startup_cancel is None
                        ):
                            engine._stop_locked()
            if (
                key not in self._engines
                or getattr(self._engines[key], "_closed", False) is True
            ):
                if model in BATCH_MODELS:
                    from local_asr_batch import create_engine

                    self._engines[key] = create_engine(model, installer_for(model))
                elif model == "nemotron-3.5-streaming":
                    from local_asr_live import NativeEngine

                    self._engines[key] = NativeEngine(installer_for(model))
                else:
                    self._engines[key] = LocalASRSidecarManager(
                        installer_for(model, device), compute_device=device
                    )
            return self._engines[key]

    def cancel(self):
        with self._lock:
            engines = tuple(self._engines.values())
        for engine in engines:
            engine.cancel()

    def shutdown(self):
        with self._lock:
            engines = tuple(self._engines.values())
        for engine in engines:
            engine.shutdown()


def _benchmark_path():
    from local_asr import default_install_root

    return default_install_root().parent / "local-asr-device-benchmarks.json"


def _fingerprint(model, inventory):
    cpu = installer_for(model).manifest
    cuda = installer_for(model, "cuda:0").manifest
    return {
        "model": cpu["assets"]["model"]["sha256"],
        "cpu_runtime": cpu["assets"]["runtime"]["sha256"],
        "gpu_runtime": cuda["assets"]["runtime"]["sha256"],
        "cublas": cuda["assets"]["cublas"]["sha256"],
        "cpu": platform.processor(),
        "cores": os.cpu_count(),
        "gpus": inventory[2:],
    }


def measured_device(model):
    if model in CPU_ONLY_MODELS:
        return "cpu"
    try:
        data = json.loads(_benchmark_path().read_text(encoding="utf8"))[model]
        if data["fingerprint"] != _fingerprint(model, devices()):
            return "cpu"
        device = normalize_device(data["selected"])
        return device if device != "auto" else "cpu"
    except (OSError, ValueError, KeyError, TypeError):
        return "cpu"


def _calibrate(pool, model, audio, cancel_token):
    """Measure installed engines on synthetic local audio. Never download assets."""
    if model in CPU_ONLY_MODELS:
        raise ValueError(
            "This model uses CPU only; CPU/GPU measurement is not available."
        )
    inventory = devices()
    scores = {}
    for item in inventory[1:]:
        cancel_token.raise_if_cancelled()
        engine = pool.get(model, item["id"])
        if engine.installer.status().get("state") != "installed":
            continue
        try:
            engine.transcribe(audio, "en", cancel_event=cancel_token)  # warmup
            times = []
            for _ in range(3):
                cancel_token.raise_if_cancelled()
                started = time.perf_counter()
                engine.transcribe(audio, "en", cancel_event=cancel_token)
                times.append((time.perf_counter() - started) * 1000)
            scores[item["id"]] = statistics.median(times)
        except Exception:
            cancel_token.raise_if_cancelled()
        finally:
            engine.stop()
    if "cpu" not in scores:
        raise ValueError("Install the CPU version of this model before measuring.")
    selected = min(scores, key=scores.get)
    result = {
        "fingerprint": _fingerprint(model, inventory),
        "selected": selected,
        "median_ms": scores,
    }
    path = _benchmark_path()
    try:
        data = json.loads(path.read_text(encoding="utf8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    cancel_token.raise_if_cancelled()
    data[model] = result
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf8")
    temporary.replace(path)
    return result


def calibrate(pool, model, audio, cancel_token):
    """Recording requests cancel measurement before starting their own engine."""
    from local_asr import LocalASRSidecarManager

    completed = threading.Event()
    with pool._lock:
        if pool._measurement is not None:
            raise ValueError("A local measurement is already running.")
        for engine in pool._engines.values():
            if isinstance(engine, LocalASRSidecarManager):
                with engine._lock:
                    if engine._active_cancellations:
                        raise ValueError(
                            "Finish the current dictation before measuring."
                        )
        pool._measurement = (threading.get_ident(), cancel_token, completed)
    try:
        return _calibrate(pool, model, audio, cancel_token)
    finally:
        with pool._lock:
            pool._measurement = None
            completed.set()
