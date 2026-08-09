"""Qt-facing state for the transient recording and processing pill."""

from __future__ import annotations

import base64
import ctypes
import io
import sys
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import (
    Property,
    QBuffer,
    QByteArray,
    QFileInfo,
    QIODevice,
    QObject,
    QTimer,
    Signal,
)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider


def _pillow_data_url(image: Image.Image) -> str:
    """Encode a full-resolution Pillow icon without a filesystem round trip."""

    payload = io.BytesIO()
    image.save(payload, "PNG")
    encoded = base64.b64encode(payload.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _normalize_app_icon(image: Image.Image, size: int = 64) -> Image.Image:
    """Crop transparent padding while preserving a crisp, balanced footprint."""

    icon = image.convert("RGBA")
    alpha = icon.getchannel("A")
    visible_box = alpha.point(lambda value: 255 if value >= 128 else 0).getbbox()
    if visible_box:
        icon = icon.crop(visible_box)

    target = size - 8
    ratio = min(target / icon.width, target / icon.height)
    resized = icon.resize(
        (max(1, round(icon.width * ratio)), max(1, round(icon.height * ratio))),
        Image.Resampling.LANCZOS,
    )
    normalized = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    normalized.alpha_composite(
        resized,
        ((size - resized.width) // 2, (size - resized.height) // 2),
    )
    return normalized


def _packaged_app_icon(executable: str, size: int = 64) -> Image.Image | None:
    """Prefer the high-resolution visual asset shipped by packaged apps."""

    try:
        for parent in Path(executable).parents:
            assets = parent / "assets"
            if not assets.is_dir():
                continue
            patterns = (
                f"Square44x44Logo.targetsize-{size}*_altform-unplated.png",
                f"Square44x44Logo.targetsize-{size}*.png",
                "Square44x44Logo.scale-200.png",
                "Square44x44Logo.png",
                "icon.png",
            )
            for pattern in patterns:
                candidate = next(assets.glob(pattern), None)
                if candidate is not None:
                    with Image.open(candidate) as image:
                        return _normalize_app_icon(image.copy(), size)
            break
    except Exception:
        pass
    return None


def _windows_executable_icon(
    executable: str,
    size: int = 64,
) -> Image.Image | None:
    """Render an executable's largest native HICON into a 64px RGBA image."""

    if sys.platform != "win32" or not executable:
        return None

    packaged_icon = _packaged_app_icon(executable, size)
    if packaged_icon is not None:
        return packaged_icon

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BitmapInfo(ctypes.Structure):
        _fields_ = [
            ("bmiHeader", BitmapInfoHeader),
            ("bmiColors", wintypes.DWORD * 3),
        ]

    try:
        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        user32.PrivateExtractIconsW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(wintypes.HICON),
            ctypes.POINTER(wintypes.UINT),
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.PrivateExtractIconsW.restype = wintypes.UINT
        user32.DrawIconEx.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HICON,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.HBRUSH,
            wintypes.UINT,
        ]
        user32.DrawIconEx.restype = wintypes.BOOL
        user32.DestroyIcon.argtypes = [wintypes.HICON]
        user32.DestroyIcon.restype = wintypes.BOOL
        shell32.ExtractIconExW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(wintypes.HICON),
            ctypes.POINTER(wintypes.HICON),
            wintypes.UINT,
        ]
        shell32.ExtractIconExW.restype = wintypes.UINT
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(BitmapInfo),
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        gdi32.SelectObject.restype = wintypes.HANDLE
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi32.DeleteDC.argtypes = [wintypes.HDC]

        large_icon = wintypes.HICON()
        icon_id = wintypes.UINT()
        extracted = user32.PrivateExtractIconsW(
            executable,
            0,
            size,
            size,
            ctypes.byref(large_icon),
            ctypes.byref(icon_id),
            1,
            0,
        )
        if extracted != 1 or not large_icon:
            large_icon = wintypes.HICON()
            if (
                shell32.ExtractIconExW(
                    executable,
                    0,
                    ctypes.byref(large_icon),
                    None,
                    1,
                )
                != 1
            ):
                return None

        dc = gdi32.CreateCompatibleDC(0)
        bits = ctypes.c_void_p()
        info = BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
        info.bmiHeader.biWidth = size
        info.bmiHeader.biHeight = -size
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        bitmap = gdi32.CreateDIBSection(
            dc,
            ctypes.byref(info),
            0,
            ctypes.byref(bits),
            None,
            0,
        )
        if not dc or not bitmap or not bits:
            if large_icon:
                user32.DestroyIcon(large_icon)
            if dc:
                gdi32.DeleteDC(dc)
            return None

        old_bitmap = gdi32.SelectObject(dc, bitmap)
        try:
            ctypes.memset(bits, 0, size * size * 4)
            if not user32.DrawIconEx(
                dc,
                0,
                0,
                large_icon,
                size,
                size,
                0,
                None,
                0x0003,
            ):
                return None
            pixels = bytearray(ctypes.string_at(bits, size * size * 4))
            for offset in range(0, len(pixels), 4):
                alpha = pixels[offset + 3]
                if 0 < alpha < 255:
                    pixels[offset] = min(255, pixels[offset] * 255 // alpha)
                    pixels[offset + 1] = min(255, pixels[offset + 1] * 255 // alpha)
                    pixels[offset + 2] = min(255, pixels[offset + 2] * 255 // alpha)
            rendered = Image.frombytes(
                "RGBA",
                (size, size),
                bytes(pixels),
                "raw",
                "BGRA",
            )
            return _normalize_app_icon(rendered, size)
        finally:
            gdi32.SelectObject(dc, old_bitmap)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(dc)
            user32.DestroyIcon(large_icon)
    except Exception:
        return None


def _icon_data_url(icon: QIcon, size: int = 64) -> str:
    """Encode a Qt icon as an in-memory PNG that QML can render directly."""

    pixmap = icon.pixmap(size, size)
    if pixmap.isNull():
        return ""
    payload = QByteArray()
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        return ""
    try:
        if not pixmap.save(buffer, "PNG"):
            return ""
    finally:
        buffer.close()
    encoded = bytes(payload.toBase64()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class QmlStatusPillController(QObject):
    """Expose the live input level and target application icon to QML.

    SoX remains the authoritative audio recorder.  The optional PortAudio
    stream owned by ``QtRecorder`` is sampled only for presentation, matching
    the previous pill without coupling the workflow to a UI callback.
    """

    audioLevelChanged = Signal()
    targetIconChanged = Signal()

    def __init__(
        self,
        bridge: Any,
        recorder: Any,
        *,
        fallback_icon: QIcon,
        icon_resolver: Callable[[str], str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._recorder = recorder
        self._audio_level = 0.0
        self._fallback_icon = fallback_icon
        self._file_icons = QFileIconProvider()
        self._icon_resolver = icon_resolver or self._resolve_icon
        self._target_icon = self._icon_resolver("")
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(16)
        self._level_timer.timeout.connect(self._sample_level)
        bridge.recordingChanged.connect(self._sync_recording)
        bridge.targetExecutableChanged.connect(self._sync_target_icon)
        self._sync_target_icon()
        self._sync_recording()

    def _resolve_icon(self, executable: str) -> str:
        native_icon = _windows_executable_icon(executable)
        if native_icon is not None:
            return _pillow_data_url(native_icon)

        icon = QIcon()
        if executable and Path(executable).is_file():
            icon = self._file_icons.icon(QFileInfo(executable))
        if icon.isNull():
            icon = self._fallback_icon
        return _icon_data_url(icon)

    @Property(float, notify=audioLevelChanged)
    def audioLevel(self) -> float:
        return self._audio_level

    @Property(str, notify=targetIconChanged)
    def targetIcon(self) -> str:
        return self._target_icon

    def _set_audio_level(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._audio_level) < 0.002:
            return
        self._audio_level = value
        self.audioLevelChanged.emit()

    def _sample_level(self) -> None:
        try:
            target = float(getattr(self._recorder, "mic_level", 0.0) or 0.0)
        except (TypeError, ValueError):
            target = 0.0
        blend = 0.38 if target > self._audio_level else 0.12
        self._set_audio_level(self._audio_level + (target - self._audio_level) * blend)

    def _sync_recording(self) -> None:
        if bool(self._bridge.recording):
            if not self._level_timer.isActive():
                self._level_timer.start()
            return
        self._level_timer.stop()
        self._set_audio_level(0.0)

    def _sync_target_icon(self) -> None:
        resolved = self._icon_resolver(str(self._bridge.targetExecutable or ""))
        if resolved == self._target_icon:
            return
        self._target_icon = resolved
        self.targetIconChanged.emit()


__all__ = ["QmlStatusPillController"]
