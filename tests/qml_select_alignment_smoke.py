"""Exercise shared dropdown geometry without the runtime or user config."""

import os
import math
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from PySide6.QtCore import QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def main():
    QQuickStyle.setStyle("Basic")
    app = QApplication([])
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    reference_font_loaded = False
    if font_path.exists():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
        reference_font_loaded = True
    source = Path(
        os.environ.get(
            "CLARIFYVOICE_TEST_QML_ROOT",
            str(Path(__file__).resolve().parents[1] / "spikes/pyside6/qml"),
        )
    )
    with TemporaryDirectory() as directory:
        stage = Path(shutil.copytree(source, Path(directory) / "qml"))
        engine = QQmlApplicationEngine()
        engine.loadData(
            rb"""
import QtQuick 6.5
import QtQuick.Controls 6.5
ApplicationWindow {
    width: 720; height: 600; visible: true; color: "#0a0a0a"
    property real testScale: 1
    Theme { id: theme }
    Item {
        x: 20; y: 20; scale: testScale; transformOrigin: Item.TopLeft
        SearchSelect {
            objectName: "plain"; width: 320; visualTheme: theme
            options: [{id: "prompt", label: "Prompt"}, {id: "other", label: "Another option"}]
            value: "prompt"; searchable: false
        }
        SearchSelect {
            objectName: "language"; y: 50; width: 320; visualTheme: theme
            refreshable: true
            options: [
                {id: "en", label: "Portuguese", icon: "flags/pt.svg"},
                {id: "pt", label: "Portugu\u00eas: sele\u00e7\u00e3o", icon: "flags/pt.svg"}
            ]
            value: "en"
        }
    }
}
""",
            QUrl.fromLocalFile(str(stage / "Alignment.qml")),
        )
        assert engine.rootObjects()
        window = engine.rootObjects()[0]
        refresh_calls = []
        window.findChild(QObject, "language").refreshRequested.connect(
            lambda: refresh_calls.append(True)
        )

        def check_alignment(control):
            content = control.property("contentItem")
            label = next(
                item
                for item in content.childItems()
                if item.property("text") is not None
            )
            center = label.mapToItem(control, QPointF(0, label.height() / 2)).y()
            assert abs(center - control.height() / 2) < 0.01, (
                label.property("text"),
                center,
                control.height(),
            )
            # Measure the rendered glyphs, not only the text item's line box.
            shot = window.grabWindow()
            ratio = shot.width() / window.width()
            origin = label.mapToScene(QPointF(0, 0))
            end = label.mapToScene(QPointF(label.width(), label.height()))
            top = math.ceil(origin.y() * ratio) + 3
            bottom = math.floor(end.y() * ratio) - 3
            rows = [
                y
                for y in range(top, bottom)
                if any(
                    min(shot.pixelColor(x, y).getRgb()[:3]) > 100
                    for x in range(
                        math.ceil(origin.x() * ratio), math.floor(end.x() * ratio)
                    )
                )
            ]
            assert rows, label.property("text")
            assert min(rows) > top and max(rows) < bottom - 1, (
                label.property("text"),
                "glyphs touch the text area's vertical limits",
            )
            ink_center = (min(rows) + max(rows) + 1) / 2
            target = control.mapToScene(QPointF(0, control.height() / 2)).y() * ratio
            # Keep pixel expectations tied to a known font; Linux fallback
            # fonts differ. Item geometry is checked on every platform.
            if reference_font_loaded:
                assert abs(ink_center - target) <= 1.1, (
                    label.property("text"),
                    ink_center,
                    target,
                )

        for scale in (1.0, 1.1, 1.5, 2.0):
            window.setProperty("testScale", scale)
            QTest.qWait(100)
            for name in ("plain", "language"):
                control = window.findChild(QObject, name)
                check_alignment(control)
                control.clicked.emit()
                QTest.qWait(150)
                results = window.findChild(QObject, name + "Results")
                delegates = [
                    item
                    for item in results.property("contentItem").childItems()
                    if item.property("contentItem") is not None
                ]
                assert delegates
                for delegate in delegates:
                    check_alignment(delegate)
                if name == "language":
                    search = window.findChild(QObject, "languageSearch")
                    refresh = window.findChild(QObject, "languageRefresh")
                    assert refresh.parentItem() == search.parentItem()
                    assert refresh.x() >= search.x() + search.width()
                    assert (
                        abs(
                            refresh.y()
                            + refresh.height() / 2
                            - search.y()
                            - search.height() / 2
                        )
                        < 0.01
                    )
                    assert refresh.property("text") == ""
                    assert (
                        refresh.property("iconSource")
                        .toString()
                        .endswith("refresh.svg")
                    )
                    search.setProperty("text", "Port")
                    count = len(refresh_calls)
                    QTest.mouseClick(
                        window,
                        Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier,
                        refresh.mapToScene(
                            QPointF(refresh.width() / 2, refresh.height() / 2)
                        ).toPoint(),
                    )
                    QTest.qWait(50)
                    assert len(refresh_calls) == count + 1
                    assert search.property("text") == "Port"
                    assert search.property("activeFocus")
                    assert control.property("popupVisible")
                    control.setProperty("busy", True)
                    assert not refresh.property("enabled")
                    control.setProperty("busy", False)
                control.clicked.emit()
                QTest.qWait(150)
        window.setProperty("testScale", 1.1)
        QTest.qWait(100)
        if os.environ.get("ALIGNMENT_SCREENSHOT"):
            assert window.grabWindow().save(os.environ["ALIGNMENT_SCREENSHOT"])
        window.close()
        engine.deleteLater()
        app.processEvents()
        print(
            "PASS: dropdown text and menu options centered at 100%, 110%, 150%, and 200% scale"
        )


if __name__ == "__main__":
    main()
