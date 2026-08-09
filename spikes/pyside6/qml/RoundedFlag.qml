import QtQuick 6.5

Rectangle {
    id: flagFrame
    property url source

    implicitWidth: 20
    implicitHeight: 14
    color: "transparent"
    radius: 4
    clip: true
    border.width: 0

    Image {
        anchors.fill: parent
        anchors.margins: 1
        source: flagFrame.source
        sourceSize.width: 40
        sourceSize.height: 28
        fillMode: Image.Stretch
        smooth: true
        mipmap: true
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        radius: flagFrame.radius
        border.width: 1
        border.color: "#2a2a2a"
    }
}
