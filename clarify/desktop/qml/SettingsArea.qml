import QtQuick 6.5
import QtQuick.Controls 6.5

TextArea {
    id: field
    property string focusText: ""
    readonly property bool pendingEdit: activeFocus && text !== focusText
    onActiveFocusChanged: if (activeFocus) focusText = text
    required property Theme visualTheme
    property bool flat: false
    implicitHeight: Math.max(80, contentHeight + topPadding + bottomPadding)
    padding: flat ? 0 : 11
    font.pixelSize: visualTheme.fieldFontSize
    color: enabled ? visualTheme.text : visualTheme.dim
    placeholderTextColor: visualTheme.subtleText
    selectionColor: visualTheme.controlPressed
    selectedTextColor: visualTheme.text
    wrapMode: TextEdit.Wrap
    selectByMouse: true
    background: Rectangle {
        radius: field.visualTheme.fieldRadius
        color: field.flat ? "transparent" : field.enabled
            ? field.visualTheme.control : field.visualTheme.controlDisabled
        border.width: field.flat ? 0 : 1
        border.color: field.activeFocus ? field.visualTheme.secondaryText : field.visualTheme.border
        Behavior on border.color { ColorAnimation { duration: 100 } }
    }
}
