import QtQuick 6.5
import QtQuick.Controls 6.5

ComboBox {
    id: control
    required property Theme visualTheme
    hoverEnabled: true
    implicitHeight: visualTheme.fieldHeight
    leftPadding: 10
    rightPadding: 30
    contentItem: Text {
        text: control.displayText
        color: control.enabled ? control.visualTheme.text : control.visualTheme.dim
        font.pixelSize: control.visualTheme.fieldFontSize
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: control.visualTheme.fieldRadius
        color: !control.enabled ? control.visualTheme.controlDisabled
            : control.hovered || control.down || control.visualFocus || control.popup.visible
              ? control.visualTheme.controlHover : control.visualTheme.control
        border.color: control.visualTheme.border
    }
    indicator: DropdownIndicator {
        x: control.width - width - 10
        y: (control.height - height) / 2
        rotation: control.popup.visible ? 180 : 0
    }
    delegate: ItemDelegate {
        required property string modelData
        required property int index
        highlighted: control.highlightedIndex === index
        implicitHeight: control.visualTheme.fieldHeight
        width: control.width
        contentItem: Text { text: modelData; color: control.visualTheme.text; font.pixelSize: control.visualTheme.fieldFontSize }
        background: Rectangle { color: parent.hovered || parent.highlighted ? control.visualTheme.controlHover : control.visualTheme.card }
    }
}
