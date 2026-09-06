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
            font.pixelSize: row.visualTheme.fieldFontSize
            wrapMode: Text.WordWrap
        }
        RowLayout {
            id: controlArea
            Layout.preferredWidth: Math.max(0, row.availableWidth - 180)
            Layout.minimumWidth: Math.max(0, row.availableWidth - 180)
            Layout.maximumWidth: Math.max(0, row.availableWidth - 180)
            spacing: 8
        }
    }
}
