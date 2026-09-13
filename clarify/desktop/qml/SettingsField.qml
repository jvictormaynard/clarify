import QtQuick 6.5
import QtQuick.Controls 6.5

TextField {
    id: field
    property string focusText: ""
    readonly property bool pendingEdit: activeFocus && text !== focusText
    onActiveFocusChanged: if (activeFocus) focusText = text
    required property Theme visualTheme
    implicitHeight: visualTheme.fieldHeight
    leftPadding: 11
    rightPadding: 11
    font.pixelSize: visualTheme.fieldFontSize
    color: enabled ? visualTheme.text : visualTheme.dim
    placeholderTextColor: visualTheme.subtleText
    selectionColor: visualTheme.controlPressed
    selectedTextColor: visualTheme.text
    selectByMouse: true
    background: Rectangle {
        radius: field.visualTheme.fieldRadius
        color: field.enabled ? field.visualTheme.control : field.visualTheme.controlDisabled
        border.color: field.activeFocus ? field.visualTheme.secondaryText : field.visualTheme.border
        Behavior on border.color { ColorAnimation { duration: 100 } }
    }
}
