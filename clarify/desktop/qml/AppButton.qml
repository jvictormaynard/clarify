import QtQuick 6.5
import QtQuick.Controls 6.5

Button {
    id: control
    required property Theme theme
    property bool primary: false
    property bool quiet: false
    property int contentAlignment: Text.AlignHCenter
    property url iconSource: ""
    property int iconSize: 16

    implicitHeight: control.theme.fieldHeight
    hoverEnabled: true

    contentItem: Item {
        Image {
            id: buttonIcon
            width: control.iconSource == "" ? 0 : control.iconSize
            height: control.iconSize
            anchors.verticalCenter: parent.verticalCenter
            x: control.text === "" ? (parent.width - width) / 2 : 0
            visible: control.iconSource != ""
            source: control.iconSource
            sourceSize.width: control.iconSize
            sourceSize.height: control.iconSize
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            opacity: !control.enabled
                     ? 0.35
                     : control.primary ? 1.0 : 0.62
        }

        Label {
            x: control.iconSource != "" ? buttonIcon.x + buttonIcon.width + 6 : 0
            width: Math.max(0, parent.width - x)
            height: parent.height
            visible: control.text !== ""
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
        radius: control.theme.fieldRadius
        color: !control.enabled
               ? control.theme.controlDisabled
               : control.hovered || control.down || control.checked || control.visualFocus
                 ? control.theme.controlHover
                 : control.quiet ? "transparent" : control.theme.control
        border.width: control.quiet ? 0 : 1
        border.color: control.theme.border

        Behavior on color {
            ColorAnimation { duration: 110; easing.type: Easing.OutCubic }
        }
    }
}
