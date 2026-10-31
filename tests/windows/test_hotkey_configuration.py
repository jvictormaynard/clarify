from tests.support.native_hotkeys import _User32

import unittest

from hotkey_config import (
    HotkeySettings,
)
from windows_hotkeys import (
    HotkeyRegistrationError,
    WindowsHotkeyRegistration,
    register_global_hotkeys,
)


class RegistrationTests(unittest.TestCase):
    def test_legacy_settings_skip_new_voice_binding_during_strict_registration(self):
        settings = HotkeySettings.from_mapping({"ui_language": "pt"})
        user32 = _User32(fail_keys={ord("V")})

        registered = register_global_hotkeys(user32, 1, settings, strict=True)

        self.assertEqual(
            registered,
            {0x5101, 0x5102, 0x5103, 0x5104},
        )
        self.assertNotIn(0x5106, registered)
        self.assertEqual(len(user32.registered), 4)

    def test_strict_registration_cleans_up_partial_set(self):
        user32 = _User32(fail_keys={ord("T")})

        with self.assertRaises(HotkeyRegistrationError) as raised:
            register_global_hotkeys(user32, 1, strict=True)

        self.assertIn("translation_hotkey", raised.exception.failed_actions)
        self.assertEqual(user32.registered, [])
        self.assertGreaterEqual(len(user32.unregistered), 2)

    def test_transactional_replace_restores_previous_set_on_failure(self):
        user32 = _User32()
        manager = WindowsHotkeyRegistration(user32, 1)
        manager.register()
        original = manager.settings
        user32.fail_keys.add(ord("Q"))

        with self.assertRaises(HotkeyRegistrationError):
            manager.replace(original.with_hotkey("rewrite_hotkey", "Alt+Q"))

        self.assertEqual(manager.settings, original)
        self.assertEqual(len(manager.registered), 5)
        self.assertEqual(len(user32.registered), 5)

    def test_transactional_replace_restores_legacy_set_when_voice_conflicts(self):
        user32 = _User32()
        legacy = HotkeySettings.from_mapping({"ui_language": "pt"})
        manager = WindowsHotkeyRegistration(user32, 1, legacy)
        manager.register()
        user32.fail_keys.add(ord("V"))

        with self.assertRaises(HotkeyRegistrationError) as raised:
            manager.replace(HotkeySettings.defaults())

        self.assertIn("voice_translation_hotkey", raised.exception.failed_actions)
        self.assertEqual(manager.settings, legacy)
        self.assertEqual(manager.registered, {0x5101, 0x5102, 0x5103, 0x5104})
        self.assertEqual(len(user32.registered), 4)
        self.assertNotIn(0x5106, {hotkey_id for hotkey_id, _ in user32.registered})


if __name__ == "__main__":
    unittest.main()
