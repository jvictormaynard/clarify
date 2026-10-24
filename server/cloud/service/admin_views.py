"""Private, read-only business administration. Allauth owns authentication."""

from functools import wraps
from pathlib import Path
import secrets

from allauth.account.models import EmailAddress
from allauth.headless.account.views import ConfirmLoginCodeView, RequestLoginCodeView
from django.conf import settings
from django.contrib.auth import logout
from django.http import FileResponse, HttpResponseNotFound, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import User
from .middleware import take_rate
from .admin_auth import take_confirmation_attempt


AUTH_PATHS = frozenset(
    {
        "/_allauth/browser/v1/auth/code/request",
        "/_allauth/browser/v1/auth/code/confirm",
    }
)
ASSETS = {"admin.css": "text/css", "admin.js": "text/javascript"}


class AdminBoundary:
    """Isolate browser auth and the dashboard from the native API host."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        admin = request.path == "/admin" or request.path.startswith("/admin/")
        browser = request.path.startswith("/_allauth/browser/")
        host = request.get_host().split(":", 1)[0].lower()
        on_host = bool(
            settings.CLARIFY_ADMIN_HOST and host == settings.CLARIFY_ADMIN_HOST
        )
        if (admin or browser) and not on_host:
            return HttpResponseNotFound()
        if on_host:
            if request.path == "/":
                return redirect("/admin/")
            if browser and request.path not in AUTH_PATHS:
                return HttpResponseNotFound()
            if request.path != "/health" and not admin and not browser:
                return HttpResponseNotFound()
        response = self.get_response(request)
        if admin or browser:
            response["Cache-Control"] = "no-store"
            response["X-Frame-Options"] = "DENY"
            response["Referrer-Policy"] = "no-referrer"
            response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
        return response


class AdminRequestLoginCodeView(RequestLoginCodeView):
    def post(self, request, *args, **kwargs):
        email = self.input.cleaned_data["email"].lower()
        if email not in settings.CLARIFY_ADMIN_EMAILS:
            # Same pending UI for all addresses; never mail or enroll an outsider.
            return JsonResponse(
                {
                    "status": 401,
                    "data": {"flows": [{"id": "login_by_code", "is_pending": True}]},
                },
                status=401,
            )
        if not take_rate("admin_email", email, 3, 600):
            return JsonResponse({"code": "rate_limited"}, status=429)
        request.session.pop("clarify_admin_authenticated_at", None)
        request.session["clarify_admin_pending"] = {
            "email": email,
            "nonce": secrets.token_urlsafe(24),
            "issued_at": timezone.now().timestamp(),
        }
        return super().post(request, *args, **kwargs)


class AdminConfirmLoginCodeView(ConfirmLoginCodeView):
    def dispatch(self, request, *args, **kwargs):
        pending = request.session.get("clarify_admin_pending", {})
        if (
            not isinstance(pending, dict)
            or not pending.get("digest")
            or pending.get("email") not in settings.CLARIFY_ADMIN_EMAILS
            or not 0 <= timezone.now().timestamp() - pending.get("issued_at", 0) < 600
        ):
            return JsonResponse({"code": "sign_in_required"}, status=401)
        # The shared database enforces this bound across workers and concurrent
        # guesses; allauth additionally owns its own attempt count and expiry.
        if request.method == "POST" and not take_confirmation_attempt(pending):
            return JsonResponse({"code": "rate_limited"}, status=429)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        pending = request.session.get("clarify_admin_pending", {})
        email = pending.get("email")
        # A native app request can share the same Django session key. A flag
        # alone is insufficient: prove that this is the exact admin challenge.
        digest = salted_hmac(
            "clarify-admin-code", pending.get("nonce", "") + ":" + self.process.code
        ).hexdigest()
        if (
            not constant_time_compare(digest, pending.get("digest", ""))
            or self.process.state.get("email", "").lower() != email
            or not self.process.user
            or self.process.user.email.lower() != email
        ):
            request.session.pop("clarify_admin_pending", None)
            return JsonResponse({"code": "sign_in_required"}, status=401)
        response = super().post(request, *args, **kwargs)
        if (
            response.status_code == 200
            and request.user.is_authenticated
            and request.user.email.lower() == email
            and email in settings.CLARIFY_ADMIN_EMAILS
        ):
            request.session.pop("clarify_admin_pending", None)
            request.session["clarify_admin_authenticated_at"] = (
                timezone.now().timestamp()
            )
            request.session.set_expiry(8 * 60 * 60)
        return response


def authorized(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({"code": "sign_in_required"}, status=401)
        if not (
            user.is_active
            and user.email.lower() in settings.CLARIFY_ADMIN_EMAILS
            and EmailAddress.objects.filter(
                user=user, email__iexact=user.email, primary=True, verified=True
            ).exists()
        ):
            return JsonResponse({"code": "admin_required"}, status=403)
        authenticated_at = request.session.get("clarify_admin_authenticated_at")
        if (
            not isinstance(authenticated_at, (int, float))
            or isinstance(authenticated_at, bool)
            or not 0 <= timezone.now().timestamp() - authenticated_at < 8 * 60 * 60
        ):
            return JsonResponse({"code": "sign_in_required"}, status=401)
        return view(request, *args, **kwargs)

    return guarded


@require_GET
@ensure_csrf_cookie
def dashboard(request):
    return render(request, "admin/dashboard.html")


@require_GET
def asset(request, name):
    if name not in ASSETS:
        return HttpResponseNotFound()
    path = Path(__file__).with_name("admin_assets") / name
    if not path.is_file():
        return HttpResponseNotFound()
    return FileResponse(path.open("rb"), content_type=ASSETS[name])


@require_GET
@authorized
def session(request):
    return JsonResponse({"email": request.user.email})


@require_POST
def sign_out(request):
    logout(request)
    return JsonResponse({"ok": True})


def query(request, allowed):
    if set(request.GET) - set(allowed) or any(
        len(request.GET.getlist(k)) != 1 for k in request.GET
    ):
        raise ValueError("Invalid query")
    days = int(request.GET.get("days", "14"))
    if days not in (7, 14, 30):
        raise ValueError("Invalid period")
    return days


@require_GET
@authorized
def overview(request):
    from . import admin_analytics

    try:
        days = query(request, {"days"})
        payload = admin_analytics.overview(days)
    except (ValueError, TypeError):
        return JsonResponse({"code": "invalid_query"}, status=400)
    return JsonResponse(payload)


@require_GET
@authorized
def users(request):
    from . import admin_analytics

    try:
        days = query(request, {"days", "search", "segment", "page"})
        payload = admin_analytics.users(
            days,
            request.GET.get("search", ""),
            request.GET.get("segment", "all"),
            int(request.GET.get("page", "1")),
        )
    except (ValueError, TypeError):
        return JsonResponse({"code": "invalid_query"}, status=400)
    return JsonResponse(payload)


@require_GET
@authorized
def user_detail(request, user_id):
    from . import admin_analytics

    try:
        days = query(request, {"days"})
        payload = admin_analytics.user_detail(user_id, days)
    except User.DoesNotExist:
        return JsonResponse({"code": "not_found"}, status=404)
    except (ValueError, TypeError):
        return JsonResponse({"code": "invalid_query"}, status=400)
    if payload is None:
        return JsonResponse({"code": "not_found"}, status=404)
    return JsonResponse(payload)
