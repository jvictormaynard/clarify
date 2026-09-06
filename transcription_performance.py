"""Local, content-free timing and conservative host memory policy."""
from __future__ import annotations

import math
import os
from collections.abc import Mapping

TIMING_FIELDS = frozenset({
    "capture_finalize_ms", "provider_ms", "asr_ms", "refinement_ms",
    "text_cleanup_ms", "model_start_ms", "inference_ms", "delivery_ms",
    "stop_to_delivery_ms",
})


def safe_timings(value) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    return {key: round(float(number), 3) for key, number in value.items()
            if key in TIMING_FIELDS and type(number) in (int, float)
            and math.isfinite(number) and 0 <= number <= 86_400_000}


def memory_bytes() -> tuple[int, int] | None:
    """Return total and available physical RAM; unknown hosts use safe defaults."""
    try:
        if os.name == "nt":
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in (
                        "total", "available", "total_page", "available_page",
                        "total_virtual", "available_virtual", "extended")]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.total, status.available
        elif os.path.isfile("/proc/meminfo"):
            with open("/proc/meminfo", encoding="ascii") as source:
                values = {line.split(":")[0]: int(line.split()[1]) * 1024
                          for line in source if line.startswith(("MemTotal:", "MemAvailable:"))}
            return values["MemTotal"], values["MemAvailable"]
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    return None


def model_idle_seconds(memory: tuple[int, int] | None) -> float:
    if memory is None:
        return 60.0
    total, available = memory
    gib = 1024 ** 3
    if total >= 16 * gib and available >= 6 * gib:
        return 600.0
    if total >= 8 * gib and available >= 2 * gib:
        return 300.0
    return 60.0
