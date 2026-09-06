import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Window 6.5

Window {
    id: pill
    objectName: "workflowStatusPill"
    readonly property real dpiCompensation: 1.0 / Math.max(1.0,
                                                           Screen.devicePixelRatio)
    readonly property bool refinementWarning: workflow.refinementFailed === true
    readonly property int designWidth: refinementWarning ? 330 : 142
    readonly property int designHeight: 42
    width: Math.round(designWidth * dpiCompensation)
    height: Math.round(designHeight * dpiCompensation)
    x: Screen.virtualX + (Screen.width - width) / 2
    y: Screen.virtualY + Screen.height - height - 80
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
           | Qt.WindowDoesNotAcceptFocus
    visible: workflow.surface === "recording"
             || workflow.surface === "processing"
             || workflow.surface === "voice_processing"
             || (workflow.surface === "success" && successVisible)
    title: "Clarify workflow status"

    Theme { id: theme }
    property bool successVisible: false
    property real motionPhase: 0.0
    readonly property bool recording: workflow.recording
    readonly property bool processing: visible && !recording
                                      && workflow.surface !== "success"

    Timer {
        interval: 16
        repeat: true
        running: pill.visible
        onTriggered: pill.motionPhase += 0.085
    }

    Timer {
        id: successTimer
        objectName: "statusDismissTimer"
        interval: pill.refinementWarning ? 5000 : 850
        repeat: false
        onTriggered: pill.successVisible = false
    }

    Connections {
        target: workflow

        function onSurfaceChanged() {
            if (workflow.surface === "success") {
                pill.successVisible = true
                successTimer.restart()
            } else {
                successTimer.stop()
                pill.successVisible = false
            }
        }
    }

    Item {
        width: pill.designWidth
        height: pill.designHeight
        scale: pill.dpiCompensation
        transformOrigin: Item.TopLeft

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: height / 2
            color: theme.card
            border.color: theme.border
            border.width: 1
            Accessible.name: workflow.status

            Image {
                id: targetIcon
                x: 7
                y: 9
                width: 24
                height: 24
                source: pillStatus.targetIcon
                sourceSize.width: 64
                sourceSize.height: 64
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                Accessible.name: "Target application"
            }

            Item {
                id: waveform
                x: 38
                y: 0
                width: 96
                height: parent.height
                visible: pill.recording

                Repeater {
                    model: 12

                    Rectangle {
                        required property int index
                        readonly property real position: index / 11
                        readonly property real envelope: 0.58
                                                         + 0.42 * Math.sin(position * Math.PI)
                        readonly property real motion: 0.12
                                                       * Math.sin(pill.motionPhase + index * 0.82)
                        readonly property real amplitude: Math.max(
                            0.22,
                            Math.min(
                                0.98,
                                (pillStatus.audioLevel * 1.45 + 0.24 + motion)
                                * envelope
                            )
                        )
                        x: index * (waveform.width / 12)
                           + (waveform.width / 12 - width) / 2
                        anchors.verticalCenter: parent.verticalCenter
                        width: 3
                        height: Math.max(6.4, (waveform.height - 16) * amplitude)
                        radius: width / 2
                        color: theme.text

                        Behavior on height {
                            NumberAnimation { duration: 45; easing.type: Easing.OutCubic }
                        }
                    }
                }
            }

            Item {
                id: progress
                x: 45
                width: 82
                height: parent.height
                visible: pill.processing

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width
                    height: 2
                    radius: 1
                    color: theme.border
                }

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width * 0.32
                    height: 2
                    radius: 1
                    color: theme.text
                    x: (parent.width - width)
                       * (Math.sin(pill.motionPhase * 0.62 - Math.PI / 2) + 1) / 2
                }
            }

            Label {
                anchors.centerIn: progress
                visible: workflow.surface === "success" && pill.successVisible
                         && !pill.refinementWarning
                text: "✓"
                color: "#30d158"
                font.pixelSize: 25
                font.weight: Font.DemiBold
                Accessible.name: "Completed"
            }

            Label {
                objectName: "refinementWarningLabel"
                x: 40
                width: parent.width - 50
                anchors.verticalCenter: parent.verticalCenter
                visible: pill.refinementWarning
                text: workflow.status
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                color: theme.text
                Accessible.name: text
            }
        }
    }
}
