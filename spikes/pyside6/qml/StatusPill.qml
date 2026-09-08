import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Window 6.5

Window {
    id: pill
    objectName: "workflowStatusPill"
    readonly property real dpiCompensation: 1.0 / Math.max(1.0,
                                                           Screen.devicePixelRatio)
    readonly property int designWidth: 168
    readonly property bool refinementWarning: workflow.refinementFailed === true
    readonly property int designHeight: 50
    readonly property bool feedback: workflow.feedbackVisible
    property string feedbackCaption: ""
    readonly property int horizontalInset: 6
    readonly property real feedbackWidth: Math.min(620, Math.max(230,
        feedbackLabel.implicitWidth + feedbackActions.width + 66)) + 2 * horizontalInset
    property real animatedWidth: feedback ? feedbackWidth
                                 : starting || !requestedVisible ? 88 : designWidth
    Behavior on animatedWidth {
        NumberAnimation { duration: 280; easing.type: Easing.OutCubic }
    }
    width: Math.round(animatedWidth * dpiCompensation)
    height: Math.round(designHeight * dpiCompensation)
    x: Screen.virtualX + (Screen.width - width) / 2
    y: Screen.virtualY + Screen.height - height - 80
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
           | Qt.WindowDoesNotAcceptFocus
    readonly property bool requestedVisible: workflow.surface === "recording"
                                             || workflow.transitionPending
                                             || feedback
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
    title: "Clarify workflow status"

    Theme { id: theme }
    property bool successVisible: false
    property real motionPhase: 0.0
    readonly property bool recording: workflow.recording
    readonly property bool starting: workflow.transitionPending
                                     || (recording && !pillStatus.recordingReady)
    readonly property bool processing: requestedVisible && !recording
                                      && !starting
                                      && !feedback
                                      && workflow.surface !== "success"

    function syncFeedback() {
        feedbackTimer.stop()
        if (feedback) {
            feedbackCaption = workflow.feedbackTitle
            if (!workflow.canRetryTranscription) {
                feedbackTimer.operationId = workflow.feedbackOperationId
                feedbackTimer.restart()
            }
        }
    }
    Component.onCompleted: syncFeedback()

    Timer {
        id: feedbackTimer
        objectName: "statusDismissTimer"
        interval: workflow.cancellationVisible || pill.refinementWarning ? 5000 : 3200
        property int operationId: 0
        onTriggered: workflow.dismissFeedback(operationId)
    }

    Timer {
        interval: 16
        repeat: true
        running: pill.visible && !pill.feedback
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
            pill.syncFeedback()
            if (workflow.surface === "success") {
                pill.successVisible = true
                successTimer.restart()
            } else {
                successTimer.stop()
                pill.successVisible = false
            }
        }
        function onStatusChanged() {
            if (pill.feedback) pill.feedbackCaption = workflow.feedbackTitle
        }
    }

    Item {
        width: pill.animatedWidth
        height: pill.designHeight
        scale: pill.dpiCompensation
        transformOrigin: Item.TopLeft

        Rectangle {
            objectName: "statusCapsule"
            anchors.fill: parent
            anchors.margins: 1
            radius: height / 2
            color: theme.card
            border.color: theme.border
            border.width: 1
            Accessible.name: workflow.status

            Item {
                x: pill.horizontalInset
                width: parent.width - 2 * pill.horizontalInset
                height: parent.height

                Image {
                    id: targetIcon
                    x: 8
                    anchors.verticalCenter: parent.verticalCenter
                    width: 26
                    height: 26
                    source: pillStatus.targetIcon
                    sourceSize.width: 64
                    sourceSize.height: 64
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                    Accessible.name: "Target application"
                }

                Item {
                    id: captureSpinner
                    objectName: "captureStartupSpinner"
                    x: 48
                    anchors.verticalCenter: parent.verticalCenter
                    width: 18
                    height: 18
                    opacity: pill.starting ? 1 : 0
                    visible: opacity > 0.001
                    Behavior on opacity { NumberAnimation { duration: 180 } }
                    Canvas {
                        anchors.fill: parent
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            ctx.lineWidth = 1.8
                            ctx.lineCap = "round"
                            ctx.strokeStyle = theme.text
                            ctx.beginPath()
                            ctx.arc(width / 2, height / 2, 7, 0, Math.PI * 1.45)
                            ctx.stroke()
                        }
                    }
                    RotationAnimator on rotation {
                        from: 0; to: 360; duration: 900
                        loops: Animation.Infinite
                        running: pill.visible && pill.starting
                    }
                    Accessible.name: "Starting microphone"
                }

                Item {
                    id: waveform
                    objectName: "captureWaveform"
                    x: 42
                    y: 0
                    width: 104
                    height: parent.height
                    property bool fadeShown: pill.recording && !pill.starting
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
                    x: 50
                    width: 90
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

                Label {
                    id: feedbackLabel
                    objectName: "pillFeedbackLabel"
                    x: 47 + (1 - opacity) * 6
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 47 - feedbackActions.width - 17
                    text: pill.feedbackCaption
                    font.pixelSize: 16
                    color: theme.text
                    elide: Text.ElideRight
                    opacity: pill.feedback ? 1 : 0
                    visible: opacity > 0.001
                    Behavior on opacity {
                        NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                    }
                    Accessible.name: workflow.status
                }

                Row {
                    id: feedbackActions
                    anchors.right: parent.right
                    anchors.rightMargin: 7
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    opacity: pill.feedback ? 1 : 0
                    visible: opacity > 0.001
                    enabled: pill.feedback
                    Behavior on opacity {
                        NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                    }
                    ToolButton {
                        id: undoButton
                        objectName: "undoCancellationButton"
                        visible: workflow.cancellationVisible
                        enabled: workflow.canUndoCancellation
                        width: Math.max(64, contentItem.implicitWidth + 24)
                        height: 32
                        padding: 0
                        text: workflow.language === "pt" ? "Desfazer" : "Undo"
                        focusPolicy: Qt.NoFocus
                        contentItem: Label {
                            text: undoButton.text
                            color: undoButton.enabled ? theme.text : theme.subtleText
                            font.pixelSize: 16
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: 8
                            color: undoButton.hovered ? "#30ffffff" : "#18ffffff"
                        }
                        Accessible.name: text
                        onClicked: workflow.undoCancellation()
                    }
                    ToolButton {
                        objectName: "retryTranscriptionButton"
                        visible: workflow.canRetryTranscription
                        width: 32
                        height: 32
                        padding: 0
                        text: "↻"
                        focusPolicy: Qt.NoFocus
                        contentItem: Label {
                            text: parent.text
                            color: theme.text
                            font.pixelSize: 19
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: height / 2
                            color: parent.hovered ? "#20ffffff" : "transparent"
                        }
                        Accessible.name: "Retry transcription with the same audio"
                        Accessible.description: workflow.language === "pt"
                            ? "Reenviar o mesmo áudio. Pode gerar outra cobrança."
                            : "Resend the same audio. May incur another charge."
                        onClicked: workflow.retryTranscription()
                    }
                    ToolButton {
                        objectName: "dismissFeedbackButton"
                        visible: !workflow.cancellationVisible
                        width: 32
                        height: 32
                        padding: 0
                        text: "×"
                        focusPolicy: Qt.NoFocus
                        contentItem: Item {
                            Rectangle {
                                anchors.centerIn: parent
                                width: 10; height: 1.5; radius: 0.75
                                color: theme.subtleText
                                rotation: 45
                                antialiasing: true
                            }
                            Rectangle {
                                anchors.centerIn: parent
                                width: 10; height: 1.5; radius: 0.75
                                color: theme.subtleText
                                rotation: -45
                                antialiasing: true
                            }
                        }
                        background: Rectangle {
                            radius: height / 2
                            color: parent.hovered ? "#20ffffff" : "transparent"
                        }
                        Accessible.name: workflow.language === "pt" ? "Fechar aviso" : "Close feedback"
                        onClicked: workflow.reset()
                    }
                }
            }
        }
    }
}
