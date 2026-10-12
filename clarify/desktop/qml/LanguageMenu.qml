import QtQuick
import QtQuick.Controls

Popup {
    id: menu
    required property Theme visualTheme
    required property var languages
    required property var languageNames
    property string selectedLanguage
    signal selected(string language)
    popupType: Popup.Window
    focus: false
    padding: 6
    width: 48
    implicitHeight: contentItem.implicitHeight + topPadding + bottomPadding
    margins: 8
    transformOrigin: Popup.Top
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

    function keepOpen() { closeTimer.stop() }
    function closeSoon() { closeTimer.restart() }
    onClosed: closeTimer.stop()
    Timer { id: closeTimer; interval: 180; onTriggered: menu.close() }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 180; easing.type: Easing.OutCubic }
            NumberAnimation { property: "scale"; from: 0.82; to: 1; duration: 220; easing.type: Easing.OutCubic }
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 130; easing.type: Easing.InCubic }
    }
    background: Rectangle {
        radius: 15
        color: menu.visualTheme.control
        border.color: menu.visualTheme.controlPressed
    }
    contentItem: Column {
        spacing: 3
        HoverHandler {
            onHoveredChanged: hovered ? menu.keepOpen() : menu.closeSoon()
        }
        Repeater {
            model: menu.languages
            AppButton {
                required property string modelData
                objectName: "languageOption_" + modelData
                theme: menu.visualTheme
                quiet: true
                checked: menu.selectedLanguage === modelData
                width: menu.availableWidth
                height: 30
                Accessible.name: menu.languageNames[modelData]
                Accessible.role: Accessible.RadioButton
                Accessible.checked: checked
                RoundedFlag {
                    anchors.centerIn: parent
                    width: 21.333; height: 16
                    displayScale: menu.visualTheme.uiScale
                    source: "flags/" + modelData + ".svg"
                }
                onClicked: {
                    menu.selected(modelData)
                    menu.close()
                }
            }
        }
    }
}
