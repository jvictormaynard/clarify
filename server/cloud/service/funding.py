"""Received cash, operating provisions, and common Monday UTC allocations.

All mutations take the treasury lock. A receipt releases its net processing
share over one calendar month, with the next weekly slice available upfront.
Unused cash remains in the treasury; personal allocations expire each Monday.
"""

import calendar
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from itertools import chain

from allauth.account.models import EmailAddress
from django.db import connection, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from .models import FundingEntry, FundingPeriod, Treasury, User, WeeklyQuota

UNIT = Decimal("0.000000001")
ZERO = Decimal(0)
WEEK = timedelta(days=7)


def money(value, *, up=False):
    return Decimal(value).quantize(UNIT, rounding=ROUND_UP if up else ROUND_DOWN)


def _usd(value):
    return format(money(value), ".9f")


@contextmanager
def locked():
    with transaction.atomic():
        Treasury.objects.get_or_create(pk=1)
        yield Treasury.objects.select_for_update().get(pk=1)


@contextmanager
def read_snapshot():
    """Use one nonlocking PostgreSQL snapshot for a complete public response."""
    nested = connection.in_atomic_block
    with transaction.atomic():
        if connection.vendor == "postgresql" and not nested:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
        yield


def week_bounds(now=None):
    now = (now or timezone.now()).astimezone(dt_timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start -= timedelta(days=start.weekday())
    return start, start + WEEK


def _one_month_after(value):
    year, month = value.year + (value.month == 12), value.month % 12 + 1
    return value.replace(
        year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1])
    )


def _totals(now):
    rows = FundingEntry.objects.filter(occurred_at__lte=now)
    totals = {
        kind: rows.filter(kind=kind).aggregate(total=Sum("amount_usd"))["total"] or ZERO
        for kind in (
            "contribution",
            "operating_expense",
            "operating_reserve",
            "operating_release",
        )
    }
    consumed = rows.aggregate(total=Sum("reserve_consumed_usd"))["total"] or ZERO
    return (
        totals["contribution"],
        totals["operating_expense"],
        totals["operating_reserve"] - totals["operating_release"] - consumed,
    )


def _commitments(now):
    # Old in-flight work remains in Treasury.processing_reserved after reset.
    allocated = (
        WeeklyQuota.objects.filter(period__reset_at__gt=now).aggregate(
            total=Sum(F("allocated_usd") - F("used_usd") - F("reserved_usd"))
        )["total"]
        or ZERO
    )
    newcomers = (
        FundingPeriod.objects.filter(reset_at__gt=now).aggregate(
            total=Sum("newcomers_remaining_usd")
        )["total"]
        or ZERO
    )
    return allocated, newcomers


def _available(treasury, now):
    received, spent, reserved = _totals(now)
    allocated, newcomers = _commitments(now)
    return (
        received
        - spent
        - reserved
        - treasury.processing_spent
        - treasury.processing_reserved
        - allocated
        - newcomers
    )


def _validate_entry(amount_usd, reference, occurred_at, source):
    if (
        not isinstance(amount_usd, Decimal)
        or not amount_usd.is_finite()
        or not ZERO < amount_usd <= Decimal("100000000")
        or amount_usd != money(amount_usd)
    ):
        raise ValueError("Use a positive USD amount with at most nine decimal places")
    if (
        not isinstance(reference, str)
        or not reference.strip()
        or len(reference) > 200
        or not isinstance(source, str)
        or not re.fullmatch(r"[a-z0-9_-]{1,32}", source)
        or source in {"ledger", "historical"}
    ):
        raise ValueError("Use a stable reference and a lowercase source identifier")
    if (
        not isinstance(occurred_at, datetime)
        or timezone.is_naive(occurred_at)
        or occurred_at > timezone.now()
    ):
        raise ValueError("Use an aware timestamp for cash already available")


def _change_processing_basis(amount, *, restore=False):
    """Assign operating changes once, while the caller holds the treasury lock."""
    receipts = FundingEntry.objects.filter(kind="contribution")
    if restore:
        # Restore the newest available headroom first, which retains the
        # slowest release schedule for money returning from a provision.
        rows = receipts.filter(processing_basis_usd__lt=F("amount_usd")).order_by(
            "-occurred_at", "-pk"
        )
    else:
        receipts = receipts.filter(processing_basis_usd__gt=0)
        rows = chain(
            receipts.filter(processing_ready_at__isnull=True).order_by(
                "occurred_at", "pk"
            ),
            receipts.filter(processing_ready_at__isnull=False).order_by(
                "-occurred_at", "-pk"
            ),
        )
    changed = []
    for receipt in rows:
        headroom = (
            receipt.amount_usd - receipt.processing_basis_usd
            if restore
            else receipt.processing_basis_usd
        )
        adjustment = min(amount, headroom)
        receipt.processing_basis_usd += adjustment if restore else -adjustment
        changed.append(receipt)
        amount -= adjustment
        if amount == 0:
            break
    if amount:
        raise ValueError("Operating change has no matching contribution basis")
    FundingEntry.objects.bulk_update(changed, ["processing_basis_usd"])


def _record(kind, *, amount_usd, reference, occurred_at, source):
    _validate_entry(amount_usd, reference, occurred_at, source)
    occurred_at = occurred_at.astimezone(dt_timezone.utc)
    with locked() as treasury:
        previous = FundingEntry.objects.filter(
            source=source, reference=reference
        ).first()
        if previous:
            if (
                previous.kind != kind
                or previous.amount_usd != amount_usd
                or previous.occurred_at != occurred_at
            ):
                raise ValueError("This finance reference already has different details")
            return previous, False
        now = timezone.now()
        available = _available(treasury, now)
        _, _, reserved = _totals(now)
        consumed = ZERO
        if kind == "operating_expense":
            consumed = min(reserved, amount_usd)
            if amount_usd - consumed > available:
                raise ValueError("Operating expense would use already allocated cash")
        elif kind == "operating_reserve" and amount_usd > available:
            raise ValueError("Operating provision would use already allocated cash")
        elif kind == "operating_release" and amount_usd > reserved:
            raise ValueError("Operating release exceeds the current provision")
        if kind == "operating_reserve" or (
            kind == "operating_expense" and amount_usd > consumed
        ):
            _change_processing_basis(amount_usd - consumed)
        elif kind == "operating_release":
            _change_processing_basis(amount_usd, restore=True)
        entry = FundingEntry.objects.create(
            kind=kind,
            amount_usd=amount_usd,
            reference=reference,
            source=source,
            occurred_at=occurred_at,
            reserve_consumed_usd=consumed,
            processing_basis_usd=amount_usd if kind == "contribution" else ZERO,
            release_until=_one_month_after(occurred_at)
            if kind == "contribution"
            else None,
        )
        treasury.save(update_fields=["updated_at"])
        return entry, True


def record_contribution(
    *,
    amount_usd: Decimal,
    reference: str,
    occurred_at: datetime,
    source: str = "manual",
):
    """Record available positive USD cash once per (source, reference).

    Return (FundingEntry, created). A repeated reference must have identical
    amount, kind and timestamp. References are private and never published.
    """
    return _record(
        "contribution",
        amount_usd=amount_usd,
        reference=reference,
        occurred_at=occurred_at,
        source=source,
    )


def record_operating(
    *,
    kind: str,
    amount_usd: Decimal,
    reference: str,
    occurred_at: datetime,
    source: str = "manual",
):
    """Record expense, reserve or release; return (FundingEntry, created).

    Expenses consume an existing operating reserve first. New reserves and
    any uncovered expense can use only unallocated cash. Releases return an
    unspent provision. These entries never revoke an existing weekly grant.
    """
    if kind not in {"expense", "reserve", "release"}:
        raise ValueError("Choose expense, reserve or release")
    return _record(
        "operating_" + kind,
        amount_usd=amount_usd,
        reference=reference,
        occurred_at=occurred_at,
        source=source,
    )


def eligible_users():
    verified = EmailAddress.objects.filter(
        verified=True, primary=True, email__iexact=F("user__email")
    ).values("user_id")
    return User.objects.filter(is_active=True, funded_access=True, pk__in=verified)


def _approve_locked(now):
    return FundingEntry.objects.filter(
        kind="contribution",
        processing_ready_at__isnull=True,
    ).update(processing_ready_at=now)


def approve_funding():
    """Operator confirmation that operating costs for pending cash are recorded."""
    with locked() as treasury:
        changed = _approve_locked(timezone.now())
        if changed:
            treasury.save(update_fields=["updated_at"])
        return changed


def _distribute_locked(treasury, now):
    start, reset = week_bounds(now)
    existing = FundingPeriod.objects.filter(start=start).first()
    if existing:
        return existing
    # A receipt can commit before its known operating provision. Automatic
    # requests must not allocate that cash during the operator's review.
    if FundingEntry.objects.filter(
        kind="contribution", processing_ready_at__isnull=True
    ).exists():
        return None
    received, _, _ = _totals(now)
    if received <= 0:
        return None
    gross_released = ZERO
    for receipt in FundingEntry.objects.filter(
        kind="contribution", occurred_at__lte=now
    ).order_by("occurred_at", "pk"):
        elapsed = min(reset, receipt.release_until) - receipt.occurred_at
        fraction = Decimal(str(elapsed.total_seconds())) / Decimal(
            str((receipt.release_until - receipt.occurred_at).total_seconds())
        )
        gross_released += receipt.processing_basis_usd * max(ZERO, fraction)
    released = money(
        max(
            ZERO,
            min(
                _available(treasury, now),
                gross_released
                - treasury.processing_spent
                - treasury.processing_reserved,
            ),
        )
    )
    if released <= 0:
        return None
    users = list(
        eligible_users()
        .filter(
            hosted_requested_at__lte=start,
            hosted_last_active_at__gte=start - timedelta(days=28),
        )
        .order_by("pk")
    )
    regular = money(released * Decimal("0.8"))
    share = money(regular / max(1, len(users)))
    period = FundingPeriod.objects.create(
        start=start,
        reset_at=reset,
        released_usd=released,
        regular_share_usd=share,
        population=len(users),
        newcomers_remaining_usd=money(released * Decimal("0.2")),
    )
    WeeklyQuota.objects.bulk_create(
        [WeeklyQuota(user=user, period=period, allocated_usd=share) for user in users]
    )
    treasury.save(update_fields=["updated_at"])
    return period


def distribute(*, now=None, confirm_operating_costs=False):
    with locked() as treasury:
        if confirm_operating_costs:
            _approve_locked(now or timezone.now())
            treasury.save(update_fields=["updated_at"])
        return _distribute_locked(treasury, now or timezone.now())


def quota_locked(treasury, user, now):
    """Register requested access, then grant only this period's funded share."""
    owner = eligible_users().filter(pk=user.pk).first()
    if owner is None:
        return None, None, "inactive"
    if owner.hosted_requested_at is None:
        owner.hosted_requested_at = now
    owner.hosted_last_active_at = now
    owner.save(update_fields=["hosted_requested_at", "hosted_last_active_at"])
    period = _distribute_locked(treasury, now)
    if period is None:
        return None, None, "unfunded"
    quota = WeeklyQuota.objects.filter(user=user, period=period).first()
    if quota is None and owner.hosted_requested_at > period.start:
        remaining = Decimal(str((period.reset_at - now).total_seconds())) / Decimal(
            604800
        )
        amount = money(
            min(period.newcomers_remaining_usd, period.regular_share_usd * remaining)
        )
        if amount > 0:
            quota = WeeklyQuota.objects.create(
                user=user, period=period, allocated_usd=amount
            )
            period.newcomers_remaining_usd -= amount
            period.save(update_fields=["newcomers_remaining_usd"])
            treasury.save(update_fields=["updated_at"])
    return (
        quota,
        period,
        "available" if quota and quota.allocated_usd > 0 else "waiting",
    )


def public_summary(*, page=1, page_size=50):
    """Return public totals and one bounded page, without private references."""
    if (
        type(page) is not int
        or page < 1
        or type(page_size) is not int
        or not 1 <= page_size <= 100
    ):
        raise ValueError("Use a positive page and a page size from 1 to 100")
    with read_snapshot():
        now = timezone.now()
        treasury = Treasury.objects.filter(pk=1).first() or Treasury()
        received, operating_spent, operating_reserved = _totals(now)
        allocated, newcomers = _commitments(now)
        labels = dict(FundingEntry._meta.get_field("kind").choices)
        rows = FundingEntry.objects.filter(
            Q(occurred_at__lte=now) | Q(occurred_at__isnull=True)
        ).order_by(F("occurred_at").desc(nulls_last=True), "-pk")
        offset = (page - 1) * page_size
        return {
            "currency": "usd",
            "received_usd": _usd(received),
            "operating_spent_usd": _usd(operating_spent),
            "operating_reserved_usd": _usd(operating_reserved),
            "processing_spent_usd": _usd(treasury.processing_spent),
            "allocated_usd": _usd(allocated + treasury.processing_reserved),
            "available_usd": _usd(max(ZERO, _available(treasury, now))),
            "newcomers_reserved_usd": _usd(newcomers),
            "updated_at": (treasury.updated_at or now).isoformat(),
            "movements_total": rows.count(),
            "movements": [
                {
                    "occurred_at": entry.occurred_at.isoformat()
                    if entry.occurred_at
                    else None,
                    "kind": entry.kind,
                    "amount_usd": _usd(entry.amount_usd),
                    "source": "project",
                    "label": labels[entry.kind],
                }
                for entry in rows[offset : offset + page_size]
            ],
        }
