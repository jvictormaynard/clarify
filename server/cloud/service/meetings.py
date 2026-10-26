"""Bounded, authenticated meeting routes with existing funded admission."""

import hashlib
import json
import tempfile
import uuid

from django.conf import settings
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from shared.meeting_contract import CHUNK_SECONDS, LANGUAGES, MAX_SOURCE_BYTES
from . import audio, groq, ledger, meeting_policy
from .api import ServiceView
from .middleware import take_rate
from .models import Operation


def _response(user, result):
    return Response(
        {
            **{k: v for k, v in result.items() if k != "_status"},
            "usage": ledger.usage(user),
        },
        status=result.get("_status", 200),
    )


def _run(user, operation_id, digest, audio_ms, perform, *, text=False):
    operation = None
    try:
        operation, fresh = ledger.reserve(
            user, operation_id, digest, audio_ms, text_operation=text
        )
        if not fresh:
            return _response(user, operation.result)
        outcome = perform(operation)
        result = {**outcome.result, "operation_id": str(operation_id)}
        with ledger.admission_lock():
            if Operation.objects.get(pk=operation.pk).state != "running":
                raise ledger.Rejected("operation_expired", 410)
            ledger.settle(
                operation,
                result=result,
                cost=outcome.cost,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                cost_estimated=outcome.cost_estimated,
            )
        return _response(user, result)
    except ledger.Rejected as error:
        result = {
            "code": error.code,
            "phase": "admission",
            "operation_id": str(operation_id),
            "_status": error.status,
        }
    except groq.ProviderFailure as error:
        result = {
            "code": "meeting_processing_failed",
            "phase": "summary" if text else "transcription",
            "operation_id": str(operation_id),
            "retry_operation": True,
            "_status": 502,
        }
        if operation:
            ledger.settle(
                operation,
                result=result,
                cost=error.cost,
                input_tokens=error.input_tokens,
                output_tokens=error.output_tokens,
            )
        return _response(user, result)
    except Exception:
        # No exception or provider response content reaches a client or a log.
        result = {
            "code": "meeting_processing_failed",
            "phase": "processing",
            "operation_id": str(operation_id),
            "retry_operation": True,
            "_status": 502,
        }
    if operation:
        ledger.settle(operation, result=result)
    return _response(user, result)


class MeetingTranscriptionView(ServiceView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        if not take_rate("meeting_audio", str(request.user.pk), 12):
            return Response({"code": "rate_limited"}, status=429)
        try:
            if set(request.data) != {"audio", "operation_id", "language"} or any(
                len(request.data.getlist(k)) != 1 for k in request.data
            ):
                raise ValueError()
            operation_id = uuid.UUID(request.data["operation_id"])
            language = request.data["language"]
            upload = request.FILES["audio"]
            if language not in LANGUAGES or not 0 < upload.size <= min(
                settings.CLARIFY_MAX_UPLOAD_BYTES, 12 * 1024 * 1024
            ):
                raise ValueError()
        except (ValueError, KeyError, AttributeError, TypeError):
            return Response({"code": "invalid_meeting_audio"}, status=400)
        try:
            digest = hashlib.sha256(
                ("meeting.asr.v1\n" + audio.fingerprint(upload, language)).encode()
            ).hexdigest()
            with tempfile.TemporaryDirectory(prefix="clarify-meeting-") as directory:
                path, duration_ms = audio.decode(upload, directory)
                if duration_ms > CHUNK_SECONDS * 1000:
                    raise ledger.Rejected("invalid_duration", 400)
                return _run(
                    request.user,
                    operation_id,
                    digest,
                    duration_ms,
                    lambda op: meeting_policy.transcribe(
                        path, duration_ms, language, op
                    ),
                )
        except ledger.Rejected as error:
            return Response(
                {
                    "code": error.code,
                    "phase": "validation",
                    "operation_id": str(operation_id),
                },
                status=error.status,
            )


class MeetingSummaryView(ServiceView):
    def post(self, request):
        if not take_rate("meeting_summary", str(request.user.pk), 6):
            return Response({"code": "rate_limited"}, status=429)
        try:
            if set(request.data) != {"operation_id", "source", "language"}:
                raise ValueError()
            operation_id = uuid.UUID(request.data["operation_id"])
            source, language = request.data["source"], request.data["language"]
            if (
                not isinstance(source, str)
                or not source.strip()
                or len(source.encode()) > MAX_SOURCE_BYTES
                or language not in LANGUAGES
            ):
                raise ValueError()
            digest = hashlib.sha256(
                json.dumps(
                    ["meeting.summary.v1", source, language], ensure_ascii=False
                ).encode()
            ).hexdigest()
        except (ValueError, KeyError, AttributeError, TypeError):
            return Response({"code": "invalid_meeting_summary"}, status=400)
        return _run(
            request.user,
            operation_id,
            digest,
            0,
            lambda op: meeting_policy.summarize(source, language, op),
            text=True,
        )
