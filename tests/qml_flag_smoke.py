"""Check actual flag pixels, corner clipping and source changes, offline."""

import os
import shutil
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow


def main():
    app = QGuiApplication([])
    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory() as directory:
        qml = Path(
            shutil.copytree(root / "spikes/pyside6/qml", Path(directory) / "qml")
        )
        engine = QQmlApplicationEngine()
        engine.loadData(
            b"""
import QtQuick
import QtQuick.Window
Window {
    id: root
    property string firstLanguage: "en"
    width: 220; height: 64; visible: true; color: "#151515"
    Row {
        x: 10; y: 10; spacing: 16
        Repeater {
            model: ["en", "pt", "es", "de", "ru"]
            RoundedFlag {
                required property string modelData
                objectName: modelData
                source: "flags/" + (modelData === "en" ? root.firstLanguage : modelData) + ".svg"
            }
        }
    }
}
""",
            QUrl.fromLocalFile(str(qml / "FlagTest.qml")),
        )
        assert engine.rootObjects(), "QML failed to load"
        window = engine.rootObjects()[0]
        assert isinstance(window, QQuickWindow)

        def capture():
            for _ in range(70):
                app.processEvents()
                time.sleep(0.01)
            return window.grabWindow()

        shot = capture()
        if len(sys.argv) > 1:
            assert shot.save(sys.argv[1])
        ratio = shot.width() / window.width()
        background = shot.pixelColor(0, 0)
        for index, name in enumerate(("en", "pt", "es", "de", "ru")):
            x, y = int((10 + index * 40) * ratio), int(10 * ratio)
            colors = {
                shot.pixelColor(x + i, y + j).name()
                for i in range(int(24 * ratio))
                for j in range(int(18 * ratio))
            }
            assert len(colors) > 3, (name, "missing artwork", colors)
            corner = shot.pixelColor(x, y)
            assert (
                max(
                    abs(a - b)
                    for a, b in zip(corner.getRgb()[:3], background.getRgb()[:3])
                )
                < 30
            ), (name, "corner not clipped", corner.name())
            assert shot.pixelColor(x + int(12 * ratio), y) != background, (
                name,
                "top edge missing",
            )
        window.setProperty("firstLanguage", "pt")
        changed = capture()
        assert changed != shot, "language change did not repaint"
        window.close()
        print(
            "PASS: five visible flags, transparent rounded corners, no inset border, source change; "
            + os.environ.get("QSG_RHI_BACKEND", "default backend")
        )


if __name__ == "__main__":
    main()
