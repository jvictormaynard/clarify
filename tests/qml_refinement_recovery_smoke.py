"""Render the actual status pill in an isolated Qt process, without microphone."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, Property, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from spikes.pyside6.qml_bridge import QmlWorkflowBridge  # noqa: E402
from workflows import WorkflowKind, WorkflowPhase, WorkflowState  # noqa: E402


class Service:
    state = WorkflowState()

    def subscribe(self, callback):
        self.callback = callback

    def publish(self, state):
        self.state = state
        self.callback(state)


class PillStatus(QObject):
    @Property(str, constant=True)
    def targetIcon(self):
        return ""

    @Property(float, constant=True)
    def audioLevel(self):
        return 0.0


app = QGuiApplication([])
service = Service()
bridge = QmlWorkflowBridge(service)
status = PillStatus()
engine = QQmlApplicationEngine()
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(str(error) for error in errors))
engine.rootContext().setContextProperty("workflow", bridge)
engine.rootContext().setContextProperty("pillStatus", status)
engine.load(QUrl.fromLocalFile(str(ROOT / "spikes/pyside6/qml/StatusPill.qml")))
assert engine.rootObjects(), warnings
pill = engine.rootObjects()[0]
label = pill.findChild(QObject, "refinementWarningLabel")
timer = pill.findChild(QObject, "statusDismissTimer")
service.publish(
    WorkflowState(
        phase=WorkflowPhase.COMPLETED,
        operation_id=1,
        kind=WorkflowKind.DICTATION,
        result_text="Original",
        status_key="refinement_failed",
    )
)
app.processEvents()
assert pill.isVisible()
assert pill.flags() & Qt.WindowDoesNotAcceptFocus
# The offscreen platform does not implement native focus exclusion. Check the
# requested window flag here; real Windows focus acceptance is a separate gate.
assert label.property("visible")
assert label.property("text") == "Refinement failed. Original text is available."
assert label.property("implicitHeight") <= pill.property("designHeight")
assert timer.property("interval") == 5000
service.publish(WorkflowState(phase=WorkflowPhase.RECORDING, operation_id=2))
app.processEvents()
assert not label.property("visible")
assert pill.property("designWidth") == 142
service.publish(
    WorkflowState(phase=WorkflowPhase.COMPLETED, operation_id=2, result_text="OK")
)
app.processEvents()
assert timer.property("interval") == 850
assert not label.property("visible")
assert not warnings, warnings
pill.close()
engine.deleteLater()
app.processEvents()
print("PASS: refinement recovery pill")
