import threading
import json
import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path

from hotkey_config import (
    ActivationMode,
    ActivationRaceState,
    HotkeyAction,
    HotkeyConflictError,
    HotkeyDefinition,
    HotkeySettings,
    HotkeySettingsController,
    HotkeyValidationError,
    RecordingActivationController,
)
from repositories import AppConfig, LocalConfigRepository


class HotkeySettingsTests(unittest.TestCase):
    def test_modifier_and_side_mouse_bindings_round_trip_without_modifiers(self):
        for key in ("CTRL", "WIN", "ALT", "SHIFT", "XBUTTON1", "XBUTTON2"):
            with self.subTest(key=key):
                definition = HotkeyDefinition.from_mapping(key)
                self.assertFalse(definition.modifiers)
                self.assertEqual(
                    HotkeyDefinition.from_mapping(definition.to_mapping()), definition
                )
                settings = HotkeySettings.defaults().with_hotkey(
                    "recording_hotkey", definition
                )
                self.assertEqual(
                    HotkeySettings.from_mapping(settings.to_mapping()), settings
                )

    def test_bare_letters_and_primary_mouse_buttons_are_rejected(self):
        for key in ("A", "MOUSE1", "MOUSE2", "LBUTTON", "RBUTTON"):
            with self.subTest(key=key), self.assertRaises(HotkeyValidationError):
                HotkeyDefinition.from_mapping({"modifiers": [], "key": key})

    def test_legacy_installation_gets_original_defaults(self):
        settings = HotkeySettings.from_mapping({"ui_language": "pt"})

        self.assertEqual(settings.definition(HotkeyAction.RECORDING).display, "Alt+L")
        self.assertEqual(settings.definition(HotkeyAction.REWRITE).display, "Alt+K")
        self.assertEqual(settings.activation_mode, ActivationMode.TOGGLE)
        self.assertNotIn(HotkeyAction.VOICE_TRANSLATION, settings.hotkeys)

    def test_flat_pre_release_bindings_are_migrated(self):
        settings = HotkeySettings.from_mapping(
            {
                "recording_hotkey": "Ctrl+Shift+L",
                "rewrite_hotkey": {"modifiers": ["alt"], "key": "F2"},
            }
        )

        self.assertEqual(
            settings.definition("recording_hotkey").display, "Ctrl+Shift+L"
        )
        self.assertEqual(settings.definition("rewrite_hotkey").display, "Alt+F2")
        self.assertEqual(settings.definition("translation_hotkey").display, "Alt+T")

    def test_invalid_entry_reverts_only_that_entry(self):
        settings = HotkeySettings.from_mapping(
            {
                "bindings": {
                    "recording_hotkey": {"modifiers": ["alt"], "key": "NotAKey"},
                    "rewrite_hotkey": {"modifiers": ["ctrl"], "key": "K"},
                },
            }
        )

        self.assertEqual(settings.definition("recording_hotkey").display, "Alt+L")
        self.assertEqual(settings.definition("rewrite_hotkey").display, "Ctrl+K")

    def test_conflicts_are_rejected_before_registration(self):
        settings = HotkeySettings.defaults()

        with self.assertRaises(HotkeyConflictError):
            settings.with_hotkey("rewrite_hotkey", "Alt+L")

    def test_capture_and_reset_form_settings_facing_api(self):
        controller = HotkeySettingsController()
        controller.capture("recording_hotkey", "Ctrl+L")
        self.assertEqual(
            controller.settings.definition("recording_hotkey").display, "Ctrl+L"
        )
        controller.reset("recording_hotkey")
        self.assertEqual(
            controller.settings.definition("recording_hotkey").display, "Alt+L"
        )

    def test_push_to_talk_requires_key_release_capability(self):
        with self.assertRaises(HotkeyValidationError):
            HotkeySettings.defaults().with_activation_mode(ActivationMode.PUSH_TO_TALK)

        supported = HotkeySettings.defaults().with_activation_mode(
            ActivationMode.PUSH_TO_TALK, push_to_talk_supported=True
        )
        self.assertEqual(supported.activation_mode, ActivationMode.PUSH_TO_TALK)

    def test_repository_round_trip_writes_typed_nested_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            repository = LocalConfigRepository(path)
            repository.save(
                AppConfig.from_mapping(
                    {
                        "hotkeys": HotkeySettings.defaults()
                        .with_hotkey("recording_hotkey", "Ctrl+L")
                        .to_mapping(),
                    }
                )
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            loaded = repository.load()

        self.assertEqual(payload["hotkeys"]["bindings"]["recording_hotkey"]["key"], "L")
        self.assertEqual(
            loaded.hotkeys.definition("recording_hotkey").display, "Ctrl+L"
        )


class ActivationControllerTests(unittest.TestCase):
    def test_toggle_press_during_start_stops_once_after_start(self):
        started = threading.Event()
        release_start = threading.Event()
        starts = []
        stops = []

        def start():
            starts.append(True)
            started.set()
            release_start.wait(1)
            return True

        controller = RecordingActivationController(start, lambda: stops.append(True))
        thread = threading.Thread(target=controller.press)
        thread.start()
        self.assertTrue(started.wait(1))
        controller.press()
        release_start.set()
        thread.join(1)

        self.assertEqual(len(starts), 1)
        self.assertEqual(len(stops), 1)
        self.assertEqual(controller.state, ActivationRaceState.IDLE)

    def test_push_to_talk_release_during_start_cannot_stick(self):
        started = threading.Event()
        release_start = threading.Event()
        stops = []

        def start():
            started.set()
            release_start.wait(1)
            return True

        controller = RecordingActivationController(
            start, lambda: stops.append(True), mode=ActivationMode.PUSH_TO_TALK
        )
        thread = threading.Thread(target=controller.press)
        thread.start()
        self.assertTrue(started.wait(1))
        self.assertTrue(controller.release())
        release_start.set()
        thread.join(1)

        self.assertEqual(stops, [True])
        self.assertEqual(controller.state, ActivationRaceState.IDLE)

    def test_shutdown_cancels_active_edge_and_ignores_late_start(self):
        started = threading.Event()
        release_start = threading.Event()
        starts = []
        cancels = []

        def start():
            starts.append(True)
            started.set()
            release_start.wait(1)
            return True

        controller = RecordingActivationController(
            start, Mock(), on_cancel=lambda: cancels.append(True)
        )
        thread = threading.Thread(target=controller.press)
        thread.start()
        self.assertTrue(started.wait(1))
        controller.shutdown()
        release_start.set()
        thread.join(1)

        self.assertEqual(len(starts), 1)
        self.assertEqual(cancels, [True])
        self.assertEqual(controller.state, ActivationRaceState.CLOSED)


if __name__ == "__main__":
    unittest.main()
