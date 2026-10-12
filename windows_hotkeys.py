"""Native Windows global-hotkey and synthetic-key helpers for Clarify."""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass
from ctypes import wintypes

from hotkey_config import (
    HotkeyAction,
    HotkeyDefinition,
    HotkeySettings,
    HotkeyValidationError,
)


WM_HOTKEY = 0x0312
WM_PASTE = 0x0302
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
EM_GETSEL = 0x00B0
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_MENU = 0x12
VK_ESCAPE = 0x1B
ESCAPE_HOTKEY_ID = 0x5105

HOTKEY_SPECS = {
    0x5101: ("recording_hotkey", ord("L")),
    0x5102: ("rewrite_hotkey", ord("K")),
    0x5103: ("translation_hotkey", ord("T")),
    0x5104: ("toggle_visibility", ord("R")),
    0x5106: ("voice_translation_hotkey", ord("V")),
}
HOTKEY_IDS_BY_ACTION = {spec[0]: hotkey_id for hotkey_id, spec in HOTKEY_SPECS.items()}


class HotkeyRegistrationError(RuntimeError):
    """Registration failed; no partially active shortcut set remains."""

    def __init__(
        self, failed_actions, *, registered=(), reason="RegisterHotKey failed"
    ):
        self.failed_actions = tuple(str(action) for action in failed_actions)
        self.registered = frozenset(int(item) for item in registered)
        self.reason = str(reason)
        actions = ", ".join(self.failed_actions) or "unknown action"
        super().__init__(
            f"Could not register hotkey(s) for {actions}: {self.reason}. "
            "Choose a different combination and try again."
        )


_CONFIRMABLE_PASTE_CLASSES = frozenset(
    {
        "Edit",
        "RichEdit20A",
        "RichEdit20W",
        "RICHEDIT50A",
        "RICHEDIT50W",
        "RICHEDIT60A",
        "RICHEDIT60W",
    }
)
_MAX_CONFIRMABLE_CONTROL_TEXT = 4 * 1024 * 1024


class _GUIThreadInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
    ]


def action_for_hotkey_id(hotkey_id: int) -> str | None:
    if int(hotkey_id) == ESCAPE_HOTKEY_ID:
        return "escape"
    spec = HOTKEY_SPECS.get(int(hotkey_id))
    return spec[0] if spec else None


def _hotkey_modifier_mask(definition: HotkeyDefinition) -> int:
    modifiers = {
        "alt": MOD_ALT,
        "ctrl": MOD_CONTROL,
        "shift": MOD_SHIFT,
        "win": MOD_WIN,
    }
    return sum(modifiers[name] for name in definition.modifiers) | MOD_NOREPEAT


def _hotkey_virtual_key(key: str) -> int:
    key = str(key).upper()
    if key.startswith("F") and key[1:].isdigit():
        return 0x70 + int(key[1:]) - 1
    special_keys = {
        "SPACE": 0x20,
        "TAB": 0x09,
        "ENTER": 0x0D,
        "ESCAPE": 0x1B,
        "UP": 0x26,
        "DOWN": 0x28,
        "LEFT": 0x25,
        "RIGHT": 0x27,
        "CTRL": 0x11,
        "ALT": 0x12,
        "SHIFT": 0x10,
        "WIN": 0x5B,
        "XBUTTON1": 0x05,
        "XBUTTON2": 0x06,
    }
    if key in special_keys:
        return special_keys[key]
    return ord(key)


def _normalised_registration_settings(settings=None) -> HotkeySettings:
    if settings is None:
        return HotkeySettings.defaults()
    if isinstance(settings, HotkeySettings):
        return settings
    if isinstance(settings, dict):
        if any(
            str(key) in {action.value for action in HotkeyAction} for key in settings
        ):
            return HotkeySettings(settings)
        return HotkeySettings.from_mapping(settings)
    return HotkeySettings.from_mapping(settings)


def register_global_hotkeys(user32, hwnd, settings=None, *, strict=False) -> set[int]:
    """Register configured shortcuts and return successful IDs.

    ``strict=True`` is used by the tray and settings transaction. It cleans up
    every successful registration when one action is unavailable, so a failed
    Apply can never leave a stale or partially active set. The default keeps
    the historical best-effort return contract for integrations that only
    need to inspect which IDs the OS accepted.
    """
    try:
        configured = _normalised_registration_settings(settings)
    except HotkeyValidationError:
        raise
    user32.RegisterHotKey.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.RegisterHotKey.restype = wintypes.BOOL
    registered: set[int] = set()
    failed: list[str] = []
    for action in HotkeyAction:
        hotkey_id = HOTKEY_IDS_BY_ACTION[action.value]
        # Legacy configurations predate voice translation and intentionally
        # omit its binding.  Skipping an omitted action keeps those users'
        # existing shortcuts registered even if Alt+V belongs to another app.
        try:
            definition = configured.definition(action)
        except KeyError:
            continue
        if definition.requires_hook:
            continue
        if user32.RegisterHotKey(
            hwnd,
            hotkey_id,
            _hotkey_modifier_mask(definition),
            _hotkey_virtual_key(definition.key),
        ):
            registered.add(hotkey_id)
        else:
            failed.append(action.value)
    if failed and strict:
        unregister_global_hotkeys(user32, hwnd, registered)
        reason = "the combination is already registered by another application"
        get_last_error = getattr(ctypes, "get_last_error", None)
        if callable(get_last_error):
            last_error = get_last_error()
            if last_error:
                reason = f"Windows error {last_error}"
        raise HotkeyRegistrationError(failed, registered=registered, reason=reason)
    return registered


def unregister_global_hotkeys(user32, hwnd, registered: set[int]) -> None:
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    for hotkey_id in tuple(registered):
        try:
            user32.UnregisterHotKey(hwnd, hotkey_id)
        except (AttributeError, OSError, TypeError):
            pass


class WindowsHotkeyRegistration:
    """Transactional registration state for the native tray thread."""

    def __init__(self, user32, hwnd, settings=None):
        self.user32 = user32
        self.hwnd = hwnd
        self.settings = _normalised_registration_settings(settings)
        self.registered: set[int] = set()

    def register(self, settings=None) -> set[int]:
        selected = (
            _normalised_registration_settings(settings)
            if settings is not None
            else self.settings
        )
        ids = register_global_hotkeys(self.user32, self.hwnd, selected, strict=True)
        self.settings = selected
        self.registered = set(ids)
        return set(ids)

    def unregister(self) -> None:
        unregister_global_hotkeys(self.user32, self.hwnd, self.registered)
        self.registered.clear()

    def replace(self, settings) -> set[int]:
        """Replace the set atomically, restoring the old set on failure."""
        selected = _normalised_registration_settings(settings)
        previous = self.settings
        previous_was_registered = bool(self.registered)
        self.unregister()
        try:
            return self.register(selected)
        except Exception:
            self.settings = previous
            if previous_was_registered:
                try:
                    self.register(previous)
                except Exception:
                    # There is deliberately no stale state to report: the OS
                    # has no registered IDs and the next Apply can retry.
                    self.registered.clear()
            raise


_MODIFIER_KEYS = {
    0x11: "CTRL",
    0xA2: "CTRL",
    0xA3: "CTRL",
    0x12: "ALT",
    0xA4: "ALT",
    0xA5: "ALT",
    0x10: "SHIFT",
    0xA0: "SHIFT",
    0xA1: "SHIFT",
    0x5B: "WIN",
    0x5C: "WIN",
}


@dataclass
class _ModifierPress:
    hotkey_id: int
    expected: set[str]
    clean: bool
    held: bool
    started_at: float


class HookHotkeyState:
    """Match modifier taps and side buttons without capturing text.

    Modifier taps wait for release. Holding a recording modifier waits 200 ms
    and is cancelled when another input turns it into an ordinary chord.
    """

    def __init__(self, settings, *, clock=time.monotonic):
        self.bindings = {
            definition.combination: HOTKEY_IDS_BY_ACTION[action.value]
            for action, definition in settings.hotkeys.items()
            if definition.requires_hook
        }
        self.ids = set(self.bindings.values())
        self.hold = settings.activation_mode.value == "push_to_talk"
        self.clock = clock
        self.down: dict[int, str] = {}
        self.pending: dict[int, _ModifierPress] = {}
        self.mouse_down: dict[str, int] = {}

    def _invalidate(self, key):
        events = []
        for candidate in self.pending.values():
            if key not in candidate.expected:
                if candidate.held:
                    events.append((candidate.hotkey_id, "release"))
                candidate.clean = False
                candidate.held = False
        return events

    def keyboard(self, virtual_key, pressed):
        key = _MODIFIER_KEYS.get(virtual_key, str(virtual_key))
        if pressed:
            if virtual_key in self.down:
                return []
            events = self._invalidate(key)
            duplicate_modifier = (
                key in _MODIFIER_KEYS.values() and key in self.down.values()
            )
            if duplicate_modifier:
                events.extend(self._invalidate("duplicate modifier"))
            modifiers = frozenset(
                k.lower()
                for k in self.down.values()
                if k in {"CTRL", "ALT", "SHIFT", "WIN"} and k != key
            )
            self.down[virtual_key] = key
            identifier = self.bindings.get((modifiers, key))
            if identifier is not None:
                expected = {key, *(m.upper() for m in modifiers)}
                clean = not duplicate_modifier and set(self.down.values()) <= expected
                self.pending[virtual_key] = _ModifierPress(
                    identifier, expected, clean, False, self.clock()
                )
            return events
        self.down.pop(virtual_key, None)
        candidate = self.pending.pop(virtual_key, None)
        events = []
        if candidate:
            if candidate.held:
                events.append((candidate.hotkey_id, "release"))
            elif candidate.clean and not (self.hold and candidate.hotkey_id == 0x5101):
                events.append((candidate.hotkey_id, "tap"))
        # Releasing a required modifier also ends a special-key chord.
        events.extend(self._invalidate(key + " released"))
        return events

    def mouse(self, key, pressed):
        events = self._invalidate(key) if pressed else []
        if not pressed:
            identifier = self.mouse_down.pop(key, None)
            return identifier is not None, events + (
                [(identifier, "release")] if identifier is not None else []
            )
        if key in self.mouse_down:
            return True, events
        modifiers = frozenset(
            k.lower()
            for k in self.down.values()
            if k in {"CTRL", "ALT", "SHIFT", "WIN"}
        )
        identifier = self.bindings.get((modifiers, key))
        if identifier is None:
            return False, events
        self.mouse_down[key] = identifier
        return True, events + [(identifier, "press")]

    def poll(self):
        events = []
        if self.hold:
            for candidate in self.pending.values():
                if (
                    candidate.hotkey_id == 0x5101
                    and candidate.clean
                    and not candidate.held
                    and self.clock() - candidate.started_at >= 0.2
                ):
                    candidate.held = True
                    events.append((candidate.hotkey_id, "press"))
        return events


class WindowsInputHook:
    """Scoped low-level hooks. The owning Qt loop performs all application work."""

    class KeyboardData(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("extra", ctypes.c_size_t),
        ]

    class MouseData(ctypes.Structure):
        _fields_ = [
            ("point", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("extra", ctypes.c_size_t),
        ]

    def __init__(self, user32, settings, emit):
        self.user32 = user32
        self.state = HookHotkeyState(settings)
        self.ids = self.state.ids
        self.needs_poll = self.state.hold and any(
            key in _MODIFIER_KEYS.values() and identifier == 0x5101
            for (_, key), identifier in self.state.bindings.items()
        )
        self.emit = emit
        self.handles = []
        self.callbacks = []

    def start(self):
        if not self.ids:
            return
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )
        self.user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            callback_type,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        self.user32.SetWindowsHookExW.restype = wintypes.HANDLE
        self.user32.CallNextHookEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
        self.user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self.user32.keybd_event.argtypes = [
            wintypes.BYTE,
            wintypes.BYTE,
            wintypes.DWORD,
            ctypes.c_size_t,
        ]
        self.user32.keybd_event.restype = None
        # A held modifier may predate startup or an Apply transaction. Seed
        # its state without treating it as a new shortcut press.
        for virtual_key in (0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C):
            if physical_key_down(self.user32, virtual_key):
                self.state.down[virtual_key] = _MODIFIER_KEYS[virtual_key]
        try:
            for kind, handler in ((13, self._keyboard), (14, self._mouse)):
                callback = callback_type(handler)
                self.callbacks.append(callback)
                handle = self.user32.SetWindowsHookExW(kind, callback, None, 0)
                if not handle:
                    raise HotkeyRegistrationError(
                        [], reason="Windows could not install the input hook"
                    )
                self.handles.append(handle)
        except BaseException:
            self.stop()
            raise

    def stop(self):
        for handle in self.handles:
            self.user32.UnhookWindowsHookEx(handle)
        self.handles.clear()
        self.callbacks.clear()

    def poll(self):
        self._emit(self.state.poll())

    def _emit(self, events):
        for identifier, phase in events:
            self.emit(identifier, phase)

    def _keyboard(self, code, message, pointer):
        if code >= 0 and message in {0x100, 0x101, 0x104, 0x105}:
            data = ctypes.cast(pointer, ctypes.POINTER(self.KeyboardData)).contents
            if not data.flags & 0x10:  # Ignore synthetic clipboard and paste keys.
                events = self.state.keyboard(data.vkCode, message in {0x100, 0x104})
                if data.vkCode in {0x5B, 0x5C} and events and message in {0x101, 0x105}:
                    # A harmless synthetic key prevents a clean Win tap from
                    # opening Start. The real Win release still reaches Windows.
                    self.user32.keybd_event(0xFF, 0, 0, 0)
                    self.user32.keybd_event(0xFF, 0, 2, 0)
                self._emit(events)
        return self.user32.CallNextHookEx(None, code, message, pointer)

    def _mouse(self, code, message, pointer):
        if code >= 0 and message in {0x201, 0x204, 0x207, 0x20A, 0x20B, 0x20C, 0x20E}:
            data = ctypes.cast(pointer, ctypes.POINTER(self.MouseData)).contents
            if not data.flags & 1:
                button = (data.mouseData >> 16) & 0xFFFF
                key = f"XBUTTON{button}" if message in {0x20B, 0x20C} else "OTHER_MOUSE"
                consumed, events = self.state.mouse(key, message != 0x20C)
                self._emit(events)
                if consumed:
                    return 1
        return self.user32.CallNextHookEx(None, code, message, pointer)


def supports_push_to_talk() -> bool:
    """Whether this native layer can observe key-up edges safely.

    RegisterHotKey delivers WM_HOTKEY key-down notifications only. Until a
    keyboard-hook adapter with explicit lifecycle ownership is added, the
    packaged Windows path exposes toggle mode and rejects push-to-talk.
    """
    return False


def supports_qt_push_to_talk() -> bool:
    """The Qt shell owns a scoped physical-key release timer on Windows."""
    import sys

    return sys.platform == "win32"


def physical_key_down(user32, virtual_key: int) -> bool:
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    return bool(user32.GetAsyncKeyState(virtual_key) & 0x8000)


def hotkey_physical_keys(definition: HotkeyDefinition) -> tuple[int, ...]:
    modifiers = {"alt": 0x12, "ctrl": 0x11, "shift": 0x10, "win": 0x5B}
    return (
        _hotkey_virtual_key(definition.key),
        *(modifiers[key] for key in definition.modifiers),
    )


def register_escape_hotkey(user32, hwnd) -> bool:
    """Capture Escape without modifiers for the active recording session only."""
    user32.RegisterHotKey.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.RegisterHotKey.restype = wintypes.BOOL
    return bool(user32.RegisterHotKey(hwnd, ESCAPE_HOTKEY_ID, MOD_NOREPEAT, VK_ESCAPE))


def unregister_escape_hotkey(user32, hwnd) -> None:
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey(hwnd, ESCAPE_HOTKEY_ID)


def is_alt_pressed() -> bool:
    """Read the physical Alt state without installing a keyboard hook."""
    return bool(getattr(ctypes, "windll").user32.GetAsyncKeyState(VK_MENU) & 0x8000)


def _focused_control_for_foreground(user32):
    """Return the focused child of the current foreground window, if any."""
    user32.GetForegroundWindow.restype = wintypes.HWND
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return None

    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    thread_id = user32.GetWindowThreadProcessId(foreground, None)
    if not thread_id:
        return None

    info = _GUIThreadInfo()
    info.cbSize = ctypes.sizeof(info)
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUIThreadInfo)]
    user32.GetGUIThreadInfo.restype = wintypes.BOOL
    if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
        return None
    focused = info.hwndFocus or info.hwndActive
    if not focused:
        return None
    if focused != foreground:
        user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.IsChild.restype = wintypes.BOOL
        if not user32.IsChild(foreground, focused):
            return None
    return focused


def _window_class_name(user32, hwnd) -> str | None:
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    buffer = ctypes.create_unicode_buffer(256)
    length = user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value if length else None


def _send_message_timeout(user32, hwnd, message, wparam, lparam, timeout_ms):
    """Send a control query with the same bounded timeout as WM_PASTE."""
    result = ctypes.c_size_t()
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wintypes.BOOL
    try:
        delivered = user32.SendMessageTimeoutW(
            hwnd,
            message,
            wparam,
            lparam,
            SMTO_BLOCK | SMTO_ABORTIFHUNG,
            int(timeout_ms),
            ctypes.byref(result),
        )
    except (AttributeError, OSError, TypeError):
        return None
    return result.value if delivered else None


def _control_state(user32, hwnd, timeout_ms):
    """Read plain text and selection bounds from a standard text control."""
    length_result = _send_message_timeout(
        user32, hwnd, WM_GETTEXTLENGTH, 0, 0, timeout_ms
    )
    if length_result is None:
        return None
    length = int(length_result)
    if length < 0 or length > _MAX_CONFIRMABLE_CONTROL_TEXT:
        return None
    buffer = ctypes.create_unicode_buffer(length + 1)
    copied = _send_message_timeout(
        user32, hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buffer), timeout_ms
    )
    if copied is None or copied < 0:
        return None

    start = ctypes.c_int()
    end = ctypes.c_int()
    selection_result = _send_message_timeout(
        user32,
        hwnd,
        EM_GETSEL,
        ctypes.addressof(start),
        ctypes.addressof(end),
        timeout_ms,
    )
    if selection_result is None:
        return None
    if start.value < 0 or end.value < start.value or end.value > length:
        return None
    return buffer.value, start.value, end.value


def _paste_result_matches(before, after, expected_text: str) -> bool:
    if before is None or after is None:
        return False
    before_text, start, end = before
    after_text, after_start, after_end = after
    # EM_GETSEL counts UTF-16 code units; avoid guessing around surrogate
    # pairs when Python's string indexes use Unicode code points.
    if len(before_text.encode("utf-16-le")) // 2 != len(before_text):
        return False
    expected_variants = {
        str(expected_text),
        str(expected_text).replace("\n", "\r\n"),
    }
    suffix = before_text[end:]
    prefix = before_text[:start]
    for inserted in expected_variants:
        if after_text != prefix + inserted + suffix:
            continue
        expected_caret = start + len(inserted.encode("utf-16-le")) // 2
        if after_start == after_end == expected_caret:
            return True
    return False


def paste_focused_control(
    expected_text: str | None = None, timeout_ms: int = 250, *, user32=None
) -> bool | None:
    """Paste synchronously into a compatible focused control when possible.

    ``SendMessageTimeoutW`` only proves that a standard text control returned
    from its window procedure. When the expected text is supplied, confirmation
    additionally requires the control's text and caret to match the predicted
    insertion. Custom, read-only, limited, and otherwise unobservable controls
    fall back to key injection without claiming consumption.
    """
    if user32 is None:
        user32 = getattr(ctypes, "windll").user32
    try:
        focused = _focused_control_for_foreground(user32)
        class_name = _window_class_name(user32, focused) if focused else None
        if (
            expected_text is not None
            and focused is not None
            and class_name in _CONFIRMABLE_PASTE_CLASSES
        ):
            before = _control_state(user32, focused, timeout_ms)
            if before is None:
                return send_ctrl_key("v")
            try:
                delivered = _send_message_timeout(
                    user32, focused, WM_PASTE, 0, 0, timeout_ms
                )
            except (AttributeError, OSError, TypeError):
                # The message may have crossed the process boundary before
                # the API reported an error; never inject a second paste.
                return None
            if delivered is not None:
                try:
                    after = _control_state(user32, focused, timeout_ms)
                except (AttributeError, OSError, TypeError):
                    return None
                if _paste_result_matches(before, after, expected_text):
                    return True
            # WM_PASTE was attempted. A timeout or an unverifiable/malformed
            # state must not be followed by Ctrl+V, which could double-paste
            # if the original message was delivered late.
            return None
    except (AttributeError, OSError, TypeError):
        pass
    return send_ctrl_key("v")


def send_ctrl_key(letter: str) -> bool | None:
    """Inject Ctrl plus one ASCII letter without claiming paste consumption."""
    virtual_key = ord(str(letter).upper())
    user32 = getattr(ctypes, "windll").user32
    key_up = 0x0002
    try:
        user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, key_up, 0)
        user32.keybd_event(0x11, 0, key_up, 0)  # Ctrl up
        # keybd_event is void; successful injection is not proof that the
        # target consumed Ctrl+V. Returning None keeps the result available.
        return None
    except OSError:
        return False
