import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

ColumnLayout {
    id: page
    required property Theme theme
    required property var settings
    signal connectProvider()
    spacing: 14
    property bool advanced: false
    function loadModels() { if (visible) settings.loadRouteModels() }
    onVisibleChanged: loadModels()
    Component.onCompleted: loadModels()
    Connections {
        target: settings
        function onRouteChanged() { page.loadModels() }
        function onProviderStateChanged() { page.loadModels() }
    }
    Label { text: "Choose your AI"; color: theme.text; font.pixelSize: 20; font.weight: Font.DemiBold }
    Label {
        Layout.fillWidth: true
        text: "Pick a task, then choose a model. Changes apply when you save."
        color: theme.subtleText; wrapMode: Text.WordWrap
    }
    GridLayout {
        Layout.fillWidth: true; columns: 2; columnSpacing: 16; rowSpacing: 10
        Label { text: "Task"; color: theme.secondaryText }
        SettingsComboBox {
            theme: page.theme
            id: scope; objectName: "workflowScopeBox"
            Layout.fillWidth: true; implicitHeight: 36
            model: [
                { id: "transcription", label: "Transcribe audio" },
                { id: "refinement", label: "Refine text" },
                { id: "rewrite", label: "Rewrite selected text" },
                { id: "translation", label: "Translate text" },
                { id: "local_asr_refinement", label: "Refine local transcription" }
            ]
            textRole: "label"; valueRole: "id"
            currentIndex: model.findIndex(function(item) { return item.id === settings.selectedScope })
            onActivated: settings.selectWorkflow(currentValue)
        }
        Label { text: "Provider"; color: theme.secondaryText }
        SettingsComboBox {
            theme: page.theme
            id: provider; objectName: "workflowProviderBox"
            Layout.fillWidth: true; implicitHeight: 36
            model: settings.providersForScope(settings.selectedScope).map(function(id) {
                return { id: id, label: settings.providerName(id) }
            })
            textRole: "label"; valueRole: "id"
            currentIndex: model.findIndex(function(item) { return item.id === settings.routeProviderId })
            onActivated: settings.setRouteProviderId(currentValue)
        }
    }
    LocalModelCard {
        Layout.fillWidth: true
        visible: settings.routeProviderId === "local_asr"
        theme: page.theme; settings: page.settings
    }
    ColumnLayout {
        Layout.fillWidth: true; spacing: 8
        visible: settings.routeProviderId !== "local_asr"
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Model"; color: theme.secondaryText }
            Item { Layout.fillWidth: true }
            AppButton {
                theme: page.theme; quiet: true; text: settings.routeModelStatus === "loading" ? "Loading…" : "Refresh list"
                enabled: settings.routeModelStatus !== "loading" && settings.routeModelStatus !== "not_configured"
                onClicked: settings.refreshRouteModels()
            }
        }
        TextField {
            id: search; objectName: "modelSearchField"
            property string previousProvider: settings.routeProviderId
            onPreviousProviderChanged: clear()
            Layout.fillWidth: true; implicitHeight: 36
            visible: settings.routeModelOptions.length > 6
            placeholderText: "Search available models"
            onVisibleChanged: if (!visible) text = ""
            Connections { target: settings; function onSelectedScopeChanged() { search.clear() } }
        }
        SettingsComboBox {
            theme: page.theme
            id: models; objectName: "workflowModelPicker"
            Layout.fillWidth: true; implicitHeight: 40
            textRole: "label"; valueRole: "id"
            model: settings.routeModelOptions.filter(function(item) {
                return !search.visible || item.label.toLowerCase().indexOf(search.text.toLowerCase()) !== -1
            })
            currentIndex: model.findIndex(function(item) { return item.id === settings.routeModelId })
            displayText: currentIndex >= 0 ? currentText : (settings.routeModelId || "Select a model")
            enabled: model.length > 0
            onActivated: settings.setRouteModelId(currentValue)
            Accessible.name: "Available models for this task"
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.subtleText
            text: {
                var status = settings.routeModelStatus
                if (status === "loading") return "Getting available models from your provider…"
                if (status === "not_configured") return "Connect this provider to see its available models."
                if (status === "error") return "Could not load models. Check your connection and provider settings, then retry. Your selection is unchanged."
                if (status === "empty") return "No compatible models returned. Check the provider or use a custom model in Advanced."
                if (status === "ready" && !settings.routeModelOptions.some(function(item) { return item.id === settings.routeModelId }))
                    return "Current model is not in this list. Choose an available model or keep your custom selection."
                if (models.count === 0 && search.text) return "No models match your search."
                return "Available models for this task. Access and pricing depend on your provider."
            }
        }
        AppButton {
            theme: page.theme
            visible: settings.routeModelStatus === "not_configured" || settings.routeModelStatus === "error"
            text: "Connect provider"
            onClicked: { settings.selectProvider(settings.routeProviderId); page.connectProvider() }
        }
    }
    AppButton {
        theme: page.theme; quiet: true; text: page.advanced ? "− Advanced" : "+ Advanced"
        onClicked: page.advanced = !page.advanced
        Accessible.name: "Show or hide advanced model settings"
    }
    ColumnLayout {
        visible: page.advanced; Layout.fillWidth: true; spacing: 8
        Label { text: "Custom model ID"; color: theme.secondaryText }
        TextField {
            objectName: "workflowModelField"; Layout.fillWidth: true
            text: settings.routeModelId
            enabled: settings.routeProviderId !== "local_asr"
            placeholderText: "For models not returned by the provider"
            onEditingFinished: settings.setRouteModelId(text)
        }
        Label { text: "Custom endpoint"; color: theme.secondaryText }
        TextField {
            objectName: "workflowEndpointField"; Layout.fillWidth: true
            text: settings.routeCustomEndpoint; placeholderText: "Use provider default"
            enabled: settings.routeProviderId !== "local_asr"
            onEditingFinished: settings.setRouteCustomEndpoint(text)
        }
        CheckBox {
            objectName: "workflowEnabledBox"; text: "Enable this task"
            checked: settings.routeEnabled; onToggled: settings.setRouteEnabled(checked)
        }
        Label { text: "Custom instruction"; color: theme.secondaryText }
        TextArea {
            objectName: "workflowPromptField"; Layout.fillWidth: true; Layout.preferredHeight: 80
            text: settings.routePrompt; placeholderText: "Optional instruction for this task"
            wrapMode: TextArea.Wrap; selectByMouse: true
            onEditingFinished: settings.setRoutePrompt(text)
        }
    }
}
