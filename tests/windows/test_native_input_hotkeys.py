"""Special global inputs use fake events, never real keyboard/mouse hooks."""

import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hotkey_config import HotkeySettings
from windows_hotkeys import HookHotkeyState, WindowsInputHook, HotkeyRegistrationError


class HookHotkeyTests(unittest.TestCase):
    def state(self, key="CTRL", **kwargs):
        return HookHotkeyState(
            HotkeySettings.defaults().with_hotkey("recording_hotkey", key), **kwargs
        )

    def test_ctrl_tap_fires_once_on_release_and_chords_do_not_fire(self):
        state = self.state()
        self.assertEqual(state.keyboard(0xA2, True), [])
        self.assertEqual(state.keyboard(0xA2, True), [])
        self.assertEqual(state.keyboard(0xA2, False), [(0x5101, "tap")])
        self.assertEqual(state.keyboard(0xA2, False), [])
        state.keyboard(0xA3, True)
        state.keyboard(ord("C"), True)
        state.keyboard(ord("C"), False)
        self.assertEqual(state.keyboard(0xA3, False), [])

    def test_side_mouse_consumes_only_configured_button_and_matches_modifiers(self):
        state = self.state("Ctrl+XBUTTON1")
        self.assertEqual(state.mouse("XBUTTON1", True), (False, []))
        state.keyboard(0xA2, True)
        self.assertEqual(state.mouse("XBUTTON1", True), (True, [(0x5101, "press")]))
        self.assertEqual(state.mouse("XBUTTON1", True), (True, []))
        state.keyboard(0xA2, False)
        self.assertEqual(state.mouse("XBUTTON1", False), (True, [(0x5101, "release")]))
        self.assertEqual(state.mouse("XBUTTON2", True), (False, []))
        self.assertEqual(state.mouse("LBUTTON", True), (False, []))

    def test_both_control_keys_do_not_generate_duplicate_taps(self):
        state = self.state()
        state.keyboard(0xA2, True)
        state.keyboard(0xA3, True)
        self.assertEqual(state.keyboard(0xA2, False), [])
        self.assertEqual(state.keyboard(0xA3, False), [])

    def test_hold_waits_for_a_clean_modifier_and_releases_on_a_chord(self):
        now = [0.0]
        settings = HotkeySettings.defaults().with_hotkey("recording_hotkey", "CTRL")
        settings = settings.with_activation_mode(
            "push_to_talk", push_to_talk_supported=True
        )
        state = HookHotkeyState(settings, clock=lambda: now[0])
        state.keyboard(0xA2, True)
        self.assertEqual(state.poll(), [])
        now[0] = 0.25
        self.assertEqual(state.poll(), [(0x5101, "press")])
        self.assertEqual(state.keyboard(ord("C"), True), [(0x5101, "release")])
        self.assertEqual(state.keyboard(0xA2, False), [])

    def test_mouse_or_an_already_held_key_prevents_a_modifier_tap(self):
        state = self.state("WIN")
        state.keyboard(0x5B, True)
        state.mouse("LBUTTON", True)
        self.assertEqual(state.keyboard(0x5B, False), [])
        state.keyboard(ord("E"), True)
        state.keyboard(0x5C, True)
        self.assertEqual(state.keyboard(0x5C, False), [])


class InputHookAdapterTests(unittest.TestCase):
    def user32(self, *, fail_second=False):
        installed, removed = [], []

        def install(kind, callback, module, thread):
            installed.append(kind)
            return 0 if fail_second and len(installed) == 2 else kind

        def remove(handle):
            removed.append(handle)
            return True

        return (
            SimpleNamespace(
                SetWindowsHookExW=install,
                UnhookWindowsHookEx=remove,
                CallNextHookEx=lambda *_: 0,
                keybd_event=lambda *_: None,
                GetAsyncKeyState=lambda *_: 0,
            ),
            installed,
            removed,
        )

    def test_callbacks_ignore_injected_keys_and_consume_only_bound_side_buttons(self):
        user32, installed, removed = self.user32()
        settings = (
            HotkeySettings.defaults()
            .with_hotkey("recording_hotkey", "CTRL")
            .with_hotkey("rewrite_hotkey", "XBUTTON1")
        )
        events = []
        hook = WindowsInputHook(user32, settings, lambda *event: events.append(event))
        with patch.object(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, create=True):
            hook.start()
        self.assertEqual(installed, [13, 14])
        try:
            key = hook.KeyboardData(vkCode=0xA2, flags=0x10)
            hook._keyboard(0, 0x100, ctypes.addressof(key))
            hook._keyboard(0, 0x101, ctypes.addressof(key))
            self.assertEqual(events, [])
            key.flags = 0
            hook._keyboard(0, 0x100, ctypes.addressof(key))
            hook._keyboard(0, 0x101, ctypes.addressof(key))
            self.assertEqual(events, [(0x5101, "tap")])
            mouse = hook.MouseData(mouseData=1 << 16)
            self.assertEqual(hook._mouse(0, 0x20B, ctypes.addressof(mouse)), 1)
            self.assertEqual(hook._mouse(0, 0x20C, ctypes.addressof(mouse)), 1)
            self.assertEqual(hook._mouse(0, 0x201, ctypes.addressof(mouse)), 0)
            self.assertEqual(events[-2:], [(0x5102, "press"), (0x5102, "release")])
        finally:
            hook.stop()
            hook.stop()
        self.assertEqual(removed, [13, 14])

    def test_partial_installation_failure_releases_the_first_hook(self):
        user32, installed, removed = self.user32(fail_second=True)
        hook = WindowsInputHook(
            user32,
            HotkeySettings.defaults().with_hotkey("recording_hotkey", "CTRL"),
            lambda *_: None,
        )
        with patch.object(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, create=True):
            with self.assertRaises(HotkeyRegistrationError):
                hook.start()
        self.assertEqual(installed, [13, 14])
        self.assertEqual(removed, [13])
        self.assertEqual(hook.handles, [])
        self.assertEqual(hook.callbacks, [])
