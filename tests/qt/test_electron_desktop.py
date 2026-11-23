"""Persistent desktop transport preserves the engine and Settings contracts."""

import unittest
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QEventLoop, QObject, Property, QProcess, QTimer, Signal
from PySide6.QtWidgets import QApplication

from clarify.desktop.qml_bridge import QmlWorkflowBridge
from clarify.desktop.qml_electron import ElectronDesktopProcess, ElectronQtShell
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

    def test_leaving_settings_hides_it_and_closes_activity_without_accepting_drafts(
        self,
    ):
        with (
            patch.object(self.host, "start", return_value=True),
            patch.object(self.host, "_close_settings_activity") as cleanup,
        ):
            self.bridge.openSettings()
            self.host.show()
            self.assertTrue(self.host._visible)
            self.bridge.openFiles()
            self.assertFalse(self.host._visible)
            self.assertTrue(self.host.blocks_update())
            self.assertIn({"window": "settings-hide"}, self.messages)
            cleanup.assert_called_once()
            self.bridge.surfaceChanged.emit()
            cleanup.assert_called_once()

    def test_hidden_settings_receives_playback_stop_without_its_pending_state(self):
        self.host._ready = True
        self.host._visible = False
        self.settings._playback_stop_request = "old-recording"
        self.host._mark_settings({"historyState"})
        self.settings._publishPlaybackStop()
        self.host._flush()
        self.assertEqual(
            self.messages[-1],
            {"event": "settings-audio-stop", "lease": "old-recording"},
        )
        self.assertIn("historyState", self.host._settings_dirty)
        self.host._flush()
        self.assertEqual(
            sum(
                message.get("event") == "settings-audio-stop"
                for message in self.messages
            ),
            1,
        )

    def test_renderer_failures_restart_with_a_bounded_budget_and_fresh_snapshots(self):
        with (
            patch.object(self.host.process, "state", return_value=QProcess.NotRunning),
            patch.object(self.host.process, "start") as start,
            patch(
                "clarify.desktop.qml_electron.desktop_executable",
                return_value=__import__("pathlib").Path("/test/desktop"),
            ),
        ):
            self.host._visible = True
            self.host._last_settings = {"dirty": False}
            self.host._last_workflow = {"surface": "idle"}
            for expected in range(1, 4):
                self.host._failed(None)
                self.assertEqual(self.host._restart_attempts, expected)
                self.assertTrue(self.host.restart_timer.isActive())
                self.host._finished(1, None)
                self.assertEqual(self.host._restart_attempts, expected)
                self.host.restart_timer.stop()
                self.host._restart()
                self.assertIsNone(self.host._last_settings)
                self.assertIsNone(self.host._last_workflow)
                self.host._receive({"event": "ready"})
                self.assertTrue(self.host._ready)
                self.assertTrue(self.host._visible)
            self.host._failed(None)
            self.assertTrue(self.host.failed)
            self.assertFalse(self.host.restart_timer.isActive())
            self.host._unavailable.assert_called_once()
            self.assertEqual(start.call_count, 3)
            self.assertTrue(self.host.retry())
            self.assertEqual(self.host._restart_attempts, 0)

    def test_renderer_that_does_not_exit_cannot_restart_forever(self):
        with (
            patch.object(self.host.process, "state", return_value=QProcess.Running),
            patch.object(self.host.process, "kill"),
        ):
            self.host._failed(None)
            for _ in range(20):
                self.host.restart_timer.stop()
                self.host._restart()
            self.assertTrue(self.host.failed)
            self.assertFalse(self.host.restart_timer.isActive())
            self.host._unavailable.assert_called_once()

    def test_clean_exit_recovers_and_shutdown_cannot_restart_the_renderer(self):
        with patch.object(self.host.process, "state", return_value=QProcess.NotRunning):
            self.host._finished(0, None)
            self.assertTrue(self.host.restart_timer.isActive())
            self.assertTrue(self.host._recovering)
            self.host._receive({"event": "ready"})
            self.assertFalse(self.host._ready)
            self.host.shutdown()
            self.host._failed(None)
            self.host._finished(0, None)
            self.assertFalse(self.host.restart_timer.isActive())
            self.host._unavailable.assert_not_called()

    def test_only_entering_picker_grants_foreground_permission_to_the_child(self):
        self.host._ready = True
        with patch.object(self.host, "_allow_electron_activation") as allow:
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

    def test_windows_dock_opens_active_meeting_without_showing_settings(self):
        self.host._ready = True
        self.host.meetings = Mock(state=Mock(return_value={"active": {"id": "note"}}))
        with (
            patch("clarify.desktop.qml_electron.sys.platform", "win32"),
            patch.object(self.host, "_allow_electron_activation") as allow,
            patch.object(self.bridge, "openSettings") as open_settings,
        ):
            self.host._receive({"event": "meetings-open"})
            allow.assert_called_once()
            open_settings.assert_not_called()
            self.assertEqual(self.messages[-1], {"window": "meetings-show"})
            self.host.meetings.state.return_value = {"active": None}
            self.host._receive({"event": "meetings-open"})
            open_settings.assert_called_once_with()

    def test_quit_waits_for_light_meeting_to_save(self):
        self.host.meetings = Mock(
            drain_light_capture_for_quit=Mock(side_effect=[True, False])
        )
        with (
            patch("clarify.desktop.qml_electron.sys.platform", "win32"),
            patch("clarify.desktop.qml_electron.QTimer.singleShot") as schedule,
        ):
            self.host._receive({"event": "quit"})
            wait, retry = schedule.call_args.args
            self.assertEqual(wait, 250)
            self.host._receive({"event": "quit"})
            schedule.assert_called_once()
            retry()
            schedule.assert_called_with(0, self.host.application.quit)

    @unittest.skipUnless(sys.platform == "win32", "Windows foreground API")
    def test_native_activation_grant_is_limited_to_our_child(self):
        with (
            patch.object(self.host.process, "processId", return_value=1234),
            patch("clarify.desktop.qml_electron.ctypes.WinDLL") as library,
        ):
            library.return_value.AllowSetForegroundWindow.return_value = 1
            self.assertTrue(self.host._allow_electron_activation())
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

    def test_second_launch_opens_workspace_without_interrupting_active_work(self):
        shell = ElectronQtShell(Mock(), desktop=self.host)
        with (
            patch.object(self.bridge, "openSettings") as open_settings,
            patch.object(self.host, "set_pill_visible") as show_pill,
        ):
            shell.activationRequested.emit()
            open_settings.assert_called_once()
            open_settings.reset_mock()
            self.bridge._on_workflow_state(WorkflowState(phase=WorkflowPhase.RECORDING))
            shell.activationRequested.emit()
            open_settings.assert_not_called()
            show_pill.assert_called_with(True)

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
            self.host._refresh_visible_settings()
            self.host._flush()
        self.assertEqual(
            self.messages, [{"event": "settings", "state": {"historyState": revision}}]
        )

    def test_practice_publishes_macos_grants_without_window_focus(self):
        self.host._ready = True
        self.host._visible = True
        self.host._workflow_dirty = False
        self.host._last_settings = {
            "historyState": self.settings.historyState,
            "dictationPermissions": {
                "accessibility": "settings",
                "microphone": "request",
            },
            "inputMonitoringStatus": "settings",
        }
        self.settings._practice = Mock(snapshot=lambda: {"open": True})
        self.settings._input_monitoring_status = "settings"
        with (
            patch.object(sys, "platform", "darwin"),
            patch(
                "clarify.desktop.macos_clipboard.accessibility_allowed",
                return_value=True,
            ),
            patch(
                "clarify.desktop.macos_microphone_permission.microphone_permission_status",
                return_value="allowed",
            ),
            patch(
                "clarify.desktop.macos_keyboard.input_monitoring_allowed",
                return_value=True,
            ),
        ):
            self.host._refresh_visible_settings()
            self.host._flush()
            updates = self.messages[-1]["state"]
            self.assertEqual(
                updates["dictationPermissions"],
                {"accessibility": "allowed", "microphone": "allowed"},
            )
            self.assertEqual(updates["inputMonitoringStatus"], "allowed")
            self.messages.clear()
            self.host._refresh_visible_settings()
            self.host._flush()
            self.assertEqual(self.messages, [])

    def test_settings_reply_cannot_consume_a_macos_grant_before_the_refresh(self):
        self.host._visible = True
        self.host._last_settings = {
            "dictationPermissions": {
                "accessibility": "settings",
                "microphone": "allowed",
            },
            "inputMonitoringStatus": "settings",
        }
        grant = {"accessibility": "allowed", "microphone": "allowed"}
        result = {"dictationPermissions": grant, "inputMonitoringStatus": "settings"}
        with (
            patch.object(sys, "platform", "darwin"),
            patch.object(
                self.host.protocol, "dispatch", return_value={"id": 1, "result": result}
            ),
        ):
            self.host._receive(
                {
                    "id": 1,
                    "channel": "settings",
                    "method": "inputMonitoringCommand",
                    "args": ["check"],
                }
            )
        self.assertEqual(
            self.messages[-1],
            {"event": "settings", "state": {"dictationPermissions": grant}},
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


class DesktopBindingTests(unittest.TestCase):
    def test_pipe_finds_controller_bound_after_electron_construction(self):
        from clarify.desktop.qml_electron import ElectronDesktopProcess

        sent = []
        remote = SimpleNamespace(
            drain=lambda: iter([{"event": "computer-webrtc-config", "config": None}])
        )
        desktop = SimpleNamespace(
            _webrtc=None,
            settings=SimpleNamespace(_computer=SimpleNamespace(webrtc=remote)),
            _ready=True,
            _send=sent.append,
        )
        ElectronDesktopProcess._flush_webrtc(desktop)
        self.assertIs(desktop._webrtc, remote)
        self.assertEqual(sent[0]["event"], "computer-webrtc-config")
