import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5
import QtQuick.Dialogs 6.5

ApplicationWindow {
    id: root
    objectName: "clarifyMeetingWindow"
    title: qsTr("meeting.title")
    width: 1100
    height: 780
    minimumWidth: 840
    minimumHeight: 620
    visible: false
    color: theme.card
    property Theme visualTheme: theme
    font.pixelSize: 13
    Theme { id: theme; fieldFontSize: 13; fieldHeight: 36; dim: "#999999" }
    component MeetingButton: AppButton {
        id: button
        theme: root.visualTheme
        implicitWidth: Math.max(88, buttonMetrics.advanceWidth(text) + 24)
        FontMetrics { id: buttonMetrics; font.pixelSize: 12 }
    }
    component MeetingTab: TabButton {
        id: tab
        background: Rectangle { color: tab.checked ? theme.controlHover : theme.control; radius: theme.fieldRadius }
        contentItem: Label { text: tab.text; color: tab.checked ? theme.text : theme.subtleText; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; padding: 10 }
    }
    palette.window: theme.card
    palette.windowText: theme.text
    palette.base: theme.control
    palette.text: theme.text
    palette.button: theme.control
    palette.buttonText: theme.text
    palette.highlight: theme.controlPressed
    palette.highlightedText: theme.text
    palette.placeholderText: theme.subtleText
    readonly property var view: meetings.state
    readonly property var current: view.selected
    property string notesId: ""
    property string notesContext: ""
    property bool notesLoading: false
    property bool notesDirty: false
    property bool notesSaving: false
    onNotesDirtyChanged: meetings.setNotesPending(notesDirty)

    function saveNotes() {
        notesTimer.stop()
        if (!notesDirty || notesId === "") return true
        if (notesSaving) return false
        notesSaving = true
        var saved = meetings.saveNotes(notesId, notesContext, personalNotes.text)
        notesSaving = false
        if (!saved) return false
        notesDirty = false
        return true
    }
    function loadNotes() {
        if (notesSaving) return
        var nextId = current ? current.id : ""
        if (notesId === nextId && notesContext === view.context) return
        // Pending edits keep their original scope and ID. A late save is rejected
        // by the controller, never redirected to the next account or meeting.
        if (notesDirty && !saveNotes()) return
        notesLoading = true
        notesId = nextId
        notesContext = view.context
        personalNotes.text = current ? current.notes : ""
        notesLoading = false
    }
    onCurrentChanged: loadNotes()
    onClosing: function(close) { close.accepted = false; if (saveNotes()) root.hide() }
    Connections {
        target: meetings
        function onOpenRequested() { root.show(); root.raise(); root.requestActivate() }
        function onStateChanged() { root.loadNotes() }
        function onFlushNotesRequested() { root.saveNotes() }
    }
    Timer { id: notesTimer; interval: 500; onTriggered: root.saveNotes() }
    FileDialog {
        id: exportDialog
        title: qsTr("meeting.export")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "md"
        nameFilters: [qsTr("meeting.markdown_filter")]
        onAccepted: { root.saveNotes(); meetings.exportFile(selectedFile.toString()) }
    }
    Dialog {
        id: deleteDialog
        title: qsTr("meeting.delete_title")
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        Label { text: qsTr("meeting.delete_warning"); color: theme.text; wrapMode: Text.WordWrap; width: 360 }
        onAccepted: { notesDirty = false; meetings.delete() }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14
        enabled: view.editingAllowed
        RowLayout {
            Label { text: qsTr("meeting.title"); color: theme.text; font.pixelSize: 24; Layout.fillWidth: true }
            Label { text: qsTr("meeting." + view.phase) + (view.active ? " · " + view.duration + "s" : ""); color: theme.secondaryText; Accessible.role: Accessible.StatusBar }
            MeetingButton { text: qsTr("meeting.new"); enabled: !view.active; onClicked: { if (root.saveNotes()) meetings.start(titleField.text) } }
            MeetingButton { text: qsTr("meeting.stop"); visible: view.phase === "recording"; onClicked: meetings.stop() }
            MeetingButton { text: qsTr("meeting.cancel"); visible: view.active; onClicked: { root.saveNotes(); meetings.cancel() } }
        }
        Label { text: qsTr("meeting.limits"); color: theme.subtleText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        RowLayout {
            TextField { id: titleField; placeholderText: qsTr("meeting.title_placeholder"); Accessible.name: placeholderText; maximumLength: 120; Layout.fillWidth: true; enabled: !view.active }
            Label { text: current ? current.language : ""; color: theme.subtleText }
        }
        RowLayout {
            visible: Object.keys(view.sources).length > 0
            Repeater {
                model: ["microphone", "system"]
                delegate: Rectangle {
                    required property string modelData
                    readonly property var source: view.sources[modelData] || {state: "idle", level: 0, warning: ""}
                    Layout.fillWidth: true
                    implicitHeight: source.warning ? 92 : 68
                    radius: theme.fieldRadius
                    color: theme.control
                    border.color: theme.border
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 10; spacing: 4
                        Label { text: qsTr("meeting." + modelData) + " · " + qsTr("meeting." + source.state); color: theme.text }
                        ProgressBar { from: 0; to: 1; value: source.level; Layout.fillWidth: true; Accessible.name: qsTr("meeting." + modelData) }
                        Label { visible: source.warning !== ""; text: qsTr(source.warning); color: theme.secondaryText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    }
                }
            }
        }
        Label { visible: view.error !== ""; text: qsTr(view.error); color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true; Accessible.role: Accessible.AlertMessage }
        RowLayout {
            visible: view.cleanupPending
            Label { text: qsTr("meeting.delete_pending"); color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            MeetingButton { text: qsTr("meeting.retry_cleanup"); enabled: !view.active; onClicked: meetings.retryCleanup() }
        }
        RowLayout {
            visible: notesDirty && notesContext !== view.context
            Label { text: qsTr("meeting.draft_recovery"); color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            MeetingButton {
                text: qsTr("meeting.keep_draft")
                onClicked: {
                    notesSaving = true
                    var saved = meetings.preserveDraft(notesId, notesContext, personalNotes.text)
                    notesSaving = false
                    if (saved) { notesDirty = false; root.loadNotes() }
                }
            }
            MeetingButton { text: qsTr("meeting.discard_draft"); onClicked: { notesDirty = false; root.loadNotes() } }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 18
            Rectangle {
                Layout.preferredWidth: 215
                Layout.fillHeight: true
                color: theme.resultSurface
                radius: theme.fieldRadius
                ScrollView {
                    id: meetingList
                    anchors.fill: parent; anchors.margins: 8
                    anchors.bottomMargin: pagination.visible ? 50 : 8
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: meetingList.availableWidth
                        Repeater {
                            model: view.meetings
                            delegate: MeetingButton {
                                required property var modelData
                                theme: root.visualTheme
                                Layout.fillWidth: true
                                implicitWidth: 0
                                text: (modelData.title || qsTr("meeting.untitled")) + "\n" + Qt.formatDate(new Date(modelData.created * 1000), "yyyy-MM-dd")
                                implicitHeight: 58
                                checked: current && current.id === modelData.id
                                enabled: !view.active
                                onClicked: { if (root.saveNotes()) meetings.select(modelData.id) }
                            }
                        }
                    }
                }
                RowLayout {
                    id: pagination
                    anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 8
                    visible: view.page > 0 || view.hasNext
                    MeetingButton { text: qsTr("meeting.previous"); implicitWidth: 88; enabled: !view.active && view.page > 0; onClicked: { if (root.saveNotes()) meetings.changePage(-1) } }
                    MeetingButton { text: qsTr("meeting.next"); implicitWidth: 88; enabled: !view.active && view.hasNext; onClicked: { if (root.saveNotes()) meetings.changePage(1) } }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: current !== null
                TabBar {
                    id: tabs
                    Layout.fillWidth: true
                    MeetingTab { text: qsTr("meeting.notes") }
                    MeetingTab { text: qsTr("meeting.transcript") }
                    MeetingTab { text: qsTr("meeting.summary") }
                }
                StackLayout {
                    currentIndex: tabs.currentIndex
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    ScrollView {
                        clip: true
                        TextArea {
                            id: personalNotes
                            objectName: "meetingPersonalNotes"
                            placeholderText: qsTr("meeting.notes_placeholder")
                            Accessible.name: qsTr("meeting.notes")
                            color: theme.text
                            wrapMode: TextEdit.Wrap
                            selectByMouse: true
                            onTextChanged: { if (!root.notesLoading) { root.notesDirty = true; notesTimer.restart() } }
                            onActiveFocusChanged: { if (!activeFocus) root.saveNotes() }
                        }
                    }
                    ScrollView {
                        clip: true
                        TextArea {
                            objectName: "meetingTranscript"
                            readOnly: true
                            selectByMouse: true
                            color: theme.text
                            wrapMode: TextEdit.Wrap
                            text: current ? current.chunks.map(function(c) {
                                return "[" + (c.start_ms / 1000).toFixed(1) + "s · " + qsTr("meeting." + c.source) + "] " + (c.state === "transcribed" ? c.transcript : qsTr(c.error || "meeting.pending"))
                            }).join("\n\n") : ""
                            Accessible.name: qsTr("meeting.transcript")
                        }
                    }
                    ColumnLayout {
                        Label { visible: current && current.summary_stale; text: qsTr("meeting.summary_stale"); color: theme.secondaryText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            TextArea { objectName: "meetingSummary"; readOnly: true; selectByMouse: true; color: theme.text; wrapMode: TextEdit.Wrap; text: current ? current.summary : ""; Accessible.name: qsTr("meeting.summary") }
                        }
                    }
                }
                RowLayout {
                    MeetingButton { text: qsTr("meeting.retry"); enabled: !view.active; onClicked: { root.saveNotes(); meetings.retry() } }
                    MeetingButton { text: qsTr("meeting.generate"); enabled: !view.active; onClicked: { if (root.saveNotes()) meetings.summarize() } }
                    Item { Layout.fillWidth: true }
                    MeetingButton { text: qsTr("meeting.copy"); onClicked: { if (root.saveNotes()) meetings.copy() } }
                    MeetingButton { text: qsTr("meeting.export"); onClicked: { if (root.saveNotes()) exportDialog.open() } }
                    MeetingButton { text: qsTr("meeting.delete"); enabled: !view.active; onClicked: deleteDialog.open() }
                }
            }
            Label { visible: current === null; Layout.fillWidth: true; text: qsTr("meeting.empty"); color: theme.subtleText; wrapMode: Text.WordWrap }
        }
        RowLayout {
            visible: !view.managed
            enabled: !view.active
            Label { text: qsTr("meeting.notes_route"); color: theme.secondaryText }
            CheckBox { id: notesEnabled; text: qsTr("meeting.enable_notes"); checked: view.notesRoute.enabled || false }
            ComboBox {
                id: noteProvider
                model: meetings.notesProviders
                textRole: "label"
                valueRole: "id"
                currentIndex: Math.max(0, indexOfValue(view.notesRoute.provider_id || "openai"))
                onActivated: noteModel.text = model[currentIndex].model
            }
            TextField { id: noteModel; text: view.notesRoute.model_id || ""; placeholderText: qsTr("meeting.model"); Accessible.name: placeholderText; Layout.fillWidth: true; maximumLength: 256 }
            MeetingButton { text: qsTr("meeting.save_route"); onClicked: meetings.saveNotesRoute(view.context, noteProvider.currentValue, noteModel.text, notesEnabled.checked) }
        }
    }
}
