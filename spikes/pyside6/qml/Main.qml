import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Dialogs 6.5
import QtQuick.Layouts 6.5
import QtQuick.Window 6.5

ApplicationWindow {
    id: root
    objectName: "clarifyMainWindow"
    property string displayedSurface: workflow.surface
    property real surfaceOpacity: 1
    width: (displayedSurface === "result"
            || displayedSurface === "voice_result"
            || displayedSurface === "voice_error" ? theme.resultWidth
            : (displayedSurface === "files"
               || displayedSurface === "translation_picker")
              ? theme.panelWidth : theme.windowWidth) * theme.uiScale
    height: (displayedSurface === "result"
             || displayedSurface === "voice_result"
             || displayedSurface === "voice_error"
             ? theme.resultHeight
             : (displayedSurface === "files"
                || displayedSurface === "translation_picker")
               ? theme.panelHeight : theme.windowHeight) * theme.uiScale
    minimumWidth: theme.windowWidth * theme.uiScale
    minimumHeight: theme.windowHeight * theme.uiScale
    property bool passivePresentation: false
    property bool presentationVisible: false
    visible: presentationVisible || opacity > 0.001
    opacity: presentationVisible ? 1.0 : 0.0
    Behavior on opacity {
        NumberAnimation {
            duration: theme.fadeDuration
            easing.type: Easing.OutCubic
        }
    }
    title: "Clarify"
    onVisibilityChanged: {
        if (root.visibility === Window.Hidden || root.visibility === Window.Minimized)
            settings.stopMicrophoneTest()
    }
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
           | (passivePresentation ? Qt.WindowDoesNotAcceptFocus : 0)

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
    Component.onCompleted: displayedSurface = workflow.surface
    Connections {
        target: workflow
        function onSurfaceChanged() {
            if (workflow.surface !== "idle") quickMenu.close()
            if (workflow.surface === root.displayedSurface) return
            surfaceTransition.stop()
            if (workflow.surface === "files" || root.displayedSurface === "files") {
                surfaceTransition.start()
            } else {
                root.displayedSurface = workflow.surface
                root.surfaceOpacity = 1
            }
        }
    }
    SequentialAnimation {
        id: surfaceTransition
        NumberAnimation { target: root; property: "surfaceOpacity"; to: 0; duration: theme.fadeDuration; easing.type: Easing.OutCubic }
        ScriptAction { script: root.displayedSurface = workflow.surface }
        NumberAnimation { target: root; property: "surfaceOpacity"; to: 1; duration: theme.fadeDuration; easing.type: Easing.OutCubic }
    }

    QuickMenu {
        id: quickMenu
        objectName: "quickMenu"
        parent: root.contentItem
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        visualTheme: root.visualTheme
        onAboutToShow: settings.refreshMicrophoneInventory()
        property var pendingAction: null
        function dispatchPendingAction() {
            var action = pendingAction
            pendingAction = null
            if (action) Qt.callLater(action)
        }
        function runAfterClose(action) {
            pendingAction = action
            close()
            // MenuItem may emit triggered after the popup has already closed.
            // Consume the action once in either signal ordering.
            Qt.callLater(function() {
                if (!quickMenu.visible) quickMenu.dispatchPendingAction()
            })
        }
        onClosed: dispatchPendingAction()

        QuickMenu {
            id: microphoneMenu
            objectName: "quickMicrophoneMenu"
            visualTheme: root.visualTheme
            title: "Microphone"
            icon.source: "icons/mic.svg"
            width: 360
            Instantiator {
                model: settings.microphoneDevices
                delegate: QuickMenuItem {
                    required property var modelData
                    required property int index
                    objectName: "quickMicrophoneOption" + index
                    visualTheme: root.visualTheme
                    text: modelData.label
                    checkable: true
                    checked: settings.quickMicrophoneId === modelData.id
                    onTriggered: {
                        microphoneMenu.close()
                        quickMenu.close()
                        if (!settings.selectQuickMicrophone(modelData.id))
                            workflow.showQuickNotice("Could not change microphone")
                    }
                }
                onObjectAdded: function(index, object) { microphoneMenu.insertItem(index, object) }
                onObjectRemoved: function(index, object) { microphoneMenu.removeItem(object) }
            }
        }
        QuickMenuItem {
            objectName: "quickPasteItem"
            visualTheme: root.visualTheme
            text: "Paste last transcript"
            icon.source: "icons/paste.svg"
            enabled: workflow.canPasteLastTranscription
            onTriggered: quickMenu.runAfterClose(function() { workflow.pasteLastTranscription() })
            ToolTip.visible: hovered && !enabled
            ToolTip.text: "Available after your first transcription this session"
        }
        QuickMenuItem {
            objectName: "quickFilesItem"
            visualTheme: root.visualTheme
            text: "Import audio files"
            icon.source: "icons/audio-lines.svg"
            onTriggered: quickMenu.runAfterClose(function() {
                workflow.openFiles()
                root.requestActivate()
            })
        }
        MenuSeparator {
            topPadding: 4; bottomPadding: 4
            contentItem: Rectangle { implicitHeight: 1; color: theme.controlPressed }
        }
        QuickMenuItem {
            objectName: "quickSettingsItem"
            visualTheme: root.visualTheme
            text: "Settings"
            icon.source: "icons/settings.svg"
            onTriggered: quickMenu.runAfterClose(function() {
                workflow.openSettings()
            })
        }
    }

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

    Rectangle {
        id: card
        objectName: "mainCard"
        opacity: root.surfaceOpacity
        enabled: !surfaceTransition.running
        width: root.width / theme.uiScale
        height: root.height / theme.uiScale
        anchors.centerIn: parent
        scale: theme.uiScale
        transformOrigin: Item.Center
        radius: root.displayedSurface === "idle"
                || root.displayedSurface === "recording"
                || root.displayedSurface === "processing"
                || root.displayedSurface === "voice_processing"
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
            currentIndex: root.displayedSurface === "result"
                          ? 1
                          : root.displayedSurface === "files" ? 2
                          : root.displayedSurface === "translation_picker" ? 3
                          : (root.displayedSurface === "voice_result"
                             || root.displayedSurface === "voice_error") ? 1 : 0

            Item {
                id: homePage
                objectName: "homePage"
                DragHandler {
                    id: windowDragHandler
                    objectName: "homeWindowDragHandler"
                    target: null
                    acceptedButtons: Qt.LeftButton
                    grabPermissions: PointerHandler.CanTakeOverFromItems | PointerHandler.CanTakeOverFromHandlersOfDifferentType
                    onActiveChanged: {
                        if (active) {
                            quickMenu.close()
                            root.startSystemMove()
                        }
                    }
                }

                RowLayout {
                    anchors.centerIn: parent
                    width: workflow.surface === "idle" ? implicitWidth : parent.width - 18
                    height: parent.height
                    spacing: 4

                    Item {
                        id: statusArea
                        Layout.fillWidth: workflow.surface !== "idle"
                        Layout.fillHeight: true
                        Layout.preferredWidth: 26
                        Layout.minimumWidth: 26
                        Layout.alignment: Qt.AlignVCenter

                        AppButton {
                            objectName: "microphoneButton"
                            anchors.centerIn: parent
                            width: 26
                            height: 26
                            theme: root.visualTheme
                            iconSource: "icons/mic.svg"
                            quiet: true
                            enabled: workflow.surface === "idle"
                                     || workflow.surface === "recording"
                            Accessible.name: workflow.surface === "recording"
                                             ? "Stop recording" : "Start recording"
                            onClicked: {
                                if (workflow.surface === "recording")
                                    workflow.stopRecording()
                                else
                                    workflow.startRecording()
                            }
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
                            quiet: true
                            Layout.preferredWidth: 36
                            Layout.preferredHeight: 26
                            Accessible.name: "Language: "
                                              + languageNames[workflow.language]

                            RoundedFlag {
                                displayScale: theme.uiScale
                                anchors.centerIn: parent
                                width: 21.333
                                height: 16
                                source: "flags/" + workflow.language + ".svg"
                            }
                            onClicked: {
                                quickMenu.close()
                                var currentIndex = supportedLanguages.indexOf(workflow.language)
                                var nextIndex = (currentIndex + 1) % supportedLanguages.length
                                workflow.setLanguage(supportedLanguages[nextIndex])
                            }
                        }

                        AppButton {
                            checked: quickMenu.visible
                            id: settingsButton
                            objectName: "settingsButton"
                            iconSource: "icons/settings.svg"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                            Accessible.name: "Open quick actions"
                            onClicked: {
                                if (quickMenu.visible) {
                                    quickMenu.close()
                                    return
                                }
                                var position = mapToItem(root.contentItem, width, height)
                                quickMenu.x = Math.max(0, position.x - quickMenu.width)
                                quickMenu.y = root.height + 8
                                quickMenu.open()
                            }
                        }

                        AppButton {
                            id: closeButton
                            objectName: "closeButton"
                            iconSource: "icons/x.svg"
                            theme: root.visualTheme
                            quiet: true
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                            Accessible.name: "Close Clarify"
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
