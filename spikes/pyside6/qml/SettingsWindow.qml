import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5
import QtQuick.Window 6.5

ApplicationWindow {
    id: root
    objectName: "clarifySettingsWindow"
    title: "Clarify - Settings"
    width: 1040
    height: 760
    minimumWidth: 820
    minimumHeight: 560
    flags: Qt.Window
    color: theme.card
    font.pixelSize: 13
    property Theme visualTheme: theme
    Theme { id: theme; fieldFontSize: 13; fieldHeight: 38; dim: "#999999" }
    palette.window: theme.card
    palette.windowText: theme.text
    palette.base: theme.control
    palette.text: theme.text
    palette.button: theme.control
    palette.buttonText: theme.text
    palette.highlight: theme.controlPressed
    palette.highlightedText: theme.text
    palette.placeholderText: theme.subtleText
    property bool closeAfterDiscard: false
    readonly property bool editorDirty: activeFocusControl !== null
        && activeFocusControl.pendingEdit === true
    readonly property bool hasChanges: settings.dirty || settings.providerDirty || editorDirty


    readonly property string inputError: {
        var retentionText = historyRetentionField.text.trim()
        var retention = Number(retentionText)
        if (historyBox.checked && retentionText !== ""
                && (!isFinite(retention) || retention !== Math.floor(retention)
                    || retention < 0 || retention > 3650))
            return "History retention must be between 0 and 3650 days."
        var maximumText = maximumDurationField.text.trim()
        var maximum = Number(maximumText)
        if (maximumText !== "" && (!isFinite(maximum) || maximum < 0.001))
            return "Maximum recording duration must be positive, or blank for no limit."
        var warning = Number(warningSecondsField.text)
        if (warningSecondsField.text.trim() === "" || !isFinite(warning) || warning < 0
                || (maximumText !== "" && warning > maximum))
            return "Warning seconds must be between zero and the maximum duration."
        var threshold = Number(vadLevelField.text)
        var speech = Number(minimumSpeechField.text)
        var silence = Number(silenceDurationField.text)
        if (vadLevelField.text.trim() === "" || !isFinite(threshold) || threshold < 0 || threshold > 1)
            return "Speech level must be between 0 and 1."
        if (minimumSpeechField.text.trim() === "" || !isFinite(speech) || speech < 0)
            return "Minimum speech seconds must be zero or positive."
        if (silenceDurationField.text.trim() === "" || !isFinite(silence) || silence < 0.001)
            return "Silence seconds must be positive."
        return ""
    }
    function saveDraft() {
        settingsPage.forceActiveFocus()
        return inputError === "" && !settings.providerDirty && settings.save()
    }
    function requestClose() {
        settingsPage.forceActiveFocus()
        if (hasChanges || inputError !== "") {
            closeAfterDiscard = true
            unsavedDialog.open()
        } else {
            workflow.closeSettings()
        }
    }
    ButtonGroup { id: sectionButtons; exclusive: true }
    property string pendingProvider: ""
    function changeProvider(value) {
        if (value === settings.selectedProviderId) return
        if (settings.providerDirty) {
            pendingProvider = value
            providerDraftDialog.open()
        } else settings.selectProvider(value)
    }
    Dialog {
        implicitWidth: 400
        id: providerDraftDialog
        title: "Unsaved service changes"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Discard | Dialog.Cancel
        Label {
            width: 340; wrapMode: Text.WordWrap; color: theme.text
            text: "Discard the unsaved key and endpoint before switching services?"
        }
        onDiscarded: settings.selectProvider(root.pendingProvider)
    }
    function requestDiscard() {
        closeAfterDiscard = false
        unsavedDialog.open()
    }
    function syncVisibility() {
        if (workflow.surface === "settings") {
            if (visibility === Window.Minimized) showNormal()
            visible = true
            raise()
            requestActivate()
        } else {
            visible = false
        }
    }
    Component.onCompleted: syncVisibility()
    Connections {
        target: workflow
        function onSurfaceChanged() { root.syncVisibility() }
    }
    onClosing: function(event) { event.accepted = false; requestClose() }
    onVisibleChanged: {
        if (!visible) {
            settings.stopMicrophoneTest()
            settings.cancelHotkeyCapture()
        }
    }
    onVisibilityChanged: {
        if (root.visibility === Window.Minimized) settings.stopMicrophoneTest()
    }
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (settings.hotkeyCaptureAction !== "") settings.cancelHotkeyCapture()
            else root.requestClose()
        }
    }
    Dialog {
        implicitWidth: 400
        id: unsavedDialog
        objectName: "unsavedSettingsDialog"
        anchors.centerIn: parent
        title: "Unsaved changes"
        modal: true
        closePolicy: Popup.CloseOnEscape
        standardButtons: Dialog.Save | Dialog.Discard | Dialog.Cancel
        Label {
            width: 340
            wrapMode: Text.WordWrap
            text: settings.providerDirty
                ? "Service changes are not saved. Use Validate & save in Models & services, or discard the changes."
                : "Save your changes before continuing?"
            color: theme.text
        }
        Component.onCompleted: {
            standardButton(Dialog.Discard).objectName = "discardSettingsDialogButton"
            standardButton(Dialog.Save).enabled = Qt.binding(function() {
                return !settings.providerDirty && root.inputError === ""
            })
        }
        onAccepted: {
            if (root.saveDraft() && root.closeAfterDiscard) workflow.closeSettings()
        }
        onDiscarded: {
            if (settings.load() && root.closeAfterDiscard) workflow.closeSettings()
        }
    }
    Item {
        id: hotkeyCaptureItem
        objectName: "hotkeyCaptureItem"
        width: 1
        height: 1
        enabled: workflow.surface === "settings"
                 && settings.hotkeyCaptureAction !== ""
        focus: enabled

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
            event.accepted = true
            if (event.isAutoRepeat)
                return
            if (event.key === Qt.Key_Escape) {
                settings.cancelHotkeyCapture()
                return
            }
            settings.captureHotkey(
                settings.hotkeyCaptureAction, event.key, event.modifiers)
        }
    }

    Item {
        id: settingsPage
        objectName: "settingsPage"
        anchors.fill: parent
        focus: root.visible
        property int selectedSection: 0
        property string textWorkflowScope: "refinement"
        readonly property var sectionItems: [
            { "label": "General", "icon": "settings.svg" },
            { "label": "Dictation", "icon": "mic.svg" },
            { "label": "Text", "icon": "sparkles.svg" },
            { "label": "Shortcuts", "icon": "keyboard.svg" },
            { "label": "Models & services", "icon": "server.svg" }
        ]
        readonly property var textWorkflowItems: [
            { "scope": "refinement", "label": "Cleanup" },
            { "scope": "rewrite", "label": "Rewrite" },
            { "scope": "translation", "label": "Translation" }
        ]

        function workflowScopeLabel(scope) {
            var labels = {
                "transcription": "Dictation",
                "refinement": "Cleanup",
                "rewrite": "Rewrite",
                "translation": "Translation",
                "local_asr_refinement": "Cleanup after local transcription"
            }
            return labels[scope] || scope
        }

        function workflowDescription(scope) {
            var descriptions = {
                "transcription": "Choose how recorded speech is transcribed before it is pasted.",
                "refinement": "Improve dictated text while preserving its meaning.",
                "rewrite": "Rewrite selected text while preserving its requirements.",
                "translation": "Translate selected text using the configured language model.",
                "local_asr_refinement": "Optional cleanup after on-device transcription. If enabled, the transcript is sent to the selected service. Audio stays on your computer."
            }
            return descriptions[scope] || "Configure this workflow."
        }

        function workflowToggleLabel(scope) {
            var labels = {
                "transcription": "Enable dictation",
                "refinement": "Enable cleanup",
                "rewrite": "Enable rewrite",
                "translation": "Enable translation",
                "local_asr_refinement": "Clean up local transcripts"
            }
            return labels[scope] || "Enable this feature"
        }

        function selectWorkflowScope(scope) {
            if (!settings.selectWorkflow(scope))
                return
            if (scope !== "transcription")
                textWorkflowScope = scope
        }

        function selectSection(index) {
            if (index >= 0 && index < sectionItems.length
                    && index !== selectedSection) {
                selectedSection = index
                if (index === 1)
                    selectWorkflowScope("transcription")
                else if (index === 2)
                    selectWorkflowScope(textWorkflowScope)
                else if (index === 4 && settings.selectedProviderId === "local_asr")
                    settings.selectProvider("openai")
            }
        }

        onVisibleChanged: {
            if (!visible)
                settings.stopMicrophoneTest()
            if (visible) {
                Qt.callLater(function() {
                    settingsScroll.contentItem.contentY = 0
                })
            }
        }

        onSelectedSectionChanged: {
            if (selectedSection !== 1)
                settings.stopMicrophoneTest()
            Qt.callLater(function() {
                settingsScroll.contentItem.contentY = 0
            })
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 16

            RowLayout {
                id: settingsBody
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 8

                Item {
                    id: settingsSidebar
                    objectName: "settingsSidebar"
                    Layout.preferredWidth: 180
                    Layout.fillHeight: true

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 2
                        spacing: 2

                        Repeater {
                            model: settingsPage.sectionItems

                            delegate: AppButton {
                                required property int index
                                required property var modelData
                                objectName: "settingsSection" + index
                                Layout.fillWidth: true
                                Layout.preferredHeight: 40
                                text: modelData.label
                                iconSource: "icons/" + modelData.icon
                                theme: root.visualTheme
                                primary: index === settingsPage.selectedSection
                                checkable: true
                                ButtonGroup.group: sectionButtons
                                checked: index === settingsPage.selectedSection
                                quiet: true
                                contentAlignment: Text.AlignLeft
                                leftPadding: 8
                                rightPadding: 4
                                Accessible.name: "Open " + modelData.label + " settings"
                                onClicked: settingsPage.selectSection(index)
                            }
                        }

                        Item { Layout.fillHeight: true }
                    }
                }

                Rectangle {
                    id: settingsSidebarDivider
                    objectName: "settingsSidebarDivider"
                    Layout.preferredWidth: 1
                    Layout.fillHeight: true
                    color: theme.border
                }

                ScrollView {
                id: settingsScroll
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                objectName: "settingsScroll"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    contentItem: Rectangle {
                        implicitWidth: 4
                        radius: 2
                        color: theme.dim
                    }
                    background: Rectangle {
                        implicitWidth: 4
                        color: "transparent"
                    }
                }

                ColumnLayout {
                    id: settingsContent
                    width: Math.max(0, Math.min(760, settingsScroll.availableWidth - 16))
                    spacing: 12

                    SettingsGroup {
                        id: generalSettingsSection
                        objectName: "generalSettingsSection"
                        visualTheme: root.visualTheme
                        title: "General"
                        description: "App behavior and local history."
                        Layout.fillWidth: true
                        visible: settingsPage.selectedSection === 0

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 14

                        Label {
                            Layout.preferredWidth: 164
                            text: "Default mode"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SearchSelect {
                            id: settingsModeBox
                            objectName: "settingsModeBox"
                            visualTheme: theme
                            Layout.fillWidth: true
                            caption: "Mode"
                            searchable: false
                            options: settings.modes.map(function(id) { return {id: id, label: id === "prompt" ? "Prompt" : "Transcription"} })
                            value: settings.mode
                            onActivated: function(value) { settings.setMode(value) }
                        }

                        Label {
                            text: "Start with Windows"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SettingsSwitch {
                            visualTheme: theme
                            id: autostartBox
                            objectName: "autostartBox"
                            Layout.fillWidth: true
                            checked: settings.autostart
                            Accessible.name: "Start with Windows"
                            onToggled: settings.setAutostart(checked)
                        }

                        Label {
                            text: "History"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            SettingsSwitch {
                                visualTheme: theme
                                id: historyBox
                                objectName: "historyBox"
                                checked: settings.historyEnabled
                                text: "Keep local history"
                                onToggled: settings.setHistoryEnabled(checked)
                            }

                            SettingsField {
                                visualTheme: theme
                                id: historyRetentionField
                                objectName: "historyRetentionField"
                                Accessible.name: "History retention in days"
                                Layout.preferredWidth: 62
                                enabled: historyBox.checked
                                text: settings.historyRetentionDays === null
                                      || settings.historyRetentionDays === undefined
                                      ? "" : String(settings.historyRetentionDays)
                                inputMethodHints: Qt.ImhDigitsOnly
                                        onEditingFinished: settings.setHistoryRetentionDays(
                                    text.trim() === "" ? null : Number(text)
                                )
                            }
                            Label {
                                text: "days"
                                color: theme.dim
                                font.pixelSize: 13
                            }
                        }
                    }

                    }

                    SettingsGroup {
                        id: shortcutSettingsSection
                        objectName: "shortcutSettingsSection"
                        visualTheme: root.visualTheme
                        title: "Shortcuts"
                        Layout.fillWidth: true
                        visible: settingsPage.selectedSection === 3

                    Label {
                        Layout.fillWidth: true
                        text: "Configure the global Clarify actions. Changes apply when you save Settings."
                        color: theme.dim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Label {
                            Layout.fillWidth: true
                            text: settings.hotkeyCaptureAction === ""
                                  ? (settings.hotkeyPushToTalkSupported
                                     ? "Recording activation"
                                     : "Recording activation · push-to-talk unavailable")
                                  : "Press a modifier and a key. Escape cancels."
                            color: settings.hotkeyCaptureAction === ""
                                   ? theme.dim : theme.secondaryText
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }

                        AppButton {
                            text: "Reset all"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 70
                            Layout.preferredHeight: 34
                            Accessible.name: "Reset all keyboard shortcuts"
                            onClicked: settings.resetAllHotkeys()
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 14

                        Label {
                            Layout.preferredWidth: 164
                            text: "Recording activation"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SearchSelect {
                            id: hotkeyActivationBox
                            objectName: "hotkeyActivationBox"
                            visualTheme: theme
                            Layout.fillWidth: true
                            caption: "Recording activation"
                            searchable: false
                            options: settings.hotkeyActivationModes.map(function(id) { return {id: id, label: id === "push_to_talk" ? "Push-to-talk" : "Toggle"} })
                            value: settings.hotkeyActivationMode
                            onActivated: function(value) { settings.setHotkeyActivationMode(value) }
                        }

                        ColumnLayout {
                            Layout.columnSpan: 2
                            Layout.fillWidth: true
                            spacing: 4

                            Repeater {
                                model: settings.hotkeyActions

                                delegate: RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Label {
                                        Layout.fillWidth: true
                                        text: modelData["label"]
                                        color: theme.dim
                                        font.pixelSize: 13
                                        elide: Text.ElideRight
                                    }

                                    AppButton {
                                        text: settings.hotkeyCaptureAction === modelData["id"]
                                              ? "Press a key…" : modelData["display"]
                                        theme: root.visualTheme
                                        Layout.preferredWidth: 118
                                        Layout.preferredHeight: 34
                                        Accessible.name: "Edit " + modelData["label"] + " shortcut"
                                        onClicked: {
                                            if (settings.hotkeyCaptureAction === modelData["id"]) {
                                                settings.cancelHotkeyCapture()
                                            } else if (settings.beginHotkeyCapture(modelData["id"])) {
                                                hotkeyCaptureItem.forceActiveFocus()
                                            }
                                        }
                                    }

                                    AppButton {
                                        text: "Reset"
                                        theme: root.visualTheme
                                        quiet: true
                                        Layout.preferredWidth: 110
                                        Layout.preferredHeight: 34
                                        Accessible.name: "Reset " + modelData["label"] + " shortcut"
                                        onClicked: settings.resetHotkey(modelData["id"])
                                    }
                                }
                            }
                        }
                    }

                    }

                    SettingsGroup {
                        id: recordingSettingsSection
                        objectName: "recordingSettingsSection"
                        visualTheme: root.visualTheme
                        title: "Audio"
                        Layout.fillWidth: true
                        visible: settingsPage.selectedSection === 1

                    function recordingControlsDraft() {
                        var current = settings.recordingControls
                        var vad = current["vad"] || {}
                        return {
                            "max_duration_seconds": maximumDurationField.text.trim() === ""
                                                       ? null : Number(maximumDurationField.text),
                            "warning_seconds": Number(warningSecondsField.text),
                            "vad": {
                                "enabled": vadEnabledBox.checked,
                                "level_threshold": Number(vadLevelField.text),
                                "minimum_speech_seconds": Number(minimumSpeechField.text),
                                "silence_duration_seconds": Number(silenceDurationField.text)
                            }
                        }
                    }

                    function updateRecordingControls() {
                        settings.setRecordingControls(recordingControlsDraft())
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 14

                        Label {
                            Layout.preferredWidth: 164
                            text: "Input"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 5

                            SearchSelect {
                                id: microphoneBox
                                objectName: "microphoneBox"
                                visualTheme: theme
                                Layout.fillWidth: true
                                caption: "Microphone"
                                searchPlaceholder: "Search microphones"
                                options: settings.microphoneDevices
                                value: options.length ? options[Math.max(0, settings.microphoneSelectionIndex)].id : ""
                                refreshable: true
                                busy: settings.microphoneTestBusy
                                onRefreshRequested: settings.refreshMicrophoneInventory()
                                onActivated: function(value) { settings.selectMicrophone(value) }
                            }

                        }

                        Label {
                            text: "Input status"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 5

                            Label {
                                Layout.fillWidth: true
                                text: settings.microphoneStatus
                                color: settings.microphoneStatusKind === "error"
                                       ? theme.secondaryText
                                       : settings.microphoneStatusKind === "warning"
                                         ? "#d3a46f" : theme.dim
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }

                            AppButton {
                                text: "Use default"
                                theme: root.visualTheme
                                quiet: true
                                property bool fadeShown: settings.selectedMicrophoneId !== null
                                visible: fadeShown || opacity > 0.001
                                opacity: fadeShown ? 1.0 : 0.0
                                Behavior on opacity {
                                    NumberAnimation {
                                        duration: theme.fadeDuration
                                        easing.type: Easing.OutCubic
                                    }
                                }
                                Layout.preferredWidth: 78
                                Layout.preferredHeight: 34
                                Accessible.name: "Use current system microphone"
                                onClicked: settings.selectMicrophone("")
                            }

                            AppButton {
                                objectName: "microphoneTestButton"
                                text: settings.microphoneTestStopping ? "Stopping…" : settings.microphoneTestBusy ? "Stop" : "Test"
                                theme: root.visualTheme
                                enabled: !settings.microphoneTestStopping
                                Layout.preferredWidth: 78
                                Layout.preferredHeight: 34
                                Accessible.name: settings.microphoneTestBusy ? "Stop microphone test" : "Test microphone input"
                                onClicked: {
                                    if (settings.microphoneTestBusy) settings.stopMicrophoneTest()
                                    else settings.testMicrophone()
                                }
                            }
                        }

                    }

                    MicrophoneWaveform {
                        objectName: "microphoneTestWaveform"
                        Layout.fillWidth: true
                        visualTheme: root.visualTheme
                        visible: settings.microphoneTestBusy
                        running: settings.microphoneTestBusy && !settings.microphoneTestStopping
                        level: settings.microphoneTestLevel
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: settings.microphoneTestStatus !== ""
                        text: settings.microphoneTestStatus
                        color: theme.subtleText
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    SettingsGroup {
                        objectName: "advancedRecordingGroup"
                        visualTheme: root.visualTheme
                        Layout.fillWidth: true
                        title: "Advanced recording"
                        collapsible: true
                        description: "Duration limits and automatic stop after speech."
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            columnSpacing: 16
                            rowSpacing: 14
                        Label {
                                Layout.preferredWidth: 164
                            text: "Maximum seconds"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SettingsField {
                            visualTheme: theme
                            id: maximumDurationField
                            objectName: "maximumDurationField"
                            Accessible.name: "Maximum recording seconds"
                            Layout.fillWidth: true
                            text: settings.recordingControls["max_duration_seconds"] === null
                                  || settings.recordingControls["max_duration_seconds"] === undefined
                                  ? "" : String(settings.recordingControls["max_duration_seconds"])
                            placeholderText: "Blank = unlimited"
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            onEditingFinished: recordingSettingsSection.updateRecordingControls()
                        }

                        Label {
                            text: "Warning seconds"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SettingsField {
                            visualTheme: theme
                            id: warningSecondsField
                            objectName: "warningSecondsField"
                            Accessible.name: "Recording warning seconds"
                            Layout.fillWidth: true
                            text: String(settings.recordingControls["warning_seconds"])
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            onEditingFinished: recordingSettingsSection.updateRecordingControls()
                        }

                        SettingsSwitch {
                            visualTheme: theme
                            id: vadEnabledBox
                            objectName: "vadEnabledBox"
                            Layout.columnSpan: 2
                            checked: settings.recordingControls["vad"]["enabled"]
                            text: "Stop after speech and silence"
                            onToggled: recordingSettingsSection.updateRecordingControls()
                        }

                        Label {
                            text: "Level threshold"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SettingsField {
                            visualTheme: theme
                            id: vadLevelField
                            objectName: "vadLevelField"
                            Accessible.name: "Speech level threshold"
                            Layout.fillWidth: true
                            enabled: vadEnabledBox.checked
                            text: String(settings.recordingControls["vad"]["level_threshold"])
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            onEditingFinished: recordingSettingsSection.updateRecordingControls()
                        }

                        Label {
                            text: "Minimum speech seconds"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SettingsField {
                            visualTheme: theme
                            id: minimumSpeechField
                            objectName: "minimumSpeechField"
                            Accessible.name: "Minimum speech seconds"
                            Layout.fillWidth: true
                            enabled: vadEnabledBox.checked
                            text: String(settings.recordingControls["vad"]["minimum_speech_seconds"])
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            onEditingFinished: recordingSettingsSection.updateRecordingControls()
                        }

                        Label {
                            text: "Silence seconds"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SettingsField {
                            visualTheme: theme
                            id: silenceDurationField
                            objectName: "silenceDurationField"
                            Accessible.name: "Silence seconds"
                            Layout.fillWidth: true
                            enabled: vadEnabledBox.checked
                            text: String(settings.recordingControls["vad"]["silence_duration_seconds"])
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            onEditingFinished: recordingSettingsSection.updateRecordingControls()
                        }
                    }

                    }

                    }

                    ColumnLayout {
                        id: integrationsSettingsSection
                        objectName: "integrationsSettingsSection"
                        Layout.fillWidth: true
                        spacing: 8
                        visible: settingsPage.selectedSection === 4

                    Label {
                        text: "Models & services"
                        color: theme.secondaryText
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.7
                    }

                    Label {
                        Layout.fillWidth: true
                        text: "Connect services and manage credentials used by your workflows."
                        color: theme.dim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    SettingsGroup {
                        Layout.fillWidth: true
                        visualTheme: root.visualTheme
                        title: "Connected services"
                        description: "Credentials are shared by your tasks. Validate & save applies to this service only."

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 14

                        Label {
                            Layout.preferredWidth: 164
                            text: "Service"
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SearchSelect {
                            id: onboardingProviderBox
                            objectName: "onboardingProviderBox"
                            visualTheme: theme
                            Layout.fillWidth: true
                            caption: "Service"
                            searchable: false
                            options: settings.providerIds.filter(function(id) { return id !== "local_asr" }).map(function(id) { return {id: id, label: settings.providerName(id)} })
                            value: settings.selectedProviderId
                            onActivated: function(value) { root.changeProvider(value) }
                        }

                        Label {
                            text: "API key"
                            property bool fadeShown: settings.selectedProviderId !== "local_asr"
                            visible: fadeShown || opacity > 0.001
                            opacity: fadeShown ? 1.0 : 0.0
                            Behavior on opacity {
                                NumberAnimation {
                                    duration: theme.fadeDuration
                                    easing.type: Easing.OutCubic
                                }
                            }
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SettingsField {
                            visualTheme: theme
                            id: providerApiKeyField
                            objectName: "providerApiKeyField"
                            Accessible.name: "Service API key"
                            property bool fadeShown: settings.selectedProviderId !== "local_asr"
                            visible: fadeShown || opacity > 0.001
                            opacity: fadeShown ? 1.0 : 0.0
                            Behavior on opacity {
                                NumberAnimation {
                                    duration: theme.fadeDuration
                                    easing.type: Easing.OutCubic
                                }
                            }
                            Layout.fillWidth: true
                            text: settings.providerApiKey
                            placeholderText: settings.providerHasApiKey
                                             ? "Saved key; leave blank to keep it"
                                             : "Paste API key"
                            echoMode: TextInput.Password
                            onTextEdited: settings.setProviderApiKey(text)
                        }

                        Label {
                            text: "Base URL"
                            property bool fadeShown: settings.selectedProviderId !== "local_asr"
                            visible: fadeShown || opacity > 0.001
                            opacity: fadeShown ? 1.0 : 0.0
                            Behavior on opacity {
                                NumberAnimation {
                                    duration: theme.fadeDuration
                                    easing.type: Easing.OutCubic
                                }
                            }
                            color: theme.dim
                            font.pixelSize: 13
                        }

                        SettingsField {
                            visualTheme: theme
                            id: providerBaseUrlField
                            objectName: "providerBaseUrlField"
                            Accessible.name: "Service base URL"
                            property bool fadeShown: settings.selectedProviderId !== "local_asr"
                            visible: fadeShown || opacity > 0.001
                            opacity: fadeShown ? 1.0 : 0.0
                            Behavior on opacity {
                                NumberAnimation {
                                    duration: theme.fadeDuration
                                    easing.type: Easing.OutCubic
                                }
                            }
                            enabled: settings.providerSupportsCustomEndpoint
                            Layout.fillWidth: true
                            text: settings.providerBaseUrl
                            onTextEdited: settings.setProviderBaseUrl(text)
                            placeholderText: "Service endpoint"
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        property bool fadeShown: settings.selectedProviderId !== "local_asr"
                        visible: fadeShown || opacity > 0.001
                        opacity: fadeShown ? 1.0 : 0.0
                        Behavior on opacity {
                            NumberAnimation {
                                duration: theme.fadeDuration
                                easing.type: Easing.OutCubic
                            }
                        }
                        text: (({ "not_configured": "Not connected", "configured": "Key saved",
                                 "active": "Connected", "validating": "Checking connection...",
                                 "error": "Connection failed" })[settings.providerStatus] || settings.providerStatus)
                              + (settings.providerError !== ""
                                 ? " — " + settings.providerError : "")
                        color: settings.providerError !== ""
                               ? theme.secondaryText : theme.dim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        property bool fadeShown: settings.selectedProviderId !== "local_asr"
                        visible: fadeShown || opacity > 0.001
                        opacity: fadeShown ? 1.0 : 0.0
                        Behavior on opacity {
                            NumberAnimation {
                                duration: theme.fadeDuration
                                easing.type: Easing.OutCubic
                            }
                        }
                        spacing: 5

                        Item { Layout.fillWidth: true }

                        AppButton {
                            text: settings.providerBusy ? "Validating…"
                                  : "Validate & save"
                            theme: root.visualTheme
                            enabled: !settings.providerBusy
                            Layout.preferredWidth: 108
                            Layout.preferredHeight: 34
                            Accessible.name: "Validate and save provider"
                            onClicked: settings.validateProvider()
                        }

                        AppButton {
                            text: "Clear key"
                            theme: root.visualTheme
                            quiet: true
                            enabled: settings.providerHasApiKey
                            Layout.preferredWidth: 68
                            Layout.preferredHeight: 34
                            Accessible.name: "Clear provider API key"
                            onClicked: settings.clearProvider()
                        }
                    }

                    }

                    LocalModelCard {
                        id: localModelsGroup
                        Layout.fillWidth: true
                        visualTheme: root.visualTheme
                        settingsController: settings
                        onModelSelected: settingsPage.selectSection(1)
                    }

                    }

                    SettingsGroup {
                        id: workflowSettingsSection
                        objectName: "workflowSettingsSection"
                        visualTheme: root.visualTheme
                        title: settingsPage.selectedSection === 1 ? "Transcription" : "Text"
                        Layout.fillWidth: true
                        visible: settingsPage.selectedSection === 1
                                 || settingsPage.selectedSection === 2

                    RowLayout {
                        objectName: "textWorkflowTabs"
                        visible: settingsPage.selectedSection === 2
                        Layout.alignment: Qt.AlignLeft
                        spacing: 4

                        Repeater {
                            model: settingsPage.textWorkflowItems

                            delegate: AppButton {
                                required property var modelData
                                objectName: "workflowTab" + modelData.scope
                                Layout.preferredHeight: 30
                                Layout.preferredWidth: tabTextMetrics.advanceWidth + 20
                                text: settingsPage.workflowScopeLabel(modelData.scope)
                                theme: root.visualTheme
                                primary: settings.selectedScope === modelData.scope
                                         || (modelData.scope === "refinement" && settings.selectedScope === "local_asr_refinement")
                                quiet: !primary
                                contentAlignment: Text.AlignHCenter
                                Accessible.name: "Open " + modelData.label + " settings"
                                onClicked: settingsPage.selectWorkflowScope(modelData.scope)

                                TextMetrics {
                                    id: tabTextMetrics
                                    text: settingsPage.workflowScopeLabel(modelData.scope)
                                    font.pixelSize: 12
                                    font.weight: Font.Normal
                                }
                            }
                        }
                    }

                    SettingsRow {
                        Layout.fillWidth: true
                        visualTheme: root.visualTheme
                        title: "Cleanup for"
                        visible: settingsPage.selectedSection === 2 && (settings.selectedScope === "refinement" || settings.selectedScope === "local_asr_refinement")
                        SearchSelect {
                            objectName: "cleanupContextBox"
                            Layout.fillWidth: true
                            visualTheme: root.visualTheme
                            searchable: false
                            caption: "Cleanup context"
                            value: settings.selectedScope
                            options: [
                                {id: "refinement", label: "Standard dictation"},
                                {id: "local_asr_refinement", label: "Local transcription"}
                            ]
                            onActivated: function(value) { settingsPage.selectWorkflowScope(value) }
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsPage.workflowDescription(settings.selectedScope)
                        color: theme.subtleText
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                    }

                    SettingsRow {
                        Layout.fillWidth: true
                        visualTheme: root.visualTheme
                        title: "Language"
                        visible: settingsPage.selectedSection === 1
                        SearchSelect {
                            id: settingsLanguageBox
                            objectName: "settingsLanguageBox"
                            visualTheme: root.visualTheme
                            Layout.fillWidth: true
                            caption: "Language"
                            searchPlaceholder: "Search languages"
                            options: settings.languages.map(function(id) {
                                var names = {"en": "English", "pt": "Portuguese", "es": "Spanish", "de": "German", "ru": "Russian"}
                                return {id: id, label: names[id] || id.toUpperCase(), icon: "flags/" + id + ".svg"}
                            })
                            value: settings.language
                            onActivated: function(value) { settings.setLanguage(value) }
                        }
                    }

                    WorkflowModelForm {
                        Layout.fillWidth: true
                        visualTheme: root.visualTheme
                        settingsController: settings
                        enabledLabel: settingsPage.workflowToggleLabel(settings.selectedScope)
                        onConnectProvider: {
                            settings.selectProvider(settings.routeProviderId)
                            settingsPage.selectSection(4)
                        }
                        onManageLocalModels: {
                            settingsPage.selectSection(4)
                            Qt.callLater(function() {
                                var flickable = settingsScroll.contentItem
                                var position = localModelsGroup.mapToItem(settingsContent, 0, 0).y
                                flickable.contentY = Math.max(0, Math.min(position, flickable.contentHeight - flickable.height))
                            })
                        }
                    }

                    }

                    SettingsRow {
                        Layout.fillWidth: true
                        visualTheme: root.visualTheme
                        title: "Audio files"
                        visible: settingsPage.selectedSection === 1
                        AppButton {
                            objectName: "settingsImportFilesButton"
                            Layout.preferredWidth: 136
                            text: "Import audio files"
                            theme: root.visualTheme
                            quiet: true
                            Accessible.name: "Import audio files"
                            onClicked: workflow.openFiles()
                        }
                    }


                }
            }

            }

                    Label {
                        id: settingsErrorLabel
                        objectName: "settingsErrorLabel"
                        Layout.fillWidth: true
                        property bool fadeShown: root.inputError !== "" || settings.lastError !== ""
                        visible: fadeShown || opacity > 0.001
                        opacity: fadeShown ? 1.0 : 0.0
                        Behavior on opacity {
                            NumberAnimation {
                                duration: theme.fadeDuration
                                easing.type: Easing.OutCubic
                            }
                        }
                        text: root.inputError || settings.lastError
                        color: theme.secondaryText
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

            RowLayout {
                Layout.fillWidth: true
                spacing: 5

                Label {
                    objectName: "settingsDirtyLabel"
                    text: settings.providerDirty ? "Service changes: use Validate & save"
                        : root.hasChanges ? "Unsaved changes" : "Saved"
                    color: root.hasChanges ? theme.secondaryText : theme.dim
                    font.pixelSize: 12
                }

                Item { Layout.fillWidth: true }

                AppButton {
                    text: "Discard changes"
                    theme: root.visualTheme
                    quiet: true
                    Layout.preferredWidth: 110
                    Layout.preferredHeight: 34
                    Accessible.name: "Discard unsaved settings"
                    enabled: root.hasChanges || root.inputError !== ""
                    onClicked: root.requestDiscard()
                }

                AppButton {
                    text: "Save"
                    theme: root.visualTheme
                    enabled: root.hasChanges && !settings.providerDirty && root.inputError === ""
                    Layout.preferredWidth: 110
                    Layout.preferredHeight: 34
                    objectName: "saveSettingsButton"
                    Accessible.name: "Save settings"
                    onClicked: root.saveDraft()
                }

                AppButton {
                    text: "Close"
                    theme: root.visualTheme
                    quiet: true
                    Layout.preferredWidth: 56
                    Layout.preferredHeight: 34
                    Accessible.name: "Close settings"
                    onClicked: root.requestClose()
                }
            }
        }
    }
}
