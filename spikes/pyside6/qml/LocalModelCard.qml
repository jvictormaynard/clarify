import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Pane {
    id: card
    required property Theme visualTheme
    required property var settingsController
    signal modelSelected()
    property bool confirmRemoval: false
    padding: 0
    topPadding: 12
    background: null
    contentItem: ColumnLayout {
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            Label { text: settingsController.localProfiles[settingsController.localProfileIndex]; color: visualTheme.text; font.pixelSize: 12; font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            Label { text: settingsController.localAsrStatus === "installed" ? "Ready · On device" : "On device"; color: visualTheme.secondaryText }
        }
        LocalOptionCombo {
            visualTheme: card.visualTheme
            palette.text: visualTheme.text
            palette.buttonText: visualTheme.text
            palette.button: visualTheme.control
            palette.base: visualTheme.control
            palette.window: visualTheme.card
            objectName: "localProfileSelector"
            Layout.fillWidth: true
            model: settingsController.localProfiles
            currentIndex: settingsController.localProfileIndex
            enabled: !settingsController.localBenchmarkBusy && !settingsController.localAsrBusy
            Accessible.name: "Local model profile"
            onActivated: { card.confirmRemoval = false; settingsController.selectLocalProfile(currentIndex) }
        }
        LocalOptionCombo {
            visualTheme: card.visualTheme
            palette.text: visualTheme.text
            palette.buttonText: visualTheme.text
            palette.button: visualTheme.control
            palette.base: visualTheme.control
            palette.window: visualTheme.card
            objectName: "localDeviceSelector"
            Layout.fillWidth: true
            model: settingsController.localDevices
            currentIndex: settingsController.localDeviceIndex
            enabled: !settingsController.localBenchmarkBusy && !settingsController.localAsrBusy
            Accessible.name: "Local processing device"
            onActivated: { card.confirmRemoval = false; settingsController.selectLocalDevice(currentIndex) }
        }
        AppButton {
            theme: card.visualTheme
            Layout.preferredHeight: 30
            Layout.preferredWidth: 190
            palette.text: visualTheme.text
            palette.buttonText: visualTheme.text
            palette.button: visualTheme.control
            palette.base: visualTheme.control
            palette.window: visualTheme.card
            text: settingsController.localBenchmarkBusy ? "Cancel measurement" : "Optimize CPU/GPU"
            enabled: !settingsController.localAsrBusy
            onClicked: settingsController.localBenchmarkBusy ? settingsController.cancelLocalMeasurement() : settingsController.installLocalAsr()
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.secondaryText
            text: settingsController.localBenchmarkDetail
            visible: text.length > 0
        }
        CheckBox {
            id: streamCheck
            Layout.fillWidth: true
            implicitHeight: 36
            contentItem: Text {
                text: streamCheck.text; color: visualTheme.secondaryText
                leftPadding: 28; verticalAlignment: Text.AlignVCenter
                wrapMode: Text.WordWrap; font.pixelSize: 11
            }
            indicator: Rectangle {
                width: 16; height: 16; y: (streamCheck.height - height) / 2
                radius: 3; color: streamCheck.checked ? visualTheme.text : visualTheme.control
                border.color: visualTheme.secondaryText
                Rectangle { anchors.centerIn: parent; width: 8; height: 8; color: visualTheme.card; visible: streamCheck.checked }
            }
            palette.text: visualTheme.text
            palette.buttonText: visualTheme.text
            palette.button: visualTheme.control
            palette.base: visualTheme.control
            palette.window: visualTheme.card
            objectName: "localStreamingSwitch"
            text: "Process pauses while recording (experimental)"
            checked: settingsController.localStreaming
            onToggled: settingsController.setLocalStreaming(checked)
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.secondaryText
            font.pixelSize: 10
            text: "Base uses less memory. Medium needs more memory and time. Accuracy depends on your language and audio. CUDA requires a compatible NVIDIA GPU."
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.secondaryText
            font.pixelSize: 10
            visible: settingsController.localDevices.length > 2
            textFormat: Text.RichText
            text: 'Optional runtime: <a href="https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html">NVIDIA CUDA terms</a>'
            onLinkActivated: function(link) { Qt.openUrlExternally(link) }
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.secondaryText
            font.pixelSize: 11
            text: "Transcribe on your computer. No API key. One model for CPU and compatible NVIDIA GPU. Installation measures speed; Automatic uses the fastest device."
        }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font.pixelSize: 10
            color: visualTheme.secondaryText
            text: settingsController.localAsrRequirementsList.slice(0, 3).join(" · ")
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.subtleText
            font.pixelSize: 10
            text: settingsController.localAsrRequirementsList.slice(3).filter(Boolean).join("\n")
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.secondaryText
            visible: settingsController.localAsrBusy
            font.pixelSize: 10
            text: settingsController.localAsrStep
        }
        SettingsProgress {
            visualTheme: card.visualTheme
            Layout.fillWidth: true; visible: settingsController.localAsrBusy
            value: settingsController.localAsrProgress
            indeterminate: settingsController.localAsrProgress <= 0
            Accessible.name: "Current installation step progress"
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.secondaryText
            font.pixelSize: 10
            visible: !settingsController.localAsrBusy && settingsController.localAsrStatus !== "installed"
            text: !settingsController.localAsrCanInstall ? "Local installation requires Windows x64."
                : settingsController.localAsrStatus === "cancelled" ? "Download cancelled. You can try again."
                : settingsController.localAsrStatus === "error" || settingsController.localAsrStatus === "invalid"
                  ? "Installation needs attention. " + settingsController.localAsrDetail
                  : "The download starts only when you choose Install."
        }
        RowLayout {
            Layout.fillWidth: true
            AppButton {
                objectName: "localInstallButton"
                theme: card.visualTheme; primary: true; Layout.preferredWidth: 130; Layout.preferredHeight: 28
                text: settingsController.localAsrStatus === "installed" ? "Use this model"
                    : settingsController.localAsrStatus === "error" || settingsController.localAsrStatus === "invalid" ? "Retry installation" : "Install model"
                enabled: !settingsController.localBenchmarkBusy && !settingsController.localAsrBusy && settingsController.localAsrCanInstall
                background: Rectangle {
                    radius: card.visualTheme.fieldRadius
                    color: parent.enabled && (parent.hovered || parent.down || parent.checked || parent.activeFocus) ? card.visualTheme.controlHover : card.visualTheme.card
                    border.color: card.visualTheme.border
                }
                onClicked: {
                    if (settingsController.localAsrStatus === "installed") {
                        if (settingsController.useLocalAsr()) card.modelSelected()
                    } else settingsController.installLocalAsr()
                }
            }
            AppButton {
                objectName: "localCancelButton"
                theme: card.visualTheme; Layout.preferredWidth: 62; visible: settingsController.localAsrBusy; text: "Cancel"
                onClicked: settingsController.cancelLocalAsr()
            }
            Item { Layout.fillWidth: true }
            AppButton {
                objectName: "localRemoveButton"
                theme: card.visualTheme; quiet: true; Layout.preferredWidth: 72; text: "Remove…"
                visible: settingsController.localAsrStatus === "installed" && !settingsController.localAsrBusy
                onClicked: card.confirmRemoval = !card.confirmRemoval
            }
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.subtleText
            visible: settingsController.localAsrStatus === "installed"
            font.pixelSize: 10
            text: settingsController.routeProviderId === "local_asr" && settingsController.selectedScope === "transcription" && settingsController.routeModelId === ["ggml-base", "ggml-small", "ggml-medium"][settingsController.localProfileIndex]
                ? "Selected for transcription. Save settings to apply."
                : "Use this model selects it for transcription. Save settings to apply."
        }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.secondaryText
            visible: settingsController.localAsrStatus === "installed"
            text: settingsController.localAsrDetail
        }
        ColumnLayout {
            Layout.fillWidth: true; visible: card.confirmRemoval && settingsController.localAsrStatus === "installed"
            Label {
                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: visualTheme.text
                text: "Remove downloaded files? Local transcription will stop working until you install them again."
            }
            RowLayout {
                AppButton { objectName: "localKeepButton"; theme: card.visualTheme; Layout.preferredWidth: 94; text: "Keep model"; onClicked: card.confirmRemoval = false }
                AppButton { objectName: "localConfirmRemoveButton"; theme: card.visualTheme; Layout.preferredWidth: 94; text: "Remove files"; onClicked: { card.confirmRemoval = false; settingsController.removeLocalAsr() } }
            }
        }
    }
}
