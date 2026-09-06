import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

ColumnLayout {
    id: page
    required property Theme theme
    required property var settings
    property bool advanced: false
    property bool confirmDisconnect: false
    signal modelSelected()
    spacing: 14
    Label { text: "Your connections"; color: theme.text; font.pixelSize: 20; font.weight: Font.DemiBold }
    Label {
        Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.subtleText
        text: "Connect a provider to browse its models, or use Local Whisper without an account."
    }
    SettingsComboBox {
        theme: page.theme
        id: provider; objectName: "onboardingProviderBox"
        Layout.fillWidth: true; implicitHeight: 36
        model: settings.providerIds.map(function(id) { return { id: id, label: settings.providerName(id) } })
        textRole: "label"; valueRole: "id"
        currentIndex: model.findIndex(function(item) { return item.id === settings.selectedProviderId })
        onActivated: { page.confirmDisconnect = false; settings.selectProvider(currentValue) }
    }
    LocalModelCard {
        Layout.fillWidth: true; visible: settings.selectedProviderId === "local_asr"
        theme: page.theme; settings: page.settings
        onModelSelected: page.modelSelected()
    }
    ColumnLayout {
        Layout.fillWidth: true; spacing: 12; visible: settings.selectedProviderId !== "local_asr"
        Label { text: "API key"; color: theme.secondaryText }
        TextField {
            id: key; objectName: "providerApiKeyField"
            Layout.fillWidth: true; implicitHeight: 38
            text: settings.providerApiKey; echoMode: TextInput.Password; selectByMouse: true
            enabled: !settings.providerBusy
            placeholderText: settings.providerHasApiKey ? "Key saved securely · leave blank to keep it" : "Paste your API key"
            onEditingFinished: settings.setProviderApiKey(text)
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.subtleText
            text: settings.providerBusy ? "Checking access and loading models…"
                : settings.providerStatus === "active" ? "Connected. Your models are available in Models."
                : settings.providerStatus === "error" ? "Connection failed. Check your key and endpoint, then retry."
                : settings.providerHasApiKey ? "A key is saved. Connect to check access again."
                : "Your key is stored securely on this computer. Connecting saves it immediately."
        }
        RowLayout {
            Layout.fillWidth: true
            AppButton {
                theme: page.theme; primary: true; implicitHeight: 36
                text: settings.providerBusy ? "Connecting…" : "Connect & save key"
                enabled: !settings.providerBusy && (key.text.trim() !== "" || settings.providerHasApiKey)
                onClicked: {
                    settings.setProviderApiKey(key.text)
                    settings.setProviderBaseUrl(endpoint.text)
                    settings.validateProvider()
                }
            }
            Item { Layout.fillWidth: true }
            AppButton {
                theme: page.theme; quiet: true; text: "Disconnect…"
                visible: settings.providerHasApiKey; enabled: !settings.providerBusy
                onClicked: page.confirmDisconnect = !page.confirmDisconnect
            }
        }
        ColumnLayout {
            visible: page.confirmDisconnect; Layout.fillWidth: true
            Label {
                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.secondaryText
                text: "Remove the saved key? Tasks using this provider will need another connection."
            }
            RowLayout {
                AppButton { theme: page.theme; text: "Keep connection"; onClicked: page.confirmDisconnect = false }
                AppButton { theme: page.theme; text: "Remove key"; onClicked: { settings.clearProvider(); page.confirmDisconnect = false } }
            }
        }
        AppButton {
            theme: page.theme; quiet: true; text: page.advanced ? "− Advanced" : "+ Advanced"
            onClicked: page.advanced = !page.advanced
        }
        ColumnLayout {
            visible: page.advanced; Layout.fillWidth: true
            Label { text: "Provider endpoint"; color: theme.secondaryText }
            TextField {
                id: endpoint; objectName: "providerBaseUrlField"
                Layout.fillWidth: true; implicitHeight: 36
                text: settings.providerBaseUrl; selectByMouse: true
                enabled: settings.providerSupportsCustomEndpoint && !settings.providerBusy
                onEditingFinished: settings.setProviderBaseUrl(text)
            }
        }
    }
}
