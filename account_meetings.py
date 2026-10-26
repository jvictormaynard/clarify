"""Meeting calls through AccountService's session and HTTP boundary."""

from pathlib import Path
import uuid

from shared.meeting_contract import (
    LANGUAGES,
    MAX_SOURCE_BYTES,
    MAX_TRANSCRIPT_BYTES,
    MeetingError,
    MeetingIdentity,
    account_owner,
    bounded,
)

PROCESSING_PATHS = frozenset({"/v1/meetings/transcriptions", "/v1/meetings/summary"})


def identity(account):
    with account._lock:
        current = account.history_identity()
        managed = bool(account.managed)
        return MeetingIdentity(
            account_owner(current)
            if current
            else "unavailable"
            if managed
            else "guest",
            account._generation,
            managed,
            current,
        )


def validate(account, expected):
    if identity(account) != expected:
        raise MeetingError("meeting.scope_changed")
    if expected.managed and expected.account_identity is None:
        raise MeetingError("meeting.sign_in")


def process(
    account, expected, operation_id, language, *, path=None, source=None, cancel=None
):
    validate(account, expected)
    if expected.account_identity is None:
        raise MeetingError("meeting.sign_in")
    operation_id = str(uuid.UUID(operation_id))
    if language not in LANGUAGES:
        raise MeetingError("meeting.processing_error")
    if path is not None:
        with Path(path).open("rb") as stream:
            code, result = account._request(
                "POST",
                "/v1/meetings/transcriptions",
                cancel=cancel,
                expected_identity=expected.account_identity,
                data={"operation_id": operation_id, "language": language},
                files={"audio": ("meeting.wav", stream, "audio/wav")},
            )
        field, maximum = "transcript", MAX_TRANSCRIPT_BYTES
    else:
        bounded(source, MAX_SOURCE_BYTES)
        code, result = account._request(
            "POST",
            "/v1/meetings/summary",
            cancel=cancel,
            expected_identity=expected.account_identity,
            json={"operation_id": operation_id, "language": language, "source": source},
        )
        field, maximum = "summary", MAX_SOURCE_BYTES
    validate(account, expected)
    if code != 200:
        if code in {401, 403}:
            raise MeetingError("meeting.sign_in")
        if result.get("code") in {
            "allowance_exhausted",
            "allocation_waiting",
            "service_budget_exhausted",
            "hosted_unavailable",
        }:
            raise MeetingError("meeting.allowance")
        raise MeetingError(
            "meeting.processing_error",
            retry_operation=result.get("retry_operation") is True
            or result.get("code") == "operation_expired",
        )
    value = bounded(result.get(field), maximum)
    if field == "summary" and not value.strip():
        raise MeetingError("meeting.processing_error")
    return value
