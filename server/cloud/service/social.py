"""PKCE-bound, one-time native handoff of allauth-owned OAuth sessions.

The browser holds OAuth state only. Callback work and result claims lock the
same attempt row so cancellation, expiry and concurrent polls cannot publish
an abandoned or duplicate credential. Provider HTTP remains inside allauth.
"""

import base64
import hashlib
import json
import re
import secrets
from smtplib import SMTPException
from datetime import timedelta
from uuid import UUID

from allauth.account.internal.stagekit import get_pending_stage
from allauth.account.internal.flows.email_verification import (
    consume_email_verification_rate_limit,
)
from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter, get_adapter
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.base import AuthProcess
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.exceptions import MultipleObjectsReturned, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.translation import get_language
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from shared.localization import language, translate

from .middleware import take_rate
from .models import SocialAttempt, User


PROVIDERS = frozenset({"google", "microsoft", "github"})
BROWSER_KEY = "clarify_social_browser"
HANDOFF_KEY = "clarify_social_handoff"
LIFETIME = 300


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def response(data=None, status=200):
    result = (
        HttpResponse(status=status)
        if data is None
        else JsonResponse(data, status=status)
    )
    return secure_response(result)


def secure_response(result):
    result["Cache-Control"] = "no-store"
    # Keep the form POST's Origin; never send the invitation URL to a provider.
    result["Referrer-Policy"] = "same-origin"
    result["X-Frame-Options"] = "DENY"
    result["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    return result


def browser_page(request, template, **context):
    locale = language(get_language())
    messages = {
        "title": "Entrar no Clarify",
        "warning": "Continue com {v0} somente se você iniciou a entrada no aplicativo Clarify neste dispositivo. Não continue por um link enviado por outra pessoa.",
        "continue_label": "Continuar com {v0}",
        "cancel_hint": "Você pode fechar esta página para cancelar.",
        "opening": "Abrindo o provedor de entrada.",
        "continue_sign_in": "Continuar entrada",
        "return_title": "Voltar ao Clarify",
        "return_body": "Você pode fechar esta página. Seu aplicativo Clarify mostrará o resultado da entrada.",
    }
    copy = {
        key: translate(source, locale, v0=context.get("provider", ""))
        for key, source in messages.items()
    }
    if "client" in context:
        context["client"] = translate(context["client"], locale)
    return secure_response(
        render(request, template, {**context, **copy, "language": locale})
    )


def failed(status=400):
    result = response(
        {"code": "rate_limited" if status == 429 else "social_login_failed"}, status
    )
    if status == 429:
        result["Retry-After"] = "5"
    return result


def payload(request, fields):
    if request.content_type != "application/json" or len(request.body) > 2048:
        return None
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or set(data) != set(fields):
        return None
    if not all(isinstance(value, str) for value in data.values()):
        return None
    return data


def configured(request, provider):
    # Settings are the sole app configuration boundary, including disablement.
    apps = settings.SOCIALACCOUNT_PROVIDERS.get(provider, {}).get("APPS", [])
    if len(apps) != 1 or not apps[0].get("client_id") or not apps[0].get("secret"):
        return None
    try:
        return get_adapter(request).get_provider(request, provider)
    except (SocialApp.DoesNotExist, MultipleObjectsReturned):
        return None


def finish_path(client):
    return reverse("social_finish", kwargs={"client": client})


def revoke(attempt, state):
    Session.objects.filter(
        session_key__in=[attempt.session_key, attempt.browser_session_key]
    ).delete()
    attempt.session_key = ""
    attempt.browser_session_key = ""
    attempt.browser_digest = ""
    attempt.launch_digest = ""
    attempt.email = ""
    attempt.user = None
    attempt.state = state
    attempt.save()


def expire_attempts():
    """Bounded opportunistic cleanup; DB session expiry also invalidates access."""
    ids = list(
        SocialAttempt.objects.filter(expires_at__lte=timezone.now()).values_list(
            "pk", flat=True
        )[:100]
    )
    for attempt_id in ids:
        with transaction.atomic():
            attempt = (
                SocialAttempt.objects.select_for_update().filter(pk=attempt_id).first()
            )
            if attempt and attempt.expires_at <= timezone.now():
                revoke(attempt, "expired")
                attempt.delete()


@csrf_exempt
@require_POST
def start(request):
    data = payload(request, {"provider", "client", "code_challenge"})
    if (
        not request.is_secure()
        or not data
        or data["provider"] not in PROVIDERS
        or data["client"] not in {"desktop", "ios"}
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", data["code_challenge"])
    ):
        return failed()
    # Reject noncanonical base64url encodings (SHA256 has 256 bits).
    challenge = data["code_challenge"]
    if (
        base64.urlsafe_b64encode(base64.urlsafe_b64decode(challenge + "="))
        .decode()
        .rstrip("=")
        != challenge
    ):
        return failed()
    if not configured(request, data["provider"]):
        return failed()
    if not take_rate("social_start", request.META.get("REMOTE_ADDR", "unknown"), 6):
        return failed(429)
    expire_attempts()
    launch = secrets.token_urlsafe(32)
    attempt = SocialAttempt.objects.create(
        provider=data["provider"],
        client=data["client"],
        challenge=challenge,
        origin=request.get_host(),
        launch_digest=digest(launch),
        expires_at=timezone.now() + timedelta(seconds=LIFETIME),
    )
    url = reverse(
        "social_authorize", kwargs={"attempt_id": attempt.pk, "launch": launch}
    )
    return response(
        {
            "attempt_id": str(attempt.pk),
            "authorization_url": request.build_absolute_uri(url),
            "expires_in": LIFETIME,
            "interval": 5,
        }
    )


@require_http_methods(["GET", "POST"])
def authorize(request, attempt_id, launch):
    with transaction.atomic():
        attempt = (
            SocialAttempt.objects.select_for_update().filter(pk=attempt_id).first()
        )
        if (
            not attempt
            or attempt.state != "created"
            or attempt.expires_at <= timezone.now()
        ):
            return response(status=410)
        if (
            not request.is_secure()
            or attempt.origin != request.get_host()
            or not constant_time_compare(digest(launch), attempt.launch_digest)
        ):
            return failed()
        if request.method == "GET":
            return browser_page(
                request,
                "social/authorize.html",
                provider={
                    "google": "Google",
                    "microsoft": "Microsoft",
                    "github": "GitHub",
                }[attempt.provider],
                client="Clarify para iOS"
                if attempt.client == "ios"
                else "Clarify para computador",
            )
        provider = configured(request, attempt.provider)
        if not provider:
            attempt.error = "social_login_failed"
            attempt.state = "error"
            attempt.save()
            return secure_response(HttpResponseRedirect(finish_path(attempt.client)))
        # Never reuse a browser's logged-in or pending allauth session. The
        # explicit CSRF-protected confirmation also prevents silent initiation.
        previous = request.session.get(BROWSER_KEY, {})
        if previous.get("attempt"):
            old = (
                SocialAttempt.objects.select_for_update()
                .filter(pk=previous["attempt"])
                .first()
            )
            if old:
                revoke(old, "cancelled")
        request.session.flush()
        nonce = secrets.token_urlsafe(32)
        request.session[BROWSER_KEY] = {"attempt": str(attempt.pk), "nonce": nonce}
        request.session.set_expiry(attempt.expires_at)
        request.session.save()
        attempt.browser_digest = digest(nonce)
        attempt.browser_session_key = request.session.session_key
        attempt.launch_digest = ""
        attempt.state = "pending"
        attempt.save()
        provider_response = provider.redirect(
            request,
            process=AuthProcess.LOGIN,
            next_url=finish_path(attempt.client),
            headless=True,
            data={"attempt": str(attempt.pk)},
        )
        # End the form navigation before provider navigation. Chromium applies
        # form-action to redirect chains, including federated provider redirects.
        return browser_page(
            request,
            "social/redirect.html",
            authorization_url=provider_response["Location"],
        )


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form=form)
        if not EmailAddress.objects.filter(
            user=user, primary=True, verified=True
        ).exists():
            # Keep the unverified identity only inside its allauth login stage.
            # An independent email login must never activate an abandoned link.
            sociallogin.account.delete()
        return user

    def on_authentication_error(self, request, provider, **kwargs):
        attempt = getattr(request, "social_attempt", None)
        if attempt:
            request.social_error = "social_login_failed"
            raise ImmediateHttpResponse(
                HttpResponseRedirect(finish_path(attempt.client))
            )
        raise ImmediateHttpResponse(failed())

    def can_authenticate_by_email(self, login, email):
        return False

    def pre_social_login(self, request, sociallogin):
        attempt = getattr(request, "social_attempt", None)
        if (
            not attempt
            or sociallogin.state.get("data") != {"attempt": str(attempt.pk)}
            or sociallogin.state.get("process") != AuthProcess.LOGIN
            or sociallogin.state.get("next") != finish_path(attempt.client)
            or sociallogin.account.provider != attempt.provider
        ):
            raise ImmediateHttpResponse(failed())
        error = ""
        if sociallogin.is_existing:
            if not sociallogin.user.is_active:
                error = "social_login_failed"
        else:
            addresses = sociallogin.email_addresses
            # allauth sorts primary/verified addresses before this hook.
            email = addresses[0].email.lower() if addresses else ""
            try:
                validate_email(email)
            except ValidationError:
                error = "social_email_required"
            if not error:
                if any(
                    User.objects.filter(email__iexact=address.email).exists()
                    or EmailAddress.objects.filter(email__iexact=address.email).exists()
                    for address in addresses
                ):
                    error = "social_account_exists"
                elif not settings.CLARIFY_SIGNUP_ENABLED:
                    error = "social_signup_closed"
                elif not take_rate(
                    "signup", request.META.get("REMOTE_ADDR", "unknown"), 3, 3600
                ) or not take_rate("signup_global", "all", 100, 3600):
                    request.social_rate_limited = True
                    error = "social_login_failed"
                else:
                    # Persist canonical primary email with the existing model.
                    sociallogin.user.email = email
        if error:
            request.social_error = error
            raise ImmediateHttpResponse(
                HttpResponseRedirect(finish_path(attempt.client))
            )
        request.social_identity_validated = True
        request.social_email = sociallogin.user.email
        # These credentials have served their only purpose (provider exchange).
        # Allauth otherwise serializes them inside pending email login sessions.
        sociallogin.token = None
        sociallogin.state.pop("pkce_code_verifier", None)

    def is_open_for_signup(self, request, sociallogin):
        return bool(
            getattr(request, "social_attempt", None) and settings.CLARIFY_SIGNUP_ENABLED
        )


@require_GET
def callback(request, provider):
    binding = request.session.get(BROWSER_KEY, {})
    try:
        attempt_id = UUID(binding.get("attempt", ""))
    except (ValueError, TypeError, AttributeError):
        return failed()
    with transaction.atomic():
        attempt = (
            SocialAttempt.objects.select_for_update().filter(pk=attempt_id).first()
        )
        if not attempt:
            request.session.flush()
            return response(status=410)
        if attempt.state != "pending" or attempt.expires_at <= timezone.now():
            if attempt.state == "pending":
                revoke(attempt, "expired")
            request.session.flush()
            return secure_response(HttpResponseRedirect(finish_path(attempt.client)))
        nonce = binding.get("nonce", "")
        if (
            not request.is_secure()
            or attempt.origin != request.get_host()
            or attempt.provider != provider
            or not constant_time_compare(digest(nonce), attempt.browser_digest)
        ):
            return failed()
        request.social_attempt = attempt
        try:
            if not configured(request, provider):
                request.social_error = "social_login_failed"
                raise ImmediateHttpResponse(failed())
            # A failed signup race must roll back allauth's writes before we
            # record its terminal result in the outer transaction.
            with transaction.atomic():
                from allauth.socialaccount.providers.google.views import (
                    oauth2_callback as google,
                )
                from allauth.socialaccount.providers.microsoft.views import (
                    oauth2_callback as microsoft,
                )
                from allauth.socialaccount.providers.github.views import (
                    oauth2_callback as github,
                )

                provider_response = {
                    "google": google,
                    "microsoft": microsoft,
                    "github": github,
                }[provider](request)
            error = getattr(request, "social_error", "")
            stage = get_pending_stage(request)
            user = (
                request.user
                if request.user.is_authenticated
                else (stage.login.user if stage else None)
            )
            pending = bool(stage and stage.key == "verify_email")
            if (
                not error
                and getattr(request, "social_identity_validated", False)
                and user
                and user.is_active
                and (request.user.is_authenticated or pending)
                and not getattr(request, "clarify_email_limited", False)
            ):
                native = SessionStore()
                native.update(
                    {
                        key: value
                        for key, value in request.session.items()
                        if key
                        not in {
                            BROWSER_KEY,
                            "socialaccount_states",
                            "socialaccount_sociallogin",
                        }
                    }
                )
                native[HANDOFF_KEY] = str(attempt.pk)
                native.set_expiry(attempt.expires_at)
                native.create()
                attempt.session_key = native.session_key
                attempt.user = user
                attempt.email = user.email
                attempt.state = "email" if pending else "ready"
            else:
                attempt.state = "error"
                attempt.error = error or "social_login_failed"
                # Keep rate-limit status within the stated native contract.
                if (
                    getattr(request, "social_rate_limited", False)
                    or getattr(request, "clarify_email_limited", False)
                    or provider_response.status_code == 429
                    or (
                        getattr(request, "social_identity_validated", False)
                        and not stage
                        and not request.user.is_authenticated
                        and not error
                        and not consume_email_verification_rate_limit(
                            request,
                            request.social_email,
                            dry_run=True,
                        )
                    )
                ):
                    attempt.error = "rate_limited"
        except IntegrityError:
            attempt.state, attempt.error = "error", "social_account_exists"
        except ImmediateHttpResponse:
            attempt.state, attempt.error = "error", "social_login_failed"
        except (ValueError, KeyError, TypeError):
            attempt.state, attempt.error = "error", "social_login_failed"
        except (SMTPException, OSError):
            attempt.state, attempt.error = "error", "social_login_failed"
        finally:
            # Delete any pre-login and rotated browser keys. No browser cookie
            # can access the native allauth session, including email continuation.
            request.session.flush()
            Session.objects.filter(session_key=attempt.browser_session_key).delete()
        attempt.browser_session_key = ""
        attempt.browser_digest = ""
        attempt.save()
        request.clarify_email_limited = False
        return secure_response(HttpResponseRedirect(finish_path(attempt.client)))


def native_attempt(request, action):
    data = payload(request, {"attempt_id", "code_verifier"})
    if (
        not request.is_secure()
        or not data
        or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", data["code_verifier"])
    ):
        return failed()
    try:
        attempt_id = UUID(data["attempt_id"])
    except ValueError:
        return failed()
    challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(data["code_verifier"].encode("ascii")).digest()
        )
        .decode()
        .rstrip("=")
    )
    with transaction.atomic():
        attempt = (
            SocialAttempt.objects.select_for_update().filter(pk=attempt_id).first()
        )
        if not attempt:
            return response(status=204 if action == "cancel" else 410)
        if attempt.origin != request.get_host() or not constant_time_compare(
            challenge, attempt.challenge
        ):
            return failed()
        if action == "cancel":
            # Consumed attempts no longer retain the handed-off token; a late
            # cancel cannot sign out a successfully claimed account.
            revoke(attempt, "cancelled")
            return response(status=204)
        now = timezone.now()
        if attempt.expires_at <= now:
            revoke(attempt, "expired")
        if attempt.state in {"consumed", "expired", "cancelled"}:
            return response(status=410)
        if attempt.state in {"created", "pending"}:
            if attempt.next_poll_at and now < attempt.next_poll_at:
                return failed(429)
            attempt.next_poll_at = now + timedelta(seconds=5)
            attempt.save(update_fields=["next_poll_at"])
            return response(status=202)
        if attempt.state == "error":
            error = attempt.error
            revoke(attempt, "consumed")
            return (
                failed(429)
                if error == "rate_limited"
                else response({"code": error}, 400)
            )
        session = SessionStore(attempt.session_key)
        if (
            not attempt.user
            or not attempt.user.is_active
            or not session.exists(attempt.session_key)
            or session.get(HANDOFF_KEY) != str(attempt.pk)
        ):
            revoke(attempt, "consumed")
            return response({"code": "social_login_failed"}, 400)
        if (
            attempt.state == "ready"
            and not EmailAddress.objects.filter(
                user=attempt.user, primary=True, verified=True
            ).exists()
        ):
            revoke(attempt, "consumed")
            return response({"code": "social_login_failed"}, 400)
        session.pop(HANDOFF_KEY)
        session.set_expiry(settings.SESSION_COOKIE_AGE)
        session.save()
        token = session.session_key
        pending = attempt.state == "email"
        email = attempt.email
        # Detach before revocation so the claimed session survives cleanup.
        attempt.session_key = ""
        revoke(attempt, "consumed")
        body = {"meta": {"is_authenticated": not pending, "session_token": token}}
        if pending:
            body["data"] = {"pending": "signup", "email": email}
        return response(body, 401 if pending else 200)


@csrf_exempt
@require_POST
def poll(request):
    return native_attempt(request, "poll")


@csrf_exempt
@require_POST
def cancel(request):
    return native_attempt(request, "cancel")


@require_GET
def finish(request, client):
    if client == "ios":
        result = HttpResponse(status=302)
        result["Location"] = "clarify://auth/complete"
        return secure_response(result)
    return browser_page(request, "social/complete.html")
