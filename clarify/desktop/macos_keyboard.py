"""Listen for macOS shortcut events on the owning Qt run loop."""

from __future__ import annotations

import ctypes as ct
from functools import cache

if __package__:
    from . import macos_clipboard
else:
    import macos_clipboard


KEY_DOWN, KEY_UP, FLAGS_CHANGED = 10, 11, 12
MOUSE_DOWN = (1, 3, 25)
TAP_DISABLED = (0xFFFFFFFE, 0xFFFFFFFF)
_Callback = ct.CFUNCTYPE(
    ct.c_void_p, ct.c_void_p, ct.c_uint32, ct.c_void_p, ct.c_void_p
)
_LISTEN_EVENT = 1  # kIOHIDRequestTypeListenEvent
_ACCESS_GRANTED = 0  # kIOHIDAccessTypeGranted
_EVENT_MASK = sum(1 << kind for kind in (KEY_DOWN, KEY_UP, FLAGS_CHANGED, *MOUSE_DOWN))


@cache
def _quartz():
    return ct.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")


@cache
def _input_monitoring_api():
    library = ct.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
    check, request = library.IOHIDCheckAccess, library.IOHIDRequestAccess
    check.argtypes = request.argtypes = [ct.c_int]
    check.restype, request.restype = ct.c_int, ct.c_bool
    return check, request


def input_monitoring_allowed(*, request=False):
    check, prompt = _input_monitoring_api()
    return (
        bool(prompt(_LISTEN_EVENT))
        if request
        else check(_LISTEN_EVENT) == _ACCESS_GRANTED
    )


def keyboard_access_allowed(*, request=False):
    # Accessibility also allows listening on macOS. Check it before requesting
    # a second permission for the same capability.
    return (
        macos_clipboard.accessibility_allowed()
        or input_monitoring_allowed()
        or (request and input_monitoring_allowed(request=True))
    )


def open_keyboard_listener(receive):
    if macos_clipboard.accessibility_allowed():
        try:
            return _AppKitKeyboardListener(receive)
        except OSError:
            if not input_monitoring_allowed():
                raise
    return _QuartzKeyboardListener(receive)


class _AppKitKeyboardListener:
    """Read modifier events in the Qt process and in other apps, including Electron."""

    def __init__(self, receive):
        self._event = macos_clipboard._appkit().NSEvent
        self._monitors = []

        def handle(event):
            kind = int(event.type())
            code = (
                int(event.keyCode()) if kind in (KEY_DOWN, KEY_UP, FLAGS_CHANGED) else 0
            )
            repeat = kind == KEY_DOWN and bool(event.isARepeat())
            receive(kind, code, int(event.modifierFlags()), repeat)

        def handle_local(event):
            handle(event)
            return event

        try:
            for add, handler in (
                (self._event.addGlobalMonitorForEventsMatchingMask_handler_, handle),
                (
                    self._event.addLocalMonitorForEventsMatchingMask_handler_,
                    handle_local,
                ),
            ):
                monitor = add(_EVENT_MASK, handler)
                if monitor is None:
                    raise OSError("Could not start the macOS keyboard monitor.")
                self._monitors.append(monitor)
        except Exception:
            self.close()
            raise

    def flags(self):
        return int(self._event.modifierFlags())

    def close(self):
        for monitor in self._monitors:
            self._event.removeMonitor_(monitor)
        self._monitors.clear()


class _QuartzKeyboardListener:
    """Use a listen-only session tap so ordinary keyboard input still reaches apps."""

    def __init__(self, receive):
        quartz = _quartz()
        core = ct.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )

        def bind(library, name, result, *arguments):
            function = getattr(library, name)
            function.restype, function.argtypes = result, arguments
            return function

        if not input_monitoring_allowed():
            raise OSError(
                "Allow Clarify in macOS Settings > Privacy & Security > Input Monitoring."
            )

        ptr, uint, mask = ct.c_void_p, ct.c_uint32, ct.c_uint64
        create = bind(
            quartz, "CGEventTapCreate", ptr, uint, uint, uint, mask, _Callback, ptr
        )
        self._enable = bind(quartz, "CGEventTapEnable", None, ptr, ct.c_bool)
        self._get_flags = bind(quartz, "CGEventGetFlags", mask, ptr)
        self._get_field = bind(
            quartz, "CGEventGetIntegerValueField", ct.c_int64, ptr, uint
        )
        self._source_flags = bind(quartz, "CGEventSourceFlagsState", mask, ct.c_int32)
        create_source = bind(
            core, "CFMachPortCreateRunLoopSource", ptr, ptr, ptr, ct.c_long
        )
        self._release = bind(core, "CFRelease", None, ptr)
        self._invalidate = bind(core, "CFMachPortInvalidate", None, ptr)
        self._remove_source = bind(core, "CFRunLoopRemoveSource", None, ptr, ptr, ptr)
        add_source = bind(core, "CFRunLoopAddSource", None, ptr, ptr, ptr)
        self._run_loop = bind(core, "CFRunLoopGetCurrent", ptr)()
        self._mode = ptr.in_dll(core, "kCFRunLoopCommonModes")
        self._receive = receive
        self._callback = _Callback(self._handle)
        # kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionListenOnly
        self._tap = create(1, 0, 1, _EVENT_MASK, self._callback, None)
        if not self._tap:
            raise OSError("Could not start the macOS keyboard listener.")
        self._source = create_source(None, self._tap, 0)
        if not self._source:
            self.close()
            raise OSError("Could not start the macOS keyboard listener.")
        add_source(self._run_loop, self._source, self._mode)
        self._enable(self._tap, True)

    def flags(self):
        return self._source_flags(0)  # kCGEventSourceStateCombinedSessionState

    def _handle(self, _proxy, kind, event, _context):
        if kind in TAP_DISABLED:
            self._enable(self._tap, True)
            self._receive(kind, 0, self.flags(), False)
        elif kind in (KEY_DOWN, KEY_UP):
            # kCGKeyboardEventKeycode and kCGKeyboardEventAutorepeat
            self._receive(
                kind,
                self._get_field(event, 9),
                self._get_flags(event),
                kind == KEY_DOWN and bool(self._get_field(event, 8)),
            )
        else:
            self._receive(kind, 0, self._get_flags(event), False)
        return event

    def close(self):
        self._enable(self._tap, False)
        if self._source:
            self._remove_source(self._run_loop, self._source, self._mode)
            self._release(self._source)
        self._invalidate(self._tap)
        self._release(self._tap)
