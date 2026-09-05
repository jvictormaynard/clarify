import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Dialogs 6.5
import QtQuick.Layouts 6.5
import QtQuick.Window 6.5

ApplicationWindow {
    id: root
    objectName: "clarifyVoiceMainWindow"
    width: (workflow.surface === "result"
            || workflow.surface === "voice_result"
            || workflow.surface === "voice_error" ? theme.resultWidth
            : workflow.surface === "settings" ? theme.settingsWidth
            : (workflow.surface === "files"
               || workflow.surface === "translation_picker")
              ? theme.panelWidth : theme.windowWidth) * theme.uiScale
    height: (workflow.surface === "result"
             || workflow.surface === "voice_result"
             || workflow.surface === "voice_error"
             ? theme.resultHeight
             : workflow.surface === "settings" ? theme.settingsHeight
             : (workflow.surface === "files"
                || workflow.surface === "translation_picker")
               ? theme.panelHeight : theme.windowHeight) * theme.uiScale
    minimumWidth: theme.windowWidth * theme.uiScale
    minimumHeight: theme.windowHeight * theme.uiScale
    property bool presentationVisible: false
    visible: presentationVisible || opacity > 0.001
    opacity: presentationVisible ? 1.0 : 0.0
    Behavior on opacity {
        NumberAnimation {
            duration: theme.fadeDuration
            easing.type: Easing.OutCubic
        }
    }
    title: "ClarifyVoice"
    onVisibilityChanged: {
        if (visibility === Window.Hidden || visibility === Window.Minimized)
            settings.stopMicrophoneTest()
    }
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint

    palette.window: theme.card
    palette.windowText: theme.text
    palette.base: theme.control
    palette.alternateBase: theme.controlHover
    palette.text: theme.text
    palette.button: theme.control
    palette.buttonText: theme.subtleText
    palette.highlight: theme.controlHover
    palette.highlightedText: theme.text
    palette.placeholderText: theme.dim
    palette.light: theme.controlHover
    palette.mid: theme.border
    palette.dark: theme.resultSurface
    palette.toolTipBase: theme.control
    palette.toolTipText: theme.text

    Theme { id: theme }
    property Theme visualTheme: theme

    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (workflow.surface === "recording")
                workflow.cancelRecording()
            else if (workflow.surface === "translation_picker")
                workflow.cancelTranslation()
            else if (workflow.surface === "result")
                workflow.reset()
            else if (workflow.surface === "settings") {
                if (settings.hotkeyCaptureAction !== "")
                    settings.cancelHotkeyCapture()
                else
                    workflow.reset()
            }
            else if (workflow.surface === "error")
                workflow.reset()
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

    Rectangle {
        id: card
        objectName: "mainCard"
        width: root.width / theme.uiScale
        height: root.height / theme.uiScale
        anchors.centerIn: parent
        scale: theme.uiScale
        transformOrigin: Item.Center
        radius: workflow.surface === "idle"
                || workflow.surface === "recording"
                || workflow.surface === "processing"
                || workflow.surface === "voice_processing"
            ? height / 2 : theme.panelRadius
        color: theme.card
        border.color: theme.border
        border.width: 1
        clip: true

        states: [
            State {
                name: "recording"
                when: workflow.surface === "recording"
                PropertyChanges { target: card; border.color: theme.dim }
            }
        ]

        transitions: [
            Transition {
                from: "*"
                to: "*"
                ColorAnimation { duration: 180; easing.type: Easing.OutCubic }
            }
        ]

        StackLayout {
            id: pages
            objectName: "appPages"
            anchors.fill: parent
            currentIndex: workflow.surface === "result"
                          ? 1
                          : workflow.surface === "settings" ? 2
                          : workflow.surface === "files" ? 3
                          : workflow.surface === "translation_picker" ? 4
                          : (workflow.surface === "voice_result"
                             || workflow.surface === "voice_error") ? 1 : 0

            Item {
                id: homePage
                objectName: "homePage"
                property bool promptMode: workflow.mode === "prompt"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 15
                    anchors.rightMargin: 8
                    spacing: 5

                    Item {
                        id: statusArea
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumWidth: 0
                        Layout.alignment: Qt.AlignVCenter

                        // The shell is frameless, so keep the status area
                        // draggable without taking pointer ownership away
                        // from the controls to its right.
                        DragHandler {
                            id: windowDragHandler
                            target: null
                            onActiveChanged: {
                                if (active)
                                    root.startSystemMove()
                            }
                        }

                        RowLayout {
                            anchors.fill: parent
                            spacing: 6

                            Label {
                                id: statusLabel
                                Layout.fillWidth: true
                                text: workflow.surface === "idle" ? "Ready"
                                      : workflow.surface === "recording" ? "Recording"
                                      : workflow.surface === "processing" ? "Processing…"
                                      : workflow.surface === "voice_processing" ? workflow.status
                                      : workflow.status
                                color: theme.text
                                font.pixelSize: 13
                                font.weight: Font.Bold
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                                Accessible.name: workflow.status
                            }

                        }

                        TapHandler {
                            enabled: workflow.surface === "idle"
                                     || workflow.surface === "recording"
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: {
                                if (workflow.surface === "recording")
                                    workflow.stopRecording()
                                else
                                    workflow.startRecording()
                            }
                        }
                    }

                    Item {
                        id: busyIndicator
                        property bool fadeShown: workflow.busy
                        visible: fadeShown || opacity > 0.001
                        opacity: fadeShown ? 1.0 : 0.0
                        Behavior on opacity {
                            NumberAnimation {
                                duration: theme.fadeDuration
                                easing.type: Easing.OutCubic
                            }
                        }
                        Layout.preferredWidth: 14
                        Layout.preferredHeight: 14
                        Layout.alignment: Qt.AlignVCenter

                        Rectangle {
                            anchors.fill: parent
                            radius: width / 2
                            color: "transparent"
                            border.color: theme.dim
                            border.width: 1
                        }

                        Rectangle {
                            width: 4
                            height: 4
                            radius: 2
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 0
                            color: theme.text
                        }

                        RotationAnimation on rotation {
                            running: workflow.busy
                            from: 0
                            to: 360
                            duration: 760
                            loops: Animation.Infinite
                        }
                    }

                    RowLayout {
                        id: idleControls
                        property bool fadeShown: workflow.surface === "idle"
                        visible: fadeShown || opacity > 0.001
                        opacity: fadeShown ? 1.0 : 0.0
                        Behavior on opacity {
                            NumberAnimation {
                                duration: theme.fadeDuration
                                easing.type: Easing.OutCubic
                            }
                        }
                        spacing: 4

                        AppButton {
                            id: languageButton
                            objectName: "languageButton"
                            readonly property var supportedLanguages: [
                                "en", "pt", "es", "de", "ru"
                            ]
                            readonly property var languageNames: ({
                                "en": "English",
                                "pt": "Portuguese",
                                "es": "Spanish",
                                "de": "German",
                                "ru": "Russian"
                            })
                            property string languageCode: workflow.language.toUpperCase()
                            text: ""
                            theme: root.visualTheme
                            Layout.preferredWidth: 36
                            Layout.preferredHeight: 26
                            Accessible.name: "Language: "
                                              + languageNames[workflow.language]

                            RoundedFlag {
                                anchors.centerIn: parent
                                width: implicitWidth
                                height: implicitHeight
                                source: "flags/" + workflow.language + ".svg"
                            }
                            onClicked: {
                                var currentIndex = supportedLanguages.indexOf(workflow.language)
                                var nextIndex = (currentIndex + 1) % supportedLanguages.length
                                workflow.setLanguage(supportedLanguages[nextIndex])
                            }
                        }

                        AppButton {
                            id: modeButton
                            objectName: "modeButton"
                            text: homePage.promptMode ? "Prompt" : "Transcribe"
                            theme: root.visualTheme
                            Layout.preferredWidth: 78
                            Layout.preferredHeight: 26
                            Accessible.name: "Mode: "
                                              + (homePage.promptMode
                                                 ? "Prompt" : "Transcribe")
                            onClicked: {
                                workflow.setMode(homePage.promptMode
                                                 ? "transcription" : "prompt")
                            }
                        }

                        AppButton {
                            id: settingsButton
                            objectName: "settingsButton"
                            iconSource: "icons/settings.svg"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                            Accessible.name: "Open settings"
                            onClicked: workflow.openSettings()
                        }

                        AppButton {
                            id: closeButton
                            objectName: "closeButton"
                            iconSource: "icons/x.svg"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                            Accessible.name: "Close ClarifyVoice"
                            onClicked: root.close()
                        }
                    }

                    RowLayout {
                        id: errorControls
                        property bool fadeShown: workflow.surface === "error"
                        visible: fadeShown || opacity > 0.001
                        opacity: fadeShown ? 1.0 : 0.0
                        Behavior on opacity {
                            NumberAnimation {
                                duration: theme.fadeDuration
                                easing.type: Easing.OutCubic
                            }
                        }
                        spacing: 4

                        AppButton {
                            text: "Retry"
                            theme: root.visualTheme
                            visible: workflow.canRetryTranscription
                            Layout.preferredWidth: 60
                            Layout.preferredHeight: 26
                            Accessible.name: "Retry transcription with the same audio"
                            onClicked: workflow.retryTranscription()
                        }

                        AppButton {
                            text: "Dismiss"
                            theme: root.visualTheme
                            Layout.preferredWidth: 60
                            Layout.preferredHeight: 26
                            Accessible.name: "Dismiss workflow error"
                            onClicked: workflow.reset()
                        }

                        Item { Layout.fillWidth: true }
                    }

                }
            }

            Item {
                id: resultPage
                objectName: "resultPage"
                property string copyLabel: "Copy"

                function resetCopyConfirmation() {
                    copyResetTimer.stop()
                    copyLabel = "Copy"
                }

                Timer {
                    id: copyResetTimer
                    interval: 850
                    repeat: false
                    onTriggered: resultPage.copyLabel = "Copy"
                }

                onVisibleChanged: resetCopyConfirmation()

                Connections {
                    target: workflow

                    function onSurfaceChanged() {
                        resultPage.resetCopyConfirmation()
                    }

                    function onCopyCompleted(success) {
                        if (success) {
                            resultPage.copyLabel = "OK!"
                            copyResetTimer.restart()
                        } else {
                            resultPage.resetCopyConfirmation()
                        }
                    }
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 5

                    RowLayout {
                        Layout.fillWidth: true

                        Label {
                            text: "Result"
                            color: theme.text
                            font.pixelSize: 13
                            font.weight: Font.Bold
                        }

                        Item { Layout.fillWidth: true }

                        AppButton {
                            iconSource: "icons/x.svg"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                            Accessible.name: "Dismiss result"
                            onClicked: workflow.reset()
                        }
                    }

                    Rectangle {
                        id: resultCard
                        objectName: "resultCard"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 64
                        radius: 10
                        color: "transparent"

                        Label {
                            anchors.fill: parent
                            anchors.margins: 10
                            text: workflow.result
                            color: theme.secondaryText
                            font.pixelSize: 12
                            lineHeight: 1.2
                            wrapMode: Text.WordWrap
                            verticalAlignment: Text.AlignTop
                            Accessible.name: workflow.result
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        AppButton {
                            text: resultPage.copyLabel
                            theme: root.visualTheme
                            Layout.preferredWidth: 52
                            Layout.preferredHeight: 26
                            Accessible.name: "Copy result"
                            onClicked: workflow.copyResult()
                        }

                        AppButton {
                            text: "Dismiss"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 56
                            Layout.preferredHeight: 26
                            Accessible.name: "Dismiss result"
                            onClicked: workflow.reset()
                        }

                        Item { Layout.fillWidth: true }
                    }
                }
            }

            Item {
                id: settingsPage
                objectName: "settingsPage"
                focus: workflow.surface === "settings"
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
                    anchors.margins: 10
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true

                        DragHandler {
                            id: settingsWindowDragHandler
                            target: null
                            onActiveChanged: {
                                if (active)
                                    root.startSystemMove()
                            }
                        }

                        Label {
                            text: "Settings"
                            color: theme.text
                            font.pixelSize: 13
                            font.weight: Font.Bold
                        }

                        Item { Layout.fillWidth: true }

                        AppButton {
                            iconSource: "icons/x.svg"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                            Accessible.name: "Close settings"
                            onClicked: workflow.closeSettings()
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 1
                        color: theme.border
                    }

                    RowLayout {
                        id: settingsBody
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 8

                        Item {
                            id: settingsSidebar
                            objectName: "settingsSidebar"
                            Layout.preferredWidth: 145
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
                                        Layout.preferredHeight: 28
                                        text: modelData.label
                                        iconSource: "icons/" + modelData.icon
                                        theme: root.visualTheme
                                        primary: index === settingsPage.selectedSection
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
                            width: Math.max(0, settingsScroll.availableWidth)
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
                                columnSpacing: 12
                                rowSpacing: 6

                                Label {
                                    text: "Default mode"
                                    color: theme.dim
                                    font.pixelSize: 11
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
                                    font.pixelSize: 11
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
                                    font.pixelSize: 11
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
                                        validator: IntValidator { bottom: 0; top: 3650 }
                                        onEditingFinished: settings.setHistoryRetentionDays(
                                            text.trim() === "" ? null : Number(text)
                                        )
                                    }
                                    Label {
                                        text: "days"
                                        color: theme.dim
                                        font.pixelSize: 11
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
                                text: "Configure the global ClarifyVoice actions. Changes apply when you save Settings."
                                color: theme.dim
                                font.pixelSize: 10
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
                                    font.pixelSize: 10
                                    wrapMode: Text.WordWrap
                                }

                                AppButton {
                                    text: "Reset all"
                                    theme: root.visualTheme
                                    quiet: true
                                    Layout.preferredWidth: 70
                                    Layout.preferredHeight: 26
                                    Accessible.name: "Reset all keyboard shortcuts"
                                    onClicked: settings.resetAllHotkeys()
                                }
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                columns: 2
                                columnSpacing: 12
                                rowSpacing: 6

                                Label {
                                    text: "Recording activation"
                                    color: theme.dim
                                    font.pixelSize: 11
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
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                            }

                                            AppButton {
                                                text: settings.hotkeyCaptureAction === modelData["id"]
                                                      ? "Press a key…" : modelData["display"]
                                                theme: root.visualTheme
                                                Layout.preferredWidth: 118
                                                Layout.preferredHeight: 26
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
                                                Layout.preferredWidth: 52
                                                Layout.preferredHeight: 26
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
                                columnSpacing: 12
                                rowSpacing: 6

                                Label {
                                    text: "Input"
                                    color: theme.dim
                                    font.pixelSize: 11
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
                                    font.pixelSize: 11
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
                                        font.pixelSize: 10
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
                                        Layout.preferredHeight: 26
                                        Accessible.name: "Use current system microphone"
                                        onClicked: settings.selectMicrophone("")
                                    }

                                    AppButton {
                                        objectName: "microphoneTestButton"
                                        text: settings.microphoneTestStopping ? "Stopping…" : settings.microphoneTestBusy ? "Stop" : "Test"
                                        theme: root.visualTheme
                                        enabled: !settings.microphoneTestStopping
                                        Layout.preferredWidth: 78
                                        Layout.preferredHeight: 26
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
                                font.pixelSize: 10
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
                                    columnSpacing: 12
                                    rowSpacing: 8
                                Label {
                                    text: "Maximum seconds"
                                    color: theme.dim
                                    font.pixelSize: 11
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
                                    font.pixelSize: 11
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
                                    font.pixelSize: 11
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
                                    font.pixelSize: 11
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
                                    font.pixelSize: 11
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
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                                font.letterSpacing: 0.7
                            }

                            Label {
                                Layout.fillWidth: true
                                text: "Connect services and manage credentials used by your workflows."
                                color: theme.dim
                                font.pixelSize: 10
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
                                columnSpacing: 12
                                rowSpacing: 6

                                Label {
                                    text: "Service"
                                    color: theme.dim
                                    font.pixelSize: 11
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
                                    onActivated: function(value) { settings.selectProvider(value) }
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
                                    font.pixelSize: 11
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
                                    onEditingFinished: settings.setProviderApiKey(text)
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
                                    font.pixelSize: 11
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
                                    onEditingFinished: settings.setProviderBaseUrl(text)
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
                                text: "Status: " + settings.providerStatus
                                      + (settings.providerError !== ""
                                         ? " — " + settings.providerError : "")
                                color: settings.providerError !== ""
                                       ? theme.secondaryText : theme.dim
                                font.pixelSize: 10
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
                                    Layout.preferredHeight: 26
                                    Accessible.name: "Validate and save provider"
                                    onClicked: settings.validateProvider()
                                }

                                AppButton {
                                    text: "Clear key"
                                    theme: root.visualTheme
                                    quiet: true
                                    enabled: settings.providerHasApiKey
                                    Layout.preferredWidth: 68
                                    Layout.preferredHeight: 26
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
                                font.pixelSize: 11
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

                            Label {
                                id: settingsErrorLabel
                                objectName: "settingsErrorLabel"
                                Layout.fillWidth: true
                                property bool fadeShown: settings.lastError !== ""
                                visible: fadeShown || opacity > 0.001
                                opacity: fadeShown ? 1.0 : 0.0
                                Behavior on opacity {
                                    NumberAnimation {
                                        duration: theme.fadeDuration
                                        easing.type: Easing.OutCubic
                                    }
                                }
                                text: settings.lastError
                                color: theme.secondaryText
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 5

                        Label {
                            objectName: "settingsDirtyLabel"
                            text: settings.dirty ? "Unsaved changes" : "Saved"
                            color: settings.dirty ? theme.secondaryText : theme.dim
                            font.pixelSize: 10
                        }

                        Item { Layout.fillWidth: true }

                        AppButton {
                            text: "Load"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 52
                            Layout.preferredHeight: 26
                            Accessible.name: "Reload settings"
                            onClicked: settings.load()
                        }

                        AppButton {
                            text: "Save"
                            theme: root.visualTheme
                            enabled: settings.dirty
                            Layout.preferredWidth: 52
                            Layout.preferredHeight: 26
                            Accessible.name: "Save settings"
                            onClicked: settings.save()
                        }

                        AppButton {
                            text: "Close"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 56
                            Layout.preferredHeight: 26
                            Accessible.name: "Close settings"
                            onClicked: workflow.closeSettings()
                        }
                    }
                }
            }

            Item {
                id: filesPage
                objectName: "filesPage"

                // File imports are an explicit batch route.  Start with the
                // saved transcription route, but keep every picker change
                // local to this batch instead of mutating Settings.
                property var persistedTranscriptionRoute:
                    settings.routes["transcription"]
                property string batchExecution:
                    persistedTranscriptionRoute.providerId === "local_asr"
                    ? "local" : "cloud"
                property string batchProviderId:
                    persistedTranscriptionRoute.providerId || ""
                property string batchModelId:
                    persistedTranscriptionRoute.modelId || ""
                property bool batchRouteTouched: false
                property bool manualBatchModel: false
                readonly property var defaultAudioModels: ({
                    "gemini": "gemini-2.5-flash",
                    "openai": "whisper-1",
                    "groq": "whisper-large-v3-turbo",
                    "local_asr": "ggml-small"
                })

                function providerIdsForExecution(execution) {
                    var providers = settings.providersForScope("transcription")
                    var selected = []
                    for (var index = 0; index < providers.length; ++index) {
                        var providerId = providers[index]
                        if ((execution === "local" && providerId === "local_asr")
                                || (execution === "cloud" && providerId !== "local_asr"))
                            selected.push(providerId)
                    }
                    return selected
                }

                function modelIdsForProvider(providerId) {
                    var models = []
                    var addModel = function(model) {
                        var value = String(model || "").trim()
                        if (value !== "" && models.indexOf(value) < 0)
                            models.push(value)
                    }
                    var route = persistedTranscriptionRoute
                    if (route && route.providerId === providerId)
                        addModel(route.modelId)
                    var state = settings.providerStates[providerId]
                    if (state && state.models) {
                        for (var index = 0; index < state.models.length; ++index)
                            addModel(state.models[index])
                    }
                    addModel(defaultAudioModels[providerId])
                    return models
                }

                function defaultModelForProvider(providerId) {
                    var route = persistedTranscriptionRoute
                    if (route && route.providerId === providerId && route.modelId)
                        return route.modelId
                    var models = modelIdsForProvider(providerId)
                    return models.length > 0 ? models[0] : ""
                }

                function initializeBatchRoute() {
                    manualBatchModel = false
                    var route = persistedTranscriptionRoute
                    var providerId = route && route.providerId
                            ? route.providerId : ""
                    var execution = providerId === "local_asr" ? "local" : "cloud"
                    var providers = providerIdsForExecution(execution)
                    if (providers.indexOf(providerId) < 0)
                        providerId = providers.length > 0 ? providers[0] : ""
                    batchExecution = execution
                    batchProviderId = providerId
                    batchModelId = route && route.providerId === providerId
                            ? route.modelId : defaultModelForProvider(providerId)
                    batchRouteTouched = false
                }

                function selectBatchExecution(execution) {
                    manualBatchModel = false
                    var providers = providerIdsForExecution(execution)
                    var providerId = providers.indexOf(batchProviderId) >= 0
                            ? batchProviderId
                            : (providers.length > 0 ? providers[0] : "")
                    batchExecution = execution
                    batchProviderId = providerId
                    batchModelId = defaultModelForProvider(providerId)
                    batchRouteTouched = true
                }

                function selectBatchProvider(providerId) {
                    if (providerIdsForExecution(batchExecution).indexOf(providerId) < 0)
                        return
                    batchProviderId = providerId
                    manualBatchModel = false
                    batchModelId = defaultModelForProvider(providerId)
                    batchRouteTouched = true
                }

                function selectBatchModel(model) {
                    batchModelId = String(model || "").trim()
                    batchRouteTouched = true
                }

                function commitBatchModel() {
                    var value = batchModelId
                    if (manualBatchModel)
                        value = batchModelField.text
                    batchModelId = String(value || "").trim()
                    batchRouteTouched = true
                }

                function startBatch() {
                    commitBatchModel()
                    audioBatch.start(
                        audioBatch.selectedFiles,
                        batchProviderId,
                        batchModelId,
                        workflow.language,
                        workflow.mode
                    )
                }

                function retryBatch() {
                    commitBatchModel()
                    audioBatch.retryFailed(
                        batchProviderId,
                        batchModelId,
                        workflow.language,
                        workflow.mode
                    )
                }

                Component.onCompleted: initializeBatchRoute()

                Connections {
                    target: settings

                    function onConfigChanged() {
                        if (!filesPage.batchRouteTouched && !audioBatch.running)
                            filesPage.initializeBatchRoute()
                    }
                }

                FileDialog {
                    id: audioFileDialog
                    title: "Import audio files"
                    fileMode: FileDialog.OpenFiles
                    nameFilters: [
                        "Audio files (*.wav *.aif *.aiff *.au *.flac *.oga *.ogg *.wv)",
                        "All files (*)"
                    ]
                    onAccepted: {
                        var paths = []
                        for (var index = 0; index < selectedFiles.length; ++index)
                            paths.push(selectedFiles[index].toLocalFile())
                        audioBatch.setSelectedFiles(paths)
                    }
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1

                            Label {
                                Layout.fillWidth: true
                                text: "Import audio"
                                color: theme.text
                                font.pixelSize: 13
                                font.weight: Font.Bold
                            }

                            Label {
                                Layout.fillWidth: true
                                text: audioBatch.running
                                      ? "Transcribing selected files"
                                      : "Select local files to transcribe"
                                color: theme.dim
                                font.pixelSize: 10
                            }
                        }

                        AppButton {
                            iconSource: "icons/x.svg"
                            theme: root.visualTheme
                            quiet: true
                            enabled: !audioBatch.running
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                            Accessible.name: "Close audio import"
                            onClicked: workflow.closeFiles()
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 1
                        color: theme.border
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 4
                        columnSpacing: 7
                        rowSpacing: 5

                        Label {
                            text: "Route"
                            color: theme.dim
                            font.pixelSize: 10
                        }

                        SearchSelect {
                            id: batchExecutionBox
                            objectName: "batchExecutionBox"
                            visualTheme: theme
                            Layout.fillWidth: true
                            enabled: !audioBatch.running
                            caption: "Transcription route"
                            searchable: false
                            options: [{id: "local", label: "Local Whisper"}, {id: "cloud", label: "Cloud"}]
                            value: filesPage.batchExecution
                            onActivated: function(value) { filesPage.selectBatchExecution(value) }
                        }

                        Label {
                            text: "Provider"
                            color: theme.dim
                            font.pixelSize: 10
                        }

                        SearchSelect {
                            id: batchProviderBox
                            objectName: "batchProviderBox"
                            visualTheme: theme
                            Layout.fillWidth: true
                            enabled: !audioBatch.running
                            caption: "Transcription service"
                            searchable: false
                            options: filesPage.providerIdsForExecution(filesPage.batchExecution).map(function(id) { return {id: id, label: settings.providerName(id)} })
                            value: filesPage.batchProviderId
                            onActivated: function(value) { filesPage.selectBatchProvider(value) }
                        }

                        Label {
                            text: "Model"
                            color: theme.dim
                            font.pixelSize: 10
                        }

                        SearchSelect {
                            id: batchModelBox
                            objectName: "batchModelBox"
                            visualTheme: theme
                            Layout.fillWidth: true
                            enabled: !audioBatch.running
                            Layout.columnSpan: 3
                            caption: "Transcription model"
                            searchPlaceholder: "Search models"
                            options: filesPage.modelIdsForProvider(filesPage.batchProviderId).map(function(id) { return {id: id, label: id} })
                            value: filesPage.batchModelId
                            secondaryActionText: filesPage.batchExecution === "cloud" ? "Use model ID…" : ""
                            onSecondaryRequested: {
                                filesPage.manualBatchModel = true
                                Qt.callLater(function() { batchModelField.forceActiveFocus(); batchModelField.selectAll() })
                            }
                            onActivated: function(value) { filesPage.manualBatchModel = false; filesPage.selectBatchModel(value) }
                        }

                        Label {
                            visible: filesPage.manualBatchModel
                            text: "Model ID"
                            color: theme.dim
                            font.pixelSize: 10
                        }
                        SettingsField {
                            id: batchModelField
                            objectName: "batchModelField"
                            visualTheme: theme
                            visible: filesPage.manualBatchModel
                            enabled: !audioBatch.running
                            Layout.columnSpan: 3
                            Layout.fillWidth: true
                            text: filesPage.batchModelId
                            placeholderText: "For models not listed by your service"
                            Accessible.name: "Custom transcription model ID"
                            onEditingFinished: filesPage.selectBatchModel(text)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 5

                        AppButton {
                            text: "Choose files"
                            theme: root.visualTheme
                            enabled: !audioBatch.running
                            Layout.preferredWidth: 94
                            Layout.preferredHeight: 26
                            Accessible.name: "Choose local audio files"
                            onClicked: audioFileDialog.open()
                        }

                        Label {
                            Layout.fillWidth: true
                            text: audioBatch.selectedFiles.length === 0
                                  ? "No files selected"
                                  : audioBatch.selectedFiles.length + " file(s) selected"
                            color: theme.secondaryText
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        ScrollView {
                            anchors.fill: parent
                            anchors.margins: 6
                            clip: true

                            Column {
                                width: parent.width
                                spacing: 4

                                Repeater {
                                    model: audioBatch.results

                                    delegate: Rectangle {
                                        id: fileResultRow
                                        required property var modelData
                                        property bool hasTranscript: modelData.status === "succeeded"
                                                                      && modelData.text.length > 0
                                        property string copyLabel: "Copy"
                                        width: parent.width
                                        height: hasTranscript ? 166 : 34
                                        radius: 7
                                        color: "transparent"

                                        Rectangle {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            height: 1
                                            color: theme.border
                                        }

                                        Timer {
                                            id: transcriptCopyResetTimer
                                            interval: 900
                                            repeat: false
                                            onTriggered: fileResultRow.copyLabel = "Copy"
                                        }

                                        Connections {
                                            target: audioBatch

                                            function onCopyCompleted(path, success) {
                                                if (path !== fileResultRow.modelData.path)
                                                    return
                                                fileResultRow.copyLabel = success ? "Copied" : "Copy"
                                                if (success)
                                                    transcriptCopyResetTimer.restart()
                                            }
                                        }

                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 8
                                            anchors.rightMargin: 8
                                            anchors.topMargin: 4
                                            anchors.bottomMargin: 4
                                            spacing: 3

                                            Label {
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 22
                                                text: fileResultRow.modelData.name
                                                color: theme.text
                                                font.pixelSize: 10
                                                elide: Text.ElideMiddle
                                            }

                                            Label {
                                                text: fileResultRow.modelData.status
                                                color: fileResultRow.modelData.status === "failed"
                                                       ? theme.secondaryText : theme.dim
                                                font.pixelSize: 9
                                            }

                                            ScrollView {
                                                property bool fadeShown: fileResultRow.hasTranscript
                                                visible: fadeShown || opacity > 0.001
                                                opacity: fadeShown ? 1.0 : 0.0
                                                Behavior on opacity {
                                                    NumberAnimation {
                                                        duration: theme.fadeDuration
                                                        easing.type: Easing.OutCubic
                                                    }
                                                }
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 88
                                                clip: true

                                                SettingsArea {
                                                    id: transcriptText
                                                    visualTheme: theme
                                                    flat: true
                                                    width: parent.width
                                                    height: Math.max(implicitHeight, 88)
                                                    text: fileResultRow.modelData.text
                                                    readOnly: true
                                                    color: theme.secondaryText
                                                    font.pixelSize: 10
                                                    Accessible.name: "Transcript for "
                                                                      + fileResultRow.modelData.name
                                                }
                                            }

                                            RowLayout {
                                                property bool fadeShown: fileResultRow.hasTranscript
                                                visible: fadeShown || opacity > 0.001
                                                opacity: fadeShown ? 1.0 : 0.0
                                                Behavior on opacity {
                                                    NumberAnimation {
                                                        duration: theme.fadeDuration
                                                        easing.type: Easing.OutCubic
                                                    }
                                                }
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 25
                                                spacing: 5

                                                Label {
                                                    text: "Select text to reuse"
                                                    color: theme.dim
                                                    font.pixelSize: 9
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }

                                                AppButton {
                                                    text: fileResultRow.copyLabel
                                                    theme: root.visualTheme
                                                    enabled: !audioBatch.running
                                                    Layout.preferredWidth: 58
                                                    Layout.preferredHeight: 24
                                                    Accessible.name: "Copy transcript for "
                                                                      + fileResultRow.modelData.name
                                                    onClicked: {
                                                        if (audioBatch.copyFile(fileResultRow.modelData.path))
                                                            fileResultRow.copyLabel = "Copying…"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                Label {
                                    property bool fadeShown: audioBatch.results.length === 0
                                    visible: fadeShown || opacity > 0.001
                                    opacity: fadeShown ? 1.0 : 0.0
                                    Behavior on opacity {
                                        NumberAnimation {
                                            duration: theme.fadeDuration
                                            easing.type: Easing.OutCubic
                                        }
                                    }
                                    width: parent.width
                                    text: "Your selected files will appear here."
                                    color: theme.dim
                                    font.pixelSize: 10
                                    horizontalAlignment: Text.AlignHCenter
                                }
                            }
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        property bool fadeShown: audioBatch.lastError !== ""
                        visible: fadeShown || opacity > 0.001
                        opacity: fadeShown ? 1.0 : 0.0
                        Behavior on opacity {
                            NumberAnimation {
                                duration: theme.fadeDuration
                                easing.type: Easing.OutCubic
                            }
                        }
                        text: audioBatch.lastError
                        color: theme.secondaryText
                        font.pixelSize: 10
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 5

                        AppButton {
                            text: "Start"
                            theme: root.visualTheme
                            enabled: !audioBatch.running
                                     && audioBatch.selectedFiles.length > 0
                            Layout.preferredWidth: 54
                            Layout.preferredHeight: 26
                            Accessible.name: "Start audio transcription"
                            onClicked: filesPage.startBatch()
                        }

                        AppButton {
                            text: "Cancel"
                            theme: root.visualTheme
                            quiet: true
                            enabled: audioBatch.running
                            Layout.preferredWidth: 58
                            Layout.preferredHeight: 26
                            Accessible.name: "Cancel audio transcription"
                            onClicked: audioBatch.cancel()
                        }

                        AppButton {
                            text: "Retry"
                            theme: root.visualTheme
                            quiet: true
                            enabled: !audioBatch.running && audioBatch.canRetry
                            Layout.preferredWidth: 52
                            Layout.preferredHeight: 26
                            Accessible.name: "Retry failed audio files"
                            onClicked: filesPage.retryBatch()
                        }

                        Item { Layout.fillWidth: true }

                        AppButton {
                            text: "Close"
                            theme: root.visualTheme
                            quiet: true
                            enabled: !audioBatch.running
                            Layout.preferredWidth: 56
                            Layout.preferredHeight: 26
                            Accessible.name: "Close audio import"
                            onClicked: workflow.closeFiles()
                        }
                    }
                }
            }

            Item {
                id: translationPickerPage
                objectName: "translationPickerPage"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1

                            Label {
                                text: "Translate selection"
                                color: theme.text
                                font.pixelSize: 13
                                font.weight: Font.Bold
                            }

                            Label {
                                text: "Choose a target language"
                                color: theme.dim
                                font.pixelSize: 10
                            }
                        }

                        AppButton {
                            iconSource: "icons/x.svg"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                            Accessible.name: "Cancel translation"
                            onClicked: workflow.cancelTranslation()
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 1
                        color: theme.border
                    }

                    Flow {
                        id: translationOptionsFlow
                        objectName: "translationOptionsFlow"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 86
                        spacing: 6

                        Repeater {
                            model: workflow.translationOptions

                            delegate: AppButton {
                                required property var modelData
                                text: modelData.label
                                theme: root.visualTheme
                                width: 154
                                height: 34
                                Accessible.name: "Translate to " + modelData.label
                                onClicked: workflow.chooseTranslation(modelData.code)
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }

                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }

                        AppButton {
                            text: "Cancel"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 56
                            Layout.preferredHeight: 26
                            Accessible.name: "Cancel translation"
                            onClicked: workflow.cancelTranslation()
                        }
                    }
                }
            }
        }
    }
}
