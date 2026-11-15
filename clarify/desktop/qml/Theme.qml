import QtQuick 6.5

QtObject {
    // Keep these values aligned with compact black-and-white shell.
    readonly property color card: "#0a0a0a"
    readonly property color border: "#1c1c1c"
    readonly property color text: "#ffffff"
    readonly property color secondaryText: "#cccccc"
    property color dim: "#666666"
    readonly property color control: "#151515"
    readonly property color controlHover: "#222222"
    readonly property color controlPressed: "#2b2b2b"
    readonly property color controlDisabled: "#101010"
    readonly property color subtleText: "#8a8a8a"

    property int fieldHeight: 34
    readonly property int fieldRadius: 8
    property int fieldFontSize: 11
    readonly property int panelWidth: 520
    readonly property int panelHeight: 430
    readonly property int fadeDuration: 180
    readonly property real uiScale: 1.1
}
