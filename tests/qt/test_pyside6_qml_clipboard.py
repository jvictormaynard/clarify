"""Focused tests for the standalone QML clipboard boundary."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from clarify.desktop import macos_clipboard
from clarify.desktop.qml_clipboard import QmlClipboardGateway
from voice_translation import VoiceTranslationPublication
from workflows import SelectionDisposition, SelectionTarget


from tests.support.clipboard import (
    FakeClipboardAdapter,
)


class QmlClipboardGatewayTests(unittest.TestCase):
    def setUp(self):
        self.foreground = {"window": 77}
        self.clipboard = FakeClipboardAdapter()
        self.target = SelectionTarget(77, "editor.exe")
        self.sleep = Mock()

        def foreground_window():
            return self.foreground["window"]

        def copy_selected():
            self.clipboard.sequence_value += 1
            self.clipboard.state = self.clipboard._snapshot(
                "selected", self.clipboard.sequence_value
            )
            return True

        self.gateway = QmlClipboardGateway(
            adapter=self.clipboard,
            is_windows=True,
            platform_name="Windows",
            foreground_window=foreground_window,
            executable_for_window=lambda _window: "editor.exe",
            send_ctrl_c=copy_selected,
            send_ctrl_v=lambda _text: True,
            sleep=self.sleep,
            monotonic=self._monotonic,
            restore_delay=0,
            copy_timeout=0.1,
        )

    def _monotonic(self):
        # The fake Ctrl+C changes the sequence immediately, so the polling
        # loop exits on its first iteration without a real clock or sleep.
        return 0.0

    def test_capture_target_and_currentness_use_foreground_hwnd_and_executable(self):
        self.assertEqual(self.gateway.capture_target(), self.target)
        self.assertTrue(self.gateway.is_target_current(self.target))

        self.foreground["window"] = 88
        self.assertFalse(self.gateway.is_target_current(self.target))

    def test_selection_capture_and_restore_only_when_sequence_is_owned(self):
        capture = self.gateway.capture_selection(self.target)

        self.assertIsNotNone(capture)
        self.assertEqual(capture.text, "selected")
        self.assertEqual(capture.context["copy_observed_sequence"], 11)

        self.gateway.restore(capture)
        self.assertEqual(self.clipboard.text(), "previous")
        self.assertEqual(len(self.clipboard.restores), 1)

        capture = self.gateway.capture_selection(self.target)
        self.clipboard.external_write("user wins")
        self.gateway.restore(capture)
        self.assertEqual(self.clipboard.text(), "user wins")
        self.assertEqual(len(self.clipboard.restores), 1)

    def test_selection_capture_retries_one_swallowed_ctrl_c(self):
        clock = {"now": 0.0}
        copy_attempts = []

        def sleep(seconds):
            clock["now"] += seconds

        def copy_selected():
            copy_attempts.append(clock["now"])
            if len(copy_attempts) == 2:
                self.clipboard.sequence_value += 1
                self.clipboard.state = self.clipboard._snapshot(
                    "selected", self.clipboard.sequence_value
                )
            return True

        gateway = QmlClipboardGateway(
            adapter=self.clipboard,
            is_windows=True,
            platform_name="Windows",
            foreground_window=lambda: self.foreground["window"],
            executable_for_window=lambda _window: "editor.exe",
            send_ctrl_c=copy_selected,
            sleep=sleep,
            monotonic=lambda: clock["now"],
            copy_timeout=0.4,
        )

        capture = gateway.capture_selection(self.target)

        self.assertIsNotNone(capture)
        self.assertEqual(capture.text, "selected")
        self.assertEqual(len(copy_attempts), 2)

    def test_selection_capture_does_not_retry_after_focus_changes(self):
        clock = {"now": 0.0}
        copy_attempts = []

        def sleep(seconds):
            clock["now"] += seconds
            if clock["now"] >= 0.08:
                self.foreground["window"] = 88

        gateway = QmlClipboardGateway(
            adapter=self.clipboard,
            is_windows=True,
            platform_name="Windows",
            foreground_window=lambda: self.foreground["window"],
            executable_for_window=lambda _window: "editor.exe",
            send_ctrl_c=lambda: copy_attempts.append(clock["now"]) or True,
            sleep=sleep,
            monotonic=lambda: clock["now"],
            copy_timeout=0.4,
        )

        self.assertIsNone(gateway.capture_selection(self.target))
        self.assertEqual(len(copy_attempts), 1)

    def test_unsafe_paste_downgrades_to_copy_only_and_keeps_result_available(self):
        self.gateway._send_ctrl_v = lambda _text: None
        capture = self.gateway.capture_selection(self.target)

        disposition = self.gateway.apply_result(capture, "generated")

        self.assertEqual(disposition, SelectionDisposition.COPIED)
        self.assertEqual(self.clipboard.text(), "generated")
        self.assertEqual(self.clipboard.writes[-1], "generated")

    def test_injected_paste_boundary_is_called_with_generated_text(self):
        paste = Mock(return_value=None)

        def copy_selected():
            self.clipboard.sequence_value += 1
            self.clipboard.state = self.clipboard._snapshot(
                "selected", self.clipboard.sequence_value
            )
            return True

        gateway = QmlClipboardGateway(
            adapter=self.clipboard,
            is_windows=True,
            platform_name="Windows",
            foreground_window=lambda: self.foreground["window"],
            executable_for_window=lambda _window: "editor.exe",
            send_ctrl_c=copy_selected,
            send_ctrl_v=paste,
            sleep=self.sleep,
            monotonic=self._monotonic,
            restore_delay=0,
            copy_timeout=0.1,
        )
        capture = gateway.capture_selection(self.target)

        gateway.apply_result(capture, "generated")

        paste.assert_called_once_with("generated")

    def test_focus_change_downgrades_without_sending_ctrl_v(self):
        paste = Mock(return_value=True)
        self.gateway._send_ctrl_v = paste
        capture = self.gateway.capture_selection(self.target)
        self.foreground["window"] = 88

        disposition = self.gateway.apply_result(capture, "generated")

        self.assertEqual(disposition, SelectionDisposition.COPIED)
        paste.assert_not_called()
        self.assertEqual(self.clipboard.text(), "generated")

    def test_voice_publication_reuses_owned_paste_transaction(self):
        self.assertTrue(self.gateway.owns_clipboard())

        disposition = self.gateway.publish(
            "translated voice",
            self.target,
            VoiceTranslationPublication.PASTED,
        )

        self.assertEqual(disposition, VoiceTranslationPublication.PASTED)
        self.assertEqual(self.clipboard.text(), "previous")
        self.assertEqual(self.clipboard.writes[-1], "translated voice")

    def test_voice_copy_only_publication_keeps_generated_text_visible(self):
        disposition = self.gateway.publish(
            "translated voice",
            self.target,
            VoiceTranslationPublication.COPY_ONLY,
        )

        self.assertEqual(disposition, VoiceTranslationPublication.COPY_ONLY)
        self.assertEqual(self.clipboard.text(), "translated voice")


class QmlClipboardNonWindowsTests(unittest.TestCase):
    def test_visible_result_uses_xclip_and_selection_is_copy_only(self):
        run = Mock()
        gateway = QmlClipboardGateway(
            adapter=FakeClipboardAdapter(),
            is_windows=False,
            platform_name="Linux",
            run=run,
        )
        target = SelectionTarget(77, "editor.exe")

        self.assertIsNone(gateway.capture_target())
        self.assertFalse(gateway.is_target_current(target))
        self.assertIsNone(gateway.capture_selection(target))
        self.assertEqual(
            gateway.write_dictation_result(target, "visible"),
            SelectionDisposition.COPIED,
        )
        self.assertEqual(
            gateway.apply_result(None, "visible"), SelectionDisposition.COPIED
        )
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[0].args[0],
            [
                "xclip",
                "-selection",
                "clipboard",
            ],
        )
        self.assertFalse(gateway.alt_pressed())


class _PasteboardItem:
    def __init__(self):
        self.formats = {}

    def types(self):
        return tuple(self.formats)

    def dataForType_(self, name):
        return self.formats[name]

    def setData_forType_(self, data, name):
        self.formats[name] = data
        return True

    def setString_forType_(self, value, name):
        return self.setData_forType_(value.encode(), name)


class QmlClipboardMacOSTests(unittest.TestCase):
    def setUp(self):
        self.text_type = "public.utf8-plain-text"
        self.board = Mock()
        self.previous = _PasteboardItem()
        self.previous.formats = {self.text_type: b"previous", "public.rtf": b"rtf"}
        second_item = _PasteboardItem()
        second_item.formats = {"public.file-url": b"file:///fixture"}
        self.items = [self.previous, second_item]
        self.sequence = 10
        self.board.changeCount.side_effect = lambda: self.sequence
        self.board.pasteboardItems.side_effect = lambda: self.items
        self.board.stringForType_.side_effect = lambda _: self.clipboard_text()
        self.board.clearContents.side_effect = self.clear_board
        self.board.writeObjects_.side_effect = self.write_items
        self.start_patch(
            "_appkit",
            SimpleNamespace(
                NSPasteboard=SimpleNamespace(generalPasteboard=lambda: self.board),
                NSPasteboardTypeString=self.text_type,
                NSPasteboardItem=SimpleNamespace(
                    alloc=lambda: SimpleNamespace(init=_PasteboardItem)
                ),
            ),
        )
        self.app = Mock()
        self.app.processIdentifier.return_value = 123
        self.app.isTerminated.return_value = False
        self.app.executableURL.return_value.path.return_value = (
            "/Applications/Editor.app/Contents/MacOS/Editor"
        )
        self.frontmost = self.app
        self.focus = {
            "AXFocusedWindow": "editor-window",
            "AXFocusedUIElement": "editor",
        }
        self.editor = {
            "AXValue": "😀draft",
            "AXSelectedTextRange": (2, 5),
            "AXSelectedText": "draft",
        }
        self.ax = Mock()
        self.ax.AXIsProcessTrusted.return_value = True
        self.ax.AXUIElementCreateApplication.return_value = "application"
        self.ax.AXUIElementCopyAttributeValue.side_effect = self.read_attribute
        self.ax.AXValueGetValue.side_effect = lambda value, *_: (True, value)
        self.start_patch("_accessibility", self.ax)
        self.start_patch("_quartz", self.fake_quartz())
        frontmost = patch.object(
            macos_clipboard.MacOSClipboard,
            "_frontmost_app",
            side_effect=lambda: self.frontmost,
        )
        frontmost.start()
        self.addCleanup(frontmost.stop)
        self.clock = 0.0
        self.gateway = QmlClipboardGateway(
            platform_name="Darwin", sleep=self.advance, monotonic=lambda: self.clock
        )

    def start_patch(self, name, value):
        patcher = patch.object(macos_clipboard, name, return_value=value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_quartz(self):
        self.post = Mock()
        self.flags = Mock(return_value=0)
        return SimpleNamespace(
            CGPreflightPostEventAccess=lambda: True,
            CGEventSourceFlagsState=self.flags,
            kCGEventSourceStateCombinedSessionState=0,
            kCGEventFlagMaskCommand=1,
            kCGEventFlagMaskControl=2,
            kCGEventFlagMaskAlternate=4,
            kCGEventFlagMaskShift=8,
            kCGEventFlagMaskSecondaryFn=16,
            CGEventCreateKeyboardEvent=lambda _source, key, down: (key, down),
            CGEventSetFlags=Mock(),
            CGEventPostToPid=self.post,
        )

    def read_attribute(self, element, attribute, _out):
        attributes = self.focus if element == "application" else self.editor
        return 0, attributes.get(attribute)

    def clipboard_text(self):
        value = self.items[0].formats.get(self.text_type) if self.items else None
        return value.decode() if value is not None else None

    def clear_board(self):
        self.sequence += 1
        self.items = []
        return self.sequence

    def write_items(self, items):
        self.items = items
        return True

    def advance(self, seconds):
        self.clock += seconds

    def test_changed_window_control_or_selection_copies_without_posting(self):
        for attribute, state in (
            ("AXFocusedWindow", self.focus),
            ("AXFocusedUIElement", self.focus),
            ("AXSelectedText", self.editor),
            ("AXSelectedTextRange", self.editor),
        ):
            with self.subTest(attribute=attribute), patch.dict(state):
                target = self.gateway.capture_target()
                self.assertEqual(target.executable, self.app.executableURL().path())
                capture = self.gateway.capture_selection(target)
                self.assertEqual(capture.text, "draft")
                if attribute == "AXSelectedTextRange":
                    state.update(AXValue="😀draft draft", AXSelectedTextRange=(8, 5))
                else:
                    state[attribute] = "changed"

                self.assertEqual(
                    self.gateway.apply_result(capture, "result"),
                    SelectionDisposition.COPIED,
                )
                self.assertEqual(self.clipboard_text(), "result")
                self.post.assert_not_called()

    def test_verified_paste_restores_every_item_after_modifiers_release(self):
        original = [item.formats for item in self.items]
        self.flags.side_effect = [1, 0, 0]

        def paste(pid, event):
            self.assertEqual(pid, 123)
            self.assertEqual(self.clipboard_text(), "result")
            self.assertGreater(self.clock, 0)
            if event == (9, True):
                self.editor["AXValue"] = "😀result"

        self.post.side_effect = paste
        target = self.gateway.capture_target()

        self.assertEqual(
            self.gateway.write_dictation_result(target, "result"),
            SelectionDisposition.PASTED,
        )
        self.assertEqual([item.formats for item in self.items], original)

    def test_dictation_can_paste_into_text_control_without_a_readable_range(self):
        self.editor.pop("AXSelectedTextRange")
        target = self.gateway.capture_target()

        for role, expected_events in (
            ("AXButton", []),
            ("AXTextArea", [((123, (9, True)),), ((123, (9, False)),)]),
        ):
            with self.subTest(role=role):
                self.editor["AXRole"] = role
                self.assertEqual(
                    self.gateway.write_dictation_result(target, "result"),
                    SelectionDisposition.COPIED,
                )
                self.assertEqual(self.post.call_args_list, expected_events)
                self.assertEqual(self.clipboard_text(), "result")

        self.post.reset_mock()
        self.assertEqual(
            self.gateway.write_dictation_result(
                target, "result", allow_unconfirmed=False
            ),
            SelectionDisposition.COPIED,
        )
        self.assertEqual(
            self.gateway.publish("result", target, VoiceTranslationPublication.PASTED),
            VoiceTranslationPublication.COPY_ONLY,
        )
        self.post.assert_not_called()

    def test_incomplete_snapshot_and_denied_access_allow_manual_copy(self):
        target = self.gateway.capture_target()
        for formats in (
            self.previous.formats | {"com.example.promise": b"payload"},
            self.previous.formats | {"public.html": None},
        ):
            with self.subTest(formats=tuple(formats)):
                self.previous.formats = formats
                self.items = [self.previous]
                self.assertFalse(self.gateway.owns_clipboard())
                self.assertEqual(
                    self.gateway.write_dictation_result(target, "result"),
                    SelectionDisposition.COPIED,
                )
                self.assertEqual(self.clipboard_text(), "result")

        self.ax.AXIsProcessTrusted.return_value = False
        target = self.gateway.capture_target()
        self.assertEqual(target.executable, self.app.executableURL().path())
        self.assertIsNone(self.gateway.capture_selection(target))
        self.assertEqual(
            self.gateway.publish(
                "recoverable", target, VoiceTranslationPublication.PASTED
            ),
            VoiceTranslationPublication.COPY_ONLY,
        )
        self.assertEqual(self.clipboard_text(), "recoverable")
        self.post.assert_not_called()

    def test_verified_paste_keeps_newer_clipboard_even_with_same_text(self):
        def paste(_pid, event):
            if event == (9, True):
                self.editor["AXValue"] = "😀result"
                item = _PasteboardItem()
                item.formats = {self.text_type: b"result", "public.html": b"newer"}
                self.clear_board()
                self.write_items([item])

        self.post.side_effect = paste

        self.assertEqual(
            self.gateway.write_dictation_result(
                self.gateway.capture_target(), "result"
            ),
            SelectionDisposition.PASTED,
        )
        self.assertEqual(self.items[0].formats["public.html"], b"newer")

    def test_external_write_during_snapshot_keeps_newer_clipboard(self):
        read_data = self.previous.dataForType_

        def read_while_user_copies(name):
            item = _PasteboardItem()
            item.setString_forType_("newer", self.text_type)
            self.clear_board()
            self.write_items([item])
            return read_data(name)

        self.previous.dataForType_ = read_while_user_copies

        outcome = self.gateway.write_dictation_result(
            self.gateway.capture_target(), "result"
        )

        self.assertEqual(outcome, SelectionDisposition.PRESERVED)
        self.assertEqual(self.clipboard_text(), "newer")
        self.post.assert_not_called()

    def test_focus_change_while_waiting_for_modifier_release_copies_only(self):
        target = self.gateway.capture_target()
        self.flags.side_effect = [1, 0]

        def switch_control(seconds):
            self.advance(seconds)
            self.focus["AXFocusedUIElement"] = "new-control"

        self.gateway._sleep = switch_control

        self.assertEqual(
            self.gateway.write_dictation_result(target, "result"),
            SelectionDisposition.COPIED,
        )
        self.assertEqual(self.clipboard_text(), "result")
        self.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
