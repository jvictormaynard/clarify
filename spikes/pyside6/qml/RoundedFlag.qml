import QtQuick 6.5

Item {
    id: flagFrame
    property url source

    implicitWidth: 24
    implicitHeight: 18

    // Canvas clipping also works without GPU shader effects. Supersampling
    // keeps the small SVG and its transparent corners smooth at display scale.
    Canvas {
        id: artwork
        width: flagFrame.width * 4
        height: flagFrame.height * 4
        scale: 0.25
        transformOrigin: Item.TopLeft
        smooth: true
        property url loadedSource: ""
        property url imageSource: flagFrame.source
        onAvailableChanged: {
            if (available && imageSource.toString() !== "") {
                loadImage(imageSource)
                requestPaint()
            }
        }
        onImageSourceChanged: {
            if (loadedSource.toString() !== "") unloadImage(loadedSource)
            loadedSource = imageSource
            if (loadedSource.toString() !== "") loadImage(loadedSource)
            requestPaint()
        }
        onImageLoaded: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)
            if (!isImageLoaded(imageSource)) return
            var r = 12 // 3 display pixels
            ctx.beginPath()
            ctx.moveTo(r, 0)
            ctx.lineTo(width - r, 0)
            ctx.quadraticCurveTo(width, 0, width, r)
            ctx.lineTo(width, height - r)
            ctx.quadraticCurveTo(width, height, width - r, height)
            ctx.lineTo(r, height)
            ctx.quadraticCurveTo(0, height, 0, height - r)
            ctx.lineTo(0, r)
            ctx.quadraticCurveTo(0, 0, r, 0)
            ctx.closePath()
            ctx.clip()
            ctx.drawImage(imageSource, 0, 0, width, height)
        }
    }
}
