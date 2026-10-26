"""Meeting policy with existing workflow routes, registry and account ownership."""

from account_meetings import identity, validate
from dataclasses import dataclass
from contextlib import contextmanager

from shared.meeting_contract import SUMMARY_INSTRUCTION, MeetingError
from local_asr import PROVIDER_ID as LOCAL_ASR_PROVIDER_ID
from provider_types import RewriteRequest, TranscriptionRequest
from workflow_config import WorkflowRoute, WorkflowScope, validate_workflow_route


@dataclass(frozen=True)
class MeetingRoutes:
    transcription: WorkflowRoute
    transcription_connection: object
    notes: WorkflowRoute
    notes_connection: object

    def persisted(self):
        from dataclasses import asdict

        return {
            "transcription": asdict(self.transcription),
            "notes": asdict(self.notes),
        }


class MeetingProviderService:
    def __init__(self, workflows, account):
        self.workflows, self.account = workflows, account

    def identity(self):
        return identity(self.account)

    def validate(self, expected):
        validate(self.account, expected)

    @contextmanager
    def publication(self, expected):
        # Account before storage is the existing lock order. A session cannot
        # change between final validation and the local commit.
        with self.account._lock:
            self.validate(expected)
            yield

    def acquire(self):
        if not self.account.begin_change():
            raise MeetingError("meeting.busy")

    def release(self):
        self.account.end_change()

    def snapshot(self, expected, persisted=None, notes=None, *, action="record"):
        self.validate(expected)
        if expected.managed:
            return None
        route = (
            WorkflowRoute.from_mapping(persisted["transcription"])
            if persisted
            else WorkflowRoute(enabled=False)
            if action == "summary"
            else self.workflows._route(WorkflowScope.TRANSCRIPTION)
        )
        note_route = (
            WorkflowRoute.from_mapping(persisted["notes"]) if persisted else notes
        )
        note_route = note_route or WorkflowRoute(enabled=False)
        connection = note_connection = None
        if action != "summary":
            route = validate_workflow_route(
                route, WorkflowScope.TRANSCRIPTION, registry=self.workflows.registry
            )
            connection = self.workflows._connection(route)
            if route.provider_id != LOCAL_ASR_PROVIDER_ID and not connection.api_key:
                raise MeetingError("meeting.configure_asr")
        if action == "summary":
            if not note_route.enabled:
                raise MeetingError("meeting.notes_disabled")
            note_route = validate_workflow_route(
                note_route, WorkflowScope.REWRITE, registry=self.workflows.registry
            )
            note_connection = self.workflows._connection(note_route)
            if not note_connection.api_key:
                raise MeetingError("meeting.configure_notes")
        return MeetingRoutes(route, connection, note_route, note_connection)

    def transcribe(self, expected, routes, chunk, path, language, cancel):
        self.validate(expected)
        if expected.managed:
            return self.account.transcribe_meeting(
                expected, chunk["operation_id"], path, language, cancel=cancel
            )
        route = routes.transcription
        request = TranscriptionRequest(
            audio_path=path,
            model=route.model_id,
            language=language,
            instruction="Transcribe only the speech in the audio. Preserve its language. Return only the transcript.",
            prompt="Transcribe only the speech. Do not rewrite, summarize, or identify speakers.",
            temperature=0,
        )
        result = self.workflows.registry.transcribe(
            route.provider_id,
            request,
            routes.transcription_connection,
            cancel_token=cancel,
        )
        return result.text

    def summarize(self, expected, routes, operation_id, source, language, cancel):
        self.validate(expected)
        if expected.managed:
            return self.account.summarize_meeting(
                expected, operation_id, source, language, cancel=cancel
            )
        route = routes.notes
        if not route.enabled:
            raise MeetingError("meeting.notes_disabled")
        request = RewriteRequest(
            text=source,
            model=route.model_id,
            language=language,
            instruction=SUMMARY_INSTRUCTION,
            source_message=source,
        )
        return self.workflows.registry.rewrite(
            route.provider_id, request, routes.notes_connection, cancel_token=cancel
        ).text
