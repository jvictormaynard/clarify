import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

MenuItem {
    id: control
    required property Theme visualTheme
    implicitHeight: 36
    leftPadding: 10; rightPadding: 28
    topPadding: 0; bottomPadding: 0
    contentItem: RowLayout {
        spacing: 10
        Image {
            Layout.preferredWidth: 16; Layout.preferredHeight: 16
            source: control.icon.source
            sourceSize: Qt.size(32, 32)
            fillMode: Image.PreserveAspectFit
            opacity: control.enabled ? 0.75 : 0.3
        }
        Label {
            Layout.fillWidth: true; Layout.fillHeight: true
            text: control.text
            font.pixelSize: 13
            color: control.enabled ? control.visualTheme.text : control.visualTheme.dim
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }
    indicator: Label {
        visible: control.checked
        text: "✓"
        color: control.visualTheme.text
        anchors.right: parent.right; anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
    }
    arrow: Label {
        visible: control.subMenu !== null
        text: "›"; font.pixelSize: 20
        color: control.visualTheme.secondaryText
        anchors.right: parent.right; anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
    }
    background: Rectangle {
        radius: 6
        color: control.highlighted ? control.visualTheme.controlHover : "transparent"
    }
}
