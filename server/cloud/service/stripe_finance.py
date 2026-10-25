"""Read-only Stripe balance projection. No funding or ledger writes occur here.

Verified API contracts: https://docs.stripe.com/api/balance/balance_retrieve
and https://docs.stripe.com/api/balance_transactions/list (2026-10-25).
"""

from datetime import datetime, timezone as dt_timezone
import hashlib
import hmac
import json
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone
import requests

from .transparency_models import (
    PublicFinanceSnapshot,
    PublicStripeBalance,
    PublicStripeMovement,
)

STRIPE_HOST = "https://api.stripe.com"
MAX_PAGES = 100
PAGE_SIZE = 100
MAX_BODY = 1024 * 1024
TIMEOUT = (5, 20)
MAX_MINOR = 10**15
KINDS = frozenset({"payment", "refund", "fee", "payout", "transfer", "adjustment"})
LABELS = {
    "payment": "Payment",
    "refund": "Refund",
    "fee": "Stripe fee",
    "payout": "Payout transfer",
    "transfer": "Transfer",
    "adjustment": "Balance adjustment",
}


class StripeSyncError(Exception):
    """A fixed code only. Provider exception messages must never escape."""


def configured_key():
    value = getattr(settings, "CLARIFY_STRIPE_READ_KEY", "")
    return value if isinstance(value, str) else ""


def configuration_tag(key=None):
    key = configured_key() if key is None else key
    return hmac.new(
        settings.SECRET_KEY.encode(), key.encode(), hashlib.sha256
    ).hexdigest()


def configuration_state(key=None):
    key = configured_key() if key is None else key
    if not key:
        return "not_configured"
    if re.fullmatch(r"(?:rk|sk)_test_[A-Za-z0-9]+", key):
        return "test_mode"
    # A restricted live key is required; give it only balance read permissions.
    if not re.fullmatch(r"rk_live_[A-Za-z0-9]+", key):
        return "invalid_configuration"
    return "configured"


def _integer(value):
    if type(value) is not int or abs(value) > MAX_MINOR:
        raise StripeSyncError("invalid_response")
    return value


def _currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z]{3}", value):
        raise StripeSyncError("invalid_response")
    return value


def _timestamp(value):
    if type(value) is not int or not 0 <= value <= 4102444800:
        raise StripeSyncError("invalid_response")
    return datetime.fromtimestamp(value, tz=dt_timezone.utc)


def _get(path, key, params, get):
    # Never follow redirects, list URLs, sources or a configurable provider host.
    try:
        with get(
            STRIPE_HOST + path,
            headers={"Authorization": "Bearer " + key},
            params=params,
            timeout=TIMEOUT,
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                raise StripeSyncError("unavailable")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    raise StripeSyncError("invalid_response")
            value = json.loads(body)
            if not isinstance(value, dict):
                raise StripeSyncError("invalid_response")
            return value
    except (
        requests.RequestException,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
    ):
        raise StripeSyncError("unavailable") from None


def _balances(value):
    if value.get("object") != "balance" or type(value.get("livemode")) is not bool:
        raise StripeSyncError("invalid_response")
    if value["livemode"] is not True:
        raise StripeSyncError("test_mode")
    result = {}
    for field in ("available", "pending"):
        rows = value.get(field)
        if not isinstance(rows, list) or len(rows) > 200:
            raise StripeSyncError("invalid_response")
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise StripeSyncError("invalid_response")
            currency = _currency(row.get("currency"))
            if currency in seen:
                raise StripeSyncError("invalid_response")
            seen.add(currency)
            result.setdefault(currency, {"available_minor": 0, "pending_minor": 0})[
                field + "_minor"
            ] = _integer(row.get("amount"))
    return [
        {"currency": currency, **amounts}
        for currency, amounts in sorted(result.items())
    ]


def _movement(row):
    if not isinstance(row, dict) or row.get("object") != "balance_transaction":
        raise StripeSyncError("invalid_response")
    if "livemode" in row and row["livemode"] is not True:
        raise StripeSyncError("test_mode")
    kind = row.get("type")
    if not isinstance(kind, str):
        raise StripeSyncError("invalid_response")
    if kind in {"charge", "payment"}:
        kind = "payment"
    elif kind in {"refund", "payment_refund"}:
        kind = "refund"
    elif kind in {"stripe_fee", "stripe_fx_fee", "tax_fee"}:
        kind = "fee"
    elif kind in {"payout", "payout_cancel", "payout_failure"}:
        kind = "payout"
    elif kind in {"transfer", "transfer_cancel", "transfer_failure", "transfer_refund"}:
        kind = "transfer"
    else:
        kind = "adjustment"
    availability = row.get("status")
    if not isinstance(availability, str) or availability not in {
        "available",
        "pending",
    }:
        raise StripeSyncError("invalid_response")
    amount, fee, net = (_integer(row.get(k)) for k in ("amount", "fee", "net"))
    if amount - fee != net:
        raise StripeSyncError("invalid_response")
    return {
        "occurred_at": _timestamp(row.get("created")),
        "available_on": _timestamp(row.get("available_on")),
        "kind": kind,
        "currency": _currency(row.get("currency")),
        "amount_minor": amount,
        "fee_minor": fee,
        "net_minor": net,
        "availability": availability,
    }


def fetch_snapshot(key, *, get=None, now=None):
    """Fetch up to 10,000 movements. All cursor IDs stay in temporary memory."""
    state = configuration_state(key)
    if state != "configured":
        raise StripeSyncError(state)
    get = requests.get if get is None else get
    now = timezone.now() if now is None else now
    balances = _balances(_get("/v1/balance", key, {}, get))
    movements, seen = [], set()
    params = {"limit": PAGE_SIZE, "created[lte]": int(now.timestamp())}
    for _ in range(MAX_PAGES):
        value = _get("/v1/balance_transactions", key, params.copy(), get)
        rows, has_more = value.get("data"), value.get("has_more")
        if (
            value.get("object") != "list"
            or not isinstance(rows, list)
            or len(rows) > PAGE_SIZE
            or type(has_more) is not bool
            or (has_more and not rows)
        ):
            raise StripeSyncError("invalid_response")
        for row in rows:
            if not isinstance(row, dict):
                raise StripeSyncError("invalid_response")
            cursor = row.get("id")
            if (
                not isinstance(cursor, str)
                or not re.fullmatch(r"txn_[A-Za-z0-9_]{1,240}", cursor)
                or cursor in seen
            ):
                raise StripeSyncError("invalid_response")
            seen.add(cursor)
            movement = _movement(row)
            if movement["occurred_at"] > now:
                raise StripeSyncError("invalid_response")
            movements.append(movement)
        if not has_more:
            return balances, movements, True
        params["starting_after"] = cursor
    return balances, movements, False


def sync(*, get=None, now=None):
    """Replace a complete sanitized projection atomically, preserving it on error.

    Reserve a generation, fetch without database locks, then publish only if that
    generation is still current. Public readers never wait for provider HTTP.
    """
    now = timezone.now() if now is None else now
    key = configured_key()
    tag = configuration_tag(key)
    failure = None
    with transaction.atomic():
        PublicFinanceSnapshot.objects.get_or_create(pk=1)
        snapshot = PublicFinanceSnapshot.objects.select_for_update().get(pk=1)
        if snapshot.configuration_tag != tag:
            PublicStripeMovement.objects.filter(snapshot=snapshot).delete()
            PublicStripeBalance.objects.filter(snapshot=snapshot).delete()
            snapshot.synced_at = None
            snapshot.history_complete = False
        snapshot.configuration_tag = tag
        snapshot.attempted_at = now
        snapshot.generation += 1
        generation = snapshot.generation
        snapshot.save()
    try:
        balances, movements, complete = fetch_snapshot(key, get=get, now=now)
    except StripeSyncError as error:
        failure = str(error)
    with transaction.atomic():
        snapshot = PublicFinanceSnapshot.objects.select_for_update().get(pk=1)
        if snapshot.generation != generation or snapshot.configuration_tag != tag:
            raise StripeSyncError("superseded")
        if failure:
            snapshot.error_code = failure
        else:
            PublicStripeMovement.objects.filter(snapshot=snapshot).delete()
            PublicStripeBalance.objects.filter(snapshot=snapshot).delete()
            PublicStripeBalance.objects.bulk_create(
                [PublicStripeBalance(snapshot=snapshot, **row) for row in balances]
            )
            PublicStripeMovement.objects.bulk_create(
                [
                    PublicStripeMovement(snapshot=snapshot, position=i, **row)
                    for i, row in enumerate(movements)
                ],
                batch_size=500,
            )
            snapshot.synced_at = now
            snapshot.history_complete = complete
            snapshot.error_code = ""
        snapshot.save()
    if failure:
        raise StripeSyncError(failure) from None
    return snapshot
