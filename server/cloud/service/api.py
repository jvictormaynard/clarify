import json

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from rest_framework import exceptions, permissions
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler as drf_handler

from dictionary_snippets import (
    MAX_ACCOUNT_SNIPPET_BYTES,
    DictionaryEntry,
    DictionarySnippets,
    Snippet,
)
from . import history, ledger, text_actions
from .middleware import take_rate
from .models import Dictionary, Operation, SnippetLibrary


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
                "hosted_inference_available": False,
                "inference_code": "inference_retired",
                "output_preferences_supported": False,
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


class InferenceRetiredView(APIView):
    # Reject before authentication, parsing or funded admission.
    authentication_classes = []
    permission_classes = []
    parser_classes = []

    def post(self, request):
        return Response(
            {"code": "inference_retired", "update_required": True}, status=410
        )

    get = post


class UsageView(InferenceRetiredView):
    pass


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
        item = Dictionary.objects.filter(user=request.user).first()
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
            entries = validate_entries(request.data["entries"])
        except (KeyError, TypeError, ValueError):
            return Response({"code": "invalid_dictionary"}, status=400)
        with transaction.atomic():
            owner = (
                get_user_model()
                .objects.select_for_update()
                .filter(pk=request.user.pk)
                .first()
            )
            if owner is None:
                raise exceptions.PermissionDenied()
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


class DictationView(InferenceRetiredView):
    pass


class TextView(InferenceRetiredView):
    pass


class TextActionExecuteView(InferenceRetiredView):
    pass


def health(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok", "api_version": 1})
