"""Focused tests for the UI-free native Qt desktop shell."""

from __future__ import annotations

from tests.support.native_shell import FakeWindow, FakeNativeEventTarget


import ast
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hotkey_config import HotkeyAction, HotkeySettings
from windows_hotkeys import ESCAPE_HOTKEY_ID, HotkeyRegistrationError

try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
except (ImportError, ModuleNotFoundError):
    PYSIDE6_AVAILABLE = False
    QObject = object

    def Signal(*_args, **_kwargs):
        return None
else:
    PYSIDE6_AVAILABLE = True

if PYSIDE6_AVAILABLE:
    from clarify.desktop.macos_hotkeys import MacGlobalHotkeyBackend, default_hotkeys
    from clarify.desktop.qt_shell import (
        ACTIVATION_EVENT_NAME,
        QtShell,
        QtSingleInstanceGuard,
        WindowsGlobalHotkeyBackend,
        WindowsHotkeyEventFilter,
        _WindowsSingleInstanceActivationApi,
    )


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "clarify" / "desktop" / "qt_shell.py"


class FakeLock:
    locks: dict[str, "FakeLock"] = {}

    def __init__(self, path: str):
        self.path = path
        self.stale_lock_time = None
        self.locked = False

    def setStaleLockTime(self, value: int) -> None:
        self.stale_lock_time = value

    def tryLock(self, _timeout: int) -> bool:
        owner = self.locks.get(self.path)
        if owner is not None and owner is not self:
            return False
        self.locks[self.path] = self
        self.locked = True
        return True

    def unlock(self) -> None:
        if self.locks.get(self.path) is self:
            del self.locks[self.path]
        self.locked = False


class FakeActivationApi:
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 0x102

    def __init__(self):
        self.handle = 9001
        self.create_calls = []
        self.set_calls = []
        self.close_calls = []

    def create_event(self, name):
        self.create_calls.append(name)
        return self.handle

    def set_event(self, handle):
        self.set_calls.append(handle)
        return True

    def wait_for_event(self, _handle):
        return 1

    def close(self, handle):
        self.close_calls.append(handle)


class TimeoutActivationApi(FakeActivationApi):
    def __init__(self):
        super().__init__()
        self.waiting = threading.Event()
        self.wait_returned = threading.Event()
        self.woken = threading.Event()

    def wait_for_event(self, _handle):
        self.waiting.set()
        self.woken.wait(timeout=2)
        self.wait_returned.set()
        return self.WAIT_TIMEOUT

    def close(self, handle):
        self.assert_wait_finished = self.wait_returned.is_set()
        super().close(handle)


class FakeHotkeys(QObject):
    triggered = Signal(str)

    def __init__(self):
        super().__init__()
        self.started_with = None
        self.stopped = False
        self.stop_calls = 0
        self.is_running = False

    def start(self, window) -> set[int]:
        self.started_with = window
        self.is_running = True
        return {1}

    def stop(self) -> None:
        self.stopped = True
        self.stop_calls += 1
        self.is_running = False


class FailingHotkeys(FakeHotkeys):
    def start(self, window) -> set[int]:
        super().start(window)
        raise RuntimeError("hotkey setup failed")


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class QtSingleInstanceGuardTests(unittest.TestCase):
    def setUp(self):
        FakeLock.locks.clear()

    def test_only_one_guard_can_own_a_name(self):
        first = QtSingleInstanceGuard(
            "clarify-test",
            lock_path=Path(tempfile.gettempdir()) / "clarify-test.lock",
            lock_factory=FakeLock,
        )
        second = QtSingleInstanceGuard(
            "clarify-test",
            lock_path=Path(tempfile.gettempdir()) / "clarify-test.lock",
            lock_factory=FakeLock,
        )

        self.assertTrue(first.acquire())
        self.assertTrue(first.is_primary)
        self.assertFalse(second.acquire())
        self.assertFalse(second.is_primary)

        first.release()
        self.assertTrue(second.acquire())
        second.release()

    def test_second_guard_signals_the_primary_activation_event(self):
        activation_api = FakeActivationApi()
        first = QtSingleInstanceGuard(
            "clarify-test",
            lock_path=Path(tempfile.gettempdir()) / "clarify-test.lock",
            lock_factory=FakeLock,
            activation_api=activation_api,
        )
        second = QtSingleInstanceGuard(
            "clarify-test",
            lock_path=Path(tempfile.gettempdir()) / "clarify-test.lock",
            lock_factory=FakeLock,
            activation_api=activation_api,
        )

        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        self.assertEqual(
            activation_api.create_calls,
            [ACTIVATION_EVENT_NAME, ACTIVATION_EVENT_NAME],
        )
        self.assertEqual(activation_api.set_calls, [activation_api.handle])
        self.assertEqual(activation_api.close_calls, [activation_api.handle])

        first.release()
        self.assertEqual(
            activation_api.close_calls,
            [activation_api.handle, activation_api.handle],
        )

    def test_native_activation_wait_is_bounded(self):
        api = _WindowsSingleInstanceActivationApi.__new__(
            _WindowsSingleInstanceActivationApi
        )
        wait = Mock(return_value=0x102)
        api._kernel32 = SimpleNamespace(WaitForSingleObject=wait)

        self.assertEqual(api.wait_for_event(9001), 0x102)
        handle, timeout_ms = wait.call_args.args
        self.assertEqual(handle, 9001)
        self.assertGreater(timeout_ms, 0)
        self.assertLessEqual(timeout_ms, 1000)

    def test_listener_survives_timeout_before_a_real_activation(self):
        activation_api = FakeActivationApi()
        results = iter((activation_api.WAIT_TIMEOUT, activation_api.WAIT_OBJECT_0))
        activation_api.wait_for_event = lambda _handle: next(results)
        guard = QtSingleInstanceGuard(
            "clarify-timeout-test",
            lock_path=Path(tempfile.gettempdir()) / "clarify-timeout-test.lock",
            lock_factory=FakeLock,
            activation_api=activation_api,
        )
        received = threading.Event()

        def activate():
            guard.stop_activation_listener()
            received.set()

        self.assertTrue(guard.acquire())
        try:
            guard.start_activation_listener(activate)
            self.assertTrue(received.wait(timeout=1))
        finally:
            guard.release()

    def test_release_joins_listener_before_close_without_shared_activation_signal(self):
        activation_api = TimeoutActivationApi()
        guard = QtSingleInstanceGuard(
            "clarify-stop-test",
            lock_path=Path(tempfile.gettempdir()) / "clarify-stop-test.lock",
            lock_factory=FakeLock,
            activation_api=activation_api,
        )
        self.assertTrue(guard.acquire())
        guard.start_activation_listener(
            lambda: self.fail("Shutdown activated a window")
        )
        worker = guard._activation_listener_thread
        self.assertTrue(activation_api.waiting.wait(timeout=1))
        join = worker.join

        def allow_native_timeout():
            # Release the fake Win32 wait only when shutdown reaches the join.
            activation_api.woken.set()
            join(timeout=1)

        with patch.object(worker, "join", side_effect=allow_native_timeout):
            guard.release()

        self.assertFalse(worker.is_alive())
        self.assertEqual(activation_api.set_calls, [])
        self.assertTrue(activation_api.assert_wait_finished)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class MacGlobalHotkeyBackendTests(unittest.TestCase):
    def test_failed_reconfigure_keeps_the_previous_actions(self):
        app = QApplication.instance() or QApplication([])
        settings = default_hotkeys().with_hotkey(
            HotkeyAction.VOICE_TRANSLATION, "XBUTTON1"
        )
        candidate = settings.with_hotkey(HotkeyAction.RECORDING, "Ctrl+Shift+M")
        candidate = candidate.with_hotkey(HotkeyAction.VISIBILITY, "Ctrl+Shift+N")
        registrations = {}
        fail = False

        def register(combo, number):
            if fail and combo[0] == 45:  # N
                raise OSError("claimed by another app")
            registrations[combo] = number
            return combo

        def unregister(combo):
            registrations.pop(combo)

        native = SimpleNamespace(register=register, unregister=unregister, close=Mock())
        backend = MacGlobalHotkeyBackend(
            settings, native_factory=lambda _receive: native
        )
        actions = []
        backend.triggered.connect(actions.append)
        unavailable = []
        backend.availabilityChanged.connect(unavailable.extend)
        try:
            backend.start(FakeWindow())
            old = registrations.copy()
            self.assertEqual(len(old), 4)
            self.assertEqual(unavailable, ["Mouse 4"])
            old_recording = next(
                number for (code, _), number in old.items() if code == 37
            )
            fail = True
            with self.assertRaisesRegex(OSError, "claimed by another app"):
                backend.reconfigure(candidate)
            self.assertEqual(registrations, old)
            backend._receive(old_recording, True)
            app.processEvents()
            self.assertEqual(actions, [HotkeyAction.RECORDING.value])
        finally:
            backend.stop()


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class WindowsHotkeyEventFilterTests(unittest.TestCase):
    def test_filter_routes_decoded_hotkey_without_consuming_event(self):
        received = []
        event_filter = WindowsHotkeyEventFilter(
            received.append,
            message_decoder=lambda _event_type, _message: 0x5101,
            action_for_id=lambda hotkey_id: (
                "recording_hotkey" if hotkey_id == 0x5101 else None
            ),
        )

        result = event_filter.nativeEventFilter(b"windows_generic_MSG", object())

        self.assertEqual(received, [0x5101])
        self.assertEqual(result, (False, 0))

    def test_filter_deduplicates_qt_copies_of_the_same_native_hotkey(self):
        received = []
        times = iter((10.0, 10.001, 10.1))
        event_filter = WindowsHotkeyEventFilter(
            received.append,
            message_decoder=lambda _event_type, _message: 0x5104,
            action_for_id=lambda _hotkey_id: "toggle_visibility",
            monotonic=lambda: next(times),
        )

        event_filter.nativeEventFilter(b"windows_generic_MSG", object())
        event_filter.nativeEventFilter(b"windows_generic_MSG", object())
        event_filter.nativeEventFilter(b"windows_generic_MSG", object())

        self.assertEqual(received, [0x5104, 0x5104])


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class WindowsGlobalHotkeyBackendTests(unittest.TestCase):
    def test_capture_restore_collision_can_recover_on_apply(self):
        blocked = [False]

        def register(*_args, **_kwargs):
            if blocked[0]:
                raise HotkeyRegistrationError(["recording_hotkey"])
            return {0x5101}

        backend = WindowsGlobalHotkeyBackend(
            FakeNativeEventTarget(),
            user32="fake",
            register_hotkeys=register,
            unregister_hotkeys=lambda *_args: None,
        )
        try:
            backend.start(FakeWindow())
            backend.set_capture_active(True)
            blocked[0] = True
            with self.assertRaises(HotkeyRegistrationError):
                backend.set_capture_active(False)
            self.assertFalse(backend.is_running)
            blocked[0] = False
            self.assertEqual(backend.reconfigure(HotkeySettings.defaults()), {0x5101})
        finally:
            backend.stop()

    def test_capture_releases_global_inputs_and_drops_queued_actions(self):
        app = QApplication.instance() or QApplication([])
        hooks = []

        class Hook:
            def __init__(self, _user32, _settings, emit):
                self.ids, self.needs_poll = {0x5101}, False
                self.emit, self.stopped = emit, False
                hooks.append(self)

            def start(self):
                pass

            def stop(self):
                self.stopped = True

        backend = WindowsGlobalHotkeyBackend(
            FakeNativeEventTarget(),
            user32="fake",
            register_hotkeys=lambda *_args, **_kwargs: {0x5102},
            unregister_hotkeys=lambda *_args: None,
            input_hook_factory=Hook,
        )
        received = []
        backend.triggered.connect(received.append)
        try:
            backend.start(FakeWindow())
            hooks[0].emit(0x5101, "tap")
            backend.set_capture_active(True)
            self.assertFalse(backend.registered_ids)
            self.assertTrue(hooks[0].stopped)
            backend.set_capture_active(False)
            app.processEvents()
            self.assertEqual(received, [])
            self.assertEqual(backend.registered_ids, {0x5101, 0x5102})
            hooks[1].emit(0x5101, "tap")
            app.processEvents()
            self.assertEqual(received, ["recording_hotkey"])
            backend.set_capture_active(True)
            backend.stop()
            backend.set_capture_active(False)
            self.assertFalse(
                backend.is_running, "shutdown must not resume capture bindings"
            )
        finally:
            backend.stop()

    def test_hook_replacement_drops_old_events_and_keeps_old_hook_on_failure(self):
        app = QApplication.instance() or QApplication([])
        hooks = []

        class Hook:
            def __init__(self, _user32, _settings, emit):
                self.ids = {0x5101}
                self.needs_poll = False
                self.emit = emit
                self.stopped = False
                hooks.append(self)

            def start(self):
                pass

            def stop(self):
                self.stopped = True

            def poll(self):
                pass

        fail = [False]

        def register(*_args, **_kwargs):
            if fail[0]:
                fail[0] = False
                raise HotkeyRegistrationError(["recording_hotkey"])
            return set()

        backend = WindowsGlobalHotkeyBackend(
            FakeNativeEventTarget(),
            user32="fake",
            register_hotkeys=register,
            unregister_hotkeys=lambda *_args: None,
            input_hook_factory=Hook,
        )
        received = []
        backend.triggered.connect(received.append)
        try:
            self.assertEqual(backend.start(FakeWindow()), {0x5101})
            hooks[0].emit(0x5101, "tap")
            backend.reconfigure(HotkeySettings.defaults())
            app.processEvents()
            self.assertEqual(
                received, [], "queued events from the replaced hook must be ignored"
            )
            self.assertTrue(hooks[0].stopped)
            hooks[1].emit(0x5101, "tap")
            app.processEvents()
            self.assertEqual(received, ["recording_hotkey"])
            fail[0] = True
            with self.assertRaises(HotkeyRegistrationError):
                backend.reconfigure(HotkeySettings.defaults())
            self.assertTrue(hooks[2].stopped)
            self.assertFalse(hooks[1].stopped)
            self.assertEqual(backend.registered_ids, {0x5101})
        finally:
            backend.stop()
        self.assertTrue(hooks[1].stopped)

    def test_backend_registers_filters_and_emits_canonical_action(self):
        target = FakeNativeEventTarget()
        window = FakeWindow()
        registrations = []
        unregistrations = []

        def register(user32, hwnd, settings, *, strict):
            registrations.append((user32, hwnd, settings, strict))
            return {0x5101}

        def unregister(user32, hwnd, registered):
            unregistrations.append((user32, hwnd, set(registered)))

        backend = WindowsGlobalHotkeyBackend(
            target,
            user32="fake-user32",
            register_hotkeys=register,
            unregister_hotkeys=unregister,
            message_decoder=lambda _event_type, _message: 0x5101,
        )
        received = []
        backend.triggered.connect(received.append)

        self.assertEqual(backend.start(window), {0x5101})
        self.assertEqual(registrations[0][0], "fake-user32")
        self.assertEqual(registrations[0][1], 123)
        self.assertTrue(registrations[0][3])
        self.assertIsInstance(registrations[0][2], HotkeySettings)
        self.assertIn(HotkeyAction.VOICE_TRANSLATION, registrations[0][2].hotkeys)
        self.assertEqual(len(target.installed), 1)

        target.installed[0].nativeEventFilter(b"windows_generic_MSG", object())
        self.assertEqual(received, ["recording_hotkey"])

        backend.stop()
        self.assertEqual(target.removed, target.installed)
        self.assertEqual(unregistrations, [("fake-user32", 123, {0x5101})])
        self.assertFalse(backend.is_running)

    def test_backend_registers_escape_only_while_recording(self):
        target = FakeNativeEventTarget()
        escape_registrations = []
        escape_unregistrations = []

        def register_escape(user32, hwnd):
            escape_registrations.append((user32, hwnd))
            return True

        def unregister_escape(user32, hwnd):
            escape_unregistrations.append((user32, hwnd))

        backend = WindowsGlobalHotkeyBackend(
            target,
            user32="fake-user32",
            register_hotkeys=lambda *_args, **_kwargs: {0x5101},
            unregister_hotkeys=lambda *_args, **_kwargs: None,
            register_escape=register_escape,
            unregister_escape=unregister_escape,
            message_decoder=lambda _event_type, _message: ESCAPE_HOTKEY_ID,
        )
        received = []
        backend.triggered.connect(received.append)

        backend.start(FakeWindow())
        self.assertEqual(escape_registrations, [])
        self.assertNotIn(ESCAPE_HOTKEY_ID, backend.registered_ids)

        backend.set_recording_active(True)
        backend.set_recording_active(True)
        self.assertEqual(escape_registrations, [("fake-user32", 123)])
        self.assertIn(ESCAPE_HOTKEY_ID, backend.registered_ids)

        target.installed[0].nativeEventFilter(b"windows_generic_MSG", object())
        self.assertEqual(received, ["escape"])

        backend.set_recording_active(False)
        self.assertEqual(escape_unregistrations, [("fake-user32", 123)])
        self.assertNotIn(ESCAPE_HOTKEY_ID, backend.registered_ids)
        target.installed[0].nativeEventFilter(b"windows_generic_MSG", object())
        self.assertEqual(received, ["escape"])

        backend.stop()

    def test_backend_stop_cleans_escape_registration_during_recording(self):
        escape_unregistrations = []

        backend = WindowsGlobalHotkeyBackend(
            FakeNativeEventTarget(),
            user32="fake-user32",
            register_hotkeys=lambda *_args, **_kwargs: {0x5101},
            unregister_hotkeys=lambda *_args, **_kwargs: None,
            register_escape=lambda *_args, **_kwargs: True,
            unregister_escape=lambda user32, hwnd: escape_unregistrations.append(
                (user32, hwnd)
            ),
        )

        backend.start(FakeWindow())
        backend.set_recording_active(True)
        backend.stop()

        self.assertEqual(escape_unregistrations, [("fake-user32", 123)])
        self.assertFalse(backend.registered_ids)

    def test_backend_registers_all_configured_workflow_actions(self):
        target = FakeNativeEventTarget()
        registration_settings = []
        unregistrations = []

        def register(_user32, _hwnd, settings, *, strict):
            self.assertTrue(strict)
            registration_settings.append(settings)
            return {0x5101, 0x5104}

        def unregister(_user32, _hwnd, registered):
            unregistrations.append(set(registered))

        backend = WindowsGlobalHotkeyBackend(
            target,
            settings=HotkeySettings.defaults(),
            user32="fake-user32",
            register_hotkeys=register,
            unregister_hotkeys=unregister,
        )

        self.assertEqual(
            backend.start(FakeWindow()),
            {0x5101, 0x5104},
        )
        self.assertEqual(len(registration_settings), 1)
        self.assertEqual(
            set(registration_settings[0].hotkeys),
            {
                HotkeyAction.RECORDING,
                HotkeyAction.REWRITE,
                HotkeyAction.TRANSLATION,
                HotkeyAction.VOICE_TRANSLATION,
                HotkeyAction.VISIBILITY,
            },
        )
        for action in (
            HotkeyAction.REWRITE,
            HotkeyAction.TRANSLATION,
            HotkeyAction.VOICE_TRANSLATION,
        ):
            self.assertIsNotNone(registration_settings[0].definition(action))
        self.assertEqual(backend.registered_ids, {0x5101, 0x5104})

        backend.stop()
        self.assertEqual(unregistrations, [{0x5101, 0x5104}])

    def test_running_backend_reconfigures_without_replacing_native_filter(self):
        target = FakeNativeEventTarget()
        registrations = []
        unregistrations = []

        def register(_user32, _hwnd, settings, *, strict):
            self.assertTrue(strict)
            registrations.append(settings)
            return {0x5101}

        def unregister(_user32, _hwnd, registered):
            unregistrations.append(set(registered))

        backend = WindowsGlobalHotkeyBackend(
            target,
            user32="fake-user32",
            register_hotkeys=register,
            unregister_hotkeys=unregister,
        )
        backend.start(FakeWindow())
        new_settings = HotkeySettings.defaults().with_hotkey(
            HotkeyAction.RECORDING,
            {"modifiers": ["ctrl"], "key": "Q"},
        )

        self.assertEqual(backend.reconfigure(new_settings), {0x5101})
        self.assertEqual(len(target.installed), 1)
        self.assertEqual(len(target.removed), 0)
        self.assertEqual(
            registrations[-1].definition(HotkeyAction.RECORDING).display,
            "Ctrl+Q",
        )
        self.assertEqual(unregistrations, [{0x5101}])

        backend.stop()
        self.assertEqual(unregistrations, [{0x5101}, {0x5101}])

    def test_failed_reconfigure_restores_the_previous_native_shortcuts(self):
        registrations = []

        def register(_user32, _hwnd, settings, *, strict):
            self.assertTrue(strict)
            registrations.append(settings)
            if len(registrations) == 2:
                raise RuntimeError("shortcut already registered")
            return {0x5101}

        backend = WindowsGlobalHotkeyBackend(
            FakeNativeEventTarget(),
            user32="fake-user32",
            register_hotkeys=register,
            unregister_hotkeys=lambda *_args: None,
        )
        backend.start(FakeWindow())
        previous = registrations[0]
        new_settings = HotkeySettings.defaults().with_hotkey(
            HotkeyAction.RECORDING,
            {"modifiers": ["ctrl"], "key": "Q"},
        )

        with self.assertRaisesRegex(RuntimeError, "already registered"):
            backend.reconfigure(new_settings)

        self.assertEqual(backend.registered_ids, {0x5101})
        self.assertEqual(registrations[-1], previous)
        backend.stop()

    def test_event_filter_factory_failure_unregisters_every_registered_id(self):
        target = FakeNativeEventTarget()
        registrations = {0x5101, 0x5102, 0x5103}
        unregistrations = []

        def register(_user32, _hwnd, _settings, *, strict):
            self.assertTrue(strict)
            return registrations

        def unregister(user32, hwnd, registered):
            unregistrations.append((user32, hwnd, set(registered)))

        def fail_factory(*_args, **_kwargs):
            raise RuntimeError("event filter construction failed")

        backend = WindowsGlobalHotkeyBackend(
            target,
            user32="fake-user32",
            register_hotkeys=register,
            unregister_hotkeys=unregister,
            event_filter_factory=fail_factory,
        )

        with self.assertRaisesRegex(RuntimeError, "event filter construction"):
            backend.start(FakeWindow())

        self.assertEqual(
            unregistrations,
            [("fake-user32", 123, registrations)],
        )
        self.assertEqual(backend.registered_ids, frozenset())
        self.assertFalse(backend.is_running)
        self.assertEqual(target.installed, [])

    def test_failed_start_retries_with_corrected_settings_on_reconfigure(self):
        target = FakeNativeEventTarget()
        registrations = []

        def register(_user32, _hwnd, settings, *, strict):
            self.assertTrue(strict)
            registrations.append(settings)
            if len(registrations) == 1:
                raise HotkeyRegistrationError([HotkeyAction.RECORDING.value])
            return {0x5101}

        backend = WindowsGlobalHotkeyBackend(
            target,
            user32="fake-user32",
            register_hotkeys=register,
            unregister_hotkeys=lambda *_args: None,
        )
        restarted = []
        backend.restarted.connect(lambda: restarted.append(True))
        window = FakeWindow()

        with self.assertRaises(HotkeyRegistrationError):
            backend.start(window)

        corrected = HotkeySettings.defaults().with_hotkey(
            HotkeyAction.RECORDING,
            {"modifiers": ["ctrl"], "key": "Q"},
        )
        self.assertEqual(backend.reconfigure(corrected), {0x5101})
        self.assertTrue(backend.is_running)
        self.assertEqual(restarted, [True])
        self.assertEqual(len(target.installed), 1)
        self.assertEqual(
            registrations[-1].definition(HotkeyAction.RECORDING).display,
            "Ctrl+Q",
        )

        backend.stop()

    @unittest.skipUnless(sys.platform == "linux", "Linux-only user32 seam test")
    def test_linux_requires_an_injected_user32_seam(self):
        backend = WindowsGlobalHotkeyBackend(FakeNativeEventTarget())
        with self.assertRaisesRegex(RuntimeError, "user32 seam"):
            backend.start(FakeWindow())


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class QtShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        FakeLock.locks.clear()

    def _shell(
        self,
        *,
        guard=None,
        hotkeys=None,
        visibility_hotkey_allowed=None,
    ):
        return QtShell(
            FakeWindow(),
            instance_guard=guard
            or QtSingleInstanceGuard(
                lock_path=Path(tempfile.gettempdir()) / "clarify-shell.lock",
                lock_factory=FakeLock,
                activation_api=FakeActivationApi(),
            ),
            hotkeys=hotkeys,
            visibility_hotkey_allowed=visibility_hotkey_allowed,
        )

    def test_secondary_process_does_not_acquire_hotkeys(self):
        guard = QtSingleInstanceGuard(
            lock_path=Path(tempfile.gettempdir()) / "clarify-shell.lock",
            lock_factory=FakeLock,
        )
        owner = QtSingleInstanceGuard(
            lock_path=Path(tempfile.gettempdir()) / "clarify-shell.lock",
            lock_factory=FakeLock,
        )
        self.assertTrue(owner.acquire())
        shell = self._shell(guard=guard, hotkeys=FakeHotkeys())

        self.assertFalse(shell.start())
        self.assertFalse(shell.is_running)

        owner.release()

    def test_primary_process_acquires_guard_without_a_tray(self):
        hotkeys = FakeHotkeys()
        shell = self._shell(hotkeys=hotkeys)

        self.assertTrue(shell.start())
        self.assertTrue(shell.is_running)
        self.assertTrue(shell._instance_guard.is_primary)
        self.assertTrue(hotkeys.is_running)

        shell.stop()
        self.assertFalse(shell._instance_guard.is_primary)

    def test_activation_event_reactivates_a_hidden_primary_window(self):
        class ActivationGuard:
            is_primary = False

            def __init__(self):
                self.callback = None
                self.released = False

            def acquire(self):
                self.is_primary = True
                return True

            def start_activation_listener(self, callback):
                self.callback = callback

            def release(self):
                self.is_primary = False
                self.released = True

        guard = ActivationGuard()
        shell = self._shell(guard=guard)
        self.assertTrue(shell.start())

        shell.hide_window()
        self.assertFalse(shell._window.visible)
        guard.callback()

        self.assertTrue(shell._window.visible)
        self.assertEqual(shell._window.calls[-3:], ["show", "raise", "activate"])

        shell.stop()
        self.assertTrue(guard.released)

    def test_primary_shell_owns_input_and_window_actions(self):
        hotkeys = FakeHotkeys()
        shell = self._shell(hotkeys=hotkeys)
        self.assertTrue(shell.start())
        self.assertEqual(hotkeys.started_with, shell._window)
        hotkeys.triggered.emit("toggle_visibility")
        self.assertTrue(shell._window.visible)
        shell.hide_window()
        self.assertFalse(shell._window.visible)
        shell.stop()
        self.assertFalse(shell.is_running)

    def test_visibility_hotkey_is_ignored_while_recording(self):
        hotkeys = FakeHotkeys()
        recording = True
        shell = self._shell(
            hotkeys=hotkeys,
            visibility_hotkey_allowed=lambda: not recording,
        )
        visibility_events = []
        shell.hotkeyTriggered.connect(visibility_events.append)
        self.assertTrue(shell.start())

        hotkeys.triggered.emit("toggle_visibility")

        self.assertEqual(visibility_events, [])
        self.assertEqual(shell._window.calls, [])

        recording = False
        hotkeys.triggered.emit("toggle_visibility")

        self.assertEqual(visibility_events, ["toggle_visibility"])
        self.assertEqual(shell._window.calls, ["show", "raise", "activate"])
        shell.stop()

    def test_hotkey_setup_failure_cleans_backend_but_retains_guard(self):
        hotkeys = FailingHotkeys()
        shell = self._shell(hotkeys=hotkeys)

        with self.assertRaisesRegex(RuntimeError, "hotkey setup failed"):
            shell.start()

        self.assertFalse(shell.is_running)
        self.assertTrue(shell._instance_guard.is_primary)
        self.assertFalse(hotkeys.is_running)
        self.assertEqual(hotkeys.stop_calls, 1)

        shell.stop()
        self.assertFalse(shell._instance_guard.is_primary)

    def test_shell_recovers_after_corrected_hotkey_reconfigure(self):
        target = FakeNativeEventTarget()
        registrations = []

        def register(_user32, _hwnd, _settings, *, strict):
            self.assertTrue(strict)
            registrations.append(True)
            if len(registrations) == 1:
                raise HotkeyRegistrationError([HotkeyAction.RECORDING.value])
            return {0x5101}

        backend = WindowsGlobalHotkeyBackend(
            target,
            user32="fake-user32",
            register_hotkeys=register,
            unregister_hotkeys=lambda *_args: None,
        )
        shell = self._shell(hotkeys=backend)

        with self.assertRaises(HotkeyRegistrationError):
            shell.start()

        self.assertFalse(shell.is_running)
        self.assertTrue(shell._instance_guard.is_primary)

        corrected = HotkeySettings.defaults().with_hotkey(
            HotkeyAction.RECORDING,
            {"modifiers": ["ctrl"], "key": "Q"},
        )
        backend.reconfigure(corrected)

        self.assertTrue(shell.is_running)

        shell.stop()
        self.assertFalse(shell._instance_guard.is_primary)

    def test_stop_is_idempotent_after_started_shell(self):
        hotkeys = FakeHotkeys()
        shell = self._shell(hotkeys=hotkeys)

        self.assertTrue(shell.start())

        shell.stop()
        shell.stop()

        self.assertFalse(shell.is_running)
        self.assertFalse(shell._instance_guard.is_primary)
        self.assertEqual(hotkeys.stop_calls, 1)


class QtShellSourceTests(unittest.TestCase):
    def test_module_has_no_legacy_ui_imports(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])

        self.assertNotIn("app", imported_roots)
        self.assertNotIn("customtkinter", imported_roots)
        self.assertNotIn("tkinter", imported_roots)
        self.assertIn("PySide6", imported_roots)

        source = MODULE.read_text(encoding="utf-8")
        self.assertIn("_UNSUPPORTED_SHELL_HOTKEY_ACTIONS", source)
        self.assertIn("voice", source.lower())
        self.assertNotIn("translation in this slice", source.lower())


if __name__ == "__main__":
    unittest.main()
