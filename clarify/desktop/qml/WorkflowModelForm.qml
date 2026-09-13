import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

ColumnLayout {
    id: form
    required property Theme visualTheme
    required property var settingsController
    property string enabledLabel: "Enable this task"
    property bool advancedExpanded: false
    signal connectProvider()
    signal manageLocalModels()
    spacing: 12
    Connections {
        target: form.settingsController
        function onSelectedScopeChanged() { form.advancedExpanded = false }
    }
    SettingsRow {
        Layout.fillWidth: true
        visualTheme: form.visualTheme
        title: form.enabledLabel
        Item { Layout.fillWidth: true }
        SettingsSwitch {
            objectName: "workflowEnabledBox"
            visualTheme: form.visualTheme
            checked: settingsController.routeEnabled && (settingsController.selectedScope !== "local_asr_refinement" || settingsController.localAsrCloudRefinement)
            onToggled: {
                // Both setters notify bindings synchronously. Keep the user's
                // choice stable while updating the two compatibility fields.
                var requestedEnabled = checked
                if (settingsController.selectedScope === "local_asr_refinement")
                    settingsController.setLocalAsrCloudRefinement(requestedEnabled)
                settingsController.setRouteEnabled(requestedEnabled)
            }
            Accessible.name: form.enabledLabel
        }
    }
    SettingsRow {
        Layout.fillWidth: true
        visualTheme: form.visualTheme
        title: "Service"
        SearchSelect {
            objectName: "workflowProviderBox"
            Layout.fillWidth: true
            visualTheme: form.visualTheme
            options: settingsController.providersForScope(settingsController.selectedScope).map(function(id) {
                return { id: id, label: settingsController.providerName(id) }
            })
            value: settingsController.routeProviderId
            caption: "Choose a service"
            searchable: false
            onActivated: function(value) { settingsController.setRouteProviderId(value) }
        }
    }
    SettingsRow {
        Layout.fillWidth: true
        visualTheme: form.visualTheme
        title: "Model"
        ModelPicker {
            Layout.fillWidth: true
            visualTheme: form.visualTheme
            settingsController: form.settingsController
            onConnectProvider: form.connectProvider()
            onModelIdRequested: {
                form.advancedExpanded = true
                Qt.callLater(function() { manualModel.forceActiveFocus(); manualModel.selectAll() })
            }
        }
    }
    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: form.visualTheme.border }
    AppButton {
        id: advanced
        theme: form.visualTheme
        quiet: true
        objectName: "workflowAdvancedToggle"
        Layout.fillWidth: true; implicitHeight: 28
        hoverEnabled: true
        onClicked: form.advancedExpanded = !form.advancedExpanded
        Accessible.name: "Advanced model settings"
        contentItem: Label {
            text: "Advanced"; color: advanced.hovered ? form.visualTheme.text : form.visualTheme.subtleText
            font.pixelSize: 11; verticalAlignment: Text.AlignVCenter
        }
        DropdownIndicator {
            anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
            rotation: form.advancedExpanded ? 180 : 0
            Behavior on rotation { NumberAnimation { duration: 100 } }
        }
    }
    ColumnLayout {
        visible: form.advancedExpanded
        Layout.fillWidth: true; spacing: 12
        ColumnLayout {
            Layout.fillWidth: true; spacing: 6
            visible: settingsController.routeProviderId !== "local_asr"
            Label { text: "Model ID"; color: form.visualTheme.secondaryText; font.pixelSize: 11 }
            SettingsField {
                id: manualModel
                objectName: "workflowModelField"
                Layout.fillWidth: true
                visualTheme: form.visualTheme
                text: settingsController.routeModelId
                placeholderText: "For models not listed by your service"
                onEditingFinished: settingsController.setRouteModelId(text)
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 6
            visible: settingsController.routeProviderId !== "local_asr"
            Label { text: "Custom endpoint"; color: form.visualTheme.secondaryText; font.pixelSize: 11 }
            SettingsField {
                objectName: "workflowEndpointField"
                Layout.fillWidth: true
                visualTheme: form.visualTheme
                text: settingsController.routeCustomEndpoint
                placeholderText: "Use the service default"
                onEditingFinished: settingsController.setRouteCustomEndpoint(text)
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 6
            Label { text: "Instructions"; color: form.visualTheme.secondaryText; font.pixelSize: 11 }
            ScrollView {
                Layout.fillWidth: true; Layout.preferredHeight: 96
                clip: true
                SettingsArea {
                    id: prompt
                    visualTheme: form.visualTheme
                    objectName: "workflowPromptField"
                    width: parent.width
                    text: settingsController.routePrompt
                    placeholderText: "Optional instructions for this task"
                    Accessible.name: "Task instructions"
                    onEditingFinished: settingsController.setRoutePrompt(text)
                }
            }
        }
    }
}
