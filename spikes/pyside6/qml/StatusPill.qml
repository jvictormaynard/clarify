import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Window 6.5

Window {
    id: pill
    objectName: "workflowStatusPill"
    readonly property real dpiCompensation: 1.0 / Math.max(1.0,
                                                           Screen.devicePixelRatio)
    readonly property int designWidth: 142
    readonly property int designHeight: 42
    width: Math.round(designWidth * dpiCompensation)
    height: Math.round(designHeight * dpiCompensation)
    x: Screen.virtualX + (Screen.width - width) / 2
    y: Screen.virtualY + Screen.height - height - 80
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
           | Qt.WindowDoesNotAcceptFocus
    readonly property bool requestedVisible: workflow.surface === "recording"
                                             || workflow.surface === "processing"
                                             || workflow.surface === "voice_processing"
                                             || (workflow.surface === "success"
                                                 && successVisible)
    visible: requestedVisible || opacity > 0.001
    opacity: requestedVisible ? 1.0 : 0.0
    Behavior on opacity {
        NumberAnimation {
            duration: theme.fadeDuration
            easing.type: Easing.OutCubic
        }
    }
    title: "ClarifyVoice workflow status"

    Theme { id: theme }
    property bool successVisible: false
    property real motionPhase: 0.0
    readonly property bool recording: workflow.recording
    readonly property bool processing: requestedVisible && !recording
                                      && workflow.surface !== "success"

    Timer {
        interval: 16
        repeat: true
        running: pill.visible
        onTriggered: pill.motionPhase += 0.085
    }

    Timer {
        id: successTimer
        interval: 850
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
                property bool fadeShown: pill.recording
                visible: fadeShown || opacity > 0.001
                opacity: fadeShown ? 1.0 : 0.0
                Behavior on opacity {
                    NumberAnimation {
                        duration: theme.fadeDuration
                        easing.type: Easing.OutCubic
                    }
                }

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
                property bool fadeShown: pill.processing
                visible: fadeShown || opacity > 0.001
                opacity: fadeShown ? 1.0 : 0.0
                Behavior on opacity {
                    NumberAnimation {
                        duration: theme.fadeDuration
                        easing.type: Easing.OutCubic
                    }
                }

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
                property bool fadeShown: workflow.surface === "success"
                                         && pill.successVisible
                visible: fadeShown || opacity > 0.001
                opacity: fadeShown ? 1.0 : 0.0
                Behavior on opacity {
                    NumberAnimation {
                        duration: theme.fadeDuration
                        easing.type: Easing.OutCubic
                    }
                }
                text: "✓"
                color: "#30d158"
                font.pixelSize: 25
                font.weight: Font.DemiBold
                Accessible.name: "Completed"
            }
        }
    }
}
