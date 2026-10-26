import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

ApplicationWindow {
    id: root
    objectName: "clarifyMeetingIndicator"
    title: qsTr("meeting.title")
    width: 330
    height: 70
    flags: Qt.Tool | Qt.WindowStaysOnTopHint
    visible: meetings.blocksProcessing
    color: theme.card
    property Theme visualTheme: theme
    Theme { id: theme }
    onClosing: function(close) { if (meetings.blocksProcessing) { close.accepted = false; meetings.open() } }
    RowLayout {
        anchors.fill: parent
        anchors.margins: 12
        Label { text: qsTr("meeting." + meetings.state.phase) + " · " + meetings.state.duration + "s"; color: theme.text; Layout.fillWidth: true }
        AppButton { theme: root.visualTheme; implicitWidth: 70; text: qsTr("meeting.open"); onClicked: meetings.open() }
        AppButton { theme: root.visualTheme; implicitWidth: 70; text: qsTr("meeting.stop"); visible: meetings.state.phase === "recording"; onClicked: meetings.stop() }
    }
}
