"""The startup pill requires actual PCM data, including silent samples."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from spikes.pyside6.qml_runtime import QtRecorder
from spikes.pyside6.qml_status import QmlStatusPillController


class CaptureReadinessTests(unittest.TestCase):
    def test_live_process_and_headers_are_not_audio(self):
        recorder = QtRecorder(microphone_inventory_source=Mock())
        recorder.process = Mock()
        recorder.process.poll.return_value = None
        with TemporaryDirectory() as directory:
            path = Path(directory) / "capture.wav"
            recorder._capture_path = path
            self.assertFalse(recorder.capture_active)
            header = (
                b"RIFF"
                + b"\xff" * 4
                + b"WAVEfmt "
                + (16).to_bytes(4, "little")
                + b"\0" * 16
                + b"data"
                + b"\xff" * 4
            )
            path.write_bytes(header)
            self.assertFalse(recorder.capture_active)
            path.write_bytes(header + b"\0\0")
            self.assertTrue(recorder.capture_active)
            recorder.process.poll.return_value = 1
            self.assertFalse(recorder.capture_active)
            recorder.process = None
            self.assertFalse(recorder.capture_active)

    def test_meter_level_cannot_mark_capture_ready_and_stop_resets_readiness(self):
        app = QApplication.instance() or QApplication([])

        class Bridge(QObject):
            recordingChanged = Signal()
            targetExecutableChanged = Signal()
            recording = True
            targetExecutable = ""

        bridge = Bridge()
        recorder = SimpleNamespace(mic_level=1.0, capture_active=False)
        controller = QmlStatusPillController(
            bridge, recorder, fallback_icon=QIcon(), icon_resolver=lambda _: ""
        )
        controller._sample_level()
        self.assertFalse(controller.recordingReady)
        recorder.capture_active = True
        recorder.mic_level = 0.0
        controller._sample_level()
        self.assertTrue(controller.recordingReady)
        bridge.recording = False
        bridge.recordingChanged.emit()
        self.assertFalse(controller.recordingReady)
        recorder.capture_active = False
        bridge.recording = True
        bridge.recordingChanged.emit()
        controller._sample_level()
        self.assertFalse(controller.recordingReady)
        bridge.recording = False
        bridge.recordingChanged.emit()
        self.assertIsNotNone(app)
