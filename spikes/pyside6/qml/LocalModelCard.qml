import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Pane {
    id: card
    required property Theme theme
    required property var settings
    signal modelSelected()
    property bool confirmRemoval: false
    padding: 16
    background: Rectangle { color: theme.control; radius: 12; border.color: theme.border }
    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Label { text: settings.localProfiles[settings.localProfileIndex]; color: theme.text; font.pixelSize: 17; font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            Label { text: settings.localAsrStatus === "installed" ? "Ready · On device" : "On device"; color: theme.secondaryText }
        }
        LocalOptionCombo {
            visualTheme: card.theme
            palette.text: theme.text
            palette.buttonText: theme.text
            palette.button: theme.control
            palette.base: theme.control
            palette.window: theme.card
            objectName: "localProfileSelector"
            Layout.fillWidth: true
            model: settings.localProfiles
            currentIndex: settings.localProfileIndex
            enabled: !settings.localBenchmarkBusy && !settings.localAsrBusy
            Accessible.name: "Local model profile"
            onActivated: { card.confirmRemoval = false; settings.selectLocalProfile(currentIndex) }
        }
        LocalOptionCombo {
            visualTheme: card.theme
            palette.text: theme.text
            palette.buttonText: theme.text
            palette.button: theme.control
            palette.base: theme.control
            palette.window: theme.card
            objectName: "localDeviceSelector"
            Layout.fillWidth: true
            model: settings.localDevices
            currentIndex: settings.localDeviceIndex
            enabled: !settings.localBenchmarkBusy && !settings.localAsrBusy
            Accessible.name: "Local processing device"
            onActivated: { card.confirmRemoval = false; settings.selectLocalDevice(currentIndex) }
        }
        AppButton {
            theme: card.theme
            Layout.preferredHeight: 30
            Layout.preferredWidth: 190
            palette.text: theme.text
            palette.buttonText: theme.text
            palette.button: theme.control
            palette.base: theme.control
            palette.window: theme.card
            text: settings.localBenchmarkBusy ? "Cancel measurement" : "Measure CPU/GPU speed"
            enabled: !settings.localAsrBusy
            onClicked: settings.localBenchmarkBusy ? settings.cancelLocalMeasurement() : settings.measureLocalDevice()
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.secondaryText
            text: settings.localBenchmarkDetail
            visible: text.length > 0
        }
        CheckBox {
            id: streamCheck
            Layout.fillWidth: true
            implicitHeight: 36
            contentItem: Text {
                text: streamCheck.text; color: theme.secondaryText
                leftPadding: 28; verticalAlignment: Text.AlignVCenter
                wrapMode: Text.WordWrap; font.pixelSize: 11
            }
            indicator: Rectangle {
                width: 16; height: 16; y: (streamCheck.height - height) / 2
                radius: 3; color: streamCheck.checked ? theme.text : theme.control
                border.color: theme.secondaryText
                Rectangle { anchors.centerIn: parent; width: 8; height: 8; color: theme.card; visible: streamCheck.checked }
            }
            palette.text: theme.text
            palette.buttonText: theme.text
            palette.button: theme.control
            palette.base: theme.control
            palette.window: theme.card
            objectName: "localStreamingSwitch"
            text: "Process pauses while recording (experimental)"
            checked: settings.localStreaming
            onToggled: settings.setLocalStreaming(checked)
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.secondaryText
            font.pixelSize: 10
            text: "Base uses less memory. Medium needs more memory and time. Accuracy depends on your language and audio. CUDA requires a compatible NVIDIA GPU."
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.secondaryText
            font.pixelSize: 10
            visible: settings.localDeviceIndex > 1
            textFormat: Text.RichText
            text: 'Optional runtime: <a href="https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html">NVIDIA CUDA terms</a>'
            onLinkActivated: function(link) { Qt.openUrlExternally(link) }
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.secondaryText
            text: "Transcribe on your computer. No API key. Download once, then use offline."
        }
        Flow {
            Layout.fillWidth: true; spacing: 8
            Repeater {
                model: settings.localAsrRequirementsList.slice(0, 3)
                Label {
                    required property string modelData
                    text: modelData; color: theme.secondaryText; padding: 7
                    background: Rectangle { color: theme.card; radius: 6 }
                }
            }
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.subtleText
            text: settings.localAsrRequirementsList.slice(3).filter(Boolean).join("\n")
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.secondaryText
            visible: settings.localAsrBusy
            text: settings.localAsrStep
        }
        ProgressBar {
            Layout.fillWidth: true; visible: settings.localAsrBusy
            value: settings.localAsrProgress
            indeterminate: settings.localAsrProgress <= 0
            Accessible.name: "Current installation step progress"
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.secondaryText
            visible: !settings.localAsrBusy && settings.localAsrStatus !== "installed"
            text: !settings.localAsrCanInstall ? "Local installation requires Windows x64."
                : settings.localAsrStatus === "cancelled" ? "Download cancelled. You can try again."
                : settings.localAsrStatus === "error" || settings.localAsrStatus === "invalid"
                  ? "Installation needs attention. " + settings.localAsrDetail
                  : "The download starts only when you choose Install."
        }
        RowLayout {
            Layout.fillWidth: true
            AppButton {
                objectName: "localInstallButton"
                theme: card.theme; primary: true; implicitHeight: 36
                text: settings.localAsrStatus === "installed" ? "Use this model"
                    : settings.localAsrStatus === "error" || settings.localAsrStatus === "invalid" ? "Retry installation" : "Install model"
                enabled: !settings.localBenchmarkBusy && !settings.localAsrBusy && settings.localAsrCanInstall
                onClicked: {
                    if (settings.localAsrStatus === "installed") {
                        if (settings.useLocalAsr()) card.modelSelected()
                    } else settings.installLocalAsr()
                }
            }
            AppButton {
                objectName: "localCancelButton"
                theme: card.theme; visible: settings.localAsrBusy; text: "Cancel"
                onClicked: settings.cancelLocalAsr()
            }
            Item { Layout.fillWidth: true }
            AppButton {
                objectName: "localRemoveButton"
                theme: card.theme; quiet: true; text: "Remove…"
                visible: settings.localAsrStatus === "installed" && !settings.localAsrBusy
                onClicked: card.confirmRemoval = !card.confirmRemoval
            }
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.subtleText
            visible: settings.localAsrStatus === "installed"
            text: settings.routeProviderId === "local_asr" && settings.selectedScope === "transcription" && settings.routeModelId === ["ggml-base", "ggml-small", "ggml-medium"][settings.localProfileIndex]
                ? "Selected for transcription. Save settings to apply."
                : "Use this model selects it for transcription. Save settings to apply."
        }
        ColumnLayout {
            Layout.fillWidth: true; visible: card.confirmRemoval && settings.localAsrStatus === "installed"
            Label {
                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.text
                text: "Remove downloaded files? Local transcription will stop working until you install them again."
            }
            RowLayout {
                AppButton { objectName: "localKeepButton"; theme: card.theme; text: "Keep model"; onClicked: card.confirmRemoval = false }
                AppButton { objectName: "localConfirmRemoveButton"; theme: card.theme; text: "Remove files"; onClicked: { card.confirmRemoval = false; settings.removeLocalAsr() } }
            }
        }
        CheckBox {
            palette.text: theme.text
            palette.buttonText: theme.text
            palette.button: theme.control
            palette.base: theme.control
            palette.window: theme.card
            text: "Allow cloud refinement (sends transcript to provider)"
            visible: settings.localAsrStatus === "installed"
            checked: settings.localAsrCloudRefinement
            onToggled: settings.setLocalAsrCloudRefinement(checked)
        }
    }
}
