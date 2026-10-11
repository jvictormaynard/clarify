"""Atomic admission and settlement. Lock budget first in every transaction."""

from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Allowance, Budget, Operation

MAX_COST = Decimal("0.020000000")


@contextmanager
def admission_lock():
    # One mutex also covers requests on opposite sides of a UTC month boundary.
    with transaction.atomic():
        Budget.objects.get_or_create(month=date(1970, 1, 1))
        Budget.objects.select_for_update().get(month=date(1970, 1, 1))
        yield


class Rejected(Exception):
    def __init__(self, code, status=429):
        self.code, self.status = code, status


def month_start():
    return timezone.now().date().replace(day=1)


def allowance_limit(user):
    return (
        user.monthly_audio_ms
        if user.monthly_audio_ms is not None
        else settings.CLARIFY_MONTHLY_AUDIO_MS
    )


def reserve(user, operation_id, fingerprint, audio_ms, *, text_operation=False):
    if (
        not settings.CLARIFY_FUNDED_ENABLED
        or not settings.CLARIFY_GROQ_KEY
        or not user.funded_access
    ):
        raise Rejected("hosted_unavailable", 503)
    if not (audio_ms == 0 if text_operation else 250 <= audio_ms <= 300000):
        raise Rejected("invalid_duration", 400)
    month = month_start()
    expire_leases()
    with admission_lock():
        Budget.objects.get_or_create(month=month)
        budget = Budget.objects.select_for_update().get(month=month)
        previous = Operation.objects.filter(
            user=user, operation_id=operation_id
        ).first()
        if previous:
            if previous.fingerprint != fingerprint:
                raise Rejected("operation_conflict", 409)
            if previous.state == "running":
                raise Rejected("operation_pending", 409)
            if previous.result and previous.result_expires_at > timezone.now():
                return previous, False
            raise Rejected("operation_expired", 410)
        if Operation.objects.filter(user=user, state="running").exists():
            raise Rejected("account_busy")
        if (
            Operation.objects.filter(state="running").count()
            >= settings.CLARIFY_GLOBAL_CONCURRENCY
        ):
            raise Rejected("service_busy", 503)
        Allowance.objects.get_or_create(user=user, month=month)
        allowance = Allowance.objects.select_for_update().get(user=user, month=month)
        if (
            allowance.used_ms + allowance.reserved_ms + audio_ms > allowance_limit(user)
            or allowance.operations >= 2000
        ):
            raise Rejected("allowance_exhausted")
        if budget.spent + budget.reserved + MAX_COST > Decimal(
            settings.CLARIFY_MONTHLY_BUDGET_USD
        ):
            raise Rejected("service_budget_exhausted", 503)
        operation = Operation.objects.create(
            user=user,
            operation_id=operation_id,
            month=month,
            fingerprint=fingerprint,
            audio_ms=audio_ms,
            reserved_cost=MAX_COST,
            lease_until=timezone.now() + timedelta(seconds=180),
        )
        allowance.reserved_ms += audio_ms
        allowance.operations += 1
        allowance.save()
        budget.reserved += MAX_COST
        budget.save()
        return operation, True


def expire_leases():
    # A terminated process may already have incurred provider charges. Never
    # refund or repeat an uncertain request. Reserve its worst case as spent.
    with admission_lock():
        for operation in Operation.objects.filter(
            state="running", lease_until__lt=timezone.now()
        ):
            budget = Budget.objects.select_for_update().get(month=operation.month)
            _settle_locked(
                budget, operation, operation.reserved_cost, {}, 0, 0, "uncertain"
            )


def _settle_locked(budget, operation, cost, result, input_tokens, output_tokens, state):
    if operation.state != "running":
        return
    if operation.user_id:
        allowance = Allowance.objects.select_for_update().get(
            user_id=operation.user_id, month=operation.month
        )
        allowance.reserved_ms -= operation.audio_ms
        allowance.used_ms += operation.audio_ms
        allowance.save()
    budget.reserved -= operation.reserved_cost
    budget.spent += cost
    budget.save()
    operation.state, operation.cost = state, cost
    operation.result, operation.result_expires_at = (
        result,
        timezone.now() + timedelta(minutes=5),
    )
    operation.input_tokens, operation.output_tokens = input_tokens, output_tokens
    operation.save()


def settle(operation, *, result=None, cost=None, input_tokens=0, output_tokens=0):
    with admission_lock():
        budget = Budget.objects.select_for_update().get(month=operation.month)
        current = Operation.objects.select_for_update().get(pk=operation.pk)
        _settle_locked(
            budget,
            current,
            current.reserved_cost if cost is None else cost,
            result or {},
            input_tokens,
            output_tokens,
            "complete" if result else "uncertain",
        )


def usage(user):
    item = Allowance.objects.filter(user=user, month=month_start()).first()
    return {
        "month": str(month_start()),
        "limit_ms": allowance_limit(user),
        "used_ms": item.used_ms if item else 0,
        "reserved_ms": item.reserved_ms if item else 0,
        "hosted_available": bool(
            settings.CLARIFY_FUNDED_ENABLED
            and settings.CLARIFY_GROQ_KEY
            and user.funded_access
        ),
    }
