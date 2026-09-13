import QtQuick 6.5
import QtQuick.Controls 6.5

Switch {
    id: control
    required property Theme visualTheme
    implicitWidth: 38 + (text ? 10 + contentItem.implicitWidth : 0)
    implicitHeight: Math.max(30, contentItem.implicitHeight)
    padding: 0
    leftPadding: 38 + (text ? 10 : 0)
    hoverEnabled: true
    Accessible.name: text
    contentItem: Label {
        text: control.text
        color: control.enabled ? control.visualTheme.secondaryText : control.visualTheme.dim
        font.pixelSize: control.visualTheme.fieldFontSize
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
    }
    indicator: Rectangle {
        width: 34; height: 20
        x: 2; y: (control.height - height) / 2
        radius: 10
        opacity: control.enabled ? 1 : 0.4
        color: control.checked ? control.visualTheme.secondaryText : control.visualTheme.controlHover
        border.color: control.activeFocus ? control.visualTheme.text : control.visualTheme.subtleText
        border.width: control.activeFocus ? 2 : 1
        Rectangle {
            x: control.checked ? 17 : 3; y: 3
            width: 14; height: 14; radius: 7
            color: control.checked ? control.visualTheme.card : control.visualTheme.secondaryText
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }
}
