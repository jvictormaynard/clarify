import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Pane {
    id: group
    required property Theme visualTheme
    property string title: ""
    property string description: ""
    property bool collapsible: false
    property bool expanded: !collapsible
    default property alias content: groupBody.data
    padding: 0
    topPadding: 6
    bottomPadding: collapsible ? 0 : 12
    background: null
    contentItem: ColumnLayout {
        spacing: 10
        Label {
            Layout.fillWidth: true
            visible: group.title !== "" && !group.collapsible
            text: group.title
            color: group.visualTheme.secondaryText
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
        AppButton {
            objectName: group.objectName + "Toggle"
            Layout.fillWidth: true
            Layout.preferredHeight: 24
            theme: group.visualTheme
            text: group.title
            quiet: true
            visible: group.title !== "" && group.collapsible
            contentAlignment: Text.AlignLeft
            leftPadding: 0
            rightPadding: 22
            Accessible.name: group.title
            Accessible.description: group.collapsible ? (group.expanded ? "Expanded" : "Collapsed") : ""
            onClicked: group.expanded = !group.expanded
            contentItem: Label {
                text: group.title
                color: group.visualTheme.secondaryText
                font.pixelSize: 11
                verticalAlignment: Text.AlignVCenter
            }
            DropdownIndicator {
                visible: group.collapsible
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                rotation: group.expanded ? 180 : 0
            }
        }
        Label {
            Layout.fillWidth: true
            visible: group.description !== "" && group.expanded
            text: group.description
            color: group.visualTheme.subtleText
            font.pixelSize: 11
            wrapMode: Text.WordWrap
        }
        ColumnLayout {
            id: groupBody
            Layout.fillWidth: true
            spacing: 12
            visible: group.expanded
        }
    }
}
