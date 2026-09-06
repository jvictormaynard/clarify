import QtQuick 6.5
import QtQuick.Controls 6.5

ComboBox {
    id: control
    required property Theme theme
    implicitHeight: 36
    hoverEnabled: true
    contentItem: Label {
        leftPadding: 12; rightPadding: 32
        text: control.displayText
        color: control.enabled ? control.theme.text : control.theme.subtleText
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: Canvas {
        x: control.width - width - 14; y: (control.height - height) / 2
        width: 10; height: 6
        onPaint: {
            var context = getContext("2d")
            context.clearRect(0, 0, width, height)
            context.strokeStyle = control.theme.secondaryText
            context.lineWidth = 1.5
            context.beginPath(); context.moveTo(1, 1); context.lineTo(5, 5); context.lineTo(9, 1); context.stroke()
        }
    }
    background: Rectangle {
        radius: 8
        color: control.hovered ? control.theme.controlHover : control.theme.control
        border.width: 1
        border.color: control.activeFocus ? control.theme.secondaryText : control.theme.border
    }
    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: control.width
        text: modelData[control.textRole]
        highlighted: control.highlightedIndex === index
        contentItem: Label { text: parent.text; color: control.theme.text; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { color: parent.highlighted ? control.theme.controlHover : control.theme.control }
    }
}
