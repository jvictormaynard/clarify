import tempfile
import uuid
import hashlib
import json
import logging

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import exceptions, permissions
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler as drf_handler

from dictionary_snippets import (
    MAX_ACCOUNT_SNIPPET_BYTES,
    DictionaryEntry,
    DictionarySnippets,
    Snippet,
)
from . import audio, groq, history, ledger, text_actions
from .middleware import take_rate
from .models import Dictionary, Operation, SnippetLibrary


logger = logging.getLogger(__name__)
MAX_DICTATION_RESULT_BYTES = 384 * 1024


def processing_failure(
    user,
    operation_id,
    code,
    phase,
    status,
    *,
    operation=None,
    replayable=False,
    cost=None,
    input_tokens=0,
    output_tokens=0,
    cost_estimated=False,
):
    """Expose bounded diagnostics, never exception text or provider responses."""
    result = {"code": code, "phase": phase, "operation_id": str(operation_id)}
    if operation:
        ledger.settle(
            operation,
            result=result if replayable else None,
            cost=cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimated=cost_estimated,
        )
    logger.warning(
        "processing_failure code=%s phase=%s operation_id=%s",
        code,
        phase,
        operation_id,
    )
    return Response(
        {
            **result,
            "usage": ledger.usage(user),
        },
        status=status,
    )


def exception_handler(error, context):
    response = drf_handler(error, context)
    if response is not None:
        response.data = {
            "code": "authentication_required"
            if response.status_code in (401, 403)
            else "invalid_request"
        }
    return response


class Verified(permissions.BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.is_active
            and EmailAddress.objects.filter(
                user=request.user,
                email__iexact=request.user.email,
                verified=True,
                primary=True,
            ).exists()
        )


class ServiceView(APIView):
    permission_classes = [permissions.IsAuthenticated, Verified]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.query_params:
            raise exceptions.ValidationError()
        if not take_rate("account", str(request.user.pk), 120):
            raise exceptions.Throttled()


class AccountView(ServiceView):
    def get(self, request):
        return Response(
            {
                "id": str(request.user.pk),
                "email": request.user.email,
                "usage": ledger.usage(request.user),
                "output_preferences_supported": True,
            }
        )

    def delete(self, request):
        if request.data != {"confirm": True}:
            return Response({"code": "confirmation_required"}, status=400)
        with ledger.admission_lock():
            # Serializes deletion with admissions and settlements.
            # History takes the same parent row lock before inserting children.
            # Acquire it before Django's deletion collector visits those rows.
            user = (
                get_user_model()
                .objects.select_for_update()
                .filter(pk=request.user.pk)
                .first()
            )
            if user is None:
                return Response(status=204)
            if Operation.objects.filter(user=request.user, state="running").exists():
                return Response({"code": "account_busy"}, status=409)
            Operation.objects.filter(user=request.user).update(
                result={}, fingerprint=""
            )
            user.delete()
        return Response(status=204)


class UsageView(ServiceView):
    def get(self, request):
        return Response(ledger.usage(request.user))


class HistorySyncView(ServiceView):
    def post(self, request):
        try:
            return Response(history.synchronize(request.user, request.data))
        except history.Conflict:
            return Response({"code": "history_conflict"}, status=409)
        except history.Capacity:
            return Response({"code": "history_full"}, status=507)


def validate_entries(entries):
    if not isinstance(entries, list) or len(entries) > 512:
        raise ValueError()
    if any(
        not isinstance(item, dict)
        or set(item) - {"term", "pronunciation", "aliases", "enabled"}
        for item in entries
    ):
        raise ValueError()
    document = DictionarySnippets(
        tuple(DictionaryEntry.from_mapping(item) for item in entries)
    )
    return [entry.to_mapping() for entry in document.dictionary]


class DictionaryView(ServiceView):
    def get(self, request):
        item, _ = Dictionary.objects.get_or_create(user=request.user)
        return Response({"revision": item.revision, "entries": item.entries})

    def put(self, request):
        try:
            if (
                set(request.data) != {"revision", "entries"}
                or type(request.data["revision"]) is not int
                or request.data["revision"] < 0
            ):
                raise ValueError()
            entries = validate_entries(request.data["entries"])
        except (KeyError, TypeError, ValueError):
            return Response({"code": "invalid_dictionary"}, status=400)
        with transaction.atomic():
            Dictionary.objects.get_or_create(user=request.user)
            item = Dictionary.objects.select_for_update().get(user=request.user)
            if request.data["revision"] != item.revision:
                return Response({"code": "dictionary_conflict"}, status=409)
            item.entries, item.revision = entries, item.revision + 1
            item.save()
        return Response({"revision": item.revision, "entries": item.entries})


class SnippetView(ServiceView):
    def get(self, request):
        item = SnippetLibrary.objects.filter(user=request.user).first()
        return Response(
            {"revision": item.revision, "entries": item.entries}
            if item
            else {"revision": 0, "entries": []}
        )

    def put(self, request):
        try:
            if (
                set(request.data) != {"revision", "entries"}
                or type(request.data["revision"]) is not int
                or request.data["revision"] < 0
            ):
                raise ValueError()
            entries = request.data["entries"]
            if not isinstance(entries, list) or len(entries) > 512:
                raise ValueError()
            if any(
                not isinstance(item, dict)
                or set(item) - {"trigger", "replacement", "enabled", "case_sensitive"}
                for item in entries
            ):
                raise ValueError()
            document = DictionarySnippets(
                snippets=tuple(Snippet.from_mapping(item) for item in entries)
            )
            if any(not item.replacement.strip() for item in document.snippets):
                raise ValueError()
            entries = [item.to_mapping() for item in document.snippets]
            if (
                len(
                    json.dumps(
                        entries, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                )
                > MAX_ACCOUNT_SNIPPET_BYTES
            ):
                return Response({"code": "snippets_too_large"}, status=400)
        except (KeyError, TypeError, ValueError):
            return Response({"code": "invalid_snippets"}, status=400)
        with transaction.atomic():
            # Account deletion takes this parent lock before collecting children.
            # A request verified earlier must not insert after the collector ran.
            owner = (
                get_user_model()
                .objects.select_for_update()
                .filter(pk=request.user.pk)
                .first()
            )
            if owner is None:
                raise exceptions.PermissionDenied()
            SnippetLibrary.objects.get_or_create(user=request.user)
            item = SnippetLibrary.objects.select_for_update().get(user=request.user)
            if request.data["revision"] != item.revision:
                return Response({"code": "snippet_conflict"}, status=409)
            item.entries, item.revision = entries, item.revision + 1
            item.save()
        return Response({"revision": item.revision, "entries": item.entries})


class TextActionsView(ServiceView):
    def get(self, request):
        return Response(text_actions.read(request.user))

    def put(self, request):
        try:
            if not isinstance(request.data, dict) or set(request.data) != {
                "expected_revision",
                "actions",
            }:
                raise ValueError()
            return Response(
                text_actions.replace(
                    request.user,
                    request.data["expected_revision"],
                    request.data["actions"],
                )
            )
        except text_actions.Conflict as error:
            return Response(
                {"code": "text_actions_conflict", **error.current}, status=409
            )
        except (KeyError, TypeError, ValueError):
            return Response({"code": "invalid_text_actions"}, status=400)
        except ledger.Rejected as error:
            return Response({"code": error.code}, status=error.status)


class DictationView(ServiceView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        if (
            not settings.CLARIFY_FUNDED_ENABLED
            or not settings.CLARIFY_GROQ_KEY
            or not request.user.funded_access
        ):
            return Response({"code": "hosted_unavailable"}, status=503)
        if not take_rate("dictation", str(request.user.pk), 6):
            return Response({"code": "rate_limited"}, status=429)
        try:
            from shared.dictation_policy import cleanup_level as parse_cleanup_level
            from shared.writing_style_policy import writing_style as parse_writing_style
            from shared.output_preferences import (
                output_language as parse_output_language,
            )

            if set(request.data) - {
                "audio",
                "operation_id",
                "language",
                "cleanup_level",
                "writing_style",
                "output_language",
                "text_action_id",
                "text_action_revision",
                "text_action_language",
            }:
                raise ValueError()
            level = parse_cleanup_level(request.data.get("cleanup_level"))
            style = parse_writing_style(request.data.get("writing_style"))
            target = parse_output_language(request.data.get("output_language"))
            if any(len(request.data.getlist(key)) != 1 for key in request.data):
                raise ValueError()
            operation_id = uuid.UUID(request.data["operation_id"])
            language = request.data.get("language", "auto")
            if language not in {"auto", "pt", "en", "es", "de", "ru"}:
                raise ValueError()
            action_id = request.data.get("text_action_id")
            action_revision = request.data.get("text_action_revision")
            action_language = request.data.get("text_action_language", "auto")
            if action_id is not None or action_revision is not None:
                if (
                    not text_actions.valid_id(action_id)
                    or not isinstance(action_revision, str)
                    or not action_revision.isascii()
                    or not action_revision.isdecimal()
                    or not text_actions.valid_revision(int(action_revision), minimum=1)
                    or action_language not in text_actions.LANGUAGES
                ):
                    raise ValueError()
                action_revision = int(action_revision)
            elif "text_action_language" in request.data:
                raise ValueError()
            upload = request.FILES["audio"]
            if not 0 < upload.size <= settings.CLARIFY_MAX_UPLOAD_BYTES:
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError):
            return Response({"code": "invalid_audio_request"}, status=400)
        operation = None
        outcome = None
        action = None
        try:
            digest = audio.fingerprint(
                upload,
                language,
                cleanup_level=level,
                writing_style=style,
                **({"output_language": target} if target is not None else {}),
            )
            if action_id is not None:
                digest = hashlib.sha256(
                    json.dumps(
                        [
                            "dictation-text-action",
                            digest,
                            action_id,
                            action_revision,
                            action_language,
                        ],
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()
                previous = ledger.replay(request.user, operation_id, digest)
                if previous is not None:
                    return Response(
                        {**previous.result, "usage": ledger.usage(request.user)},
                        status=422
                        if previous.result.get("code") == "snippet_result_too_large"
                        else 200,
                    )
                action = text_actions.resolve(
                    request.user, action_id, action_revision, action_language
                )
            with tempfile.TemporaryDirectory(prefix="clarify-cloud-") as directory:
                path, duration_ms = audio.decode(upload, directory)
                operation, fresh = ledger.reserve(
                    request.user, operation_id, digest, duration_ms
                )
                if not fresh:
                    return Response(
                        {**operation.result, "usage": ledger.usage(request.user)},
                        status=422
                        if operation.result.get("code") == "snippet_result_too_large"
                        else 200,
                    )
                vocabulary = Dictionary.objects.filter(user=request.user).first()
                snippets = SnippetLibrary.objects.filter(user=request.user).first()
                outcome = groq.dictation(
                    path,
                    duration_ms,
                    vocabulary.entries if vocabulary else [],
                    language,
                    snippets=snippets.entries if snippets else [],
                    cleanup_level=level,
                    writing_style=style,
                    **({"output_language": target} if target is not None else {}),
                    cost_budget=operation.reserved_cost,
                    authorize=lambda total: ledger.authorize(operation, total),
                    **(
                        {"text_action": action, "text_action_language": action_language}
                        if action is not None
                        else {}
                    ),
                )
                if outcome.result.get("snippet_expanded") is True and any(
                    len(outcome.result[name].encode("utf-8")) > history.MAX_TEXT_BYTES
                    for name in ("transcript", "text")
                ):
                    # Both clients save the original and final text through the
                    # existing history protocol before publishing a result.
                    raise groq.SnippetResultTooLarge()
                with ledger.admission_lock():
                    current = Operation.objects.get(pk=operation.pk)
                    if (
                        current.state != "running"
                        or current.lease_until <= timezone.now()
                    ):
                        raise ledger.Rejected("operation_expired", 410)
                    ledger.settle(
                        operation,
                        result=outcome.result,
                        cost=outcome.cost,
                        input_tokens=outcome.input_tokens,
                        output_tokens=outcome.output_tokens,
                        cost_estimated=outcome.cost_estimated,
                    )
                    result = {**outcome.result, "usage": ledger.usage(request.user)}
                    if (
                        len(
                            request.accepted_renderer.render(
                                result,
                                request.accepted_media_type,
                                self.get_renderer_context(),
                            )
                        )
                        > MAX_DICTATION_RESULT_BYTES
                    ):
                        raise groq.SnippetResultTooLarge()
                return Response(result)
        except ledger.Rejected as error:
            return processing_failure(
                request.user,
                operation_id,
                error.code,
                "validation"
                if error.code in {"invalid_audio", "invalid_duration"}
                else "admission",
                error.status,
                operation=operation,
            )
        except groq.NoSpeech as error:
            return processing_failure(
                request.user,
                operation_id,
                "no_speech",
                "transcription",
                422,
                operation=operation,
                cost=error.cost,
            )
        except groq.SnippetResultTooLarge:
            return processing_failure(
                request.user,
                operation_id,
                "snippet_result_too_large",
                "processing",
                422,
                operation=operation,
                replayable=True,
                cost=outcome.cost if outcome else None,
                input_tokens=outcome.input_tokens if outcome else 0,
                output_tokens=outcome.output_tokens if outcome else 0,
                cost_estimated=outcome.cost_estimated if outcome else False,
            )
        except groq.ProviderFailure as error:
            return processing_failure(
                request.user,
                operation_id,
                "transcription_failed",
                "transcription",
                502,
                operation=operation,
                cost=error.cost,
            )
        except exceptions.PermissionDenied:
            raise
        except Exception:
            return processing_failure(
                request.user,
                operation_id,
                "processing_failed",
                "processing",
                502,
                operation=operation,
            )


class TextView(ServiceView):
    """Bounded rewrite/translation, never a general provider proxy."""

    saved_actions = False

    def post(self, request):
        if not take_rate("text", str(request.user.pk), 6):
            return Response({"code": "rate_limited"}, status=429)
        try:
            from shared.writing_style_policy import writing_style as parse_writing_style

            fields = {"operation_id", "text", "language"} | (
                {"action_id", "action_revision"} if self.saved_actions else {"action"}
            )
            if (
                not isinstance(request.data, dict)
                or not fields <= set(request.data)
                or set(request.data) - fields - {"writing_style"}
            ):
                raise ValueError()
            style = parse_writing_style(request.data.get("writing_style"))
            if "writing_style" in request.data and style is None:
                raise ValueError()
            operation_id = uuid.UUID(request.data["operation_id"])
            source, language = request.data["text"], request.data["language"]
            if not isinstance(language, str) or language not in text_actions.LANGUAGES:
                raise ValueError()
            if self.saved_actions:
                action_id, action_revision = (
                    request.data["action_id"],
                    request.data["action_revision"],
                )
                if not text_actions.valid_id(
                    action_id
                ) or not text_actions.valid_revision(action_revision, minimum=1):
                    raise ValueError()
            else:
                action = request.data["action"]
                if action not in {"rewrite", "translate"}:
                    raise ValueError()
            if (
                not isinstance(source, str)
                or not source.strip()
                or len(source.encode()) > 16000
            ):
                raise ValueError()
            fingerprint = hashlib.sha256(
                json.dumps(
                    (
                        ["text-action", action_id, action_revision, source, language]
                        if self.saved_actions
                        else ["text", action, source, language]
                    )
                    + (["writing_style", style.value] if style is not None else []),
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
        except (KeyError, TypeError, ValueError, AttributeError):
            return Response({"code": "invalid_text_request"}, status=400)
        operation = None
        try:
            if self.saved_actions:
                previous = ledger.replay(request.user, operation_id, fingerprint)
                if previous is not None:
                    return Response(
                        {**previous.result, "usage": ledger.usage(request.user)}
                    )
                action = text_actions.resolve(
                    request.user, action_id, action_revision, language
                )
            operation, fresh = ledger.reserve(
                request.user, operation_id, fingerprint, 0, text_operation=True
            )
            if fresh:
                transform = (
                    groq.action_operation if self.saved_actions else groq.text_operation
                )
                outcome = transform(
                    source,
                    action,
                    language,
                    cost_budget=operation.reserved_cost,
                    authorize=lambda total: ledger.authorize(operation, total),
                    **({"writing_style": style} if style is not None else {}),
                )
                with ledger.admission_lock():
                    current = Operation.objects.get(pk=operation.pk)
                    if (
                        current.state != "running"
                        or current.lease_until <= timezone.now()
                    ):
                        raise ledger.Rejected("operation_expired", 410)
                    ledger.settle(
                        operation,
                        result=outcome.result,
                        cost=outcome.cost,
                        input_tokens=outcome.input_tokens,
                        output_tokens=outcome.output_tokens,
                        cost_estimated=outcome.cost_estimated,
                    )
                    result = outcome.result
            else:
                result = operation.result
            return Response({**result, "usage": ledger.usage(request.user)})
        except ledger.Rejected as error:
            return processing_failure(
                request.user,
                operation_id,
                error.code,
                "admission",
                error.status,
                operation=operation,
            )
        except groq.ProviderFailure as error:
            return processing_failure(
                request.user,
                operation_id,
                "text_processing_failed",
                "text",
                502,
                operation=operation,
                cost=error.cost,
                input_tokens=error.input_tokens,
                output_tokens=error.output_tokens,
            )
        except exceptions.PermissionDenied:
            raise
        except Exception:
            return processing_failure(
                request.user,
                operation_id,
                "processing_failed",
                "processing",
                502,
                operation=operation,
            )


class TextActionExecuteView(TextView):
    saved_actions = True


def health(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok", "api_version": 1})
