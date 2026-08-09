import QtQuick 6.5

Rectangle {
    id: flagFrame
    property url source

    implicitWidth: 20
    implicitHeight: 14
    color: "transparent"
    radius: 3
    clip: true
    border.width: 1
    border.color: "#2a2a2a"

    Image {
        anchors.fill: parent
        source: flagFrame.source
        sourceSize.width: 40
        sourceSize.height: 28
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
    }
}
