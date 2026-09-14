"""Check real Windows stacking and focus with simulated recording state."""

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from clarify.desktop.qml_bridge import QmlWorkflowBridge  # noqa: E402
from clarify.desktop.qml_status import QmlStatusPillWindow  # noqa: E402
from qml_pill_transition_smoke import ROOT, Service, Status  # noqa: E402
from workflows import WorkflowPhase  # noqa: E402


def main():
    if sys.platform != "win32":
        raise SystemExit("This smoke test requires the Windows desktop")
    QQuickStyle.setStyle("Basic")
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    if app.platformName() != "windows":
        raise SystemExit("Run without QT_QPA_PLATFORM=offscreen")

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    original_focus = user32.GetForegroundWindow()
    service = Service()
    bridge = QmlWorkflowBridge(service)
    status = Status()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("workflow", bridge)
    engine.rootContext().setContextProperty("pillStatus", status)
    engine.load(QUrl.fromLocalFile(str(ROOT / "clarify/desktop/qml/StatusPill.qml")))
    pill = engine.rootObjects()[0]
    order = QmlStatusPillWindow(pill, bridge, parent=app)
    blocker = QWidget(
        None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
    )
    blocker.setAttribute(Qt.WA_ShowWithoutActivating)
    blocker.setStyleSheet("background: #808080;")
    try:
        for operation_id in range(1, 4):
            service.publish(WorkflowPhase.RECORDING, operation_id=operation_id)
            QTest.qWait(500)
            assert pill.isVisible() and pill.opacity() == 1
            hwnd = int(pill.winId())
            assert user32.GetWindowLongW(hwnd, -20) & 8
            blocker.setGeometry(pill.geometry())
            blocker.show()
            # Reproduce a stale stacking order while the window stays visible.
            assert user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0213)
            assert not user32.GetWindowLongW(hwnd, -20) & 8
            service.publish(WorkflowPhase.PROCESSING, operation_id=operation_id)
            QTest.qWait(100)
            assert user32.GetWindowLongW(hwnd, -20) & 8
            assert user32.GetForegroundWindow() == original_focus
            service.publish(WorkflowPhase.COMPLETED, operation_id=operation_id)
            QTest.qWait(350)
            assert not pill.isVisible()
            blocker.hide()
        print(
            "PASS: 3 native pill cycles recovered topmost order without changing focus"
        )
    finally:
        blocker.close()
        pill.close()
        order.deleteLater()


if __name__ == "__main__":
    main()
