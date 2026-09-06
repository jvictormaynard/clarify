import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Button {
    id: control
    required property Theme visualTheme
    property var options: []
    property string value: ""
    property string placeholderText: "Select an option"
    property string searchPlaceholder: "Search"
    property string caption: "Choose an option"
    property string statusText: ""
    property string secondaryActionText: ""
    property bool searchable: true
    property bool refreshable: false
    property bool busy: false
    readonly property int count: filteredOptions.length
    readonly property bool popupVisible: menu.visible
    readonly property real sceneScale: width > 0
        ? (mapToItem(null, width, 0).x - mapToItem(null, 0, 0).x) / width : 1
    readonly property var filteredOptions: options.filter(function(item) {
        var query = search.text.trim().toLowerCase()
        return !query || item.label.toLowerCase().indexOf(query) >= 0 || item.id.toLowerCase().indexOf(query) >= 0
    })
    readonly property string selectedLabel: {
        var selected = options.find(function(item) { return item.id === control.value })
        return selected ? selected.label : value
    }
    readonly property string selectedIcon: {
        var selected = options.find(function(item) { return item.id === control.value })
        return selected && selected.icon ? selected.icon : ""
    }
    signal activated(string value)
    signal refreshRequested()
    signal secondaryRequested()
    implicitHeight: visualTheme.fieldHeight
    hoverEnabled: true
    leftPadding: 11; rightPadding: 34
    topPadding: 0; bottomPadding: 0
    Accessible.name: caption
    Accessible.role: Accessible.ComboBox
    Accessible.description: selectedLabel || placeholderText
    onClicked: menu.visible ? menu.close() : menu.open()
    Keys.onDownPressed: menu.open()
    contentItem: RowLayout {
        spacing: 8
        RoundedFlag {
            visible: control.selectedIcon !== ""
            source: control.selectedIcon
            Layout.preferredWidth: implicitWidth; Layout.preferredHeight: implicitHeight
            Layout.alignment: Qt.AlignVCenter
        }
        Label {
            Layout.fillWidth: true
            Layout.fillHeight: true
            padding: 0
            text: control.selectedLabel || control.placeholderText
            color: !control.enabled ? control.visualTheme.dim
                : control.selectedLabel ? control.visualTheme.text : control.visualTheme.subtleText
            font.pixelSize: Math.max(12, control.visualTheme.fieldFontSize)
            font.preferTypoLineMetrics: true
            verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        }
    }
    DropdownIndicator {
        anchors.right: parent.right; anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        rotation: menu.visible ? 180 : 0
        Behavior on rotation { NumberAnimation { duration: 100 } }
    }
    background: Rectangle {
        radius: control.visualTheme.fieldRadius
        color: !control.enabled ? control.visualTheme.controlDisabled
            : control.hovered || control.down || control.activeFocus || menu.visible
              ? control.visualTheme.controlHover : control.visualTheme.control
        border.color: control.visualTheme.border
        Behavior on border.color { ColorAnimation { duration: 100 } }
    }
    function choose(index) {
        if (index >= 0 && index < filteredOptions.length) {
            activated(filteredOptions[index].id)
            menu.close()
        }
    }
    function moveSelection(delta) {
        results.currentIndex = Math.max(0, Math.min(filteredOptions.length - 1, results.currentIndex + delta))
        results.positionViewAtIndex(results.currentIndex, ListView.Contain)
    }
    onFilteredOptionsChanged: results.currentIndex = filteredOptions.length ? 0 : -1
    onVisibleChanged: if (!visible) menu.close()
    onEnabledChanged: if (!enabled) menu.close()
    Popup {
        id: menu
        objectName: control.objectName + "Popup"
        width: control.width
        scale: control.sceneScale
        transformOrigin: Popup.TopLeft
        y: control.height + 5
        padding: 6
        margins: 10
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: {
            search.clear()
            var selected = control.filteredOptions.findIndex(function(item) { return item.id === control.value })
            results.currentIndex = selected >= 0 ? selected : (control.count ? 0 : -1)
            results.positionViewAtIndex(results.currentIndex, ListView.Contain)
            if (control.searchable) search.forceActiveFocus()
            else results.forceActiveFocus()
        }
        onClosed: if (control.visible && control.enabled) control.forceActiveFocus()
        background: Rectangle {
            color: control.visualTheme.control
            border.color: control.visualTheme.controlPressed
            radius: 10
        }
        contentItem: ColumnLayout {
            spacing: 6
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                SettingsField {
                    id: search
                    objectName: control.objectName + "Search"
                    visualTheme: control.visualTheme
                    Layout.fillWidth: true
                    visible: control.searchable
                    placeholderText: control.searchPlaceholder
                    Accessible.name: control.searchPlaceholder
                    Keys.onShortcutOverride: function(event) { if (event.key === Qt.Key_Escape) event.accepted = true }
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_Down) control.moveSelection(1)
                        else if (event.key === Qt.Key_Up) control.moveSelection(-1)
                        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) control.choose(results.currentIndex)
                        else if (event.key === Qt.Key_Escape) menu.close()
                        else if (event.key === Qt.Key_Home && text === "") results.currentIndex = 0
                        else if (event.key === Qt.Key_End && text === "") results.currentIndex = control.count - 1
                        else return
                        event.accepted = true
                    }
                }
                Label {
                    Layout.fillWidth: true; Layout.margins: 5
                    visible: !control.searchable
                    text: control.caption; color: control.visualTheme.subtleText; font.pixelSize: 10
                }
                AppButton {
                    objectName: control.objectName + "Refresh"
                    theme: control.visualTheme; quiet: true
                    visible: control.refreshable; enabled: !control.busy
                    iconSource: "icons/refresh.svg"
                    iconSize: 16
                    Layout.preferredWidth: 34; Layout.preferredHeight: 34
                    Accessible.name: "Refresh list"
                    ToolTip.visible: hovered
                    ToolTip.delay: 600
                    ToolTip.text: control.busy ? "Updating list…" : "Refresh list"
                    Keys.onShortcutOverride: function(event) { if (event.key === Qt.Key_Escape) event.accepted = true }
                    Keys.onEscapePressed: menu.close()
                    onClicked: {
                        control.refreshRequested()
                        if (control.searchable) search.forceActiveFocus()
                    }
                }
            }
            Label {
                Layout.fillWidth: true; Layout.margins: 6
                visible: control.statusText !== "" || control.count === 0
                text: control.statusText || (search.text ? "No matching results" : "No options available")
                wrapMode: Text.WordWrap; color: control.visualTheme.subtleText; font.pixelSize: 11
            }
            ListView {
                id: results
                objectName: control.objectName + "Results"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(contentHeight, 210)
                clip: true
                model: control.filteredOptions
                keyNavigationEnabled: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                Keys.onShortcutOverride: function(event) { if (event.key === Qt.Key_Escape) event.accepted = true }
                Keys.onReturnPressed: control.choose(currentIndex)
                Keys.onEnterPressed: control.choose(currentIndex)
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_Home) currentIndex = control.count ? 0 : -1
                    else if (event.key === Qt.Key_End) currentIndex = control.count - 1
                    else return
                    positionViewAtIndex(currentIndex, ListView.Contain)
                    event.accepted = true
                }
                Keys.onEscapePressed: menu.close()
                delegate: ItemDelegate {
                    id: option
                    required property var modelData
                    required property int index
                    width: results.width; height: 32
                    leftPadding: 10; rightPadding: 32
                    topPadding: 0; bottomPadding: 0
                    hoverEnabled: true
                    highlighted: results.currentIndex === index
                    onClicked: control.choose(index)
                    Accessible.name: modelData.label + (modelData.id === control.value ? ", selected" : "")
                    contentItem: RowLayout {
                        spacing: 8
                        RoundedFlag {
                            visible: Boolean(option.modelData.icon)
                            source: option.modelData.icon || ""
                            Layout.preferredWidth: implicitWidth; Layout.preferredHeight: implicitHeight
                            Layout.alignment: Qt.AlignVCenter
                        }
                        Label {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            padding: 0
                            text: option.modelData.label; color: control.visualTheme.text
                            font.pixelSize: Math.max(12, control.visualTheme.fieldFontSize)
                            font.preferTypoLineMetrics: true
                            elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                        }
                    }
                    Canvas {
                        visible: option.modelData.id === control.value
                        anchors.right: parent.right; anchors.rightMargin: 11
                        anchors.verticalCenter: parent.verticalCenter
                        width: 12; height: 10
                        onPaint: {
                            var context = getContext("2d")
                            context.strokeStyle = control.visualTheme.secondaryText
                            context.lineWidth = 1.5
                            context.beginPath(); context.moveTo(1, 5); context.lineTo(4, 8); context.lineTo(11, 1); context.stroke()
                        }
                    }
                    background: Rectangle {
                        radius: 6
                        color: option.highlighted || option.hovered ? control.visualTheme.controlHover : "transparent"
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: 1
                visible: control.secondaryActionText !== ""
                color: control.visualTheme.border
            }
            RowLayout {
                visible: control.secondaryActionText !== ""
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                AppButton {
                    objectName: control.objectName + "Secondary"
                    theme: control.visualTheme; quiet: true
                    text: control.secondaryActionText
                    visible: text !== ""
                    Layout.preferredWidth: 132; Layout.preferredHeight: 28
                    contentItem: Label {
                        text: parent.text; color: control.visualTheme.subtleText; font.pixelSize: 11
                        verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter
                    }
                    onClicked: { menu.close(); control.secondaryRequested() }
                }
            }
        }
    }
}
