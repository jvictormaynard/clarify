"""Account-owned history changes. No provider, audio or credential access."""

import math
import re
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Sum
from rest_framework import exceptions
from rest_framework.renderers import JSONRenderer

from .models import HistoryClear, HistoryEntry, HistoryState

MAX_BATCH = 50
MAX_PAGE = 20
MAX_JSON_BYTES = 400 * 1024
MAX_TEXT_BYTES = 32768
MAX_ACCOUNT_BYTES = 20 * 1024 * 1024
MAX_ACCOUNT_IDS = 50000
MAX_CLEAR_IDS = 10000
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z", re.ASCII)
_FIELDS = {"id", "createdAt", "transcript", "text", "rewritten", "sourceDevice"}


class Conflict(Exception):
    pass


class Capacity(Exception):
    pass


def _record_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError()
    return value


def _entry(value):
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError()
    _record_id(value["id"])
    timestamp = value["createdAt"]
    if type(timestamp) not in (float, int) or not 0 < timestamp < 4102444800:
        raise ValueError()
    if not math.isfinite(timestamp) or type(value["rewritten"]) is not bool:
        raise ValueError()
    if value["sourceDevice"] not in ("mobile", "desktop"):
        raise ValueError()
    for name in ("transcript", "text"):
        text = value[name]
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError()
    if not value["text"].strip():
        raise ValueError()
    return {**value, "createdAt": float(timestamp)}


def validate(payload):
    if not isinstance(payload, dict) or set(payload) - {
        "cursor",
        "upserts",
        "deletes",
        "clearID",
    }:
        raise ValueError()
    if not {"cursor", "upserts", "deletes"}.issubset(payload):
        raise ValueError()
    cursor, upserts, deletes = (payload[k] for k in ("cursor", "upserts", "deletes"))
    if type(cursor) is not int or not 0 <= cursor <= 2**63 - 1:
        raise ValueError()
    if any(
        not isinstance(items, list) or len(items) > MAX_BATCH
        for items in (upserts, deletes)
    ):
        raise ValueError()
    upserts = [_entry(item) for item in upserts]
    deletes = [_record_id(value) for value in deletes]
    upsert_ids = {item["id"] for item in upserts}
    if (
        len(upsert_ids) != len(upserts)
        or len(set(deletes)) != len(deletes)
        or upsert_ids.intersection(deletes)
    ):
        raise ValueError()
    clear_id = None
    if "clearID" in payload:
        if not isinstance(payload["clearID"], str) or upserts or deletes:
            raise ValueError()
        clear_id = uuid.UUID(payload["clearID"])
    if len(JSONRenderer().render(payload)) > MAX_JSON_BYTES:
        raise ValueError()
    return cursor, upserts, deletes, clear_id


def synchronize(user, payload):
    # Validate before opening the transaction. Unicode errors are request errors,
    # not server errors. Do not return or log invalid text in an error response.
    try:
        cursor, upserts, deletes, clear_id = validate(payload)
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError):
        raise exceptions.ValidationError() from None
    with transaction.atomic():
        # Lock the existing account before get_or_create: this also serializes a
        # first sync and account deletion. Do not recreate a deleted account.
        if (
            not get_user_model()
            .objects.select_for_update()
            .filter(pk=user.pk, is_active=True)
            .exists()
        ):
            raise exceptions.PermissionDenied()
        state, _ = HistoryState.objects.get_or_create(user=user)
        if cursor > state.revision:
            raise exceptions.ValidationError()
        if clear_id is not None:
            _, fresh = HistoryClear.objects.get_or_create(
                user=user, operation_id=clear_id
            )
            if fresh:
                if HistoryClear.objects.filter(user=user).count() > MAX_CLEAR_IDS:
                    raise Capacity()
                cleared = list(
                    HistoryEntry.objects.filter(user=user, payload__isnull=False)
                    .only("pk", "revision")
                    .order_by("revision")
                )
                for row in cleared:
                    state.revision += 1
                    row.payload = None
                    row.byte_size = 0
                    row.revision = state.revision
                HistoryEntry.objects.bulk_update(
                    cleared, ["payload", "revision", "byte_size"], batch_size=250
                )
        else:
            ids = [item["id"] for item in upserts] + deletes
            existing = {
                row.record_id: row
                for row in HistoryEntry.objects.filter(user=user, record_id__in=ids)
            }
            for item in upserts:
                row = existing.get(item["id"])
                # Tombstones win, and identical retries do not allocate revisions.
                if row is not None and row.payload is not None and row.payload != item:
                    raise Conflict()
            for item in upserts:
                if item["id"] not in existing:
                    state.revision += 1
                    HistoryEntry.objects.create(
                        user=user,
                        record_id=item["id"],
                        revision=state.revision,
                        payload=item,
                        byte_size=len(JSONRenderer().render(item)),
                    )
            for record_id in deletes:
                row = existing.get(record_id)
                if row is None:
                    state.revision += 1
                    HistoryEntry.objects.create(
                        user=user,
                        record_id=record_id,
                        revision=state.revision,
                        payload=None,
                    )
                elif row.payload is not None:
                    state.revision += 1
                    row.payload, row.revision = None, state.revision
                    row.byte_size = 0
                    row.save(update_fields=["payload", "revision", "byte_size"])
            if any(item["id"] not in existing for item in upserts) or any(
                key not in existing for key in deletes
            ):
                totals = HistoryEntry.objects.filter(user=user).aggregate(
                    size=Sum("byte_size"), count=Count("pk")
                )
                if (totals["size"] or 0) > MAX_ACCOUNT_BYTES or totals[
                    "count"
                ] > MAX_ACCOUNT_IDS:
                    raise Capacity()
        state.save(update_fields=["revision"])
        rows = list(
            HistoryEntry.objects.filter(user=user, revision__gt=cursor).order_by(
                "revision"
            )[: MAX_PAGE + 1]
        )
        result = {"cursor": cursor, "hasMore": False, "entries": [], "deleted": []}
        consumed = 0
        for row in rows[:MAX_PAGE]:
            candidate = {
                "cursor": row.revision,
                "hasMore": True,
                "entries": result["entries"]
                + ([row.payload] if row.payload is not None else []),
                "deleted": result["deleted"]
                + ([row.record_id] if row.payload is None else []),
            }
            if len(JSONRenderer().render(candidate)) > MAX_JSON_BYTES:
                # One valid maximum-sized entry fits the budget. Never advance
                # the cursor over an unreturned entry when a page becomes full.
                break
            result = candidate
            consumed += 1
        result["hasMore"] = consumed < len(rows)
        return result
