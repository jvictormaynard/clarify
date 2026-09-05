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
    delegate: QuickMenuItem { visualTheme: menu.visualTheme }
    background: Rectangle {
        radius: 10
        color: menu.visualTheme.control
        border.color: menu.visualTheme.controlPressed
    }
}
