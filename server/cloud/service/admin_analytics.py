"""Bounded, read-only business analytics. Never load processing content.

Activity and audio require a confirmed completion. ``uncertain`` means that
completion was not confirmed, not that the provider made no charge. Costs are
the conservative ledger values. Monthly budget survives operation cleanup;
operation-level metrics and last activity cover only the retained 31 days.
The selected period includes today, from UTC midnight, through the request.
Its comparison has the same elapsed duration, shifted back by ``days``.
"""

import calendar
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from allauth.account.models import EmailAddress
from django.conf import settings
from django.db.models import Count, Exists, Max, OuterRef, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .funding import week_bounds
from .models import Budget, FundingPeriod, Operation, User, WeeklyQuota

PAGE_SIZE = 25
RETENTION_DAYS = 31
UTC = dt_timezone.utc


def _window(days):
    if isinstance(days, bool) or str(days) not in {"7", "14", "30"}:
        raise ValueError("Use a period of 7, 14 or 30 days")
    days = int(days)
    now = timezone.now().astimezone(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return days, midnight - timedelta(days=days - 1), now


def _ops(start, end):
    return Operation.objects.filter(created_at__gte=start, created_at__lte=end)


def _money(value):
    return format(value or Decimal(0), ".9f")


def _minutes(value):
    return round((value or 0) / 60000, 2)


def _metrics(operations):
    values = operations.aggregate(
        operations=Count("pk"),
        complete=Count("pk", filter=Q(state="complete")),
        uncertain=Count("pk", filter=Q(state="uncertain")),
        running=Count("pk", filter=Q(state="running")),
        active_users=Count("user_id", distinct=True, filter=Q(state="complete")),
        audio_ms=Sum("audio_ms", filter=Q(state="complete")),
        cost=Sum("cost"),
    )
    terminal = values["complete"] + values["uncertain"]
    return {
        "operations": values["operations"],
        "active_users": values["active_users"],
        "audio_minutes": _minutes(values["audio_ms"]),
        "cost_usd": _money(values["cost"]),
        "success_rate": round(values["complete"] * 100 / terminal, 1)
        if terminal
        else None,
    }, {name: values[name] for name in ("complete", "uncertain", "running")}


def _returning(operations):
    return (
        operations.filter(state="complete", user_id__isnull=False)
        .values("user_id")
        .annotate(active_days=Count(TruncDate("created_at", tzinfo=UTC), distinct=True))
        .filter(active_days__gte=2)
        .count()
    )


def _trend(operations, registrations, start, days):
    daily = {
        item["day"]: item
        for item in operations.annotate(day=TruncDate("created_at", tzinfo=UTC))
        .values("day")
        .annotate(
            operations=Count("pk"),
            active_users=Count("user_id", distinct=True, filter=Q(state="complete")),
            complete=Count("pk", filter=Q(state="complete")),
            uncertain=Count("pk", filter=Q(state="uncertain")),
            audio_ms=Sum("audio_ms", filter=Q(state="complete")),
            cost=Sum("cost"),
        )
    }
    registered = {
        item["day"]: item["count"]
        for item in registrations.annotate(day=TruncDate("date_joined", tzinfo=UTC))
        .values("day")
        .annotate(count=Count("pk"))
    }
    result = []
    for offset in range(days):
        date = (start + timedelta(days=offset)).date()
        item = daily.get(date, {})
        result.append(
            {
                "date": date.isoformat(),
                "active_users": item.get("active_users", 0),
                "new_users": registered.get(date, 0),
                "operations": item.get("operations", 0),
                "audio_minutes": _minutes(item.get("audio_ms")),
                "cost_usd": _money(item.get("cost")),
                "complete": item.get("complete", 0),
                "uncertain": item.get("uncertain", 0),
            }
        )
    return result


def _budget(now):
    month = now.date().replace(day=1)
    # Values only: there is no create, lock, settlement or cleanup on a read.
    ledger = Budget.objects.filter(month=month).values("spent", "reserved").first()
    spent = ledger["spent"] if ledger else Decimal(0)
    reserved = ledger["reserved"] if ledger else Decimal(0)
    limit = Decimal(settings.CLARIFY_MONTHLY_BUDGET_USD)
    month_start = datetime.combine(month, datetime.min.time(), tzinfo=UTC)
    elapsed = Decimal(str((now - month_start).total_seconds()))
    seconds = Decimal(calendar.monthrange(month.year, month.month)[1] * 86400)
    projected = spent * seconds / elapsed if ledger and elapsed > 0 else None
    return {
        "month": month.isoformat(),
        "limit_usd": _money(limit),
        "spent_usd": _money(spent),
        "reserved_usd": _money(reserved),
        "remaining_usd": _money(max(Decimal(0), limit - spent - reserved)),
        "projected_usd": _money(projected) if projected is not None else None,
    }


def _insights(metrics, funnel, budget, health):
    result = []
    if health["uncertain"]:
        result.append(
            {
                "tone": "warning",
                "title": "Verifique as conclusões não confirmadas",
                "body": f"{health['uncertain']} operações sem conclusão confirmada no período. O custo pode incluir a reserva conservadora.",
            }
        )
    if funnel["registered"] > funnel["activated"]:
        result.append(
            {
                "tone": "info",
                "title": "Acompanhe a primeira experiência",
                "body": f"{funnel['registered'] - funnel['activated']} contas criadas no período ainda não têm uma operação concluída pelo servidor nesse período.",
            }
        )
    limit = Decimal(budget["limit_usd"])
    if limit > 0 and Decimal(budget["remaining_usd"]) <= limit * Decimal("0.2"):
        result.append(
            {
                "tone": "warning",
                "title": "O orçamento mensal exige atenção",
                "body": "Restam 20% ou menos do limite após custos contabilizados e reservas. O orçamento segue o mês UTC, independentemente do filtro.",
            }
        )
    projected = budget["projected_usd"]
    if limit > 0 and projected is not None and Decimal(projected) > limit:
        result.append(
            {
                "tone": "warning",
                "title": "O ritmo de gasto supera o limite mensal",
                "body": "A projeção linear usa o gasto contabilizado até agora. É uma estimativa, sem previsão de crescimento ou receita.",
            }
        )
    if not metrics["operations"]:
        result.append(
            {
                "tone": "info",
                "title": "Ainda não há uso registrado neste período",
                "body": "Amplie o período ou acompanhe a ativação das contas. Uso local e com chave pessoal não aparece neste painel.",
            }
        )
    elif not result:
        result.append(
            {
                "tone": "info",
                "title": "Acompanhe o retorno ao produto",
                "body": f"{metrics['returning_users']} usuários concluíram operações em dois ou mais dias do período. Essa medida indica frequência, não retenção de longo prazo.",
            }
        )
    return result


def overview(days=7):
    """Return aggregate adoption, frequency, confirmed usage and monthly budget."""
    days, start, now = _window(days)
    operations = _ops(start, now)
    cohort = User.objects.filter(date_joined__gte=start, date_joined__lte=now)
    metrics, health = _metrics(operations)
    metrics.update(
        total_users=User.objects.filter(date_joined__lte=now).count(),
        new_users=cohort.count(),
        returning_users=_returning(operations),
        previous=None,
    )
    if days * 2 <= RETENTION_DAYS:
        previous_start = start - timedelta(days=days)
        previous_end = now - timedelta(days=days)
        previous, _ = _metrics(_ops(previous_start, previous_end))
        previous["new_users"] = User.objects.filter(
            date_joined__gte=previous_start, date_joined__lte=previous_end
        ).count()
        metrics["previous"] = previous
    verified_cohort = cohort.filter(
        Exists(
            EmailAddress.objects.filter(
                user_id=OuterRef("pk"), verified=True, primary=True
            )
        )
    )
    cohort_operations = operations.filter(user_id__in=cohort.values("pk"))
    funnel = {
        "registered": metrics["new_users"],
        "verified": verified_cohort.count(),
        "activated": cohort_operations.filter(state="complete")
        .values("user_id")
        .distinct()
        .count(),
        "returning": _returning(cohort_operations),
    }
    budget = _budget(now)
    return {
        "updated_at": now.isoformat(),
        "period": {"days": days, "start": start.isoformat(), "end": now.isoformat()},
        "metrics": metrics,
        "trend": _trend(operations, cohort, start, days),
        "funnel": funnel,
        "budget": budget,
        "health": health,
        "coverage": {
            "operation_days": RETENTION_DAYS,
            "scope": "Uso processado pela conta Clarify; uso local/BYOK não é medido.",
            "revenue_available": False,
            "audio_scope": "Áudio apenas de operações com conclusão confirmada.",
            "cost_scope": "Custo contabilizado; operações incertas podem reter o custo máximo reservado.",
            "previous_available": metrics["previous"] is not None,
        },
        "insights": _insights(metrics, funnel, budget, health),
    }


def _user_query(start, now):
    verified = EmailAddress.objects.filter(
        user_id=OuterRef("pk"),
        email__iexact=OuterRef("email"),
        verified=True,
        primary=True,
    )
    active = _ops(start, now).filter(user_id=OuterRef("pk"), state="complete")
    return User.objects.filter(date_joined__lte=now).annotate(
        verified=Exists(verified), period_active=Exists(active)
    )


def _user_rows(query, start, now):
    rows = list(
        query.values(
            "id",
            "email",
            "date_joined",
            "verified",
            "period_active",
            "is_active",
            "funded_access",
            "hosted_requested_at",
        )
    )
    if not rows:
        return []
    ids = [item["id"] for item in rows]
    totals = {
        item["user_id"]: item
        for item in _ops(start, now)
        .filter(user_id__in=ids)
        .values("user_id")
        .annotate(
            operations=Count("pk"),
            audio_ms=Sum("audio_ms", filter=Q(state="complete")),
            cost=Sum("cost"),
        )
    }
    last = dict(
        _ops(now - timedelta(days=RETENTION_DAYS), now)
        .filter(user_id__in=ids, state="complete")
        .values("user_id")
        .annotate(last=Max("created_at"))
        .values_list("user_id", "last")
    )
    week_start, reset_at = week_bounds(now)
    distributed = FundingPeriod.objects.filter(
        start=week_start, reset_at__gt=now
    ).exists()
    quotas = {
        item["user_id"]: item
        for item in WeeklyQuota.objects.filter(
            user_id__in=ids, period_id=week_start, period__reset_at__gt=now
        ).values("user_id", "allocated_usd", "used_usd", "reserved_usd")
    }
    result = []
    for item in rows:
        aggregate = totals.get(item["id"], {})
        quota = quotas.get(item["id"], {})
        allocated = quota.get("allocated_usd", Decimal(0))
        used = reserved = remaining = Decimal(0)
        if allocated > 0:
            used = min(Decimal(100), quota["used_usd"] * 100 / allocated)
            reserved = min(100 - used, quota["reserved_usd"] * 100 / allocated)
            remaining = max(Decimal(0), 100 - used - reserved)
        # Describe persisted allocation only. Unlike ledger.usage(), this read
        # must not request access, distribute funding or admit processing.
        if not (item["is_active"] and item["funded_access"] and item["verified"]):
            allocation_status = "inactive"
        elif allocated > 0:
            allocation_status = "available"
        elif item["hosted_requested_at"] is None:
            allocation_status = "not_requested"
        elif not distributed:
            allocation_status = "not_distributed"
        else:
            allocation_status = "waiting"
        activity = last.get(item["id"])
        result.append(
            {
                "id": str(item["id"]),
                "email": item["email"],
                "date_joined": item["date_joined"].isoformat(),
                "verified": item["verified"],
                "is_active": item["is_active"],
                "funded_access": item["funded_access"],
                "last_active_at": activity.isoformat() if activity else None,
                "operations": aggregate.get("operations", 0),
                "audio_minutes": _minutes(aggregate.get("audio_ms")),
                "cost_usd": _money(aggregate.get("cost")),
                "quota": {
                    "schema_version": 2,
                    "period_start": week_start.isoformat(),
                    "reset_at": reset_at.isoformat(),
                    "used_percent": round(float(used), 6),
                    "reserved_percent": round(float(reserved), 6),
                    "remaining_percent": round(float(remaining), 6),
                    "allocation_status": allocation_status,
                },
                "status": "unverified"
                if not item["verified"]
                else "active"
                if item["period_active"]
                else "inactive",
            }
        )
    return result


def users(days=7, search="", segment="all", page=1):
    """Return a bounded user page, with fixed-query-count usage and quota."""
    _, start, now = _window(days)
    if not isinstance(search, str) or len(search) > 254:
        raise ValueError("Search must contain at most 254 characters")
    if segment not in {"all", "active", "inactive", "unverified"}:
        raise ValueError("Invalid user segment")
    if (
        isinstance(page, bool)
        or not str(page).isascii()
        or not str(page).isdigit()
        or int(page) < 1
    ):
        raise ValueError("Use a positive page number")
    query = _user_query(start, now).filter(email__icontains=search.strip())
    if segment == "unverified":
        query = query.filter(verified=False)
    elif segment == "active":
        query = query.filter(verified=True, period_active=True)
    elif segment == "inactive":
        query = query.filter(verified=True, period_active=False)
    count = query.count()
    pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(int(page), pages)
    offset = (page - 1) * PAGE_SIZE
    query = query.order_by("-date_joined", "-id")[offset : offset + PAGE_SIZE]
    return {
        "results": _user_rows(query, start, now),
        "page": page,
        "pages": pages,
        "count": count,
    }


def user_detail(user_id, days=7):
    """Return retained usage for one account, without private content."""
    days, start, now = _window(days)
    try:
        user_id = uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid user identifier") from None
    rows = _user_rows(_user_query(start, now).filter(pk=user_id), start, now)
    if not rows:
        raise User.DoesNotExist()
    operations = _ops(start, now).filter(user_id=user_id)
    _, health = _metrics(operations)
    registrations = User.objects.filter(
        pk=user_id, date_joined__gte=start, date_joined__lte=now
    )
    return {
        "user": rows[0],
        "trend": _trend(operations, registrations, start, days),
        "health": health,
    }
