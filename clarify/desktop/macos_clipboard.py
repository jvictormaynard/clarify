"""AppKit pasteboard and Accessibility focus support for the desktop gateway."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
import os
from types import SimpleNamespace
from typing import Any


_MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
_PASTEBOARD_TYPES = {
    "public.utf8-plain-text",
    "public.utf16-plain-text",
    "public.utf16-external-plain-text",
    "public.html",
    "public.rtf",
    "public.png",
    "public.tiff",
    "public.url",
    "public.file-url",
    "public.url-name",
}
_AX_RANGE_TYPE = 4  # kAXValueCFRangeType
_ANSI_V_KEY = 9  # kVK_ANSI_V


@cache
def _appkit():
    import AppKit

    return AppKit


@cache
def _quartz():
    import Quartz

    return Quartz


@cache
def _accessibility():
    # Bind the required public HIServices functions with the existing PyObjC
    # runtime. The Quartz wheel exposes CGEvent, but does not wrap AXUIElement.
    import objc

    functions = {}
    framework = objc.loadBundle(
        "ClarifyHIServices",
        functions,
        bundle_path=(
            "/System/Library/Frameworks/ApplicationServices.framework/"
            "Frameworks/HIServices.framework"
        ),
    )
    objc.loadBundleFunctions(
        framework,
        functions,
        [
            ("AXIsProcessTrusted", b"B"),
            ("AXUIElementGetTypeID", b"Q"),
            ("AXValueGetTypeID", b"Q"),
            (
                "AXUIElementCreateApplication",
                b"^{__AXUIElement=}i",
                "",
                {"retval": {"already_cfretained": True}},
            ),
            (
                "AXUIElementCopyAttributeValue",
                b"i^{__AXUIElement=}^{__CFString=}o^@",
                "",
                {"arguments": {2: {"already_cfretained": True}}},
            ),
            ("AXUIElementSetMessagingTimeout", b"i^{__AXUIElement=}f"),
            ("AXValueGetValue", b"B^{__AXValue=}Io^{_CFRange=qq}"),
        ],
        skip_undefined=False,
    )
    objc.registerCFSignature(
        "AXUIElementRef", b"^{__AXUIElement=}", functions["AXUIElementGetTypeID"]()
    )
    objc.registerCFSignature(
        "AXValueRef", b"^{__AXValue=}", functions["AXValueGetTypeID"]()
    )
    return SimpleNamespace(**functions)


@dataclass(frozen=True)
class MacOSFocusTarget:
    app: Any
    pid: int
    executable: str | None
    window: Any = None
    element: Any = None


@dataclass(frozen=True)
class MacOSPasteboardSnapshot:
    items: tuple[tuple[tuple[str, bytes], ...], ...]
    sequence: int
    restorable: bool = True


class MacOSClipboard:
    """Snapshot pasteboard items and send input to a verified application."""

    @staticmethod
    def _board():
        return _appkit().NSPasteboard.generalPasteboard()

    def sequence(self) -> int:
        return int(self._board().changeCount())

    def text(self) -> str | None:
        return self._board().stringForType_(_appkit().NSPasteboardTypeString)

    def snapshot(self) -> MacOSPasteboardSnapshot:
        try:
            board = self._board()
            sequence = int(board.changeCount())
            items = board.pasteboardItems()
            unavailable = MacOSPasteboardSnapshot((), sequence, restorable=False)
            if items is None:
                return unavailable

            saved = []
            size = 0
            for item in items:
                formats = tuple(item.types())
                if not formats or not _PASTEBOARD_TYPES.issuperset(formats):
                    return unavailable
                saved_formats = []
                for format_name in formats:
                    data = item.dataForType_(format_name)
                    if data is None:
                        return unavailable
                    size += len(data)
                    if size > _MAX_SNAPSHOT_BYTES:
                        return unavailable
                    saved_formats.append((str(format_name), bytes(data)))
                saved.append(tuple(saved_formats))
            if int(board.changeCount()) != sequence:
                return unavailable
            return MacOSPasteboardSnapshot(tuple(saved), sequence)
        except (
            ImportError,
            AttributeError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            raise OSError("could not snapshot the macOS pasteboard") from error

    @staticmethod
    def _replace_items(
        board, items, *, expected_sequence: int | None = None
    ) -> int | None:
        if (
            expected_sequence is not None
            and int(board.changeCount()) != expected_sequence
        ):
            return None
        sequence = int(board.clearContents())
        if int(board.changeCount()) != sequence:
            return None
        if items and not board.writeObjects_(items):
            raise OSError("could not write to the macOS pasteboard")
        return sequence if int(board.changeCount()) == sequence else None

    def write_text(
        self, text: str, *, expected_sequence: int | None = None
    ) -> int | None:
        appkit = _appkit()
        item = appkit.NSPasteboardItem.alloc().init()
        if not item.setString_forType_(str(text), appkit.NSPasteboardTypeString):
            raise OSError("could not prepare macOS pasteboard text")
        return self._replace_items(
            self._board(), [item], expected_sequence=expected_sequence
        )

    def owns_text(self, sequence: int, text: str) -> bool:
        return (
            self.sequence() == sequence
            and self.text() == text
            and self.sequence() == sequence
        )

    def restore_if_owned(
        self,
        snapshot: MacOSPasteboardSnapshot,
        expected_sequence: int,
        expected_text: str,
    ) -> bool:
        if not snapshot.restorable or not self.owns_text(
            expected_sequence, expected_text
        ):
            return False

        # Prepare all representations before we clear the generated result.
        items = []
        for formats in snapshot.items:
            item = _appkit().NSPasteboardItem.alloc().init()
            for format_name, data in formats:
                if not item.setData_forType_(data, format_name):
                    return False
            items.append(item)
        return (
            self._replace_items(
                self._board(), items, expected_sequence=expected_sequence
            )
            is not None
        )

    @staticmethod
    def _attribute(element, name):
        error, value = _accessibility().AXUIElementCopyAttributeValue(
            element, name, None
        )
        return value if error == 0 else None

    @staticmethod
    def _frontmost_app():
        return _appkit().NSWorkspace.sharedWorkspace().frontmostApplication()

    def foreground_window(self) -> MacOSFocusTarget | None:
        app = self._frontmost_app()
        if app is None:
            return None
        pid = int(app.processIdentifier())
        if pid <= 0 or pid == os.getpid() or app.isTerminated():
            return None
        url = app.executableURL()
        path = url.path() if url is not None else None
        executable = str(path) if path else None

        try:
            ax = _accessibility()
            if ax.AXIsProcessTrusted():
                application = ax.AXUIElementCreateApplication(pid)
                ax.AXUIElementSetMessagingTimeout(application, 0.08)
                window = self._attribute(application, "AXFocusedWindow")
                element = self._attribute(application, "AXFocusedUIElement")
                if (
                    window is not None
                    and element is not None
                    and app == self._frontmost_app()
                ):
                    ax.AXUIElementSetMessagingTimeout(element, 0.08)
                    return MacOSFocusTarget(app, pid, executable, window, element)
        except (
            ImportError,
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            pass
        # Keep the executable identity even when Accessibility is unavailable.
        return MacOSFocusTarget(app, pid, executable)

    def is_current(self, target: MacOSFocusTarget) -> bool:
        if target.window is None or target.element is None or target.app.isTerminated():
            return False
        current = self.foreground_window()
        return bool(
            current is not None
            and current.app == target.app
            and current.window == target.window
            and current.element == target.element
        )

    def activate(self, target: MacOSFocusTarget) -> None:
        if target.window is not None and not target.app.isTerminated():
            target.app.activateWithOptions_(0)

    @staticmethod
    def modifiers_pressed() -> bool:
        quartz = _quartz()
        modifiers = (
            quartz.kCGEventFlagMaskCommand
            | quartz.kCGEventFlagMaskControl
            | quartz.kCGEventFlagMaskAlternate
            | quartz.kCGEventFlagMaskShift
            | quartz.kCGEventFlagMaskSecondaryFn
        )
        return bool(
            quartz.CGEventSourceFlagsState(
                quartz.kCGEventSourceStateCombinedSessionState
            )
            & modifiers
        )

    def _selection_range(self, element) -> tuple[int, int] | None:
        selection = self._attribute(element, "AXSelectedTextRange")
        if selection is None:
            return None
        valid, selected_range = _accessibility().AXValueGetValue(
            selection, _AX_RANGE_TYPE, None
        )
        return tuple(selected_range) if valid else None

    def selection(self, target: MacOSFocusTarget):
        if not self.is_current(target):
            return None
        selected_range = self._selection_range(target.element)
        text = self._attribute(target.element, "AXSelectedText")
        if not isinstance(text, str) or not self.is_current(target):
            return None
        if self._selection_range(target.element) != selected_range:
            return None
        return text, selected_range

    def _expected_paste_value(self, element, text: str) -> str | None:
        value = self._attribute(element, "AXValue")
        selected_range = self._selection_range(element)
        if not isinstance(value, str) or selected_range is None:
            return None
        start, length = selected_range
        # AX ranges use UTF-16 code units, including surrogate pairs.
        original = value.encode("utf-16-le")
        if start < 0 or length < 0 or (start + length) * 2 > len(original):
            return None
        try:
            expected = (
                original[: start * 2].decode("utf-16-le")
                + text
                + original[(start + length) * 2 :].decode("utf-16-le")
            )
        except UnicodeDecodeError:
            return None
        return expected if expected != value else None

    def paste(
        self,
        target,
        text,
        sequence,
        *,
        expected_selection,
        allow_unconfirmed,
        sleep,
        monotonic,
    ) -> bool:
        quartz = _quartz()
        if not quartz.CGPreflightPostEventAccess():
            return False

        deadline = monotonic() + 0.25
        while self.modifiers_pressed():
            if monotonic() >= deadline or not self.is_current(target):
                return False
            sleep(0.01)

        if not self.is_current(target):
            return False
        expected_value = self._expected_paste_value(target.element, text)
        if expected_value is None and (
            not allow_unconfirmed
            or self._attribute(target.element, "AXRole")
            not in ("AXTextField", "AXTextArea")
        ):
            return False
        events = [
            quartz.CGEventCreateKeyboardEvent(None, _ANSI_V_KEY, down)
            for down in (True, False)
        ]
        if any(event is None for event in events):
            return False
        for event in events:
            quartz.CGEventSetFlags(event, quartz.kCGEventFlagMaskCommand)
        # Target the captured process so an application switch cannot redirect
        # the shortcut. Check its window and control immediately before posting.
        if (
            not self.owns_text(sequence, text)
            or not self.is_current(target)
            or (
                expected_selection is not None
                and self.selection(target) != expected_selection
            )
            or self.modifiers_pressed()
            or self.sequence() != sequence
        ):
            return False
        for event in events:
            quartz.CGEventPostToPid(target.pid, event)

        # A text control can handle Paste without exposing a readable value
        # and selection range. Keep the result on the clipboard in that case.
        if expected_value is None:
            return False
        deadline = monotonic() + 0.25
        while monotonic() < deadline and self.is_current(target):
            if self._attribute(target.element, "AXValue") == expected_value:
                return True
            sleep(0.01)
        return False
