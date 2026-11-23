"""Register desktop shortcuts with the macOS application event dispatcher."""

from __future__ import annotations

import ctypes as ct
from itertools import count

from PySide6.QtCore import QObject, Qt, Signal

from hotkey_config import (
    ActivationMode,
    HotkeyAction,
    HotkeyDefinition,
    HotkeySettings,
    HotkeyValidationError,
)


# macOS virtual key codes identify physical keys. The renderer uses
# KeyboardEvent.code for letters and digits so Option input still matches.
_KEYS = {
    "A": 0,
    "S": 1,
    "D": 2,
    "F": 3,
    "H": 4,
    "G": 5,
    "Z": 6,
    "X": 7,
    "C": 8,
    "V": 9,
    "B": 11,
    "Q": 12,
    "W": 13,
    "E": 14,
    "R": 15,
    "Y": 16,
    "T": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "9": 25,
    "7": 26,
    "8": 28,
    "0": 29,
    "O": 31,
    "U": 32,
    "I": 34,
    "P": 35,
    "L": 37,
    "J": 38,
    "K": 40,
    "N": 45,
    "M": 46,
}
_KEYS.update(
    zip(
        (f"F{number}" for number in range(1, 21)),
        (
            122,
            120,
            99,
            118,
            96,
            97,
            98,
            100,
            101,
            109,
            103,
            111,
            105,
            107,
            113,
            106,
            64,
            79,
            80,
            90,
        ),
        strict=True,
    )
)
_KEYS.update(
    SPACE=49, TAB=48, ENTER=36, ESCAPE=53, LEFT=123, RIGHT=124, DOWN=125, UP=126
)
_MODIFIERS = {"win": 1 << 8, "shift": 1 << 9, "alt": 1 << 11, "ctrl": 1 << 12}
_ESCAPE = (_KEYS["ESCAPE"], 0)
_NOT_HANDLED = -9874
_PRESSED, _RELEASED = 5, 6
_SIGNATURE = int.from_bytes(b"Clrf")


def default_hotkeys() -> HotkeySettings:
    # Option alone types characters such as @ on some macOS keyboard layouts.
    return HotkeySettings(
        {
            action: HotkeyDefinition(frozenset({"ctrl", "shift"}), shortcut.key)
            for action, shortcut in HotkeySettings.defaults().hotkeys.items()
        }
    )


class _EventType(ct.Structure):
    _fields_ = [("group", ct.c_uint32), ("kind", ct.c_uint32)]


class _HotkeyID(ct.Structure):
    _fields_ = [("signature", ct.c_uint32), ("number", ct.c_uint32)]


_Handler = ct.CFUNCTYPE(ct.c_int32, ct.c_void_p, ct.c_void_p, ct.c_void_p)


class _CarbonHotkeys:
    """Bind Carbon only when the macOS backend starts on the Qt thread."""

    def __init__(self, receive):
        carbon = ct.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")

        def bind(name, result, *arguments):
            function = getattr(carbon, name)
            function.restype, function.argtypes = result, arguments
            return function

        pointer = ct.c_void_p
        uint = ct.c_uint32
        status = ct.c_int32
        self._target = bind("GetApplicationEventTarget", pointer)()
        install = bind(
            "InstallEventHandler",
            status,
            pointer,
            _Handler,
            uint,
            ct.POINTER(_EventType),
            pointer,
            ct.POINTER(pointer),
        )
        self._remove_handler = bind("RemoveEventHandler", status, pointer)
        self._register = bind(
            "RegisterEventHotKey",
            status,
            uint,
            uint,
            _HotkeyID,
            pointer,
            uint,
            ct.POINTER(pointer),
        )
        self.unregister = bind("UnregisterEventHotKey", status, pointer)
        self._kind = bind("GetEventKind", uint, pointer)
        self._parameter = bind(
            "GetEventParameter",
            status,
            pointer,
            uint,
            uint,
            pointer,
            ct.c_size_t,
            pointer,
            pointer,
        )
        self._receive = receive
        self._callback = _Handler(self._handle)
        self._handler = pointer()
        keyboard = int.from_bytes(b"keyb")
        events = (_EventType * 2)(
            _EventType(keyboard, _PRESSED), _EventType(keyboard, _RELEASED)
        )
        result = install(
            self._target,
            self._callback,
            len(events),
            events,
            None,
            ct.byref(self._handler),
        )
        if result:
            raise OSError(f"Could not start macOS shortcuts ({result})")

    def _handle(self, _next, event, _context):
        hotkey = _HotkeyID()
        result = self._parameter(
            event,
            int.from_bytes(b"----"),
            int.from_bytes(b"hkid"),
            None,
            ct.sizeof(hotkey),
            None,
            ct.byref(hotkey),
        )
        if result or hotkey.signature != _SIGNATURE:
            return _NOT_HANDLED
        self._receive(hotkey.number, self._kind(event) == _PRESSED)
        return 0

    def register(self, combo, number):
        handle = ct.c_void_p()
        result = self._register(
            *combo, _HotkeyID(_SIGNATURE, number), self._target, 1, ct.byref(handle)
        )
        if result:
            raise OSError(f"macOS refused the shortcut ({result})")
        return handle

    def close(self):
        self._remove_handler(self._handler)


def _bindings(settings):
    desired = {}
    unsupported = {}
    for action, shortcut in settings.hotkeys.items():
        code = _KEYS.get(shortcut.key)
        if code is None:
            unsupported[action] = shortcut
            continue
        combo = code, sum(_MODIFIERS[modifier] for modifier in shortcut.modifiers)
        desired[combo] = (action.value, shortcut.display)
    return desired, unsupported


class MacGlobalHotkeyBackend(QObject):
    """Own macOS registrations for the Qt shell and Settings transactions."""

    triggered = Signal(str)
    restarted = Signal()
    availabilityChanged = Signal(list)
    _native_event = Signal(int, int, bool)

    def __init__(self, settings, *, native_factory=_CarbonHotkeys, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._native_factory = native_factory
        self._native = None
        self._registered = {}
        self._actions = {}
        self._unavailable = []
        self._key_down = set()
        self._held = None
        self._recording_active = False
        self._capturing = False
        self._generation = 0
        self._numbers = count(1)
        self._native_event.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    def start(self, _window):
        return self._configure(self._settings, allow_unavailable=True)

    def reconfigure(self, settings):
        return self._configure(settings)

    def _configure(self, settings, *, allow_unavailable=False):
        bindings, unsupported = _bindings(settings)
        if not allow_unavailable and any(
            self._settings.hotkeys.get(action) != shortcut
            for action, shortcut in unsupported.items()
        ):
            raise HotkeyValidationError(
                "Choose a modifier and a letter, number, or function key for macOS.",
                code="unsupported_key",
            )
        if self._capturing and not allow_unavailable:
            self._settings = settings
            return set(self._actions)
        recovering = self._native is None
        if recovering:
            self._native = self._native_factory(self._receive)
        try:
            previous, _ = _bindings(self._settings)
            optional = (
                bindings.keys()
                if allow_unavailable
                else {
                    combo
                    for combo, action in bindings.items()
                    if previous.get(combo) == action
                }
            )
            unavailable = self._replace(bindings, optional=optional)
        except Exception:
            if recovering:
                self.stop()
            raise
        self._release_hold()
        self._settings = settings
        unavailable.extend(shortcut.display for shortcut in unsupported.values())
        if unavailable != self._unavailable:
            self._unavailable = unavailable
            self.availabilityChanged.emit(unavailable)
        if recovering:
            self.restarted.emit()
        return set(self._actions)

    def _receive(self, number, pressed):
        self._native_event.emit(self._generation, number, pressed)

    def _replace(self, desired, *, optional=(), capturing=False):
        if self._recording_active and not capturing:
            desired = {**desired, _ESCAPE: ("escape", "Escape")}
        additions = {}
        unavailable = []
        for combo, (action, label) in desired.items():
            if combo in self._registered:
                continue
            number = next(self._numbers)
            try:
                handle = self._native.register(combo, number)
            except OSError as error:
                if action == "escape":
                    continue
                if combo in optional:
                    unavailable.append(label)
                    continue
                for _, handle in additions.values():
                    self._native.unregister(handle)
                raise OSError(f"Could not register {label}. {error}") from None
            additions[combo] = (number, handle)
        self._registered.update(additions)
        for combo in self._registered.keys() - desired.keys():
            number, handle = self._registered.pop(combo)
            self._key_down.discard(number)
            self._native.unregister(handle)
        self._actions = {
            number: desired[combo][0] for combo, (number, _) in self._registered.items()
        }
        return unavailable

    def set_recording_active(self, active):
        self._recording_active = bool(active)
        if self._native is not None and not self._capturing:
            bindings, _ = _bindings(self._settings)
            installed = {
                combo: bindings[combo]
                for combo in self._registered.keys() & bindings.keys()
            }
            self._replace(installed)

    def set_capture_active(self, active):
        if self._capturing == bool(active):
            return
        if self._native is not None:
            if active:
                self._replace({}, capturing=True)
            else:
                self._configure(self._settings, allow_unavailable=True)
        self._capturing = bool(active)
        self._generation += 1
        self._key_down.clear()
        self._release_hold()

    def _dispatch(self, generation, number, pressed):
        if generation != self._generation or self._capturing:
            return
        if not pressed:
            self._key_down.discard(number)
            if self._held == number:
                self._release_hold()
            return
        action = self._actions.get(number)
        if action is None or number in self._key_down:
            return
        self._key_down.add(number)
        if (
            action == HotkeyAction.RECORDING.value
            and self._settings.activation_mode is ActivationMode.PUSH_TO_TALK
        ):
            self._held = number
            action = "recording_hold_press"
        self.triggered.emit(action)

    def _release_hold(self):
        if self._held is not None:
            self._held = None
            self.triggered.emit("recording_hold_release")

    def stop(self):
        self._generation += 1
        self._key_down.clear()
        self._held = None
        self._capturing = False
        if self._native is not None:
            for _, handle in self._registered.values():
                self._native.unregister(handle)
            self._native.close()
            self._native = None
        self._registered.clear()
        self._actions.clear()
