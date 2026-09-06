import QtQuick 6.5
import QtQuick.Controls 6.5

ComboBox {
    id: control
    required property Theme visualTheme
    hoverEnabled: true
    implicitHeight: 32
    leftPadding: 10
    rightPadding: 30
    contentItem: Text {
        text: control.displayText
        color: control.enabled ? control.visualTheme.text : control.visualTheme.dim
        font.pixelSize: 11
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 6
        color: !control.enabled ? control.visualTheme.controlDisabled
            : control.hovered || control.down || control.activeFocus || control.popup.visible
              ? control.visualTheme.controlHover : control.visualTheme.control
        border.color: control.visualTheme.border
    }
    indicator: Text {
        text: "v"; color: control.visualTheme.secondaryText
        x: control.width - 22; y: (control.height - height) / 2
        font.pixelSize: 11
    }
    delegate: ItemDelegate {
        required property string modelData
        width: control.width
        contentItem: Text { text: modelData; color: control.visualTheme.text; font.pixelSize: 11 }
        background: Rectangle { color: parent.hovered ? control.visualTheme.controlHover : control.visualTheme.card }
    }
}
