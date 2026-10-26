"""Render meetings with synthetic data and no recorder, account, or profile."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QUrl, QTimer  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from clarify.desktop.qml_localization import ClarifyTranslator  # noqa: E402
from clarify.desktop.qml_meetings import QmlMeetingController  # noqa: E402
from meeting_store import MeetingStore  # noqa: E402
from meeting_workflow import MeetingWorkflow  # noqa: E402
from shared.meeting_contract import MeetingIdentity  # noqa: E402


def main():
    QQuickStyle.setStyle("Basic")
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    translator = ClarifyTranslator(language="pt")
    app.installTranslator(translator)
    with tempfile.TemporaryDirectory(prefix="meeting-ui-fixture-") as directory:
        store = MeetingStore(directory)
        mid = store.create("guest", "Revisar o prototipo", language="pt")["id"]
        cid, _ = store.open_chunk("guest", mid, "system", 0)
        store.finish_chunk("guest", mid, cid, 1000)
        store.save_transcript(
            "guest", mid, cid, "Vamos testar a recuperacao antes de publicar."
        )
        store.save_notes("guest", mid, "Validar as duas fontes no Windows.")
        _, revision, _ = store.summary_request("guest", mid)
        store.save_summary(
            "guest",
            mid,
            revision,
            "Resumo do teste.\n\nDecisoes: testar a recuperacao.\n\nTarefas: validar as duas fontes.",
        )
        store.end("guest", mid)
        provider = Mock()
        provider.identity.return_value = MeetingIdentity("guest", 0, False)
        provider.workflows.registry.metadata = ()
        workflow = MeetingWorkflow(store, provider, source_factory=Mock())
        workflow.selected = mid
        controller = QmlMeetingController(workflow)
        if "--recording" in sys.argv:
            controller._timer.stop()
            workflow._thread = Mock()
            workflow._thread.is_alive.return_value = True
            controller._state = {
                **controller.state,
                "phase": "recording",
                "active": True,
                "duration": 73,
                "sources": {
                    "microphone": {"state": "recording", "level": 0.55, "warning": ""},
                    "system": {
                        "state": "failed",
                        "level": 0,
                        "warning": "meeting.device_changed",
                    },
                },
            }
        engine = QQmlApplicationEngine()
        messages = []
        engine.warnings.connect(
            lambda warnings: messages.extend(w.toString() for w in warnings)
        )
        engine.rootContext().setContextProperty("meetings", controller)
        qml = ROOT / "clarify/desktop/qml"
        engine.addImportPath(str(qml))
        engine.load(QUrl.fromLocalFile(str(qml / "MeetingWindow.qml")))
        engine.load(QUrl.fromLocalFile(str(qml / "MeetingIndicator.qml")))
        if len(engine.rootObjects()) != 2:
            print("\n".join(messages))
            return 1
        window = engine.rootObjects()[0]
        window.show()
        window.requestActivate()
        output = Path(sys.argv[1]) if len(sys.argv) > 1 else None

        def verify():
            if output:
                output.parent.mkdir(parents=True, exist_ok=True)
                window.grabWindow().save(str(output))
            controller.shutdown()
            app.quit()

        QTimer.singleShot(500, verify)
        app.exec()
        if messages:
            print("\n".join(messages))
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
