"""Atomic funded admission and once-only settlement under the treasury lock."""

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from . import funding
from .models import Allowance, Budget, FundingEntry, Operation, WeeklyQuota

MAX_COST = Decimal("0.020000000")


@contextmanager
def admission_lock():
    with funding.locked():
        yield


class Rejected(Exception):
    def __init__(self, code, status=429):
        self.code, self.status = code, status


def month_start():
    # Retained for historical administration, never used to allocate cash.
    return timezone.now().date().replace(day=1)


def asr_cost(audio_ms):
    return funding.money(
        Decimal(max((audio_ms + 999) // 1000, 10)) * Decimal("0.04") / Decimal(3600),
        up=True,
    )


def _remaining_monthly_cap(month, budget=None):
    budget = budget or Budget.objects.filter(month=month).first()
    earlier_running = Operation.objects.filter(state="running").exclude(
        month=month
    ).aggregate(total=Sum("reserved_cost"))["total"] or Decimal(0)
    return (
        Decimal(settings.CLARIFY_MONTHLY_BUDGET_USD)
        - (budget.spent + budget.reserved if budget else 0)
        - earlier_running
    )


def _previous(user, operation_id, fingerprint):
    previous = Operation.objects.filter(user=user, operation_id=operation_id).first()
    if previous is None:
        return None
    if previous.fingerprint != fingerprint:
        raise Rejected("operation_conflict", 409)
    if previous.state == "running":
        raise Rejected("operation_pending", 409)
    if (
        previous.result
        and previous.result_expires_at
        and previous.result_expires_at > timezone.now()
    ):
        return previous
    raise Rejected("operation_expired", 410)


def replay(user, operation_id, fingerprint):
    """Check accepted work before resolving mutable user-owned definitions."""
    with funding.locked():
        expire_leases()
        return _previous(user, operation_id, fingerprint)


def reserve(user, operation_id, fingerprint, audio_ms, *, text_operation=False):
    if (
        not settings.CLARIFY_FUNDED_ENABLED
        or not settings.CLARIFY_GROQ_KEY
        or not user.funded_access
    ):
        raise Rejected("hosted_unavailable", 503)
    if not (audio_ms == 0 if text_operation else 250 <= audio_ms <= 300000):
        raise Rejected("invalid_duration", 400)
    expire_leases()
    with funding.locked() as treasury:
        previous = _previous(user, operation_id, fingerprint)
        if previous:
            return previous, False
        if Operation.objects.filter(user=user, state="running").exists():
            raise Rejected("account_busy")
        if (
            Operation.objects.filter(state="running").count()
            >= settings.CLARIFY_GLOBAL_CONCURRENCY
        ):
            raise Rejected("service_busy", 503)
        quota, _, status = funding.quota_locked(treasury, user, timezone.now())
        if status == "inactive":
            raise Rejected("hosted_unavailable", 503)
        if status == "unfunded":
            raise Rejected("service_budget_exhausted", 503)
        if quota is None:
            raise Rejected("allocation_waiting")
        available = quota.allocated_usd - quota.used_usd - quota.reserved_usd
        minimum = Decimal("0.0000003") if text_operation else asr_cost(audio_ms)
        if available < minimum or quota.operations >= 2000:
            raise Rejected("allowance_exhausted")
        month = month_start()
        budget, _ = Budget.objects.get_or_create(month=month)
        allowance, _ = Allowance.objects.get_or_create(user=user, month=month)
        if allowance.operations >= 2000:
            raise Rejected("allowance_exhausted")
        # Keep the independent monthly safety cap. A request admitted before
        # midnight can still incur charges after it, so its reservation must
        # remain covered until settlement, even when its month differs.
        cap_available = _remaining_monthly_cap(month, budget)
        if cap_available < minimum:
            raise Rejected("service_budget_exhausted", 503)
        reservation = funding.money(min(MAX_COST, available, cap_available))
        operation = Operation.objects.create(
            user=user,
            operation_id=operation_id,
            month=month,
            fingerprint=fingerprint,
            audio_ms=audio_ms,
            reserved_cost=reservation,
            quota=quota,
            lease_until=timezone.now() + timedelta(seconds=180),
        )
        quota.reserved_usd += reservation
        quota.operations += 1
        quota.save(update_fields=["reserved_usd", "operations"])
        treasury.processing_reserved += reservation
        treasury.save()
        # Keep historical administration consistent without granting audio time.
        allowance.reserved_ms += audio_ms
        allowance.operations += 1
        allowance.save()
        budget.reserved += reservation
        budget.save()
        return operation, True


def authorize(operation, total_cost):
    """Persist the cumulative worst case before sending each paid request."""
    total_cost = funding.money(total_cost, up=True)
    with funding.locked():
        current = Operation.objects.get(pk=operation.pk)
        if current.state != "running" or current.lease_until <= timezone.now():
            raise Rejected("operation_expired", 410)
        if not current.authorized_cost <= total_cost <= current.reserved_cost:
            raise Rejected("allowance_exhausted")
        current.authorized_cost = total_cost
        current.save(update_fields=["authorized_cost"])


def expire_leases():
    with funding.locked() as treasury:
        for operation in Operation.objects.filter(
            state="running", lease_until__lt=timezone.now()
        ):
            _settle_locked(
                treasury,
                operation,
                operation.authorized_cost,
                {},
                0,
                0,
                "uncertain",
                cost_estimated=True,
            )


def _settle_locked(
    treasury,
    operation,
    cost,
    result,
    input_tokens,
    output_tokens,
    state,
    *,
    cost_estimated=False,
):
    if operation.state != "running":
        return
    cost = funding.money(cost, up=True)
    if not cost.is_finite() or not 0 <= cost <= operation.reserved_cost:
        raise ValueError("Provider cost exceeds its authorized financial reservation")
    if operation.quota_id:
        quota = WeeklyQuota.objects.get(pk=operation.quota_id)
        quota.reserved_usd -= operation.reserved_cost
        # Paid or uncertain work consumes quota even if the user cancels or
        # receives an error. Work rejected before a paid call has zero debit.
        quota.used_usd += cost
        quota.save(update_fields=["reserved_usd", "used_usd"])
        operation.quota_debit = cost
    if operation.user_id:
        allowance = Allowance.objects.filter(
            user_id=operation.user_id, month=operation.month
        ).first()
        if allowance:
            allowance.reserved_ms -= operation.audio_ms
            allowance.used_ms += operation.audio_ms
            allowance.save()
    budget = Budget.objects.get(month=operation.month)
    budget.reserved -= operation.reserved_cost
    budget.spent += cost
    budget.save()
    treasury.processing_reserved -= operation.reserved_cost
    treasury.processing_spent += cost
    treasury.save()
    if cost > 0:
        FundingEntry.objects.create(
            kind="processing_estimate" if cost_estimated else "processing_cost",
            amount_usd=cost,
            source="ledger",
            reference=f"cost:{operation.pk}",
            occurred_at=timezone.now(),
        )
    operation.state, operation.cost = state, cost
    operation.cost_estimated = cost_estimated
    operation.result = result
    operation.result_expires_at = timezone.now() + timedelta(minutes=5)
    operation.input_tokens, operation.output_tokens = input_tokens, output_tokens
    operation.save()


def settle(
    operation,
    *,
    result=None,
    cost=None,
    input_tokens=0,
    output_tokens=0,
    cost_estimated=False,
):
    with funding.locked() as treasury:
        current = Operation.objects.get(pk=operation.pk)
        _settle_locked(
            treasury,
            current,
            current.authorized_cost if cost is None else cost,
            result or {},
            input_tokens,
            output_tokens,
            "complete" if result else "uncertain",
            cost_estimated=cost_estimated or cost is None,
        )


def usage(user):
    now = timezone.now()
    start, reset = funding.week_bounds(now)
    with funding.locked() as treasury:
        quota, _, status = funding.quota_locked(treasury, user, now)
        used = reserved = remaining = Decimal(0)
        if quota and quota.allocated_usd > 0:
            used = min(Decimal(100), quota.used_usd * 100 / quota.allocated_usd)
            reserved = min(100 - used, quota.reserved_usd * 100 / quota.allocated_usd)
            remaining = max(Decimal(0), 100 - used - reserved)
        enabled = bool(settings.CLARIFY_FUNDED_ENABLED and settings.CLARIFY_GROQ_KEY)
        monthly = Allowance.objects.filter(user=user, month=month_start()).first()
        enabled = (
            enabled
            and _remaining_monthly_cap(month_start()) > 0
            and (monthly is None or monthly.operations < 2000)
        )
        return {
            "schema_version": 2,
            "period_start": start.isoformat(),
            "reset_at": reset.isoformat(),
            "used_percent": round(float(used), 6),
            "remaining_percent": round(float(remaining), 6),
            "reserved_percent": round(float(reserved), 6),
            "allocation_status": status,
            "hosted_available": bool(
                enabled and status == "available" and remaining > 0
            ),
        }
