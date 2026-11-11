"""Persistent desktop transport preserves the engine and Settings contracts."""

import unittest
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QEventLoop, QObject, Property, QTimer, Signal
from PySide6.QtWidgets import QApplication

from clarify.desktop.qml_bridge import QmlWorkflowBridge
from clarify.desktop.qml_electron import ElectronDesktopProcess
from clarify.desktop.qml_settings import QmlSettingsController
from local_asr_product import LocalASRProductState
from tests.support.settings import _repositories
from workflows import WorkflowPhase, WorkflowState


class _Status(QObject):
    changed = Signal()

    @Property(float, notify=changed)
    def audioLevel(self):
        return 0.25

    @Property(bool, notify=changed)
    def recordingReady(self):
        return True

    @Property(str, notify=changed)
    def targetIcon(self):
        return ""


class ElectronDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.settings = QmlSettingsController(
            _repositories(self.directory.name),
            local_product=Mock(state=LocalASRProductState("missing"), busy=False),
        )
        self.bridge = QmlWorkflowBridge(
            SimpleNamespace(state=WorkflowState(), subscribe=lambda callback: None)
        )
        self.status = _Status()
        self.host = ElectronDesktopProcess(
            self.settings, self.bridge, self.status, Mock(), Mock()
        )
        self.messages = []
        self.host._send = self.messages.append

    def tearDown(self):
        self.host.shutdown()
        self.host.flush_timer.stop()
        self.settings.shutdown()
        self.directory.cleanup()

    def test_only_entering_picker_grants_foreground_permission_to_the_child(self):
        self.host._ready = True
        with patch.object(self.host, "_allow_picker_activation") as allow:
            self.host._flush()
            self.bridge._on_workflow_state(WorkflowState(phase=WorkflowPhase.RECORDING))
            self.host._flush()
            allow.assert_not_called()
            self.bridge._on_workflow_state(
                WorkflowState(phase=WorkflowPhase.TRANSLATION_PICKER)
            )
            self.host._flush()
            allow.assert_called_once()
            self.status.changed.emit()
            self.host._flush()
            allow.assert_called_once()

    @unittest.skipUnless(sys.platform == "win32", "Windows foreground API")
    def test_native_activation_grant_is_limited_to_our_child(self):
        with (
            patch.object(self.host.process, "processId", return_value=1234),
            patch("clarify.desktop.qml_electron.ctypes.WinDLL") as library,
        ):
            library.return_value.AllowSetForegroundWindow.return_value = 1
            self.assertTrue(self.host._allow_picker_activation())
            library.return_value.AllowSetForegroundWindow.assert_called_once_with(1234)

    def test_workflow_rpc_rejects_reflection_and_wrong_argument_types(self):
        for method, args in (
            ("deleteLater", []),
            ("dismissFeedback", [True]),
            ("chooseTranslation", [12]),
            ("setLanguage", ["en", "pt"]),
        ):
            reply = self.host.dispatch_workflow(
                {"id": 1, "method": method, "args": args}
            )
            self.assertIn("error", reply)
        reply = self.host.dispatch_workflow({"id": 2, "method": "snapshot", "args": []})
        self.assertEqual(reply["result"]["surface"], "idle")
        self.assertEqual(reply["result"]["level"], 0.25)
        self.assertNotIn("settings", reply["result"])
        self.assertEqual(reply["result"]["completionId"], "")
        self.assertEqual(reply["result"]["recordingShortcut"], "Alt+L")
        self.bridge._on_workflow_state(
            WorkflowState(
                phase=WorkflowPhase.COMPLETED,
                operation_id=9,
                kind="rewrite",
                writing_style_requested="formal",
            )
        )
        self.assertEqual(self.host.workflow_snapshot()["completionId"], "workflow:9")
        self.assertTrue(
            self.settings.setHotkey(
                "recording_hotkey", {"modifiers": ["ctrl", "shift"], "key": "L"}
            )
        )
        self.assertEqual(
            self.host.workflow_snapshot()["recordingShortcut"], "Ctrl+Shift+L"
        )
        self.assertEqual(
            reply["result"]["dictationWritingStyle"],
            self.settings.dictationWritingStyle,
        )
        self.assertEqual(
            reply["result"]["writingStyleRefinementAllowed"],
            self.settings.writingStyleRefinementAllowed,
        )
        self.host._mark_settings({"dictationWritingStyle"})
        self.assertIsNone(self.host._pill_settings)
        self.assertTrue(self.host._workflow_dirty)
        self.host.toggle_pill()
        self.host.toggle_pill()
        self.assertEqual(self.messages[-2:], [{"window": "pill-toggle"}] * 2)
        self.messages.clear()
        self.host._receive({"event": "ready"})
        self.assertFalse(
            any(
                message.get("window", "").startswith("pill-")
                for message in self.messages
            )
        )

    def test_meter_push_does_not_read_or_serialize_settings_library(self):
        self.host._ready = True
        self.host._visible = True
        self.host._workflow_dirty = False
        with patch.object(
            self.settings, "library_snapshot", side_effect=AssertionError
        ):
            self.status.changed.emit()
            self.host._flush()
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.messages[0]["event"], "workflow")
        self.assertEqual(self.messages[0]["state"]["level"], 0.25)

    def test_continuous_meter_notifications_publish_before_producer_stops(self):
        self.host._ready = True
        self.host._workflow_dirty = False
        loop = QEventLoop()
        producer = QTimer()
        producer.setInterval(0)
        producer.timeout.connect(self.status.changed.emit)
        delivered_while_active = []

        def receive(message):
            self.messages.append(message)
            delivered_while_active.append(producer.isActive())
            loop.quit()

        self.host._send = receive
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        producer.start()
        deadline.start(2000)
        try:
            loop.exec()
        finally:
            producer.stop()
            deadline.stop()
        self.assertEqual(delivered_while_active, [True])

    def test_preference_push_reads_only_notified_fields(self):
        self.host._ready = True
        self.host._visible = True
        self.host._workflow_dirty = False
        self.host._last_settings = {
            "automaticUpdates": not self.settings.automaticUpdates
        }
        with patch.object(
            self.settings, "library_snapshot", side_effect=AssertionError
        ):
            self.host._mark_settings({"automaticUpdates"})
            self.host._flush()
        self.assertEqual(
            self.messages,
            [
                {
                    "event": "settings",
                    "state": {
                        "automaticUpdates": self.settings.automaticUpdates,
                    },
                }
            ],
        )

    def test_practice_pushes_native_commands_readiness_and_async_result(self):
        from tests.support.practice_settings_fixture import bind_practice

        practice = bind_practice(self.settings, self.app)
        self.settings.completeOnboarding("byok", "gsk_test_only")
        practice.command("close")
        self.settings._microphone_inventory_generation += 1
        self.settings._microphone_inventory_busy = False
        self.host._ready = self.host._visible = True
        self.host._workflow_dirty = False
        self.host._publish_settings(full=True)
        self.messages.clear()

        def pushed():
            self.host._flush()
            states = [
                m["state"]["practiceState"]
                for m in self.messages
                if m.get("event") == "settings" and "practiceState" in m["state"]
            ]
            self.assertTrue(states, "Native practice must push without a renderer RPC")
            return states[-1]

        practice.command("open")
        self.assertTrue(pushed()["open"])
        self.settings._microphone_inventory_busy = True
        self.settings.microphoneChanged.emit()
        self.assertEqual(pushed()["blocked"], "practice_busy")
        self.settings._microphone_inventory_busy = False
        self.settings.microphoneChanged.emit()
        self.assertEqual(pushed()["blocked"], "")
        readiness = practice.readiness
        other_settings_busy = False
        practice.readiness = lambda: (
            "practice_busy" if other_settings_busy else readiness()
        )
        for signal in (
            self.settings.modelCatalogChanged,
            self.settings.chatgptStateChanged,
        ):
            other_settings_busy = True
            signal.emit()
            self.assertEqual(pushed()["blocked"], "practice_busy")
            other_settings_busy = False
            signal.emit()
            self.assertEqual(pushed()["blocked"], "")
        practice.command("start")
        self.assertEqual(pushed()["phase"], "recording")
        loop, deadline = QEventLoop(), QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        unsubscribe = practice.subscribe(
            lambda: loop.quit() if practice.snapshot()["phase"] == "completed" else None
        )
        try:
            practice.command("stop")
            deadline.start(2000)
            loop.exec()
        finally:
            deadline.stop()
            unsubscribe()
        self.assertEqual(pushed()["text"], "Hoje vou escrever com o Clarify.")

    def test_completion_push_restores_value_exposed_by_intermediate_reply(self):
        self.host._ready = True
        self.host._visible = True
        self.host._workflow_dirty = False
        self.host._publish_settings(full=True)
        self.messages.clear()
        self.settings._microphone_test_level = 0.75
        self.host._receive(
            {"id": 3, "channel": "settings", "method": "snapshot", "args": []}
        )
        self.assertEqual(self.messages[-1]["result"]["microphoneTestLevel"], 0.75)
        self.settings._microphone_test_level = 0.0
        self.host._mark_settings({"microphoneTestLevel"})
        self.host._flush()
        self.assertEqual(
            self.messages[-1],
            {"event": "settings", "state": {"microphoneTestLevel": 0.0}},
        )

    def test_context_notification_replaces_library_rows_atomically(self):
        self.host._ready = True
        self.host._visible = True
        self.host._workflow_dirty = False
        self.host._last_settings = {
            "snippetContext": "old-owner",
            "dictionaryContext": "old-owner",
            "snippets": [{"trigger": "old phrase", "replacement": "old text"}],
            "dictionaryEntries": [{"term": "old term"}],
        }
        library = {
            "snippetContext": "new-owner",
            "dictionaryContext": "new-owner",
            "snippets": [],
            "dictionaryEntries": [],
        }
        with patch.object(self.settings, "library_snapshot", return_value=library):
            self.host._mark_settings({"snippetContext", "dictionaryContext"})
            self.host._flush()
        self.assertEqual(self.messages, [{"event": "settings", "state": library}])

    def test_hidden_unaccepted_drafts_still_block_update(self):
        self.host._visible = True
        self.host._accepted_close = False
        self.host.hide()
        self.assertTrue(self.host.blocks_update())
        self.host._receive({"event": "settings-hidden"})
        self.assertFalse(self.host.blocks_update())
        self.assertEqual(self.bridge.surface, "idle")
        self.host._visible = True
        self.host._accepted_close = False
        self.assertTrue(self.host.blocks_update())
        self.assertTrue(self.host._visible)
        self.messages.clear()
        self.host._receive({"event": "settings-hidden"})
        self.assertFalse(
            any(message.get("window") == "settings-hide" for message in self.messages)
        )

    def test_history_stamp_refresh_does_not_read_full_settings_library(self):
        self.host._ready = True
        self.host._visible = True
        self.host._workflow_dirty = False
        self.host._last_settings = {
            "historyState": {"context": "owner", "revision": "old"}
        }
        revision = {"context": "owner", "revision": "new"}
        view = SimpleNamespace(snapshot=lambda: revision)
        with (
            patch.object(self.settings, "_history_view", view),
            patch.object(self.settings, "library_snapshot", side_effect=AssertionError),
        ):
            self.host._check_history()
            self.host._flush()
        self.assertEqual(
            self.messages, [{"event": "settings", "state": {"historyState": revision}}]
        )

    def test_settings_channel_reuses_strict_existing_allowlist(self):
        self.host._receive(
            {"id": 7, "channel": "settings", "method": "repositories", "args": []}
        )
        self.assertIn("error", self.messages[-1])
        self.host._receive(
            {"id": 8, "channel": "untrusted", "method": "snapshot", "args": []}
        )
        self.assertEqual(self.messages[-1]["error"], "Unsupported desktop channel")


if __name__ == "__main__":
    unittest.main()
