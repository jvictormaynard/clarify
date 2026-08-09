import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Button {
    id: control
    required property Theme theme
    property bool primary: false
    property bool quiet: false
    property int contentAlignment: Text.AlignHCenter
    property url iconSource: ""

    implicitHeight: control.theme.controlHeight
    hoverEnabled: true

    contentItem: RowLayout {
        spacing: control.iconSource == "" ? 0 : 6

        Image {
            Layout.preferredWidth: control.iconSource == "" ? 0 : 16
            Layout.preferredHeight: 16
            Layout.alignment: control.text === "" ? Qt.AlignHCenter : Qt.AlignVCenter
            visible: control.iconSource != ""
            source: control.iconSource
            sourceSize.width: 16
            sourceSize.height: 16
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            opacity: !control.enabled
                     ? 0.35
                     : control.primary ? 1.0 : 0.62
        }

        Label {
            Layout.fillWidth: control.text !== ""
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
