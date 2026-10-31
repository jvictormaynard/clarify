"""Focused tests for the typed Qt Quick settings controller."""

from __future__ import annotations

import ast
import gc
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import weakref
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


from tests.support.settings import (
    _repositories,
    _MicrophoneBackend,
)

try:
    from PySide6.QtWidgets import QApplication
except (ImportError, ModuleNotFoundError):
    PYSIDE6_AVAILABLE = False
else:
    PYSIDE6_AVAILABLE = True

if PYSIDE6_AVAILABLE:
    from clarify.desktop import qml_settings
    from clarify.desktop.qml_settings import QmlSettingsController

from repositories import (
    AppConfig,
    ApplicationRepositories,
    LocalConfigRepository,
    LocalUsageStatsRepository,
)
from secret_store import MemorySecretStore
from shared.localization import translate
from provider_types import ModelCatalog
from workflow_config import WorkflowScope
from microphone_controls import (
    MicrophoneDevice,
    MicrophoneInventory,
    RecordingControls,
)
from hotkey_config import HotkeyAction, HotkeySettings
from text_actions import native_bindings, settings_for


ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "clarify" / "desktop" / "qml_settings.py"


class _RegistryKey:
    def __init__(self, registry):
        self.registry = registry

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Registry:
    HKEY_CURRENT_USER = 1
    REG_SZ = 1

    def __init__(self):
        self.values = {}
        self.types = {}

    def CreateKey(self, *_args):
        return _RegistryKey(self)

    def OpenKey(self, *_args):
        return _RegistryKey(self)

    def SetValueEx(self, _key, name, _reserved, kind, value):
        self.values[name] = value
        self.types[name] = kind

    def QueryValueEx(self, _key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.types.get(name, self.REG_SZ)

    def DeleteValue(self, _key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]
        self.types.pop(name, None)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class QmlSettingsControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        from unittest.mock import Mock

        self.inventory_source = Mock(
            snapshot=Mock(
                return_value=MicrophoneInventory.unavailable("portaudio_unavailable")
            )
        )

    def _controller(self, *args, **kwargs):
        kwargs.setdefault("microphone_inventory_source", self.inventory_source)
        controller = QmlSettingsController(*args, **kwargs)
        self.addCleanup(self._close_controller, weakref.ref(controller))
        return controller

    @staticmethod
    def _close_controller(reference):
        controller = reference()
        if controller is not None:
            controller.shutdown()

    def _wait_for_inventory(self, controller):
        deadline = time.monotonic() + 2
        while controller.microphoneInventoryBusy and time.monotonic() < deadline:
            self.qt_app.processEvents()
            time.sleep(0.001)
        self.assertFalse(controller.microphoneInventoryBusy)

    def _preference_controller(self, directory, **kwargs):
        from unittest.mock import Mock
        from local_asr_product import LocalASRProductState

        controller = self._controller(
            _repositories(directory),
            local_product=Mock(state=LocalASRProductState("installed"), busy=False),
            microphone_backend=_MicrophoneBackend(
                MicrophoneInventory.unavailable("test")
            ),
            **kwargs,
        )
        self.addCleanup(controller.shutdown)
        return controller

    def test_preference_hotkeys_persist_only_the_requested_binding_or_mode(self):
        with TemporaryDirectory() as directory:
            applied = []
            controller = self._preference_controller(
                directory, hotkey_applier=applied.append
            )
            repo = controller.repositories.config
            original = repo.load().hotkeys
            controller.setHotkey("rewrite_hotkey", "Ctrl+Shift+K")
            self.assertTrue(
                controller.savePreference(
                    "setHotkey", ["recording_hotkey", "Ctrl+Shift+L"]
                )
            )
            self.assertEqual(
                repo.load().hotkeys.definition(HotkeyAction.RECORDING).display,
                "Ctrl+Shift+L",
            )
            self.assertEqual(
                repo.load().hotkeys.definition(HotkeyAction.REWRITE),
                original.definition(HotkeyAction.REWRITE),
            )
            self.assertEqual(
                controller.hotkeyDefinitions["rewrite_hotkey"]["display"],
                "Ctrl+Shift+K",
            )
            self.assertTrue(controller.dirty)
            saved = repo.load()
            self.assertEqual(
                applied[-1], native_bindings(saved, settings_for(saved).actions)
            )

            with patch.object(
                controller._hotkey_settings_controller, "push_to_talk_supported", True
            ):
                self.assertTrue(
                    controller.savePreference(
                        "setHotkeyActivationMode", ["push_to_talk"]
                    )
                )
            self.assertEqual(repo.load().hotkeys.activation_mode.value, "push_to_talk")
            self.assertEqual(
                repo.load().hotkeys.definition(HotkeyAction.REWRITE),
                original.definition(HotkeyAction.REWRITE),
            )
            self.assertTrue(
                controller.savePreference("resetHotkey", ["recording_hotkey"])
            )
            self.assertEqual(
                repo.load().hotkeys.definition(HotkeyAction.RECORDING),
                original.definition(HotkeyAction.RECORDING),
            )
            self.assertTrue(controller.savePreference("resetAllHotkeys", []))
            self.assertEqual(repo.load().hotkeys, HotkeySettings.defaults())
            self.assertFalse(controller.dirty)
            self.assertTrue(controller.load())
            self.assertEqual(controller.hotkeyActivationMode, "toggle")

    def test_library_context_slots_keep_legacy_save_order_and_accept_context(self):
        with TemporaryDirectory() as directory:
            controller = self._preference_controller(directory)
            entries = [{"term": "Zebra"}, {"term": "Alpha"}]
            self.assertTrue(controller.setDictionaryEntries(entries))
            self.assertTrue(controller.save())
            self.assertEqual(
                [row["term"] for row in controller.dictionaryEntries],
                ["Zebra", "Alpha"],
            )
            self.assertTrue(controller.setDictionaryEntries(entries, "local"))
            self.assertTrue(controller.save("local"))
            expected = controller.dictionaryEntries
            self.assertTrue(controller.setDictionaryEntries(entries, "local", expected))
            self.assertTrue(controller.setSnippets([], "local", []))
            signatures = {
                bytes(controller.metaObject().method(index).methodSignature()).decode()
                for index in range(controller.metaObject().methodCount())
            }
            self.assertTrue(
                {
                    "save()",
                    "save(QString)",
                    "setDictionaryEntries(QVariantList)",
                    "setDictionaryEntries(QVariantList,QString)",
                    "setDictionaryEntries(QVariantList,QString,QVariantList)",
                    "setSnippets(QVariantList,QString)",
                    "setSnippets(QVariantList,QString,QVariantList)",
                }.issubset(signatures)
            )

    def test_preference_hotkey_failure_rolls_back_partial_registration_and_retries(
        self,
    ):
        with TemporaryDirectory() as directory:
            applied = []
            fail = [True]

            def apply(settings):
                applied.append(settings)
                if fail[0]:
                    fail[0] = False
                    raise OSError("registration failed")

            controller = self._preference_controller(directory, hotkey_applier=apply)
            original = controller.repositories.config.load()
            self.assertFalse(
                controller.savePreference(
                    "setHotkey", ["recording_hotkey", "Ctrl+Shift+L"]
                )
            )
            self.assertEqual(controller.repositories.config.load(), original)
            self.assertEqual(
                applied[-1], native_bindings(original, settings_for(original).actions)
            )
            self.assertEqual(
                controller.hotkeyDefinitions["recording_hotkey"]["display"],
                original.hotkeys.definition(HotkeyAction.RECORDING).display,
            )
            self.assertFalse(controller.dirty)
            self.assertTrue(
                controller.savePreference(
                    "setHotkey", ["recording_hotkey", "Ctrl+Shift+L"]
                )
            )
            saved = controller.repositories.config.load()
            self.assertEqual(
                applied[-1], native_bindings(saved, settings_for(saved).actions)
            )

    def test_preference_hotkey_storage_failure_restores_runtime_and_draft(self):
        with TemporaryDirectory() as directory:
            applied = []
            controller = self._preference_controller(
                directory, hotkey_applier=applied.append
            )
            repo = controller.repositories.config
            original = repo.load()
            controller.setLanguage("pt")
            with patch.object(repo, "apply", side_effect=OSError("disk full")):
                self.assertFalse(
                    controller.savePreference(
                        "setHotkey", ["recording_hotkey", "Ctrl+Shift+L"]
                    )
                )
            self.assertEqual(repo.load(), original)
            self.assertEqual(
                applied[-1], native_bindings(original, settings_for(original).actions)
            )
            self.assertEqual(controller.language, "pt")
            self.assertTrue(controller.dirty)
            self.assertTrue(
                controller.savePreference(
                    "setHotkey", ["recording_hotkey", "Ctrl+Shift+L"]
                )
            )
            self.assertNotEqual(repo.load().hotkeys, original.hotkeys)
            self.assertEqual(repo.load().ui.language, original.ui.language)

    def test_preference_hotkey_failed_rollback_can_reapply_the_saved_value(self):
        from unittest.mock import Mock

        with TemporaryDirectory() as directory:
            apply = Mock(
                side_effect=[
                    OSError("register failed"),
                    OSError("restore failed"),
                    None,
                ]
            )
            controller = self._preference_controller(directory, hotkey_applier=apply)
            original = controller.repositories.config.load()
            self.assertFalse(
                controller.savePreference(
                    "setHotkey", ["recording_hotkey", "Ctrl+Shift+L"]
                )
            )
            self.assertEqual(controller.repositories.config.load(), original)
            self.assertTrue(
                controller.savePreference("resetHotkey", ["recording_hotkey"])
            )
            self.assertEqual(apply.call_count, 3)
            self.assertEqual(
                apply.call_args.args[0],
                native_bindings(original, settings_for(original).actions),
            )

    def test_preference_capture_restore_failure_keeps_the_operation_retryable(self):
        from unittest.mock import Mock

        with TemporaryDirectory() as directory:
            capture = Mock(side_effect=[None, OSError("restore failed"), None])
            controller = self._preference_controller(
                directory, hotkey_capture_changed=capture
            )
            original = controller.repositories.config.load()
            self.assertTrue(controller.beginHotkeyCapture("recording_hotkey"))
            self.assertFalse(
                controller.savePreference(
                    "setHotkey", ["recording_hotkey", "Ctrl+Shift+L"]
                )
            )
            self.assertEqual(controller.repositories.config.load(), original)
            self.assertEqual(controller.hotkeyCaptureAction, "recording_hotkey")
            self.assertTrue(
                controller.savePreference(
                    "setHotkey", ["recording_hotkey", "Ctrl+Shift+L"]
                )
            )
            self.assertEqual(controller.hotkeyCaptureAction, "")

    def test_preference_autostart_registry_failure_does_not_write_config(self):
        with TemporaryDirectory() as directory:
            registry = _Registry()
            controller = self._preference_controller(directory, registry=registry)
            repo = controller.repositories.config
            original = repo.load()
            with patch.object(qml_settings, "_is_windows", return_value=True):
                with patch.object(
                    registry, "SetValueEx", side_effect=OSError("registry unavailable")
                ):
                    self.assertFalse(controller.savePreference("setAutostart", [True]))
                self.assertEqual(repo.load(), original)
                self.assertFalse(controller.autostart)
                self.assertTrue(controller.savePreference("setAutostart", [True]))

    def test_preference_autostart_storage_failure_restores_registry_and_retries(self):
        with TemporaryDirectory() as directory:
            registry = _Registry()
            controller = self._preference_controller(directory, registry=registry)
            repo = controller.repositories.config
            original = repo.load()
            controller.setLanguage("pt")
            with patch.object(qml_settings, "_is_windows", return_value=True):
                with patch.object(repo, "apply", side_effect=OSError("disk full")):
                    self.assertFalse(controller.savePreference("setAutostart", [True]))
                self.assertEqual(repo.load(), original)
                self.assertEqual(registry.values, {})
                self.assertFalse(controller.autostart)
                self.assertEqual(controller.language, "pt")
                self.assertTrue(controller.savePreference("setAutostart", [True]))
                self.assertTrue(repo.load().startup.autostart)
                self.assertIn(qml_settings.AUTOSTART_VALUE_NAME, registry.values)
                self.assertEqual(repo.load().ui.language, original.ui.language)

    def test_preference_use_local_asr_persists_route_without_text_drafts(self):
        with TemporaryDirectory() as directory:
            controller = self._preference_controller(directory)
            repo = controller.repositories.config
            original = repo.load()
            controller.setRoutePrompt("Pending transcription prompt")
            controller.selectWorkflow("rewrite")
            controller.setRoutePrompt("Pending rewrite prompt")
            controller._local_profile = "ggml-small"
            controller._local_device = "cpu"
            self.assertTrue(controller.savePreference("useLocalAsr", []))
            saved = repo.load()
            self.assertEqual(saved.workflow("transcription").provider_id, "local_asr")
            self.assertEqual(saved.workflow("transcription").model_id, "ggml-small")
            self.assertTrue(saved.workflow("transcription").enabled)
            self.assertEqual(saved.local_asr_device, "cpu")
            self.assertEqual(
                saved.workflow("transcription").prompt,
                original.workflow("transcription").prompt,
            )
            self.assertEqual(saved.workflow("rewrite"), original.workflow("rewrite"))
            self.assertEqual(controller.selectedScope, "transcription")
            self.assertEqual(controller.routePrompt, "Pending transcription prompt")
            self.assertTrue(controller.dirty)

    def test_microphone_inventory_does_not_block_construction_or_qt_heartbeat(self):
        from PySide6.QtCore import QTimer
        from unittest.mock import Mock

        entered, release, completed = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        query_threads = []
        inventory = self._microphone_inventory()
        backend = _MicrophoneBackend(inventory)

        def query():
            query_threads.append(threading.current_thread())
            entered.set()
            release.wait(1)
            completed.set()
            return inventory

        backend.microphone_inventory = query
        with TemporaryDirectory() as directory:
            controller = self._controller(
                _repositories(directory),
                microphone_backend=backend,
                local_product=Mock(
                    state=qml_settings.LocalASRProductState("missing"), busy=False
                ),
            )
            try:
                self.assertTrue(entered.wait(1))
                self.assertFalse(
                    completed.is_set(), "Construction waited for the device query"
                )
                self.assertNotEqual(query_threads, [threading.current_thread()])
                heartbeat = []
                QTimer.singleShot(0, lambda: heartbeat.append(True))
                self.qt_app.processEvents()
                self.assertEqual(heartbeat, [True])
                self.assertFalse(completed.is_set())
            finally:
                release.set()
                controller.shutdown()

    def test_refresh_shares_pending_query_and_keeps_last_inventory_and_draft_error(
        self,
    ):
        from PySide6.QtCore import QTimer

        backend = _MicrophoneBackend(self._microphone_inventory())
        with TemporaryDirectory() as directory:
            controller = self._controller(
                _repositories(directory), microphone_backend=backend
            )
            release, entered, completed = (
                threading.Event(),
                threading.Event(),
                threading.Event(),
            )
            try:
                self._wait_for_inventory(controller)
                previous = controller.microphoneDevices
                calls = []

                def query():
                    calls.append(True)
                    entered.set()
                    release.wait(1)
                    completed.set()
                    return MicrophoneInventory.unavailable("enumeration_failed")

                backend.microphone_inventory = query
                self.assertTrue(controller.refreshMicrophoneInventory())
                self.assertTrue(entered.wait(1))
                self.assertFalse(
                    completed.is_set(), "Refresh waited for the device query"
                )
                self.assertTrue(controller.refreshMicrophoneInventory())
                self.assertEqual(calls, [True])
                self.assertEqual(controller.microphoneDevices, previous)
                self.assertFalse(
                    controller.setRecordingControls(
                        {"max_duration_seconds": 2, "warning_seconds": 3}
                    )
                )
                draft_error = controller.lastError
                heartbeat = []
                QTimer.singleShot(0, lambda: heartbeat.append(True))
                self.qt_app.processEvents()
                self.assertEqual(heartbeat, [True])
                release.set()
                self._wait_for_inventory(controller)
                self.assertEqual(controller.lastError, draft_error)
                self.assertEqual(controller.microphoneSelectionState, "unavailable")
            finally:
                release.set()
                controller.shutdown()

    def test_shutdown_rejects_pending_inventory_completion(self):
        release, entered, completed = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        backend = _MicrophoneBackend(self._microphone_inventory())

        def query():
            entered.set()
            release.wait(10)
            completed.set()
            return self._microphone_inventory()

        backend.microphone_inventory = query
        with TemporaryDirectory() as directory:
            controller = self._controller(
                _repositories(directory), microphone_backend=backend
            )
            try:
                self.assertTrue(entered.wait(1))
                self.assertFalse(completed.is_set())
                controller.shutdown()
                self.assertFalse(
                    completed.is_set(), "Shutdown waited for the hardware query"
                )
                published = []
                controller.microphoneChanged.connect(lambda: published.append(True))
                release.set()
                self.assertTrue(completed.wait(1))
                self.qt_app.processEvents()
                self.assertEqual(published, [])
            finally:
                release.set()
                controller.shutdown()

    def test_default_microphone_backend_is_loaded_only_on_discovery_worker(self):
        from unittest.mock import Mock

        release, entered = threading.Event(), threading.Event()
        threads = []
        inventory = self._microphone_inventory()

        def load():
            threads.append(threading.current_thread())
            entered.set()
            release.wait(1)
            return Mock(snapshot=lambda: inventory)

        with (
            TemporaryDirectory() as directory,
            patch.object(
                qml_settings, "_default_microphone_inventory_source", side_effect=load
            ),
        ):
            controller = self._controller(
                _repositories(directory),
                microphone_inventory_source=None,
                local_product=Mock(
                    state=qml_settings.LocalASRProductState("missing"), busy=False
                ),
            )
            worker = controller._microphone_inventory_thread
            try:
                self.assertTrue(entered.wait(1))
                self.assertNotEqual(threads, [threading.current_thread()])
                self.assertTrue(controller.microphoneInventoryBusy)
                published = []
                controller.microphoneChanged.connect(
                    lambda: published.append(threading.current_thread())
                )
                release.set()
                self._wait_for_inventory(controller)
                self.assertEqual(published, [threading.current_thread()])
                self.assertEqual(controller.microphoneInventory, inventory.to_mapping())
            finally:
                release.set()
                controller.shutdown()
                worker.join(2)
                self.assertFalse(worker.is_alive())

    def test_rpc_capture_pauses_and_restores_inputs_on_save_or_cancel(self):
        from clarify.desktop.qml_web_settings import SettingsProtocol

        with TemporaryDirectory() as directory:
            changes = []
            controller = self._controller(
                _repositories(directory), hotkey_capture_changed=changes.append
            )
            protocol = SettingsProtocol(controller)
            try:
                reply = protocol.dispatch(
                    {"method": "beginHotkeyCapture", "args": ["recording_hotkey"]}
                )
                self.assertEqual(
                    reply["result"]["hotkeyCaptureAction"], "recording_hotkey"
                )
                self.assertEqual(changes, [True])
                reply = protocol.dispatch(
                    {"method": "setHotkey", "args": ["recording_hotkey", "XBUTTON1"]}
                )
                self.assertEqual(reply["result"]["hotkeyCaptureAction"], "")
                self.assertEqual(changes, [True, False])
                controller.beginHotkeyCapture("rewrite_hotkey")
                protocol.dispatch({"method": "cancelHotkeyCapture", "args": []})
                self.assertEqual(changes, [True, False, True, False])
                self.assertEqual(controller.hotkeyCaptureAction, "")
                controller.beginHotkeyCapture("recording_hotkey")
                controller.load()
                self.assertEqual(changes[-2:], [True, False])
            finally:
                controller.shutdown()

    def test_shutdown_releases_local_subscription_and_controller(self):
        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))
            product = controller._local_product
            reference = weakref.ref(controller)
            controller.shutdown()
            self.assertEqual(product._listeners, [])
            del controller
            self.qt_app.processEvents()
            gc.collect()
            self.assertIsNone(reference())

    def test_shutdown_prevents_late_inventory_delivery_to_qt(self):
        from PySide6.QtCore import Slot
        from unittest.mock import Mock

        entered, release = threading.Event(), threading.Event()
        deliveries = []

        class ObservedController(QmlSettingsController):
            @Slot(int, object)
            def _finish_microphone_inventory(self, generation, payload):
                deliveries.append(threading.get_ident())
                super()._finish_microphone_inventory(generation, payload)

        def query():
            entered.set()
            if not release.wait(10):
                raise AssertionError("inventory gate was not released")
            return self._microphone_inventory()

        backend = _MicrophoneBackend(self._microphone_inventory())
        backend.microphone_inventory = query
        with TemporaryDirectory() as directory:
            controller = ObservedController(
                _repositories(directory),
                microphone_backend=backend,
                local_product=Mock(
                    state=qml_settings.LocalASRProductState("installed"), busy=False
                ),
            )
            worker = controller._microphone_inventory_thread
            try:
                self.assertTrue(entered.wait(1))
                controller.shutdown()
                self.assertFalse(release.is_set())
                release.set()
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.qt_app.processEvents()
                self.assertEqual(deliveries, [])
            finally:
                release.set()
                worker.join(timeout=2)
                controller.shutdown()

    def test_shutdown_discards_local_state_queued_before_close(self):
        self._assert_closed_local_listener(after_shutdown=False)

    def test_shutdown_rejects_listener_copied_before_unsubscribe(self):
        self._assert_closed_local_listener(after_shutdown=True)

    def test_background_state_keeps_newest_subscription_on_qt_thread(self):
        from unittest.mock import Mock

        initial = qml_settings.LocalASRProductState("installed")
        latest = qml_settings.LocalASRProductState("installing", current=50, total=100)
        product = Mock(state=initial, busy=False)
        with (
            TemporaryDirectory() as directory,
            patch(
                "local_asr_catalog.devices",
                return_value=[{"id": "cpu", "label": "CPU"}],
            ) as devices,
        ):
            controller = self._controller(
                _repositories(directory), local_product=product
            )
            self._wait_for_inventory(controller)
            controller._local_inventory_thread.join(timeout=1)
            self.assertFalse(controller._local_inventory_thread.is_alive())
            devices.assert_called_once_with()
            controller._drain_background_publications()
            self.qt_app.processEvents()
            changes = []
            controller.providerStateChanged.connect(
                lambda: changes.append(threading.get_ident())
            )
            old_listener = product.subscribe.call_args.args[0]
            controller._local_generation += 1
            new_listener = controller._local_state_callback(
                controller._local_generation
            )

            def publish():
                new_listener(latest)
                old_listener(qml_settings.LocalASRProductState("missing"))

            worker = threading.Thread(target=publish)
            worker.start()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(controller._local_state, initial)
            deadline = time.monotonic() + 2
            while controller._local_state != latest and time.monotonic() < deadline:
                self.qt_app.processEvents()
            self.assertEqual(controller._local_state, latest)
            self.assertEqual(changes, [threading.get_ident()])

    def _assert_closed_local_listener(self, *, after_shutdown):
        from unittest.mock import Mock

        initial = qml_settings.LocalASRProductState("installed")
        product = Mock(state=initial, busy=False)
        with TemporaryDirectory() as directory:
            controller = self._controller(
                _repositories(directory), local_product=product
            )
            self._wait_for_inventory(controller)
            controller._local_inventory_thread.join(timeout=1)
            self.qt_app.processEvents()
            changes = []
            controller.providerStateChanged.connect(lambda: changes.append(True))
            listener = product.subscribe.call_args.args[0]
            if after_shutdown:
                controller.shutdown()
            worker = threading.Thread(
                target=listener,
                args=(qml_settings.LocalASRProductState("missing"),),
            )
            worker.start()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            if not after_shutdown:
                controller.shutdown()
            self.qt_app.processEvents()
            self.assertEqual(controller._local_state, initial)
            self.assertEqual(changes, [])

    def test_pending_local_device_query_does_not_retain_closed_qt_owner(self):
        from PySide6.QtCore import Qt
        from unittest.mock import Mock

        entered, release = threading.Event(), threading.Event()
        destroyed_on = []

        def query():
            entered.set()
            if not release.wait(10):
                raise AssertionError("local device gate was not released")
            return [{"id": "cpu", "label": "CPU"}]

        with (
            TemporaryDirectory() as directory,
            patch("local_asr_catalog.devices", side_effect=query),
        ):
            controller = self._controller(
                _repositories(directory),
                local_product=Mock(
                    state=qml_settings.LocalASRProductState("installed"), busy=False
                ),
            )
            worker = controller._local_inventory_thread
            reference = weakref.ref(controller)
            controller.destroyed.connect(
                lambda *_: destroyed_on.append(threading.get_ident()),
                Qt.ConnectionType.DirectConnection,
            )
            try:
                self.assertTrue(entered.wait(1))
                controller.shutdown()
                del controller
                gc.collect()
                self.assertIsNone(reference())
                self.assertEqual(destroyed_on, [threading.get_ident()])
                self.assertFalse(release.is_set())
            finally:
                release.set()
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())

    @staticmethod
    def _microphone_inventory():
        selected = MicrophoneDevice(
            stable_id="mic-selected",
            name="USB microphone",
            host_api="Windows WASAPI",
            input_channels=1,
            backend_index=7,
        )
        default = MicrophoneDevice(
            stable_id="mic-default",
            name="System microphone",
            host_api="Windows WASAPI",
            input_channels=1,
            is_default=True,
            backend_index=2,
        )
        return MicrophoneInventory.from_records(
            [selected, default], default_id=default.stable_id
        )

    def test_microphone_inventory_recovery_uses_stable_ids_and_typed_draft(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            repositories.config.save(
                AppConfig.from_mapping(
                    {"microphone": {"selected_id": "stale-microphone"}}
                )
            )
            backend = _MicrophoneBackend(self._microphone_inventory())
            controller = self._controller(
                repositories,
                microphone_backend=backend,
            )
            try:
                self._wait_for_inventory(controller)
                self.assertEqual(controller.selectedMicrophoneId, "stale-microphone")
                self.assertEqual(
                    controller.microphoneSelectionState,
                    "fallback_default",
                )
                self.assertIn(
                    translate(
                        "Saved microphone unavailable; using current default: {name}",
                        name="",
                    ).strip(),
                    controller.microphoneStatus,
                )
                self.assertEqual(controller.microphoneSelectionIndex, 0)
                self.assertEqual(
                    [option["id"] for option in controller.microphoneDevices],
                    ["", "mic-selected", "mic-default"],
                )

                self.assertTrue(controller.selectMicrophone("mic-selected"))
                self.assertEqual(controller.selectedMicrophoneId, "mic-selected")
                self.assertTrue(controller.setMicrophone(""))
                self.assertIsNone(controller.selectedMicrophoneId)

                self.assertTrue(
                    controller.setRecordingControls(
                        {
                            "max_duration_seconds": 45,
                            "warning_seconds": 5,
                            "vad": {
                                "enabled": True,
                                "level_threshold": 0.03,
                                "minimum_speech_seconds": 0.4,
                                "silence_duration_seconds": 1.2,
                            },
                        }
                    )
                )
                self.assertTrue(controller.dirty)
                self.assertTrue(controller.save())

                persisted = repositories.config.load()
                self.assertIsNone(persisted.microphone.selected_id)
                self.assertEqual(
                    persisted.recording_controls.max_duration_seconds,
                    45,
                )
                self.assertTrue(persisted.recording_controls.vad.enabled)
            finally:
                controller.shutdown()

    def test_recording_controls_reject_invalid_boundary_without_mutating_draft(self):
        with TemporaryDirectory() as directory:
            backend = _MicrophoneBackend(self._microphone_inventory())
            controller = self._controller(
                _repositories(directory),
                microphone_backend=backend,
            )
            try:
                before = controller.recordingControls
                self.assertFalse(
                    controller.setRecordingControls(
                        {"max_duration_seconds": 2, "warning_seconds": 3}
                    )
                )
                self.assertIn("cannot exceed", controller.lastError)
                self.assertEqual(controller.recordingControls, before)
                self.assertEqual(
                    controller.recordingControls,
                    RecordingControls.defaults().to_mapping(),
                )
            finally:
                controller.shutdown()

    def test_microphone_test_is_async_and_does_not_persist_audio(self):
        with TemporaryDirectory() as directory:
            backend = _MicrophoneBackend(self._microphone_inventory())
            controller = self._controller(
                _repositories(directory),
                microphone_backend=backend,
            )
            try:
                self._wait_for_inventory(controller)
                self.assertTrue(controller.testMicrophone())
                self.assertTrue(backend.test_started.wait(timeout=1))
                for _ in range(100):
                    self.qt_app.processEvents()
                    if not controller.microphoneTestBusy:
                        break
                    time.sleep(0.01)
                self.assertFalse(controller.microphoneTestBusy)
                self.assertEqual(
                    controller.microphoneTestStatus, "Microphone input detected."
                )
                self.assertEqual(controller.microphoneTestStatusKind, "ok")
                self.assertFalse((Path(directory) / "recording.wav").exists())
            finally:
                controller.shutdown()

    def test_live_microphone_levels_cancel_and_ignore_stale_callbacks(self):
        with TemporaryDirectory() as directory:
            backend = _MicrophoneBackend(self._microphone_inventory())
            callbacks = []
            closed = threading.Event()

            def preview(selection, inventory, *, on_level, cancel_event, duration):
                callbacks.append(on_level)
                self.assertEqual(duration, 30.0)
                on_level(0.6)
                cancel_event.wait(2)
                on_level(0.9)  # A queued callback after Stop must not revive the wave.
                closed.set()
                return 0.9

            backend.test_microphone = preview
            controller = self._controller(
                _repositories(directory), microphone_backend=backend
            )

            def until(predicate):
                for _ in range(100):
                    self.qt_app.processEvents()
                    if predicate():
                        return
                    time.sleep(0.01)
                self.fail("Microphone preview did not reach the expected state")

            try:
                self._wait_for_inventory(controller)
                original = controller._config
                self.assertTrue(controller.testMicrophone())
                until(lambda: controller.microphoneTestLevel == 0.6)
                self.assertFalse(controller.testMicrophone())
                controller.stopMicrophoneTest()
                self.assertEqual(controller.microphoneTestLevel, 0)
                self.assertTrue(closed.wait(1))
                until(lambda: not controller.microphoneTestBusy)
                self.assertEqual(controller.microphoneTestStatus, "Test stopped.")
                self.assertEqual(controller._config, original)
                old_callback = callbacks[0]
                self.assertTrue(controller.testMicrophone())
                until(lambda: controller.microphoneTestLevel == 0.6)
                old_callback(1.0)
                self.qt_app.processEvents()
                self.assertEqual(controller.microphoneTestLevel, 0.6)
                controller.refreshMicrophoneInventory()
                until(lambda: not controller.microphoneTestBusy)
                self._wait_for_inventory(controller)
                self.assertEqual(controller.microphoneTestLevel, 0)
                self.assertTrue(controller.testMicrophone())
                until(lambda: controller.microphoneTestLevel == 0.6)
                controller.load()
                until(lambda: not controller.microphoneTestBusy)
                self.assertTrue(controller.testMicrophone())
                controller.shutdown()
                self.assertFalse(controller._microphone_test_thread.is_alive())
            finally:
                controller.shutdown()

    def test_unavailable_inventory_exposes_recoverable_default_and_fails_closed_test(
        self,
    ):
        with TemporaryDirectory() as directory:
            backend = _MicrophoneBackend(
                MicrophoneInventory.unavailable("enumeration_failed")
            )
            controller = self._controller(
                _repositories(directory),
                microphone_backend=backend,
            )
            try:
                self._wait_for_inventory(controller)
                self.assertEqual(controller.microphoneDevices[0]["id"], "")
                self.assertEqual(controller.microphoneSelectionState, "unavailable")
                self.assertIn(
                    "Input inventory unavailable", controller.microphoneStatus
                )
                self.assertFalse(controller.testMicrophone())
                self.assertEqual(
                    controller.microphoneTestStatus,
                    "No safe microphone to test.",
                )
            finally:
                controller.shutdown()

    def test_load_exposes_typed_app_config_and_selected_route(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            repositories.config.save(
                AppConfig.from_mapping(
                    {
                        "ui_mode": "transcription",
                        "ui_language": "pt",
                        "autostart": True,
                        "history_enabled": True,
                        "history_retention_days": 14,
                        "workflows": {
                            "rewrite": {
                                "provider_id": "groq",
                                "model_id": "llama-3.3-70b-versatile",
                                "prompt": "Rewrite selected text only.",
                                "custom_endpoint": "https://proxy.example/v1",
                                "enabled": True,
                            }
                        },
                    }
                )
            )

            controller = self._controller(repositories)

            self.assertEqual(controller.mode, "prompt")
            self.assertEqual(controller.language, "pt")
            self.assertTrue(controller.autostart)
            self.assertTrue(controller.historyEnabled)
            self.assertEqual(controller.historyRetentionDays, 14)
            self.assertEqual(
                controller.workflowScopes,
                [scope.value for scope in WorkflowScope],
            )
            self.assertEqual(controller.selectedScope, "transcription")
            self.assertEqual(
                controller.routeFor("rewrite"),
                {
                    "scope": "rewrite",
                    "providerId": "groq",
                    "modelId": "llama-3.3-70b-versatile",
                    "prompt": "Rewrite selected text only.",
                    "customEndpoint": "https://proxy.example/v1",
                    "enabled": True,
                },
            )

            self.assertTrue(controller.selectWorkflow("rewrite"))
            self.assertEqual(controller.routeProviderId, "groq")
            self.assertEqual(controller.routeModelId, "llama-3.3-70b-versatile")

    def test_unconfigured_legacy_voice_shortcut_is_not_presented_as_active(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            repositories.config.save(
                AppConfig.from_mapping(
                    {
                        "hotkeys": {
                            "bindings": {
                                HotkeyAction.RECORDING.value: {
                                    "modifiers": ["ctrl"],
                                    "key": "Q",
                                },
                                HotkeyAction.REWRITE.value: {
                                    "modifiers": ["alt"],
                                    "key": "K",
                                },
                                HotkeyAction.TRANSLATION.value: {
                                    "modifiers": ["alt"],
                                    "key": "T",
                                },
                                HotkeyAction.VISIBILITY.value: {
                                    "modifiers": ["alt"],
                                    "key": "R",
                                },
                            }
                        }
                    }
                )
            )
            controller = self._controller(repositories)
            try:
                self.assertEqual(
                    [item["id"] for item in controller.hotkeyActions],
                    [action.value for action in HotkeyAction],
                )
                self.assertEqual(
                    controller.hotkeyDefinitions[HotkeyAction.RECORDING.value][
                        "display"
                    ],
                    "Ctrl+Q",
                )
                self.assertEqual(
                    controller.hotkeyDefinitions[HotkeyAction.VOICE_TRANSLATION.value][
                        "display"
                    ],
                    "Not configured",
                )
                self.assertEqual(
                    controller.hotkeyActivationModes,
                    ["toggle", "push_to_talk"],
                )
                self.assertEqual(controller.hotkeyActivationMode, "toggle")
            finally:
                controller.shutdown()

    def test_hotkey_capture_clears_when_definition_is_unchanged(self):
        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))
            try:
                self.assertTrue(
                    controller.beginHotkeyCapture(HotkeyAction.RECORDING.value)
                )
                current = controller.hotkeyDefinitions[HotkeyAction.RECORDING.value]
                self.assertTrue(
                    controller.setHotkey(
                        HotkeyAction.RECORDING.value,
                        {
                            "modifiers": current["modifiers"],
                            "key": current["key"],
                        },
                    )
                )
                self.assertEqual(controller.hotkeyCaptureAction, "")
            finally:
                controller.shutdown()

    def test_modifier_and_side_mouse_capture_rejects_primary_mouse(self):
        from PySide6.QtCore import Qt

        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))
            try:
                self.assertTrue(
                    controller.captureHotkey(
                        "recording_hotkey",
                        Qt.Key_Control.value,
                        Qt.ControlModifier.value,
                    )
                )
                self.assertEqual(
                    controller.hotkeyDefinitions["recording_hotkey"]["display"], "Ctrl"
                )
                self.assertFalse(
                    controller.captureMouseHotkey(
                        "recording_hotkey", Qt.LeftButton.value, 0
                    )
                )
                self.assertTrue(
                    controller.captureMouseHotkey(
                        "recording_hotkey",
                        Qt.BackButton.value,
                        Qt.ControlModifier.value,
                    )
                )
                self.assertEqual(
                    controller.hotkeyDefinitions["recording_hotkey"]["display"],
                    "Ctrl+Mouse 4",
                )
            finally:
                controller.shutdown()

    def test_hotkey_capture_rejects_conflicts_and_preserves_the_draft(self):
        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))
            try:
                self.assertTrue(
                    controller.beginHotkeyCapture(HotkeyAction.RECORDING.value)
                )
                self.assertEqual(
                    controller.hotkeyCaptureAction,
                    HotkeyAction.RECORDING.value,
                )
                self.assertFalse(
                    controller.captureHotkey(
                        HotkeyAction.RECORDING.value,
                        ord("K"),
                        134217728,  # Qt.KeyboardModifier.AltModifier
                    )
                )
                self.assertIn("conflict", controller.lastError.lower())
                self.assertEqual(
                    controller.hotkeyDefinitions[HotkeyAction.RECORDING.value][
                        "display"
                    ],
                    "Alt+L",
                )
                self.assertTrue(
                    controller.captureHotkey(
                        HotkeyAction.RECORDING.value,
                        ord("Q"),
                        67108864,  # Qt.KeyboardModifier.ControlModifier
                    )
                )
                self.assertEqual(controller.hotkeyCaptureAction, "")
                self.assertEqual(
                    controller.hotkeyDefinitions[HotkeyAction.RECORDING.value][
                        "display"
                    ],
                    "Ctrl+Q",
                )
                self.assertTrue(controller.dirty)
            finally:
                controller.shutdown()

    def test_hotkey_save_persists_and_reset_restores_shared_defaults(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = self._controller(repositories)
            try:
                self.assertTrue(
                    controller.setHotkey(
                        HotkeyAction.RECORDING.value,
                        {"modifiers": ["ctrl"], "key": "Q"},
                    )
                )
                self.assertTrue(controller.save())
                self.assertEqual(
                    repositories.config.load()
                    .hotkeys.definition(HotkeyAction.RECORDING)
                    .display,
                    "Ctrl+Q",
                )

                self.assertTrue(controller.resetHotkey(HotkeyAction.RECORDING.value))
                self.assertEqual(
                    controller.hotkeyDefinitions[HotkeyAction.RECORDING.value][
                        "display"
                    ],
                    HotkeySettings.defaults()
                    .definition(HotkeyAction.RECORDING)
                    .display,
                )
                self.assertTrue(controller.resetAllHotkeys())
                self.assertTrue(controller.save())
                self.assertEqual(
                    repositories.config.load().hotkeys,
                    HotkeySettings.defaults(),
                )
            finally:
                controller.shutdown()

    def test_hotkey_save_calls_production_applier_before_persistence(self):
        with TemporaryDirectory() as directory:
            applied = []
            repositories = _repositories(directory)
            controller = self._controller(
                repositories,
                hotkey_applier=applied.append,
            )
            try:
                self.assertTrue(
                    controller.setHotkey(
                        HotkeyAction.RECORDING.value,
                        {"modifiers": ["ctrl"], "key": "Q"},
                    )
                )
                self.assertTrue(controller.save())
                self.assertEqual(len(applied), 1)
                self.assertEqual(
                    applied[0].definition(HotkeyAction.RECORDING).display,
                    "Ctrl+Q",
                )
            finally:
                controller.shutdown()

    def test_provider_onboarding_validates_and_persists_key_in_secret_store(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret_store = MemorySecretStore()
            repositories = ApplicationRepositories(
                config=LocalConfigRepository(
                    root / "config.json",
                    secret_store=secret_store,
                ),
                usage_stats=LocalUsageStatsRepository(root / "usage.json"),
            )
            controller = self._controller(repositories)
            try:
                self.assertTrue(controller.selectProvider("openai"))
                self.assertFalse(controller.providerHasApiKey)
                controller.setProviderApiKey("onboarding-test-key")
                self.assertTrue(controller.providerDirty)

                with patch.object(
                    qml_settings.PROVIDER_REGISTRY,
                    "discover_models",
                    return_value=ModelCatalog(
                        audio_models=("whisper-1",),
                        text_models=("gpt-test",),
                    ),
                ):
                    self.assertTrue(controller.validateProvider())
                    for _ in range(100):
                        self.qt_app.processEvents()
                        if controller.providerStatus == "active":
                            break
                        time.sleep(0.01)

                self.assertEqual(controller.providerStatus, "active")
                self.assertTrue(controller.providerHasApiKey)
                self.assertEqual(secret_store.get("openai"), "onboarding-test-key")
                self.assertEqual(controller.providerApiKey, "")
                self.assertFalse(controller.providerDirty)
                self.assertNotIn(
                    "onboarding-test-key",
                    (root / "config.json").read_text(encoding="utf-8"),
                )
            finally:
                controller.shutdown()

    def test_provider_selection_loads_persisted_custom_endpoint(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret_store = MemorySecretStore()
            repositories = ApplicationRepositories(
                config=LocalConfigRepository(
                    root / "config.json",
                    secret_store=secret_store,
                ),
                usage_stats=LocalUsageStatsRepository(root / "usage.json"),
            )
            repositories.config.save(
                AppConfig.from_mapping(
                    {
                        "openai_api_key": "saved-key",
                        "openai_base_url": "https://proxy.example/v1",
                    }
                )
            )
            controller = self._controller(repositories)
            try:
                self.assertTrue(controller.selectProvider("openai"))
                self.assertEqual(
                    controller.providerBaseUrl,
                    "https://proxy.example/v1",
                )
            finally:
                controller.shutdown()

    def test_provider_validation_preserves_draft_for_newly_selected_provider(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = self._controller(repositories)
            started = threading.Event()
            release = threading.Event()

            def blocked_discovery(*_args):
                started.set()
                release.wait(timeout=2)
                return ModelCatalog(audio_models=("whisper-1",))

            try:
                self.assertTrue(controller.selectProvider("openai"))
                controller.setProviderApiKey("provider-a-key")
                controller.setProviderBaseUrl("https://openai-proxy.example/v1")

                with patch.object(
                    qml_settings.PROVIDER_REGISTRY,
                    "discover_models",
                    side_effect=blocked_discovery,
                ):
                    self.assertTrue(controller.validateProvider())
                    self.assertTrue(started.wait(timeout=2))

                    self.assertTrue(controller.selectProvider("groq"))
                    controller.setProviderApiKey("provider-b-draft")
                    controller.setProviderBaseUrl("https://groq-proxy.example/v1")
                    release.set()

                    for _ in range(100):
                        self.qt_app.processEvents()
                        if controller.providerStates["openai"]["status"] == "active":
                            break
                        time.sleep(0.01)

                self.assertEqual(
                    controller.providerStates["openai"]["status"], "active"
                )
                self.assertEqual(controller.selectedProviderId, "groq")
                self.assertEqual(controller.providerApiKey, "provider-b-draft")
                self.assertEqual(
                    controller.providerBaseUrl,
                    "https://groq-proxy.example/v1",
                )
            finally:
                release.set()
                controller.shutdown()

    def test_provider_validation_keeps_unrelated_qml_draft_out_of_persistence(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = self._controller(repositories)
            try:
                controller.setAutostart(True)
                self.assertTrue(controller.selectWorkflow("rewrite"))
                controller.setRoutePrompt("draft-only prompt")
                self.assertTrue(controller.selectProvider("openai"))
                controller.setProviderApiKey("draft-provider-key")

                with patch.object(
                    qml_settings.PROVIDER_REGISTRY,
                    "discover_models",
                    return_value=ModelCatalog(
                        audio_models=("whisper-1",),
                        text_models=("gpt-test",),
                    ),
                ):
                    self.assertTrue(controller.validateProvider())
                    for _ in range(100):
                        self.qt_app.processEvents()
                        if controller.providerStatus == "active":
                            break
                        time.sleep(0.01)

                persisted = repositories.config.load()
                self.assertTrue(controller.autostart)
                self.assertEqual(controller.routePrompt, "draft-only prompt")
                self.assertFalse(persisted.startup.autostart)
                self.assertNotEqual(
                    persisted.workflow("rewrite").prompt,
                    "draft-only prompt",
                )
                self.assertEqual(persisted.openai.api_key, "draft-provider-key")
            finally:
                controller.shutdown()

    def test_clearing_provider_invalidates_pending_validation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret_store = MemorySecretStore()
            repositories = ApplicationRepositories(
                config=LocalConfigRepository(
                    root / "config.json",
                    secret_store=secret_store,
                ),
                usage_stats=LocalUsageStatsRepository(root / "usage.json"),
            )
            repositories.config.save(
                AppConfig.from_mapping({"openai_api_key": "saved-key"})
            )
            controller = self._controller(repositories)
            started = threading.Event()
            release = threading.Event()

            def blocked_discovery(*_args):
                started.set()
                release.wait(timeout=2)
                return ModelCatalog(audio_models=("whisper-1",))

            try:
                controller.selectProvider("openai")
                with patch.object(
                    qml_settings.PROVIDER_REGISTRY,
                    "discover_models",
                    side_effect=blocked_discovery,
                ):
                    self.assertTrue(controller.validateProvider())
                    self.assertTrue(started.wait(timeout=2))
                    self.assertTrue(controller.clearProvider())
                    release.set()
                    for _ in range(100):
                        self.qt_app.processEvents()
                        time.sleep(0.01)

                self.assertFalse(controller.providerHasApiKey)
                self.assertIsNone(secret_store.get("openai"))
                self.assertEqual(repositories.config.load().openai.api_key, "")
            finally:
                release.set()
                controller.shutdown()

    def test_clear_provider_failure_restores_idle_error_state(self):
        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))
            pending = qml_settings.CancellationToken()
            try:
                controller.selectProvider("openai")
                controller._provider_generations["openai"] = 4
                controller._provider_tokens["openai"] = pending
                controller._provider_activity["openai"] = {
                    "status": "validating",
                    "error": "",
                    "models": [],
                    "textModels": [],
                    "busy": True,
                }

                with patch.object(
                    controller,
                    "_persist_provider_credentials",
                    side_effect=OSError("credential store unavailable"),
                ):
                    self.assertFalse(controller.clearProvider())

                self.assertTrue(pending.cancelled)
                self.assertFalse(controller.providerBusy)
                self.assertEqual(controller.providerStatus, "error")
                self.assertEqual(
                    controller.providerError,
                    "credential store unavailable",
                )
                self.assertIn("credential store unavailable", controller.lastError)
            finally:
                controller.shutdown()

    def test_properties_and_slots_update_one_typed_draft(self):
        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))
            changes = []
            routes = []
            controller.configChanged.connect(lambda: changes.append(True))
            controller.routeChanged.connect(lambda: routes.append(True))

            self.assertTrue(controller.selectWorkflow("translation"))
            self.assertTrue(controller.setMode("transcription"))
            self.assertTrue(controller.setLanguage("de"))
            self.assertTrue(controller.setAutostart(True))
            self.assertTrue(controller.setHistoryEnabled(True))
            self.assertTrue(controller.setHistoryRetentionDays(None))
            self.assertTrue(
                controller.setRoute(
                    "translation",
                    "openai",
                    "gpt-4o-mini",
                    "Translate literally.",
                    "https://proxy.example/v1",
                    True,
                )
            )

            self.assertTrue(controller.dirty)
            self.assertEqual(controller.mode, "prompt")
            self.assertEqual(controller.language, "de")
            self.assertTrue(controller.autostart)
            self.assertTrue(controller.historyEnabled)
            self.assertIsNone(controller.historyRetentionDays)
            self.assertGreaterEqual(len(changes), 5)
            self.assertGreaterEqual(len(routes), 2)
            self.assertFalse(controller.setMode("not-a-mode"))
            self.assertIn("Invalid mode", controller.lastError)
            self.assertFalse(controller.setHistoryRetentionDays(-1))
            self.assertIn("cannot be negative", controller.lastError)

    def test_every_route_edit_marks_the_route_independent(self):
        edit_cases = (
            ("setRouteProviderId", ("groq",)),
            ("setRouteModelId", ("custom-model",)),
            ("setRoutePrompt", ("Rewrite only.",)),
            ("setRouteCustomEndpoint", ("https://proxy.example/v1",)),
            ("setRouteEnabled", (False,)),
            (
                "setRoute",
                (
                    "rewrite",
                    "groq",
                    "llama-3.3-70b-versatile",
                    "Rewrite only.",
                    "",
                    True,
                ),
            ),
        )

        for method_name, arguments in edit_cases:
            with self.subTest(method=method_name):
                with TemporaryDirectory() as directory:
                    controller = self._controller(_repositories(directory))
                    self.assertTrue(controller.selectWorkflow("rewrite"))
                    self.assertFalse(controller._config.workflow("rewrite").independent)

                    self.assertTrue(getattr(controller, method_name)(*arguments))
                    self.assertTrue(controller._config.workflow("rewrite").independent)

    def test_invalid_route_queries_set_error_and_return_qml_safe_values(self):
        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))

            self.assertEqual(controller.routeFor("not-a-scope"), {})
            self.assertIn("Unknown workflow scope", controller.lastError)

            self.assertEqual(controller.providersForScope("not-a-scope"), [])
            self.assertIn("Unknown workflow scope", controller.lastError)

            self.assertEqual(controller.routeFor("rewrite")["scope"], "rewrite")
            self.assertEqual(controller.lastError, "")

    def test_valid_unchanged_edit_clears_a_previous_error(self):
        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))

            self.assertFalse(controller.setMode("not-a-mode"))
            self.assertNotEqual(controller.lastError, "")

            self.assertTrue(controller.setMode(controller.mode))
            self.assertEqual(controller.lastError, "")

    def test_history_retention_rejects_non_integer_float_without_truncating(self):
        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))

            self.assertFalse(controller.setHistoryRetentionDays(14.9))
            self.assertIn("must be an integer", controller.lastError)
            self.assertEqual(controller.historyRetentionDays, 30)

            self.assertTrue(controller.setHistoryRetentionDays(14.0))
            self.assertEqual(controller.historyRetentionDays, 14)

    def test_save_delegates_to_atomic_repository_apply_and_reloads_canonical_config(
        self,
    ):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = self._controller(repositories)
            controller.selectWorkflow("rewrite")
            controller.setRouteProviderId("groq")
            controller.setRouteModelId("llama-3.3-70b-versatile")
            controller.setRoutePrompt("Rewrite only.")

            with patch.object(
                repositories.config,
                "apply",
                wraps=repositories.config.apply,
            ) as apply:
                self.assertTrue(controller.save())

            apply.assert_called_once()
            self.assertFalse(controller.dirty)
            self.assertEqual(controller.lastError, "")
            persisted = repositories.config.load()
            self.assertEqual(
                persisted.workflow(WorkflowScope.REWRITE).provider_id,
                "groq",
            )
            self.assertEqual(
                persisted.workflow(WorkflowScope.REWRITE).model_id,
                "llama-3.3-70b-versatile",
            )
            self.assertTrue(persisted.workflow(WorkflowScope.REWRITE).independent)

            payload = json.loads(
                (Path(directory) / "config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["workflows"]["rewrite"]["provider_id"], "groq")

    def test_source_autostart_command_uses_absolute_qml_entrypoint(self):
        executable = r"C:\Program Files\Python311\python.exe"
        entrypoint = (SETTINGS.parent / "qml_app.py").resolve()

        with patch.object(qml_settings.sys, "frozen", False, create=True):
            command = qml_settings._autostart_command(executable)

        self.assertTrue(entrypoint.is_absolute())
        self.assertEqual(
            command,
            subprocess.list2cmdline([executable, str(entrypoint), "--hidden"]),
        )

    def test_frozen_autostart_command_does_not_append_source_script(self):
        executable = r"C:\Program Files\Clarify\Clarify.exe"

        with patch.object(qml_settings.sys, "frozen", True, create=True):
            command = qml_settings._autostart_command(executable)

        self.assertEqual(command, subprocess.list2cmdline([executable, "--hidden"]))

    def test_windows_save_applies_autostart_run_key_and_config(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            registry = _Registry()
            controller = self._controller(repositories, registry=registry)
            controller.setAutostart(True)
            with (
                patch("clarify.desktop.qml_settings._is_windows", return_value=True),
                patch.object(
                    repositories.config,
                    "apply",
                    wraps=repositories.config.apply,
                ) as apply,
            ):
                self.assertTrue(controller.save())

            apply.assert_called_once()
            self.assertIn("qml_app.py", registry.values["Clarify"])
            self.assertIn("--hidden", registry.values["Clarify"])
            self.assertTrue(repositories.config.load().startup.autostart)
            self.assertFalse(controller.dirty)

    def test_persist_preference_does_not_apply_the_settings_draft(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            repositories.config.save(
                AppConfig.from_mapping(
                    {
                        "ui_mode": "prompt",
                        "ui_language": "en",
                        "autostart": False,
                        "history_enabled": False,
                        "workflows": {
                            "rewrite": {
                                "provider_id": "openai",
                                "model_id": "gpt-4o-mini",
                                "prompt": "Persisted prompt",
                                "enabled": True,
                            }
                        },
                    }
                )
            )
            controller = self._controller(repositories)
            controller.selectWorkflow("rewrite")
            controller.setRoutePrompt("Draft prompt")
            controller.setHistoryEnabled(True)
            controller.setAutostart(True)

            self.assertTrue(controller.persistMode("transcription"))

            persisted = repositories.config.load()
            self.assertEqual(persisted.ui.mode, "prompt")
            self.assertEqual(persisted.ui.language, "en")
            self.assertFalse(persisted.startup.autostart)
            self.assertFalse(persisted.history_enabled)
            self.assertEqual(
                persisted.workflow("rewrite").prompt,
                "Persisted prompt",
            )
            self.assertEqual(controller.mode, "prompt")
            self.assertEqual(controller.routePrompt, "Draft prompt")
            self.assertTrue(controller.autostart)
            self.assertTrue(controller.historyEnabled)
            self.assertTrue(controller.dirty)

    def test_windows_save_removes_autostart_when_disabled(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            registry = _Registry()
            registry.values["Clarify"] = r"C:\Legacy\Clarify.exe --old"
            controller = self._controller(repositories, registry=registry)

            with patch("clarify.desktop.qml_settings._is_windows", return_value=True):
                self.assertTrue(controller.save())

            self.assertNotIn("Clarify", registry.values)
            self.assertNotIn("Clarify", registry.types)
            self.assertFalse(repositories.config.load().startup.autostart)

    def test_windows_save_restores_registry_when_apply_fails(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            registry = _Registry()
            registry.values["Clarify"] = r"C:\Legacy\Clarify.exe --old"
            registry.types["Clarify"] = 42
            controller = self._controller(repositories, registry=registry)
            controller.setAutostart(True)
            with (
                patch("clarify.desktop.qml_settings._is_windows", return_value=True),
                patch.object(
                    repositories.config,
                    "apply",
                    side_effect=OSError("simulated config write failure"),
                ),
            ):
                self.assertFalse(controller.save())

            self.assertEqual(
                registry.values["Clarify"],
                r"C:\Legacy\Clarify.exe --old",
            )
            self.assertEqual(registry.types["Clarify"], 42)
            self.assertFalse(repositories.config.load().startup.autostart)
            self.assertTrue(controller.dirty)
            self.assertIn("simulated config write failure", controller.lastError)

    def test_failed_atomic_apply_keeps_the_draft_and_does_not_write(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = self._controller(repositories)
            config_path = Path(directory) / "config.json"
            before = config_path.read_bytes() if config_path.exists() else None

            controller.selectWorkflow("rewrite")
            controller.setRouteCustomEndpoint("https://proxy.example:0/v1")

            self.assertFalse(controller.save())
            self.assertTrue(controller.dirty)
            self.assertIn("port", controller.lastError.lower())
            self.assertEqual(
                config_path.read_bytes() if config_path.exists() else None,
                before,
            )
            self.assertEqual(
                controller.routeCustomEndpoint,
                "https://proxy.example:0/v1",
            )

    def test_load_replaces_the_draft_without_a_ui_or_legacy_import(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = self._controller(repositories)
            controller.setLanguage("es")
            self.assertTrue(controller.dirty)

            repositories.config.save(AppConfig.from_mapping({"ui_language": "ru"}))
            self.assertTrue(controller.load())

            self.assertEqual(controller.language, "ru")
            self.assertFalse(controller.dirty)

    def test_qml_properties_are_registered_and_module_does_not_import_app(self):
        property_names = {
            controller_property.name()
            for controller_property in (
                QmlSettingsController.staticMetaObject.property(index)
                for index in range(
                    QmlSettingsController.staticMetaObject.propertyCount()
                )
            )
        }
        self.assertTrue(
            {
                "mode",
                "language",
                "selectedScope",
                "routeProviderId",
                "routeModelId",
                "routePrompt",
                "routeCustomEndpoint",
                "routeEnabled",
                "selectedMicrophoneId",
                "microphoneDevices",
                "microphoneInventory",
                "microphoneStatus",
                "microphoneTestStatus",
                "microphoneTestBusy",
                "recordingControls",
                "dirty",
                "lastError",
            }.issubset(property_names)
        )

        source = SETTINGS.read_text(encoding="utf-8")
        tree = ast.parse(source)
        top_level_imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level_imports.update(
                    alias.name.split(".")[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level_imports.add(node.module.split(".")[0])
        self.assertNotIn("app", top_level_imports)
        self.assertNotIn("customtkinter", top_level_imports)
        self.assertNotIn("tkinter", top_level_imports)

        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "from clarify.desktop.qml_settings import "
                    "QmlSettingsController; "
                    "print('app' in sys.modules)"
                ),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "False")

    def _wait_models(self, controller):
        for _ in range(200):
            self.qt_app.processEvents()
            if controller.routeModelStatus != "loading":
                return
            time.sleep(0.01)
        self.fail("Model discovery did not finish")

    def test_model_discovery_filters_task_and_preserves_saved_custom_model(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            repositories.config.save(
                AppConfig.from_mapping({"openai_api_key": "test-key"})
            )
            controller = self._controller(repositories)
            try:
                controller.setRouteProviderId("openai")
                controller.setRouteModelId("custom-saved")
                before = repositories.config.load()
                with patch.object(
                    qml_settings.PROVIDER_REGISTRY,
                    "discover_models",
                    return_value=ModelCatalog(
                        audio_models=("whisper-1", "whisper-1"),
                        text_models=("text-model",),
                    ),
                ) as discover:
                    self.assertTrue(controller.loadRouteModels())
                    self._wait_models(controller)
                    self.assertEqual(
                        controller.routeModelOptions,
                        [{"id": "whisper-1", "label": "whisper-1"}],
                    )
                    self.assertEqual(controller.routeModelId, "custom-saved")
                    controller.selectWorkflow("rewrite")
                    controller.setRouteProviderId("openai")
                    self.assertFalse(controller.loadRouteModels())
                    self.assertEqual(
                        controller.routeModelOptions[0]["id"], "text-model"
                    )
                    self.assertEqual(discover.call_count, 1)
                self.assertEqual(repositories.config.load(), before)
            finally:
                controller.shutdown()

    def test_model_discovery_handles_missing_credentials_empty_and_failure(self):
        with TemporaryDirectory() as directory:
            repositories = _repositories(directory)
            controller = self._controller(repositories)
            try:
                controller.setRouteProviderId("openai")
                self.assertEqual(controller.routeModelStatus, "not_configured")
                self.assertFalse(controller.refreshRouteModels())
                repositories.config.save(
                    AppConfig.from_mapping({"openai_api_key": "test-key"})
                )
                controller.load()
                controller.setRouteProviderId("openai")
                with patch.object(
                    qml_settings.PROVIDER_REGISTRY,
                    "discover_models",
                    return_value=ModelCatalog(),
                ):
                    controller.refreshRouteModels()
                    self._wait_models(controller)
                    self.assertEqual(controller.routeModelStatus, "empty")
                saved_model = controller.routeModelId
                with patch.object(
                    qml_settings.PROVIDER_REGISTRY,
                    "discover_models",
                    side_effect=RuntimeError("secret"),
                ):
                    controller.refreshRouteModels()
                    self._wait_models(controller)
                    self.assertEqual(controller.routeModelStatus, "error")
                    self.assertEqual(controller.routeModelId, saved_model)
                    self.assertNotIn("secret", controller.lastError)
            finally:
                controller.shutdown()

    def test_model_discovery_ignores_stale_connection_results(self):
        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))
            try:
                controller._model_generation = 2
                controller._finish_model_discovery(
                    1,
                    ("openai", "https://old", "old-key"),
                    ModelCatalog(audio_models=("stale",)),
                )
                self.assertEqual(controller._model_catalogs, {})
                controller.setRouteProviderId("openai")
                controller.setRouteModelId("old-provider-model")
                controller.setRouteCustomEndpoint("https://example.com/v1")
                controller.setRouteProviderId("groq")
                self.assertEqual(controller.routeCustomEndpoint, "")
                self.assertNotEqual(controller.routeModelId, "old-provider-model")
            finally:
                controller.shutdown()

    def test_local_model_selection_is_explicit_and_preserves_privacy(self):
        from local_asr_product import LocalASRProductState

        with TemporaryDirectory() as directory:
            controller = self._controller(_repositories(directory))
            try:
                controller._apply_local_state(LocalASRProductState("missing"))
                self.assertFalse(controller.useLocalAsr())
                controller._apply_local_state(
                    LocalASRProductState("installing", "download:model", 50, 100)
                )
                self.assertTrue(controller.localAsrBusy)
                self.assertIn("4 of 5", controller.localAsrStep)
                self.assertEqual(controller.localAsrProgress, 0.5)
                controller._apply_local_state(LocalASRProductState("installed"))
                self.assertFalse(controller.localAsrBusy)
                self.assertTrue(controller.useLocalAsr())
                self.assertEqual(controller.routeProviderId, "local_asr")
                self.assertEqual(controller.routeModelId, "ggml-small")
                self.assertFalse(controller.localAsrCloudRefinement)
                self.assertTrue(controller.dirty)
            finally:
                controller.shutdown()


if __name__ == "__main__":
    unittest.main()
