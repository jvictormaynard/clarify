import QtQuick 6.5
import QtQuick.Controls 6.5

Button {
    id: control
    required property Theme theme
    property bool primary: false
    property bool quiet: false

    implicitHeight: control.theme.controlHeight
    hoverEnabled: true

    contentItem: Label {
        text: control.text
        color: !control.enabled
               ? control.theme.dim
               : control.primary ? control.theme.card
               : control.quiet ? control.theme.dim : control.theme.subtleText
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font.pixelSize: 11
        font.weight: control.primary ? Font.DemiBold : Font.Normal
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: control.theme.controlRadius
        color: !control.enabled
               ? control.theme.controlDisabled
               : control.primary ? (control.down ? control.theme.secondaryText : control.theme.text)
               : control.quiet
                 ? (control.down ? control.theme.controlPressed
                    : control.hovered ? control.theme.controlHover : "transparent")
                 : (control.down ? control.theme.controlPressed
                    : control.hovered ? control.theme.controlHover : control.theme.control)
        border.width: control.activeFocus ? 1 : 0
        border.color: control.theme.secondaryText

        Behavior on color {
            ColorAnimation { duration: 110; easing.type: Easing.OutCubic }
        }
    }
}
