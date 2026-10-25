"""Public, anonymous finance views. Provider HTTP runs only in the sync command."""

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
import re
from urllib.parse import urlencode

from django.conf import settings
from django.db import DatabaseError
from django.http import FileResponse, HttpResponseNotFound, JsonResponse
from django.shortcuts import render
from django.utils import timezone, translation
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from . import stripe_finance
from .transparency_models import (
    PublicFinanceSnapshot,
    PublicStripeBalance,
    PublicStripeMovement,
)
from .funding import read_snapshot

PAGE_SIZE = 50
STALE_AFTER = timedelta(hours=24)
ASSETS = {"transparency.css": "text/css; charset=utf-8"}
BUDGET_FIELDS = (
    "received_usd",
    "operating_spent_usd",
    "operating_reserved_usd",
    "processing_spent_usd",
    "allocated_usd",
    "available_usd",
    "newcomers_reserved_usd",
)
BUDGET_KINDS = frozenset(
    {
        "contribution",
        "receipt",
        "deposit",
        "operating_expense",
        "operating_reserve",
        "operating_release",
        "processing",
        "processing_cost",
        "processing_estimate",
        "historical_processing_cost",
        "allocation",
        "refund",
        "adjustment",
    }
)
# Stripe's API uses two decimal amounts for the ISK and UGX special cases.
ZERO_DECIMAL = frozenset(
    "bif clp djf gnf jpy kmf krw mga pyg rwf vnd vuv xaf xof xpf".split()
)
THREE_DECIMAL = frozenset({"bhd", "jod", "kwd", "omr", "tnd"})

COPY = {
    "en": {
        "title": "Where the money goes",
        "nav": "Financial transparency",
        "skip": "Skip to finances",
        "intro": "Clarify is maintained without a profit goal. Voluntary support helps pay operating costs and shared processing.",
        "language": "Language",
        "budget": "Project budget",
        "budget_note": "Only confirmed funds enter the project budget. The Stripe balance is shown separately.",
        "stripe": "Stripe balance",
        "stripe_note": "This is the balance held at Stripe. It is separate from the project budget and does not show the full project treasury.",
        "available": "Available",
        "pending": "Pending",
        "currency": "Currency",
        "updated": "Updated",
        "last_sync": "Last successful Stripe sync",
        "not_configured": "Stripe is not connected yet. No Stripe balances or receipts are published.",
        "not_synced": "Stripe is configured. The first successful sync is still pending.",
        "test_mode": "Stripe test mode is excluded. Test payments do not fund Clarify.",
        "invalid_configuration": "The Stripe connection is not ready. Financial data is unavailable.",
        "ready": "Live Stripe data",
        "stale": "Stripe data is stale. The last successful snapshot is shown.",
        "empty": "The last sync found no Stripe balances or movements.",
        "unavailable": "The project ledger is not available yet.",
        "sync_failed": "The latest Stripe sync failed. The last successful snapshot is shown when available.",
        "complete": "All Stripe movements returned by the last sync are included.",
        "partial": "History is incomplete. Each sync includes up to 10,000 movements. Older movements are not included.",
        "stripe_movements": "Stripe movements",
        "project_movements": "Project budget movements",
        "no_movements": "No movements to show.",
        "time": "Time (UTC)",
        "kind": "Movement",
        "amount": "Amount",
        "fee": "Fee",
        "net": "Net",
        "availability": "Availability",
        "available_on": "Available on (UTC)",
        "payout_note": "Payouts move money out of Stripe. They are transfers, not operating expenses. Fees and refunds are shown explicitly.",
        "privacy": "Public records show amounts and neutral labels. Donor names, contact details and payment identifiers stay private.",
        "rules": "How shared funding works",
        "operations": "We reserve operating costs first.",
        "split": "Of the remaining processing budget, 80% supports the weekly pool and 20% is reserved for newcomers.",
        "quota": "Each account has an individual quota. Quotas reset together on Monday at 00:00 UTC. Use also depends on available project funding.",
        "support": "Support Clarify",
        "support_note": "Support is voluntary. Stripe handles payment on its own secure page.",
        "support_pending": "Online sponsorship is not available yet.",
        "previous": "Previous",
        "next": "Next",
        "page": "Page",
        "of": "of",
        "records": "records",
        "api": "Public finance data (JSON)",
        "received_usd": "Confirmed receipts",
        "operating_spent_usd": "Operating costs paid",
        "operating_reserved_usd": "Operating costs reserved",
        "processing_spent_usd": "Processing costs (including estimates)",
        "allocated_usd": "Processing allocated",
        "available_usd": "Budget available",
        "newcomers_reserved_usd": "Reserved for newcomers",
        "payment": "Payment",
        "refund": "Refund",
        "fee_kind": "Stripe fee",
        "payout": "Payout transfer",
        "transfer": "Transfer",
        "adjustment": "Balance adjustment",
        "contribution": "Contribution",
        "receipt": "Receipt",
        "deposit": "Deposit",
        "operating_expense": "Operating expense",
        "operating_reserve": "Operating reserve",
        "operating_release": "Operating reserve released",
        "processing": "Processing",
        "processing_cost": "Processing cost",
        "processing_estimate": "Estimated processing cost",
        "historical_processing_cost": "Historical processing cost",
        "before_weekly_accounting": "Before weekly accounting",
        "allocation": "Allocation",
    },
    "pt": {
        "title": "Para onde vai o dinheiro",
        "nav": "Transparência financeira",
        "skip": "Ir para as finanças",
        "intro": "O Clarify é mantido sem objetivo de lucro. O apoio voluntário ajuda a pagar os custos de operação e o processamento compartilhado.",
        "language": "Idioma",
        "budget": "Orçamento do projeto",
        "budget_note": "Somente recursos confirmados entram no orçamento do projeto. O saldo no Stripe aparece separadamente.",
        "stripe": "Saldo no Stripe",
        "stripe_note": "Este é o saldo mantido no Stripe. Ele é separado do orçamento do projeto e não mostra todos os recursos financeiros do projeto.",
        "available": "Disponível",
        "pending": "Pendente",
        "currency": "Moeda",
        "updated": "Atualizado",
        "last_sync": "Última sincronização bem-sucedida com o Stripe",
        "not_configured": "O Stripe ainda não está conectado. Nenhum saldo ou recebimento do Stripe está publicado.",
        "not_synced": "O Stripe está configurado. A primeira sincronização bem-sucedida ainda está pendente.",
        "test_mode": "O modo de teste do Stripe está excluído. Pagamentos de teste não financiam o Clarify.",
        "invalid_configuration": "A conexão com o Stripe não está pronta. Os dados financeiros estão indisponíveis.",
        "ready": "Dados reais do Stripe",
        "stale": "Os dados do Stripe estão desatualizados. A última cópia sincronizada está em exibição.",
        "empty": "A última sincronização não encontrou saldos ou movimentações no Stripe.",
        "unavailable": "O livro financeiro do projeto ainda não está disponível.",
        "sync_failed": "A última tentativa de sincronização com o Stripe falhou. A última cópia bem-sucedida é exibida quando disponível.",
        "complete": "Todas as movimentações retornadas pela última sincronização com o Stripe estão incluídas.",
        "partial": "O histórico está incompleto. Cada sincronização inclui até 10.000 movimentações. As movimentações mais antigas não estão incluídas.",
        "stripe_movements": "Movimentações do Stripe",
        "project_movements": "Movimentações do orçamento",
        "no_movements": "Nenhuma movimentação para exibir.",
        "time": "Data e hora (UTC)",
        "kind": "Movimentação",
        "amount": "Valor",
        "fee": "Tarifa",
        "net": "Líquido",
        "availability": "Disponibilidade",
        "available_on": "Disponível em (UTC)",
        "payout_note": "Os repasses retiram dinheiro do Stripe. Eles são transferências, não despesas de operação. As tarifas e os reembolsos são exibidos de forma explícita.",
        "privacy": "Os registros públicos mostram valores e descrições neutras. Nomes, contatos e identificadores de pagamento dos doadores são privados.",
        "rules": "Como funciona o financiamento compartilhado",
        "operations": "Primeiro, reservamos os custos de operação.",
        "split": "Do orçamento restante para processamento, 80% vai para o fundo semanal e 20% fica reservado para novos usuários.",
        "quota": "Cada conta tem uma cota individual. As cotas são renovadas juntas na segunda-feira às 00:00 UTC. O uso também depende dos fundos disponíveis no projeto.",
        "support": "Apoiar o Clarify",
        "support_note": "O apoio é voluntário. O Stripe recebe o pagamento na própria página segura.",
        "support_pending": "O patrocínio on-line ainda não está disponível.",
        "previous": "Anterior",
        "next": "Próxima",
        "page": "Página",
        "of": "de",
        "records": "registros",
        "api": "Dados financeiros públicos (JSON)",
        "received_usd": "Recebimentos confirmados",
        "operating_spent_usd": "Custos de operação pagos",
        "operating_reserved_usd": "Custos de operação reservados",
        "processing_spent_usd": "Custos de processamento (incluindo estimativas)",
        "allocated_usd": "Processamento alocado",
        "available_usd": "Orçamento disponível",
        "newcomers_reserved_usd": "Reserva para novos usuários",
        "payment": "Pagamento",
        "refund": "Reembolso",
        "fee_kind": "Tarifa do Stripe",
        "payout": "Repasse por transferência",
        "transfer": "Transferência",
        "adjustment": "Ajuste de saldo",
        "contribution": "Contribuição",
        "receipt": "Recebimento",
        "deposit": "Depósito",
        "operating_expense": "Despesa de operação",
        "operating_reserve": "Reserva de operação",
        "operating_release": "Reserva de operação liberada",
        "processing": "Processamento",
        "processing_cost": "Custo de processamento",
        "processing_estimate": "Custo de processamento estimado",
        "historical_processing_cost": "Custo histórico de processamento",
        "before_weekly_accounting": "Anterior ao controle semanal",
        "allocation": "Alocação",
    },
    "es": {
        "title": "Adónde va el dinero",
        "nav": "Transparencia financiera",
        "skip": "Ir a las finanzas",
        "intro": "Clarify se mantiene sin objetivo de lucro. El apoyo voluntario ayuda a pagar los costos de operación y el procesamiento compartido.",
        "language": "Idioma",
        "budget": "Presupuesto del proyecto",
        "budget_note": "Solo los fondos confirmados entran en el presupuesto del proyecto. El saldo de Stripe se muestra por separado.",
        "stripe": "Saldo en Stripe",
        "stripe_note": "Este es el saldo que mantiene Stripe. Es independiente del presupuesto del proyecto y no muestra todos los recursos financieros del proyecto.",
        "available": "Disponible",
        "pending": "Pendiente",
        "currency": "Moneda",
        "updated": "Actualizado",
        "last_sync": "Última sincronización correcta con Stripe",
        "not_configured": "Stripe aún no está conectado. No se publican saldos ni ingresos de Stripe.",
        "not_synced": "Stripe está configurado. La primera sincronización correcta sigue pendiente.",
        "test_mode": "El modo de prueba de Stripe está excluido. Los pagos de prueba no financian Clarify.",
        "invalid_configuration": "La conexión con Stripe no está lista. Los datos financieros no están disponibles.",
        "ready": "Datos reales de Stripe",
        "stale": "Los datos de Stripe están desactualizados. Se muestra la última copia sincronizada.",
        "empty": "La última sincronización no encontró saldos ni movimientos en Stripe.",
        "unavailable": "El libro financiero del proyecto aún no está disponible.",
        "sync_failed": "El último intento de sincronización con Stripe falló. Se muestra la última copia correcta cuando está disponible.",
        "complete": "Se incluyen todos los movimientos devueltos por la última sincronización con Stripe.",
        "partial": "El historial está incompleto. Cada sincronización incluye hasta 10.000 movimientos. Los movimientos más antiguos no se incluyen.",
        "stripe_movements": "Movimientos de Stripe",
        "project_movements": "Movimientos del presupuesto",
        "no_movements": "No hay movimientos para mostrar.",
        "time": "Fecha y hora (UTC)",
        "kind": "Movimiento",
        "amount": "Importe",
        "fee": "Comisión",
        "net": "Neto",
        "availability": "Disponibilidad",
        "available_on": "Disponible el (UTC)",
        "payout_note": "Los desembolsos retiran dinero de Stripe. Son transferencias, no gastos de operación. Las comisiones y los reembolsos se muestran de forma explícita.",
        "privacy": "Los registros públicos muestran importes y etiquetas neutras. Los nombres, contactos e identificadores de pago de los donantes son privados.",
        "rules": "Cómo funciona la financiación compartida",
        "operations": "Primero reservamos los costos de operación.",
        "split": "Del presupuesto restante para procesamiento, el 80% va al fondo semanal y el 20% se reserva para nuevos usuarios.",
        "quota": "Cada cuenta tiene una cuota individual. Las cuotas se renuevan juntas el lunes a las 00:00 UTC. El uso también depende de los fondos disponibles del proyecto.",
        "support": "Apoyar a Clarify",
        "support_note": "El apoyo es voluntario. Stripe recibe el pago en su propia página segura.",
        "support_pending": "El patrocinio en línea aún no está disponible.",
        "previous": "Anterior",
        "next": "Siguiente",
        "page": "Página",
        "of": "de",
        "records": "registros",
        "api": "Datos financieros públicos (JSON)",
        "received_usd": "Ingresos confirmados",
        "operating_spent_usd": "Costos de operación pagados",
        "operating_reserved_usd": "Costos de operación reservados",
        "processing_spent_usd": "Costos de procesamiento (incluidas las estimaciones)",
        "allocated_usd": "Procesamiento asignado",
        "available_usd": "Presupuesto disponible",
        "newcomers_reserved_usd": "Reserva para nuevos usuarios",
        "payment": "Pago",
        "refund": "Reembolso",
        "fee_kind": "Comisión de Stripe",
        "payout": "Desembolso por transferencia",
        "transfer": "Transferencia",
        "adjustment": "Ajuste de saldo",
        "contribution": "Contribución",
        "receipt": "Ingreso",
        "deposit": "Depósito",
        "operating_expense": "Gasto de operación",
        "operating_reserve": "Reserva de operación",
        "operating_release": "Reserva de operación liberada",
        "processing": "Procesamiento",
        "processing_cost": "Costo de procesamiento",
        "processing_estimate": "Costo estimado de procesamiento",
        "historical_processing_cost": "Costo histórico de procesamiento",
        "before_weekly_accounting": "Anterior al control semanal",
        "allocation": "Asignación",
    },
}


def public(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        host = request.get_host().split(":", 1)[0].lower()
        if host == getattr(settings, "CLARIFY_ADMIN_HOST", ""):
            response = HttpResponseNotFound()
        else:
            try:
                response = view(request, *args, **kwargs)
            except DatabaseError:
                response = JsonResponse({"code": "finance_unavailable"}, status=503)
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Referrer-Policy"] = "no-referrer"
        response["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response["Cross-Origin-Resource-Policy"] = "same-origin"
        response["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; img-src 'self'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
        )
        return response

    return guarded


def _time(value):
    if isinstance(value, str):
        if len(value) > 40:
            raise ValueError()
        value = parse_datetime(value)
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValueError()
    return value.astimezone(dt_timezone.utc).isoformat()


def _money(value):
    if not isinstance(value, (str, Decimal)) or len(str(value)) > 40:
        raise ValueError()
    amount = Decimal(value)
    if not amount.is_finite() or abs(amount) >= Decimal("1000000000"):
        raise ValueError()
    return format(amount.quantize(Decimal("0.000000001")), "f")


def _minor(value, currency):
    stripe_finance._integer(value)
    places = 0 if currency in ZERO_DECIMAL else 3 if currency in THREE_DECIMAL else 2
    return format(Decimal(value).scaleb(-places), "." + str(places) + "f")


def _pagination(total, page):
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if not 1 <= page <= pages:
        raise ValueError()
    return {
        "page": page,
        "pages": pages,
        "page_size": PAGE_SIZE,
        "total": total,
        "previous": page - 1 if page > 1 else None,
        "next": page + 1 if page < pages else None,
    }


def project_summary(*, page=1):
    # Read only the requested page from the durable project ledger.
    from .funding import public_summary

    return public_summary(page=page, page_size=PAGE_SIZE)


def _budget(page):
    unavailable = {
        "state": "unavailable",
        "currency": "usd",
        "movements": [],
        "pagination": _pagination(0, 1),
    }
    try:
        raw = project_summary(page=page)
        if not isinstance(raw, dict) or raw.get("currency") != "usd":
            return unavailable
        result = {field: _money(raw.get(field)) for field in BUDGET_FIELDS}
        result["updated_at"] = (
            _time(raw.get("updated_at")) if raw.get("updated_at") else None
        )
        rows = raw.get("movements")
        if not isinstance(rows, list):
            return unavailable
        total = raw.get("movements_total")
        if type(total) is not int or total < 0:
            return unavailable
        paging = _pagination(total, page)
        if len(rows) != min(PAGE_SIZE, max(0, total - (page - 1) * PAGE_SIZE)):
            return unavailable
        movements = []
        for row in rows:
            if not isinstance(row, dict):
                return unavailable
            kind = row.get("kind")
            kind = (
                kind if isinstance(kind, str) and kind in BUDGET_KINDS else "adjustment"
            )
            occurred_at = row.get("occurred_at")
            occurred_at = (
                None
                if kind == "historical_processing_cost" and occurred_at is None
                else _time(occurred_at)
            )
            movements.append(
                {
                    "occurred_at": occurred_at,
                    "kind": kind,
                    "amount": _money(row.get("amount_usd")),
                    "currency": "usd",
                    "label": COPY["en"][kind],
                    "source": "project",
                }
            )
        return {
            "state": "ready",
            "currency": "usd",
            **result,
            "movements": movements,
            "pagination": paging,
        }
    except (ImportError, ValueError, TypeError, InvalidOperation):
        return unavailable


def _stripe(page, now):
    state = stripe_finance.configuration_state()
    result = {
        "state": state,
        "last_successful_sync": None,
        "stale": False,
        "sync_failed": False,
        "history_complete": False,
        "balances": [],
        "movements": [],
        "pagination": _pagination(0, 1),
    }
    if state != "configured":
        return result
    result["state"] = "not_synced"
    snapshot = PublicFinanceSnapshot.objects.filter(
        pk=1, configuration_tag=stripe_finance.configuration_tag()
    ).first()
    if not snapshot:
        return result
    result["sync_failed"] = bool(snapshot.error_code)
    if not snapshot.synced_at:
        return result
    result["last_successful_sync"] = _time(snapshot.synced_at)
    result["stale"] = (
        bool(snapshot.error_code)
        or now - snapshot.synced_at > STALE_AFTER
        or snapshot.synced_at > now
    )
    result["state"] = "stale" if result["stale"] else "ready"
    result["history_complete"] = snapshot.history_complete is True
    for row in PublicStripeBalance.objects.filter(snapshot=snapshot).order_by(
        "currency"
    ):
        currency = stripe_finance._currency(row.currency)
        result["balances"].append(
            {
                "currency": currency,
                "available": _minor(row.available_minor, currency),
                "pending": _minor(row.pending_minor, currency),
            }
        )
    rows = PublicStripeMovement.objects.filter(snapshot=snapshot).order_by("position")
    result["pagination"] = _pagination(rows.count(), page)
    for row in rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]:
        currency = stripe_finance._currency(row.currency)
        kind = row.kind if row.kind in stripe_finance.KINDS else "adjustment"
        result["movements"].append(
            {
                "occurred_at": _time(row.occurred_at),
                "available_on": _time(row.available_on),
                "kind": kind,
                "label": stripe_finance.LABELS[kind],
                "currency": currency,
                "amount": _minor(row.amount_minor, currency),
                "fee": _minor(row.fee_minor, currency),
                "net": _minor(row.net_minor, currency),
                "availability": row.availability
                if row.availability in {"available", "pending"}
                else "pending",
            }
        )
    if not result["balances"] and not result["pagination"]["total"]:
        if not result["stale"]:
            result["state"] = "empty"
    return result


def _payment_link(stripe):
    value = getattr(settings, "CLARIFY_STRIPE_PAYMENT_LINK", "")
    if (
        getattr(settings, "CLARIFY_STRIPE_PAYMENT_LINK_VERIFIED", False) is True
        and stripe["last_successful_sync"]
        and isinstance(value, str)
        and re.fullmatch(r"https://buy\.stripe\.com/[A-Za-z0-9]{1,200}", value)
    ):
        return value
    return None


def _query(request):
    if set(request.GET) - {"lang", "stripe_page", "budget_page"} or any(
        len(request.GET.getlist(k)) != 1 for k in request.GET
    ):
        raise ValueError()
    language = request.GET.get("lang")
    if language is None:
        language = translation.get_language_from_request(request).split("-", 1)[0]
    if language not in COPY:
        language = "en"
    pages = []
    for key in ("stripe_page", "budget_page"):
        value = request.GET.get(key, "1")
        if not re.fullmatch(r"[1-9][0-9]{0,5}", value):
            raise ValueError()
        pages.append(int(value))
    return language, *pages


def _data(stripe_page, budget_page):
    # One read snapshot covers both ledgers without blocking financial writers.
    with read_snapshot():
        stripe = _stripe(stripe_page, timezone.now())
        budget = _budget(budget_page)
        if (
            stripe["pagination"]["page"] != stripe_page
            or budget["pagination"]["page"] != budget_page
        ):
            raise ValueError()
    return {
        "schema_version": 1,
        "stripe": stripe,
        "project_budget": budget,
        "sponsorship": {"payment_link": _payment_link(stripe)},
    }


@public
@require_GET
def summary(request):
    try:
        _, stripe_page, budget_page = _query(request)
        data = _data(stripe_page, budget_page)
    except ValueError:
        return JsonResponse({"code": "invalid_query"}, status=400)
    except stripe_finance.StripeSyncError:
        return JsonResponse({"code": "finance_unavailable"}, status=503)
    return JsonResponse(data)


def _display_money(value):
    whole, _, fraction = value.partition(".")
    return whole + "." + fraction.rstrip("0").ljust(2, "0")


@public
@require_GET
def page(request):
    try:
        language, stripe_page, budget_page = _query(request)
        data = _data(stripe_page, budget_page)
    except ValueError:
        return JsonResponse({"code": "invalid_query"}, status=400)
    except stripe_finance.StripeSyncError:
        return JsonResponse({"code": "finance_unavailable"}, status=503)
    copy = COPY[language]

    def link(**changes):
        return "?" + urlencode(
            {
                "lang": language,
                "stripe_page": stripe_page,
                "budget_page": budget_page,
                **changes,
            }
        )

    for field, key in (("stripe", "stripe_page"), ("project_budget", "budget_page")):
        section = data[field]
        for row in section["movements"]:
            row["label"] = copy["fee_kind" if row["kind"] == "fee" else row["kind"]]
            if "availability" in row:
                row["availability_label"] = copy[row["availability"]]
            else:
                row["amount"] = _display_money(row["amount"])
        section["previous_url"] = (
            link(**{key: section["pagination"]["previous"]})
            if section["pagination"]["previous"]
            else None
        )
        section["next_url"] = (
            link(**{key: section["pagination"]["next"]})
            if section["pagination"]["next"]
            else None
        )
    budget_cards = (
        [
            {
                "label": copy[field],
                "amount": _display_money(data["project_budget"][field]),
            }
            for field in BUDGET_FIELDS
        ]
        if data["project_budget"]["state"] == "ready"
        else []
    )
    return render(
        request,
        "public/transparency.html",
        {
            "copy": copy,
            "language": language,
            **data,
            "budget_cards": budget_cards,
            "stripe_state": copy[data["stripe"]["state"]],
            "languages": [
                {"code": code, "label": label, "url": link(lang=code)}
                for code, label in (
                    ("pt", "Português"),
                    ("en", "English"),
                    ("es", "Español"),
                )
            ],
            "api_url": "/v1/public/finances" + link(),
        },
    )


@public
@require_GET
def asset(request, name):
    if name not in ASSETS:
        return HttpResponseNotFound()
    path = Path(__file__).with_name("public_assets") / name
    return FileResponse(path.open("rb"), content_type=ASSETS[name])
