"""Check real capsule style labels with synthetic states and no audio capture."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.qml_pill_transition_smoke import ROOT, Service, Status
from clarify.desktop.qml_bridge import QmlWorkflowBridge
from workflows import WorkflowPhase


def main():
    QQuickStyle.setStyle("Basic")
    app = QApplication([])
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    service = Service()
    bridge = QmlWorkflowBridge(service)
    status = Status()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("workflow", bridge)
    engine.rootContext().setContextProperty("pillStatus", status)
    engine.load(QUrl.fromLocalFile(str(ROOT / "clarify/desktop/qml/StatusPill.qml")))
    assert len(engine.rootObjects()) == 1
    pill = engine.rootObjects()[0]
    label = pill.findChild(QObject, "writingStyleCaption")
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    cases = (
        (WorkflowPhase.RECORDING, "Selected: Informal", {}),
        (
            WorkflowPhase.COMPLETED,
            "Applied: Informal",
            {"writing_style_applied": "informal", "writing_style_status": "applied"},
        ),
        (
            WorkflowPhase.COMPLETED,
            "Style not applied",
            {"writing_style_status": "refinement_not_allowed"},
        ),
    )
    with patch("shared.localization.device_language", return_value="en"):
        for operation, (phase, expected, fields) in enumerate(cases, 1):
            service.publish(
                phase,
                operation_id=operation,
                kind="dictation",
                writing_style_requested="informal",
                result_text="Synthetic 42.",
                **fields,
            )
            QTest.qWait(400)
            assert label.property("text") == expected
            assert pill.isVisible() and label.property("visible")
            assert label.property("implicitWidth") <= label.property("width")
            if output:
                output.mkdir(parents=True, exist_ok=True)
                assert pill.grabWindow().save(str(output / f"style-{operation}.png"))
        QTest.qWait(2300)
        assert not pill.isVisible()


if __name__ == "__main__":
    main()
