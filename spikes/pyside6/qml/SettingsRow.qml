import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Pane {
    id: row
    required property Theme visualTheme
    property string title: ""
    default property alias controls: controlArea.data
    padding: 0
    background: null
    contentItem: RowLayout {
        spacing: 12
        Label {
            Layout.fillWidth: true
            Layout.minimumWidth: 90
            text: row.title
            color: row.visualTheme.secondaryText
            font.pixelSize: 11
            wrapMode: Text.WordWrap
        }
        RowLayout {
            id: controlArea
            Layout.preferredWidth: row.availableWidth * 0.62
            Layout.minimumWidth: row.availableWidth * 0.62
            Layout.maximumWidth: row.availableWidth * 0.62
            spacing: 8
        }
    }
}
