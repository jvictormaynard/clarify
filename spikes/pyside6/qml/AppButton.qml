import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Button {
    id: control
    required property Theme theme
    property bool primary: false
    property bool quiet: false
    property int contentAlignment: Text.AlignHCenter
    property string iconText: ""

    implicitHeight: control.theme.controlHeight
    hoverEnabled: true

    contentItem: RowLayout {
        spacing: control.iconText === "" ? 0 : 6

        Label {
            Layout.preferredWidth: control.iconText === "" ? 0 : 16
            visible: control.iconText !== ""
            text: control.iconText
            color: !control.enabled
                   ? control.theme.dim
                   : control.primary ? control.theme.text
                   : control.quiet ? control.theme.dim : control.theme.subtleText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 13
            font.weight: Font.Normal
        }

        Label {
            Layout.fillWidth: true
            text: control.text
            color: !control.enabled
                   ? control.theme.dim
                   : control.primary ? control.theme.text
                   : control.quiet ? control.theme.dim : control.theme.subtleText
            horizontalAlignment: control.contentAlignment
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 12
            font.weight: Font.Normal
            elide: Text.ElideRight
        }
    }

    background: Rectangle {
        radius: control.theme.controlRadius
        color: !control.enabled
               ? control.theme.controlDisabled
               : control.quiet
                 ? (control.down ? control.theme.controlPressed
                    : control.hovered ? control.theme.controlHover : "transparent")
                 : (control.down ? control.theme.controlPressed
                    : control.hovered ? control.theme.controlHover : control.theme.control)
        border.width: 0

        Behavior on color {
            ColorAnimation { duration: 110; easing.type: Easing.OutCubic }
        }
    }
}
