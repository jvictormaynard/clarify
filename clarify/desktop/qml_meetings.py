"""Dedicated meeting presentation; workers never retain a QObject callback."""

from pathlib import Path

from PySide6.QtCore import (
    QObject,
    Property,
    QSaveFile,
    QTimer,
    QUrl,
    Signal,
    Slot,
    QIODevice,
)

from meeting_provider import MeetingProviderService
from meeting_store import MeetingStore
from meeting_workflow import MeetingWorkflow
from provider_types import ProviderCapability
from shared.localization import translate
from shared.meeting_contract import MeetingError
from windows_meeting_audio import WasapiSource
from workflow_config import WorkflowRoute, WorkflowScope, validate_workflow_route
from workflow_provider import WorkflowProviderService


class QmlMeetingController(QObject):
    stateChanged = Signal()
    openRequested = Signal()
    flushNotesRequested = Signal()

    def __init__(
        self,
        workflow=None,
        *,
        language=lambda: "auto",
        copy_runner=None,
        dispatch=lambda callback: callback(),
        error="",
        activate=True,
        editing_allowed=lambda: True,
        parent=None,
    ):
        super().__init__(parent)
        self.workflow = workflow
        self._language, self._copy, self._dispatch = language, copy_runner, dispatch
        self._error = error
        self._notes_pending = False
        self._enabled = False
        self._editing_allowed = editing_allowed
        self._note_contexts = {}
        self._state = {
            "active": False,
            "phase": "idle",
            "error": error,
            "selected": None,
            "meetings": [],
            "sources": {},
            "duration": 0,
            "managed": False,
            "context": "",
            "notesRoute": {},
            "editingAllowed": bool(editing_allowed()),
            "page": 0,
            "hasNext": False,
            "cleanupPending": False,
        }
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        if activate:
            self.activate()

    def activate(self):
        """Call only after the composition acquires the global instance guard."""
        self._enabled = True
        self._timer.start()
        self.refresh()

    @Property("QVariantMap", notify=stateChanged)
    def state(self):
        return self._state

    @property
    def blocks_processing(self):
        return self._notes_pending or self.workflow is not None and self.workflow.active

    @Slot(bool)
    def setNotesPending(self, pending):
        if self._notes_pending != pending:
            self._notes_pending = pending
            self.stateChanged.emit()

    @Property(bool, notify=stateChanged)
    def blocksProcessing(self):
        return self.blocks_processing

    @Property("QVariantList", constant=True)
    def notesProviders(self):
        if self.workflow is None:
            return []
        registry = self.workflow.provider.workflows.registry
        return [
            {
                "id": item.provider_id,
                "label": item.display_name,
                "model": item.default_text_model,
            }
            for item in registry.metadata
            if item.supports(ProviderCapability.TEXT_GENERATION)
        ]

    @Slot()
    def refresh(self):
        if self.workflow is None or not self._enabled:
            return
        try:
            state = self.workflow.snapshot()
            state["editingAllowed"] = bool(self._editing_allowed())
            if state.get("selected"):
                self._note_contexts[(state["context"], state["selected"]["id"])] = (
                    state["context"].rsplit(":", 1)[0]
                )
            if self._error:
                state["error"] = self._error
            if state != self._state:
                self._state = state
                self.stateChanged.emit()
        except Exception as error:
            self._state = {
                **self._state,
                "error": error.code
                if isinstance(error, MeetingError)
                else "meeting.store_error",
            }
            self.stateChanged.emit()

    def _run(self, action, *, editing=False):
        try:
            if self.workflow is None:
                raise MeetingError(self._error or "meeting.store_error")
            if not self._enabled:
                raise MeetingError("meeting.busy")
            if editing and not self._editing_allowed():
                raise MeetingError("meeting.busy")
            self._error = ""
            action()
            self.refresh()
            return True
        except Exception as error:
            self._error = (
                error.code
                if isinstance(error, MeetingError)
                else "meeting.processing_error"
            )
            self._state = {**self._state, "error": self._error}
            self.stateChanged.emit()
            return False

    @Slot()
    def open(self):
        self.refresh()
        self.openRequested.emit()

    @Slot(str, result=bool)
    def start(self, title=""):
        return self._run(
            lambda: self.workflow.start(title, self._language()), editing=True
        )

    @Slot()
    def stop(self):
        self._run(self.workflow.stop)

    @Slot()
    def cancel(self):
        self._run(self.workflow.cancel)

    @Slot(result=bool)
    def retry(self):
        return self._run(self.workflow.retry, editing=True)

    @Slot(result=bool)
    def summarize(self):
        return self._run(self.workflow.summarize, editing=True)

    @Slot(str, result=bool)
    def select(self, meeting_id):
        return self._run(lambda: self.workflow.select(meeting_id))

    @Slot(str, str, str, result=bool)
    def saveNotes(self, meeting_id, context, text):
        return self._run(
            lambda: self.workflow.save_notes(meeting_id, context, text), editing=True
        )

    @Slot(str, str, str, result=bool)
    def preserveDraft(self, meeting_id, context, text):
        def save():
            owner = self._note_contexts.get((context, meeting_id))
            if owner is None:
                raise MeetingError("meeting.scope_changed")
            # Explicit recovery of a manual draft writes only to the owner that
            # was shown before expiry. It cannot assign it to the new session.
            self.workflow.store.save_notes(owner, meeting_id, text)

        return self._run(save, editing=True)

    @Slot(str, str, str, bool, result=bool)
    def saveNotesRoute(self, context, provider, model, enabled):
        def save():
            if self.blocks_processing or context != self.workflow.snapshot()["context"]:
                raise MeetingError("meeting.busy")
            registry = self.workflow.provider.workflows.registry
            registry.adapter(provider, ProviderCapability.TEXT_GENERATION)
            if not model.strip() or len(model) > 256:
                raise MeetingError("meeting.configure_notes")
            route = WorkflowRoute(
                provider_id=provider,
                model_id=model.strip(),
                enabled=enabled,
                independent=True,
            )
            # Reuse the existing text-capability validator. The saved meeting
            # route is independent of the active selected-text rewrite route.
            route = validate_workflow_route(
                route, WorkflowScope.REWRITE, registry=registry
            )
            self.workflow.provider.workflows._connection(route)
            self.workflow.store.save_notes_route(
                self.workflow.provider.identity().owner, route
            )

        return self._run(save, editing=True)

    @Slot(int, result=bool)
    def changePage(self, delta):
        return self._run(lambda: self.workflow.change_page(delta), editing=True)

    @Slot(result=bool)
    def retryCleanup(self):
        return self._run(self.workflow.retry_cleanup, editing=True)

    def markdown(self):
        data = self.workflow.export()
        row = self._state.get("selected") or {}
        summary = data["summary"]
        if row.get("summary_stale"):
            summary = translate("meeting.summary_stale") + "\n\n" + summary
        return (
            "# "
            + (data["title"] or translate("meeting.untitled"))
            + "\n\n"
            + "\n\n".join(
                "## " + translate("meeting." + key) + "\n\n" + value
                for key, value in (
                    ("notes", data["notes"]),
                    ("summary", summary),
                    ("transcript", data["transcript"]),
                )
            )
            + "\n"
        )

    @Slot(result=bool)
    def copy(self):
        def copy():
            if self._copy:
                text = self.markdown()
                self._dispatch(lambda: self._copy(text))

        return self._run(copy, editing=True)

    @Slot(str, result=bool)
    def exportFile(self, url):
        def save():
            target = QUrl(url)
            if not target.isLocalFile():
                raise MeetingError("meeting.export_error")
            file = QSaveFile(str(Path(target.toLocalFile())))
            data = self.markdown().encode("utf-8")
            if (
                not file.open(QIODevice.WriteOnly)
                or file.write(data) != len(data)
                or not file.commit()
            ):
                raise MeetingError("meeting.export_error")

        return self._run(save, editing=True)

    @Slot(result=bool)
    def delete(self):
        return self._run(self.workflow.delete, editing=True)

    def shutdown(self):
        self.flushNotesRequested.emit()
        self._timer.stop()
        if self.workflow:
            self.workflow.shutdown()


def create_qml_meetings(
    runtime, *, can_start, workflow_config, editing_allowed=lambda: True, parent=None
):
    try:
        workflows = WorkflowProviderService(
            workflow_config,
            runtime.dictionary_service,
            registry=runtime.provider_registry,
            account=runtime.account,
        )
        provider = MeetingProviderService(workflows, runtime.account)
        store = MeetingStore(runtime.account.directory / "meetings")
        workflow = MeetingWorkflow(
            store, provider, source_factory=WasapiSource, can_start=can_start
        )
        return QmlMeetingController(
            workflow,
            language=lambda: runtime.repositories.config.load().ui.language,
            copy_runner=runtime.copy_result,
            dispatch=runtime.scheduler.run_dispatch,
            activate=False,
            editing_allowed=editing_allowed,
            parent=parent,
        )
    except MeetingError as error:
        return QmlMeetingController(
            error=error.code,
            activate=False,
            editing_allowed=editing_allowed,
            parent=parent,
        )
