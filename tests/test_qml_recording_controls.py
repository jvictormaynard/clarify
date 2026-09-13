"""Recording input ownership and delayed shortcut release regression tests."""

import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlEngine, QQmlComponent
from spikes.pyside6.qml_bridge import QmlWorkflowBridge
from spikes.pyside6.qt_shell import WindowsGlobalHotkeyBackend
from workflows import (
    CancelDictation,
    WorkflowState,
    WorkflowPhase,
    StartDictation,
    StopDictation,
)


class Service:
    def __init__(self):
        self.state = WorkflowState()
        self.commands = []

    def subscribe(self, listener):
        self.listener = listener

    def publish(self, phase):
        self.state = WorkflowState(phase=phase)
        self.listener(self.state)

    def dispatch(self, command):
        self.commands.append(command)


class RecordingControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = Service()
        self.queue = []
        self.bridge = QmlWorkflowBridge(self.service, dispatch_runner=self.queue.append)

    def test_reopening_toolbar_leaves_settings_placeholder(self):
        source = (
            Path(__file__).resolve().parents[1] / "spikes/pyside6/qml/Main.qml"
        ).read_text(encoding="utf-8")
        start = source.index("    onPresentationVisibleChanged:")
        end = source.index("    visible:", start)
        handler = source[start:end]
        engine = QQmlEngine()
        engine.rootContext().setContextProperty("workflow", self.bridge)
        component = QQmlComponent(engine)
        component.setData(
            (
                "import QtQml\nQtObject { property bool presentationVisible: false\n"
                + handler
                + "}"
            ).encode(),
            "",
        )
        item = component.create()
        self.assertIsNotNone(item, component.errors())
        self.bridge.openSettings()
        self.assertEqual(self.bridge.surface, "settings")
        item.setProperty("presentationVisible", True)
        self.assertEqual(self.bridge.surface, "idle")
        item.deleteLater()

    def test_mouse_start_has_stop_and_release_does_not_stop_it(self):
        self.bridge.startRecordingFromButton()
        self.queue.pop(0)()
        self.assertIsInstance(self.service.commands[-1], StartDictation)
        self.service.publish(WorkflowPhase.RECORDING)
        self.assertTrue(self.bridge.showRecordingStop)
        self.bridge.handleHotkey("recording_hold_release")
        self.assertEqual(self.queue, [])
        self.bridge.stopRecording()
        self.bridge.stopRecording()
        self.assertEqual(len(self.queue), 1)
        self.queue.pop(0)()
        self.assertIsInstance(self.service.commands[-1], StopDictation)

    def test_release_before_recording_notification_stops_once(self):
        self.bridge.handleHotkey("recording_hold_press")
        self.bridge.handleHotkey("recording_hold_press")
        self.assertEqual(len(self.queue), 1)
        self.bridge.handleHotkey("recording_hold_release")
        self.queue.pop(0)()
        self.service.publish(WorkflowPhase.RECORDING)
        self.assertFalse(self.bridge.showRecordingStop)
        self.assertEqual(len(self.queue), 1)
        self.queue.pop(0)()
        self.assertIsInstance(self.service.commands[-1], StopDictation)

    def test_cancel_invalidates_hold_release(self):
        self.bridge.handleHotkey("recording_hold_press")
        self.queue.pop(0)()
        self.service.publish(WorkflowPhase.RECORDING)
        self.bridge.cancelRecording()
        self.queue.clear()
        self.service.publish(WorkflowPhase.READY)
        self.bridge.startRecordingFromButton()
        self.queue.pop(0)()
        self.service.publish(WorkflowPhase.RECORDING)
        self.bridge.handleHotkey("recording_hold_release")
        self.assertEqual(self.queue, [])

    def test_native_modifier_release_emits_one_release(self):
        backend = WindowsGlobalHotkeyBackend(self.app)
        backend._user32 = object()
        events = []
        backend.triggered.connect(events.append)
        with patch(
            "spikes.pyside6.qt_shell.physical_key_down",
            side_effect=lambda api, key: key != 0x1B,
        ):
            backend._begin_hold((65, 18))
            backend._begin_hold((65, 18))
        with patch(
            "spikes.pyside6.qt_shell.physical_key_down",
            side_effect=[False, True, False],
        ):
            backend._check_hold_release()
        backend._check_hold_release()
        self.assertEqual(events, ["recording_hold_press", "recording_hold_release"])
        self.assertFalse(backend._release_timer.isActive())

    def test_escape_with_held_modifiers_cancels_once_before_release(self):
        backend = WindowsGlobalHotkeyBackend(self.app)
        backend._user32 = object()
        events = []
        backend.triggered.connect(events.append)
        with patch(
            "spikes.pyside6.qt_shell.physical_key_down",
            side_effect=lambda api, key: key != 0x1B,
        ):
            backend._begin_hold((65, 18))
        with patch("spikes.pyside6.qt_shell.physical_key_down", return_value=True):
            backend._check_hold_release()
            backend._check_hold_release()
        with patch("spikes.pyside6.qt_shell.physical_key_down", return_value=False):
            backend._check_hold_release()
        self.assertEqual(
            events, ["recording_hold_press", "escape", "recording_hold_release"]
        )

    def test_escape_during_startup_wins_over_release(self):
        self.bridge.handleHotkey("recording_hold_press")
        self.bridge.handleHotkey("escape")
        self.bridge.handleHotkey("recording_hold_release")
        self.queue.pop(0)()
        self.service.publish(WorkflowPhase.RECORDING)
        self.queue.pop(0)()
        self.assertIsInstance(self.service.commands[-1], CancelDictation)
        self.assertFalse(
            any(isinstance(command, StopDictation) for command in self.service.commands)
        )
