"""Check compact capsule geometry with synthetic styles and no audio capture."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.support.qml_pill_transition_smoke import ROOT, Service, Status
from clarify.desktop.qml_bridge import QmlWorkflowBridge
from workflows import WorkflowPhase


def main():
    QQuickStyle.setStyle("Basic")
    app = QApplication([])
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    symbol_font = Path("C:/Windows/Fonts/seguisym.ttf")
    if symbol_font.is_file():
        QFontDatabase.addApplicationFont(str(symbol_font))
    service = Service()
    bridge = QmlWorkflowBridge(service)
    status = Status()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("workflow", bridge)
    engine.rootContext().setContextProperty("pillStatus", status)
    engine.load(QUrl.fromLocalFile(str(ROOT / "clarify/desktop/qml/StatusPill.qml")))
    assert len(engine.rootObjects()) == 1
    pill = engine.rootObjects()[0]
    assert pill.findChild(QObject, "writingStyleCaption") is None
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    cases = (
        (WorkflowPhase.RECORDING, {}),
        (WorkflowPhase.RECORDING, {"writing_style_requested": None}),
        (WorkflowPhase.PROCESSING, {}),
        (
            WorkflowPhase.COMPLETED,
            {"writing_style_applied": "informal", "writing_style_status": "applied"},
        ),
        (
            WorkflowPhase.COMPLETED,
            {"writing_style_status": "refinement_not_allowed"},
        ),
    )
    with patch("shared.localization.device_language", return_value="en"):
        for operation, (phase, fields) in enumerate(cases, 1):
            service.publish(
                phase,
                operation_id=operation,
                kind="dictation",
                result_text="Synthetic 42.",
                **{"writing_style_requested": "informal", **fields},
            )
            QTest.qWait(400)
            assert pill.isVisible()
            assert pill.height() == round(50 * pill.property("dpiCompensation"))
            if output:
                output.mkdir(parents=True, exist_ok=True)
                assert pill.grabWindow().save(str(output / f"style-{operation}.png"))
        QTest.qWait(2300)
        assert not pill.isVisible()


if __name__ == "__main__":
    main()
