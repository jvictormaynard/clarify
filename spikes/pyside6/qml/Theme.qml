import QtQuick 6.5

QtObject {
    // Keep these values aligned with compact black-and-white shell.
    readonly property color card: "#0a0a0a"
    readonly property color resultSurface: "#050505"
    readonly property color border: "#1c1c1c"
    readonly property color text: "#ffffff"
    readonly property color secondaryText: "#cccccc"
    readonly property color dim: "#666666"
    readonly property color control: "#151515"
    readonly property color controlHover: "#222222"
    readonly property color controlPressed: "#2b2b2b"
    readonly property color controlDisabled: "#101010"
    readonly property color subtleText: "#8a8a8a"
    readonly property color transparentKey: "#010101"

    readonly property int pillRadius: 24
    readonly property int panelRadius: 18
    readonly property int controlRadius: 13
    readonly property int controlHeight: 26
    readonly property int fieldHeight: 34
    readonly property int fieldRadius: 8
    readonly property int fieldFontSize: 11
    readonly property int windowWidth: 380
    readonly property int windowHeight: 48
    readonly property int resultWidth: 400
    readonly property int resultHeight: 148
    readonly property int panelWidth: 520
    readonly property int panelHeight: 430
    readonly property int settingsWidth: 720
    readonly property int settingsHeight: 540
    readonly property int fadeDuration: 180
    readonly property real uiScale: 1.1
}
