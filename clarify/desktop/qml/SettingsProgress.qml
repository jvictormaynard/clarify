import QtQuick 6.5
import QtQuick.Controls 6.5

ProgressBar {
    id: control
    required property Theme visualTheme
    implicitHeight: 6
    padding: 0
    background: Rectangle {
        radius: 3
        color: control.visualTheme.controlPressed
    }
    contentItem: Item {
        clip: true
        Rectangle {
            width: control.indeterminate ? parent.width * 0.3 : parent.width * control.visualPosition
            height: parent.height
            radius: 3
            color: control.visualTheme.secondaryText
            x: control.indeterminate ? (parent.width - width) * sweep.position : 0
            QtObject { id: sweep; property real position: 0 }
            SequentialAnimation {
                running: control.visible && control.indeterminate
                loops: Animation.Infinite
                NumberAnimation { target: sweep; property: "position"; from: 0; to: 1; duration: 900; easing.type: Easing.InOutSine }
                NumberAnimation { target: sweep; property: "position"; from: 1; to: 0; duration: 900; easing.type: Easing.InOutSine }
            }
        }
    }
}
