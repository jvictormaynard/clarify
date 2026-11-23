"""Register desktop shortcuts with the macOS application event dispatcher."""

from __future__ import annotations

import ctypes as ct
from dataclasses import dataclass
from itertools import count

from PySide6.QtCore import QObject, Qt, QTimer, Signal

if __package__:
    from .macos_keyboard import (
        FLAGS_CHANGED,
        KEY_DOWN,
        KEY_UP,
        TAP_DISABLED,
        open_keyboard_listener,
    )
else:
    from macos_keyboard import (
        FLAGS_CHANGED,
        KEY_DOWN,
        KEY_UP,
        TAP_DISABLED,
        open_keyboard_listener,
    )

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
_FLAGS = {
    "fn": 1 << 23,
    "ctrl": 1 << 18,
    "alt": 1 << 19,
    "shift": 1 << 17,
    "win": 1 << 20,
}
_FLAGS_MASK = sum(_FLAGS.values())
_ESCAPE = (_KEYS["ESCAPE"], 0)
_KEYBOARD_ESCAPE = 0
_NOT_HANDLED = -9874
_PRESSED, _RELEASED = 5, 6
_SIGNATURE = int.from_bytes(b"Clrf")


def default_hotkeys() -> HotkeySettings:
    bindings = {
        action: HotkeyDefinition(frozenset({"ctrl", "shift"}), shortcut.key)
        for action, shortcut in HotkeySettings.defaults().hotkeys.items()
    }
    bindings[HotkeyAction.RECORDING] = HotkeyDefinition(frozenset(), "FN")
    return HotkeySettings(bindings, ActivationMode.PUSH_TO_TALK)


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


@dataclass(frozen=True)
class _ModifierChord:
    flags: int

    def definition(self):
        modifiers = [name for name, flag in _FLAGS.items() if self.flags & flag]
        key = modifiers.pop().upper()
        return HotkeyDefinition(frozenset(modifiers), key)


def _bindings(settings):
    desired = {}
    unsupported = {}
    special = {}
    for action, shortcut in settings.hotkeys.items():
        code = _KEYS.get(shortcut.key)
        key_modifier = _FLAGS.get(shortcut.key.lower())
        if key_modifier is not None:
            flags = sum(_FLAGS[name] for name in shortcut.modifiers)
            chord = _ModifierChord(flags | key_modifier)
            special.setdefault(chord, []).append((action, shortcut))
            continue
        if code is None or shortcut.uses_fn:
            unsupported[action] = shortcut
            continue
        combo = code, sum(_MODIFIERS[modifier] for modifier in shortcut.modifiers)
        desired[combo] = (action.value, shortcut.display)
    for chord, entries in special.items():
        if len(entries) > 1:
            unsupported.update(entries)
            continue
        action, shortcut = entries[0]
        desired[chord] = (action.value, shortcut.display)
    return desired, unsupported


class MacGlobalHotkeyBackend(QObject):
    """Own macOS registrations for the Qt shell and Settings transactions."""

    triggered = Signal(str)
    restarted = Signal()
    availabilityChanged = Signal(list)
    shortcutCaptured = Signal(object)
    _native_event = Signal(int, int, bool)
    _keyboard_action = Signal(int, int, bool)

    def __init__(
        self,
        settings,
        *,
        native_factory=_CarbonHotkeys,
        keyboard_factory=open_keyboard_listener,
        parent=None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._native_factory = native_factory
        self._keyboard_factory = keyboard_factory
        self._native = None
        self._keyboard = None
        self._keyboard_generation = 0
        self._keyboard_bindings = {}
        self._keyboard_timer = QTimer(self, singleShot=True, interval=200)
        self._keyboard_timer.timeout.connect(self._start_modifier_hold)
        self._modifier_flags = 0
        self._modifier_blocked = False
        self._modifier_chord = None
        self._keyboard_down = set()
        self._keyboard_hold = None
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
        self._keyboard_action.connect(
            self._dispatch_keyboard, Qt.ConnectionType.QueuedConnection
        )

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
                "This shortcut is unsupported or already assigned on macOS.",
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
        self._settings = settings
        self._reset_keyboard()
        self._release_hold()
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
        try:
            for combo, (action, label) in desired.items():
                if combo in self._registered:
                    continue
                number = next(self._numbers)
                try:
                    if isinstance(combo, _ModifierChord):
                        self._open_keyboard()
                        handle = None
                    else:
                        handle = self._native.register(combo, number)
                except OSError as error:
                    if action == "escape":
                        continue
                    if combo in optional:
                        unavailable.append(label)
                        continue
                    raise OSError(f"Could not register {label}. {error}") from None
                additions[combo] = (number, handle)
        except Exception:
            for _, handle in additions.values():
                if handle is not None:
                    self._native.unregister(handle)
            if not self._keyboard_bindings and not self._capturing:
                self._close_keyboard()
            raise
        self._registered.update(additions)
        for combo in self._registered.keys() - desired.keys():
            number, handle = self._registered.pop(combo)
            self._key_down.discard(number)
            if handle is not None:
                self._native.unregister(handle)
        self._actions = {
            number: desired[combo][0] for combo, (number, _) in self._registered.items()
        }
        self._keyboard_bindings = {
            combo: number
            for combo, (number, _) in self._registered.items()
            if isinstance(combo, _ModifierChord)
        }
        if not capturing and not self._keyboard_bindings:
            self._close_keyboard()
        return unavailable

    def _open_keyboard(self):
        if self._keyboard is None:
            self._keyboard = self._keyboard_factory(self._keyboard_event)

    def _close_keyboard(self):
        if self._keyboard is not None:
            self._keyboard.close()
            self._keyboard = None

    def _reset_keyboard(self, flags=None):
        self._keyboard_generation += 1
        self._key_down.difference_update(self._keyboard_bindings.values())
        self._keyboard_timer.stop()
        self._modifier_chord = self._keyboard_hold = None
        self._keyboard_down.clear()
        if flags is None:
            flags = self._keyboard.flags() if self._keyboard is not None else 0
        self._modifier_flags = flags & _FLAGS_MASK
        self._modifier_blocked = bool(self._modifier_flags)

    def _is_hold(self, number):
        return (
            self._actions.get(number) == HotkeyAction.RECORDING.value
            and self._settings.activation_mode is ActivationMode.PUSH_TO_TALK
        )

    def _start_modifier_hold(self):
        number = self._keyboard_bindings.get(self._modifier_chord)
        if self._is_hold(number):
            self._keyboard_hold = number
            self._emit_keyboard_action(number, True)

    def _emit_keyboard_action(self, number, pressed):
        self._keyboard_action.emit(self._keyboard_generation, number, pressed)

    def _dispatch_keyboard(self, generation, number, pressed):
        if generation != self._keyboard_generation or self._capturing:
            return
        if number == _KEYBOARD_ESCAPE:
            self.triggered.emit("escape")
        else:
            self._dispatch(self._generation, number, pressed)

    def _release_keyboard_hold(self):
        if self._keyboard_hold is not None:
            self._emit_keyboard_action(self._keyboard_hold, False)
            self._keyboard_hold = None

    def _finish_chord(self, chord):
        if self._capturing:
            self.shortcutCaptured.emit(chord.definition())
        else:
            number = self._keyboard_bindings.get(chord)
            if number is not None and not self._is_hold(number):
                self._emit_keyboard_action(number, True)
                self._emit_keyboard_action(number, False)

    def _keyboard_event(self, kind, code, flags, repeat):
        if kind in TAP_DISABLED:
            if self._held in self._keyboard_bindings.values():
                self._release_hold()
            self._reset_keyboard(flags)
            return
        flags &= _FLAGS_MASK
        if kind == FLAGS_CHANGED:
            previous, self._modifier_flags = self._modifier_flags, flags
            if flags == previous:
                return
            self._keyboard_timer.stop()
            self._release_keyboard_hold()
            if previous & ~flags:
                if self._modifier_chord is not None:
                    self._finish_chord(self._modifier_chord)
                self._modifier_chord = None
                self._modifier_blocked = bool(flags)
            elif not self._modifier_blocked and not self._keyboard_down:
                self._modifier_chord = _ModifierChord(flags)
                if self._is_hold(self._keyboard_bindings.get(self._modifier_chord)):
                    self._keyboard_timer.start()
            return
        if kind == KEY_UP:
            self._keyboard_down.discard(code)
            return
        if repeat:
            return
        self._keyboard_timer.stop()
        self._modifier_chord = None
        self._modifier_blocked = bool(flags)
        # Carbon only registers unmodified Escape. A held chord may still
        # have modifiers down when the user cancels.
        if kind == KEY_DOWN and code == _ESCAPE[0] and self._keyboard_hold is not None:
            self._emit_keyboard_action(_KEYBOARD_ESCAPE, True)
        self._release_keyboard_hold()
        if kind == KEY_DOWN:
            self._keyboard_down.add(code)

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
            if active and self._native is not None and self._keyboard is None:
                try:
                    self._open_keyboard()
                except OSError:
                    return False
                self._reset_keyboard()
            return self._capturing and self._keyboard is not None
        if self._native is not None:
            if active:
                try:
                    self._open_keyboard()
                except OSError:
                    # Ordinary shortcuts can still be captured by the renderer.
                    pass
                self._replace({}, capturing=True)
            else:
                self._configure(self._settings, allow_unavailable=True)
        self._capturing = bool(active)
        self._generation += 1
        self._key_down.clear()
        self._release_hold()
        self._reset_keyboard()
        return self._capturing and self._keyboard is not None

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
        if self._is_hold(number):
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
        self._close_keyboard()
        self._reset_keyboard()
        if self._native is not None:
            for _, handle in self._registered.values():
                if handle is not None:
                    self._native.unregister(handle)
            self._native.close()
            self._native = None
        self._registered.clear()
        self._actions.clear()
        self._keyboard_bindings.clear()
