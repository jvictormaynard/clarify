import QtQuick 6.5

Item {
    id: flagFrame
    property alias source: artwork.source
    property real displayScale: 1
    implicitWidth: 24
    implicitHeight: 18

    Image {
        id: artwork
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        // Rasterize the vector once at display density, including shell scale.
        sourceSize.width: Math.ceil(width * Screen.devicePixelRatio * flagFrame.displayScale)
        sourceSize.height: Math.ceil(height * Screen.devicePixelRatio * flagFrame.displayScale)
    }
}
