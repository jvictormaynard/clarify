import QtQuick
import QtQuick.Controls

Menu {
    id: menu
    required property Theme visualTheme
    popupType: Popup.Window
    width: 252
    padding: 6
    margins: 8
    overlap: 0
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: menu.visualTheme.fadeDuration; easing.type: Easing.OutCubic }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: menu.visualTheme.fadeDuration; easing.type: Easing.OutCubic }
    }
    delegate: QuickMenuItem { visualTheme: menu.visualTheme }
    background: Rectangle {
        radius: 10
        color: menu.visualTheme.control
        border.color: menu.visualTheme.controlPressed
    }
}
