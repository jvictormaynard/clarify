"""Exercise the actual Main.qml deferred-menu handler in a Qt event loop."""

from pathlib import Path
import sys
import shutil
from tempfile import TemporaryDirectory
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QTimer

root = Path(__file__).resolve().parents[1]
qml_dir = root / "spikes/pyside6/qml"
source = (qml_dir / "Main.qml").read_text(encoding="utf8")
start = source.index("        property var pendingAction: null")
end = source.index("\n        QuickMenu {", start)
handler = source[start:end]
# Qt's relative QML imports do not resolve consistently over a Windows UNC URL.
assets = TemporaryDirectory()
shutil.copytree(qml_dir, Path(assets.name) / "qml")
qml_dir = Path(assets.name) / "qml"
app = QGuiApplication([])
engine = QQmlApplicationEngine()
qml = """import QtQuick
import QtQuick.Controls
import "DIRECTORY"
ApplicationWindow {
    visible: true; width: 200; height: 100
    property int actions: 0
    Theme { id: theme }
    QuickMenu {
        id: quickMenu; visualTheme: theme
        HANDLER
        onOpened: runAfterClose(function() { actions += 1 })
    }
    Component.onCompleted: quickMenu.runAfterClose(function() { actions += 1 })
    Timer { interval: 80; running: true; onTriggered: quickMenu.open() }
}
""".replace("DIRECTORY", qml_dir.as_uri()).replace("HANDLER", handler)
engine.loadData(qml.encode(), QUrl.fromLocalFile(str(qml_dir / "menu-case.qml")))
if not engine.rootObjects():
    raise SystemExit(2)
window = engine.rootObjects()[0]
assert isinstance(window, QQuickWindow)


def finish():
    count = window.property("actions")
    print("closed-menu and open-menu actions:", count)
    app.exit(0 if count == 2 else 1)


QTimer.singleShot(1200, finish)
sys.exit(app.exec())
