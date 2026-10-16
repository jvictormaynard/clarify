import tempfile
import uuid
import hashlib
import json

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from rest_framework import exceptions, permissions
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler as drf_handler

from dictionary_snippets import DictionaryEntry, DictionarySnippets
from . import audio, groq, history, ledger
from .middleware import take_rate
from .models import Dictionary, Operation


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
            if set(request.data) - {"audio", "operation_id", "language"}:
                raise ValueError()
            if any(len(request.data.getlist(key)) != 1 for key in request.data):
                raise ValueError()
            operation_id = uuid.UUID(request.data["operation_id"])
            language = request.data.get("language", "auto")
            if language not in {"auto", "pt", "en", "es", "de", "ru"}:
                raise ValueError()
            upload = request.FILES["audio"]
            if not 0 < upload.size <= settings.CLARIFY_MAX_UPLOAD_BYTES:
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError):
            return Response({"code": "invalid_audio_request"}, status=400)
        operation = None
        try:
            digest = audio.fingerprint(upload, language)
            with tempfile.TemporaryDirectory(prefix="clarify-cloud-") as directory:
                path, duration_ms = audio.decode(upload, directory)
                operation, fresh = ledger.reserve(
                    request.user, operation_id, digest, duration_ms
                )
                if not fresh:
                    return Response(
                        {**operation.result, "usage": ledger.usage(request.user)}
                    )
                vocabulary = Dictionary.objects.filter(user=request.user).first()
                outcome = groq.dictation(
                    path,
                    duration_ms,
                    vocabulary.entries if vocabulary else [],
                    language,
                )
                ledger.settle(
                    operation,
                    result=outcome.result,
                    cost=outcome.cost,
                    input_tokens=outcome.input_tokens,
                    output_tokens=outcome.output_tokens,
                )
                return Response({**outcome.result, "usage": ledger.usage(request.user)})
        except ledger.Rejected as error:
            return Response(
                {"code": error.code, "usage": ledger.usage(request.user)},
                status=error.status,
            )
        except Exception:
            if operation:
                ledger.settle(operation)
            return Response(
                {"code": "processing_failed", "usage": ledger.usage(request.user)},
                status=502,
            )


class TextView(ServiceView):
    """Bounded rewrite/translation, never a general provider proxy."""

    def post(self, request):
        if not take_rate("text", str(request.user.pk), 6):
            return Response({"code": "rate_limited"}, status=429)
        try:
            if set(request.data) != {"operation_id", "action", "text", "language"}:
                raise ValueError()
            operation_id = uuid.UUID(request.data["operation_id"])
            action, source, language = (
                request.data[k] for k in ("action", "text", "language")
            )
            if action not in {"rewrite", "translate"} or language not in {
                "auto",
                "pt",
                "en",
                "es",
                "de",
                "ru",
            }:
                raise ValueError()
            if (
                not isinstance(source, str)
                or not source.strip()
                or len(source.encode()) > 16000
            ):
                raise ValueError()
            fingerprint = hashlib.sha256(
                json.dumps(
                    ["text", action, source, language], ensure_ascii=False
                ).encode()
            ).hexdigest()
        except (KeyError, TypeError, ValueError, AttributeError):
            return Response({"code": "invalid_text_request"}, status=400)
        operation = None
        try:
            operation, fresh = ledger.reserve(
                request.user, operation_id, fingerprint, 0, text_operation=True
            )
            if fresh:
                outcome = groq.text_operation(source, action, language)
                ledger.settle(
                    operation,
                    result=outcome.result,
                    cost=outcome.cost,
                    input_tokens=outcome.input_tokens,
                    output_tokens=outcome.output_tokens,
                )
                result = outcome.result
            else:
                result = operation.result
            return Response({**result, "usage": ledger.usage(request.user)})
        except ledger.Rejected as error:
            return Response(
                {"code": error.code, "usage": ledger.usage(request.user)},
                status=error.status,
            )
        except Exception:
            if operation:
                ledger.settle(operation)
            return Response(
                {"code": "processing_failed", "usage": ledger.usage(request.user)},
                status=502,
            )


def health(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok", "api_version": 1})
