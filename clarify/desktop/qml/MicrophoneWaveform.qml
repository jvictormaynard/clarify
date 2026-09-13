import QtQuick 6.5
import QtQuick.Controls 6.5

Rectangle {
    id: wave
    required property Theme visualTheme
    property real level: 0
    property bool running: false
    property var samples: []
    readonly property int sampleCount: 64
    implicitHeight: 64
    radius: visualTheme.fieldRadius
    color: visualTheme.control
    border.color: visualTheme.border
    Accessible.role: Accessible.Indicator
    Accessible.name: "Live microphone input"
    Accessible.description: running ? "Listening to the selected microphone" : "Microphone test stopped"

    function clear() {
        samples = Array(sampleCount).fill(0)
        plot.requestPaint()
    }
    Component.onCompleted: clear()
    onRunningChanged: clear()
    Canvas {
        id: plot
        anchors.fill: parent
        anchors.margins: 10
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            ctx.strokeStyle = wave.visualTheme.secondaryText
            ctx.lineWidth = 2
            ctx.lineCap = "round"
            var step = width / wave.sampleCount
            ctx.beginPath()
            for (var i = 0; i < wave.samples.length; i++) {
                var amplitude = Math.max(0.5, wave.samples[i] * (height / 2 - 2))
                var x = step * (i + 0.5)
                ctx.moveTo(x, height / 2 - amplitude)
                ctx.lineTo(x, height / 2 + amplitude)
            }
            ctx.stroke()
        }
    }
    Timer {
        interval: 40
        repeat: true
        running: wave.running && wave.visible
        onTriggered: {
            var next = wave.samples.slice(1)
            next.push(Math.max(0, Math.min(1, wave.level)))
            wave.samples = next
            plot.requestPaint()
        }
    }
}
