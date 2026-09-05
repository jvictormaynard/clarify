"""Exercise the real capsule, its animation, expiry and retry without a provider."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, Property, QPointF, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from spikes.pyside6.qml_bridge import QmlWorkflowBridge
from workflows import RetryDictation, WorkflowPhase, WorkflowState


ROOT = Path(__file__).resolve().parents[1]


class Service:
    def __init__(self):
        self.state = WorkflowState()
        self.listeners = []
        self.commands = []

    def subscribe(self, listener):
        self.listeners.append(listener)

    def publish(self, phase, operation_id=1, **kwargs):
        self.state = WorkflowState(phase=phase, operation_id=operation_id, **kwargs)
        for listener in self.listeners:
            listener(self.state)

    def finish(self, _operation_id):
        self.publish(WorkflowPhase.READY)

    def dispatch(self, command):
        self.commands.append(command)
        self.publish(WorkflowPhase.PROCESSING)


class Status(QObject):
    audioLevel = Property(float, lambda self: 0.25, constant=True)
    targetIcon = Property(
        str,
        lambda self: QUrl.fromLocalFile(
            str(ROOT / "assets/branding/clarify.ico")
        ).toString(),
        constant=True,
    )


def main():
    QQuickStyle.setStyle("Basic")
    app = QApplication.instance() or QApplication([])
    # The Windows offscreen backend does not load system fonts automatically.
    for filename in ("segoeui.ttf", "seguisym.ttf"):
        font_path = Path("C:/Windows/Fonts") / filename
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families and filename == "segoeui.ttf":
                app.setFont(QFont(families[0], 10))
    messages = []
    qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    service = Service()
    bridge = QmlWorkflowBridge(service)
    bridge.setLanguage("pt")
    status = Status()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("workflow", bridge)
    engine.rootContext().setContextProperty("pillStatus", status)
    engine.load(QUrl.fromLocalFile(str(ROOT / "spikes/pyside6/qml/StatusPill.qml")))
    assert len(engine.rootObjects()) == 1, messages
    pill = engine.rootObjects()[0]
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if output:
        output.mkdir(parents=True, exist_ok=True)

    def shot(name):
        if output:
            assert pill.grabWindow().save(str(output / f"{name}.png"))

    def click(name):
        item = pill.findChild(QObject, name)
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        QTest.mouseClick(pill, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(350)

    service.publish(WorkflowPhase.PROCESSING)
    QTest.qWait(350)
    native_id = pill.winId()
    capsule = pill.findChild(QObject, "statusCapsule")
    height = pill.height()
    start_width = pill.width()
    center = pill.x() + pill.width() / 2
    shot("01-processing")
    service.publish(WorkflowPhase.FAILED, status_key="no_selection")
    QTest.qWait(75)
    midway = pill.width()
    label = pill.findChild(QObject, "pillFeedbackLabel")
    assert start_width < midway
    assert 0 < label.property("opacity") < 1
    shot("02-expanding")
    QTest.qWait(300)
    assert midway < pill.width()
    assert pill.height() == height
    assert abs(pill.x() + pill.width() / 2 - center) <= 1
    assert pill.winId() == native_id
    assert pill.findChild(QObject, "statusCapsule") is capsule
    assert pill.flags() & Qt.WindowDoesNotAcceptFocus
    assert label.property("text") == "Nenhum texto selecionado"
    assert label.property("truncated") is False
    shot("03-message")
    # A new operation replaces the message and invalidates its expiry timer.
    service.publish(WorkflowPhase.PROCESSING, operation_id=2)
    QTest.qWait(350)
    assert pill.width() == start_width
    assert pill.height() == height
    assert pill.winId() == native_id
    shot("04-processing-again")
    QTest.qWait(3000)
    assert service.state.phase is WorkflowPhase.PROCESSING
    service.publish(WorkflowPhase.FAILED, operation_id=3, status_key="no_selection")
    QTest.qWait(3500)
    assert service.state.phase is WorkflowPhase.READY
    assert not pill.isVisible()
    # Retained audio does not expire, and the inline retry remains clickable.
    service.publish(
        WorkflowPhase.FAILED,
        operation_id=4,
        status_key="transcription_network",
        can_retry=True,
    )
    QTest.qWait(3500)
    assert bridge.canRetryTranscription and pill.isVisible()
    assert pill.height() == height
    shot("05-inline-retry")
    click("retryTranscriptionButton")
    assert service.commands == [RetryDictation(4)]
    assert service.state.phase is WorkflowPhase.PROCESSING
    service.publish(WorkflowPhase.COMPLETED, result_text="fixture")
    QTest.qWait(350)
    assert not pill.isVisible()
    errors = [
        m
        for m in messages
        if any(
            word in m
            for word in (
                "Error",
                "Binding loop",
                "Unable to assign",
                "is not defined",
                "Cannot assign",
            )
        )
    ]
    assert not errors, errors
    print(
        "PASS: one native capsule, animated width and text fade, constant height, error expiry, inline retry, no success window"
    )
    engine.deleteLater()
    app.processEvents()
    qInstallMessageHandler(None)


if __name__ == "__main__":
    main()
