"""Windows shared-mode WASAPI capture, one COM apartment per source worker.

Loopback follows Microsoft's rendering-endpoint capture contract:
https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
No device or audio backend is opened at import time.
"""

import ctypes as C
import math
import struct
import sys
import time
import uuid
from array import array

from shared.meeting_contract import MeetingError


class WaveFormat(C.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("tag", C.c_uint16),
        ("channels", C.c_uint16),
        ("rate", C.c_uint32),
        ("bytes_per_second", C.c_uint32),
        ("align", C.c_uint16),
        ("bits", C.c_uint16),
        ("extra", C.c_uint16),
    ]


def pcm16_mono(data, channels, bits, floating=False):
    """Convert a bounded native packet; never interpret float audio as PCM."""
    if not 1 <= channels <= 16 or bits not in {16, 24, 32} or floating and bits != 32:
        raise MeetingError("meeting.audio_format")
    width = bits // 8
    if len(data) % (channels * width):
        raise MeetingError("meeting.audio_format")
    output = array("h")
    for frame in range(0, len(data), channels * width):
        value = 0.0
        for channel in range(channels):
            offset = frame + channel * width
            if floating:
                sample = struct.unpack_from("<f", data, offset)[0]
                value += sample * 32768 if math.isfinite(sample) else 0
            else:
                value += int.from_bytes(
                    data[offset : offset + width], "little", signed=True
                ) / (2 ** (bits - 16))
        output.append(max(-32768, min(32767, int(value / channels))))
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


def _guid(value):
    return (C.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le)


def _ole32():
    # WinDLL uses stdcall without OleDLL's implicit HRESULT handling. These
    # declarations follow combaseapi.h; Windows LONG/DWORD are always 32 bits.
    ole = C.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [C.c_void_p, C.c_uint32]
    ole.CoInitializeEx.restype = C.c_int32
    ole.CoCreateInstance.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.c_uint32,
        C.c_void_p,
        C.POINTER(C.c_void_p),
    ]
    ole.CoCreateInstance.restype = C.c_int32
    ole.CoTaskMemFree.argtypes = [C.c_void_p]
    ole.CoTaskMemFree.restype = None
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    return ole


class WasapiSource:
    def __init__(self, source):
        if source not in {"microphone", "system"}:
            raise ValueError(source)
        self.source = source

    def run(self, stop, packet, warning):
        if sys.platform != "win32":
            raise MeetingError("meeting.windows_only")
        ole = _ole32()
        pointers = []
        format_ptr = C.c_void_p()
        client = C.c_void_p()
        initialized = started = False

        def call(pointer, index, types=(), args=()):
            vtable = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
            # IUnknown::Release returns ULONG; all other methods called here
            # return HRESULT. Do not interpret a reference count as an error.
            restype = C.c_uint32 if index == 2 else C.c_int32
            method = C.WINFUNCTYPE(restype, C.c_void_p, *types)(vtable[index])
            result = method(pointer, *args)
            if index != 2 and result < 0:
                raise MeetingError("meeting.capture_error")
            return result

        def default_device(enumerator):
            device = C.c_void_p()
            call(
                enumerator,
                4,
                (C.c_int, C.c_int, C.POINTER(C.c_void_p)),
                (
                    0 if self.source == "system" else 1,
                    0 if self.source == "system" else 2,
                    C.byref(device),
                ),
            )
            return device

        def device_id(device):
            identifier = C.c_void_p()
            call(device, 5, (C.POINTER(C.c_void_p),), (C.byref(identifier),))
            try:
                return C.wstring_at(identifier)
            finally:
                ole.CoTaskMemFree(identifier)

        try:
            if ole.CoInitializeEx(None, 0) < 0:
                raise MeetingError("meeting.capture_error")
            initialized = True
            enumerator = C.c_void_p()
            if (
                ole.CoCreateInstance(
                    _guid("bcde0395-e52f-467c-8e3d-c4579291692e"),
                    None,
                    23,
                    _guid("a95664d2-9614-4f35-a746-de8db63617e6"),
                    C.byref(enumerator),
                )
                < 0
            ):
                raise MeetingError("meeting.capture_error")
            pointers.append(enumerator)
            device = default_device(enumerator)
            pointers.append(device)
            original_device = device_id(device)
            call(
                device,
                3,
                (C.c_void_p, C.c_uint32, C.c_void_p, C.POINTER(C.c_void_p)),
                (
                    _guid("1cb9ad4c-dbfa-4c32-b178-c2f568a703b2"),
                    23,
                    None,
                    C.byref(client),
                ),
            )
            pointers.append(client)
            call(client, 8, (C.POINTER(C.c_void_p),), (C.byref(format_ptr),))
            fmt = C.cast(format_ptr, C.POINTER(WaveFormat)).contents
            tag = fmt.tag
            if tag == 0xFFFE and fmt.extra >= 22:
                tag = C.c_uint16.from_address(format_ptr.value + 24).value
            if (
                tag not in {1, 3}
                or not 8000 <= fmt.rate <= 192000
                or fmt.align != fmt.channels * (fmt.bits // 8)
            ):
                raise MeetingError("meeting.audio_format")
            # Validate before the first data packet, including a silent endpoint.
            pcm16_mono(b"", fmt.channels, fmt.bits, tag == 3)
            call(
                client,
                3,
                (C.c_int, C.c_uint32, C.c_int64, C.c_int64, C.c_void_p, C.c_void_p),
                (
                    0,
                    0x20000 if self.source == "system" else 0,
                    10000000,
                    0,
                    format_ptr,
                    None,
                ),
            )
            capture = C.c_void_p()
            call(
                client,
                14,
                (C.c_void_p, C.POINTER(C.c_void_p)),
                (_guid("c8adbd64-e71e-48a0-a4de-185c395cd317"), C.byref(capture)),
            )
            pointers.append(capture)
            call(client, 10)
            started = True
            checked = time.monotonic()
            while not stop.wait(0.01):
                if time.monotonic() - checked >= 1:
                    current = default_device(enumerator)
                    try:
                        if device_id(current) != original_device:
                            raise MeetingError("meeting.device_changed")
                    finally:
                        call(current, 2)
                    checked = time.monotonic()
                count = C.c_uint32()
                call(capture, 5, (C.POINTER(C.c_uint32),), (C.byref(count),))
                while count.value and not stop.is_set():
                    data, frames, flags = C.c_void_p(), C.c_uint32(), C.c_uint32()
                    call(
                        capture,
                        3,
                        (
                            C.POINTER(C.c_void_p),
                            C.POINTER(C.c_uint32),
                            C.POINTER(C.c_uint32),
                            C.c_void_p,
                            C.c_void_p,
                        ),
                        (C.byref(data), C.byref(frames), C.byref(flags), None, None),
                    )
                    try:
                        if frames.value > fmt.rate * 2:
                            raise MeetingError("meeting.audio_format")
                        raw = (
                            bytes(frames.value * fmt.align)
                            if flags.value & 2
                            else C.string_at(data, frames.value * fmt.align)
                        )
                        if flags.value & 1:
                            warning("meeting.audio_gap")
                        packet(
                            pcm16_mono(raw, fmt.channels, fmt.bits, tag == 3), fmt.rate
                        )
                    finally:
                        call(capture, 4, (C.c_uint32,), (frames.value,))
                    call(capture, 5, (C.POINTER(C.c_uint32),), (C.byref(count),))
        finally:
            failed = sys.exc_info()[0] is not None
            cleanup_failed = False

            def cleanup(action, *args):
                nonlocal cleanup_failed
                try:
                    action(*args)
                except Exception:
                    cleanup_failed = True

            if started:
                cleanup(call, client, 11)
            if format_ptr:
                cleanup(ole.CoTaskMemFree, format_ptr)
            for pointer in reversed(pointers):
                cleanup(call, pointer, 2)
            if initialized:
                cleanup(ole.CoUninitialize)
            if cleanup_failed and not failed:
                raise MeetingError("meeting.capture_error")
