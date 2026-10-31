"""Text action contracts use temporary profiles and fake provider boundaries."""

import unittest

from hotkey_config import HotkeyDefinition


from tests.support.text_actions import (
    LocalServiceFixture,
)


class LocalServiceTests(LocalServiceFixture, unittest.TestCase):
    def test_dynamic_native_ids_and_strict_registration_rollback(self):
        from tests.support.native_hotkeys import _User32
        from windows_hotkeys import (
            register_global_hotkeys,
            action_for_hotkey_id,
            HotkeyRegistrationError,
        )

        self.save(self.custom(shortcut=HotkeyDefinition.from_mapping("Ctrl+Alt+X")))
        bindings = self.service.bindings()
        native = _User32()
        identifiers = register_global_hotkeys(native, 1, bindings, strict=True)
        actions = {action_for_hotkey_id(key) for key in identifiers}
        self.assertIn("text_action:summary", actions)
        self.assertIn("text_action:rewrite", actions)
        self.assertNotIn("rewrite_hotkey", actions)
        rejected = _User32(fail_keys={ord("X")})
        with self.assertRaises(HotkeyRegistrationError):
            register_global_hotkeys(rejected, 1, bindings, strict=True)
        self.assertEqual(rejected.registered, [])
        self.assertTrue(rejected.unregistered)


if __name__ == "__main__":
    unittest.main()
