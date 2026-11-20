"""Focus-safe clipboard boundary for the native QML workflow runtime.

The QML frontend cannot depend on the legacy Tk application.  This module is
the small platform boundary that gives :class:`workflows.WorkflowService` the
selection transaction it needs while keeping native focus and clipboard
ownership rules outside the UI and orchestration layers.
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

try:
    from workflows import (
        ClipboardGateway,
        SelectionCapture,
        SelectionDisposition,
        SelectionTarget,
    )
    from windows_clipboard import ClipboardSnapshot, WindowsClipboardAdapter
    from windows_hotkeys import (
        is_alt_pressed as native_alt_pressed,
        paste_focused_control,
        send_ctrl_key,
    )
    from voice_translation import VoiceTranslationPublication
except ImportError:  # PyInstaller may load the module as part of the package.
    from ...workflows import (  # type: ignore[no-redef]
        ClipboardGateway,
        SelectionCapture,
        SelectionDisposition,
        SelectionTarget,
    )
    from ...windows_clipboard import (  # type: ignore[no-redef]
        ClipboardSnapshot,
        WindowsClipboardAdapter,
    )
    from ...windows_hotkeys import (  # type: ignore[no-redef]
        is_alt_pressed as native_alt_pressed,
        paste_focused_control,
        send_ctrl_key,
    )
    from ...voice_translation import VoiceTranslationPublication  # type: ignore[no-redef]


CLIPBOARD_RESTORE_DELAY_SECONDS = 0.2
SELECTION_COPY_TIMEOUT_SECONDS = 0.7
SELECTION_COPY_POLL_SECONDS = 0.02
SELECTION_COPY_RETRY_SECONDS = 0.12


def _foreground_window_handle() -> int | None:
    """Return the current foreground HWND without importing the UI."""

    if platform.system() != "Windows":
        return None
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        return int(user32.GetForegroundWindow() or 0) or None
    except (AttributeError, OSError, TypeError):
        return None


def _window_executable(hwnd: Any = None) -> str | None:
    """Return the executable path owning ``hwnd`` when Windows permits it."""

    if platform.system() != "Windows":
        return None
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        hwnd = hwnd or user32.GetForegroundWindow()
        if not hwnd:
            return None

        process_id = wintypes.DWORD()
        if (
            not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            or not process_id.value
        ):
            return None
        if process_id.value == os.getpid():
            return None

        process = kernel32.OpenProcess(0x1000, False, process_id.value)
        if not process:
            return None
        try:
            size = wintypes.DWORD(32768)
            executable = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(
                process, 0, executable, ctypes.byref(size)
            ):
                return None
            path = executable.value
            if Path(path).name.lower() == "explorer.exe":
                class_name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_name, len(class_name))
                if class_name.value != "CabinetWClass":
                    return None
            return path or None
        finally:
            kernel32.CloseHandle(process)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _activate_window(hwnd: Any) -> bool:
    """Return keyboard focus to a previously captured native window."""

    if platform.system() != "Windows" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        return bool(user32.SetForegroundWindow(hwnd))
    except (AttributeError, OSError, TypeError):
        return False


def _same_selected_text(left: Any, right: Any) -> bool:
    """Compare text using the same newline normalization as the old adapter."""

    def normalize(value: Any) -> str:
        return str(value).replace("\r\n", "\n").replace("\r", "\n")

    return normalize(left) == normalize(right)


class QmlClipboardGateway(ClipboardGateway):
    """Concrete clipboard gateway used by the QML ``WorkflowService``.

    Each native boundary can be tested without a desktop session or a GUI.
    """

    def __init__(
        self,
        *,
        adapter: Any | None = None,
        is_windows: bool | None = None,
        platform_name: str | None = None,
        foreground_window: Callable[[], Any] | None = None,
        executable_for_window: Callable[[Any], str | None] | None = None,
        activate_window: Callable[[Any], bool] | None = None,
        send_ctrl_c: Callable[[], bool | None] | None = None,
        send_ctrl_v: Callable[[str], bool | None] | None = None,
        alt_pressed: Callable[[], bool] | None = None,
        run: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        lock: threading.Lock | None = None,
        copy_timeout: float = SELECTION_COPY_TIMEOUT_SECONDS,
        restore_delay: float = CLIPBOARD_RESTORE_DELAY_SECONDS,
    ) -> None:
        self.platform_name = platform_name or platform.system()
        self.is_windows = (
            self.platform_name == "Windows" if is_windows is None else bool(is_windows)
        )
        self._macos = None
        if self.platform_name == "Darwin" and not self.is_windows:
            if __package__:
                from .macos_clipboard import MacOSClipboard
            else:
                from macos_clipboard import MacOSClipboard

            self._macos = MacOSClipboard()
        if adapter is None:
            adapter = self._macos or WindowsClipboardAdapter(is_windows=self.is_windows)
        self.adapter = adapter
        self._foreground_window = foreground_window or (
            self._macos.foreground_window if self._macos else _foreground_window_handle
        )
        self._executable_for_window = executable_for_window or (
            (lambda window: window.executable) if self._macos else _window_executable
        )
        self._activate_window = activate_window or (
            self._macos.activate if self._macos else _activate_window
        )
        self._send_ctrl_c = (
            (lambda: send_ctrl_key("c")) if send_ctrl_c is None else send_ctrl_c
        )
        self._send_ctrl_v = (
            (lambda expected_text: paste_focused_control(expected_text=expected_text))
            if send_ctrl_v is None
            else send_ctrl_v
        )
        self._alt_pressed = alt_pressed or (
            self._macos.modifiers_pressed if self._macos else native_alt_pressed
        )
        self._run = subprocess.run if run is None else run
        self._sleep = time.sleep if sleep is None else sleep
        self._monotonic = time.monotonic if monotonic is None else monotonic
        self._lock = threading.Lock() if lock is None else lock
        self.copy_timeout = max(0.0, float(copy_timeout))
        self.restore_delay = max(0.0, float(restore_delay))

    def capture_target(self) -> SelectionTarget | None:
        """Capture the foreground window before a workflow releases focus."""

        if not self.is_windows and self._macos is None:
            return None
        try:
            window = self._foreground_window()
        except Exception:
            return None
        if not window:
            return None
        try:
            executable = self._executable_for_window(window)
        except Exception:
            executable = None
        return SelectionTarget(window, executable)

    def is_target_current(self, target: SelectionTarget) -> bool:
        """Verify the native target at each focus-sensitive boundary."""

        if target is None or not target.window:
            return False
        try:
            if self._macos is not None:
                return self._macos.is_current(target.window)
            return self.is_windows and self._foreground_window() == target.window
        except Exception:
            return False

    @staticmethod
    def _is_restorable(snapshot: Any) -> bool:
        return bool(snapshot is not None and getattr(snapshot, "restorable", False))

    def _snapshot(self) -> ClipboardSnapshot | Any | None:
        return self.adapter.snapshot()

    def _snapshot_for_selection(self) -> Any | None:
        try:
            return self._snapshot()
        except OSError:
            try:
                return self._snapshot()
            except OSError:
                return None

    def _sequence(self) -> int | None:
        try:
            return int(self.adapter.sequence())
        except (OSError, TypeError, ValueError):
            return None

    def _copy_selected_text_with_sequence(
        self,
        *,
        expected_sequence: int | None = None,
        suppress_read_errors: bool = False,
        before_copy: Callable[[], bool] | None = None,
    ) -> tuple[str | None, int | None, int | None]:
        """Copy only after a sequence/focus check and wait for ownership."""

        previous_sequence = self._sequence()
        if previous_sequence is None:
            return None, None, None
        if expected_sequence is not None and previous_sequence != expected_sequence:
            return None, previous_sequence, previous_sequence
        if before_copy is not None:
            try:
                if not before_copy():
                    return None, previous_sequence, previous_sequence
            except Exception:
                return None, previous_sequence, previous_sequence
        try:
            copied = self._send_ctrl_c()
        except Exception:
            return None, previous_sequence, previous_sequence
        if copied is False:
            return None, previous_sequence, previous_sequence

        deadline = self._monotonic() + self.copy_timeout
        retry_at = min(
            deadline,
            self._monotonic() + SELECTION_COPY_RETRY_SECONDS,
        )
        retried = False
        observed_sequence = previous_sequence
        while self._monotonic() < deadline:
            observed_sequence = self._sequence()
            if observed_sequence is None:
                return None, previous_sequence, None
            if observed_sequence != previous_sequence:
                try:
                    selected = self.adapter.text()
                except Exception:
                    if not suppress_read_errors:
                        raise
                    selected = None
                return selected, previous_sequence, observed_sequence
            if not retried and self._monotonic() >= retry_at:
                # Some custom Windows controls swallow the first synthetic
                # Ctrl+C immediately after the global Alt hotkey is released.
                # Retry only while focus and clipboard ownership are unchanged.
                if before_copy is not None:
                    try:
                        if not before_copy():
                            return None, previous_sequence, observed_sequence
                    except Exception:
                        return None, previous_sequence, observed_sequence
                try:
                    copied = self._send_ctrl_c()
                except Exception:
                    return None, previous_sequence, observed_sequence
                if copied is False:
                    return None, previous_sequence, observed_sequence
                retried = True
            self._sleep(SELECTION_COPY_POLL_SECONDS)
        return None, previous_sequence, observed_sequence

    def capture_selection(self, target: SelectionTarget) -> SelectionCapture | None:
        """Capture selected text and preserve the user's clipboard."""

        if self._macos is not None:
            if target is None:
                return None
            try:
                selection = self._macos.selection(target.window)
            except Exception:
                return None
            return (
                SelectionCapture(target, selection[0], selection[1])
                if selection is not None
                else None
            )
        if not self.is_windows or not self.is_target_current(target):
            return None
        previous = self._snapshot_for_selection()
        if not self._is_restorable(previous):
            return None
        if not self.is_target_current(target):
            return None
        selected, _before_sequence, copied_sequence = (
            self._copy_selected_text_with_sequence(
                expected_sequence=getattr(previous, "sequence", None),
                suppress_read_errors=True,
                before_copy=lambda: self.is_target_current(target),
            )
        )
        if not isinstance(selected, str) or copied_sequence is None:
            # A changed sequence without readable text may belong to another
            # application.  Never restore the user's clipboard in that case.
            return None
        return SelectionCapture(
            target,
            selected,
            {
                "previous": previous,
                "selected": selected,
                "copy_observed_sequence": copied_sequence,
            },
        )

    def _restore_if_owned(
        self, snapshot: Any, expected_sequence: int | None, expected_text: str
    ) -> bool:
        if (
            (not self.is_windows and self._macos is None)
            or not self._is_restorable(snapshot)
            or expected_sequence is None
        ):
            return False
        try:
            return bool(
                self.adapter.restore_if_owned(
                    snapshot, expected_sequence, expected_text
                )
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def restore(self, capture: SelectionCapture) -> None:
        """Restore the pre-copy clipboard only while our copy still owns it."""

        if not self.is_windows or capture is None:
            return
        context = capture.context if isinstance(capture.context, dict) else {}
        previous = context.get("previous")
        selected = context.get("selected", capture.text)
        copied_sequence = context.get("copy_observed_sequence")
        self._restore_if_owned(previous, copied_sequence, selected)

    def _write_visible_copy(self, text: str) -> bool:
        """Copy a result that the user can paste manually."""

        if self.is_windows:
            self.adapter.write_text(text)
            return True
        if self._macos is not None:
            try:
                return self.adapter.write_text(text) is not None
            except ImportError:
                # A source run without PyObjC can still copy a visible result.
                pass
        command = (
            ["pbcopy"]
            if self.platform_name == "Darwin"
            else ["xclip", "-selection", "clipboard"]
        )
        self._run(command, input=str(text).encode(), check=True)
        return True

    def _publish_macos(self, text, target, *, expected_selection=None):
        value = str(text)
        with self._lock:
            try:
                if target is None or not self.is_target_current(target):
                    return (
                        SelectionDisposition.COPIED
                        if self._write_visible_copy(value)
                        else SelectionDisposition.PRESERVED
                    )
                before = self._snapshot()
                sequence = self.adapter.write_text(
                    value, expected_sequence=before.sequence
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                return SelectionDisposition.PRESERVED
            if sequence is None:
                return SelectionDisposition.PRESERVED
            if self._is_restorable(before):
                try:
                    pasted = self._macos.paste(
                        target.window,
                        value,
                        sequence,
                        expected_selection=expected_selection,
                        sleep=self._sleep,
                        monotonic=self._monotonic,
                    )
                except Exception:
                    pasted = False
                if pasted:
                    self._sleep(self.restore_delay)
                    self._restore_if_owned(before, sequence, value)
                    return SelectionDisposition.PASTED
            try:
                if self.adapter.owns_text(sequence, value):
                    return SelectionDisposition.COPIED
            except Exception:
                pass
            return SelectionDisposition.PRESERVED

    def _publish_generated_text(
        self,
        text: str,
        *,
        should_paste: bool,
        paste_predicate: Callable[[], bool] | None = None,
    ) -> bool:
        """Write, conditionally paste, and restore only an owned snapshot."""

        value = str(text)
        with self._lock:
            try:
                previous = self._snapshot()
            except OSError:
                previous = None
            try:
                self.adapter.write_text(value)
            except Exception:
                if self._is_restorable(previous):
                    try:
                        self.adapter.restore(previous)
                    except (OSError, RuntimeError, TypeError, ValueError):
                        pass
                raise

            written_sequence = self._sequence()
            if (
                not should_paste
                or not self._is_restorable(previous)
                or written_sequence is None
            ):
                return False
            try:
                if paste_predicate is not None and not paste_predicate():
                    return False
                pasted = self._send_ctrl_v(value)
            except Exception:
                return False
            if pasted is not True:
                return False
            self._sleep(self.restore_delay)
            return self._restore_if_owned(previous, written_sequence, value)

    def apply_result(
        self, capture: SelectionCapture, result: str
    ) -> SelectionDisposition:
        """Verify the original selection before replacing it with ``result``."""

        if self._macos is not None:
            if capture is None or capture.context is None:
                return self._publish_macos(result, None)
            return self._publish_macos(
                result,
                capture.target,
                expected_selection=(capture.text, capture.context),
            )
        if not self.is_windows:
            self._write_visible_copy(result)
            return SelectionDisposition.COPIED
        if capture is None or not self.is_target_current(capture.target):
            self._publish_generated_text(result, should_paste=False)
            return SelectionDisposition.COPIED

        try:
            before = self._snapshot()
        except OSError:
            before = None
        if not self._is_restorable(before):
            self._publish_generated_text(result, should_paste=False)
            return SelectionDisposition.COPIED
        if not self.is_target_current(capture.target):
            self._publish_generated_text(result, should_paste=False)
            return SelectionDisposition.COPIED

        current, _before_sequence, copied_sequence = (
            self._copy_selected_text_with_sequence(
                before_copy=lambda: self.is_target_current(capture.target)
            )
        )
        safe = (
            self.is_target_current(capture.target)
            and isinstance(current, str)
            and _same_selected_text(current, capture.text)
        )
        if isinstance(current, str):
            self._restore_if_owned(before, copied_sequence, current)
        if safe and self.is_target_current(capture.target):
            pasted = self._publish_generated_text(
                result,
                should_paste=True,
                paste_predicate=lambda: self.is_target_current(capture.target),
            )
            return (
                SelectionDisposition.PASTED if pasted else SelectionDisposition.COPIED
            )
        self._publish_generated_text(result, should_paste=False)
        return SelectionDisposition.COPIED

    def write_dictation_result(
        self, target: SelectionTarget | None, text: str
    ) -> SelectionDisposition:
        """Publish dictation, pasting only into a verified native target."""

        if self._macos is not None:
            return self._publish_macos(text, target)
        if not self.is_windows:
            self._write_visible_copy(text)
            return SelectionDisposition.COPIED
        if target is None or not self.is_target_current(target):
            self._publish_generated_text(text, should_paste=False)
            return SelectionDisposition.COPIED
        pasted = self._publish_generated_text(
            text,
            should_paste=True,
            paste_predicate=lambda: self.is_target_current(target),
        )
        return SelectionDisposition.PASTED if pasted else SelectionDisposition.COPIED

    def owns_clipboard(self) -> bool:
        """Return whether the current clipboard can be safely snapshotted."""

        if not self.is_windows and self._macos is None:
            return False
        try:
            return self._is_restorable(self._snapshot())
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def publish(
        self,
        text: str,
        target: SelectionTarget | None,
        disposition: VoiceTranslationPublication,
    ) -> VoiceTranslationPublication:
        """Publish a voice result, downgrading an unsafe paste to copy-only."""

        value = str(text or "").strip()
        if not value:
            return VoiceTranslationPublication.NONE
        if self._macos is not None:
            paste_target = (
                target if disposition is VoiceTranslationPublication.PASTED else None
            )
            published = self.write_dictation_result(paste_target, value)
            return {
                SelectionDisposition.PASTED: VoiceTranslationPublication.PASTED,
                SelectionDisposition.COPIED: VoiceTranslationPublication.COPY_ONLY,
                SelectionDisposition.PRESERVED: VoiceTranslationPublication.REJECTED,
            }[published]
        if disposition is VoiceTranslationPublication.PASTED:
            safe = target is not None and self.is_target_current(target)
            try:
                pasted = self._publish_generated_text(
                    value,
                    should_paste=safe,
                    paste_predicate=(
                        None
                        if target is None
                        else lambda: self.is_target_current(target)
                    ),
                )
            except Exception:
                self._publish_generated_text(value, should_paste=False)
                return VoiceTranslationPublication.COPY_ONLY
            return (
                VoiceTranslationPublication.PASTED
                if pasted
                else VoiceTranslationPublication.COPY_ONLY
            )
        self._publish_generated_text(value, should_paste=False)
        return VoiceTranslationPublication.COPY_ONLY

    def activate(self, target: SelectionTarget) -> None:
        if target is not None and target.window:
            if self.is_windows:
                self._activate_window(target.window)
            elif self._macos is not None:
                try:
                    self._activate_window(target.window)
                except Exception:
                    pass

    def alt_pressed(self) -> bool:
        if not self.is_windows and self._macos is None:
            return False
        try:
            return bool(self._alt_pressed())
        except Exception:
            return False


# The Qt runtime historically used this descriptive name while the QML
# boundary is being split into its own module.  Both names refer to the same
# concrete implementation; neither path imports the legacy frontend.
QtClipboardGateway = QmlClipboardGateway


__all__ = [
    "QmlClipboardGateway",
    "QtClipboardGateway",
]
